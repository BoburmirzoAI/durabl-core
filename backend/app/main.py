"""Durabl — FastAPI ilovasining yagona kirish nuqtasi.

Bu modul UCH ishni bajaradi va boshqa hech narsa qilmaydi:

1. **Hayot sikli** (`lifespan`) — logging, DB va Redis ulanishlarini
   tekshirish, bootstrap admin, chiqishda ulanishlarni yopish.
2. **Ilovani yig'ish** (`create_app`) — middleware, exception handler'lar,
   servis endpointlari (`/health`, `/ready`, `/metrics`, `/`) va routerlar.
3. **Protsess kirish nuqtasi** — `if __name__ == "__main__"` ichida uvicorn.

## Nima bu yerda YO'Q

* **Worker'lar.** `worker_pool`, `scheduler`, `dlq_processor` va
  `webhook_sender` — ALOHIDA protsesslar (`python -m app.workers.<nom>`).
  Ularni ilova ichida ishga tushirish API protsessini qulatganda job'larni
  ham to'xtatardi va gorizontal masshtablashni (API 10 nusxa, scheduler 1)
  imkonsiz qilardi.
* **Biznes logika.** Hamma qaror `app/services/` da; bu yerda faqat HTTP.
* **`setup_cors(app)` ning alohida chaqiruvi.** CORS'ni `setup_middleware`
  O'ZI eng oxirida qo'shadi (Starlette oxirgi qo'shilgan qatlamni ENG
  TASHQI qiladi, CORS esa 429/401/500 javoblarida ham header qo'yishi
  uchun eng tashqida bo'lishi SHART). Shuning uchun uni ikkinchi marta
  chaqirish `CORSMiddleware` ni ikki nusxada ulab, tartibni buzardi.

## Nega Redis xatosi ilovani ko'tarilishdan to'xtatmaydi

Job'lar DB'da saqlanadi, navbat esa Redis'da. Redis qulaganda yangi job
navbatga tushmaydi (`POST /jobs` 503 beradi), lekin `GET /jobs`,
`/health` va butun o'qish qismi ishlashi KERAK — aks holda operator
nosozlikni diagnostika qila olmaydi va orkestrator (compose/k8s) butun
ilovani restart halqasiga tushirib yuboradi. Shuning uchun Redis nosozligi
— WARNING, DB nosozligi esa ishga tushishni to'xtatadi (DB'siz hech qanday
endpoint ma'noga ega emas).

## Xato javoblari shakli

Barcha 4xx/5xx (FastAPI'ning o'z 404/405'i ham, tutilmagan xato ham) AYNI
konvertda qaytadi, chunki frontend `src/lib/api.ts` va ikki SDK aynan
shuni kutadi:

```json
{"error": {"code": "NOT_FOUND", "message": "...", "details": {...}}, "request_id": "..."}
```

`request_id` ni `RequestLoggingMiddleware` har so'rovda
`request.state.request_id` ga yozadi.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from http import HTTPStatus
from typing import TYPE_CHECKING, Any, Final

from fastapi import FastAPI, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import Field
from pydantic import ValidationError as PydanticValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.api.v1 import websocket
from app.config import settings
from app.database import check_db_health, close_db, init_db, session_scope
from app.exceptions import (
    DuplicateEmailError,
    DurablError,
    RateLimitExceededError,
)
from app.exceptions import (
    ValidationError as DomainValidationError,
)
from app.logging_config import get_logger, setup_logging
from app.metrics import render_metrics
from app.middleware import setup_middleware
from app.middleware.rate_limit import HEADER_RETRY_AFTER
from app.redis_client import check_redis_health, close_redis
from app.schemas.admin import CHECK_DATABASE, CHECK_REDIS
from app.schemas.auth import RegisterRequest
from app.schemas.base import (
    DurablSchema,
    ErrorDetail,
    ErrorResponse,
    HealthStatus,
    ValidationErrorItem,
)
from app.services.auth_service import AuthService
from app.utils.time_utils import utcnow

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi uchun
    from collections.abc import AsyncIterator, Sequence

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Konstantalar
# ---------------------------------------------------------------------------

#: Protsess ishga tushgan payt — `uptime_seconds` shundan hisoblanadi.
#: Modul darajasida: import paytida bir marta qo'yiladi va `lifespan`
#: qayta ishga tushsa ham (testlarda ilova bir necha marta yasaladi)
#: o'zgarmaydi.
_STARTED_AT: Final[datetime] = utcnow()

#: Bootstrap admin uchun ko'rinadigan ism.
BOOTSTRAP_ADMIN_NAME: Final = "Durabl administrator"

#: Tutilmagan xato uchun production'da ko'rsatiladigan xabar — tafsilot
#: (stack trace, SQL matni, ichki yo'llar) mijozga chiqmasligi kerak.
INTERNAL_ERROR_MESSAGE: Final = "Ichki xato yuz berdi"

#: `/health` javobidagi `status` qiymatlari (`HealthStatus` bilan mos).
STATUS_OK: Final = "ok"
STATUS_DEGRADED: Final = "degraded"
STATUS_DOWN: Final = "down"

#: Validatsiya xatosi tafsilotlari shu kalit ostida qaytadi.
VALIDATION_DETAILS_KEY: Final = "errors"

#: Pydantic `loc` yo'lining bo'laklarini ajratuvchi (`"body.code"`).
LOC_SEPARATOR: Final = "."

#: Starlette'ning o'z `HTTPException` statuslari uchun barqaror kodlar.
#: Ro'yxatda yo'q status uchun kod `HTTPStatus` nomidan yasaladi
#: (`418 -> I_M_A_TEAPOT`), ya'ni mijoz har doim `error.code` ni oladi.
HTTP_ERROR_CODES: Final[dict[int, str]] = {
    status.HTTP_400_BAD_REQUEST: "BAD_REQUEST",
    status.HTTP_401_UNAUTHORIZED: "AUTHENTICATION_REQUIRED",
    status.HTTP_403_FORBIDDEN: "PERMISSION_DENIED",
    status.HTTP_404_NOT_FOUND: "NOT_FOUND",
    status.HTTP_405_METHOD_NOT_ALLOWED: "METHOD_NOT_ALLOWED",
    status.HTTP_409_CONFLICT: "CONFLICT",
    status.HTTP_413_CONTENT_TOO_LARGE: "PAYLOAD_TOO_LARGE",
    status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: "UNSUPPORTED_MEDIA_TYPE",
    status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMIT_EXCEEDED",
    status.HTTP_500_INTERNAL_SERVER_ERROR: "INTERNAL_ERROR",
    status.HTTP_503_SERVICE_UNAVAILABLE: "SERVICE_UNAVAILABLE",
}

#: OpenAPI bo'limlari — `/docs` dagi tartib va o'zbekcha tavsiflar.
OPENAPI_TAGS: Final[list[dict[str, Any]]] = [
    {
        "name": "auth",
        "description": (
            "Ro'yxatdan o'tish, kirish, token yangilash va profil. "
            "Parol almashtirish va profilni o'zgartirish FAQAT JWT bilan "
            "ishlaydi — o'g'irlangan API kalit bilan hisobni egallab olish "
            "mumkin bo'lmasligi uchun."
        ),
    },
    {
        "name": "api-keys",
        "description": (
            "Server-server integratsiyalari uchun API kalitlar. Xom kalit "
            "FAQAT yaratish javobida bir marta ko'rinadi — bazada uning "
            "SHA-256 hash'i saqlanadi."
        ),
    },
    {
        "name": "jobs",
        "description": (
            "Job yuborish, kuzatish, loglarini o'qish va bekor qilish — "
            "platformaning asosiy qismi. `POST /jobs` `Idempotency-Key` "
            "header'ini qo'llab-quvvatlaydi."
        ),
    },
    {
        "name": "executions",
        "description": (
            "Job'ning har bir BAJARISH urinishi (attempt). Retry bo'lgan "
            "job'da bir nechta urinish bo'ladi — diagnostika shu yerdan "
            "boshlanadi."
        ),
    },
    {
        "name": "webhooks",
        "description": (
            "Job hodisalarini o'z serveringizga yuborish. Har bir yuborish "
            "HMAC-SHA256 bilan imzolanadi; imzoni tekshirish majburiy."
        ),
    },
    {
        "name": "dlq",
        "description": (
            "Dead Letter Queue — barcha urinishlardan keyin ham yiqilgan "
            "job'lar. Sababini ko'rish, qayta urinish va hal qilingan deb "
            "belgilash."
        ),
    },
    {
        "name": "analytics",
        "description": (
            "Dashboard uchun agregatlar: oqim, muvaffaqiyat foizi, kechikish "
            "persentillari va DLQ chuqurligi. Javoblar qisqa muddat "
            "keshlanadi."
        ),
    },
    {
        "name": "billing",
        "description": (
            "Rejalar, joriy iste'mol va obuna. `GET /billing/plans` ochiq "
            "(narx sahifasi uchun), qolgani autentifikatsiya talab qiladi."
        ),
    },
    {
        "name": "admin",
        "description": (
            "Administratorlar uchun: tizim holati, foydalanuvchilar, barcha "
            "job'lar va audit jurnali. Har bir o'zgartirish `audit_logs` ga "
            "yoziladi."
        ),
    },
    {
        "name": "websocket",
        "description": (
            "`WS /ws/jobs?token=<jwt>` — job hodisalarining real vaqtli "
            "oqimi. OpenAPI WebSocket'ni hujjatlashtirmaydi, shuning uchun "
            "bu bo'lim bo'sh ko'rinadi."
        ),
    },
    {
        "name": "system",
        "description": (
            "Infratuzilma endpointlari: `/health` (compose va k8s liveness), "
            "`/ready` (readiness), `/metrics` (Prometheus) va ildiz "
            "ma'lumoti. Autentifikatsiya talab qilmaydi."
        ),
    },
]

#: Ilova tavsifi — `/docs` ning bosh sahifasida ko'rinadi.
API_DESCRIPTION: Final = """
**Durabl** — ishonchli background job va kod bajarish platformasi.
Kodni (Python yoki Node.js) yuborasiz, Durabl uni izolyatsiyalangan
sandbox'da bajaradi, yiqilsa eksponensial backoff bilan qayta uradi,
umidsiz holatda esa Dead Letter Queue'ga o'tkazadi — hech qanday job
jimgina yo'qolmaydi.

