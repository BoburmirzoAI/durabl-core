"""Durabl — `JobKind.HTTP` uchun uchidan-uchiga testlar.

## Nega alohida fayl

`test_full_flow.py` kod rejimining (`JobKind.CODE`) butun zanjirini
qoplaydi: yuborish -> navbat -> sandbox -> natija -> webhook. HTTP
rejimi esa AYNI zanjirdan o'tadi, lekin bajarish qadami boshqa —
`HttpRunner` mijozning endpointini chaqiradi.

Shu testlarning maqsadi aynan **umumiylikni** isbotlash: HTTP job
hech qanday maxsus yo'l talab qilmasdan lease, retry, DLQ va
idempotency kafolatlarini oladi. Agar kelgusida kimdir HTTP uchun
alohida qisqa yo'l qo'shsa, bu testlar buzilib e'tiborni tortadi.

## Mijozning serveri `respx` bilan ushlanadi

Haqiqiy tarmoq so'rovi ketmaydi. `respx` `httpx` darajasida ushlaydi,
ya'ni `HttpRunner` ning HAQIQIY kodi (header yasash, tana, status
tasnifi) bajariladi — faqat tarmoq chetlab o'tiladi.

## SSRF validatori mock qilinadi

`example.com` kabi nom DNS so'rovini talab qiladi. Birlik testlarida
bo'lgani kabi, validator o'rnini bosuvchi bilan almashtiriladi —
uning o'zi `tests/unit/test_validators.py` da to'liq qoplangan, HTTP
runner'dagi chaqiruvi esa `tests/unit/test_http_runner.py` da
tekshiriladi.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest
import respx
from app.constants import FailureReason, HttpMethod, JobKind, JobStatus
from app.execution import http_runner as http_runner_module
from httpx import Response

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from collections.abc import Awaitable, Callable

    from app.models.execution import Execution
    from app.models.job import Job

pytestmark = pytest.mark.e2e

#: Mijozning "o'z serveri" — haqiqiy so'rov ketmaydi.
TARGET_URL = "https://api.durabl-mijoz.dev/nightly-report"


@pytest.fixture(autouse=True)
def _skip_ssrf(monkeypatch: pytest.MonkeyPatch) -> None:
    """SSRF validatorini o'rnini bosuvchi bilan almashtiradi (DNS yo'q).

    Ikki joyda: `HttpRunner` (bajarish paytida) va `JobCreate` sxemasi
    (yuborish paytida). Ikkisi ham AYNI validatorni chaqiradi, lekin
    har biri o'z moduliga import qilgan.
    """

    async def _noop_async(url: str, **_: Any) -> None:
        return None

    def _noop_sync(url: str, **_: Any) -> None:
        return None

    monkeypatch.setattr(http_runner_module, "validate_webhook_url_async", _noop_async)
    monkeypatch.setattr("app.schemas.job.validate_webhook_url", _noop_sync)


async def submit_http_job(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    **overrides: Any,
) -> dict[str, Any]:
    """HTTP job yuboradi va javob tanasini qaytaradi."""
    body: dict[str, Any] = {
        "kind": JobKind.HTTP.value,
        "target_url": TARGET_URL,
        "http_method": HttpMethod.POST.value,
        "payload": {"sana": "2026-10-10"},
        "max_retries": 2,
    }
    body.update(overrides)
    response = await client.post(f"{api_prefix}/jobs", headers=auth_headers, json=body)
    assert response.status_code == 201, response.text
    return dict(response.json())


# ---------------------------------------------------------------------------
# Muvaffaqiyatli oqim
# ---------------------------------------------------------------------------


@respx.mock
async def test_http_job_endpointni_chaqiradi_va_natijani_saqlaydi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    run_until: Callable[..., Awaitable[Job]],
) -> None:
    """To'liq oqim: yuborish -> navbat -> chaqiruv -> SUCCESS + natija."""
    route = respx.post(TARGET_URL).mock(
        return_value=Response(201, json={"yuborildi": 42}),
    )

    created = await submit_http_job(client, api_prefix, auth_headers)
    assert created["kind"] == JobKind.HTTP.value
    assert created["target_url"] == TARGET_URL
    # Kod rejimi maydonlari bo'sh.
    assert created["code"] is None

    job = await run_until(created["id"], JobStatus.SUCCESS)

    # --- Mijozning serveri HAQIQATAN chaqirilgan ---
    assert route.call_count == 1
    sent = route.calls.last.request
    assert sent.method == "POST"
    # Durabl o'z header'larini qo'ygan.
    assert sent.headers["X-Durabl-Job-Id"] == created["id"]
    assert sent.headers["X-Durabl-Attempt"] == "1"
    # `payload` so'rov tanasiga tushgan.
    assert sent.read() == b'{"sana": "2026-10-10"}'

    # --- Natija job'da saqlangan ---
    assert job.exit_code == 0
    assert job.failure_reason is None
    # Javob tanasi natija sifatida.
    assert job.result == {"value": {"yuborildi": 42}}
    # Haqiqiy status kodi ALOHIDA ustunda: `exit_code` muvaffaqiyatda
    # 0 bo'lishi shart, shuning uchun 201 shu yerda saqlanadi.
    assert job.response_status == 201

    # --- API ham shu maydonlarni qaytaradi ---
    fetched = await client.get(f"{api_prefix}/jobs/{created['id']}", headers=auth_headers)
    assert fetched.status_code == 200
    payload = fetched.json()
    assert payload["kind"] == JobKind.HTTP.value
    assert payload["response_status"] == 201
    assert payload["http_method"] == HttpMethod.POST.value


