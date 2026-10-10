"""Durabl — `app/utils/pagination.py` birlik testlari.

Modul API qatlamining sahifalash va tartiblash poydevori: `apply_sorting`
oq ro'yxat orqali SQL injection'dan himoyalaydi, kursor funksiyalari esa
log oqimini uzluksiz o'qish uchun ishlatiladi. Shuning uchun uning
chegaraviy holatlari (noma'lum ustun, buzilgan kursor, `limit+1` kesimi)
alohida tekshiriladi — integratsiya testlari faqat "baxtli yo'l"ni
qamraydi.
"""

from __future__ import annotations

import base64
import json

import pytest
from app.exceptions import ValidationError
from app.models.job import Job
from app.schemas.base import CursorPage, PaginationParams
from app.utils.pagination import (
    apply_sorting,
    build_cursor_page,
    decode_cursor,
    encode_cursor,
    paginate,
    pagination_params,
)
from sqlalchemy import select

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# `pagination_params` va `paginate`
# ---------------------------------------------------------------------------


def test_pagination_params_builds_model() -> None:
    """Dependency `PaginationParams` modelini qaytaradi (offset hisoblanadi)."""
    params = pagination_params(page=3, page_size=20)

    assert isinstance(params, PaginationParams)
    assert params.page == 3
    assert params.page_size == 20
    assert params.offset == 40
    assert params.limit == 20


def test_paginate_wraps_items_with_meta() -> None:
    """`paginate()` ro'yxatni meta ma'lumot bilan o'raydi."""
    response = paginate(["a", "b"], total=5, params=PaginationParams(page=1, page_size=2))

    assert list(response.items) == ["a", "b"]
    assert response.pagination.total == 5
    assert response.pagination.total_pages == 3
    assert response.pagination.has_next is True
    assert response.pagination.has_prev is False


# ---------------------------------------------------------------------------
# `apply_sorting`
# ---------------------------------------------------------------------------


def test_apply_sorting_adds_descending_order_by() -> None:
    """Standart yo'nalish — `desc`."""
    stmt = apply_sorting(select(Job), Job, sort_by="created_at")

    assert "ORDER BY jobs.created_at DESC" in str(stmt)


def test_apply_sorting_respects_ascending_order() -> None:
    """`sort_order="asc"` registrga sezgir emas."""
    stmt = apply_sorting(select(Job), Job, sort_by="created_at", sort_order="ASC")

    assert "ORDER BY jobs.created_at ASC" in str(stmt)


def test_apply_sorting_rejects_field_outside_allow_list() -> None:
    """Oq ro'yxatdan tashqari ustun `ValidationError` beradi.

    Bu SQL injection'dan asosiy himoya: `sort_by` mijozdan keladi.
    """
    with pytest.raises(ValidationError) as exc_info:
        apply_sorting(select(Job), Job, sort_by="hashed_password", allowed=["created_at", "status"])

    assert exc_info.value.details["allowed"] == ["created_at", "status"]


def test_apply_sorting_rejects_unknown_column_without_allow_list() -> None:
    """Oq ro'yxat berilmasa ham mavjud bo'lmagan ustun rad etiladi."""
    with pytest.raises(ValidationError):
        apply_sorting(select(Job), Job, sort_by="bunday_ustun_yoq")


# ---------------------------------------------------------------------------
# Kursor
# ---------------------------------------------------------------------------


def test_cursor_round_trip_preserves_payload() -> None:
    """Kodlash -> dekodlash aylanishi qiymatni saqlaydi."""
    payload = {"sequence": 42, "execution_id": "a-b-c"}

    assert decode_cursor(encode_cursor(payload)) == payload


def test_encode_cursor_is_url_safe_and_unpadded() -> None:
    """Kursor URL'da qo'shimcha kodlashsiz ishlatilishi kerak."""
    cursor = encode_cursor({"sequence": 1})

    assert "=" not in cursor
    assert "+" not in cursor
    assert "/" not in cursor


def test_decode_cursor_accepts_empty_values() -> None:
    """Bo'sh yoki `None` kursor — "boshidan boshla" degani."""
    assert decode_cursor(None) == {}
    assert decode_cursor("") == {}


def test_decode_cursor_rejects_malformed_text() -> None:
    """base64 bo'lmagan matn `ValidationError` beradi (500 EMAS)."""
    with pytest.raises(ValidationError):
        decode_cursor("!!! bu base64 emas !!!")


def test_decode_cursor_rejects_non_object_payload() -> None:
    """Yaroqli base64, lekin JSON obyekti bo'lmagan tana ham rad etiladi."""
    raw = base64.urlsafe_b64encode(json.dumps([1, 2, 3]).encode()).decode().rstrip("=")

    with pytest.raises(ValidationError):
        decode_cursor(raw)


# ---------------------------------------------------------------------------
# `build_cursor_page`
# ---------------------------------------------------------------------------


def test_build_cursor_page_trims_extra_item_and_sets_cursor() -> None:
    """`limit+1` usuli: ortiqcha element kesiladi, `has_more=True`."""
    page = build_cursor_page([1, 2, 3], limit=2, cursor_builder=lambda item: f"cursor-{item}")

    assert isinstance(page, CursorPage)
    assert page.items == [1, 2]
    assert page.has_more is True
    # Kursor OXIRGI QAYTARILGAN elementdan yasaladi (kesilgan element emas).
    assert page.next_cursor == "cursor-2"


def test_build_cursor_page_without_extra_item_has_no_cursor() -> None:
    """Element soni limitga teng bo'lsa — oqim tugagan, kursor `None`."""
    page = build_cursor_page([1, 2], limit=2, cursor_builder=lambda item: f"cursor-{item}")

    assert page.items == [1, 2]
    assert page.has_more is False
    assert page.next_cursor is None


def test_build_cursor_page_handles_empty_input() -> None:
    """Bo'sh ro'yxat `cursor_builder` ni CHAQIRMAYDI."""

    def exploding_builder(_item: object) -> str:
        raise AssertionError("bo'sh sahifada kursor yasalmasligi kerak")

    page = build_cursor_page([], limit=10, cursor_builder=exploding_builder)

    assert page.items == []
    assert page.has_more is False
    assert page.next_cursor is None


__all__ = [
    "test_apply_sorting_adds_descending_order_by",
    "test_apply_sorting_rejects_field_outside_allow_list",
    "test_apply_sorting_rejects_unknown_column_without_allow_list",
    "test_apply_sorting_respects_ascending_order",
    "test_build_cursor_page_handles_empty_input",
    "test_build_cursor_page_trims_extra_item_and_sets_cursor",
    "test_build_cursor_page_without_extra_item_has_no_cursor",
    "test_cursor_round_trip_preserves_payload",
    "test_decode_cursor_accepts_empty_values",
    "test_decode_cursor_rejects_malformed_text",
    "test_decode_cursor_rejects_non_object_payload",
    "test_encode_cursor_is_url_safe_and_unpadded",
    "test_paginate_wraps_items_with_meta",
    "test_pagination_params_builds_model",
]
