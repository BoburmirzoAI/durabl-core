"""`DurablClient` va `AsyncDurablClient` testlari.

Barcha HTTP so'rovlar `respx` bilan mock qilinadi — haqiqiy tarmoqqa
chiqilmaydi. Mijozning `_sleep` metodi `conftest.py`da almashtirilgan,
shuning uchun backoff tekshirilsa ham testlar bir zumda tugaydi.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from durabl import (
    AuthenticationError,
    ConflictError,
    DurablClient,
    DurablConfig,
    DurablConfigError,
    DurablConnectionError,
    DurablTimeoutError,
    JobFailedError,
    JobStatus,
    NotFoundError,
    PermissionDeniedError,
    QuotaExceededError,
    RateLimitError,
    ResultNotReadyError,
    ServerError,
    ValidationError,
    error_from_response,
)

from .conftest import (
    API_KEY,
    BASE_URL,
    error_payload,
    job_payload,
    page_payload,
    result_payload,
)

JOB_ID = "11111111-1111-1111-1111-111111111111"
JOB_URL = f"/api/v1/jobs/{JOB_ID}"


# ---------------------------------------------------------------------------
# Sozlama
# ---------------------------------------------------------------------------


def test_config_muhit_ozgaruvchilaridan_oqiladi(monkeypatch: pytest.MonkeyPatch) -> None:
    """`DURABL_API_KEY` va `DURABL_BASE_URL` avtomatik o'qilishi kerak."""
    monkeypatch.setenv("DURABL_API_KEY", "durabl_from_env")
    monkeypatch.setenv("DURABL_BASE_URL", "https://local.durabl.test/")

    config = DurablConfig()

    assert config.api_key == "durabl_from_env"
    # Oxiridagi `/` olib tashlanadi.
    assert config.base_url == "https://local.durabl.test"
    assert config.api_url == "https://local.durabl.test/api/v1"
    assert config.path("jobs", JOB_ID) == JOB_URL


def test_config_api_kalit_bolmasa_xato_beradi() -> None:
    """API kalit yo'q bo'lsa mijoz yaratilishida tushunarli xato chiqadi."""
    with pytest.raises(DurablConfigError) as excinfo:
        DurablClient(base_url=BASE_URL)

    assert "DURABL_API_KEY" in str(excinfo.value)


def test_config_kalit_yashiriladi_va_tekshiriladi() -> None:
    """Kalit loglarda to'liq ko'rinmaydi, noto'g'ri manzil esa rad etiladi."""
    config = DurablConfig(api_key="durabl_abcdefghij1234", base_url=BASE_URL)
    masked = config.masked_api_key()

    assert masked.startswith("durabl_")
    assert config.api_key not in masked

    with pytest.raises(DurablConfigError):
        DurablConfig(api_key="x", base_url="api.durabl.dev")


# ---------------------------------------------------------------------------
# submit
# ---------------------------------------------------------------------------


def test_submit_tanani_togri_yasaydi(client: DurablClient) -> None:
    """`submit` barcha argumentlarni `JobCreate` shakliga o'giradi."""
    with respx.mock(base_url=BASE_URL) as router:
        route = router.post("/api/v1/jobs").mock(
            return_value=httpx.Response(201, json=job_payload(status="queued"))
        )
        handle = client.submit(
            code="print('salom')",
            runtime="python",
            payload={"x": 1},
            env_vars={"MODE": "test"},
            timeout=45,
            max_retries=5,
            priority="high",
            tags=["etl", "nightly"],
            cron="0 3 * * *",
        )

    body = json.loads(route.calls.last.request.content)
    assert body == {
        "code": "print('salom')",
        "runtime": "python",
        "priority": "high",
        "timeout_seconds": 45,
        "max_retries": 5,
        "payload": {"x": 1},
        "env_vars": {"MODE": "test"},
        "cron_expression": "0 3 * * *",
        "tags": ["etl", "nightly"],
    }
    assert handle.id == JOB_ID
    assert handle.job is not None
    assert handle.job.status is JobStatus.QUEUED