### Autentifikatsiya — ikki usul

| Usul | Header | Qachon |
|---|---|---|
| JWT | `Authorization: Bearer <access_token>` | Brauzer va dashboard |
| API kalit | `X-API-Key: durabl_...` | Server-server, SDK, CI |

`POST /auth/login` `access_token` (qisqa muddatli) va `refresh_token`
qaytaradi. Profilni o'zgartirish, parol almashtirish va API kalit
boshqaruvi **faqat JWT** bilan ishlaydi: o'g'irlangan kalit bilan yangi
kalit yasash yoki parolni almashtirish privilegiyani oshirish bo'lardi.

### Idempotency

`POST /jobs` da `Idempotency-Key: <8..255 belgi>` header'ini yuboring.
Tarmoq uzilib so'rovni takrorlasangiz YANGI job yaratilmaydi — ayni job
qaytadi va status **200** bo'ladi (yangi yaratilganda **201**). Kalit
shakli: `[A-Za-z0-9_.:-]`.

### Sahifalash

Barcha ro'yxat endpointlari `?page`, `?page_size`, `?sort_by`,
`?sort_order` qabul qiladi va bir xil konvertda javob beradi:

```json
{"items": [...], "pagination": {"page": 1, "page_size": 20, "total": 42,
  "total_pages": 3, "has_next": true, "has_prev": false}}
```

