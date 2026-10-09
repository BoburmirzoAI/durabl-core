"""Durabl — middleware zanjirining integratsiya testlari.

## Nega tartib test bilan muzlatilgan

`Starlette.add_middleware()` yangi qatlamni ro'yxat BOSHIGA qo'yadi, ya'ni
OXIRGI qo'shilgan qatlam eng TASHQI bo'ladi. `setup_middleware()` shu
sababli teskari tartibda yozilgan. Tartib buzilsa 429 va 500 javoblarida
CORS header'i bo'lmaydi va brauzer xatoni o'qiy olmaydi — frontend'da
"Network Error" degan tushunarsiz xabar chiqadi. Shuning uchun haqiqiy
bajarilish tartibi alohida test bilan qulflangan.

## Nega `RATE_LIMIT_ENABLED` `monkeypatch` bilan yoqiladi

`conftest.py` limitni O'CHIRIB qo'yadi (anonim limit daqiqada 20 ta, FREE
reja 30 ta — o'nlab so'rov yuboradigan testlar bir-birini 429 bilan
yiqitardi). `RateLimitMiddleware.dispatch()` sozlamani HAR SO'ROVDA
o'qiydi, shuning uchun uni shu faylda vaqtincha yoqish yetarli —
ilovani qayta yasash kerak emas.

## 500 testi uchun `raise_app_exceptions=False`

Starlette'ning `ServerErrorMiddleware` javobni YUBORGANDAN keyin istisnoni
QAYTA tashlaydi. `conftest.py` dagi `client` fixture'i transportni
`raise_app_exceptions=False` bilan yasagani uchun istisno testga qaytmaydi
va javob tanasini tekshirish mumkin bo'ladi.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from app.config import settings
from app.constants import (
    HEADER_IDEMPOTENCY_KEY,
    HEADER_RATELIMIT_LIMIT,
    HEADER_RATELIMIT_REMAINING,
    HEADER_RATELIMIT_RESET,
    HEADER_REQUEST_ID,
)
from app.middleware import middleware_order
from app.middleware.idempotency_middleware import MAX_KEY_LENGTH, MIN_KEY_LENGTH
from app.middleware.logging_middleware import HEADER_RESPONSE_TIME
from app.services.analytics_service import AnalyticsService

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    import httpx
    from fastapi import FastAPI

pytestmark = pytest.mark.integration

#: `setup_middleware()` kafolatlaydigan BAJARILISH tartibi (tashqidan ichkariga).
EXPECTED_ORDER = [
    "CORSMiddleware",
    "RequestLoggingMiddleware",
    "RateLimitMiddleware",
    "IdempotencyMiddleware",
]

#: Preflight so'rovida ishlatiladigan origin (`settings.CORS_ORIGINS` dagi).
ALLOWED_ORIGIN = "http://localhost:3000"

#: Oddiy job tanasi (idempotency testlari uchun).
JOB_BODY = {"code": "def main(payload):\n    return 1\n", "runtime": "python"}


def assert_error_envelope(body: dict[str, Any]) -> dict[str, Any]:
    """Javob `{"error": {...}}` konvertida ekanini talab qiladi."""
    assert set(body) <= {"error", "request_id"}, body
    error = body["error"]
    assert isinstance(error, dict)
    assert isinstance(error["code"], str)
    assert isinstance(error["message"], str)
    return error


async def test_middleware_order(app: FastAPI) -> None:
    """Qatlamlar kelishilgan tartibda ulangan (modul docstring'iga qara)."""
    assert [name for name, _ in middleware_order(app)] == EXPECTED_ORDER


async def test_request_id_generated(client: httpx.AsyncClient, api_prefix: str) -> None:
    """`X-Request-ID` berilmasa yaratiladi va javobda qaytadi."""
    response = await client.get(f"{api_prefix}/billing/plans")

    assert response.status_code == 200, response.text
    request_id = response.headers[HEADER_REQUEST_ID]
    assert len(request_id) == 32  # `uuid4().hex`


async def test_request_id_echoed_and_clipped(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    """Mijoz yuborgan `X-Request-ID` saqlanadi, 64 belgidan uzun qiymat kesiladi."""
    response = await client.get(
        f"{api_prefix}/billing/plans", headers={HEADER_REQUEST_ID: "mening-izim-123"}
    )
    assert response.headers[HEADER_REQUEST_ID] == "mening-izim-123"

    long_id = "a" * 200
    clipped = await client.get(
        f"{api_prefix}/billing/plans", headers={HEADER_REQUEST_ID: long_id}
    )
    assert clipped.headers[HEADER_REQUEST_ID] == "a" * 64


async def test_request_id_in_error_body(client: httpx.AsyncClient, api_prefix: str) -> None:
    """Xato javobidagi `request_id` header bilan AYNI bo'ladi."""
    response = await client.get(
        f"{api_prefix}/jobs", headers={HEADER_REQUEST_ID: "xato-izi-0001"}
    )

    assert response.status_code == 401, response.text
    assert response.json()["request_id"] == "xato-izi-0001"
    assert response.headers[HEADER_REQUEST_ID] == "xato-izi-0001"


async def test_response_time_header(client: httpx.AsyncClient) -> None:
    """`X-Response-Time-ms` har javobda bor va son ko'rinishida."""
    response = await client.get("/health")

    assert response.status_code == 200, response.text
    # `/health` LOG qilinmaydi (`SILENT_PATHS`), lekin header'lar qo'yiladi.
    assert float(response.headers[HEADER_RESPONSE_TIME]) >= 0
    assert response.headers[HEADER_REQUEST_ID]


async def test_rate_limit_headers(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Limit yoqilganda `X-RateLimit-*` uchligi qaytadi va `remaining` kamayadi."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)

    first = await client.get(f"{api_prefix}/auth/me", headers=auth_headers)
    second = await client.get(f"{api_prefix}/auth/me", headers=auth_headers)

    assert first.status_code == 200, first.text
    limit = int(first.headers[HEADER_RATELIMIT_LIMIT])
    assert limit > 0
    assert int(first.headers[HEADER_RATELIMIT_RESET]) > 0
    assert int(first.headers[HEADER_RATELIMIT_REMAINING]) == limit - 1
    assert int(second.headers[HEADER_RATELIMIT_REMAINING]) == limit - 2


async def test_rate_limit_exceeded(
    client: httpx.AsyncClient, api_prefix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Limitdan oshgan so'rov 429, `Retry-After` va standart xato konverti."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)
    limit = settings.RATE_LIMIT_ANONYMOUS_PER_MINUTE

    response = None
    for _ in range(limit + 1):
        response = await client.get(f"{api_prefix}/billing/plans")
    assert response is not None

    assert response.status_code == 429, response.text
    error = assert_error_envelope(response.json())
    assert error["code"] == "RATE_LIMIT_EXCEEDED"
    assert error["details"]["limit"] == limit
    retry_after = int(response.headers["Retry-After"])
    assert 1 <= retry_after <= 60
    assert int(response.headers[HEADER_RATELIMIT_REMAINING]) == 0


async def test_options_requests_are_exempt(
    client: httpx.AsyncClient, api_prefix: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preflight (`OPTIONS`) limitga hisoblanmaydi — brauzer uni o'zi yuboradi."""
    monkeypatch.setattr(settings, "RATE_LIMIT_ENABLED", True)

    for _ in range(settings.RATE_LIMIT_ANONYMOUS_PER_MINUTE + 5):
        response = await client.options(
            f"{api_prefix}/jobs",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 200, response.text


async def test_cors_preflight(client: httpx.AsyncClient, api_prefix: str) -> None:
    """Preflight ruxsat etilgan origin, metod va header'larni qaytaradi."""
    response = await client.options(
        f"{api_prefix}/jobs",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": f"Authorization,{HEADER_IDEMPOTENCY_KEY}",
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "POST" in response.headers["access-control-allow-methods"]
    allowed = response.headers["access-control-allow-headers"]
    assert "Authorization" in allowed
    assert HEADER_IDEMPOTENCY_KEY in allowed


async def test_cors_headers_on_error_response(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    """CORS eng TASHQI qatlam: 401 javobida ham origin header'i bor."""
    response = await client.get(f"{api_prefix}/jobs", headers={"Origin": ALLOWED_ORIGIN})

    assert response.status_code == 401, response.text
    assert response.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    assert HEADER_REQUEST_ID in response.headers["access-control-expose-headers"]


@pytest.mark.parametrize(
    "key",
    ["ab", "x" * (MAX_KEY_LENGTH + 1), "bo'sh joy bor", "yulduz*belgi"],
    ids=["too_short", "too_long", "space", "bad_char"],
)
async def test_invalid_idempotency_key(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str], key: str
) -> None:
    """Yaroqsiz `Idempotency-Key` 400 `BAD_REQUEST` beradi (DB'ga tegmasdan)."""
    response = await client.post(
        f"{api_prefix}/jobs",
        headers={**auth_headers, HEADER_IDEMPOTENCY_KEY: key},
        json=JOB_BODY,
    )

    assert response.status_code == 400, response.text
    error = assert_error_envelope(response.json())
    assert error["code"] == "BAD_REQUEST"
    assert error["details"]["header"] == HEADER_IDEMPOTENCY_KEY


async def test_valid_idempotency_key_passes(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Chegaradagi eng qisqa yaroqli kalit o'tadi."""
    key = "k" * MIN_KEY_LENGTH

    response = await client.post(
        f"{api_prefix}/jobs",
        headers={**auth_headers, HEADER_IDEMPOTENCY_KEY: key},
        json=JOB_BODY,
    )

    assert response.status_code == 201, response.text
    assert response.json()["idempotency_key"] == key


async def test_idempotency_key_ignored_on_other_paths(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Middleware FAQAT `POST /jobs` ni ushlaydi — boshqa yo'lda kalit tekshirilmaydi."""
    response = await client.get(
        f"{api_prefix}/jobs", headers={**auth_headers, HEADER_IDEMPOTENCY_KEY: "ab"}
    )

    assert response.status_code == 200, response.text


async def test_unknown_path_error_shape(client: httpx.AsyncClient) -> None:
    """Noma'lum yo'l Starlette'ning `{"detail": ...}` emas, `{"error": ...}` beradi."""
    response = await client.get("/bunday-yol-yoq")

    assert response.status_code == 404, response.text
    body = response.json()
    assert "detail" not in body
    error = assert_error_envelope(body)
    assert error["code"] == "NOT_FOUND"


async def test_method_not_allowed_error_shape(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    """405 ham AYNI konvertda va `Allow` header'i saqlanadi."""
    response = await client.delete(f"{api_prefix}/auth/login")

    assert response.status_code == 405, response.text
    error = assert_error_envelope(response.json())
    assert error["code"] == "METHOD_NOT_ALLOWED"
    assert "POST" in response.headers["allow"]


async def test_internal_error_hidden_in_production(
    client: httpx.AsyncClient,
    api_prefix: str,
    admin_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production'da 500 javobi tafsilotni YASHIRADI, test muhitida KO'RSATADI."""
    secret = "ichki-sir-sql-matni"

    async def _boom(self: AnalyticsService) -> None:
        raise RuntimeError(secret)

    monkeypatch.setattr(AnalyticsService, "admin_stats", _boom)

    in_test = await client.get(f"{api_prefix}/admin/stats", headers=admin_headers)
    assert in_test.status_code == 500, in_test.text
    assert secret in in_test.json()["error"]["message"]

    monkeypatch.setattr(settings, "ENV", "production")
    in_production = await client.get(f"{api_prefix}/admin/stats", headers=admin_headers)

    assert in_production.status_code == 500, in_production.text
    error = assert_error_envelope(in_production.json())
    assert error["code"] == "INTERNAL_ERROR"
    assert secret not in error["message"]
    # `request_id` baribir qaytadi — operator log'ni shu bo'yicha topadi.
    assert in_production.json()["request_id"]


async def test_error_envelope_omits_empty_fields(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """`exclude_none=True`: `details` bo'lmasa JSON'da maydon UMUMAN yo'q."""
    response = await client.get(f"{api_prefix}/jobs/{'0' * 8}-0000-0000-0000-000000000000")

    assert response.status_code == 401, response.text
    body = response.json()
    assert "details" not in body["error"]

    with_details = await client.get(f"{api_prefix}/dlq?sort_by=yoq", headers=auth_headers)
    assert with_details.status_code == 422, with_details.text
    assert "details" in with_details.json()["error"]


__all__ = ["ALLOWED_ORIGIN", "EXPECTED_ORDER", "JOB_BODY", "assert_error_envelope"]
