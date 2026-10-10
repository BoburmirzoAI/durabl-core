"""Durabl — migratsiya va modellar orasidagi drift tekshiruvi (CI darvozasi).

## Nega bu skript kerak

Testlar sxemani **modellardan** yasaydi (`init_db(create_all=True)`), ya'ni
migratsiya fayllariga umuman tegmaydi. Oqibati: kimdir modelga ustun
qo'shib migratsiya yozmasa, **barcha testlar o'tadi**, lekin production'da
`alembic upgrade` dan keyin ilova `UndefinedColumn` bilan yiqiladi.

Bu skript ikkisini yuzma-yuz qo'yadi: migratsiyalar qo'llangan DB'ning
HAQIQIY sxemasini `Base.metadata` bilan solishtiradi. Farq bo'lsa — demak
migratsiya yozilmagan yoki to'liq emas.

## Ma'lum va ATAYLAB qoldirilgan farqlar

Boshlang'ich migratsiyada ikki PostgreSQL optimizatsiyasi bor, ular
`Base.metadata` da ATAYLAB yo'q:

* `ix_jobs_tags_gin` — GIN indeks (SQLite'da mavjud emas);
* `ix_dlq_unresolved` — qisman indeks (SQLite'da foyda bermaydi).

Modelga qo'shilsa SQLite testlari yiqilardi, shuning uchun ular faqat
PostgreSQL'da, dialekt tekshiruvi bilan yaratiladi. Alembic esa ularni
"metadata'da yo'q, DB'da bor" deb `remove_index` taklif qiladi. Bu DRIFT
EMAS, shuning uchun `_EXPECTED_EXTRA_INDEXES` ro'yxati bilan chiqarib
tashlanadi.

**Diqqat:** bu ro'yxatga yangi nom qo'shish — oxirgi chora. Har bir nom
"bu indeks ataylab metadata'dan tashqarida" degan ma'noni bildiradi va
sababi shu yerda yozilishi kerak.

## `server_default` shovqini haqida

SQLite `now()` ni `CURRENT_TIMESTAMP` deb qaytaradi, ya'ni qiymat bir xil,
matn boshqa. Alembic bunday farqni `modify_default` deb belgilaydi. Bu ham
drift emas — shuning uchun faqat SQLite dialektida e'tiborsiz qoldiriladi.
PostgreSQL'da esa `modify_default` HAQIQIY farq bo'ladi va o'tkazilmaydi.

## Ishlatish

    DATABASE_URL=postgresql+asyncpg://... python scripts/check_migration_drift.py

Chiqish kodi: 0 — drift yo'q, 1 — drift topildi (tafsiloti chiqariladi).
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any, Final

# `backend/` katalogini sys.path'ga qo'shamiz: skript `python
# scripts/check_migration_drift.py` ko'rinishida chaqiriladi, bunda `app`
# paketi avtomatik topilmaydi. Shu sababli `app` importlari ataylab shu
# qatordan KEYIN turadi (`scripts/sandbox_check.py` bilan ayni yondashuv).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.config import settings
from app.models import Base
from sqlalchemy import Connection
from sqlalchemy.ext.asyncio import create_async_engine

#: `Base.metadata` da ATAYLAB yo'q, lekin migratsiyada bor indekslar.
#: Sababi modul docstring'ida.
_EXPECTED_EXTRA_INDEXES: Final[frozenset[str]] = frozenset(
    {
        "ix_jobs_tags_gin",
        "ix_dlq_unresolved",
    }
)


def _diff(connection: Connection) -> list[Any]:
    """DB sxemasi va `Base.metadata` orasidagi farqlar ro'yxati."""
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    return list(compare_metadata(context, Base.metadata))


def _index_name(entry: Any) -> str | None:
    """`remove_index` / `add_index` yozuvidan indeks nomini ajratadi."""
    if not isinstance(entry, tuple) or len(entry) < 2:
        return None
    return getattr(entry[1], "name", None)


def _is_ignorable(entry: Any, *, is_sqlite: bool) -> tuple[bool, str]:
    """Farq e'tiborsiz qoldirilishi mumkinmi va nega.

    Returns:
        `(e'tiborsizmi, sabab)` juftligi. Sabab chiqishda ko'rsatiladi —
        shunda "nega bu farq o'tkazib yuborildi?" savoliga javob bo'ladi.
    """
    if not isinstance(entry, tuple) or not entry:
        return False, ""

    kind = entry[0]

    if kind == "remove_index" and _index_name(entry) in _EXPECTED_EXTRA_INDEXES:
        return True, "ataylab metadata'dan tashqarida (dialektga xos indeks)"

    # SQLite `now()` ni `CURRENT_TIMESTAMP` deb o'qiydi — matn boshqa,
    # qiymat bir xil. PostgreSQL'da bu yengillik BERILMAYDI.
    if kind == "modify_default" and is_sqlite:
        return True, "SQLite server_default matn farqi (qiymat bir xil)"

    return False, ""


async def main() -> int:
    """Driftni tekshiradi va chiqish kodini qaytaradi."""
    is_sqlite = settings.is_sqlite
    engine = create_async_engine(settings.DATABASE_URL)
    try:
        async with engine.connect() as connection:
            differences = await connection.run_sync(_diff)
    finally:
        await engine.dispose()

    real: list[Any] = []
    ignored: list[tuple[Any, str]] = []
    for entry in differences:
        ignorable, reason = _is_ignorable(entry, is_sqlite=is_sqlite)
        if ignorable:
            ignored.append((entry, reason))
        else:
            real.append(entry)

    dialect = "SQLite" if is_sqlite else "PostgreSQL"
    print(f"Dialekt: {dialect}")
    print(f"Jami farq: {len(differences)} | e'tiborsiz: {len(ignored)} | haqiqiy: {len(real)}")

    for entry, reason in ignored:
        print(f"  [o'tkazildi] {entry} — {reason}")

    if not real:
        print("\nDRIFT YO'Q — migratsiya modellarga to'liq mos.")
        return 0

    print("\nDRIFT TOPILDI — model o'zgargan, lekin migratsiya yozilmagan:")
    for entry in real:
        print(f"  {entry}")
    print(
        "\nTuzatish: `alembic revision --autogenerate -m '...'` chaqirib, "
        "hosil bo'lgan faylni TEKSHIRIB commit qiling.\n"
        "Diqqat: autogenerate SQLite'ga qarshi chaqirilsa yolg'on "
        "`alter_column(server_default=...)` qatorlari chiqadi — ularni "
        "o'chirish kerak (tafsilot `4f521f5c9fbc` migratsiyasida)."
    )
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
