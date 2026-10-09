"""Durabl — CORS sozlamasi (brauzerdagi frontend uchun).

`CORSMiddleware` eng TASHQI qatlam bo'lishi kerak: shundagina rate limit
429'i, 401 va 500 javoblari ham CORS header'larini oladi. Aks holda brauzer
xato javobini o'qiy olmaydi va frontend'da "Network Error" degan tushunarsiz
xabar chiqadi.
"""

from __future__ import annotations

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.config import settings
from app.constants import (
    HEADER_API_KEY,
    HEADER_CORRELATION_ID,
    HEADER_IDEMPOTENCY_KEY,
    HEADER_RATELIMIT_LIMIT,
    HEADER_RATELIMIT_REMAINING,
    HEADER_RATELIMIT_RESET,
    HEADER_REQUEST_ID,
)
from app.logging_config import get_logger

logger = get_logger(__name__)

#: Mijoz YUBORISHI mumkin bo'lgan header'lar.
#: `"*"` ataylab ishlatilmaydi: `allow_credentials=True` bilan birga
#: `"*"` spetsifikatsiya bo'yicha ishlamaydi va brauzer preflight'ni rad etadi.
ALLOWED_HEADERS: tuple[str, ...] = (
    "Accept",
    "Accept-Language",
    "Authorization",
    "Content-Type",
    HEADER_API_KEY,
    HEADER_IDEMPOTENCY_KEY,
    HEADER_CORRELATION_ID,
    HEADER_REQUEST_ID,
)

#: Mijoz JavaScript'i O'QISHI mumkin bo'lgan javob header'lari.
#: Ro'yxatga kiritilmagan header `fetch`/`axios` uchun ko'rinmas bo'ladi.
EXPOSED_HEADERS: tuple[str, ...] = (
    HEADER_REQUEST_ID,
    HEADER_RATELIMIT_LIMIT,
    HEADER_RATELIMIT_REMAINING,
    HEADER_RATELIMIT_RESET,
    "Retry-After",
    "X-Response-Time-ms",
    "Location",
)

#: Preflight javobini brauzer qancha keshlashi mumkin (soniya)
PREFLIGHT_MAX_AGE = 600


def setup_cors(app: FastAPI) -> None:
    """Ilovaga `CORSMiddleware` ni qo'shadi.

    `settings.CORS_ORIGINS` bo'sh bo'lsa middleware QO'SHILMAYDI: bu
    "faqat server-server" rejimi (brauzerdan foydalanilmaydi), va bo'sh
    ro'yxat bilan middleware qo'shish har bir so'rovga foydasiz ish
    qo'shardi. Qaror log'ga yoziladi, chunki CORS muammolarini
    diagnostika qilishda birinchi savol aynan shu bo'ladi.

    Args:
        app: Sozlanayotgan FastAPI ilovasi.
    """
    origins = [origin for origin in settings.CORS_ORIGINS if origin.strip()]
    if not origins:
        logger.warning(
            "CORS_ORIGINS bo'sh — CORSMiddleware qo'shilmadi "
            "(brauzerdan to'g'ridan-to'g'ri so'rovlar bloklanadi)"
        )
        return

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
        allow_methods=["*"],
        allow_headers=list(ALLOWED_HEADERS),
        expose_headers=list(EXPOSED_HEADERS),
        max_age=PREFLIGHT_MAX_AGE,
    )
    logger.info("CORS yoqildi", origins=origins, credentials=settings.CORS_ALLOW_CREDENTIALS)


__all__ = [
    "ALLOWED_HEADERS",
    "EXPOSED_HEADERS",
    "PREFLIGHT_MAX_AGE",
    "setup_cors",
]
