"""Durabl — async SQLAlchemy engine va sessiya boshqaruvi.

Ikki xil ishlatish usuli bor:

1. **FastAPI dependency** — `get_db()`: so'rov oxirida sessiya avtomatik yopiladi.
2. **Worker/skript** — `session_scope()`: `async with` ichida tranzaksiya
   muvaffaqiyatli tugasa commit, xato bo'lsa rollback qiladi.

Muhim: bu modul `app.models`ni modul darajasida import QILMAYDI
(aylanma importni oldini olish uchun) — faqat funksiya ichida.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from app.config import settings
from app.exceptions import DatabaseError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine (lazy singleton)
# ---------------------------------------------------------------------------

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _engine_kwargs() -> dict[str, Any]:
    """Drayverga qarab engine parametrlarini tanlaydi."""
    kwargs: dict[str, Any] = {
        "echo": settings.DB_ECHO,
        "future": True,
        "pool_pre_ping": True,
    }

    if settings.is_sqlite:
        # SQLite (testlar): in-memory DB bir ulanishda qolishi uchun StaticPool
        if ":memory:" in settings.DATABASE_URL:
            kwargs["poolclass"] = StaticPool
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs["poolclass"] = NullPool
        kwargs.pop("pool_pre_ping", None)
        return kwargs

    # PostgreSQL (asyncpg)
    kwargs.update(
        {
            "pool_size": settings.DB_POOL_SIZE,
            "max_overflow": settings.DB_MAX_OVERFLOW,
            "pool_timeout": settings.DB_POOL_TIMEOUT,
            "pool_recycle": settings.DB_POOL_RECYCLE,
        }
    )
    # asyncpg prepared-statement keshi PgBouncer bilan muammo qiladi — o'chiramiz
    kwargs["connect_args"] = {
        "statement_cache_size": 0,
        "server_settings": {
            "application_name": f"{settings.APP_NAME.lower()}-{settings.ENV}",
            "jit": "off",
        },
    }
    return kwargs


def create_engine() -> AsyncEngine:
    """Yangi engine yaratadi (odatda `get_engine()` ishlatiladi)."""
    engine = create_async_engine(settings.DATABASE_URL, **_engine_kwargs())

    if settings.is_sqlite:
        # SQLite'da foreign key'lar sukut bo'yicha o'chirilgan — yoqamiz
        @event.listens_for(engine.sync_engine, "connect")
        def _enable_sqlite_fk(dbapi_connection: Any, _record: Any) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def get_engine() -> AsyncEngine:
    """Global engine (ilk chaqiruvda yaratiladi)."""
    global _engine
    if _engine is None:
        _engine = create_engine()
        logger.debug("DB engine yaratildi: %s", settings.DATABASE_URL.split("@")[-1])
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Global sessiya fabrikasi."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,  # commit'dan keyin obyektlar o'qiladigan holda qoladi
            autoflush=False,
            autocommit=False,
        )
    return _sessionmaker


def set_engine(engine: AsyncEngine | None) -> None:
    """Testlar uchun: engine'ni almashtirish (sessionmaker ham tiklanadi)."""
    global _engine, _sessionmaker
    _engine = engine
    _sessionmaker = None


# ---------------------------------------------------------------------------
# Sessiya olish usullari
# ---------------------------------------------------------------------------


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency — har so'rov uchun bitta sessiya.

    Commit mas'uliyati service qatlamida: biz faqat xato bo'lsa rollback
    qilamiz va sessiyani yopamiz.
    """
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Worker va skriptlar uchun tranzaksiya konteksti.

    Misol:
        async with session_scope() as session:
            await repo.create(session, ...)
        # shu yerda avtomatik commit bo'ladi
    """
    session_factory = get_sessionmaker()
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ---------------------------------------------------------------------------
# Hayot sikli
# ---------------------------------------------------------------------------


async def init_db(*, create_all: bool = False) -> None:
    """Ulanishni tekshiradi; `create_all=True` bo'lsa jadvallarni yaratadi.

    Production'da jadvallar Alembic migratsiyalari bilan yaratiladi —
    `create_all` faqat test va tezkor development uchun.
    """
    engine = get_engine()
    # Barcha modellarni import qilib metadata'ga ro'yxatdan o'tkazamiz
    from app.models import Base  # aylanma importni oldini olish uchun funksiya ichida

    async with engine.begin() as conn:
        if create_all:
            await conn.run_sync(Base.metadata.create_all)
        else:
            await conn.execute(text("SELECT 1"))
    logger.info("DB ulanishi tayyor (create_all=%s)", create_all)


async def drop_db() -> None:
    """Barcha jadvallarni o'chiradi — FAQAT test muhitida."""
    if settings.is_production:
        raise DatabaseError("drop_db() production muhitida chaqirilishi mumkin emas")
    from app.models import Base

    async with get_engine().begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


async def close_db() -> None:
    """Engine'ni yopadi (ilova to'xtaganda)."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
        logger.info("DB engine yopildi")
    _engine = None
    _sessionmaker = None


async def check_db_health() -> bool:
    """Healthcheck uchun — DB javob beradimi."""
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover - infratuzilma xatosi
        logger.warning("DB healthcheck muvaffaqiyatsiz: %s", exc)
        return False


__all__ = [
    "check_db_health",
    "close_db",
    "create_engine",
    "drop_db",
    "get_db",
    "get_engine",
    "get_sessionmaker",
    "init_db",
    "session_scope",
    "set_engine",
]