def test_submit_api_kalit_sarlavhasini_yuboradi(client: DurablClient) -> None:
    """Har bir so'rovda `X-API-Key` sarlavhasi bo'lishi shart."""
    with respx.mock(base_url=BASE_URL) as router:
        route = router.post("/api/v1/jobs").mock(
            return_value=httpx.Response(201, json=job_payload())
        )
        client.submit(code="print(1)")

    request = route.calls.last.request
    assert request.headers["x-api-key"] == API_KEY
    assert request.headers["user-agent"].startswith("durabl-python/")
    assert "idempotency-key" not in request.headers


def test_submit_idempotency_sarlavhasini_qoshadi(client: DurablClient) -> None:
    """`idempotency_key` berilsa `Idempotency-Key` sarlavhasi yuboriladi."""
    with respx.mock(base_url=BASE_URL) as router:
        route = router.post("/api/v1/jobs").mock(
            return_value=httpx.Response(200, json=job_payload(status="queued"))
        )
        client.submit(code="print(1)", idempotency_key="unique-123")

    request = route.calls.last.request
    assert request.headers["idempotency-key"] == "unique-123"
    assert json.loads(request.content)["idempotency_key"] == "unique-123"


def test_submit_bosh_kodni_rad_etadi(client: DurablClient) -> None:
    """Bo'sh kod serverga yuborilmaydi — lokal validatsiya ishlaydi."""
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        route = router.post("/api/v1/jobs")
        with pytest.raises(ValidationError):
            client.submit(code="   ")

    assert not route.called


def test_submit_scheduled_at_iso_matnga_oladi(client: DurablClient) -> None:
    """Naive `datetime` UTC deb qabul qilinadi va ISO-8601 matn bo'lib ketadi."""
    from datetime import datetime

    with respx.mock(base_url=BASE_URL) as router:
        route = router.post("/api/v1/jobs").mock(
            return_value=httpx.Response(201, json=job_payload())
        )
        client.submit(code="print(1)", scheduled_at=datetime(2026, 10, 4, 12, 30, 0))

    body = json.loads(route.calls.last.request.content)
    assert body["scheduled_at"].startswith("2026-10-04T12:30:00")
    assert body["scheduled_at"].endswith("+00:00")


# ---------------------------------------------------------------------------
# O'qish metodlari
# ---------------------------------------------------------------------------


def test_get_job_sanalarni_parse_qiladi(client: DurablClient) -> None:
    """ISO-8601 `...Z` sanalar `datetime` obyektiga aylanadi."""
    with respx.mock(base_url=BASE_URL) as router:
        router.get(JOB_URL).mock(
            return_value=httpx.Response(
                200,
                json=job_payload(
                    status="success",
                    started_at="2026-10-04T10:00:01Z",
                    finished_at="2026-10-04T10:00:03Z",
                    duration_ms=2000,
                    exit_code=0,
                ),
            )
        )
        job = client.get_job(JOB_ID)

    assert job.status is JobStatus.SUCCESS
    assert job.is_success and job.is_terminal
    assert job.created_at is not None and job.created_at.year == 2026
    assert job.finished_at is not None and job.finished_at.tzinfo is not None
    assert job.duration_seconds == 2.0


def test_get_status_enum_qaytaradi(client: DurablClient) -> None:
    """`get_status` matn emas, `JobStatus` enum qaytaradi."""
    with respx.mock(base_url=BASE_URL) as router:
        router.get(JOB_URL).mock(
            return_value=httpx.Response(200, json=job_payload(status="running"))
        )
        status = client.get_status(JOB_ID)

    assert status is JobStatus.RUNNING
    assert status.is_active and not status.is_finished


def test_get_result_muvaffaqiyatli(client: DurablClient) -> None:
    """Muvaffaqiyatli natijada `ok` rost bo'ladi."""
    with respx.mock(base_url=BASE_URL) as router:
        router.get(f"{JOB_URL}/result").mock(
            return_value=httpx.Response(200, json=result_payload())
        )
        result = client.get_result(JOB_ID)

    assert result.ok
    assert result.stdout == "Salom dunyo\n"
    assert result.exit_code == 0
    assert result.duration_ms == 1234