### Xato formati

Har qanday 4xx/5xx AYNI shaklda qaytadi — `error.code` barqaror va
mijoz kodida tekshirish uchun mo'ljallangan:

```json
{"error": {"code": "JOB_NOT_FOUND", "message": "...", "details": {}},
 "request_id": "01J..."}
```

`request_id` ni yordam so'rovida yuboring — server loglari aynan shu
identifikator bo'yicha qidiriladi.

### So'rov chastotasi limiti

Limit rejaga bog'liq va har bir javobda ko'rsatiladi:

| Header | Ma'nosi |
|---|---|
| `X-RateLimit-Limit` | Daqiqadagi ruxsat |
| `X-RateLimit-Remaining` | Shu daqiqada qolgani |
| `X-RateLimit-Reset` | Hisoblagich nollanadigan payt (Unix) |

Limit oshsa **429 `RATE_LIMIT_EXCEEDED`** va `Retry-After` header'i
qaytadi.

### Webhook imzosi

Har bir yuborishda `X-Durabl-Signature: sha256=<hex>` va
`X-Durabl-Timestamp` header'lari bo'ladi. Imzo —
`HMAC-SHA256(secret, "<timestamp>.<xom tana>")`. Imzoni **xom tana**
ustida tekshiring (JSON'ni qayta serializatsiya qilmasdan) va
`timestamp` 5 daqiqadan oshgan so'rovni rad eting (replay himoyasi).
Ikki SDK'da tayyor funksiya bor: `verify_webhook` / `verifyWebhook`.
""".strip()


# ---------------------------------------------------------------------------
# Ildiz endpointi javobi
# ---------------------------------------------------------------------------


class ServiceInfo(DurablSchema):
    """`GET /` javobi — xizmatni tez aniqlash uchun."""

    name: str = Field(description="Ilova nomi")
    version: str = Field(description="Ilova versiyasi")
    environment: str = Field(description="Muhit: development/test/staging/production")
    api_prefix: str = Field(description="Versiyalangan API prefiksi")
    docs_url: str | None = Field(description="Interaktiv hujjat (o'chirilgan bo'lsa `null`)")
    health_url: str = Field(description="Sog'liq tekshiruvi endpointi")


# ---------------------------------------------------------------------------
# Hayot sikli
# ---------------------------------------------------------------------------


async def _safe_check(check: Callable[[], Awaitable[bool]], *, name: str) -> bool:
    """Sog'liq tekshiruvini bajaradi va HAR QANDAY xatoni `False` ga aylantiradi.

    `check_db_health`/`check_redis_health` o'zi ham xatoni yutadi, lekin
    klient YARATISHDA (masalan noto'g'ri `REDIS_URL`) istisno chiqishi
    mumkin. `/health` endpointi hech qachon 500 bermasligi kerak — aks
    holda orkestrator "ilova yiqildi" deb qaror qiladi, holbuki sabab
    pastki tizimda.

    Args:
        check: Sog'liqni qaytaruvchi async funksiya.
        name: Log uchun pastki tizim nomi.

    Returns:
        Pastki tizim javob berdimi.
    """
    try:
        return await check()
    except Exception as exc:
        logger.warning("sog'liq tekshiruvi xato berdi", subsystem=name, error=str(exc))
        return False


async def _check_subsystems() -> dict[str, bool]:
    """DB va Redis'ni PARALLEL tekshiradi.

    Ketma-ket tekshirish ikki timeout'ni qo'shardi (`/health` sekin
    bo'lsa healthcheck'ning o'zi "unhealthy" deb belgilanadi), shuning
    uchun `asyncio.gather`.
    """
    database, redis_ok = await asyncio.gather(
        _safe_check(check_db_health, name=CHECK_DATABASE),
        _safe_check(check_redis_health, name=CHECK_REDIS),
    )
    return {CHECK_DATABASE: database, CHECK_REDIS: redis_ok}


def _uptime_seconds() -> float:
    """Protsess ishga tushgandan beri o'tgan vaqt (soniya)."""
    return (utcnow() - _STARTED_AT).total_seconds()


async def _bootstrap_admin() -> None:
    """Sozlamada ko'rsatilgan birinchi administratorni yaratadi.

    `BOOTSTRAP_ADMIN_EMAIL` va `BOOTSTRAP_ADMIN_PASSWORD` ikkisi ham
    berilgan bo'lsa ishlaydi. `AuthService.register()` ayni shu emailni
    `is_admin=True` bilan yaratadi (boshqa yo'l bilan admin bo'lib
    ro'yxatdan o'tish mumkin emas), shuning uchun bu yerda `users`
    jadvaliga bevosita yozilmaydi — qatlam qoidasi saqlanadi.

    Hisob allaqachon bo'lsa `DuplicateEmailError` chiqadi va u NORMAL
    holat deb qabul qilinadi: funksiya idempotent, ya'ni har ishga
    tushishda xavfsiz chaqiriladi.

    Ishga tushishni to'xtatadigan xato YO'Q: admin yaratilmasligi
    (masalan parol talablarga javob bermasligi) sababli butun API'ni
    ko'tarmaslik nomutanosib bo'lardi — ogohlantirish yoziladi.
    """
    email = settings.BOOTSTRAP_ADMIN_EMAIL
    password = settings.BOOTSTRAP_ADMIN_PASSWORD
    if not email or not password:
        return

    try:
        data = RegisterRequest(email=email, password=password, full_name=BOOTSTRAP_ADMIN_NAME)
    except PydanticValidationError as exc:
        logger.warning(
            "bootstrap admin sozlamasi yaroqsiz",
            email=email,
            error_count=exc.error_count(),
        )
        return

    try:
        async with session_scope() as session:
            user = await AuthService(session).register(data)
    except DuplicateEmailError:
        logger.info("bootstrap admin allaqachon mavjud", email=email)
    except DurablError as exc:
        logger.warning("bootstrap admin yaratilmadi", email=email, code=exc.code)
    else:
        logger.info(
            "bootstrap admin yaratildi",
            email=email,
            user_id=str(user.id),
            is_admin=user.is_admin,
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Ilovaning ishga tushish va to'xtash ketma-ketligi.

    Ishga tushish:

    1. `setup_logging()` — structlog. Eng birinchi, shunda qolgan
       qadamlarning loglari ham to'g'ri formatda chiqadi.
    2. `init_db()` — ulanishni tekshiradi. **Test muhitida**
       `create_all=True`: testlar Alembic ishlatmaydi, sxema SQLite
       xotira bazasida joyida yaratiladi.
    3. `check_redis_health()` — nosoz bo'lsa WARNING (yuqoridagi modul
       docstring'ida sababi tushuntirilgan).
    4. `_bootstrap_admin()` — birinchi administrator.

    To'xtash: Redis va DB ulanishlari yopiladi (shu TARTIBDA — Redis
    yengil, DB esa ochiq tranzaksiyalarni kutishi mumkin).

    Args:
        app: Ishga tushayotgan ilova (FastAPI shartnomasi talab qiladi).
    """
    setup_logging()
    logger.info(
        "ilova ishga tushmoqda",
        app=settings.APP_NAME,
        version=settings.APP_VERSION,
        env=settings.ENV,
        api_prefix=settings.API_V1_PREFIX,
        routes=len(app.routes),
    )

    await init_db(create_all=settings.is_test)

    if not await _safe_check(check_redis_health, name=CHECK_REDIS):
        logger.warning(
            "Redis javob bermadi — ilova DEGRADED rejimda ko'tariladi "
            "(navbat va cache ishlamaydi, o'qish endpointlari ishlaydi)",
            redis_url=settings.REDIS_URL,
        )

    await _bootstrap_admin()

    logger.info("ilova tayyor", uptime_seconds=round(_uptime_seconds(), 3))
    try:
        yield
    finally:
        logger.info("ilova to'xtatilmoqda")
        with contextlib.suppress(Exception):
            await close_redis()
        with contextlib.suppress(Exception):
            await close_db()
        logger.info("ilova to'xtadi")


# ---------------------------------------------------------------------------
# Exception handler'lar
# ---------------------------------------------------------------------------


def _error_response(
    request: Request,
    detail: ErrorDetail,
    *,
    status_code: int,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    """`ErrorResponse` konvertida JSON javob yasaydi.

    `exclude_none=True`: `details` yoki `request_id` yo'q bo'lsa maydon
    JSON'da UMUMAN chiqmaydi (frontend va SDK `null` emas, YO'Q deb
    kutadi).

    Args:
        request: Joriy so'rov — `request_id` shundan olinadi.
        detail: Xato tafsiloti.
        status_code: HTTP status.
        headers: Qo'shimcha javob header'lari (`Retry-After`, `Allow`).
    """
    payload = ErrorResponse(
        error=detail,
        request_id=getattr(request.state, "request_id", None),
    ).model_dump(mode="json", exclude_none=True)
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


def _format_loc(loc: Sequence[Any]) -> str:
    """Pydantic `loc` ni o'qiladigan maydon yo'liga aylantiradi.

    `("body", "code")` -> `"body.code"`,
    `("body", "tags", 0)` -> `"body.tags.0"`.
    Bo'sh `loc` (modelning o'zi haqidagi xato) -> `"body"`.
    """
    if not loc:
        return "body"
    return LOC_SEPARATOR.join(str(part) for part in loc)


def _validation_details(errors: Sequence[Any]) -> dict[str, Any]:
    """Validatsiya xatolarini `details.errors` ro'yxatiga aylantiradi."""
    items = [
        ValidationErrorItem(
            field=_format_loc(error.get("loc", ())),
            message=str(error.get("msg", "")),
            type=str(error.get("type", "")),
        )
        for error in errors
    ]
    return {VALIDATION_DETAILS_KEY: [item.model_dump(mode="json") for item in items]}


