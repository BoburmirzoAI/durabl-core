"""Durabl — bajarish zanjirining uchidan-uchiga testlari.

Job HTTP orqali yuboriladi, keyin HAQIQIY `Worker.process_one()` ishga
tushadi: navbatdan olish -> lease -> `LocalRunner` (subprocess) -> natija ->
DB. Hech qanday soxta obyekt YO'Q — `SANDBOX_ENABLED=false` bo'lgani uchun
kod `sandbox/runners/python/entrypoint.py` orqali joriy interpretatorda
bajariladi.

## `payload` shakli — nozik joy

`entrypoint.py` kirish funksiyasini FAQAT `payload` berilganda chaqiradi va
chaqiruv `main(*args, **kwargs)` ko'rinishida bo'ladi, bunda `args`/`kwargs`
payload'ning AYNI nomli kalitlaridan olinadi. Ya'ni `{"n": 1}` yuborish
`main(n=1)` ni chaqiradi; `{"args": [1]}` esa `main(1)` ni. Payload
berilmasa funksiya chaqirilmaydi va natija `None` bo'ladi (kod moduli
baribir bajariladi) — natija kutilayotgan testlarda payload SHART.

## Worker boshqa sessiyada ishlaydi — kesh bo'shatish SHART

`conftest.py` `get_db` dependency'sini `db_session` ga bog'laydi, ya'ni
HTTP so'rovi va test AYNI sessiyani baham ko'radi. Worker esa O'Z
sessiyasini ochadi (`session_scope()`). Natijada worker job'ni
o'zgartirgandan keyin baham ko'rilgan sessiyaning identity map'ida ESKI
nusxa qoladi va `GET /jobs/{id}` eski holatni qaytarardi (ORM `select()`
mavjud obyektning yuklangan atributlarini qayta yozmaydi).

Shuning uchun `run_one()` yordamchisi worker tugagach
`session.expire_all()` chaqiradi — shundan keyin har bir o'qish DB'dan
yangi qiymat oladi.

## Nega retry zanjirida `JobService.requeue()` chaqiriladi

`ReliabilityService.schedule_retry()` job'ni `RETRYING` holatida qoldirib
Redis'ning kechiktirilgan navbatiga qo'yadi; backoff bir necha soniya
bo'lishi mumkin. Testni `sleep` bilan sekinlashtirmaslik uchun ikkinchi
urinish `requeue()` bilan darhol navbatga qaytariladi — bu amalda
`SchedulerWorker` bajaradigan AYNI o'tish (`RETRYING -> QUEUED`).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from app.constants import ExecutionStatus, FailureReason, JobStatus, LogStream
from app.services.job_service import JobService
from app.services.reliability_service import ReliabilityService
from app.workers.worker import Worker

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    import httpx
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

#: Natijani payload'dan hisoblab qaytaradigan kod.
DOUBLING_CODE = "def main(n):\n    print('hisoblanmoqda')\n    return {'double': n * 2}\n"

#: Chiqish kodi 1 bilan yiqiladigan kod.
FAILING_CODE = "raise ValueError('ataylab yiqildi')\n"

#: Timeout'ga uriladigan kod (`time` taqiqlanmagan modul).
SLEEPING_CODE = "import time\ntime.sleep(30)\n"


async def submit(
    client: httpx.AsyncClient,
    api_prefix: str,
    headers: dict[str, str],
    **overrides: Any,
) -> str:
    """Job yuboradi va uning identifikatorini qaytaradi."""
    body: dict[str, Any] = {"code": DOUBLING_CODE, "runtime": "python"}
    body.update(overrides)
    response = await client.post(f"{api_prefix}/jobs", headers=headers, json=body)
    assert response.status_code == 201, response.text
    return str(response.json()["id"])


async def run_one(session: AsyncSession, worker_id: str = "test-worker") -> bool:
    """Navbatdan bitta job olib to'liq bajaradi va test keshini bo'shatadi.

    `expire_all()` nega kerakligi modul docstring'ida yozilgan.
    """
    claimed = await Worker(worker_id=worker_id).process_one(timeout=1)
    session.expire_all()
    return claimed


async def test_successful_chain(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Muvaffaqiyatli zanjir: `queued -> running -> success`, natija va stdout."""
    job_id = await submit(client, api_prefix, auth_headers, payload={"args": [21]})

    assert await run_one(db_session) is True

    status = await client.get(f"{api_prefix}/jobs/{job_id}/status", headers=auth_headers)
    assert status.json()["status"] == JobStatus.SUCCESS.value
    assert status.json()["is_terminal"] is True
    assert status.json()["duration_ms"] >= 0

    result = await client.get(f"{api_prefix}/jobs/{job_id}/result", headers=auth_headers)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["exit_code"] == 0
    assert body["error"] is None
    # `entrypoint.py` natijani `{"value": <qaytgan qiymat>}` ichida beradi.
    assert body["result"]["value"] == {"double": 42}
    assert "hisoblanmoqda" in body["stdout"]