def test_get_result_tayyor_bolmasa_xato(client: DurablClient) -> None:
    """Job tugamagan bo'lsa `ResultNotReadyError` tashlanadi."""
    with respx.mock(base_url=BASE_URL) as router:
        router.get(f"{JOB_URL}/result").mock(
            return_value=httpx.Response(409, json=error_payload("RESULT_NOT_READY"))
        )
        with pytest.raises(ResultNotReadyError) as excinfo:
            client.get_result(JOB_ID)

    assert isinstance(excinfo.value, ConflictError)
    assert excinfo.value.status_code == 409


def test_get_logs_items_va_logs_shakllarini_tushunadi(client: DurablClient) -> None:
    """Loglar `{items: [...]}` yoki `{logs: [...]}` ko'rinishida kelishi mumkin."""
    entry = {"stream": "stdout", "content": "qator", "sequence": 1}
    with respx.mock(base_url=BASE_URL) as router:
        router.get(f"{JOB_URL}/logs").mock(
            side_effect=[
                httpx.Response(200, json={"items": [entry]}),
                httpx.Response(200, json={"job_id": JOB_ID, "logs": [entry, entry]}),
            ]
        )
        first = client.get_logs(JOB_ID)
        second = client.get_logs(JOB_ID)

    assert first == [entry]
    assert len(second) == 2


def test_get_logs_entries_kalitini_oqiydi(client: DurablClient) -> None:
    """Backendning haqiqiy shakli — `JobLogsResponse.entries` (`items` EMAS)."""
    birinchi = {"stream": "stdout", "content": "birinchi", "sequence": 1}
    ikkinchi = {"stream": "stderr", "content": "ikkinchi", "sequence": 2}
    with respx.mock(base_url=BASE_URL) as router:
        router.get(f"{JOB_URL}/logs").mock(
            return_value=httpx.Response(
                200,
                json={
                    "job_id": JOB_ID,
                    "execution_id": "exec-1",
                    "entries": [birinchi, ikkinchi],
                    "next_sequence": 3,
                    "has_more": False,
                    "count": 2,
                },
            )
        )
        yozuvlar = client.get_logs(JOB_ID)

    assert yozuvlar == [birinchi, ikkinchi]


def test_get_result_id_kalitini_job_id_ga_kochiradi(client: DurablClient) -> None:
    """`JobResultResponse` job identifikatorini `id` da yuboradi, `job_id` da emas."""
    with respx.mock(base_url=BASE_URL) as router:
        router.get(f"{JOB_URL}/result").mock(
            return_value=httpx.Response(
                200,
                json={
                    "id": JOB_ID,
                    "status": "success",
                    "result": 42,
                    "stdout": "",
                    "stderr": "",
                    "exit_code": 0,
                    "duration_ms": 12,
                    "succeeded": True,
                },
            )
        )
        natija = client.get_result(JOB_ID)

    assert natija.job_id == JOB_ID
    assert natija.result == 42
    assert natija.ok is True


# ---------------------------------------------------------------------------
# wait_for_result
# ---------------------------------------------------------------------------


def test_wait_for_result_pending_running_success(
    client: DurablClient, sleeps: list[float]
) -> None:
    """pending -> running -> success ketma-ketligi va o'sib boruvchi interval."""
    with respx.mock(base_url=BASE_URL) as router:
        status_route = router.get(JOB_URL).mock(
            side_effect=[
                httpx.Response(200, json=job_payload(status="pending")),
                httpx.Response(200, json=job_payload(status="running")),
                httpx.Response(200, json=job_payload(status="success", exit_code=0)),
            ]
        )
        router.get(f"{JOB_URL}/result").mock(
            return_value=httpx.Response(200, json=result_payload())
        )
        result = client.wait_for_result(JOB_ID, timeout=60, poll_interval=1.0)

    assert status_route.call_count == 3
    assert result.ok
    # Polling intervali ikki barobar oshadi: 1s -> 2s
    assert sleeps == [1.0, 2.0]