async def durabl_error_handler(request: Request, exc: DurablError) -> JSONResponse:
    """Domen xatolari — loyihadagi 54 ta xato klassining hammasi.

    Status va kod xatoning O'ZIDA (`exc.status_code`, `exc.code`), shuning
    uchun handler'da `if` zinapoyasi yo'q: yangi xato klassi qo'shilsa
    bu yer o'zgarmaydi.

    `RateLimitExceededError` da `Retry-After` qo'yiladi — HTTP standarti
    talabi va SDK'lar shu header bo'yicha kutadi. (Middleware'dan kelgan
    429 bu handler'ga YETIB KELMAYDI — middleware exception handler'lardan
    TASHQARIDA ishlaydi va javobni o'zi yasaydi; bu yo'l servis qatlami
    429 tashlaganda ishlaydi.)

    4xx `warning`, 5xx `error` bilan log qilinadi: mijoz xatosi (noto'g'ri
    UUID) va server xatosi (DB uzildi) bir xil darajada bo'lsa alertlar
    ma'nosini yo'qotadi.
    """
    headers: dict[str, str] | None = None
    retry_after = getattr(exc, "retry_after", None)
    if isinstance(exc, RateLimitExceededError) and retry_after is not None:
        headers = {HEADER_RETRY_AFTER: str(int(retry_after))}

    context: dict[str, Any] = {
        "code": exc.code,
        "status_code": exc.status_code,
        "method": request.method,
        "path": request.url.path,
        "error": exc.message,
    }
    if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        logger.error("domen xatosi (server)", **context)
    else:
        logger.warning("domen xatosi (mijoz)", **context)

    return _error_response(
        request,
        ErrorDetail(**exc.to_dict()),
        status_code=exc.status_code,
        headers=headers,
    )


