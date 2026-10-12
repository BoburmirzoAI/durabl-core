"""Durabl — FastAPI dependency'lari (API qatlamining yagona kirish nuqtasi).

Bu modul uch guruh dependency beradi:

1. **Infratuzilma** — `DbSession`, `RedisDep` (sessiya va Redis klienti).
2. **Autentifikatsiya** — `CurrentPrincipal`, `CurrentUser`, `AdminUser`,
   WebSocket uchun `get_ws_user`.
3. **Service fabrikalari** — `JobSvc`, `AuthSvc`, ... Har bir endpointda
   `JobService(session, redis)` ni qo'lda yasash o'rniga `Annotated` tur
   ishlatiladi; shu tufayli konstruktor imzosi o'zgarsa faqat shu fayl
   tahrirlanadi.

Qatlam qoidasi: bu modul `services/` ni chaqiradi, `repositories/` yoki
`models/` ga bevosita SQL yozmaydi.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Header, Query, Request
from fastapi.security import APIKeyHeader, HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocket

from app.constants import (
    HEADER_API_KEY,
    HEADER_CORRELATION_ID,
    HEADER_IDEMPOTENCY_KEY,
    HEADER_REQUEST_ID,
    ApiKeyScope,
    RedisKeys,
)
from app.database import get_db
from app.exceptions import (
    AdminRequiredError,
    ApiKeyScopeError,
    AuthenticationError,
    InactiveUserError,
)
from app.logging_config import bind_request_context, get_logger
from app.middleware.auth_middleware import extract_credentials, extract_ws_token
from app.models.api_key import ApiKey
from app.models.user import User
from app.redis_client import get_redis, get_redis_dependency
from app.schemas.base import PaginationParams
from app.services.analytics_service import AnalyticsService
from app.services.auth_service import AuthService
from app.services.billing_service import BillingService
from app.services.cache_service import CacheService
from app.services.execution_service import ExecutionService
from app.services.idempotency_service import IdempotencyService
from app.services.job_service import JobService
from app.services.queue_service import QueueService
from app.services.reliability_service import ReliabilityService
from app.services.webhook_service import WebhookService
from app.utils.pagination import pagination_params
from app.utils.security import generate_correlation_id, hash_api_key, is_api_key_format

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Infratuzilma dependency'lari
# ---------------------------------------------------------------------------

#: Har so'rovga bitta async sessiya. Commit — service qatlamining mas'uliyati.
DbSession = Annotated[AsyncSession, Depends(get_db)]

#: Global Redis klienti (pool ichidan).
RedisDep = Annotated[Redis, Depends(get_redis_dependency)]

# ---------------------------------------------------------------------------
# OpenAPI xavfsizlik sxemalari
# ---------------------------------------------------------------------------
# `auto_error=False` — sxemalar O'ZI 403 tashlamaydi, chunki qarorni
# `get_current_principal` qabul qiladi (bizda 401 va o'zbekcha `ErrorResponse`
# qaytishi kerak). Ikkisi dependency sifatida e'lon qilinganligi uchun
# `/docs` da "Authorize" tugmasida IKKI usul ko'rinadi.

_bearer_scheme = HTTPBearer(
    scheme_name="JWT",
    description=(
        "`Authorization: Bearer <access_token>`. API kalitni ham shu yerda yuborish mumkin."
    ),
    auto_error=False,
)

_api_key_scheme = APIKeyHeader(
    name=HEADER_API_KEY,
    scheme_name="ApiKey",
    description=f"`{HEADER_API_KEY}: durabl_...` — server-server integratsiyalari uchun.",
    auto_error=False,
)

#: `apikey_user` cache TTL (soniya) — `rate_limit` middleware shu yozuvni
#: o'qiydi, shuning uchun qiymat qisqa: kalit bekor qilinsa limit tez
#: to'g'rilanadi.
APIKEY_CACHE_TTL_SECONDS = 60

#: `user_plan` cache TTL (soniya) — reja kamdan-kam o'zgaradi.
PLAN_CACHE_TTL_SECONDS = 300


@dataclass(slots=True)
class Principal:
    """So'rovni bajarayotgan sub'ekt.

    Attributes:
        user: Autentifikatsiyadan o'tgan foydalanuvchi.
        auth_method: Qanday usulda aniqlangani — audit va metrikalar uchun.
        api_key: `auth_method == "api_key"` bo'lsa ishlatilgan kalit
            (scope'larni tekshirish va `last_used_at` uchun), aks holda `None`.
    """

    user: User
    auth_method: Literal["jwt", "api_key"]
    api_key: ApiKey | None = None

    @property
    def user_id(self) -> uuid.UUID:
        """Foydalanuvchi ID'si (qisqartma)."""
        return self.user.id

    @property
    def is_admin(self) -> bool:
        """Foydalanuvchi administratormi?"""
        return bool(self.user.is_admin)


# ---------------------------------------------------------------------------
# Cache'ni to'ldirish (rate limit middleware uchun)
# ---------------------------------------------------------------------------


async def _prime_api_key_cache(redis: Redis, raw_key: str, user_id: uuid.UUID) -> None:
    """`apikey_user` cache'ini to'ldiradi.

    `rate_limit` middleware'i DB sessiyasi ochmaydi, shuning uchun API kalit
    egasini FAQAT shu cache orqali bilishi mumkin. Birinchi so'rov anonim
    limit bilan o'tadi, shundan keyin — reja limiti bilan.

    Redis xatosi jim yutiladi: cache yo'qligi autentifikatsiyani to'xtatmasin.
    """
    try:
        await redis.set(
            RedisKeys.cache("apikey_user", hash_api_key(raw_key)),
            str(user_id),
            ex=APIKEY_CACHE_TTL_SECONDS,
        )
    except RedisError as exc:  # pragma: no cover - Redis nosozligi
        logger.debug("apikey_user cache yozilmadi", error=str(exc))


async def _prime_plan_cache(redis: Redis, session: AsyncSession, user_id: uuid.UUID) -> None:
    """`user_plan` cache'ini to'ldiradi (bo'sh bo'lsa).

    Avval `EXISTS` bilan tekshiriladi — shu tufayli DB so'rovi har bir
    so'rovda emas, TTL'da bir marta bajariladi. `BillingService.limits_for()`
    faqat o'qiydi va `commit()` qilmaydi, ya'ni joriy tranzaksiyaga xalaqit
    bermaydi.
    """
    key = RedisKeys.cache("user_plan", user_id)
    try:
        if await redis.exists(key):
            return
    except RedisError as exc:  # pragma: no cover - Redis nosozligi
        logger.debug("user_plan cache o'qilmadi", error=str(exc))
        return

    limits = await BillingService(session).limits_for(user_id)
    try:
        await redis.set(key, limits.plan.value, ex=PLAN_CACHE_TTL_SECONDS)
    except RedisError as exc:  # pragma: no cover - Redis nosozligi
        logger.debug("user_plan cache yozilmadi", error=str(exc))


# ---------------------------------------------------------------------------
# Autentifikatsiya
# ---------------------------------------------------------------------------


async def get_current_principal(
    request: Request,
    session: DbSession,
    bearer: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)] = None,
    api_key_header: Annotated[str | None, Depends(_api_key_scheme)] = None,
) -> Principal:
    """So'rovni API kalit yoki JWT orqali foydalanuvchiga bog'laydi.

    Tartib:

    1. `X-API-Key` header'i bo'lsa — `AuthService.resolve_api_key`.
    2. Bo'lmasa `Authorization: Bearer <...>`: qiymat API kalit shaklida
       bo'lsa yana `resolve_api_key`, aks holda `resolve_token`.
    3. Hech biri yo'q bo'lsa — `AuthenticationError` (401).

    `bearer` va `api_key_header` parametrlari faqat OpenAPI hujjati uchun
    e'lon qilingan (`auto_error=False`); haqiqiy ajratish `extract_credentials`
    bilan `request` dan bajariladi, chunki u `Authorization` ichidagi API
    kalitni ham taniydi.

    Raises:
        AuthenticationError: Hech qanday ma'lumot yuborilmadi.
        InvalidApiKeyError: Kalit yaroqsiz/bekor qilingan.
        InvalidTokenError | TokenExpiredError: JWT yaroqsiz.
        InactiveUserError: Hisob faolsizlantirilgan.
    """
    raw_api_key, raw_token = extract_credentials(request)
    auth_service = AuthService(session)
    redis = get_redis()

    if raw_api_key is not None:
        user, api_key = await auth_service.resolve_api_key(raw_api_key)
        await _prime_api_key_cache(redis, raw_api_key, user.id)
        await _prime_plan_cache(redis, session, user.id)
        _bind_principal_context(request, user.id, "api_key")
        return Principal(user=user, auth_method="api_key", api_key=api_key)

    if raw_token is not None:
        user = await auth_service.resolve_token(raw_token)
        await _prime_plan_cache(redis, session, user.id)
        _bind_principal_context(request, user.id, "jwt")
        return Principal(user=user, auth_method="jwt")

    raise AuthenticationError(
        "Autentifikatsiya talab qilinadi: `Authorization: Bearer <token>` "
        f"yoki `{HEADER_API_KEY}` header'ini yuboring"
    )


