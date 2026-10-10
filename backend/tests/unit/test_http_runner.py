"""Durabl — `app/execution/http_runner.py` birlik testlari.

## Nega bu testlar aynan shu narsalarni tekshiradi

`HttpRunner` mahsulotning ikkinchi ish rejimi (`JobKind.HTTP`) ning
butun yuragi: mijoz o'z endpointini ko'rsatadi, Durabl uni chaqiradi.
Shu sababli uchta narsa muhim va uchalasi ham JIM buzilishi mumkin:

1. **Xato tasnifi** — 4xx qayta urinilmasligi, 5xx qayta urinilishi.
   Agar 4xx ham qayta urinilsa, yo'q endpoint uchun mijozning kvotasi
   uch barobar yeyiladi va DLQ'ga tushish kechikadi. Teskarisi ham
   yomon: 5xx qayta urinilmasa, serverning bir soniyalik nosozligi
   job'ni butunlay yo'qotadi.

2. **SSRF tekshiruvi** — bajarishdan OLDIN chaqirilishi. Job yuborilgan
   paytda URL to'g'ri bo'lib, keyin DNS yozuvi ichki manzilga
   o'zgartirilishi mumkin (DNS rebinding). Tekshiruv chaqirilmasa, bu
   teshik jimgina ochiq qoladi — hech qanday test yiqilmaydi.

3. **Durabl header'lari** mijoz header'laridan USTUN turishi. Mijoz
   `X-Durabl-Attempt` ni o'zgartirib qabul qiluvchini chalg'itib
   yuborishi mumkin bo'lmasligi kerak.

## Nega SSRF validatori mock qilinadi

`validate_webhook_url_async()` DNS so'rovi qiladi. Birlik testida bu
(a) tarmoqqa bog'liqlik, (b) sekinlik, (c) CI'da tasodifiy yiqilish
manbai. Validatorning O'ZI `tests/unit/test_validators.py` da to'liq
qoplangan, shuning uchun bu yerda u o'rnini bosuvchi bilan
almashtiriladi — lekin CHAQIRILGANI alohida testda tekshiriladi.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import respx
from app.constants import FailureReason, HttpMethod, JobKind, LogStream, Runtime
from app.exceptions import SandboxError
from app.execution import http_runner as http_runner_module
from app.execution.http_runner import (
    HEADER_ATTEMPT,
    HEADER_JOB_ID,
    MAX_RESPONSE_PREVIEW_BYTES,
    HttpRunner,
    HttpRuntime,
)
from app.execution.types import ResourceLimits, RunnerOutcome, SandboxSpec

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from collections.abc import Callable

pytestmark = pytest.mark.unit

TARGET = "https://api.example.com/durabl/hook"


@pytest.fixture(autouse=True)
def _skip_ssrf(monkeypatch: pytest.MonkeyPatch) -> None:
    """SSRF validatorini o'rnini bosuvchi bilan almashtiradi (DNS yo'q).

    `autouse` — har testga qo'llanadi. Chaqirilganini tekshiradigan
    test o'zi alohida kuzatuvchi qo'yadi.
    """

    async def _noop(url: str, **_: Any) -> None:
        return None

    monkeypatch.setattr(http_runner_module, "validate_webhook_url_async", _noop)


def make_spec(
    *,
    method: HttpMethod = HttpMethod.POST,
    url: str = TARGET,
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    attempt: int = 1,
    timeout_seconds: int = 10,
) -> SandboxSpec:
    """HTTP rejimidagi `SandboxSpec` yasaydi."""
    return SandboxSpec(
        job_id="job-1",
        kind=JobKind.HTTP,
        runtime=Runtime.PYTHON,
        limits=ResourceLimits(timeout_seconds=timeout_seconds),
        target_url=url,
        http_method=method,
        http_headers=headers,
        payload=payload,
        attempt_number=attempt,
        correlation_id="corr-1",
    )


def collect_logs() -> tuple[list[tuple[LogStream, str]], Callable[[LogStream, str], None]]:
    """Log yig'uvchi va uning `LogSink` ko'rinishini qaytaradi."""
    seen: list[tuple[LogStream, str]] = []

    def sink(stream: LogStream, chunk: str) -> None:
        seen.append((stream, chunk))

    return seen, sink


# ---------------------------------------------------------------------------
# Muvaffaqiyatli chaqiruv
# ---------------------------------------------------------------------------


@respx.mock
async def test_2xx_muvaffaqiyat_va_json_natija() -> None:
    """2xx -> `ok=True`, `exit_code=0`, JSON tana tahlil qilingan natija."""
    respx.post(TARGET).mock(
        return_value=httpx.Response(200, json={"total": 42}),
    )

    outcome = await HttpRunner().run(make_spec(), HttpRuntime())

    assert outcome.exit_code == 0
    assert outcome.runner_payload.ok is True
    # Natija LUG'AT bo'lib keladi — mijoz `result["total"]` qila oladi.
    assert outcome.runner_payload.result == {"total": 42}
    assert outcome.timed_out is False


@respx.mock
async def test_json_bolmagan_tana_xom_matn_qoladi() -> None:
    """`content-type` JSON bo'lmasa natija xom matn bo'ladi."""
    respx.post(TARGET).mock(return_value=httpx.Response(200, text="OK, qabul qilindi"))

    outcome = await HttpRunner().run(make_spec(), HttpRuntime())

    assert outcome.runner_payload.result == "OK, qabul qilindi"


@respx.mock
async def test_buzilgan_json_matn_sifatida_qaytadi() -> None:
    """`content-type: json`, lekin tana buzilgan — istisno TASHLANMAYDI.

    Mijozning serveri noto'g'ri JSON qaytarishi uning xatosi, lekin
    bundan Durabl yiqilmasligi kerak: job natijasi xom matn bo'ladi.
    """
    respx.post(TARGET).mock(
        return_value=httpx.Response(
            200, headers={"content-type": "application/json"}, text="{buzilgan"
        )
    )

    outcome = await HttpRunner().run(make_spec(), HttpRuntime())

    assert outcome.runner_payload.ok is True
    assert outcome.runner_payload.result == "{buzilgan"


# ---------------------------------------------------------------------------
# Xato tasnifi — mahsulot uchun eng muhim qism
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422, 499])
@respx.mock
async def test_4xx_mijoz_xatosi_deb_tasniflanadi(status: int) -> None:
    """4xx -> `HTTP_CLIENT_ERROR`, ya'ni QAYTA URINILMAYDI."""
    respx.post(TARGET).mock(return_value=httpx.Response(status, text="xato"))

    outcome = await HttpRunner().run(make_spec(), HttpRuntime())

    assert outcome.runner_payload.ok is False
    # `exit_code` ga HAQIQIY status kodi yoziladi — mijoz natijada
    # `404` ni ko'radi, quruq `1` ni emas.
    assert outcome.exit_code == status
    assert HttpRuntime().classify_failure(outcome) is FailureReason.HTTP_CLIENT_ERROR