def test_wait_for_result_interval_besh_soniyada_toxtaydi(client: DurablClient) -> None:
    """Interval 5 soniyadan oshmaydi."""
    assert client._next_poll_interval(1.0) == 2.0
    assert client._next_poll_interval(3.0) == 5.0
    assert client._next_poll_interval(5.0) == 5.0


def test_wait_for_result_vaqt_tugasa_timeout_beradi(client: DurablClient) -> None:
    """Berilgan vaqt ichida tugamasa SDK `TimeoutError` tashlaydi."""
    with respx.mock(base_url=BASE_URL) as router:
        router.get(JOB_URL).mock(
            return_value=httpx.Response(200, json=job_payload(status="running"))
        )
        with pytest.raises(DurablTimeoutError) as excinfo:
            client.wait_for_result(JOB_ID, timeout=0)

    assert "running" in str(excinfo.value)


def test_wait_for_result_muvaffaqiyatsizlikda_xato_beradi(client: DurablClient) -> None:
    """`raise_on_failure=True` bo'lsa `JobFailedError` tashlanadi."""
    with respx.mock(base_url=BASE_URL) as router:
        router.get(JOB_URL).mock(
            return_value=httpx.Response(
                200, json=job_payload(status="failed", exit_code=1, error="ZeroDivisionError")
            )
        )
        router.get(f"{JOB_URL}/result").mock(
            return_value=httpx.Response(
                200,
                json=result_payload(status="failed", exit_code=1, stderr="Traceback...\n"),
            )
        )
        with pytest.raises(JobFailedError) as excinfo:
            client.wait_for_result(JOB_ID, timeout=10, raise_on_failure=True)

    assert excinfo.value.job_id == JOB_ID
    assert "ZeroDivisionError" in str(excinfo.value)


def test_wait_for_result_natija_bolmasa_job_suratidan_yasaydi(client: DurablClient) -> None:
    """Bekor qilingan job'da natija yo'q — holat job suratidan olinadi."""
    with respx.mock(base_url=BASE_URL) as router:
        router.get(JOB_URL).mock(
            return_value=httpx.Response(
                200, json=job_payload(status="cancelled", error="Mijoz bekor qildi")
            )
        )
        router.get(f"{JOB_URL}/result").mock(
            return_value=httpx.Response(409, json=error_payload("RESULT_NOT_READY"))
        )
        result = client.wait_for_result(JOB_ID, timeout=10)

    assert not result.ok
    assert result.status is JobStatus.CANCELLED
    assert result.error == "Mijoz bekor qildi"


# ---------------------------------------------------------------------------
# cancel va ro'yxatlar
# ---------------------------------------------------------------------------


def test_cancel_jobni_bekor_qiladi(client: DurablClient) -> None:
    """`cancel` yangi holatdagi job'ni qaytaradi."""
    with respx.mock(base_url=BASE_URL) as router:
        route = router.post(f"{JOB_URL}/cancel").mock(
            return_value=httpx.Response(200, json=job_payload(status="cancelled"))
        )
        job = client.cancel(JOB_ID)

    assert route.called
    assert job.status is JobStatus.CANCELLED
    assert job.is_terminal


def test_cancel_qisqa_javobda_jobni_qayta_oqiydi(client: DurablClient) -> None:
    """Server `{success: true}` qaytarsa, to'liq holat alohida so'rov bilan olinadi."""
    with respx.mock(base_url=BASE_URL) as router:
        router.post(f"{JOB_URL}/cancel").mock(
            return_value=httpx.Response(200, json={"success": True, "message": "bekor qilindi"})
        )
        refetch = router.get(JOB_URL).mock(
            return_value=httpx.Response(200, json=job_payload(status="cancelled"))
        )
        job = client.cancel(JOB_ID)

    assert refetch.called
    assert job.status is JobStatus.CANCELLED


