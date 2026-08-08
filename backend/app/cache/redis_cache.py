"""Redis-backed cache for expensive geospatial aggregations.

Why Redis is part of the architecture rather than decoration:

* Zone and road GeoJSON payloads are the product of PostGIS simplification and
  spatial joins. They change only when ingestion runs, but are requested on
  every map pan. Caching them by viewport is the difference between a
  responsive command centre and a slow one.
* From Phase 2 the same instance is the broker for scheduled ingestion jobs.

The cache is optional by design: when ``REDIS_ENABLED=false`` every call becomes
a no-op miss and the application still works, just slower.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import redis.asyncio as aioredis
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: Redis | None = None


def init_cache(settings: Settings) -> Redis | None:
    """Create the shared Redis client, or return None when disabled."""
    global _client
    if not settings.redis_enabled:
        logger.info("cache_disabled", reason="REDIS_ENABLED=false")
        return None
    if _client is None:
        _client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=settings.redis_health_timeout_seconds,
            socket_timeout=settings.redis_health_timeout_seconds,
        )
    return _client


def get_cache() -> Redis | None:
    return _client


async def close_cache() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
    _client = None


class CacheService:
    """Thin JSON cache facade.

    Cache failures are logged and swallowed: a broken cache must never turn a
    working read into an API error.
    """

    def __init__(self, client: Redis | None, *, default_ttl: int) -> None:
        self._client = client
        self._default_ttl = default_ttl

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def ping(self, *, timeout: float) -> None:
        """Raise if the cache is unreachable. Used by the readiness probe."""
        if self._client is None:
            raise RuntimeError("Cache is disabled.")
        await asyncio.wait_for(self._client.ping(), timeout=timeout)

    async def get_json(self, key: str) -> Any | None:
        if self._client is None:
            return None
        try:
            raw = await self._client.get(key)
        except Exception as exc:  # noqa: BLE001 - cache must degrade, not fail
            logger.warning("cache_get_failed", key=key, error=str(exc))
            return None
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("cache_corrupt_entry", key=key)
            return None

    async def set_json(self, key: str, value: Any, *, ttl: int | None = None) -> None:
        if self._client is None:
            return
        try:
            await self._client.set(key, json.dumps(value), ex=ttl or self._default_ttl)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache_set_failed", key=key, error=str(exc))

    async def invalidate_prefix(self, prefix: str) -> int:
        """Drop every key under a prefix. Called after an ingestion run."""
        if self._client is None:
            return 0
        removed = 0
        try:
            async for key in self._client.scan_iter(match=f"{prefix}*", count=500):
                removed += await self._client.delete(key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("cache_invalidate_failed", prefix=prefix, error=str(exc))
        return removed
