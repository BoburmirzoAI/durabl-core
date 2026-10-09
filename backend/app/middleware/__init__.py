"""Durabl — HTTP middleware qatlami va uni ilovaga ulash.

`main.py` faqat `setup_middleware(app)` ni chaqiradi — tartib va sozlamalar
shu modulda jamlangan.
"""

from __future__ import annotations

from typing import cast

from fastapi import FastAPI

from app.logging_config import get_logger
from app.middleware.auth_middleware import (
    PUBLIC_PATH_PREFIXES,
    PUBLIC_PATHS,
    extract_api_key,
    extract_bearer_token,
    extract_credentials,
    extract_ws_token,
    is_public_path,
)
from app.middleware.cors_middleware import setup_cors
from app.middleware.idempotency_middleware import IdempotencyMiddleware
from app.middleware.logging_middleware import RequestLoggingMiddleware
from app.middleware.rate_limit import RateLimitDecision, RateLimitMiddleware

logger = get_logger(__name__)


def setup_middleware(app: FastAPI) -> None:
    """Barcha middleware'ni KELISHILGAN tartibda ulaydi.

    ## Kerakli BAJARILISH tartibi (tashqi qatlamdan ichkariga)

    1. `CORSMiddleware` — eng tashqi: xato javoblari ham CORS header'larini
       olishi va preflight (`OPTIONS`) qolgan qatlamlarga tegmasdan darhol
       javob berishi uchun.
    2. `RequestLoggingMiddleware` — `X-Request-ID` ni eng boshida yaratadi,
       shunda PASTDAGI qatlamlar (rate limit 429'i ham) `request_id` ni
       javobga qo'sha oladi.
    3. `RateLimitMiddleware` — qimmat ishdan OLDIN to'xtatadi.
    4. `IdempotencyMiddleware` — eng ichki: limitdan o'tgan so'rovning
       header'ini tekshiradi.

    ## Nega kod TESKARI tartibda yozilgan

    `Starlette.add_middleware()` yangi qatlamni ro'yxatning BOSHIGA qo'yadi
    (`user_middleware.insert(0, ...)`), keyin stack `reversed()` bilan
    o'raladi. Natijada **oxirgi qo'shilgan qatlam — eng tashqi** bo'ladi.
    Shuning uchun quyida yuqoridagi ro'yxat teskari yo'nalishda qo'shiladi:
    Idempotency -> RateLimit -> Logging -> CORS.

    Bu nozik joy: tartib buzilsa 429 javobida CORS header'i bo'lmaydi va
    frontend xatoni ko'rsata olmaydi. Shuning uchun haqiqiy bajarilish
    tartibi test bilan tasdiqlanadi.

    Args:
        app: Sozlanayotgan FastAPI ilovasi.
    """
    # 4-qatlam (eng ichki)
    app.add_middleware(IdempotencyMiddleware)
    # 3-qatlam
    app.add_middleware(RateLimitMiddleware)
    # 2-qatlam
    app.add_middleware(RequestLoggingMiddleware)
    # 1-qatlam (eng tashqi) — `CORS_ORIGINS` bo'sh bo'lsa qo'shilmaydi
    setup_cors(app)

    logger.info(
        "middleware ulandi",
        order=[name for name, _ in middleware_order(app)],
    )


def middleware_order(app: FastAPI) -> list[tuple[str, type]]:
    """Haqiqiy BAJARILISH tartibi: tashqi qatlamdan ichkariga.

    Diagnostika va testlar uchun: `user_middleware[0]` eng tashqi qatlam
    ekanini `Starlette.build_middleware_stack()` kafolatlaydi.

    Args:
        app: Tekshirilayotgan ilova.

    Returns:
        `(klass_nomi, klass)` juftliklari ro'yxati.
    """
    # `Middleware.cls` starlette'da `_MiddlewareFactory` deb e'lon qilingan
    # (chaqirilishi mumkin bo'lgan har qanday obyekt), amalda esa biz faqat
    # `add_middleware(Klass, ...)` ishlatamiz — ya'ni bu HAR DOIM klass.
    # `getattr` zaxirasi shunchaki diagnostika funksiyasi hech qachon
    # yiqilmasligi uchun.
    rows: list[tuple[str, type]] = []
    for item in app.user_middleware:
        cls = cast("type", item.cls)
        rows.append((getattr(cls, "__name__", repr(cls)), cls))
    return rows


__all__ = [
    "PUBLIC_PATHS",
    "PUBLIC_PATH_PREFIXES",
    "IdempotencyMiddleware",
    "RateLimitDecision",
    "RateLimitMiddleware",
    "RequestLoggingMiddleware",
    "extract_api_key",
    "extract_bearer_token",
    "extract_credentials",
    "extract_ws_token",
    "is_public_path",
    "middleware_order",
    "setup_cors",
    "setup_middleware",
]
