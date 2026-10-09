"""Durabl — reja (plan) bo'yicha so'rov chastotasini cheklash middleware'i.

## Nega middleware, nega dependency emas

Limit **har bir** so'rovga qo'llanishi kerak — shu jumladan autentifikatsiya
bilan muvaffaqiyatsiz tugagan va mavjud bo'lmagan yo'llarga ham. Dependency
faqat router topilgandan keyin ishlaydi, shuning uchun himoya middleware
qatlamida turadi.

## Foydalanuvchini DB'siz aniqlash (ataylab qabul qilingan murosa)

Middleware `Depends()` ishlatolmaydi va unda DB sessiyasi yo'q. Har so'rovda
sessiya ochish — limitni tekshirish uchun — eng qimmat yo'l bo'lardi (aynan
rate limit himoya qilishi kerak bo'lgan hujum paytida DB'ni o'zimiz ko'mib
qo'yardik). Shuning uchun:

* **JWT** — `decode_token()` bilan DB'ga TEGMASDAN `sub` ajratiladi
  (imzo tekshiriladi, ya'ni soxta ID bilan boshqa birovning limitini
  sarflash mumkin emas).
* **API kalit** — kalit hash'i Redis cache'da qidiriladi
  (`RedisKeys.cache("apikey_user", <hash>)`, TTL 60s). Cache'da bo'lmasa
  (masalan kalit bilan birinchi so'rov) — bu so'rov **anonim** IP limiti
  bilan o'tkaziladi, DB'ga murojaat qilinmaydi. Keyinroq
  `dependencies.get_current_principal` muvaffaqiyatli autentifikatsiyadan
  so'ng cache'ni to'ldiradi va keyingi so'rovlar reja limitini oladi.

Natijada API kalit bilan ishlayotgan mijoz eng yomon holatda daqiqada
`RATE_LIMIT_ANONYMOUS_PER_MINUTE` ta "sovuq" so'rov oladi — bu xavfsiz
tomonga xatolik (limit QATTIQROQ bo'ladi, bo'shashmaydi).

## Hisoblash

Sirpanuvchi daqiqa oynasi: `RedisKeys.rate_limit(identity, minute_key())`
kalitiga `INCR` + `EXPIRE 120`. Oyna almashganda kalit ham almashadi, eski
kalit TTL bo'yicha o'z-o'zidan o'chadi.

## Redis qulasa — fail-open

Redis'ga ulanish yo'qolsa limit butunlay O'CHADI va so'rov o'tkaziladi.
Sabab: rate limit — qulaylik mexanizmi, mavjudlik (availability) esa asosiy
talab. Aks holda Redis nosozligi butun API'ni o'chirib qo'yardi.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta

from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.config import settings
from app.constants import (
    HEADER_RATELIMIT_LIMIT,
    HEADER_RATELIMIT_REMAINING,
    HEADER_RATELIMIT_RESET,
    PlanType,
    RedisKeys,
    plan_limits,
)
from app.exceptions import DurablError, RateLimitExceededError
from app.logging_config import get_logger
from app.middleware.auth_middleware import extract_credentials, is_public_path
from app.redis_client import get_redis
from app.schemas.base import ErrorDetail, ErrorResponse
from app.utils.security import decode_token, hash_api_key
from app.utils.time_utils import minute_key, utcnow

logger = get_logger(__name__)

#: Hisoblagich kalitining TTL'i (soniya). Oyna 60 soniya, lekin TTL ikki
#: barobar: soat nozik farq qilsa ham oldingi oyna kaliti yashab turadi.
COUNTER_TTL_SECONDS = 120

#: Limitdan oshganda qo'yiladigan header
HEADER_RETRY_AFTER = "Retry-After"

#: Limit hisoblanmaydigan metodlar — CORS preflight'ni cheklash mantiqsiz
#: (brauzer uni avtomatik yuboradi va javobida auth ma'lumoti yo'q).
EXEMPT_METHODS: frozenset[str] = frozenset({"OPTIONS"})

CallNext = Callable[[Request], Awaitable[Response]]


@dataclass(slots=True)
class RateLimitDecision:
    """Bitta so'rov uchun limit hisobi natijasi.

    Attributes:
        identity: Hisoblagich kaliti egasi (`user:<uuid>` yoki `ip:<addr>`).
        scope: `plan` yoki `anonymous` — log va diagnostika uchun.
        limit: Daqiqadagi ruxsat etilgan so'rovlar soni.
        used: Shu oynada allaqachon sarflangan so'rovlar (joriysi bilan).
        reset_at: Oyna yangilanadigan unix vaqt (soniya).
        retry_after: Mijoz qancha kutishi kerak (soniya).
    """

    identity: str
    scope: str
    limit: int
    used: int
    reset_at: int
    retry_after: int

    @property
    def remaining(self) -> int:
        """Qolgan so'rovlar soni (manfiy bo'lmaydi)."""
        return max(0, self.limit - self.used)

    @property
    def exceeded(self) -> bool:
        """Limit oshdimi?"""
        return self.used > self.limit


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Reja bo'yicha so'rov chastotasini cheklaydi va `X-RateLimit-*` qo'shadi."""

    def __init__(self, app: ASGIApp, *, redis: Redis | None = None) -> None:
        """Middleware'ni yaratadi.

        Args:
            app: Keyingi ASGI ilova (Starlette o'zi uzatadi).
            redis: Testlarda boshqa klientni (yoki "o'lik" klientni) berish
                uchun. Berilmasa global pool ishlatiladi.
        """
        super().__init__(app)
        self._redis = redis

    @property
    def redis(self) -> Redis:
        """Ishlatiladigan Redis klienti."""
        return self._redis if self._redis is not None else get_redis()

    async def dispatch(self, request: Request, call_next: CallNext) -> Response:
        """Limitni tekshiradi, so'rovni o'tkazadi va header'larni qo'shadi."""
        if not settings.RATE_LIMIT_ENABLED or request.method in EXEMPT_METHODS:
            return await call_next(request)

        try:
            decision = await self._evaluate(request)
        except RedisError as exc:
            # Fail-open: Redis yo'q bo'lsa API ishlashda davom etadi.
            logger.warning("rate limit o'chirildi (Redis xatosi)", error=str(exc))
            return await call_next(request)

        if decision.exceeded:
            logger.warning(
                "rate limit oshdi",
                identity=decision.identity,
                scope=decision.scope,
                limit=decision.limit,
                used=decision.used,
            )
            return self._exceeded_response(request, decision)

        response = await call_next(request)
        self._apply_headers(response, decision)
        return response

    # ------------------------------------------------------------------
    # Hisoblash
    # ------------------------------------------------------------------

    async def _evaluate(self, request: Request) -> RateLimitDecision:
        """Identifikator va limitni aniqlab hisoblagichni oshiradi.

        Raises:
            RedisError: Chaqiruvchi (`dispatch`) fail-open qiladi.
        """
        identity, scope, limit = await self._identify(request)

        now = utcnow()
        window_start = now.replace(second=0, microsecond=0)
        reset_at = int((window_start + timedelta(minutes=1)).timestamp())
        retry_after = max(1, reset_at - int(now.timestamp()))

        key = RedisKeys.rate_limit(identity, minute_key(now))
        async with self.redis.pipeline(transaction=False) as pipe:
            pipe.incr(key)
            pipe.expire(key, COUNTER_TTL_SECONDS)
            results = await pipe.execute()
        used = int(results[0])

        return RateLimitDecision(
            identity=identity,
            scope=scope,
            limit=limit,
            used=used,
            reset_at=reset_at,
            retry_after=retry_after,
        )

    async def _identify(self, request: Request) -> tuple[str, str, int]:
        """So'rov egasini va unga tegishli limitni aniqlaydi.

        Returns:
            `(identity, scope, limit)` uchligi.
        """
        if is_public_path(request.url.path):
            return self._anonymous(request)

        user_id = await self._resolve_user_id(request)
        if user_id is None:
            return self._anonymous(request)

        plan = await self._resolve_plan(user_id)
        return f"user:{user_id}", "plan", plan_limits(plan).requests_per_minute

    def _anonymous(self, request: Request) -> tuple[str, str, int]:
        """Anonim (IP bo'yicha) identifikator va limit."""
        return (
            f"ip:{self._client_ip(request)}",
            "anonymous",
            settings.RATE_LIMIT_ANONYMOUS_PER_MINUTE,
        )

    async def _resolve_user_id(self, request: Request) -> str | None:
        """So'rov egasini DB'ga TEGMASDAN aniqlaydi (yuqoridagi izohga qarang)."""
        api_key, token = extract_credentials(request)

        if api_key is not None:
            cached = await self.redis.get(RedisKeys.cache("apikey_user", hash_api_key(api_key)))
            if isinstance(cached, bytes):  # pragma: no cover - decode_responses=True
                cached = cached.decode("utf-8")
            return cached or None

        if token is not None:
            try:
                payload = decode_token(token, expected_type="access")
            except DurablError:
                # Yaroqsiz/muddati o'tgan token — anonim limit qo'llanadi,
                # 401 ni esa `get_current_principal` qaytaradi.
                return None
            subject = payload.get("sub")
            return str(subject) if subject else None

        return None

    async def _resolve_plan(self, user_id: str) -> PlanType:
        """Foydalanuvchi rejasini cache'dan oladi; bo'lmasa FREE.

        FREE eng past limit, ya'ni cache sovuq bo'lganda ham xatolik
        xavfsiz tomonga (qattiqroq limit) ketadi.
        `dependencies.get_current_principal` cache'ni to'ldiradi.
        """
        raw = await self.redis.get(RedisKeys.cache("user_plan", user_id))
        if isinstance(raw, bytes):  # pragma: no cover - decode_responses=True
            raw = raw.decode("utf-8")
        if not raw:
            return PlanType.FREE
        try:
            return PlanType(raw)
        except ValueError:
            logger.debug("user_plan cache'da noma'lum reja", value=raw)
            return PlanType.FREE

    @staticmethod
    def _client_ip(request: Request) -> str:
        """Mijoz IP'si.

        `X-Forwarded-For` ATAYLAB o'qilmaydi: ishonchli reverse proxy
        sozlanmagan holatda uni mijoz o'zi yozib limitni cheksiz
        aylanib o'tishi mumkin. Proxy orqasida ishlatish uchun uvicorn'ning
        `--proxy-headers` rejimi `request.client` ni to'g'rilaydi.
        """
        return request.client.host if request.client else "unknown"

    # ------------------------------------------------------------------
    # Javoblar
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_headers(response: Response, decision: RateLimitDecision) -> None:
        """Har qanday javobga `X-RateLimit-*` header'larini qo'yadi."""
        response.headers[HEADER_RATELIMIT_LIMIT] = str(decision.limit)
        response.headers[HEADER_RATELIMIT_REMAINING] = str(decision.remaining)
        response.headers[HEADER_RATELIMIT_RESET] = str(decision.reset_at)

    def _exceeded_response(self, request: Request, decision: RateLimitDecision) -> JSONResponse:
        """429 javobini O'ZI yasaydi.

        Middleware `main.py` dagi exception handler'lardan OLDIN (tashqarida)
        ishlaydi, ya'ni `raise RateLimitExceededError` bu yerda javobga
        aylanmaydi. Shuning uchun xato obyekti faqat kod/xabar manbai
        sifatida ishlatiladi va `ErrorResponse` qo'lda yig'iladi — javob
        shakli API'ning qolgan qismi bilan BIR XIL bo'lishi SHART.
        """
        error = RateLimitExceededError(limit=decision.limit, retry_after=decision.retry_after)
        body = ErrorResponse(
            error=ErrorDetail(**error.to_dict()),
            request_id=getattr(request.state, "request_id", None),
        )
        response = JSONResponse(
            status_code=error.status_code,
            content=body.model_dump(mode="json", exclude_none=True),
        )
        response.headers[HEADER_RETRY_AFTER] = str(decision.retry_after)
        self._apply_headers(response, decision)
        return response


__all__ = [
    "COUNTER_TTL_SECONDS",
    "EXEMPT_METHODS",
    "HEADER_RETRY_AFTER",
    "RateLimitDecision",
    "RateLimitMiddleware",
]
