"""Durabl — Redis ulanish pooli (navbat, lease, cache, pub/sub uchun yagona manba).

`queue_service`, `cache_service`, `idempotency_service`, `rate_limit` middleware
va barcha worker'lar Redis'ni FAQAT shu modul orqali oladi.

Testlarda `settings.REDIS_FAKE = True` qilinsa `fakeredis` ishlatiladi —
haqiqiy Redis serveri kerak bo'lmaydi.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from redis.asyncio import Redis
from redis.asyncio.client import Pipeline
from redis.exceptions import RedisError

from app.config import settings
from app.exceptions import QueueError

logger = logging.getLogger(__name__)

_redis: Redis | None = None


def _build_client() -> Redis:
    """Sozlamaga qarab haqiqiy yoki fake Redis klientini yaratadi."""
    if settings.REDIS_FAKE:
        try:
            import fakeredis.aioredis
        except ImportError as exc:  # pragma: no cover
            raise QueueError(
                "REDIS_FAKE=True, lekin `fakeredis` o'rnatilmagan (`pip install fakeredis`)"
            ) from exc
        logger.warning("fakeredis ishlatilmoqda — faqat test muhiti uchun")
        return fakeredis.aioredis.FakeRedis(decode_responses=True)

    return Redis.from_url(
        settings.REDIS_URL,
        max_connections=settings.REDIS_MAX_CONNECTIONS,
        socket_timeout=settings.REDIS_SOCKET_TIMEOUT,
        socket_connect_timeout=settings.REDIS_SOCKET_CONNECT_TIMEOUT,
        socket_keepalive=True,
        health_check_interval=30,
        # Barcha qiymatlar `str` sifatida qaytadi — JSON bilan ishlash qulay
        decode_responses=True,
    )


def get_redis() -> Redis:
    """Global Redis klienti (ilk chaqiruvda yaratiladi)."""
    global _redis
    if _redis is None:
        _redis = _build_client()
    return _redis


def set_redis(client: Redis | None) -> None:
    """Testlar uchun: klientni almashtirish."""
    global _redis
    _redis = client


async def get_redis_dependency() -> Redis:
    """FastAPI dependency ko'rinishi."""
    return get_redis()


@asynccontextmanager
async def redis_pipeline(*, transaction: bool = True) -> AsyncIterator[Pipeline]:
    """Atomar bir nechta buyruq uchun pipeline.

    Misol:
        async with redis_pipeline() as pipe:
            pipe.rpush(key, value)
            pipe.expire(key, 60)
    """
    client = get_redis()
    async with client.pipeline(transaction=transaction) as pipe:
        yield pipe
        await pipe.execute()


async def close_redis() -> None:
    """Ulanishni yopadi (ilova to'xtaganda)."""
    global _redis
    if _redis is not None:
        try:
            await _redis.aclose()
        except Exception as exc:  # pragma: no cover
            logger.warning("Redis yopishda xato: %s", exc)
        logger.info("Redis ulanishi yopildi")
    _redis = None


async def check_redis_health() -> bool:
    """Healthcheck — Redis PING'ga javob beradimi."""
    try:
        return bool(await get_redis().ping())
    except RedisError as exc:  # pragma: no cover - infratuzilma xatosi
        logger.warning("Redis healthcheck muvaffaqiyatsiz: %s", exc)
        return False


async def redis_info() -> dict[str, Any]:
    """Admin paneli uchun Redis holati."""
    try:
        info = await get_redis().info()
        return {
            "connected": True,
            "version": info.get("redis_version"),
            "used_memory_human": info.get("used_memory_human"),
            "connected_clients": info.get("connected_clients"),
            "uptime_seconds": info.get("uptime_in_seconds"),
        }
    except RedisError as exc:
        return {"connected": False, "error": str(exc)}


__all__ = [
    "check_redis_health",
    "close_redis",
    "get_redis",
    "get_redis_dependency",
    "redis_info",
    "redis_pipeline",
    "set_redis",
]
