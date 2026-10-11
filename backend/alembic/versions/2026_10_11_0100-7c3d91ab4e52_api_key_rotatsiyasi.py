"""API kalit rotatsiyasi — to'rtinchi migratsiya.

`api_keys` jadvaliga uch ustun:

* `previous_key_hash` — rotatsiyadan keyin eski kalitning hashi;
* `previous_key_expires_at` — eski kalit qachongacha ishlaydi;
* `rotated_at` — oxirgi rotatsiya vaqti (audit va UI).

## Nega eski kalit saqlanadi

Rotatsiya "joyida almashtirish": `id`, nom va huquqlar saqlanadi,
faqat kalit qiymati o'zgaradi. Eski kalit darhol o'lsa, mijozning CI,
server va lokal muhiti BIR VAQTDA uziladi — ya'ni rotatsiya
"xavfsizlik amali" emas, "avariya" bo'lib qolardi.

Shuning uchun eski hash saqlanadi va unga `API_KEY_ROTATION_GRACE_HOURS`
(24 soat) beriladi. `AuthService.resolve_api_key()` grace oynasida
ikki hashni ham qabul qiladi.

Agar kalit HAQIQATAN sizib ketgan bo'lsa, rotatsiya emas, bekor qilish
(`DELETE /api-keys/{id}`) ishlatiladi — u grace bermaydi.

## Indeks NEGA qo'shiladi

`resolve_api_key()` kalit topilmasa `previous_key_hash` bo'yicha
IKKINCHI so'rov qiladi. Indekssiz bu to'liq jadval skaneri bo'lardi —
va u HAR yaroqsiz kalit so'rovida ishlaydi, ya'ni brute-force
urinishlari DB'ni yuklab qo'yardi.

Indeks `unique` EMAS: nazariy jihatdan ikki kalit bir xil eski hashga
ega bo'lishi mumkin emas, lekin `unique` cheklov rotatsiyani
`IntegrityError` bilan yiqitish xavfini qo'shadi va foyda bermaydi.

Revision ID: 7c3d91ab4e52
Revises: 502a82925e5c
Yaratilgan: 2026-10-11 01:00:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Alembic identifikatorlari
revision: str = "7c3d91ab4e52"
down_revision: str | None = "502a82925e5c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Sxemani oldinga siljitadi."""
    op.add_column("api_keys", sa.Column("previous_key_hash", sa.String(length=64), nullable=True))
    op.add_column(
        "api_keys",
        sa.Column("previous_key_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("api_keys", sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        op.f("ix_api_keys_previous_key_hash"),
        "api_keys",
        ["previous_key_hash"],
    )


def downgrade() -> None:
    """O'zgarishni orqaga qaytaradi.

    Grace oynasidagi eski kalitlar ishlashdan to'xtaydi — bu kutilgan:
    orqaga qaytarish rotatsiya imkoniyatini butunlay olib tashlaydi.
    """
    op.drop_index(op.f("ix_api_keys_previous_key_hash"), table_name="api_keys")
    op.drop_column("api_keys", "rotated_at")
    op.drop_column("api_keys", "previous_key_expires_at")
    op.drop_column("api_keys", "previous_key_hash")


__all__ = [
    "branch_labels",
    "depends_on",
    "down_revision",
    "downgrade",
    "revision",
    "upgrade",
]
