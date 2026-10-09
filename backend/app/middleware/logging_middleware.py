"""Durabl — so'rovlarni log qilish va metrikaga yozish middleware'i.

Vazifalari:

* `X-Request-ID` ni so'rovdan oladi yoki yaratadi; `request.state.request_id`
  ga yozadi va JAVOB header'ida qaytaradi (mijoz xato haqida murojaat qilsa
  shu ID bo'yicha log topiladi).
* structlog kontekstini bog'laydi — shu so'rov ichidagi BARCHA log yozuvlari
  avtomatik `request_id`, `method`, `path` maydonlarini oladi.
* `X-Response-Time-ms` header'i va `http.request.finished` yozuvi.
* Prometheus `http_requests_total` / `http_request_duration_seconds`.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.config import settings
from app.constants import HEADER_REQUEST_ID
from app.logging_config import bind_request_context, clear_request_context, get_logger
from app.metrics import track_request

logger = get_logger(__name__)

#: Javobda qaytariladigan javob vaqti header'i
HEADER_RESPONSE_TIME = "X-Response-Time-ms"

#: Bu yo'llar LOG QILINMAYDI — konteyner healthcheck va Prometheus scrape
#: sekundda bir marta keladi va log'ni butunlay ko'mib tashlaydi.
#: Metrikaga esa YOZILADI (ular arzon va foydali).
SILENT_PATHS: frozenset[str] = frozenset({"/health", "/metrics", settings.METRICS_PATH})

#: Route topilmaganda metrikada ishlatiladigan yorliq. Xom yo'lni (404 bo'lgan
#: tasodifiy URL'lar) label sifatida yozish Prometheus'da cheksiz timeseries
#: yaratadi, shuning uchun hammasi bitta yorliqqa yig'iladi.
UNMATCHED_ROUTE = "unmatched"

CallNext = Callable[[Request], Awaitable[Response]]


def _route_template(request: Request) -> str:
    """Metrika uchun yo'l SHABLONI (`/api/v1/jobs/{job_id}`).

    Starlette router moslikni topganda `scope["route"]` ga route obyektini
    yozadi. `BaseHTTPMiddleware` downstream ilovaga AYNI `scope` lug'atini
    uzatadi, shuning uchun `call_next` qaytgandan keyin shablon mavjud
    bo'ladi. Moslik bo'lmasa (404) — `UNMATCHED_ROUTE`.
    """
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return UNMATCHED_ROUTE


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Har bir HTTP so'rovini kuzatadi: request ID, log, vaqt, metrika."""

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        """So'rovni o'rab oladi va natijani qayd qiladi."""
        request_id = self._resolve_request_id(request)
        request.state.request_id = request_id

        method = request.method
        raw_path = request.url.path
        silent = raw_path in SILENT_PATHS
        started = time.perf_counter()

        bind_request_context(request_id=request_id, method=method, path=raw_path)
        try:
            if not silent:
                logger.debug("http.request.started", client=self._client_host(request))

            try:
                response = await call_next(request)
            except Exception as exc:
                # ExceptionMiddleware (bizdan ICHKARIDA) `DurablError` kabi
                # ro'yxatdan o'tgan xatolarni javobga aylantiradi, ya'ni bu
                # yerga faqat KUTILMAGAN xato yetib keladi — uni albatta
                # log qilamiz va `ServerErrorMiddleware` ga uzatamiz.
                duration = time.perf_counter() - started
                logger.exception(
                    "http.request.failed",
                    status_code=500,
                    duration_ms=round(duration * 1000, 2),
                    error=type(exc).__name__,
                    user_id=getattr(request.state, "user_id", None),
                )
                track_request(method, _route_template(request), 500, duration)
                raise

            duration = time.perf_counter() - started
            duration_ms = round(duration * 1000, 2)

            response.headers[HEADER_REQUEST_ID] = request_id
            response.headers[HEADER_RESPONSE_TIME] = f"{duration_ms:.2f}"

            track_request(method, _route_template(request), response.status_code, duration)

            if not silent:
                self._log_finished(request, response.status_code, duration_ms)

            return response
        finally:
            # Tozalash MAJBURIY: asyncio task'lari contextvar'ni meros qilib
            # oladi, tozalanmasa keyingi so'rov eski `request_id` bilan
            # log yozishi mumkin.
            clear_request_context()

    @staticmethod
    def _resolve_request_id(request: Request) -> str:
        """Mijoz yuborgan `X-Request-ID` yoki yangi UUID4 (defis'siz)."""
        incoming = request.headers.get(HEADER_REQUEST_ID)
        if incoming:
            candidate = incoming.strip()
            # Juda uzun qiymat log va header'ni ifloslantirmasin.
            if candidate:
                return candidate[:64]
        return uuid.uuid4().hex

    @staticmethod
    def _client_host(request: Request) -> str | None:
        """So'rov kelgan IP (proxy orqasida bo'lsa `None` bo'lishi mumkin)."""
        return request.client.host if request.client else None

    def _log_finished(self, request: Request, status_code: int, duration_ms: float) -> None:
        """So'rov yakunini mos log darajasida yozadi."""
        payload: dict[str, object] = {
            "status_code": status_code,
            "duration_ms": duration_ms,
            "route": _route_template(request),
        }
        user_id = getattr(request.state, "user_id", None)
        if user_id is not None:
            payload["user_id"] = str(user_id)

        if status_code >= 500:
            logger.error("http.request.finished", **payload)
        elif status_code >= 400:
            logger.warning("http.request.finished", **payload)
        else:
            logger.info("http.request.finished", **payload)


__all__ = [
    "HEADER_RESPONSE_TIME",
    "SILENT_PATHS",
    "UNMATCHED_ROUTE",
    "RequestLoggingMiddleware",
]
