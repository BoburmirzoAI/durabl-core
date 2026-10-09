"""Durabl — baxtli yo'l: ro'yxatdan o'tishdan webhook yetkazilishigacha.

Bu fayl Durabl'ning "ishlayapti" da'vosini isbotlaydi: HECH BIR qatlam
taqlid qilinmaydi. Haqiqiy HTTP so'rov -> haqiqiy service -> haqiqiy
`LocalRunner` subprocess'i -> haqiqiy `fakeredis` navbati -> haqiqiy
SQLite tranzaksiyasi. Tashqi dunyoga chiqadigan YAGONA chaqiruv —
webhook'ning HTTP so'rovi, u `respx` bilan ushlanadi (mijozning serveri
bizning nazoratimizda emas).

## Nega birinchi test BITTA uzun zanjir

Har bosqichni alohida testga bo'lish mumkin edi, lekin unda eng muhim
narsa — bosqichlar O'ZARO bog'liqligi — tekshirilmay qolardi: masalan
API kalit bilan yuborilgan job'ning `user_id` si JWT bilan yaratilgan
webhook egasiga mos kelishi, yoki `job.succeeded` hodisasining payload'i
AYNI o'sha job'ning yakuniy holatini aks ettirishi. Shuning uchun zanjir
bitta testda, lekin har bosqichda ochiq `assert` bilan.

## Vaqt maydonlari haqida

`stdout`/`stderr` DB'da to'liq saqlanadi (`"salom\\n"`), lekin javob
schema'lari `ORMSchema` dan voris va u `str_strip_whitespace=True` bilan
sozlangan — ya'ni API'dagi `stdout` oxirgi qator ko'chirishisiz
(`"salom"`) qaytadi. Test IKKISINI ham tasdiqlaydi, chunki mijoz
(frontend va SDK) API qiymatiga, diagnostika esa DB qiymatiga tayanadi.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
import respx
from app.constants import (
    HEADER_API_KEY,
    HEADER_WEBHOOK_EVENT,
    HEADER_WEBHOOK_SIGNATURE,
    DeliveryStatus,
    ExecutionStatus,
    JobStatus,
    LogStream,
    RedisKeys,
    Runtime,
    WebhookEvent,
)
from app.utils.security import verify_webhook_signature
from app.utils.time_utils import utcnow
from httpx import Response

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from collections.abc import Awaitable, Callable

    import httpx
    from app.models.execution import Execution
    from app.models.job import Job
    from app.workers.scheduler import SchedulerWorker
    from app.workers.webhook_sender import WebhookSender
    from app.workers.worker import Worker
    from redis.asyncio import Redis

pytestmark = pytest.mark.e2e

#: Ro'yxatdan o'tish uchun email. `.test` TLD ISHLATILMAYDI —
#: `email-validator` uni "special-use/reserved" deb rad etadi (422), ya'ni
#: `RegisterRequest.email` dan o'tmaydi.
E2E_EMAIL = "zanjir@durabl.dev"
E2E_PASSWORD = "Parol12345"

#: Webhook mock'ining manzili. Haqiqiy so'rov ketmaydi (`respx`), lekin
#: `validate_webhook_url()` sxemani tekshiradi — `https` bo'lishi shart.
HOOK_URL = "https://hooks.durabl.dev/e2e"

#: Analitika oralig'i: `ANALYTICS_MAX_RANGE_DAYS` (90) dan kichik bo'lishi
#: SHART, aks holda 422 qaytadi.
RANGE_HOURS = 1


def _range_params() -> dict[str, str]:
    """Analitika uchun "hozirni o'z ichiga oladigan" oraliq.

    Standart oraliq ISHLATILMAYDI: `AnalyticsService._quantized_now()`
    `end` ni kesh oynasiga tushiradi, ya'ni HOZIR yuborilgan job standart
    24 soatlik oynaga TUSHMAYDI (bu ataylab — kesh kaliti barqaror
    bo'lishi uchun). Testda chegaralar ochiq berilib, oyna hozirni
    qamrab oladi.
    """
    now = utcnow()
    return {
        "start": (now - timedelta(hours=RANGE_HOURS)).isoformat(),
        "end": (now + timedelta(hours=RANGE_HOURS)).isoformat(),
    }


async def _register_and_login(client: httpx.AsyncClient, prefix: str) -> dict[str, str]:
    """Yangi foydalanuvchi yaratadi va uning JWT header'ini qaytaradi."""
    registered = await client.post(
        f"{prefix}/auth/register",
        json={"email": E2E_EMAIL, "password": E2E_PASSWORD, "full_name": "Zanjir Egasi"},
    )
    assert registered.status_code == 201, registered.text
    assert registered.json()["email"] == E2E_EMAIL
    assert registered.json()["is_active"] is True

    logged_in = await client.post(
        f"{prefix}/auth/login",
        json={"email": E2E_EMAIL, "password": E2E_PASSWORD},
    )
    assert logged_in.status_code == 200, logged_in.text
    tokens = logged_in.json()
    assert tokens["token_type"] == "bearer"
    assert tokens["refresh_token"]
    return {"Authorization": f"Bearer {tokens['access_token']}"}


# ---------------------------------------------------------------------------
# 1. To'liq zanjir
# ---------------------------------------------------------------------------


async def test_register_api_key_job_execution_webhook_chain(
    client: httpx.AsyncClient,
    api_prefix: str,
    fake_redis: Redis,
    worker: Worker,
    webhook_sender: WebhookSender,
    fetch_job: Callable[..., Awaitable[Job]],
    fetch_executions: Callable[..., Awaitable[list[Execution]]],
    allow_remote_webhooks: None,
) -> None:
    """Ro'yxatdan o'tish -> API kalit -> webhook -> job -> bajarish -> webhook."""
    # --- 1. Ro'yxatdan o'tish va kirish ------------------------------
    jwt_headers = await _register_and_login(client, api_prefix)

    # --- 2. API kalit (job yuborish uchun) ---------------------------
    created_key = await client.post(
        f"{api_prefix}/api-keys",
        headers=jwt_headers,
        json={"name": "zanjir-kaliti"},
    )
    assert created_key.status_code == 201, created_key.text
    raw_key = created_key.json()["key"]
    assert raw_key.startswith("durabl_")
    key_headers = {HEADER_API_KEY: raw_key}

    # API kalit JWT bilan AYNI foydalanuvchini beradi — zanjirning
    # ikki uchi bir egaga tegishli ekanini shu tasdiqlaydi.
    me_by_key = await client.get(f"{api_prefix}/auth/me", headers=key_headers)
    me_by_jwt = await client.get(f"{api_prefix}/auth/me", headers=jwt_headers)
    assert me_by_key.status_code == 200
    assert me_by_key.json()["id"] == me_by_jwt.json()["id"]
    user_id = me_by_key.json()["id"]

    # --- 3. Webhook (JWT bilan) --------------------------------------
    created_hook = await client.post(
        f"{api_prefix}/webhooks",
        headers=jwt_headers,
        json={
            "url": HOOK_URL,
            "events": [WebhookEvent.JOB_QUEUED.value, WebhookEvent.JOB_SUCCEEDED.value],
            "description": "E2E zanjiri",
        },
    )
    assert created_hook.status_code == 201, created_hook.text
    hook = created_hook.json()
    hook_id = hook["id"]
    # `secret` FAQAT yaratish javobida qaytadi (`WebhookCreated`).
    hook_secret = hook["secret"]
    assert hook_secret
    assert hook["is_active"] is True

    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(HOOK_URL).mock(return_value=Response(200, text="qabul qilindi"))

        # --- 4. Job yuborish (API kalit bilan) -----------------------
        submitted = await client.post(
            f"{api_prefix}/jobs",
            headers=key_headers,
            json={"code": "print('salom')", "runtime": Runtime.PYTHON.value},
        )
        assert submitted.status_code == 201, submitted.text
        job_payload = submitted.json()
        job_id = job_payload["id"]
        assert job_payload["user_id"] == user_id
        assert job_payload["status"] == JobStatus.QUEUED.value
        assert job_payload["queued_at"] is not None
        assert submitted.headers["Location"] == f"{api_prefix}/jobs/{job_id}"

        # Job HAQIQATAN navbatda — bu Durabl'ning "qabul qilindi = bardoshli"
        # kafolati: javob 201 bo'lsa, job Redis'da ham, DB'da ham bor.
        assert await fake_redis.lrange(RedisKeys.queue("normal"), 0, -1) == [
            f"normal:{job_id}"
        ]

        # --- 5. Worker bajaradi --------------------------------------
        assert await worker.process_one(timeout=0) is True
        job = await fetch_job(job_id)
        assert JobStatus(job.status) is JobStatus.SUCCESS
        assert job.exit_code == 0
        # DB'da chiqish oqimi TO'LIQ saqlanadi — oxirgi qator ko'chirishi bilan.
        assert job.stdout == "salom\n"
        assert job.duration_ms is not None and job.duration_ms >= 0
        assert job.failure_reason is None
        assert job.retry_count == 0

        # Navbat bo'shadi va `processing` ro'yxati ham tozalandi (`ack`).
        assert await fake_redis.lrange(RedisKeys.queue("normal"), 0, -1) == []
        assert await fake_redis.lrange(RedisKeys.processing(worker.worker_id), 0, -1) == []

        # --- 6. `GET /jobs/{id}/result` ------------------------------
        result = await client.get(f"{api_prefix}/jobs/{job_id}/result", headers=key_headers)
        assert result.status_code == 200, result.text
        assert result.json()["status"] == JobStatus.SUCCESS.value
        # Javob schema'si bo'sh belgilarni kesadi (`str_strip_whitespace`).
        assert result.json()["stdout"] == "salom"
        assert result.json()["exit_code"] == 0
        assert result.json()["error"] is None

        # --- 7. `GET /jobs/{id}/logs` --------------------------------
        logs = await client.get(f"{api_prefix}/jobs/{job_id}/logs", headers=key_headers)
        assert logs.status_code == 200, logs.text
        entries = logs.json()["entries"]
        assert entries, "loglar bo'sh — chiqish oqimi saqlanmagan"
        streams = {entry["stream"] for entry in entries}
        assert LogStream.STDOUT.value in streams
        assert any("salom" in entry["content"] for entry in entries)
        # Ketma-ketlik raqamlari o'sib boradi (mijoz `after_sequence` bilan
        # faqat yangi qatorlarni so'rashi mumkin bo'lishi kerak).
        sequences = [entry["sequence"] for entry in entries]
        assert sequences == sorted(sequences)
        assert logs.json()["execution_id"] is not None

        # --- 8. `GET /jobs/{id}/timeline` ----------------------------
        timeline = await client.get(f"{api_prefix}/jobs/{job_id}/timeline", headers=key_headers)
        assert timeline.status_code == 200, timeline.text
        line = timeline.json()
        for field in ("created_at", "queued_at", "started_at", "finished_at"):
            assert line[field] is not None, f"`{field}` to'lmagan"
        for field in ("queue_wait_ms", "execution_ms", "total_ms"):
            assert line[field] is not None, f"`{field}` hisoblanmagan"
            assert line[field] >= 0
        assert line["cancelled_at"] is None
        assert line["attempts"] == 1
        assert len(line["executions"]) == 1
        assert line["executions"][0]["status"] == ExecutionStatus.SUCCESS.value

        # --- 9. Webhook yetkazishlari --------------------------------
        # `dispatch()` yozuvni yaratadi va navbatga qo'yadi, yuborishni esa
        # `WebhookSender` bajaradi — ikki hodisa uchun ikki yozuv.
        queued_deliveries = await fake_redis.lrange(RedisKeys.WEBHOOK_QUEUE, 0, -1)
        assert len(queued_deliveries) == 2, queued_deliveries

        await webhook_sender.tick()
        assert route.call_count == 2
        assert await fake_redis.lrange(RedisKeys.WEBHOOK_QUEUE, 0, -1) == []

        # --- 10. Imzo tekshiruvi -------------------------------------
        succeeded_calls = [
            call
            for call in route.calls
            if call.request.headers[HEADER_WEBHOOK_EVENT] == WebhookEvent.JOB_SUCCEEDED.value
        ]
        assert len(succeeded_calls) == 1
        request = succeeded_calls[0].request
        assert verify_webhook_signature(
            request.content,
            request.headers[HEADER_WEBHOOK_SIGNATURE],
            hook_secret,
        ), "webhook imzosi tekshiruvdan o'tmadi"

        sent = _json_body(request.content)
        assert sent["event"] == WebhookEvent.JOB_SUCCEEDED.value
        assert sent["data"]["job_id"] == job_id
        assert sent["data"]["status"] == JobStatus.SUCCESS.value

    # --- 11. Yetkazish yozuvlari API'da ------------------------------
    deliveries = await client.get(
        f"{api_prefix}/webhooks/{hook_id}/deliveries", headers=jwt_headers
    )
    assert deliveries.status_code == 200, deliveries.text
    items = deliveries.json()["items"]
    assert len(items) == 2
    assert {item["status"] for item in items} == {DeliveryStatus.SUCCESS.value}
    assert all(item["response_code"] == 200 for item in items)
    assert all(item["delivered_at"] is not None for item in items)

    # --- 12. Analitika bitta muvaffaqiyatli job ko'rsatadi -----------
    overview = await client.get(
        f"{api_prefix}/analytics/overview", headers=key_headers, params=_range_params()
    )
    assert overview.status_code == 200, overview.text
    stats = overview.json()
    assert stats["jobs"]["total"] == 1
    assert stats["jobs"]["success"] == 1
    assert stats["jobs"]["failed"] == 0
    assert stats["jobs"]["active"] == 0
    assert stats["jobs"]["success_rate"] == 100.0
    assert stats["jobs"]["by_status"][JobStatus.SUCCESS.value] == 1
    assert stats["executions"]["total"] == 1
    assert stats["executions"]["success"] == 1
    assert stats["dlq_depth"] == 0
    assert stats["usage"]["job_count"] == 1
    assert stats["usage"]["success_count"] == 1

    # --- 13. Billing hisobi -----------------------------------------
    usage = await client.get(f"{api_prefix}/billing/usage", headers=jwt_headers)
    assert usage.status_code == 200, usage.text
    assert usage.json()["job_count"] == 1
    assert usage.json()["success_count"] == 1
    assert usage.json()["failed_count"] == 0
    assert usage.json()["is_over_limit"] is False

    # --- 14. Urinishlar jadvali: AYNI BITTA yozuv --------------------
    executions = await fetch_executions(job_id)
    assert len(executions) == 1
    assert executions[0].attempt_number == 1
    assert ExecutionStatus(executions[0].status) is ExecutionStatus.SUCCESS
    assert executions[0].worker_id == worker.worker_id
    # Lease bo'shatilgan — qulagan worker qoldig'i qolmadi.
    assert executions[0].lease_expires_at is None
    assert await fake_redis.get(RedisKeys.lease(job_id)) is None


def _json_body(raw: bytes) -> dict[str, Any]:
    """Webhook tanasini lug'atga aylantiradi (imzo xom baytdan tekshiriladi)."""
    decoded = json.loads(raw.decode("utf-8"))
    assert isinstance(decoded, dict)
    return decoded


# ---------------------------------------------------------------------------
# 2. Payload bilan funksiya
# ---------------------------------------------------------------------------


async def test_function_with_payload_returns_value(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    run_until: Callable[..., Awaitable[Job]],
) -> None:
    """`main(x)` + `payload={"args": [21]}` -> natija 42.

    Natija `{"value": 42}` ko'rinishida saqlanadi: `jobs.result` ustuni
    JSON OBYEKT, shuning uchun `ExecutionResult.to_job_fields()` skalyar
    qiymatni `{"value": ...}` ichiga o'raydi (`app/execution/types.py`).
    """
    submitted = await client.post(
        f"{api_prefix}/jobs",
        headers=auth_headers,
        json={
            "code": "def main(x):\n    return x * 2\n",
            "runtime": Runtime.PYTHON.value,
            "payload": {"args": [21]},
        },
    )
    assert submitted.status_code == 201, submitted.text
    job_id = submitted.json()["id"]

    job = await run_until(job_id, JobStatus.SUCCESS)
    assert job.result == {"value": 42}

    result = await client.get(f"{api_prefix}/jobs/{job_id}/result", headers=auth_headers)
    assert result.status_code == 200, result.text
    assert result.json()["result"] == {"value": 42}
    assert result.json()["succeeded"] is True


# ---------------------------------------------------------------------------
# 3. Node runtime
# ---------------------------------------------------------------------------


async def test_node_runtime_executes(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    run_until: Callable[..., Awaitable[Job]],
) -> None:
    """`console.log('salom')` -> SUCCESS (ayni worker, boshqa runtime)."""
    submitted = await client.post(
        f"{api_prefix}/jobs",
        headers=auth_headers,
        json={"code": "console.log('salom')", "runtime": Runtime.NODE.value},
    )
    assert submitted.status_code == 201, submitted.text
    job_id = submitted.json()["id"]

    job = await run_until(job_id, JobStatus.SUCCESS)
    assert job.exit_code == 0
    assert "salom" in (job.stdout or "")
    assert job.failure_reason is None

    fetched = await client.get(f"{api_prefix}/jobs/{job_id}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["runtime"] == Runtime.NODE.value
    assert fetched.json()["status"] == JobStatus.SUCCESS.value


# ---------------------------------------------------------------------------
# 4. Kechiktirilgan job
# ---------------------------------------------------------------------------


async def test_scheduled_job_waits_then_runs(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    fake_redis: Redis,
    worker: Worker,
    scheduler: SchedulerWorker,
    advance_time: Callable[..., Awaitable[None]],
    fetch_job: Callable[..., Awaitable[Job]],
    run_until: Callable[..., Awaitable[Job]],
) -> None:
    """Kelajakdagi `scheduled_at`: navbatda YO'Q, vaqti kelgach bajariladi."""
    due_at = utcnow() + timedelta(minutes=10)
    submitted = await client.post(
        f"{api_prefix}/jobs",
        headers=auth_headers,
        json={
            "code": "print('keyin')",
            "runtime": Runtime.PYTHON.value,
            "scheduled_at": due_at.isoformat(),
        },
    )
    assert submitted.status_code == 201, submitted.text
    job_id = submitted.json()["id"]

    # --- Hali vaqti kelmagan ----------------------------------------
    # Rejali job `PENDING` qoladi: `QUEUED` "bajarishga tayyor" degani,
    # rejali job esa hali tayyor emas.
    assert submitted.json()["status"] == JobStatus.PENDING.value
    assert submitted.json()["queued_at"] is None
    assert await fake_redis.lrange(RedisKeys.queue("normal"), 0, -1) == []
    delayed = await fake_redis.zrange(RedisKeys.DELAYED, 0, -1)
    assert delayed == [f"normal:{job_id}"]

    # Worker uni OLMAYDI — navbat bo'sh.
    assert await worker.process_one(timeout=0) is False
    assert JobStatus((await fetch_job(job_id)).status) is JobStatus.PENDING

    # Scheduler ham vaqti kelmaganini hurmat qiladi.
    await scheduler.tick()
    assert JobStatus((await fetch_job(job_id)).status) is JobStatus.PENDING
    assert await fake_redis.zcard(RedisKeys.DELAYED) == 1

    # --- Vaqt o'tdi --------------------------------------------------
    await advance_time(11 * 60, job_ids=[job_id])
    await scheduler.tick()

    promoted = await fetch_job(job_id)
    assert JobStatus(promoted.status) is JobStatus.QUEUED
    assert promoted.queued_at is not None
    assert await fake_redis.zcard(RedisKeys.DELAYED) == 0
    assert await fake_redis.lrange(RedisKeys.queue("normal"), 0, -1) == [f"normal:{job_id}"]

    # --- Bajarildi ---------------------------------------------------
    job = await run_until(job_id, JobStatus.SUCCESS)
    assert job.stdout == "keyin\n"
    assert job.exit_code == 0


__all__ = [
    "E2E_EMAIL",
    "E2E_PASSWORD",
    "HOOK_URL",
    "RANGE_HOURS",
    "test_function_with_payload_returns_value",
    "test_node_runtime_executes",
    "test_register_api_key_job_execution_webhook_chain",
    "test_scheduled_job_waits_then_runs",
]
