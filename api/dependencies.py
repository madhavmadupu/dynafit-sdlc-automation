"""
api/dependencies.py
FastAPI dependencies including API key authentication, rate limiting, and Redis client access.
"""
from __future__ import annotations

import structlog
from fastapi import Depends, HTTPException, Security
from fastapi.security import APIKeyHeader

from core.config.settings import settings
from infrastructure.storage.redis_client import redis_client
from infrastructure.storage.postgres_client import postgres_client

log = structlog.get_logger()

X_API_KEY = APIKeyHeader(name="X-API-Key", auto_error=True)


async def verify_api_key(api_key: str = Security(X_API_KEY)) -> str:
    """Validate API key and apply strictly enforced Redis rate-limiting."""
    if api_key != settings.API_KEY:
        log.warning("auth.invalid_api_key", provided_key=f"*{api_key[-4:]}")
        raise HTTPException(status_code=403, detail="Invalid API Key")

    from datetime import datetime
    window = datetime.utcnow().strftime("%Y-%m-%d-%H")
    
    count = await redis_client.increment_rate_limit(
        api_key=api_key,
        window=window,
        max_value=settings.API_RATE_LIMIT_PER_HOUR,
    )

    if count > settings.API_RATE_LIMIT_PER_HOUR:
        log.warning("auth.rate_limit_exceeded", api_key=f"*{api_key[-4:]}", window=window)
        raise HTTPException(status_code=429, detail="Hourly rate limit exceeded")

    return api_key