@pytest.mark.parametrize("status", [500, 502, 503, 504])
@respx.mock
async def test_5xx_server_xatosi_deb_tasniflanadi(status: int) -> None:
    """5xx -> `HTTP_SERVER_ERROR`, ya'ni qayta urinadi."""
    respx.post(TARGET).mock(return_value=httpx.Response(status))

    outcome = await HttpRunner().run(make_spec(), HttpRuntime())

    assert outcome.exit_code == status
    assert HttpRuntime().classify_failure(outcome) is FailureReason.HTTP_SERVER_ERROR


@respx.mock
async def test_ulanish_xatosi_connect_error_deb_tasniflanadi() -> None:
    """Ulanish o'rnatilmasa — `HTTP_CONNECT_ERROR` (status YO'Q)."""
    respx.post(TARGET).mock(side_effect=httpx.ConnectError("ulanmadi"))

    outcome = await HttpRunner().run(make_spec(), HttpRuntime())

    assert outcome.exit_code is None
    assert outcome.runner_payload.ok is False
    assert outcome.runner_payload.error_type == "ConnectError"
    assert HttpRuntime().classify_failure(outcome) is FailureReason.HTTP_CONNECT_ERROR


@respx.mock
async def test_timeout_belgilanadi() -> None:
    """`httpx` timeout -> `timed_out=True` va `TIMEOUT` sababi."""
    respx.post(TARGET).mock(side_effect=httpx.ReadTimeout("kutish tugadi"))

    outcome = await HttpRunner().run(make_spec(), HttpRuntime())

    assert outcome.timed_out is True
    assert HttpRuntime().classify_failure(outcome) is FailureReason.TIMEOUT


def test_timeout_status_kodidan_USTUN_turadi() -> None:
    """`timed_out` bo'lsa status kodi e'tiborga olinmaydi.

    Bu holat haqiqiy: `TimeoutGuard` tashqaridan `kill()` chaqirganda
    qismiy natija saqlanib qolishi mumkin (`exit_code` to'lgan), lekin
    sabab baribir TIMEOUT bo'lishi kerak — javob mijozga yetmagan.
    """
    outcome = RunnerOutcome(exit_code=503, timed_out=True)
    assert HttpRuntime().classify_failure(outcome) is FailureReason.TIMEOUT