@respx.mock
async def test_get_metodida_tana_yuborilmaydi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    run_until: Callable[..., Awaitable[Job]],
) -> None:
    """`GET` da `payload` tanaga AYLANMAYDI (proxy'lar rad etadi)."""
    route = respx.get(TARGET_URL).mock(return_value=Response(200, text="ok"))

    created = await submit_http_job(
        client, api_prefix, auth_headers, http_method=HttpMethod.GET.value
    )
    await run_until(created["id"], JobStatus.SUCCESS)

    assert route.calls.last.request.read() == b""


# ---------------------------------------------------------------------------
# Xato oqimlari — bu yerda butun ishonchlilik zanjiri sinaladi
# ---------------------------------------------------------------------------


@respx.mock
async def test_5xx_qayta_urinadi_keyin_DLQga_tushadi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    run_until: Callable[..., Awaitable[Job]],
    fetch_executions: Callable[..., Awaitable[list[Execution]]],
) -> None:
    """5xx vaqtinchalik deb hisoblanadi: urinishlar tugagach DLQ.

    Bu test HTTP job'ning retry zanjiriga HECH QANDAY maxsus kod
    qo'shilmaganini isbotlaydi — `max_retries=2` bo'lsa uch urinish
    bo'ladi va keyin `DEAD_LETTER`.
    """
    route = respx.post(TARGET_URL).mock(return_value=Response(503, text="band"))

    created = await submit_http_job(client, api_prefix, auth_headers)

    # `advance_seconds` — backoff'ni haqiqatan kutmaslik uchun.
    job = await run_until(created["id"], JobStatus.DEAD_LETTER, advance_seconds=60)

    assert job.retry_count == 2
    assert job.failure_reason is FailureReason.HTTP_SERVER_ERROR
    assert job.exit_code == 503
    # Uch urinish = uch chaqiruv.
    assert route.call_count == 3
    assert len(await fetch_executions(created["id"])) == 3


@respx.mock
async def test_4xx_QAYTA_URINILMAYDI_darhol_DLQga(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    run_until: Callable[..., Awaitable[Job]],
) -> None:
    """4xx mijoz xatosi: `max_retries` bo'lsa ham BITTA urinish.

    Mahsulot uchun muhim: yo'q endpoint yoki noto'g'ri token uch marta
    urinishdan tuzalmaydi, faqat mijozning kvotasi yeyiladi. Shuning
    uchun `HTTP_CLIENT_ERROR` `NON_RETRYABLE_REASONS` ichida.
    """
    route = respx.post(TARGET_URL).mock(return_value=Response(404, text="yo'q"))

    created = await submit_http_job(client, api_prefix, auth_headers)
    job = await run_until(created["id"], JobStatus.DEAD_LETTER, advance_seconds=60)

    assert job.failure_reason is FailureReason.HTTP_CLIENT_ERROR
    assert job.exit_code == 404
    # `max_retries=2` bo'lsa ham qayta urinilmagan.
    assert job.retry_count == 0
    assert route.call_count == 1


@respx.mock
async def test_ulanmasa_qayta_urinadi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    run_until: Callable[..., Awaitable[Job]],
) -> None:
    """Ulanish xatosi vaqtinchalik — qayta urinadi."""
    route = respx.post(TARGET_URL).mock(side_effect=httpx.ConnectError("ulanmadi"))

    created = await submit_http_job(client, api_prefix, auth_headers, max_retries=1)
    job = await run_until(created["id"], JobStatus.DEAD_LETTER, advance_seconds=60)

    assert job.failure_reason is FailureReason.HTTP_CONNECT_ERROR
    assert route.call_count == 2


# ---------------------------------------------------------------------------
# Idempotency — HTTP maydonlari izga kirishi
# ---------------------------------------------------------------------------


@respx.mock
async def test_ayni_kalit_ayni_sorov_bitta_job(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
) -> None:
    """Ayni `Idempotency-Key` + ayni so'rov -> bitta job (200 qaytadi)."""
    respx.post(TARGET_URL).mock(return_value=Response(200))
    headers = {**auth_headers, "Idempotency-Key": "http-job-1"}
    body = {
        "kind": JobKind.HTTP.value,
        "target_url": TARGET_URL,
        "http_method": HttpMethod.POST.value,
    }

    first = await client.post(f"{api_prefix}/jobs", headers=headers, json=body)
    second = await client.post(f"{api_prefix}/jobs", headers=headers, json=body)

    assert first.status_code == 201
    # Takroriy so'rov — 200 va AYNI job.
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