def test_list_jobs_bitta_sahifa(client: DurablClient) -> None:
    """Ro'yxat `{items, pagination}` shaklida keladi."""
    with respx.mock(base_url=BASE_URL) as router:
        route = router.get("/api/v1/jobs").mock(
            return_value=httpx.Response(
                200, json=page_payload([job_payload(status="success")], page_size=20)
            )
        )
        jobs = client.list_jobs(status="success", page_size=20)

    assert len(jobs) == 1
    assert jobs[0].status is JobStatus.SUCCESS
    assert dict(route.calls.last.request.url.params) == {
        "page": "1",
        "page_size": "20",
        "status": "success",
    }


def test_list_jobs_barcha_sahifalarni_aylanadi(client: DurablClient) -> None:
    """`all_pages=True` bo'lsa `has_next` tugaguncha o'qiladi."""
    first = page_payload(
        [job_payload(job_id="1"), job_payload(job_id="2")],
        page=1,
        page_size=2,
        total=3,
        has_next=True,
    )
    second = page_payload([job_payload(job_id="3")], page=2, page_size=2, total=3)
    with respx.mock(base_url=BASE_URL) as router:
        route = router.get("/api/v1/jobs").mock(
            side_effect=[httpx.Response(200, json=first), httpx.Response(200, json=second)]
        )
        jobs = client.list_jobs(page_size=2, all_pages=True)

    assert [job.id for job in jobs] == ["1", "2", "3"]
    assert route.call_count == 2


def test_list_jobs_limit_bilan_cheklanadi(client: DurablClient) -> None:
    """`limit` berilsa, keraksiz sahifa so'ralmaydi."""
    first = page_payload(
        [job_payload(job_id="1"), job_payload(job_id="2")],
        page=1,
        page_size=2,
        total=10,
        has_next=True,
    )
    with respx.mock(base_url=BASE_URL) as router:
        route = router.get("/api/v1/jobs").mock(return_value=httpx.Response(200, json=first))
        jobs = client.list_jobs(page_size=2, all_pages=True, limit=2)

    assert len(jobs) == 2
    assert route.call_count == 1


# ---------------------------------------------------------------------------
# DLQ, webhook, billing, health
# ---------------------------------------------------------------------------


def test_dlq_royxat_va_qayta_urinish(client: DurablClient) -> None:
    """DLQ yozuvlarini o'qish va qayta urinish."""
    entry = {"id": "dlq-1", "job_id": JOB_ID, "failure_reason": "timeout", "resolved": False}
    with respx.mock(base_url=BASE_URL) as router:
        router.get("/api/v1/dlq").mock(
            return_value=httpx.Response(200, json=page_payload([entry]))
        )
        retry_route = router.post("/api/v1/dlq/dlq-1/retry").mock(
            return_value=httpx.Response(200, json={"job_id": JOB_ID, "status": "queued"})
        )
        entries = client.list_dlq(resolved=False)
        response = client.retry_dlq("dlq-1")

    assert entries == [entry]
    assert retry_route.called
    assert response["status"] == "queued"
    assert dict(retry_route.calls.last.request.url.params) == {}


def test_webhook_yaratish_royxat_ochirish(client: DurablClient) -> None:
    """Webhook CRUD amallari."""
    webhook = {"id": "wh-1", "url": "https://example.com/hook", "events": ["job.succeeded"]}
    with respx.mock(base_url=BASE_URL) as router:
        create = router.post("/api/v1/webhooks").mock(
            return_value=httpx.Response(201, json=webhook)
        )
        router.get("/api/v1/webhooks").mock(
            return_value=httpx.Response(200, json=page_payload([webhook]))
        )
        delete = router.delete("/api/v1/webhooks/wh-1").mock(
            return_value=httpx.Response(204)
        )

        created = client.create_webhook("https://example.com/hook", ["job.succeeded"])
        listed = client.list_webhooks()
        client.delete_webhook("wh-1")

    assert created["id"] == "wh-1"
    assert listed == [webhook]
    assert delete.called
    assert json.loads(create.calls.last.request.content) == {
        "url": "https://example.com/hook",
        "events": ["job.succeeded"],
    }


