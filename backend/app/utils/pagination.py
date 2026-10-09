"""Durabl — sahifalash va tartiblash yordamchilari (API qatlami uchun)."""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from typing import Any, TypeVar

from fastapi import Query
from sqlalchemy import Select, asc, desc

from app.exceptions import ValidationError
from app.schemas.base import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    CursorPage,
    PaginatedResponse,
    PaginationParams,
)

T = TypeVar("T")


def pagination_params(
    page: int = Query(1, ge=1, description="Sahifa raqami (1'dan boshlanadi)"),
    page_size: int = Query(
        DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE, description="Sahifadagi yozuvlar soni"
    ),
) -> PaginationParams:
    """FastAPI dependency — `?page=&page_size=` parametrlarini o'qiydi."""
    return PaginationParams(page=page, page_size=page_size)


def apply_sorting(
    stmt: Select[Any],
    model: type[Any],
    *,
    sort_by: str,
    sort_order: str = "desc",
    allowed: Sequence[str] | None = None,
) -> Select[Any]:
    """SQL so'rovga ORDER BY qo'shadi.

    `allowed` berilsa, faqat ro'yxatdagi ustunlar bo'yicha tartiblash mumkin
    (SQL injection va noto'g'ri ustun nomidan himoya).
    """
    if allowed is not None and sort_by not in allowed:
        raise ValidationError(
            f"'{sort_by}' bo'yicha tartiblash mumkin emas",
            details={"allowed": list(allowed)},
        )
    column = getattr(model, sort_by, None)
    if column is None:
        raise ValidationError(f"'{sort_by}' ustuni mavjud emas")
    direction = asc if sort_order.lower() == "asc" else desc
    return stmt.order_by(direction(column))


def paginate(
    items: Sequence[T],
    *,
    total: int,
    params: PaginationParams,
) -> PaginatedResponse[T]:
    """Ro'yxatni sahifalangan javobga o'raydi."""
    return PaginatedResponse.from_params(items, total=total, params=params)


# ---------------------------------------------------------------------------
# Kursorli sahifalash (loglar uchun)
# ---------------------------------------------------------------------------


def encode_cursor(payload: dict[str, Any]) -> str:
    """Kursorni base64url matnga aylantiradi."""
    raw = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None) -> dict[str, Any]:
    """base64url kursorni lug'atga qaytaradi; yaroqsiz bo'lsa `ValidationError`."""
    if not cursor:
        return {}
    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + padding)
        decoded = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise ValidationError("Kursor yaroqsiz") from exc
    if not isinstance(decoded, dict):
        raise ValidationError("Kursor yaroqsiz")
    return decoded


def build_cursor_page(
    items: Sequence[T],
    *,
    limit: int,
    cursor_builder: Any,
) -> CursorPage[T]:
    """Kursorli sahifa yasaydi.

    `items` uzunligi `limit`dan katta bo'lsa — oxirgi element kesiladi va
    `has_more=True` qo'yiladi (klassik "limit+1" usuli).
    """
    has_more = len(items) > limit
    page_items = list(items[:limit])
    next_cursor = cursor_builder(page_items[-1]) if has_more and page_items else None
    return CursorPage(items=page_items, next_cursor=next_cursor, has_more=has_more)


__all__ = [
    "apply_sorting",
    "build_cursor_page",
    "decode_cursor",
    "encode_cursor",
    "paginate",
    "pagination_params",
]
