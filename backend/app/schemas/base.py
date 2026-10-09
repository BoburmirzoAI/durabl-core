"""Durabl — Pydantic bazaviy schema'lar va umumiy javob konvertlari.

Barcha API javoblari ikki shakldan birida qaytadi:

* Bitta resurs yoki amal natijasi — resurs schema'si bevosita (masalan `JobRead`).
* Ro'yxat — `PaginatedResponse[T]` (`items` + `pagination`).

Xatolar esa har doim `ErrorResponse` ko'rinishida (`main.py` handler'lari).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, Any, Generic, Literal, TypeVar

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_serializer,
)

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Bazaviy schema'lar
# ---------------------------------------------------------------------------


class DurablSchema(BaseModel):
    """Barcha schema'larning bazasi — qat'iy validatsiya."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",  # noma'lum maydon yuborilsa xato (mijoz xatosini erta topish)
        validate_assignment=True,
        populate_by_name=True,
    )


class ORMSchema(DurablSchema):
    """SQLAlchemy modelidan to'g'ridan-to'g'ri o'qiladigan schema."""

    model_config = ConfigDict(
        from_attributes=True,
        str_strip_whitespace=True,
        extra="ignore",  # modelda qo'shimcha maydon bo'lishi normal
        populate_by_name=True,
    )

    @field_serializer("*", when_used="json", check_fields=False)
    def _serialize_datetimes(self, value: Any) -> Any:
        """Barcha datetime'lar UTC `Z` formatida qaytadi."""
        if isinstance(value, datetime):
            iso = value.isoformat()
            return iso.replace("+00:00", "Z")
        return value


# ---------------------------------------------------------------------------
# Umumiy javoblar
# ---------------------------------------------------------------------------


class SuccessResponse(DurablSchema):
    """Oddiy "bajarildi" javobi (DELETE, cancel, test va h.k.)."""

    success: bool = True
    message: str = "Bajarildi"
    data: dict[str, Any] | None = None


class ErrorDetail(DurablSchema):
    """Bitta xato tafsiloti."""

    code: str = Field(description="Mashina o'qiydigan barqaror xato kodi")
    message: str = Field(description="Inson o'qiydigan xabar")
    details: dict[str, Any] | None = Field(default=None, description="Qo'shimcha kontekst")


class ErrorResponse(DurablSchema):
    """Xato javobi — barcha 4xx/5xx shu shaklda."""

    error: ErrorDetail
    request_id: str | None = Field(default=None, description="So'rovni kuzatish identifikatori")


class ValidationErrorItem(DurablSchema):
    """Pydantic validatsiya xatosining bitta elementi."""

    field: str
    message: str
    type: str


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

#: Standart va maksimal sahifa hajmi
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 200


class PaginationParams(DurablSchema):
    """Query parametrlari: `?page=1&page_size=20`."""

    page: Annotated[int, Field(ge=1, description="Sahifa raqami (1'dan)")] = 1
    page_size: Annotated[
        int, Field(ge=1, le=MAX_PAGE_SIZE, description="Sahifadagi yozuvlar soni")
    ] = DEFAULT_PAGE_SIZE

    @property
    def offset(self) -> int:
        """SQL OFFSET."""
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        """SQL LIMIT."""
        return self.page_size


class SortParams(DurablSchema):
    """Tartiblash parametrlari."""

    sort_by: str = Field(default="created_at", description="Tartiblash ustuni")
    sort_order: Literal["asc", "desc"] = Field(default="desc", description="Yo'nalish")


class PaginationMeta(DurablSchema):
    """Sahifalash meta-ma'lumoti."""

    page: int
    page_size: int
    total: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_pages(self) -> int:
        """Umumiy sahifalar soni."""
        if self.page_size <= 0:
            return 0
        return math.ceil(self.total / self.page_size)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_next(self) -> bool:
        return self.page < self.total_pages

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_prev(self) -> bool:
        return self.page > 1


class PaginatedResponse(DurablSchema, Generic[T]):
    """Sahifalangan ro'yxat javobi."""

    items: list[T]
    pagination: PaginationMeta

    @classmethod
    def create(
        cls,
        items: Sequence[T],
        *,
        total: int,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> PaginatedResponse[T]:
        """Ro'yxat va umumiy sondan javob yasaydi."""
        return cls(
            items=list(items),
            pagination=PaginationMeta(page=page, page_size=page_size, total=total),
        )

    @classmethod
    def from_params(
        cls,
        items: Sequence[T],
        *,
        total: int,
        params: PaginationParams,
    ) -> PaginatedResponse[T]:
        """`PaginationParams`dan javob yasaydi."""
        return cls.create(items, total=total, page=params.page, page_size=params.page_size)


class CursorPage(DurablSchema, Generic[T]):
    """Kursorli sahifalash — real-time loglar va katta ro'yxatlar uchun."""

    items: list[T]
    next_cursor: str | None = Field(default=None, description="Keyingi sahifa kursori")
    has_more: bool = False


# ---------------------------------------------------------------------------
# Umumiy filtrlar va yordamchilar
# ---------------------------------------------------------------------------


class TimeRangeParams(DurablSchema):
    """Vaqt oralig'i filtri — analitika va ro'yxatlar uchun."""

    start: datetime | None = Field(default=None, description="Boshlanish (ISO-8601, UTC)")
    end: datetime | None = Field(default=None, description="Tugash (ISO-8601, UTC)")


class HealthStatus(DurablSchema):
    """`/health` javobi."""

    status: Literal["ok", "degraded", "down"]
    version: str
    environment: str
    checks: dict[str, bool] = Field(default_factory=dict)
    uptime_seconds: float | None = None


class CountResponse(DurablSchema):
    """Faqat son qaytarish kerak bo'lganda."""

    count: int


class IdResponse(DurablSchema):
    """Yaratilgan resurs identifikatori."""

    id: str


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "CountResponse",
    "CursorPage",
    "DurablSchema",
    "ErrorDetail",
    "ErrorResponse",
    "HealthStatus",
    "IdResponse",
    "ORMSchema",
    "PaginatedResponse",
    "PaginationMeta",
    "PaginationParams",
    "SortParams",
    "SuccessResponse",
    "TimeRangeParams",
    "ValidationErrorItem",
]