def test_webhook_hodisasiz_yaratilmaydi(client: DurablClient) -> None:
    """Hodisalar ro'yxati bo'sh bo'lsa so'rov yuborilmaydi."""
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        route = router.post("/api/v1/webhooks")
        with pytest.raises(ValidationError):
            client.create_webhook("https://example.com/hook", [])

    assert not route.called


def test_usage_statistikani_qaytaradi(client: DurablClient) -> None:
    """`usage()` billing ma'lumotini qaytaradi."""
    with respx.mock(base_url=BASE_URL) as router:
        router.get("/api/v1/billing/usage").mock(
            return_value=httpx.Response(200, json={"period": "2026-10", "job_count": 42})
        )
        usage = client.usage()

    assert usage["job_count"] == 42


def test_ping_sogliqni_tekshiradi(client: DurablClient) -> None:
    """`ping()` xato tashlamaydi — `True`/`False` qaytaradi."""
    with respx.mock(base_url=BASE_URL) as router:
        route = router.get("/health").mock(
            side_effect=[
                httpx.Response(200, json={"status": "ok"}),
                httpx.Response(503, json=error_payload("SERVICE_UNAVAILABLE")),
                httpx.Response(503, json=error_payload("SERVICE_UNAVAILABLE")),
                httpx.Response(503, json=error_payload("SERVICE_UNAVAILABLE")),
            ]
        )
        assert client.ping() is True
        assert client.ping() is False

    # 503 qayta urinishga loyiq: 1 + max_retries(2) = 3 chaqiruv
    assert route.call_count == 4


# ---------------------------------------------------------------------------
# Xato javoblari
# ---------------------------------------------------------------------------


def test_401_authentication_error(client: DurablClient) -> None:
    """401 -> `AuthenticationError`, `request_id` saqlanadi."""
    with respx.mock(base_url=BASE_URL) as router:
        router.get(JOB_URL).mock(
            return_value=httpx.Response(
                401, json=error_payload("INVALID_API_KEY", "Kalit yaroqsiz")
            )
        )
        with pytest.raises(AuthenticationError) as excinfo:
            client.get_job(JOB_ID)

    error = excinfo.value
    assert error.status_code == 401
    assert error.code == "INVALID_API_KEY"
    assert error.message == "Kalit yaroqsiz"
    assert error.request_id == "req_test_1"


def test_404_not_found_error(client: DurablClient) -> None:
    """404 -> `NotFoundError`."""
    with respx.mock(base_url=BASE_URL) as router:
        router.get(JOB_URL).mock(
            return_value=httpx.Response(404, json=error_payload("JOB_NOT_FOUND"))
        )
        with pytest.raises(NotFoundError):
            client.get_job(JOB_ID)


def test_402_quota_exceeded_error(client: DurablClient) -> None:
    """402 -> `QuotaExceededError` (oylik limit tugadi)."""
    with respx.mock(base_url=BASE_URL) as router:
        router.post("/api/v1/jobs").mock(
            return_value=httpx.Response(
                402, json=error_payload("QUOTA_EXCEEDED", details={"monthly_jobs": 1000})
            )
        )
        with pytest.raises(QuotaExceededError) as excinfo:
            client.submit(code="print(1)")

    assert excinfo.value.details == {"monthly_jobs": 1000}


def test_422_validation_error(client: DurablClient) -> None:
    """422 -> `ValidationError`, tafsilotlar saqlanadi."""
    with respx.mock(base_url=BASE_URL) as router:
        router.post("/api/v1/jobs").mock(
            return_value=httpx.Response(
                422,
                json=error_payload(
                    "CODE_VALIDATION_FAILED", details={"violations": ["import subprocess"]}
                ),
            )
        )
        with pytest.raises(ValidationError) as excinfo:
            client.submit(code="import subprocess")

    assert excinfo.value.details["violations"] == ["import subprocess"]