async def request_validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """FastAPI'ning so'rov validatsiyasi — 422.

    Tana, query, path va header xatolari shu yerga keladi. Har bir xato
    `{field, message, type}` ko'rinishida `details.errors` ga tushadi,
    shunda frontend formadagi AYNI maydon yonida xabar ko'rsata oladi.
    """
    logger.warning(
        "so'rov validatsiyasi yiqildi",
        method=request.method,
        path=request.url.path,
        error_count=len(exc.errors()),
    )
    return _error_response(
        request,
        ErrorDetail(
            code=DomainValidationError.code,
            message=DomainValidationError.message,
            details=_validation_details(exc.errors()),
        ),
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


async def pydantic_validation_handler(
    request: Request, exc: PydanticValidationError
) -> JSONResponse:
    """XOM pydantic `ValidationError` — 422 (MAJBURIY handler).

    Nega kerak: `JobFilter`/`ExecutionFilter`/`DlqFilter` query
    dependency sifatida `Depends()` bilan ishlatiladi, ularning
    `model_validator(mode="after")` i esa yaroqsiz `sort_by` yoki teskari
    oraliq (`start > end`) uchun xom `pydantic_core.ValidationError`
    tashlaydi. FastAPI bu xatoni `RequestValidationError` ga AYLANTIRMAYDI
    (u `solve_dependencies` dan chiqib ketadi), demak bu handler bo'lmasa
    `GET /dlq?sort_by=yoq` **500** berardi.

    Javob shakli `RequestValidationError` bilan AYNI — mijoz uchun
    farq bo'lmasligi kerak.
    """
    logger.warning(
        "dependency validatsiyasi yiqildi",
        method=request.method,
        path=request.url.path,
        model=exc.title,
        error_count=exc.error_count(),
    )
    return _error_response(
        request,
        ErrorDetail(
            code=DomainValidationError.code,
            message=DomainValidationError.message,
            details=_validation_details(exc.errors()),
        ),
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


async def http_exception_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Starlette/FastAPI'ning o'z `HTTPException` i — `ErrorResponse` ga o'raladi.

    Buning yo'qligi eng ko'p uchraydigan ikki javobni (404 noma'lum yo'l,
    405 noto'g'ri metod) standart Starlette shaklida — `{"detail": "..."}`
    — qoldirardi. Mijoz esa `error.code` ni o'qiydi, ya'ni oddiy xato
    "tushunarsiz javob" ga aylanardi.

    `exc.headers` saqlanadi: 405 javobidagi `Allow` header'i yo'qolmasligi
    kerak.
    """
    code = HTTP_ERROR_CODES.get(exc.status_code)
    if code is None:
        with contextlib.suppress(ValueError):
            code = HTTPStatus(exc.status_code).phrase.upper().replace(" ", "_")
    message = str(exc.detail) if exc.detail else (code or INTERNAL_ERROR_MESSAGE)

    logger.warning(
        "HTTP xatosi",
        status_code=exc.status_code,
        method=request.method,
        path=request.url.path,
        error=message,
    )
    return _error_response(
        request,
        ErrorDetail(code=code or "HTTP_ERROR", message=message),
        status_code=exc.status_code,
        headers=dict(exc.headers) if exc.headers else None,
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Tutilmagan xato — 500.

    Production'da mijozga faqat umumiy xabar va `request_id` qaytadi:
    istisno matni SQL so'rovini, fayl yo'lini yoki sirni oshkor qilishi
    mumkin. Development va test muhitida esa `str(exc)` qaytadi — aks
    holda dasturchi har xatoda log faylini qidirishga majbur bo'lardi.

    `logger.exception` stack trace'ni TO'LIQ yozadi, ya'ni ma'lumot
    yo'qolmaydi.
    """
    logger.exception(
        "tutilmagan xato",
        method=request.method,
        path=request.url.path,
        error_type=type(exc).__name__,
    )
    message = INTERNAL_ERROR_MESSAGE if settings.is_production else str(exc)
    return _error_response(
        request,
        ErrorDetail(
            code=HTTP_ERROR_CODES[status.HTTP_500_INTERNAL_SERVER_ERROR],
            message=message or INTERNAL_ERROR_MESSAGE,
        ),
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _register_exception_handlers(app: FastAPI) -> None:
    """Barcha handler'larni ulaydi (eng aniqdan eng umumiyga).

    Starlette handler'ni istisno TURI bo'yicha (MRO bilan) tanlaydi,
    shuning uchun ro'yxat tartibi ahamiyatsiz — lekin o'qish uchun
    aniqdan umumiyga yozilgan.
    """
    app.add_exception_handler(DurablError, durabl_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, request_validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(PydanticValidationError, pydantic_validation_handler)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)


# ---------------------------------------------------------------------------
# Servis endpointlari
# ---------------------------------------------------------------------------


def _register_service_routes(app: FastAPI) -> None:
    """`/health`, `/ready`, `/metrics` va `/` ni qo'shadi.

    Hammasi prefiksisiz va autentifikatsiyasiz: compose healthcheck,
    k8s probe va Prometheus scraper token yubora olmaydi.
    """

    @app.get(
        "/health",
        response_model=HealthStatus,
        tags=["system"],
        summary="Sog'liq tekshiruvi",
        description=(
            "Pastki tizimlarni (DB, Redis) PARALLEL tekshiradi. "
            "`ok` — hammasi ishlaydi; `degraded` — Redis javob bermaydi "
            "(o'qish ishlaydi, navbat ishlamaydi) va status kodi hamon "
            "**200**; `down` — DB javob bermaydi, status kodi **503**. "
            "Compose/k8s liveness probe shu endpointni ishlatadi."
        ),
        responses={
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": HealthStatus,
                "description": "DB javob bermaydi — ilova ishlay olmaydi",
            }
        },
    )
    async def health(response: Response) -> HealthStatus:
        """Liveness: ilova va pastki tizimlar holati."""
        checks = await _check_subsystems()
        if not checks[CHECK_DATABASE]:
            state = STATUS_DOWN
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        elif not all(checks.values()):
            state = STATUS_DEGRADED
        else:
            state = STATUS_OK
        return HealthStatus(
            status=state,
            version=settings.APP_VERSION,
            environment=settings.ENV,
            checks=checks,
            uptime_seconds=_uptime_seconds(),
        )

    @app.get(
        "/ready",
        response_model=HealthStatus,
        tags=["system"],
        summary="Tayyorlik tekshiruvi",
        description=(
            "Readiness probe: DB **va** Redis ikkisi ham SHART. `/health` "
            "dan farqi — bu yerda `degraded` holat YO'Q, chunki Redis'siz "
            "ilova yangi job qabul qila olmaydi, ya'ni trafik yuborish "
            "ma'nosiz. Tayyor bo'lmasa **503** qaytadi va orkestrator "
            "nusxani balanserdan chiqaradi (lekin RESTART qilmaydi — "
            "liveness alohida)."
        ),
        responses={
            status.HTTP_503_SERVICE_UNAVAILABLE: {
                "model": HealthStatus,
                "description": "Pastki tizimlardan biri tayyor emas",
            }
        },
    )
    async def ready(response: Response) -> HealthStatus:
        """Readiness: trafik qabul qilishga tayyormi."""
        checks = await _check_subsystems()
        is_ready = all(checks.values())
        if not is_ready:
            response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthStatus(
            status=STATUS_OK if is_ready else STATUS_DOWN,
            version=settings.APP_VERSION,
            environment=settings.ENV,
            checks=checks,
            uptime_seconds=_uptime_seconds(),
        )

    if settings.METRICS_ENABLED:

        @app.get(
            settings.METRICS_PATH,
            tags=["system"],
            summary="Prometheus metrikalari",
            description=(
                "Prometheus matn formatidagi metrikalar. "
                "`settings.METRICS_ENABLED=False` bo'lsa endpoint UMUMAN "
                "qo'shilmaydi (404) — scraper'ga bo'sh javob berishdan "
                "ko'ra yo'qligi aniqroq signal."
            ),
            include_in_schema=False,
        )
        async def metrics() -> Response:
            """Prometheus uchun joriy metrikalar."""
            body, content_type = render_metrics()
            return Response(content=body, media_type=content_type)

    @app.get(
        "/",
        response_model=ServiceInfo,
        tags=["system"],
        summary="Xizmat ma'lumoti",
        description=(
            "Ilova nomi, versiyasi, muhiti va hujjat havolasi. Xizmatni "
            "tez aniqlash uchun (`curl <host>/`)."
        ),
    )
    async def root() -> ServiceInfo:
        """Ildiz: xizmat haqida qisqa ma'lumot."""
        return ServiceInfo(
            name=settings.APP_NAME,
            version=settings.APP_VERSION,
            environment=settings.ENV,
            api_prefix=settings.API_V1_PREFIX,
            docs_url=settings.docs_url,
            health_url="/health",
        )


# ---------------------------------------------------------------------------
# Ilovani yig'ish
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    """To'liq sozlangan FastAPI ilovasini yasaydi.

    Fabrika funksiyasi (global obyekt emas), chunki testlar har bir
    sinov uchun toza ilova yasashi kerak: middleware'ni ilova
    ishlagandan keyin qo'shish mumkin emas, ya'ni global obyektni
    "qayta sozlash" imkonsiz.

    Qadamlar tartibi MUHIM:

    1. `FastAPI(...)` — lifespan va hujjat sozlamalari;
    2. `setup_middleware(app)` — har qanday so'rovdan OLDIN
       (Starlette ilova ishga tushgandan keyin middleware qo'shishga
       ruxsat bermaydi);
    3. exception handler'lar;
    4. servis endpointlari;
    5. routerlar.

    Returns:
        Ishga tushirishga tayyor ilova.
    """
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=API_DESCRIPTION,
        summary="Ishonchli background job va kod bajarish platformasi",
        lifespan=lifespan,
        docs_url=settings.docs_url,
        redoc_url=settings.redoc_url,
        openapi_url=settings.openapi_url,
        openapi_tags=OPENAPI_TAGS,
        # Noma'lum yo'lda `/jobs/` -> `/jobs` ga avtomatik redirect
        # ATAYLAB o'chirilmagan: SDK'lar ba'zan oxirgi `/` bilan chaqiradi.
        redirect_slashes=True,
    )

    # Middleware: CORS -> Logging -> RateLimit -> Idempotency tartibini
    # `setup_middleware` O'ZI ta'minlaydi (CORS ni ham o'zi qo'shadi).
    setup_middleware(app)

    _register_exception_handlers(app)
    _register_service_routes(app)

    # Versiyalangan API — prefiks FAQAT shu yerda beriladi.
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    # WebSocket ildizda: `WS /ws/jobs`. Router o'zida `tags=["websocket"]`
    # bor, shuning uchun bu yerda qayta berilmaydi (dublikat tag).
    app.include_router(websocket.router, prefix="/ws")

    logger.info(
        "ilova yig'ildi",
        routes=len(app.routes),
        env=settings.ENV,
        docs=settings.docs_url,
    )
    return app


#: Uvicorn ishlatadigan ASGI ilovasi (`uvicorn app.main:app`).
app = create_app()


if __name__ == "__main__":  # pragma: no cover - qo'lda ishga tushirish
    import uvicorn

    # Host va port — `settings` da ATAYLAB yo'q: ular joylashtirish
    # (deployment) qarori va Docker `CMD` / `make dev` orqali beriladi
    # (`uvicorn app.main:app --host ... --port ...`). Shu blok faqat
    # `python -m app.main` bilan tezkor sinov uchun.
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=settings.is_development,
        log_level=settings.LOG_LEVEL.lower(),
    )


__all__ = [
    "API_DESCRIPTION",
    "BOOTSTRAP_ADMIN_NAME",
    "HTTP_ERROR_CODES",
    "INTERNAL_ERROR_MESSAGE",
    "OPENAPI_TAGS",
    "STATUS_DEGRADED",
    "STATUS_DOWN",
    "STATUS_OK",
    "ServiceInfo",
    "app",
    "create_app",
    "durabl_error_handler",
    "http_exception_handler",
    "lifespan",
    "pydantic_validation_handler",
    "request_validation_handler",
    "unhandled_exception_handler",
]
