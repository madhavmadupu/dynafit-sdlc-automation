"""
api/server.py
FastAPI application entrypoint.
Handles app lifecycle (startup/shutdown) and router registration.
"""
from __future__ import annotations

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import router
from core.config.settings import settings
from infrastructure.storage.postgres_client import postgres_client
from infrastructure.storage.redis_client import redis_client
from infrastructure.vector_db.qdrant_client import qdrant_client
from infrastructure.vector_db.pgvector_client import pgvector_client
from infrastructure.llm.client import http_client as llm_http_client

log = structlog.get_logger()


def create_app() -> FastAPI:
    """Standard FastAPI factory function."""
    
    app = FastAPI(
        title="DYNAFIT RFE",
        description="D365 Requirement Fitment Engine",
        version="1.0.0",
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(router, prefix="/api/v1")

    @app.on_event("startup")
    async def startup_event() -> None:
        log.info("app.startup_init")
        
        # Initialize connections
        await redis_client.connect()
        # Ensure LLM httpx client is warm
        _ = llm_http_client
        # Fast health checks
        try:
            await qdrant_client._client.client.get_collections()
        except Exception as e:
            log.warning("startup.qdrant_unavailable", error=str(e))
        
        log.info("app.startup_complete")

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        log.info("app.shutdown_start")
        await redis_client.disconnect()
        # postgres_client teardown (asyncpg connection pool)
        if postgres_client._pool:
            await postgres_client._pool.close()
        # pgvector_client teardown
        if pgvector_client._pool:
            await pgvector_client._pool.close()
            
        await llm_http_client.aclose()
        log.info("app.shutdown_complete")

    @app.get("/health")
    async def health_check() -> dict:
        """Lightweight health check endpoint."""
        return {
            "status": "ok",
            "kb_version": settings.KB_VERSION,
        }

    return app
