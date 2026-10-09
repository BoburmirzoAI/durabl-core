"""Durabl — `Idempotency-Key` header'ini tekshiruvchi middleware.

## Mas'uliyat chegarasi (muhim)

Bu middleware **idempotency mantig'ini bajarmaydi** — faqat kalitni
tekshiradi va `request.state.idempotency_key` ga yozadi.

Haqiqiy takrorlanishni aniqlash `JobService.submit()` ichida, DB tranzaksiyasi
BILAN BIRGA bajarilishi SHART: kalitni band qilish (`IdempotencyService.reserve`)
va job yozuvini yaratish bitta atomar oqimda bo'lishi kerak, aks holda ikki
parallel so'rov ikki job yaratib qo'yadi. Middleware'da esa DB sessiyasi yo'q
va javob tanasi hali ma'lum emas, shuning uchun u yerda hech narsa
"keshlanmaydi".

Ya'ni bu qatlamning yagona foydasi — mijoz xatosini ERTA (DB'ga tegmasdan)
va bir xil `ErrorResponse` shaklida qaytarish.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import settings
from app.constants import HEADER_IDEMPOTENCY_KEY
from app.exceptions import BadRequestError
from app.logging_config import get_logger
from app.schemas.base import ErrorDetail, ErrorResponse

logger = get_logger(__name__)

#: Kalit uzunligi chegaralari
MIN_KEY_LENGTH = 8
MAX_KEY_LENGTH = 255

#: Ruxsat etilgan belgilar: UUID, ULID, `<prefix>:<id>` kabi shakllar.
#: Qat'iy shablon ataylab: kalit log'ga va Redis kalitiga tushadi, shuning
#: uchun bo'shliq, `*`, yangi qator kabi belgilar o'tmasligi kerak.
KEY_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]+$")

CallNext = Callable[[Request], Awaitable[Response]]


class IdempotencyMiddleware(BaseHTTPMiddleware):
    """`POST {API_V1_PREFIX}/jobs` uchun idempotency kalitini tekshiradi."""

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        """Faqat job yaratish so'rovini ushlaydi, qolganini o'tkazib yuboradi."""
        if not self._is_job_submit(request):
            return await call_next(request)

        raw = request.headers.get(HEADER_IDEMPOTENCY_KEY)
        key = raw.strip() if raw else ""

        if not key:
            # Idempotency IXTIYORIY — so'rov rad etilmaydi. Lekin
            # production'da kalitsiz `POST /jobs` tarmoq uzilishida ikki
            # marta job yaratilishiga olib keladi, shuning uchun
            # ogohlantirish yoziladi (SDK mijozlari kalitni avtomatik qo'yadi).
            if settings.is_production:
                logger.warning(
                    "POST /jobs `Idempotency-Key` headerisiz keldi — "
                    "tarmoq uzilishida job ikki marta yaratilishi mumkin",
                    path=request.url.path,
                )
            request.state.idempotency_key = None
            return await call_next(request)

        error = self._validate(key)
        if error is not None:
            logger.info("yaroqsiz Idempotency-Key", reason=error.message)
            return self._error_response(request, error)

        request.state.idempotency_key = key
        return await call_next(request)

    # ------------------------------------------------------------------
    # Yordamchilar
    # ------------------------------------------------------------------

    @staticmethod
    def _is_job_submit(request: Request) -> bool:
        """So'rov `POST {API_V1_PREFIX}/jobs` ga tegishlimi?"""
        if request.method != "POST":
            return False
        path = request.url.path
        if len(path) > 1 and path.endswith("/"):
            path = path.rstrip("/")
        return path == f"{settings.API_V1_PREFIX.rstrip('/')}/jobs"

    @staticmethod
    def _validate(key: str) -> BadRequestError | None:
        """Kalitni tekshiradi; muammo bo'lsa xato obyektini qaytaradi."""
        if len(key) < MIN_KEY_LENGTH or len(key) > MAX_KEY_LENGTH:
            return BadRequestError(
                f"`{HEADER_IDEMPOTENCY_KEY}` uzunligi {MIN_KEY_LENGTH}..{MAX_KEY_LENGTH} "
                "belgi bo'lishi kerak",
                details={
                    "header": HEADER_IDEMPOTENCY_KEY,
                    "length": len(key),
                    "min_length": MIN_KEY_LENGTH,
                    "max_length": MAX_KEY_LENGTH,
                },
            )
        if KEY_PATTERN.match(key) is None:
            return BadRequestError(
                f"`{HEADER_IDEMPOTENCY_KEY}` faqat harf, raqam va `_ . : -` "
                "belgilaridan tuzilishi kerak",
                details={"header": HEADER_IDEMPOTENCY_KEY, "pattern": KEY_PATTERN.pattern},
            )
        return None

    @staticmethod
    def _error_response(request: Request, error: BadRequestError) -> JSONResponse:
        """400 javobini `ErrorResponse` shaklida yasaydi.

        Middleware exception handler'lardan tashqarida ishlaydi, shuning
        uchun javob qo'lda yig'iladi — shakl API'ning qolgan qismi bilan
        bir xil bo'lishi SHART.
        """
        body = ErrorResponse(
            error=ErrorDetail(**error.to_dict()),
            request_id=getattr(request.state, "request_id", None),
        )
        return JSONResponse(
            status_code=error.status_code,
            content=body.model_dump(mode="json", exclude_none=True),
        )


__all__ = [
    "KEY_PATTERN",
    "MAX_KEY_LENGTH",
    "MIN_KEY_LENGTH",
    "IdempotencyMiddleware",
]