# ---------------------------------------------------------------------------
# Header'lar va tana
# ---------------------------------------------------------------------------


@respx.mock
async def test_durabl_headerlari_mijoz_headerlaridan_USTUN() -> None:
    """Mijoz `X-Durabl-*` ni almashtira OLMAYDI.

    Aks holda qabul qiluvchi tomon "bu nechanchi urinish?" savoliga
    noto'g'ri javob olardi va idempotency mantig'ini mijozning o'zi
    buzishi mumkin bo'lardi.
    """
    route = respx.post(TARGET).mock(return_value=httpx.Response(200))

    spec = make_spec(
        attempt=3,
        headers={
            HEADER_ATTEMPT: "999",
            HEADER_JOB_ID: "boshqa-job",
            "X-Mijoz-Header": "saqlanadi",
        },
    )
    await HttpRunner().run(spec, HttpRuntime())

    sent = route.calls.last.request
    assert sent.headers[HEADER_ATTEMPT] == "3"
    assert sent.headers[HEADER_JOB_ID] == "job-1"
    # Mijozning O'Z header'i esa saqlanadi.
    assert sent.headers["X-Mijoz-Header"] == "saqlanadi"
    assert sent.headers["X-Correlation-ID"] == "corr-1"


@respx.mock
async def test_payload_json_tana_sifatida_yuboriladi() -> None:
    """`payload` POST tanasiga JSON bo'lib tushadi."""
    route = respx.post(TARGET).mock(return_value=httpx.Response(200))

    await HttpRunner().run(make_spec(payload={"n": 7}), HttpRuntime())

    assert route.calls.last.request.read() == b'{"n": 7}'


@pytest.mark.parametrize("method", [HttpMethod.GET, HttpMethod.DELETE])
@respx.mock
async def test_get_va_delete_uchun_tana_YUBORILMAYDI(method: HttpMethod) -> None:
    """`GET`/`DELETE` da tana yuborilmaydi — ko'p proxy ularni rad etadi."""
    route = respx.request(method.value, TARGET).mock(return_value=httpx.Response(200))

    await HttpRunner().run(make_spec(method=method, payload={"n": 7}), HttpRuntime())

    assert route.calls.last.request.read() == b""


@respx.mock
async def test_redirect_KUZATILMAYDI() -> None:
    """302 javob natija sifatida qaytadi, ergashilmaydi (SSRF himoyasi).

    Redirect kuzatilsa, mijoz tekshiruvdan o'tgan URL'ni ko'rsatib,
    serveridan `Location: http://169.254.169.254/...` qaytarishi va
    ichki metadata servisiga yetishi mumkin bo'lardi.
    """
    respx.post(TARGET).mock(
        return_value=httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
    )

    outcome = await HttpRunner().run(make_spec(), HttpRuntime())

    # 302 `is_success` emas -> xato deb hisoblanadi, lekin IZLANMAYDI.
    assert outcome.exit_code == 302
    assert outcome.runner_payload.ok is False


# ---------------------------------------------------------------------------
# SSRF tekshiruvi CHAQIRILADIMI
# ---------------------------------------------------------------------------


@respx.mock
async def test_bajarishdan_oldin_ssrf_tekshiruvi_chaqiriladi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """URL har BAJARISHDA qayta tekshiriladi (DNS rebinding'ga qarshi).

    Bu test mavjud bo'lmasa, tekshiruv chaqiruvini tasodifan o'chirib
    yuborish mumkin va hech narsa yiqilmaydi — teshik jimgina ochiq
    qoladi.
    """
    seen: list[str] = []

    async def _spy(url: str, **_: Any) -> None:
        seen.append(url)

    monkeypatch.setattr(http_runner_module, "validate_webhook_url_async", _spy)
    respx.post(TARGET).mock(return_value=httpx.Response(200))

    await HttpRunner().run(make_spec(), HttpRuntime())

    assert seen == [TARGET]


@respx.mock
async def test_ssrf_xatosi_TASHLANADI_yutilmaydi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tekshiruv xato tashlasa, so'rov YUBORILMAYDI."""

    async def _reject(url: str, **_: Any) -> None:
        raise SandboxError("ichki manzil taqiqlangan")

    monkeypatch.setattr(http_runner_module, "validate_webhook_url_async", _reject)
    route = respx.post(TARGET).mock(return_value=httpx.Response(200))

    with pytest.raises(SandboxError):
        await HttpRunner().run(make_spec(), HttpRuntime())

    assert route.call_count == 0


# ---------------------------------------------------------------------------
# Loglar va chegaralar
# ---------------------------------------------------------------------------


