"""Key/value cache with TTL. Redis when REDIS_URL works, otherwise an in-process dictionary."""

from __future__ import annotations

import logging
import time
from typing import Optional, Protocol

logger = logging.getLogger(__name__)


class Cache(Protocol):
    """What the app needs from a cache."""

    name: str

    async def get(self, key: str) -> Optional[str]:
        """Return the cached string or None."""

    async def set(self, key: str, value: str, ttl_seconds: float) -> None:
        """Store a string with a time to live."""

    async def delete(self, key: str) -> None:
        """Remove a key."""

    async def ping(self) -> bool:
        """Return True when the cache is reachable."""

    async def close(self) -> None:
        """Release resources."""


class MemoryCache:
    """Per-process TTL cache. Fine for one instance; use Redis to share between instances."""

    name = "memory"

    def __init__(self, max_entries: int = 2000):
        """Create an empty cache holding at most max_entries items."""
        self._data: dict[str, tuple[float, str]] = {}
        self._max = max_entries

    async def get(self, key: str) -> Optional[str]:
        """Return the value if present and not expired."""
        item = self._data.get(key)
        if item is None:
            return None
        expires_at, value = item
        if expires_at < time.monotonic():
            self._data.pop(key, None)
            return None
        return value

    async def set(self, key: str, value: str, ttl_seconds: float) -> None:
        """Store a value, evicting the oldest entries when full."""
        if len(self._data) >= self._max:
            for old_key in sorted(self._data, key=lambda k: self._data[k][0])[: max(1, self._max // 10)]:
                self._data.pop(old_key, None)
        self._data[key] = (time.monotonic() + ttl_seconds, value)

    async def delete(self, key: str) -> None:
        """Remove a key if present."""
        self._data.pop(key, None)

    async def ping(self) -> bool:
        """The in-memory cache is always reachable."""
        return True

    async def close(self) -> None:
        """Nothing to release."""


class RedisCache:
    """Redis backed cache. Any Redis error is logged and treated as a cache miss, never as a failure."""

    name = "redis"

    def __init__(self, client, prefix: str = "adsify:"):
        """Wrap an already created redis.asyncio client."""
        self._client = client
        self._prefix = prefix

    async def get(self, key: str) -> Optional[str]:
        """Read a key; return None on miss or error."""
        try:
            value = await self._client.get(self._prefix + key)
        except Exception as exc:
            logger.warning("redis get failed: %s", exc)
            return None
        if value is None:
            return None
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)

    async def set(self, key: str, value: str, ttl_seconds: float) -> None:
        """Write a key with expiry; ignore errors."""
        try:
            await self._client.set(self._prefix + key, value, ex=max(1, int(ttl_seconds)))
        except Exception as exc:
            logger.warning("redis set failed: %s", exc)

    async def delete(self, key: str) -> None:
        """Delete a key; ignore errors."""
        try:
            await self._client.delete(self._prefix + key)
        except Exception as exc:
            logger.warning("redis delete failed: %s", exc)

    async def ping(self) -> bool:
        """Return True when Redis answers PING."""
        try:
            return bool(await self._client.ping())
        except Exception:
            return False

    async def close(self) -> None:
        """Close the Redis connection."""
        try:
            await self._client.aclose()
        except Exception:
            pass


async def make_cache(redis_url: str) -> Cache:
    """Return a RedisCache if REDIS_URL is set and reachable, else a MemoryCache."""
    if not redis_url:
        return MemoryCache()
    try:
        import redis.asyncio as aioredis  # type: ignore[import-not-found]

        client = aioredis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        cache = RedisCache(client)
        if await cache.ping():
            logger.info("Using Redis cache")
            return cache
        logger.warning("REDIS_URL is set but Redis is unreachable; using in-memory cache")
    except ImportError:
        logger.warning("REDIS_URL is set but the redis package is not installed; using in-memory cache")
    except Exception as exc:
        logger.warning("Could not start Redis cache (%s); using in-memory cache", exc)
    return MemoryCache()