def _bind_principal_context(
    request: Request, user_id: uuid.UUID, auth_method: Literal["jwt", "api_key"]
) -> None:
    """Foydalanuvchini `request.state` va log kontekstiga yozadi.

    `RequestLoggingMiddleware` so'rov oxirida `request.state.user_id` ni o'qib
    `http.request.finished` yozuviga qo'shadi.
    """
    request.state.user_id = str(user_id)
    request.state.auth_method = auth_method
    bind_request_context(user_id=user_id, auth_method=auth_method)


async def get_current_user(
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> User:
    """Autentifikatsiyadan o'tgan foydalanuvchi (faollik TEKSHIRILMAYDI)."""
    return principal.user


async def get_current_active_user(
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> User:
    """Faol foydalanuvchi — endpointlarning standart talabi.

    `resolve_token`/`resolve_api_key` ham faollikni tekshiradi, lekin bu
    yerda qayta tekshirish ataylab qoldirilgan: autentifikatsiya natijasi
    kelajakda cache'lansa ham endpoint faolsizlantirilgan hisobga javob
    bermaydi.

    Raises:
        InactiveUserError: Hisob `is_active=False`.
    """
    if not principal.user.is_active:
        raise InactiveUserError()
    return principal.user


async def require_admin(
    user: Annotated[User, Depends(get_current_active_user)],
) -> User:
    """Administrator huquqini talab qiladi.

    Raises:
        AdminRequiredError: Foydalanuvchi admin emas (403).
    """
    if not user.is_admin:
        logger.warning(
            "admin bo'lmagan foydalanuvchi admin endpointga urindi",
            user_id=str(user.id),
        )
        raise AdminRequiredError()
    return user


def require_scope(scope: ApiKeyScope) -> Callable[..., Awaitable[Principal]]:
    """Endpoint uchun API kalit ruxsat doirasini talab qiladigan dependency.

    ## Semantika — uch qoida

    1. **JWT bilan kirilgan bo'lsa scope TEKSHIRILMAYDI.** Scope —
       mashina hisob ma'lumotining xususiyati. Foydalanuvchi o'z nomidan
       kirganda u allaqachon to'liq huquqqa ega (dashboard ham shu
       yo'ldan ishlaydi).
    2. **`scopes` bo'sh ro'yxat bo'lsa — to'liq huquq.** Bu ORQAGA
       MOSLIK uchun: majburlash qo'shilishidan oldin yaratilgan kalitlar
       bo'sh ro'yxat bilan yozilgan va ular ishlashdan to'xtamasligi
       kerak. `ApiKeyCreate` tavsifi ham "bo'sh ro'yxat — barcha
       standart huquqlar" deb yozilgan.
    3. **`ADMIN` scope hammasini qamraydi.** Frontend tavsifi ham
       shunday: "everything above, plus billing, webhooks, team and
       API key management".

    ## Nega `Principal` qaytaradi, `User` emas

    Endpoint odatda `CurrentUser` ni alohida oladi. Bu dependency esa
    `dependencies=[...]` ro'yxatida ishlatiladi, ya'ni qaytargan qiymati
    ishlatilmaydi — lekin `Principal` qaytarish testlarda to'g'ridan-
    to'g'ri chaqirib tekshirishni osonlashtiradi.

    Args:
        scope: Talab qilinadigan doira.

    Returns:
        FastAPI dependency funksiyasi.
    """

    async def dependency(principal: CurrentPrincipal) -> Principal:
        """Kalitning doirasi yetarli ekanini tekshiradi."""
        if principal.auth_method != "api_key" or principal.api_key is None:
            return principal

        granted = [str(item) for item in (principal.api_key.scopes or [])]
        # Bo'sh ro'yxat — to'liq huquq (orqaga moslik, yuqoridagi 2-qoida).
        if not granted:
            return principal
        if ApiKeyScope.ADMIN.value in granted or scope.value in granted:
            return principal

        logger.warning(
            "API kalit doirasi yetarli emas",
            user_id=str(principal.user.id),
            api_key_id=str(principal.api_key.id),
            required_scope=scope.value,
            granted_scopes=granted,
        )
        raise ApiKeyScopeError(required=scope.value, granted=granted)

    return dependency


async def get_ws_user(
    websocket: WebSocket,
    session: DbSession,
    token: Annotated[str | None, Query(description="JWT access token yoki API kalit")] = None,
) -> User:
    """WebSocket ulanishini foydalanuvchiga bog'laydi.

    Token query parametridan olinadi (`/ws/jobs?token=<jwt>`), chunki brauzer
    `WebSocket` API'si header yuborishga ruxsat bermaydi.

    **MUHIM:** bu funksiya `WebSocketException` TASHLAMAYDI — oddiy domen
    xatosi (`AuthenticationError` va hokazo) tashlaydi. Sababi: WebSocket
    uchun FastAPI exception handler'lari ishlamaydi, shuning uchun router
    xatoni o'zi tutib `await websocket.close(code=1008)` qiladi va sababini
    mijozga yuboradi.

    Args:
        websocket: Joriy ulanish.
        token: `?token=` query parametri (hujjatlashtirish uchun e'lon
            qilingan; haqiqiy qiymat `extract_ws_token` bilan olinadi —
            u `access_token` nomini va header'larni ham qo'llab-quvvatlaydi).
        session: DB sessiyasi.

    Raises:
        AuthenticationError: Token yo'q.
        InvalidApiKeyError | InvalidTokenError | TokenExpiredError: Yaroqsiz.
        InactiveUserError: Hisob faolsizlantirilgan.
    """
    raw = token.strip() if token else extract_ws_token(websocket)
    if not raw:
        raise AuthenticationError("WebSocket uchun `?token=` parametri talab qilinadi")

    auth_service = AuthService(session)
    if is_api_key_format(raw):
        user, _ = await auth_service.resolve_api_key(raw)
    else:
        user = await auth_service.resolve_token(raw)

    if not user.is_active:
        raise InactiveUserError()
    bind_request_context(user_id=user.id)
    return user


# ---------------------------------------------------------------------------
# So'rov metama'lumotlari
# ---------------------------------------------------------------------------


async def get_idempotency_key(
    request: Request,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias=HEADER_IDEMPOTENCY_KEY,
            description=(
                "Takroriy `POST /jobs` so'rovini xavfsiz qilish uchun kalit "
                "(8..255 belgi, `[A-Za-z0-9_.:-]`)."
            ),
        ),
    ] = None,
) -> str | None:
    """`Idempotency-Key` header'ini qaytaradi.

    `IdempotencyMiddleware` kalitni allaqachon tekshirib
    `request.state.idempotency_key` ga yozgan bo'lishi mumkin — shu qiymat
    ustun turadi (ikki marta validatsiya qilinmaydi). Middleware ishlamagan
    holatda (masalan unit testda endpoint to'g'ridan-to'g'ri chaqirilsa)
    header'dan o'qiladi.
    """
    cached = getattr(request.state, "idempotency_key", None)
    if isinstance(cached, str) and cached:
        return cached
    if idempotency_key is None:
        return None
    value = idempotency_key.strip()
    return value or None


