"""
infrastructure/storage/redis_client.py
Redis client for RetrievalContext caching and rate limiting.
TTL: 24 hours. Key: "retrieval:{atom_hash}:{kb_version}"
"""

from __future__ import annotations

import redis.asyncio as aioredis
import structlog

from core.config.settings import settings
from core.schemas.retrieval_context import RetrievalContext

log = structlog.get_logger()


class DynafitRedisClient:
    """
    Redis operations for DYNAFIT.

    Uses:
    1. RetrievalContext caching — avoids redundant Qdrant/pgvector calls on repeat runs
    2. Rate limit counters for API endpoints

    Key naming convention:
    - Cache: "retrieval:{atom_hash}:{kb_version}"
    - Rate limit: "ratelimit:{api_key}:{window}"

    Redis failures are SOFT — pipeline continues without cache.
    Never use Redis for persistent data — PostgreSQL only.
    """

    def __init__(self) -> None:
        self._client: aioredis.Redis = aioredis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=5,
        )

    def _cache_key(self, atom_hash: str, kb_version: str) -> str:
        """Generate consistent cache key."""
        return f"retrieval:{atom_hash}:{kb_version}"

    async def get_retrieval_context(
        self, atom_hash: str, kb_version: str
    ) -> RetrievalContext | None:
        """
        Retrieve a cached RetrievalContext.

        Args:
            atom_hash: SHA256 of the requirement atom's normalized text
            kb_version: Current KB version (cache key includes version for invalidation)

        Returns:
            RetrievalContext if cached, None on cache miss or error.
        """
        key = self._cache_key(atom_hash, kb_version)
        try:
            data = await self._client.get(key)
            if data:
                log.debug("redis_cache_hit", atom_hash=atom_hash[:8])
                return RetrievalContext.model_validate_json(data)
            return None
        except Exception as e:
            log.warning("redis_get_failed", key=key, error=str(e))
            return None

    async def set_retrieval_context(
        self,
        context: RetrievalContext,
        kb_version: str,
        ttl: int | None = None,
    ) -> None:
        """
        Cache a RetrievalContext.

        Args:
            context: The assembled RetrievalContext to cache
            kb_version: Current KB version
            ttl: TTL in seconds (defaults to settings.RETRIEVAL_CACHE_TTL_SEC = 86400)
        """
        if ttl is None:
            ttl = settings.RETRIEVAL_CACHE_TTL_SEC

        key = self._cache_key(context.atom_hash, kb_version)
        try:
            await self._client.setex(key, ttl, context.model_dump_json())
            log.debug("redis_cache_set", atom_hash=context.atom_hash[:8], ttl=ttl)
        except Exception as e:
            log.warning("redis_set_failed", key=key, error=str(e))

    async def increment_rate_limit(self, api_key: str, window: str, max_value: int) -> int:
        """
        Increment rate limit counter for an API key.

        Args:
            api_key: The API key being rate-limited
            window: Time window string (e.g., "2024-01-15-14" for hourly)
            max_value: Max allowed value before rejecting

        Returns:
            Current count after increment. Caller checks if > max_value.
        """
        key = f"ratelimit:{api_key}:{window}"
        try:
            count = await self._client.incr(key)
            if count == 1:
                # First request in this window — set expiry
                await self._client.expire(key, 3600)  # 1-hour TTL
            return count
        except Exception as e:
            log.warning("redis_rate_limit_failed", error=str(e))
            return 0  # On error, allow the request through

    async def health_check(self) -> bool:
        """Ping Redis and confirm connectivity."""
        try:
            await self._client.ping()
            log.debug("redis.health_check_ok")
            return True
        except Exception as e:
            log.error("redis.health_check_failed", error=str(e))
            return False

    async def close(self) -> None:
        """Gracefully close Redis connection."""
        await self._client.aclose()


# Module-level singleton
redis_client = DynafitRedisClient()