async def test_logs_persisted_and_served(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Loglar DB'ga yoziladi va `/logs` orqali tartib bilan qaytadi."""
    job_id = await submit(client, api_prefix, auth_headers, payload={"args": [1]})
    await run_one(db_session)

    response = await client.get(f"{api_prefix}/jobs/{job_id}/logs", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    entries = body["entries"]
    assert entries, "kamida bitta tizim logi bo'lishi kerak"
    assert body["execution_id"] is not None
    # `sequence` qat'iy o'sish tartibida.
    assert [entry["sequence"] for entry in entries] == sorted(
        entry["sequence"] for entry in entries
    )
    streams = {entry["stream"] for entry in entries}
    assert streams <= {stream.value for stream in LogStream}
    assert body["next_sequence"] == entries[-1]["sequence"]

    # Kursor: oxirgi raqamdan KEYIN yangi qator yo'q.
    after = await client.get(
        f"{api_prefix}/jobs/{job_id}/logs?after_sequence={body['next_sequence']}",
        headers=auth_headers,
    )
    assert after.json()["entries"] == []


async def test_execution_record_created(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Har urinish uchun `executions` yozuvi yaratiladi va `/executions` da ko'rinadi."""
    job_id = await submit(client, api_prefix, auth_headers, payload={"args": [2]})
    await run_one(db_session, worker_id="exec-worker")

    response = await client.get(
        f"{api_prefix}/executions?job_id={job_id}", headers=auth_headers
    )

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["attempt_number"] == 1
    assert items[0]["status"] == ExecutionStatus.SUCCESS.value
    assert items[0]["worker_id"] == "exec-worker"
    assert items[0]["exit_code"] == 0


async def test_failure_schedules_retry(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Xato bo'lsa va urinish qolsa job `RETRYING` bo'ladi, DLQ'ga TUSHMAYDI."""
    job_id = await submit(client, api_prefix, auth_headers, code=FAILING_CODE, max_retries=2)

    await run_one(db_session)

    status = await client.get(f"{api_prefix}/jobs/{job_id}/status", headers=auth_headers)
    body = status.json()
    assert body["status"] == JobStatus.RETRYING.value
    assert body["retry_count"] == 1
    assert body["failure_reason"] == FailureReason.NON_ZERO_EXIT.value

    dlq = await client.get(f"{api_prefix}/dlq", headers=auth_headers)
    assert dlq.json()["pagination"]["total"] == 0


async def test_retries_exhausted_go_to_dlq(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Urinishlar tugagach job `DEAD_LETTER` bo'ladi va DLQ yozuvi paydo bo'ladi."""
    job_id = await submit(client, api_prefix, auth_headers, code=FAILING_CODE, max_retries=1)

    # 1-urinish: xato -> RETRYING.
    await run_one(db_session, worker_id="retry-worker-1")
    service = JobService(db_session)
    job = await service.get_internal(job_id)
    assert JobStatus(job.status) is JobStatus.RETRYING

    # Scheduler bajaradigan o'tishni darhol takrorlaymiz (docstring'ga qara).
    await service.requeue(job)

    # 2-urinish: urinishlar tugadi -> DEAD_LETTER.
    await run_one(db_session, worker_id="retry-worker-2")

    status = await client.get(f"{api_prefix}/jobs/{job_id}/status", headers=auth_headers)
    assert status.json()["status"] == JobStatus.DEAD_LETTER.value

    dlq = await client.get(f"{api_prefix}/dlq", headers=auth_headers)
    items = dlq.json()["items"]
    assert len(items) == 1
    assert items[0]["job_id"] == job_id
    assert items[0]["resolved"] is False
    assert "ataylab yiqildi" in items[0]["last_error"]

    executions = await client.get(
        f"{api_prefix}/executions?job_id={job_id}", headers=auth_headers
    )
    assert executions.json()["pagination"]["total"] == 2


async def test_timeout_marks_job_failed(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """`timeout_seconds` oshsa urinish `TIMEOUT` sababi bilan tugaydi."""
    job_id = await submit(
        client,
        api_prefix,
        auth_headers,
        code=SLEEPING_CODE,
        timeout_seconds=1,
        max_retries=0,
    )

    await run_one(db_session, worker_id="timeout-worker")

    status = await client.get(f"{api_prefix}/jobs/{job_id}/status", headers=auth_headers)
    body = status.json()
    assert body["status"] == JobStatus.DEAD_LETTER.value
    assert body["failure_reason"] == FailureReason.TIMEOUT.value

    executions = await client.get(
        f"{api_prefix}/executions?job_id={job_id}", headers=auth_headers
    )
    assert executions.json()["items"][0]["status"] == ExecutionStatus.TIMEOUT.value


async def test_cancel_signal_stops_execution(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Bekor qilish signali qo'yilgan job `CANCELLED` bo'lib tugaydi.

    Signal Redis'da turadi (`ReliabilityService.request_cancel`), worker esa
    bajarish tugagach uni tekshiradi va natijani `CANCELLED` deb qayta
    belgilaydi — kooperativ to'xtatish. Signal ataylab worker ishga
    TUSHISHIDAN OLDIN qo'yiladi: aks holda test poyga shartiga bog'liq
    bo'lib qolardi.
    """
    job_id = await submit(client, api_prefix, auth_headers, payload={"args": [3]})
    await ReliabilityService(db_session).request_cancel(job_id)

    await run_one(db_session, worker_id="cancel-worker")

    status = await client.get(f"{api_prefix}/jobs/{job_id}/status", headers=auth_headers)
    assert status.json()["status"] == JobStatus.CANCELLED.value

    executions = await client.get(
        f"{api_prefix}/executions?job_id={job_id}", headers=auth_headers
    )
    assert executions.json()["items"][0]["status"] == ExecutionStatus.CANCELLED.value


async def test_cancelled_job_is_skipped_by_worker(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Navbatda qolgan, lekin bekor qilingan job BAJARILMAYDI (`ack` qilinadi)."""
    job_id = await submit(client, api_prefix, auth_headers, payload={"args": [4]})
    cancelled = await client.post(f"{api_prefix}/jobs/{job_id}/cancel", headers=auth_headers)
    assert cancelled.status_code == 200, cancelled.text

    # `cancel()` a'zoni navbatdan olib tashlaydi, shuning uchun navbat BO'SH.
    assert await run_one(db_session, worker_id="skip-worker") is False

    executions = await client.get(
        f"{api_prefix}/executions?job_id={job_id}", headers=auth_headers
    )
    assert executions.json()["pagination"]["total"] == 0


async def test_empty_queue_returns_false(db_session: AsyncSession) -> None:
    """Navbat bo'sh bo'lsa `process_one()` `False` qaytaradi."""
    assert await run_one(db_session, worker_id="idle-worker") is False


async def test_lease_released_after_completion(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Bajarish tugagach lease bo'shatiladi (boshqa worker job'ni olishi mumkin)."""
    job_id = await submit(client, api_prefix, auth_headers, payload={"args": [5]})
    await run_one(db_session, worker_id="lease-worker")

    holder = await ReliabilityService(db_session).lease_holder(job_id)
    assert holder is None


async def test_usage_recorded_after_success(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Muvaffaqiyatli bajarish billing hisobiga tushadi."""
    await submit(client, api_prefix, auth_headers, payload={"args": [6]})
    await run_one(db_session, worker_id="usage-worker")

    usage = await client.get(f"{api_prefix}/billing/usage", headers=auth_headers)

    assert usage.status_code == 200, usage.text
    body = usage.json()
    assert body["job_count"] == 1
    assert body["success_count"] == 1
    assert body["execution_seconds"] >= 0


__all__ = ["DOUBLING_CODE", "FAILING_CODE", "SLEEPING_CODE", "run_one", "submit"]