@respx.mock
async def test_log_callbacki_sorov_va_javobni_yozadi() -> None:
    """Real-time logda so'rov va status kodi ko'rinadi."""
    respx.post(TARGET).mock(return_value=httpx.Response(201, text="yaratildi"))

    seen, sink = collect_logs()
    await HttpRunner().run(make_spec(), HttpRuntime(), sink)

    text = "".join(chunk for _, chunk in seen)
    assert "POST" in text
    assert TARGET in text
    assert "201" in text
    assert "yaratildi" in text


@respx.mock
async def test_log_callbacki_yiqilsa_bajarish_BUZILMAYDI() -> None:
    """Log callback'i istisno tashlasa, natija baribir qaytadi."""
    respx.post(TARGET).mock(return_value=httpx.Response(200, json={"ok": True}))

    def broken(stream: LogStream, chunk: str) -> None:
        raise RuntimeError("log yozilmadi")

    outcome = await HttpRunner().run(make_spec(), HttpRuntime(), broken)

    assert outcome.runner_payload.ok is True


@respx.mock
async def test_katta_javob_qisqartiriladi() -> None:
    """Javob tanasi chegaradan oshsa kesiladi — DB to'ldirilmaydi."""
    big = "x" * (MAX_RESPONSE_PREVIEW_BYTES + 5_000)
    respx.post(TARGET).mock(return_value=httpx.Response(200, text=big))

    outcome = await HttpRunner().run(make_spec(), HttpRuntime())

    assert isinstance(outcome.runner_payload.result, str)
    assert len(outcome.runner_payload.result) == MAX_RESPONSE_PREVIEW_BYTES


# ---------------------------------------------------------------------------
# Shartnoma buzilishlari
# ---------------------------------------------------------------------------


async def test_url_yoq_bolsa_xato_tashlanadi() -> None:
    """`target_url` bo'sh bo'lsa — dasturchi xatosi, aniq xabar bilan."""
    spec = make_spec()
    spec.target_url = None

    with pytest.raises(SandboxError, match="target_url"):
        await HttpRunner().run(spec, HttpRuntime())


async def test_cleanup_orphans_har_doim_nol() -> None:
    """HTTP rejimida tozalanadigan qoldiq yo'q (protokol uchun mavjud)."""
    assert await HttpRunner().cleanup_orphans() == 0


async def test_available_har_doim_true() -> None:
    """HTTP runner tashqi demon talab qilmaydi."""
    assert await HttpRunner().available() is True


@pytest.mark.parametrize(
    "attr",
    ["image", "entrypoint_path"],
)
def test_http_runtime_konteyner_xossalari_xato_tashlaydi(attr: str) -> None:
    """HTTP job konteynerda bajarilmaydi — xossalar ataylab yiqiladi.

    Bu "o'lik kod" emas, balki SHARTNOMA: agar kimdir HTTP spec'ni
    sandbox runner'iga yuborib qo'ysa, jim ishlab ketish o'rniga aniq
    xato chiqadi.
    """
    with pytest.raises(SandboxError, match="konteynerda bajarilmaydi"):
        getattr(HttpRuntime(), attr)


def test_http_runtime_buyruq_metodlari_xato_tashlaydi() -> None:
    """`container_command` / `local_command` ham ataylab yiqiladi."""
    runtime = HttpRuntime()
    spec = make_spec()
    with pytest.raises(SandboxError):
        runtime.container_command(spec)
    with pytest.raises(SandboxError):
        runtime.local_command(spec, __import__("pathlib").Path("/tmp"))


# ---------------------------------------------------------------------------
# Bekor qilish
# ---------------------------------------------------------------------------


@respx.mock
async def test_kill_ketayotgan_sorovni_bekor_qiladi() -> None:
    """`kill()` so'rovni to'xtatadi va `CancelledError` yuqoriga chiqadi.

    `Executor` aynan shunga tayanadi: `TimeoutGuard` vaqt tugaganda
    `runner.kill()` chaqiradi va bekor qilish `ExecutionTimeoutError`
    ga aylanadi.
    """
    started = asyncio.Event()

    async def slow(request: httpx.Request) -> httpx.Response:
        started.set()
        await asyncio.sleep(10)
        return httpx.Response(200)

    respx.post(TARGET).mock(side_effect=slow)

    runner = HttpRunner()
    task = asyncio.create_task(runner.run(make_spec(timeout_seconds=30), HttpRuntime()))
    await asyncio.wait_for(started.wait(), timeout=5)
    await runner.kill()

    with pytest.raises(asyncio.CancelledError):
        await task
