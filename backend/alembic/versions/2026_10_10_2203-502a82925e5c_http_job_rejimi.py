"""HTTP job rejimi (`JobKind.HTTP`) — uchinchi migratsiya.

Nima o'zgaradi (faqat `jobs` jadvali):

* **5 yangi ustun**: `kind`, `target_url`, `http_method`,
  `http_headers`, `response_status`.
* **`code` endi `NULL` bo'lishi mumkin** — HTTP rejimidagi job'da kod
  yo'q, uning o'rniga `target_url` to'ldiriladi.
* **1 yangi indeks**: `ix_jobs_kind` — ro'yxatni rejim bo'yicha
  filtrlash uchun.

## Orqaga moslik

`kind` ustuni `server_default='code'` bilan qo'shiladi, ya'ni MAVJUD
barcha job'lar avtomatik `code` rejimiga tushadi va eski mijozlar
`kind` yubormasa ham xulq o'zgarmaydi.

## Nega `batch_alter_table` ishlatiladi (oldingi migratsiyadan farqli)

Ikkinchi migratsiyada (`4f521f5c9fbc`) faqat `CREATE TABLE` /
`ADD COLUMN` bor edi — ikkisi SQLite'da to'g'ridan-to'g'ri ishlaydi.
Bu yerda esa `code` ustunining `NOT NULL` cheklovi olib tashlanadi, va
SQLite `ALTER COLUMN` ni QO'LLAMAYDI — jadvalni qayta yasash kerak.
`batch_alter_table` aynan shuni qiladi: SQLite'da jadvalni nusxalab
qayta yasaydi, PostgreSQL'da esa oddiy `ALTER TABLE` chiqaradi.

## DIQQAT — `--autogenerate` shovqini

Bu migratsiya autogenerate bilan boshlangan, lekin SQLite'ga qarshi.
Alembic mavjud 12 jadvalning `created_at`/`updated_at`/boolean
ustunlari uchun yolg'on `alter_column(server_default=...)` taklif
qildi (SQLite `now()` ni `CURRENT_TIMESTAMP` deb o'qiydi — qiymat bir
xil, matn boshqa). Barcha shunday qatorlar QO'LDA O'CHIRILGAN.
Tafsilot `4f521f5c9fbc` migratsiyasining docstring'ida.

Revision ID: 502a82925e5c
Revises: 4f521f5c9fbc
Yaratilgan: 2026-10-10 22:03:00.000000+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Alembic identifikatorlari
revision: str = "502a82925e5c"
down_revision: str | None = "4f521f5c9fbc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `app.models.base.JSONType` ning DDL'dagi aynan o'zi.
_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

#: `JobKind` enum ustuni (`native_enum=False` -> VARCHAR).
_JOB_KIND = sa.Enum("code", "http", name="jobkind", native_enum=False, length=32)

#: `HttpMethod` enum ustuni. `HEAD`/`OPTIONS` ATAYLAB yo'q — ular tana
#: qaytarmaydi, ya'ni job natijasi har doim bo'sh bo'lardi.
_HTTP_METHOD = sa.Enum(
    "GET",
    "POST",
    "PUT",
    "PATCH",
    "DELETE",
    name="httpmethod",
    native_enum=False,
    length=16,
)


def upgrade() -> None:
    """Sxemani oldinga siljitadi."""
    with op.batch_alter_table("jobs", schema=None) as batch_op:
        # `server_default='code'` — mavjud qatorlar avtomatik to'ldiriladi,
        # shuning uchun `nullable=False` darhol qo'yilishi mumkin.
        batch_op.add_column(sa.Column("kind", _JOB_KIND, server_default="code", nullable=False))
        batch_op.add_column(sa.Column("target_url", sa.String(length=2048), nullable=True))
        batch_op.add_column(sa.Column("http_method", _HTTP_METHOD, nullable=True))
        batch_op.add_column(sa.Column("http_headers", _JSON, nullable=True))
        batch_op.add_column(sa.Column("response_status", sa.Integer(), nullable=True))
        # HTTP rejimida kod yo'q. "Kod yo'q bo'lsa URL bor" qoidasi DB
        # CHECK bilan emas, `JobCreate` sxemasida tekshiriladi: xato
        # xabari mijozga tushunarli bo'lishi kerak.
        batch_op.alter_column("code", existing_type=sa.TEXT(), nullable=True)
        batch_op.create_index(batch_op.f("ix_jobs_kind"), ["kind"], unique=False)


def downgrade() -> None:
    """O'zgarishni orqaga qaytaradi.

    DIQQAT: `code` ustuniga `NOT NULL` qaytarilganda HTTP rejimidagi
    job'lar (kodi bo'sh) cheklovni buzadi. Shuning uchun orqaga
    qaytarishdan OLDIN ular o'chiriladi — aks holda migratsiyaning o'zi
    yiqilardi va baza yarim holatda qolardi.
    """
    op.execute("DELETE FROM jobs WHERE kind = 'http'")

    with op.batch_alter_table("jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_jobs_kind"))
        batch_op.alter_column("code", existing_type=sa.TEXT(), nullable=False)
        batch_op.drop_column("response_status")
        batch_op.drop_column("http_headers")
        batch_op.drop_column("http_method")
        batch_op.drop_column("target_url")
        batch_op.drop_column("kind")


__all__ = [
    "branch_labels",
    "depends_on",
    "down_revision",
    "downgrade",
    "revision",
    "upgrade",
]