def test_429_rate_limit_error_retry_after_bilan(client: DurablClient) -> None:
    """Barcha urinishlar 429 bo'lsa `RateLimitError` va `retry_after` qaytadi."""
    with respx.mock(base_url=BASE_URL) as router:
        route = router.get(JOB_URL).mock(
            return_value=httpx.Response(
                429,
                headers={"Retry-After": "3"},
                json=error_payload("RATE_LIMIT_EXCEEDED"),
            )
        )
        with pytest.raises(RateLimitError) as excinfo:
            client.get_job(JOB_ID)

    assert excinfo.value.retry_after == 3.0
    # 1 urinish + 2 qayta urinish
    assert route.call_count == 3


def test_400_xatosida_qayta_urinilmaydi(client: DurablClient) -> None:
    """4xx (429'dan tashqari) xatolarda qayta urinish ma'nosiz."""
    with respx.mock(base_url=BASE_URL) as router:
        route = router.post("/api/v1/jobs").mock(
            return_value=httpx.Response(400, json=error_payload("BAD_REQUEST"))
        )
        with pytest.raises(ValidationError):
            client.submit(code="print(1)")

    assert route.call_count == 1


def test_json_bolmagan_javob_tushunarli_xato(client: DurablClient) -> None:
    """HTML yoki matn javob kelsa, SDK aniq xato beradi."""
    with respx.mock(base_url=BASE_URL) as router:
        router.get(JOB_URL).mock(
            return_value=httpx.Response(200, text="<html>nginx</html>")
        )
        with pytest.raises(Exception) as excinfo:
            client.get_job(JOB_ID)

    assert "JSON bo'lmagan" in str(excinfo.value)


def test_error_from_response_kod_bilan_klass_tanlaydi() -> None:
    """`error_from_response` `error.code` bo'yicha mos klassni tanlaydi."""
    assert isinstance(error_from_response(404, error_payload("JOB_NOT_FOUND")), NotFoundError)
    assert isinstance(error_from_response(500, error_payload("DATABASE_ERROR")), ServerError)
    assert isinstance(error_from_response(409, error_payload("RESULT_NOT_READY")), ResultNotReadyError)
    # Kod noma'lum bo'lsa — status bo'yicha
    assert isinstance(
        error_from_response(403, {"error": {"code": "XXX"}}), PermissionDeniedError
    )
    # Tana butunlay boshqa shaklda bo'lsa ham xabar yo'qolmaydi
    error = error_from_response(500, {"detail": "ichki xato"})
    assert error.message == "ichki xato"


# ---------------------------------------------------------------------------
# Qayta urinish va backoff
# ---------------------------------------------------------------------------


def test_5xx_da_eksponensial_backoff_bilan_qayta_urinadi(
    client: DurablClient, sleeps: list[float]
) -> None:
    """500 -> 500 -> 200: ikki marta qayta urinadi, kutish 1s va 2s."""
    with respx.mock(base_url=BASE_URL) as router:
        route = router.get(JOB_URL).mock(
            side_effect=[
                httpx.Response(500, json=error_payload("INTERNAL_ERROR")),
                httpx.Response(502, text="bad gateway"),
                httpx.Response(200, json=job_payload(status="success")),
            ]
        )
        job = client.get_job(JOB_ID)

    assert route.call_count == 3
    assert job.status is JobStatus.SUCCESS
    assert sleeps == [1.0, 2.0]


def test_429_retry_after_kutish_vaqtini_belgilaydi(
    client: DurablClient, sleeps: list[float]
) -> None:
    """`Retry-After` sarlavhasi backoff'dan ustun turadi."""
    with respx.mock(base_url=BASE_URL) as router:
        router.get(JOB_URL).mock(
            side_effect=[
                httpx.Response(429, headers={"Retry-After": "7"}, json=error_payload("RATE_LIMIT_EXCEEDED")),
                httpx.Response(200, json=job_payload(status="queued")),
            ]
        )
        job = client.get_job(JOB_ID)

    assert job.status is JobStatus.QUEUED
    assert sleeps == [7.0]