async def get_correlation_id(
    request: Request,
    correlation_id: Annotated[
        str | None,
        Header(
            alias=HEADER_CORRELATION_ID,
            description="Job'ning butun hayot siklini bog'laydigan identifikator.",
        ),
    ] = None,
) -> str:
    """So'rovning correlation ID'si.

    Manba tartibi: `X-Correlation-ID` -> `X-Request-ID`
    (`RequestLoggingMiddleware` har doim to'ldiradi) -> yangi yaratiladi.
    Qiymat `request.state.correlation_id` ga va log kontekstiga yoziladi,
    shuning uchun shu so'rov ichidagi barcha log yozuvlarida ko'rinadi.
    """
    existing = getattr(request.state, "correlation_id", None)
    if isinstance(existing, str) and existing:
        return existing

    value = (correlation_id or "").strip()
    if not value:
        value = (request.headers.get(HEADER_REQUEST_ID) or "").strip()
    if not value:
        # `RequestLoggingMiddleware` mijoz header yubormaganda ham ID yasaydi.
        value = (getattr(request.state, "request_id", "") or "").strip()
    if not value:
        value = generate_correlation_id()

    request.state.correlation_id = value
    bind_request_context(correlation_id=value)
    return value


# ---------------------------------------------------------------------------
# Service fabrikalari
# ---------------------------------------------------------------------------


