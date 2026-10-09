"""Durabl — Alembic muhiti (async SQLAlchemy bilan).

DB manzili `app.config.settings.DATABASE_URL` dan olinadi — `alembic.ini` dagi
`sqlalchemy.url` ataylab bo'sh qoldirilgan, shunda sozlama bitta joyda (.env) turadi.

`--autogenerate` to'g'ri ishlashi uchun `app.models` paketidagi BARCHA modellar
import qilinishi kerak — `app/models/__init__.py` shuni ta'minlaydi.
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# `backend/` katalogini sys.path'ga qo'shamiz (alembic ichidan `app` ni import qilish uchun)
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import settings  # noqa: E402
from app.models import Base  # noqa: E402  (barcha modellarni ro'yxatdan o'tkazadi)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Autogenerate shu metadata bilan solishtiradi
target_metadata = Base.metadata

# DB manzilini sozlamadan olamiz
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)


#: `Base.metadata` da ataylab yo'q bo'lgan, lekin DB'da MAVJUD indekslar.
#: `include_object()` ularni autogeneratsiyadan chiqaradi (sababi quyida).
AUTOGENERATE_IGNORED_INDEXES: frozenset[str] = frozenset(
    {"ix_jobs_tags_gin", "ix_dlq_unresolved"}
)


def include_object(
    obj: object,
    name: str | None,
    type_: str,
    reflected: bool,
    compare_to: object,
) -> bool:
    """Qaysi obyektlar migratsiyaga kirishini belgilaydi.

    Alembic'ning o'z `alembic_version` jadvalini va vaqtinchalik jadvallarni
    chetlab o'tadi.

    ## Nega ikki indeks AVTOGENERATSIYADAN chiqarilgan

    `ix_jobs_tags_gin` (GIN) va `ix_dlq_unresolved` (qisman indeks) ataylab
    `Base.metadata` da YO'Q: GIN SQLite'da mavjud emas, qisman indeks esa
    unda foyda bermaydi — modelga qo'shilsa SQLite testlari yiqilardi.
    Ularni FAQAT migratsiya yaratadi (`8fb11e62b45f`).

    Oqibati: PostgreSQL'ga qarshi `alembic revision --autogenerate` ularni
    "Detected removed index" deb belgilab `op.drop_index` taklif qilardi.
    Bu DRIFT EMAS, lekin e'tiborsiz commit qilinsa ikki optimizatsiya
    yo'qolardi (amalda bir marta yiqilgan ham). Shu sababli ikki nom shu
    yerda OCHIQ chetlab o'tiladi — batafsil tushuntirish
    `alembic/README.md` §7 da.
    """
    if type_ == "table" and name in {"alembic_version"}:
        return False
    if type_ == "index" and name in AUTOGENERATE_IGNORED_INDEXES:
        return False
    return True


def process_revision_directives(context_: object, revision: object, directives: list) -> None:
    """O'zgarish bo'lmasa bo'sh migratsiya fayli yaratilmasin."""
    if getattr(config.cmd_opts, "autogenerate", False) and directives:
        script = directives[0]
        if script.upgrade_ops is not None and script.upgrade_ops.is_empty():
            directives[:] = []
            print("O'zgarish topilmadi — migratsiya yaratilmadi.")


_COMMON_CONTEXT_KWARGS = {
    "target_metadata": target_metadata,
    "include_object": include_object,
    "process_revision_directives": process_revision_directives,
    # Ustun turi o'zgarishini ham aniqlaydi
    "compare_type": True,
    # Standart qiymat (server_default) o'zgarishini aniqlaydi
    "compare_server_default": True,
    # SQLite'da ALTER TABLE cheklangan — "batch" rejimi kerak
    "render_as_batch": settings.is_sqlite,
}


def run_migrations_offline() -> None:
    """Oflayn rejim — SQL skriptini faylga chiqaradi (`alembic upgrade head --sql`)."""
    context.configure(
        url=settings.DATABASE_URL,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **_COMMON_CONTEXT_KWARGS,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Sinxron ulanishda migratsiyalarni bajaradi (async engine ichidan chaqiriladi)."""
    context.configure(connection=connection, **_COMMON_CONTEXT_KWARGS)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Async engine yaratib migratsiyalarni bajaradi."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Onlayn rejim — haqiqiy DB'ga ulanadi."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