def test_backoff_hisobi_maksimumdan_oshmaydi(client: DurablClient) -> None:
    """Backoff `retry_max_delay` bilan cheklanadi."""
    assert client._compute_retry_delay(0) == 1.0
    assert client._compute_retry_delay(1) == 2.0
    assert client._compute_retry_delay(2) == 4.0
    # retry_max_delay = 10.0
    assert client._compute_retry_delay(10) == 10.0
    # Retry-After ham cheklanadi
    assert client._compute_retry_delay(0, 99.0) == 10.0


def test_ulanish_xatosida_qayta_urinadi_va_xato_beradi(
    client: DurablClient, sleeps: list[float]
) -> None:
    """Tarmoq uzilsa `ConnectionError` (SDK) tashlanadi."""
    with respx.mock(base_url=BASE_URL) as router:
        route = router.get(JOB_URL).mock(side_effect=httpx.ConnectError("ulanmadi"))
        with pytest.raises(DurablConnectionError):
            client.get_job(JOB_ID)

    assert route.call_count == 3
    assert sleeps == [1.0, 2.0]


def test_sorov_timeoutida_sdk_timeout_xatosi(client: DurablClient) -> None:
    """HTTP timeout SDK `TimeoutError`ga aylanadi."""
    with respx.mock(base_url=BASE_URL) as router:
        router.get(JOB_URL).mock(side_effect=httpx.ReadTimeout("sekin"))
        with pytest.raises(DurablTimeoutError):
            client.get_job(JOB_ID)


def test_kontekst_menejer_ulanishni_yopadi() -> None:
    """`with` blokidan chiqishda HTTP mijoz yopiladi."""
    with DurablClient(api_key=API_KEY, base_url=BASE_URL) as instance:
        assert instance._http.is_closed is False
    assert instance._http.is_closed is True


# ---------------------------------------------------------------------------
# Asinxron mijoz
# ---------------------------------------------------------------------------


async def test_async_submit_va_wait(async_client, sleeps: list[float]) -> None:
    """Asinxron mijoz sinxron variant bilan bir xil ishlaydi."""
    with respx.mock(base_url=BASE_URL) as router:
        router.post("/api/v1/jobs").mock(
            return_value=httpx.Response(201, json=job_payload(status="queued"))
        )
        router.get(JOB_URL).mock(
            side_effect=[
                httpx.Response(200, json=job_payload(status="running")),
                httpx.Response(200, json=job_payload(status="success", exit_code=0)),
            ]
        )
        router.get(f"{JOB_URL}/result").mock(
            return_value=httpx.Response(200, json=result_payload())
        )

        handle = await async_client.submit(code="print(1)", idempotency_key="async-1")
        assert handle.id == JOB_ID
        result = await handle.wait(timeout=30)

    assert result.ok
    assert sleeps == [1.0]


async def test_async_kontekst_menejer_va_xatolar(sleeps: list[float]) -> None:
    """`async with` ishlaydi va xatolar bir xil klasslarga o'giriladi."""
    from durabl import AsyncDurablClient

    with respx.mock(base_url=BASE_URL) as router:
        router.get(JOB_URL).mock(
            return_value=httpx.Response(404, json=error_payload("JOB_NOT_FOUND"))
        )
        async with AsyncDurablClient(api_key=API_KEY, base_url=BASE_URL, max_retries=0) as instance:
            with pytest.raises(NotFoundError):
                await instance.get_job(JOB_ID)
        assert instance._http.is_closed is True


async def test_async_list_jobs_va_usage(async_client) -> None:
    """Asinxron ro'yxat va billing metodlari."""
    with respx.mock(base_url=BASE_URL) as router:
        router.get("/api/v1/jobs").mock(
            return_value=httpx.Response(200, json=page_payload([job_payload()]))
        )
        router.get("/api/v1/billing/usage").mock(
            return_value=httpx.Response(200, json={"job_count": 7})
        )
        jobs = await async_client.list_jobs(page_size=5)
        usage = await async_client.usage()

    assert len(jobs) == 1
    assert usage["job_count"] == 7
