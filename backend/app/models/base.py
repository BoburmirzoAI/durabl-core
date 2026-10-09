"""Durabl — SQLAlchemy bazaviy klass, mixinlar va umumiy ustun turlari.

Dizayn qarorlari:

* **UUID birlamchi kalit** — `sqlalchemy.Uuid` ishlatiladi: PostgreSQL'da
  tabiiy `uuid` turi, SQLite'da `CHAR(32)`. Shu tufayli testlar SQLite'da
  tez ishlaydi, production esa PostgreSQL'da.
* **JSON ustunlar** — PostgreSQL'da `JSONB` (indekslanadi), boshqa yerda `JSON`.
* **Enum ustunlar** — `native_enum=False`: VARCHAR + CHECK. Yangi enum qiymati
  qo'shilganda PostgreSQL `ALTER TYPE` migratsiyasi kerak bo'lmaydi.
* **Nomlash konvensiyasi** — Alembic `--autogenerate` barqaror nom bersin
  (aks holda cheklovlarni o'chirish migratsiyalari buziladi).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar, TypeVar

from sqlalchemy import (
    JSON,
    DateTime,
    MetaData,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from app.constants import StrEnum
from app.utils.time_utils import utcnow

# ---------------------------------------------------------------------------
# Umumiy ustun turlari
# ---------------------------------------------------------------------------

#: JSON ustun: PostgreSQL -> JSONB, qolganlari -> JSON
JSONType = JSON().with_variant(JSONB(astext_type=Text()), "postgresql")

#: UUID ustun turi (Python tomonida `uuid.UUID`)
UUIDType = Uuid(as_uuid=True)

#: Timezone-aware datetime
DateTimeTZ = DateTime(timezone=True)

_EnumT = TypeVar("_EnumT", bound=StrEnum)


def enum_column(enum_cls: type[_EnumT], *, length: int = 32) -> SAEnum:
    """Enum ustun turi: qiymatlar `.value` sifatida saqlanadi.

    `native_enum=False` — DDL'da `VARCHAR(n)` yasaladi (PostgreSQL `ENUM` turi
    EMAS), shuning uchun yangi holat qo'shish uchun `ALTER TYPE` migratsiyasi
    kerak bo'lmaydi. SQLAlchemy 2.x bu rejimda CHECK cheklovini ham yaratmaydi
    (`create_constraint=False` sukut bo'yicha), ya'ni qiymat to'g'riligi
    `validate_strings=True` orqali Python tomonida tekshiriladi. Bu ataylab
    tanlangan: holat mashinasi `JOB_STATUS_TRANSITIONS` bilan ilova qatlamida
    nazorat qilinadi, DB esa migratsiyaga moslashuvchan qoladi.
    """
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda cls: [member.value for member in cls],
        validate_strings=True,
    )


# ---------------------------------------------------------------------------
# Bazaviy deklarativ klass
# ---------------------------------------------------------------------------

#: Alembik barqaror nom bersin — indeks/cheklov nomlari shablonlari
NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_N_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Barcha modellarning bazaviy klassi."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)

    #: Python tipidan SQL turiga standart moslik
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        dict[str, Any]: JSONType,
        list[str]: JSONType,
        uuid.UUID: UUIDType,
        datetime: DateTimeTZ,
        str: String(255),
    }

    @declared_attr.directive
    def __tablename__(cls) -> str:  # noqa: N805
        """Klass nomidan jadval nomini yasaydi: `DlqEntry` -> `dlq_entries`.

        Modelda `__tablename__` qo'lda berilsa, u ustun turadi.
        """
        name = cls.__name__
        snake: list[str] = []
        for index, char in enumerate(name):
            if char.isupper() and index > 0:
                snake.append("_")
            snake.append(char.lower())
        base = "".join(snake)
        # Oddiy pluralizatsiya
        if base.endswith("y") and not base.endswith(("ay", "ey", "oy", "uy")):
            return f"{base[:-1]}ies"
        if base.endswith(("s", "x", "z", "ch", "sh")):
            return f"{base}es"
        return f"{base}s"

    def to_dict(self, *, exclude: set[str] | None = None) -> dict[str, Any]:
        """Modelni lug'atga aylantiradi (debug va log uchun)."""
        skip = exclude or set()
        result: dict[str, Any] = {}
        for column in self.__table__.columns:
            if column.name in skip:
                continue
            value = getattr(self, column.name, None)
            if isinstance(value, uuid.UUID):
                value = str(value)
            elif isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, StrEnum):
                value = value.value
            result[column.name] = value
        return result

    def __repr__(self) -> str:  # pragma: no cover - debug yordamchisi
        identifier = getattr(self, "id", None)
        return f"<{type(self).__name__} id={identifier}>"


# ---------------------------------------------------------------------------
# Mixinlar
# ---------------------------------------------------------------------------


class UUIDPrimaryKeyMixin:
    """UUID birlamchi kalit (`uuid4`, ilova tomonida generatsiya qilinadi).

    ID ilova tomonida yaratilgani uchun job'ni DB'ga yozishdan oldin ham
    identifikator ma'lum bo'ladi — idempotency va log korrelyatsiyasi uchun muhim.
    """

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        primary_key=True,
        default=uuid.uuid4,
        sort_order=-100,  # har doim birinchi ustun
    )


class TimestampMixin:
    """`created_at` / `updated_at` ustunlari.

    Ikki tomonlama standart: Python tomonida `utcnow()` (obyekt darhol to'liq
    bo'ladi) va DB tomonida `now()` (bevosita SQL INSERT uchun).
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTimeTZ,
        default=utcnow,
        server_default=func.now(),
        nullable=False,
        index=True,
        sort_order=100,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTimeTZ,
        default=utcnow,
        server_default=func.now(),
        onupdate=utcnow,
        nullable=False,
        sort_order=101,
    )


class SoftDeleteMixin:
    """Yumshoq o'chirish — yozuv saqlanadi, lekin `deleted_at` belgilanadi."""

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTimeTZ, nullable=True, index=True, sort_order=102
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


__all__ = [
    "NAMING_CONVENTION",
    "Base",
    "DateTimeTZ",
    "JSONType",
    "SoftDeleteMixin",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "UUIDType",
    "enum_column",
]