async def get_auth_service(session: DbSession) -> AuthService:
    """`AuthService` — faqat sessiya kerak."""
    return AuthService(session)


async def get_billing_service(session: DbSession) -> BillingService:
    """`BillingService` — faqat sessiya kerak."""
    return BillingService(session)


async def get_job_service(session: DbSession, redis: RedisDep) -> JobService:
    """`JobService` — job yuborish, ro'yxat, bekor qilish."""
    return JobService(session, redis)


async def get_execution_service(session: DbSession, redis: RedisDep) -> ExecutionService:
    """`ExecutionService` — bajarishlar va loglar."""
    return ExecutionService(session, redis)


async def get_webhook_service(session: DbSession, redis: RedisDep) -> WebhookService:
    """`WebhookService` — webhook CRUD va yuborish."""
    return WebhookService(session, redis)


async def get_reliability_service(session: DbSession, redis: RedisDep) -> ReliabilityService:
    """`ReliabilityService` — lease, retry, DLQ."""
    return ReliabilityService(session, redis)


async def get_analytics_service(session: DbSession, redis: RedisDep) -> AnalyticsService:
    """`AnalyticsService` — statistika va vaqt qatorlari."""
    return AnalyticsService(session, redis)


async def get_queue_service(redis: RedisDep) -> QueueService:
    """`QueueService` — faqat Redis bilan ishlaydi."""
    return QueueService(redis)