@respx.mock
async def test_ayni_kalit_BOSHQA_url_toqnashuv(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
) -> None:
    """Ayni kalit, BOSHQA `target_url` -> 409 to'qnashuv.

    ## Nega bu test eng muhimlaridan biri

    `kind=http` da `code` bo'sh, ya'ni ishning mazmuni butunlay
    `target_url` da. Agar barmoq izi HTTP maydonlarini qamramasa,
    `/a` va `/b` ga ketadigan ikki job AYNI iz berardi va ikkinchisi
    "takroriy so'rov" deb qabul qilinib, **hech qachon
    bajarilmasdan** birinchisining natijasini qaytarardi.

    Ya'ni mijozning ishi jimgina yo'qolardi — eng yomon xato turi.
    """
    respx.post(url__regex=r"https://api\.durabl-mijoz\.dev/.*").mock(return_value=Response(200))
    headers = {**auth_headers, "Idempotency-Key": "http-job-2"}

    first = await client.post(
        f"{api_prefix}/jobs",
        headers=headers,
        json={"kind": "http", "target_url": "https://api.durabl-mijoz.dev/a"},
    )
    second = await client.post(
        f"{api_prefix}/jobs",
        headers=headers,
        json={"kind": "http", "target_url": "https://api.durabl-mijoz.dev/b"},
    )

    assert first.status_code == 201
    assert second.status_code == 409, second.text


# ---------------------------------------------------------------------------
# Qayta yuborish va ro'yxat
# ---------------------------------------------------------------------------


@respx.mock
async def test_http_job_qayta_yuboriladi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
) -> None:
    """`POST /jobs/{id}/resubmit` HTTP job uchun ham ishlaydi.

    `resubmit` `JobCreate` ni QAYTA yasaydi, ya'ni rejimga qarab
    boshqa maydon to'plami kerak. Busiz HTTP job'ni qayta yuborish
    "`code` berilishi shart" xatosi bilan yiqilardi.
    """
    respx.post(TARGET_URL).mock(return_value=Response(200))
    created = await submit_http_job(client, api_prefix, auth_headers)

    again = await client.post(f"{api_prefix}/jobs/{created['id']}/resubmit", headers=auth_headers)

    assert again.status_code == 201, again.text
    assert again.json()["id"] != created["id"]
    assert again.json()["kind"] == JobKind.HTTP.value
    assert again.json()["target_url"] == TARGET_URL


@respx.mock
async def test_royxat_kind_boyicha_filtrlanadi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
) -> None:
    """`GET /jobs?kind=http` faqat HTTP job'larni qaytaradi."""
    respx.post(TARGET_URL).mock(return_value=Response(200))
    await submit_http_job(client, api_prefix, auth_headers)
    code_job = await client.post(
        f"{api_prefix}/jobs",
        headers=auth_headers,
        json={"code": "print('salom')", "runtime": "python"},
    )
    assert code_job.status_code == 201

    http_only = await client.get(f"{api_prefix}/jobs?kind=http", headers=auth_headers)
    code_only = await client.get(f"{api_prefix}/jobs?kind=code", headers=auth_headers)

    assert [item["kind"] for item in http_only.json()["items"]] == [JobKind.HTTP.value]
    assert [item["kind"] for item in code_only.json()["items"]] == [JobKind.CODE.value]


# ---------------------------------------------------------------------------
# Validatsiya — mos kelmaydigan maydonlar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "kutilgan_matn"),
    [
        ({"kind": "http"}, "target_url"),
        ({"kind": "http", "target_url": TARGET_URL, "code": "print(1)"}, "code"),
        (
            {"kind": "http", "target_url": TARGET_URL, "env_vars": {"A": "1"}},
            "env_vars",
        ),
        ({"kind": "code", "code": "print(1)"}, "runtime"),
        (
            {"kind": "code", "code": "print(1)", "runtime": "python", "target_url": TARGET_URL},
            "target_url",
        ),
    ],
)
async def test_mos_kelmaydigan_maydonlar_rad_etiladi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    body: dict[str, Any],
    kutilgan_matn: str,
) -> None:
    """Rejimga mos kelmaydigan maydon JIM O'TKAZILMAYDI — 422.

    Jim e'tiborsiz qoldirish yomonroq bo'lardi: mijoz kodini yuborib,
    u hech qachon bajarilmaganini bilmay qolardi.
    """
    response = await client.post(f"{api_prefix}/jobs", headers=auth_headers, json=body)

    assert response.status_code == 422, response.text
    assert kutilgan_matn in response.text


async def test_durabl_headeri_rad_etiladi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
) -> None:
    """`X-Durabl-*` header'i band — mijoz uni bera olmaydi.

    `HttpRunner` ularni baribir bosib o'tadi, ya'ni jim qabul qilish
    mijozni chalg'itardi.
    """
    response = await client.post(
        f"{api_prefix}/jobs",
        headers=auth_headers,
        json={
            "kind": "http",
            "target_url": TARGET_URL,
            "http_headers": {"X-Durabl-Attempt": "99"},
        },
    )

    assert response.status_code == 422, response.text
    assert "X-Durabl" in response.text
