"""Durabl — autentifikatsiya yordamchilari (middleware EMAS).

Bu modul ataylab middleware emas: haqiqiy autentifikatsiya `dependencies.py`
dagi `get_current_principal` ichida, ya'ni DB sessiyasi mavjud bo'lgan joyda
bajariladi. Middleware'da sessiya ochish har bir so'rovga (hatto ommaviy
yo'llarga ham) qimmat yuk qo'shardi va `Depends()` zanjiri bilan ikki marta
tekshirishga olib kelardi.

Shuning uchun bu yerda faqat **toza funksiyalar** bor: so'rovdan ma'lumot
ajratib olish va yo'lning ommaviy (auth talab qilmaydigan) ekanini aniqlash.
Ularni `dependencies.py` ham, `rate_limit.py` middleware'i ham ishlatadi —
mantiq bir joyda saqlanadi.
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.websockets import WebSocket

from app.config import settings
from app.constants import HEADER_API_KEY
from app.utils.security import is_api_key_format

#: `Authorization` header'idagi kutilgan sxema (registrdan qat'i nazar)
_BEARER_SCHEME = "bearer"

#: WebSocket ulanishida token qidiriladigan query parametr nomlari
_WS_TOKEN_PARAMS = ("token", "access_token")


def extract_bearer_token(request: Request) -> str | None:
    """`Authorization: Bearer <token>` dan xom tokenni ajratadi.

    Qaytgan qiymat JWT ham, API kalit ham bo'lishi mumkin — mijozlar ko'pincha
    API kalitni ham `Bearer` ichida yuboradi. Turini ajratish chaqiruvchining
    mas'uliyatida (`is_api_key_format()` yoki `extract_credentials()`).

    Args:
        request: Joriy HTTP so'rovi.

    Returns:
        Token matni yoki header yo'q/noto'g'ri shaklda bo'lsa `None`.
    """
    header = request.headers.get("Authorization")
    if not header:
        return None
    scheme, _, credentials = header.partition(" ")
    if scheme.strip().lower() != _BEARER_SCHEME:
        return None
    token = credentials.strip()
    return token or None


def extract_api_key(request: Request) -> str | None:
    """`X-API-Key` header'idan API kalitni ajratadi.

    FAQAT maxsus header'ga qaraydi (`Authorization` ichidagi kalitni topish
    uchun `extract_credentials()` ishlatiladi) — shu tufayli funksiya bitta
    ishni bajaradi va testlash oson.

    Args:
        request: Joriy HTTP so'rovi.

    Returns:
        Kalit matni yoki `None`.
    """
    raw = request.headers.get(HEADER_API_KEY)
    if raw is None:
        return None
    key = raw.strip()
    return key or None


def extract_credentials(request: Request) -> tuple[str | None, str | None]:
    """So'rovdan `(api_key, jwt)` juftligini ajratadi.

    Qoidalar:

    1. `X-API-Key` header'i bo'lsa — u API kalit.
    2. Bo'lmasa `Authorization: Bearer <...>` qaraladi: qiymat
       `settings.API_KEY_PREFIX` bilan boshlansa (`is_api_key_format`) u ham
       API kalit deb qabul qilinadi, aks holda JWT deb hisoblanadi.

    Ikkinchi qoida ataylab kiritilgan: SDK'lardan tashqari mijozlar (curl,
    Postman namunalari) API kalitni `Bearer` ichida yuborishga odatlangan va
    ularga 401 qaytarish foydasiz noqulaylik tug'diradi.

    Args:
        request: Joriy HTTP so'rovi.

    Returns:
        `(api_key, jwt)` — ikkisi ham `None` bo'lishi mumkin, lekin bir
        vaqtda ikkisi ham to'ldirilmaydi.
    """
    api_key = extract_api_key(request)
    if api_key is not None:
        return api_key, None

    bearer = extract_bearer_token(request)
    if bearer is None:
        return None, None
    if is_api_key_format(bearer):
        return bearer, None
    return None, bearer


def extract_ws_token(websocket: WebSocket) -> str | None:
    """WebSocket ulanishidan tokenni ajratadi.

    Brauzerning `WebSocket` API'si maxsus header yuborishga ruxsat bermaydi,
    shuning uchun token query parametrida keladi: `/ws/jobs?token=<jwt>`.
    Zaxira sifatida `Authorization` header'i ham qaraladi (server-server
    ulanishlari va testlar uchun qulay).

    Args:
        websocket: Joriy WebSocket ulanishi.

    Returns:
        Token matni yoki `None`.
    """
    for name in _WS_TOKEN_PARAMS:
        raw = websocket.query_params.get(name)
        if raw:
            token = raw.strip()
            if token:
                return token

    header = websocket.headers.get("Authorization")
    if header:
        scheme, _, credentials = header.partition(" ")
        if scheme.strip().lower() == _BEARER_SCHEME:
            token = credentials.strip()
            if token:
                return token

    api_key = websocket.headers.get(HEADER_API_KEY)
    if api_key and api_key.strip():
        return api_key.strip()
    return None


def _api_path(suffix: str) -> str:
    """`settings.API_V1_PREFIX` ostidagi to'liq yo'l."""
    return f"{settings.API_V1_PREFIX.rstrip('/')}{suffix}"


#: Aniq moslik bo'yicha ommaviy yo'llar — auth talab qilinmaydi.
#:
#: DIQQAT: to'plam modul import qilinganda hisoblanadi. Agar test
#: `reload_settings()` bilan `API_V1_PREFIX` ni o'zgartirsa, `is_public_path`
#: joriy prefiksni ham qo'shimcha ravishda tekshiradi (quyida).
PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/",
        "/health",
        "/ready",
        "/metrics",
        settings.METRICS_PATH,
        "/docs",
        "/redoc",
        "/openapi.json",
        "/favicon.ico",
        _api_path("/auth/login"),
        _api_path("/auth/register"),
        _api_path("/auth/refresh"),
        _api_path("/billing/plans"),
    }
)

#: Prefiks bo'yicha ommaviy yo'llar — ostidagi hamma narsa ochiq.
#: `/docs/oauth2-redirect` va `/redoc/...` kabi Swagger yordamchi yo'llari
#: shu tufayli auth so'ramaydi.
PUBLIC_PATH_PREFIXES: tuple[str, ...] = ("/docs", "/redoc", "/static")

#: Auth talab qilmaydigan ommaviy yo'l suffikslari (prefiks o'zgarsa ham ishlaydi)
_PUBLIC_API_SUFFIXES: tuple[str, ...] = (
    "/auth/login",
    "/auth/register",
    "/auth/refresh",
    "/billing/plans",
)


def _normalize(path: str) -> str:
    """Yo'lni solishtirishga tayyorlaydi (oxirgi `/` olib tashlanadi)."""
    if len(path) > 1 and path.endswith("/"):
        return path.rstrip("/")
    return path


def is_public_path(path: str) -> bool:
    """Yo'l autentifikatsiya talab qilmaydimi?

    Tekshirish tartibi: aniq moslik -> prefiks moslik -> joriy
    `API_V1_PREFIX` ostidagi ommaviy suffikslar.

    Args:
        path: So'rov yo'li (`request.url.path`).

    Returns:
        `True` — ochiq yo'l, `False` — token kerak.
    """
    candidate = _normalize(path)
    if candidate in PUBLIC_PATHS:
        return True
    for prefix in PUBLIC_PATH_PREFIXES:
        if candidate == prefix or candidate.startswith(f"{prefix}/"):
            return True
    prefix = settings.API_V1_PREFIX.rstrip("/")
    return any(candidate == f"{prefix}{suffix}" for suffix in _PUBLIC_API_SUFFIXES)


__all__ = [
    "PUBLIC_PATHS",
    "PUBLIC_PATH_PREFIXES",
    "extract_api_key",
    "extract_bearer_token",
    "extract_credentials",
    "extract_ws_token",
    "is_public_path",
]
