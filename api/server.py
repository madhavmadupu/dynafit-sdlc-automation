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
from infrastructure.vector_db.pgvector_client import pgvector_client
from infrastructure.vector_db.qdrant_client import qdrant_client

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

    @app.get("/")
    async def root():
        from fastapi.responses import RedirectResponse

        return RedirectResponse(url="/docs")

    @app.on_event("startup")
    async def startup_event() -> None:
        log.info("app.startup_init")

        # Fast health checks
        try:
            await qdrant_client._client.get_collections()
        except Exception as e:
            log.warning("startup.qdrant_unavailable", error=str(e))

        log.info("app.startup_complete")

    @app.on_event("shutdown")
    async def shutdown_event() -> None:
        log.info("app.shutdown_start")
        await redis_client.close()
        # postgres_client teardown (asyncpg connection pool)
        if hasattr(postgres_client, "_engine"):
            await postgres_client._engine.dispose()
        # pgvector_client teardown
        if hasattr(pgvector_client, "_engine"):
            await pgvector_client._engine.dispose()

        log.info("app.shutdown_complete")

    @app.get("/health")
    async def health_check() -> dict:
        """Lightweight health check endpoint."""
        return {
            "status": "ok",
            "kb_version": settings.KB_VERSION,
        }

    return app
