import json
from typing import Any

import structlog
from redis.asyncio import Redis

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)

# TTL constants (seconds) used across all tools
TTL_QUOTE: int = 60          # 1 minute
TTL_NEWS: int = 1_800        # 30 minutes
TTL_FINANCIALS: int = 86_400  # 24 hours
TTL_FILINGS: int = 0         # permanent (no expiry)


class CacheClient:
    def __init__(self) -> None:
        self._redis: Redis | None = None

    def set_client(self, client: Redis) -> None:
        """Inject the Redis connection from the server lifespan."""
        self._redis = client

    def _require_client(self) -> Redis:
        if self._redis is None:
            raise RuntimeError("CacheClient has no Redis connection. Call set_client() first.")
        return self._redis

    async def get(self, key: str) -> Any | None:
        """Return deserialised value or None on cache miss."""
        client = self._require_client()
        raw = await client.get(key)
        if raw is None:
            logger.debug("Cache miss", key=key)
            return None
        logger.debug("Cache hit", key=key)
        return json.loads(raw)

    async def set(self, key: str, value: Any, ttl: int) -> None:
        """Serialise value to JSON and store with TTL. ttl=0 means no expiry."""
        client = self._require_client()
        serialised = json.dumps(value)
        if ttl > 0:
            await client.setex(key, ttl, serialised)
        else:
            await client.set(key, serialised)
        logger.debug("Cache set", key=key, ttl=ttl)

    async def delete(self, key: str) -> None:
        """Remove a key from the cache."""
        client = self._require_client()
        await client.delete(key)
        logger.debug("Cache delete", key=key)


cache = CacheClient()
