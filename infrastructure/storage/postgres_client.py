"""
infrastructure/storage/postgres_client.py
PostgreSQL client for audit trail, run history, and run status management.
Uses asyncpg via SQLAlchemy async engine.
"""
from __future__ import annotations

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from core.config.settings import settings
from core.schemas.enums import RunStatus

log = structlog.get_logger()


class DynafitPostgresClient:
    """
    PostgreSQL client for pipeline run management and audit trail.

    Tables:
    - dynafit_runs: Run metadata, status, timestamps
    - audit_trail: Per-decision audit entries
    - consultant_overrides: Override history with reasons
    - historical_fitments: Shared with pgvector_client for fitment history

    All writes are transactional. Pool: min=5 connections.
    """

    def __init__(self) -> None:
        self._engine = create_async_engine(
            settings.POSTGRES_URL,
            pool_size=settings.POSTGRES_POOL_MIN,
            max_overflow=settings.POSTGRES_POOL_MAX - settings.POSTGRES_POOL_MIN,
            echo=False,
        )
        self._session_factory = sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def create_run(self, run_id: str, source_files: list[str]) -> None:
        """Create a new pipeline run record."""
        try:
            async with self._session_factory() as session:
                await session.execute(
                    text("""
                        INSERT INTO dynafit_runs (run_id, status, source_files, created_at)
                        VALUES (:run_id, :status, :source_files, NOW())
                        ON CONFLICT DO NOTHING
                    """),
                    {
                        "run_id": run_id,
                        "status": RunStatus.QUEUED.value,
                        "source_files": ",".join(source_files),
                    },
                )
                await session.commit()
        except Exception as e:
            log.error("postgres.create_run_failed", run_id=run_id, error=str(e))
            raise

    async def update_run_status(self, run_id: str, status: RunStatus) -> None:
        """Update the status of a pipeline run."""
        try:
            async with self._session_factory() as session:
                await session.execute(
                    text("""
                        UPDATE dynafit_runs
                        SET status = :status, updated_at = NOW()
                        WHERE run_id = :run_id
                    """),
                    {"run_id": run_id, "status": status.value},
                )
                await session.commit()
                log.info("postgres.run_status_updated", run_id=run_id, status=status.value)
        except Exception as e:
            log.error("postgres.update_run_status_failed", run_id=run_id, error=str(e))
            raise

    async def write_audit_entry(
        self,
        *,
        run_id: str,
        atom_id: str,
        phase: str,
        action: str,
        verdict: str | None,
        actor: str,
        metadata: dict,
    ) -> None:
        """Write a single audit trail entry."""
        try:
            async with self._session_factory() as session:
                await session.execute(
                    text("""
                        INSERT INTO audit_trail
                            (run_id, atom_id, phase, action, verdict, actor, metadata, created_at)
                        VALUES
                            (:run_id, :atom_id, :phase, :action, :verdict, :actor, :metadata::jsonb, NOW())
                    """),
                    {
                        "run_id": run_id,
                        "atom_id": atom_id,
                        "phase": phase,
                        "action": action,
                        "verdict": verdict,
                        "actor": actor,
                        "metadata": str(metadata),
                    },
                )
                await session.commit()
        except Exception as e:
            log.error("postgres.write_audit_failed", run_id=run_id, error=str(e))
            raise

    async def write_override(
        self,
        *,
        run_id: str,
        atom_id: str,
        original_verdict: str,
        override_verdict: str,
        reason: str,
        reviewed_by: str,
    ) -> None:
        """Record a consultant override decision."""
        try:
            async with self._session_factory() as session:
                await session.execute(
                    text("""
                        INSERT INTO consultant_overrides
                            (run_id, atom_id, original_verdict, override_verdict,
                             reason, reviewed_by, reviewed_at)
                        VALUES
                            (:run_id, :atom_id, :original_verdict, :override_verdict,
                             :reason, :reviewed_by, NOW())
                    """),
                    {
                        "run_id": run_id,
                        "atom_id": atom_id,
                        "original_verdict": original_verdict,
                        "override_verdict": override_verdict,
                        "reason": reason,
                        "reviewed_by": reviewed_by,
                    },
                )
                await session.commit()
                log.info(
                    "override_written",
                    run_id=run_id,
                    atom_id=atom_id,
                    override_verdict=override_verdict,
                )
        except Exception as e:
            log.error("postgres.write_override_failed", run_id=run_id, error=str(e))
            raise

    async def health_check(self) -> bool:
        """Verify PostgreSQL connectivity."""
        try:
            async with self._session_factory() as session:
                await session.execute(text("SELECT 1"))
            log.debug("postgres.health_check_ok")
            return True
        except Exception as e:
            log.error("postgres.health_check_failed", error=str(e))
            return False


# Module-level singleton
postgres_client = DynafitPostgresClient()
