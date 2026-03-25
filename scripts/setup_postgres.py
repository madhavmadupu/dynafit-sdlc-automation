"""
scripts/setup_postgres.py
Idempotent schema creation script for Postgres (Audit trail + Pgvector).
Creates `dynafit_runs`, `pipeline_audit`, and `historical_fitments` tables.
Ensures the pgvector extension is enabled.
"""
from __future__ import annotations

import asyncio
import os
import sys

# Ensure project root is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncpg
import structlog
from urllib.parse import urlparse

from core.config.settings import settings

log = structlog.get_logger()

# Raw schema definitions
SCHEMA = """
-- 1. Pipeline Run Lifecycle
CREATE TABLE IF NOT EXISTS dynafit_runs (
    run_id UUID PRIMARY KEY,
    status VARCHAR(50) NOT NULL,
    source_files JSONB DEFAULT '[]',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. Audit Trail
CREATE TABLE IF NOT EXISTS pipeline_audit (
    id SERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES dynafit_runs(run_id) ON DELETE CASCADE,
    atom_id UUID NOT NULL,
    phase VARCHAR(50) NOT NULL,
    action VARCHAR(50) NOT NULL,
    verdict VARCHAR(50),
    actor VARCHAR(50) NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_audit_run_id ON pipeline_audit(run_id);
CREATE INDEX IF NOT EXISTS idx_audit_atom_id ON pipeline_audit(atom_id);

-- 3. Historical Fitments (requires pgvector)
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS historical_fitments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    atom_hash CHAR(64) NOT NULL,
    original_text TEXT NOT NULL,
    module VARCHAR(50) NOT NULL,
    verdict VARCHAR(50) NOT NULL,
    confidence FLOAT NOT NULL,
    rationale TEXT NOT NULL,
    matched_capability VARCHAR(255),
    wave_id VARCHAR(100) NOT NULL,
    embedding vector(1024),
    overridden_by_consultant BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_hist_hash ON historical_fitments(atom_hash);
CREATE INDEX IF NOT EXISTS idx_hist_module ON historical_fitments(module);

-- HNSW Index for fast vector similarity search (cosine distance)
CREATE INDEX IF NOT EXISTS idx_hist_vector ON historical_fitments USING hnsw (embedding vector_cosine_ops);
"""


async def run_migrations() -> None:
    uri = settings.POSTGRES_URL
    if not uri:
        log.error("setup.missing_pg_uri")
        sys.exit(1)

    # Some asyncpg DSN fixes for asyncpg parsing if needed
    if uri.startswith("postgresql+asyncpg://"):
        uri = uri.replace("postgresql+asyncpg://", "postgresql://")
    elif uri.startswith("postgresql://"):
        pass
        
    try:
        log.info("setup.connecting_postgres", dsn="***")
        conn = await asyncpg.connect(uri)
    except Exception as e:
        log.error("setup.postgres_connection_failed", error=str(e))
        sys.exit(1)

    try:
        log.info("setup.running_schema_migrations")
        await conn.execute(SCHEMA)
        log.info("setup.schema_applied_successfully")
    except Exception as e:
        log.error("setup.schema_migration_failed", error=str(e))
        sys.exit(1)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(run_migrations())