async def get_cache_service(redis: RedisDep) -> CacheService:
    """`CacheService` — umumiy cache qatlami."""
    return CacheService(redis)


async def get_idempotency_service(redis: RedisDep) -> IdempotencyService:
    """`IdempotencyService` — takroriy so'rovlarni aniqlash."""
    return IdempotencyService(redis)


# ---------------------------------------------------------------------------
# Qisqartma `Annotated` turlari (endpointlar shularni ishlatadi)
# ---------------------------------------------------------------------------

CurrentPrincipal = Annotated[Principal, Depends(get_current_principal)]
CurrentUser = Annotated[User, Depends(get_current_active_user)]
AdminUser = Annotated[User, Depends(require_admin)]
WsUser = Annotated[User, Depends(get_ws_user)]

#: Router darajasida ishlatiladigan scope darvozalari.
#:
#: `APIRouter(dependencies=[...])` butun routerga qo'llanadi — bu 45
#: endpointni bitta-bitta belgilashdan ancha xatosizroq: yangi endpoint
#: qo'shilganda u AVTOMATIK himoyalanadi, belgilashni unutib bo'lmaydi.
#:
#: Aralash (o'qish + yozish) routerlar uchun esa endpoint darajasida
#: beriladi — `jobs` va `dlq` shunday.
ScopeJobsRead = Depends(require_scope(ApiKeyScope.JOBS_READ))
ScopeJobsWrite = Depends(require_scope(ApiKeyScope.JOBS_WRITE))
ScopeDlqRead = Depends(require_scope(ApiKeyScope.DLQ_READ))
ScopeDlqWrite = Depends(require_scope(ApiKeyScope.DLQ_WRITE))
ScopeAdmin = Depends(require_scope(ApiKeyScope.ADMIN))

Pagination = Annotated[PaginationParams, Depends(pagination_params)]
IdempotencyKey = Annotated[str | None, Depends(get_idempotency_key)]
CorrelationId = Annotated[str, Depends(get_correlation_id)]

AuthSvc = Annotated[AuthService, Depends(get_auth_service)]
BillingSvc = Annotated[BillingService, Depends(get_billing_service)]
JobSvc = Annotated[JobService, Depends(get_job_service)]
ExecutionSvc = Annotated[ExecutionService, Depends(get_execution_service)]
WebhookSvc = Annotated[WebhookService, Depends(get_webhook_service)]
ReliabilitySvc = Annotated[ReliabilityService, Depends(get_reliability_service)]
#: DLQ endpointlari ham `ReliabilityService` ni ishlatadi (alohida service yo'q).
DlqSvc = ReliabilitySvc
AnalyticsSvc = Annotated[AnalyticsService, Depends(get_analytics_service)]
QueueSvc = Annotated[QueueService, Depends(get_queue_service)]
CacheSvc = Annotated[CacheService, Depends(get_cache_service)]
IdempotencySvc = Annotated[IdempotencyService, Depends(get_idempotency_service)]


__all__ = [
    "APIKEY_CACHE_TTL_SECONDS",
    "PLAN_CACHE_TTL_SECONDS",
    "AdminUser",
    "AnalyticsSvc",
    "AuthSvc",
    "BillingSvc",
    "CacheSvc",
    "CorrelationId",
    "CurrentPrincipal",
    "CurrentUser",
    "DbSession",
    "DlqSvc",
    "ExecutionSvc",
    "IdempotencyKey",
    "IdempotencySvc",
    "JobSvc",
    "Pagination",
    "Principal",
    "QueueSvc",
    "RedisDep",
    "ReliabilitySvc",
    "WebhookSvc",
    "WsUser",
    "get_analytics_service",
    "get_auth_service",
    "get_billing_service",
    "get_cache_service",
    "get_correlation_id",
    "get_current_active_user",
    "get_current_principal",
    "get_current_user",
    "get_execution_service",
    "get_idempotency_key",
    "get_idempotency_service",
    "get_job_service",
    "get_queue_service",
    "get_reliability_service",
    "get_webhook_service",
    "get_ws_user",
    "require_admin",
]
