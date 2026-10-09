"""Durabl — asosiy da'vo: JOB YO'QOLMAYDI.

Durabl'ning butun qiymati shu fayldagi oltita testda. Har biri real
nosozlikni taqlid qiladi va job'ning taqdirini oxirigacha kuzatadi:

| Nosozlik | Kim tiklaydi | Natija |
|---|---|---|
| Kod xato beradi | `ReliabilityService.handle_failure` | retry -> DLQ |
| Worker quladi (lease yo'qoldi) | `reap_expired_leases` + scheduler | boshqa worker bajaradi |
| Redis quladi (navbat yo'qoldi) | `SchedulerWorker._recover_lost` | job qayta navbatga tushadi |
| Kod muddatdan oshdi | `TimeoutGuard` + runner `kill()` | `TIMEOUT`, jarayon o'ldirilgan |
| Mijoz bekor qildi | `JobService.cancel` | navbatdan olinadi, worker olmaydi |
| Ikki worker bir job'ni oldi | lease `SET NX` | job BIR MARTA bajariladi |

## Nega ba'zi testlarda service'lar bevosita chaqiriladi

"Worker quladi" holatini HTTP orqali yasash mumkin emas: worker job'ni
olib, `RUNNING` qilib, keyin bajarishni TUGATMASLIGI kerak. Shuning uchun
`_claim_without_finishing()` yordamchisi `Worker._process()` ning aynan
shu bosqichigacha qo'lda boradi (dequeue -> lease -> `ExecutionService.start`)
va to'xtaydi — xuddi `SIGKILL` kelgan worker kabi. Qolgan tiklanish
zanjiri (reaper -> scheduler -> ikkinchi worker) HAQIQIY kod bilan
bajariladi.

## Vaqt

Backoff kutishlari HAQIQIY (`RETRY_BASE_DELAY_SECONDS=1`, multiplier 2),
shuning uchun testlar `advance_time()` bilan muddatlarni orqaga suradi —
`asyncio.sleep` ishlatilmaydi (test sekinlashardi va vaqtga bog'lanib
beqaror bo'lardi).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from app.constants import (
    ExecutionStatus,
    FailureReason,
    JobStatus,
    LogStream,
    Priority,
    RedisKeys,
    Runtime,
)
from app.database import session_scope
from app.services.execution_service import ExecutionService
from app.services.job_service import JobService
from app.services.queue_service import QueueService
from app.services.reliability_service import ReliabilityService

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from collections.abc import Awaitable, Callable

    import httpx
    from app.models.execution import Execution
    from app.models.job import Job
    from app.workers.scheduler import SchedulerWorker
    from app.workers.worker import Worker
    from redis.asyncio import Redis

pytestmark = pytest.mark.e2e

#: Har doim yiqiladigan kod — `non_zero_exit` sababini beradi.
FAILING_CODE = "raise RuntimeError('ataylab yiqildi')\n"

#: Muddatdan oshadigan kod. `time` moduli `PYTHON_FORBIDDEN_IMPORTS` da
#: YO'Q, shuning uchun `assert_code_safe()` dan o'tadi.
SLEEPING_CODE = "import time\ntime.sleep(60)\n"

#: Bajarilishi kafolatlangan kod (tiklanishdan keyingi urinish uchun).
WORKING_CODE = "print('tiklandim')\n"

#: Backoff kutishini "o'tkazib yuborish" uchun yetarli vaqt.
#: Eng katta backoff `RETRY_BASE_DELAY_SECONDS * RETRY_MULTIPLIER^n` + jitter,
#: ikki urinish uchun bu 10 soniyadan ancha kichik.
BACKOFF_SKIP_SECONDS = 120

#: "Yo'qolgan job" deb hisoblanishi uchun kerakli yosh
#: (`scheduler.LOST_JOB_GRACE_SECONDS = 30`).
LOST_SKIP_SECONDS = 120

#: `_claim_without_finishing()` ishlatadigan "qulagan" worker nomi.
GHOST_WORKER_ID = "e2e-worker-quladi"


async def _submit(
    client: httpx.AsyncClient,
    prefix: str,
    headers: dict[str, str],
    code: str,
    **fields: object,
) -> str:
    """Job yuboradi va uning identifikatorini qaytaradi."""
    response = await client.post(
        f"{prefix}/jobs",
        headers=headers,
        json={"code": code, "runtime": Runtime.PYTHON.value, **fields},
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == JobStatus.QUEUED.value
    return str(response.json()["id"])


async def _claim_without_finishing(job_id: str, worker_id: str) -> None:
    """Job'ni navbatdan oladi, lease oladi, `RUNNING` qiladi — va to'xtaydi.

    Bu `Worker._process()` ning bajarishdan OLDINGI holati: lease Redis'da,
    `executions` yozuvi `RUNNING`, job `RUNNING`. Keyin protsess "o'ladi".
    """
    queue = QueueService()
    dequeued = await queue.dequeue(worker_id, timeout=0)
    assert dequeued == job_id, f"navbatdan boshqa job keldi: {dequeued}"

    async with session_scope() as session:
        reliability = ReliabilityService(session)
        assert await reliability.acquire_lease(job_id, worker_id) is True

        job = await JobService(session).get_internal(job_id)
        execution = await ExecutionService(session).start(job, worker_id)

        assert JobStatus(job.status) is JobStatus.RUNNING
        assert ExecutionStatus(execution.status) is ExecutionStatus.RUNNING
        assert execution.lease_expires_at is not None


# ---------------------------------------------------------------------------
# 1. Retry -> DLQ -> qo'lda qayta urinish
# ---------------------------------------------------------------------------


async def test_retry_chain_ends_in_dlq_then_manual_retry(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    worker: Worker,
    scheduler: SchedulerWorker,
    advance_time: Callable[..., Awaitable[None]],
    fetch_job: Callable[..., Awaitable[Job]],
    fetch_executions: Callable[..., Awaitable[list[Execution]]],
) -> None:
    """`max_retries=2`: 3 urinish -> DLQ -> tuzatib qayta urinish.

    Har bosqich ALOHIDA tekshiriladi, chunki `RETRYING -> QUEUED` o'tishining
    egasi `scheduler` (CONTRACTS "QO'SHIMCHA 4 §A"): egasi ishlamasa job
    `RETRYING` da muzlab qolardi va buni faqat bosqichma-bosqich tekshiruv
    ko'rsatadi.
    """
    job_id = await _submit(client, api_prefix, auth_headers, FAILING_CODE, max_retries=2)

    # --- 1-urinish -> RETRYING ---------------------------------------
    assert await worker.process_one(timeout=0) is True
    job = await fetch_job(job_id)
    assert JobStatus(job.status) is JobStatus.RETRYING
    assert job.retry_count == 1
    assert FailureReason(job.failure_reason) is FailureReason.NON_ZERO_EXIT
    assert "RuntimeError" in (job.error or "")

    # Navbatda YO'Q, kechiktirilganlar ro'yxatida BOR — backoff kutilmoqda.
    assert await scheduler.redis.lrange(RedisKeys.queue("normal"), 0, -1) == []
    assert await scheduler.redis.zcard(RedisKeys.DELAYED) == 1

    # --- scheduler `RETRYING -> QUEUED` ------------------------------
    await advance_time(BACKOFF_SKIP_SECONDS, job_ids=[job_id])
    await scheduler.tick()
    assert JobStatus((await fetch_job(job_id)).status) is JobStatus.QUEUED

    # --- 2-urinish -> RETRYING ---------------------------------------
    assert await worker.process_one(timeout=0) is True
    job = await fetch_job(job_id)
    assert JobStatus(job.status) is JobStatus.RETRYING
    assert job.retry_count == 2

    await advance_time(BACKOFF_SKIP_SECONDS, job_ids=[job_id])
    await scheduler.tick()
    assert JobStatus((await fetch_job(job_id)).status) is JobStatus.QUEUED

    # --- 3-urinish -> DEAD_LETTER ------------------------------------
    assert await worker.process_one(timeout=0) is True
    job = await fetch_job(job_id)
    assert JobStatus(job.status) is JobStatus.DEAD_LETTER
    assert job.finished_at is not None
    # `max_retries=2` -> uchta urinish (1 asosiy + 2 qayta).
    assert job.retry_count == 2
    assert job.attempts_used == 3

    # --- `executions` jadvalida UCHTA urinish ------------------------
    executions = await fetch_executions(job_id)
    assert [item.attempt_number for item in executions] == [1, 2, 3]
    assert all(
        ExecutionStatus(item.status) is ExecutionStatus.FAILED for item in executions
    ), [str(item.status) for item in executions]

    # --- DLQ yozuvi --------------------------------------------------
    listed = await client.get(f"{api_prefix}/dlq", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert len(items) == 1
    entry = items[0]
    assert entry["job_id"] == job_id
    assert entry["failure_reason"] == FailureReason.NON_ZERO_EXIT.value
    assert "RuntimeError" in (entry["last_error"] or "")
    assert entry["resolved"] is False
    assert entry["retry_count"] == 2

    stats = await client.get(f"{api_prefix}/dlq/stats", headers=auth_headers)
    assert stats.status_code == 200, stats.text
    assert stats.json()["depth"] == 1
    assert stats.json()["unresolved"] == 1
    assert stats.json()["resolved"] == 0
    assert stats.json()["by_reason"][FailureReason.NON_ZERO_EXIT.value] == 1

    # --- Qo'lda qayta urinish ----------------------------------------
    # Mijoz muammoni tuzatgan deb hisoblanadi: `retry_count` NOLLANADI
    # (yangi urinishlar seriyasi) va yozuv hal qilingan deb belgilanadi.
    retried = await client.post(
        f"{api_prefix}/dlq/{entry['id']}/retry", headers=auth_headers, json={}
    )
    assert retried.status_code == 200, retried.text
    assert retried.json()["job_id"] == job_id
    assert retried.json()["status"] == JobStatus.QUEUED.value
    assert retried.json()["requeued"] is True
    assert retried.json()["resolved"] is True

    job = await fetch_job(job_id)
    assert JobStatus(job.status) is JobStatus.QUEUED
    assert job.retry_count == 0
    assert job.failure_reason is None
    assert await scheduler.redis.lrange(RedisKeys.queue("normal"), 0, -1) == [
        f"normal:{job_id}"
    ]

    # DLQ chuqurligi bo'shadi (yozuvning O'ZI tarix uchun qoladi).
    stats = await client.get(f"{api_prefix}/dlq/stats", headers=auth_headers)
    assert stats.json()["depth"] == 0
    assert stats.json()["total"] == 1
    assert stats.json()["resolved"] == 1


# ---------------------------------------------------------------------------
# 2. Worker qulashi (lease yo'qolishi)
# ---------------------------------------------------------------------------


async def test_crashed_worker_job_is_recovered_by_another(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    worker_b: Worker,
    scheduler: SchedulerWorker,
    crash_worker: Callable[..., Awaitable[None]],
    advance_time: Callable[..., Awaitable[None]],
    fetch_job: Callable[..., Awaitable[Job]],
    fetch_executions: Callable[..., Awaitable[list[Execution]]],
    fake_redis: Redis,
) -> None:
    """Worker qulasa job YO'QOLMAYDI — boshqa worker uni tugatadi."""
    job_id = await _submit(client, api_prefix, auth_headers, WORKING_CODE, max_retries=2)

    # --- Worker job'ni oldi va "quladi" ------------------------------
    await _claim_without_finishing(job_id, GHOST_WORKER_ID)
    assert await fake_redis.get(RedisKeys.lease(job_id)) == GHOST_WORKER_ID
    await crash_worker(job_id)
    assert await fake_redis.get(RedisKeys.lease(job_id)) is None

    # --- Reaper yo'qolgan urinishni yopadi ---------------------------
    async with session_scope() as session:
        recovered = await ReliabilityService(session).reap_expired_leases()
    assert recovered == 1

    lost = await fetch_executions(job_id)
    assert len(lost) == 1
    assert ExecutionStatus(lost[0].status) is ExecutionStatus.LOST
    assert FailureReason(lost[0].failure_reason) is FailureReason.LEASE_LOST
    assert lost[0].finished_at is not None
    assert lost[0].lease_expires_at is None

    job = await fetch_job(job_id)
    assert JobStatus(job.status) is JobStatus.RETRYING
    assert job.retry_count == 1

    # --- Scheduler qayta navbatga qo'yadi ----------------------------
    await advance_time(BACKOFF_SKIP_SECONDS, job_ids=[job_id])
    await scheduler.tick()
    assert JobStatus((await fetch_job(job_id)).status) is JobStatus.QUEUED

    # --- BOSHQA worker bajaradi --------------------------------------
    assert await worker_b.process_one(timeout=0) is True
    job = await fetch_job(job_id)
    assert JobStatus(job.status) is JobStatus.SUCCESS, "JOB YO'QOLDI"
    assert job.stdout == "tiklandim\n"
    assert job.exit_code == 0

    executions = await fetch_executions(job_id)
    assert [item.attempt_number for item in executions] == [1, 2]
    assert ExecutionStatus(executions[0].status) is ExecutionStatus.LOST
    assert executions[0].worker_id == GHOST_WORKER_ID
    assert ExecutionStatus(executions[1].status) is ExecutionStatus.SUCCESS
    assert executions[1].worker_id == worker_b.worker_id

    # Mijoz loglardan NEGA ikkinchi urinish bo'lganini ko'radi.
    logs = await client.get(f"{api_prefix}/jobs/{job_id}/logs", headers=auth_headers)
    assert logs.status_code == 200, logs.text
    system_lines = [
        entry["content"]
        for entry in logs.json()["entries"]
        if entry["stream"] == LogStream.SYSTEM.value
    ]
    assert system_lines, "SYSTEM log qatori yo'q — mijoz sababni bilmaydi"


# ---------------------------------------------------------------------------
# 3. Redis qulashi (navbat yo'qoldi)
# ---------------------------------------------------------------------------


async def test_flushed_redis_queue_is_rebuilt_from_database(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    worker: Worker,
    scheduler: SchedulerWorker,
    advance_time: Callable[..., Awaitable[None]],
    fetch_job: Callable[..., Awaitable[Job]],
    fake_redis: Redis,
) -> None:
    """Redis butunlay tozalansa ham job DB'dan tiklanadi.

    Bardoshlilik DB'da: navbat — faqat TEZLIK vositasi. `FLUSHALL` real
    holat (`maxmemory` evicton, replikadan tiklash, qo'lda `FLUSHDB`).
    """
    job_id = await _submit(client, api_prefix, auth_headers, WORKING_CODE)
    assert await fake_redis.lrange(RedisKeys.queue("normal"), 0, -1) == [f"normal:{job_id}"]

    # --- Redis quladi ------------------------------------------------
    await fake_redis.flushall()
    assert await fake_redis.lrange(RedisKeys.queue("normal"), 0, -1) == []
    assert await fake_redis.zcard(RedisKeys.DELAYED) == 0

    # Worker uchun job "yo'q" — navbat bo'sh.
    assert await worker.process_one(timeout=0) is False
    assert JobStatus((await fetch_job(job_id)).status) is JobStatus.QUEUED

    # --- Scheduler yo'qolgan job'ni topadi ---------------------------
    # `LOST_JOB_GRACE_SECONDS` (30) oynasi: yangi job "yo'qolgan" deb
    # hisoblanmaydi (DB commit va `RPUSH` orasidagi poygadan himoya),
    # shuning uchun job avval "qaritiladi".
    await scheduler.tick()
    assert await fake_redis.lrange(RedisKeys.queue("normal"), 0, -1) == [], (
        "grace oynasi ichidagi job qayta navbatga qo'yilmasligi kerak"
    )

    await advance_time(LOST_SKIP_SECONDS, job_ids=[job_id])
    await scheduler.tick()
    assert await fake_redis.lrange(RedisKeys.queue("normal"), 0, -1) == [f"normal:{job_id}"]

    # --- Bajarildi ---------------------------------------------------
    assert await worker.process_one(timeout=0) is True
    job = await fetch_job(job_id)
    assert JobStatus(job.status) is JobStatus.SUCCESS, "JOB YO'QOLDI"
    assert job.stdout == "tiklandim\n"


# ---------------------------------------------------------------------------
# 4. Timeout
# ---------------------------------------------------------------------------


async def test_timeout_kills_process_and_marks_job(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    worker: Worker,
    fetch_job: Callable[..., Awaitable[Job]],
    fetch_executions: Callable[..., Awaitable[list[Execution]]],
) -> None:
    """`timeout_seconds=1` + 60 soniyalik kod -> `TIMEOUT`, jarayon o'ldirilgan.

    `max_retries=0` ataylab: timeout'dan keyin DARHOL yakuniy holat kelsin,
    ya'ni test retry zanjirini emas, timeout mexanizmini tekshirsin.

    "Zombi qolmagani" DAVOMIYLIK bilan isbotlanadi: agar jarayon
    o'ldirilmaganda `process_one()` 60 soniya kutib turardi va
    `duration_ms` ~60000 bo'lardi. Bir necha soniyalik qiymat —
    `TimeoutGuard` `runner.kill()` ni chaqirgani va kutish tugaganining
    bevosita dalili.
    """
    timeout_seconds = 1
    job_id = await _submit(
        client,
        api_prefix,
        auth_headers,
        SLEEPING_CODE,
        timeout_seconds=timeout_seconds,
        max_retries=0,
    )

    assert await worker.process_one(timeout=0) is True

    job = await fetch_job(job_id)
    assert FailureReason(job.failure_reason) is FailureReason.TIMEOUT
    # `max_retries=0` — qayta urinish huquqi yo'q, shuning uchun DLQ.
    assert JobStatus(job.status) is JobStatus.DEAD_LETTER
    assert job.retry_count == 0
    assert "limit" in (job.error or "").lower() or "timeout" in (job.error or "").lower()

    # Jarayon TUGATILGAN, kutish cho'zilmagan.
    assert job.duration_ms is not None
    assert job.duration_ms < 30_000, (
        f"bajarish {job.duration_ms} ms davom etdi — jarayon o'ldirilmagan"
    )

    executions = await fetch_executions(job_id)
    assert len(executions) == 1
    assert ExecutionStatus(executions[0].status) is ExecutionStatus.TIMEOUT
    assert FailureReason(executions[0].failure_reason) is FailureReason.TIMEOUT
    assert executions[0].finished_at is not None

    # DLQ'da sabab TO'G'RI yozilgan — mijoz nimani tuzatishini biladi.
    dlq = await client.get(f"{api_prefix}/dlq", headers=auth_headers)
    assert dlq.status_code == 200, dlq.text
    assert len(dlq.json()["items"]) == 1
    assert dlq.json()["items"][0]["failure_reason"] == FailureReason.TIMEOUT.value


# ---------------------------------------------------------------------------
# 5. Bekor qilish
# ---------------------------------------------------------------------------


async def test_cancelled_job_is_removed_from_queue(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    worker: Worker,
    fetch_job: Callable[..., Awaitable[Job]],
    fetch_executions: Callable[..., Awaitable[list[Execution]]],
    fake_redis: Redis,
) -> None:
    """`QUEUED` job bekor qilinsa navbatdan olinadi va worker uni OLMAYDI."""
    job_id = await _submit(client, api_prefix, auth_headers, WORKING_CODE)
    assert await fake_redis.lrange(RedisKeys.queue("normal"), 0, -1) == [f"normal:{job_id}"]

    cancelled = await client.post(f"{api_prefix}/jobs/{job_id}/cancel", headers=auth_headers)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == JobStatus.CANCELLED.value
    assert cancelled.json()["cancelled_at"] is not None

    # Navbatdan OLIB TASHLANDI — worker uni ko'rmaydi ham.
    assert await fake_redis.lrange(RedisKeys.queue("normal"), 0, -1) == []
    assert await fake_redis.zcard(RedisKeys.DELAYED) == 0
    assert await worker.process_one(timeout=0) is False

    job = await fetch_job(job_id)
    assert JobStatus(job.status) is JobStatus.CANCELLED
    assert job.started_at is None
    # Bajarish BOSHLANMAGAN — urinish yozuvi ham yo'q.
    assert await fetch_executions(job_id) == []


# ---------------------------------------------------------------------------
# 6. Ikki worker bitta job'ni olishga urinsa
# ---------------------------------------------------------------------------


async def test_two_workers_execute_job_exactly_once(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    worker: Worker,
    worker_b: Worker,
    fetch_job: Callable[..., Awaitable[Job]],
    fetch_executions: Callable[..., Awaitable[list[Execution]]],
    fake_redis: Redis,
) -> None:
    """Navbatda DUBLIKAT a'zo bo'lsa ham kod BIR MARTA bajariladi.

    Dublikat a'zo real holat: `requeue_stale()` yoki `_recover_lost()`
    job'ni navbatga qaytargan paytda asl a'zo ham qolib ketishi mumkin.
    Himoya — lease `SET NX`: ikki worker ham job'ni navbatdan olsa, faqat
    lease egasi bajaradi.
    """
    job_id = await _submit(client, api_prefix, auth_headers, WORKING_CODE)
    await fake_redis.rpush(RedisKeys.queue("normal"), f"{Priority.NORMAL.value}:{job_id}")
    assert len(await fake_redis.lrange(RedisKeys.queue("normal"), 0, -1)) == 2

    outcomes = await asyncio.gather(
        worker.process_one(timeout=0),
        worker_b.process_one(timeout=0),
    )
    # Ikkisi ham navbatdan a'zo oldi (dublikat bor edi).
    assert outcomes == [True, True]

    job = await fetch_job(job_id)
    assert JobStatus(job.status) is JobStatus.SUCCESS
    assert job.stdout == "tiklandim\n"

    # ENG MUHIM TASDIQ: kod bir marta bajarilgan.
    executions = await fetch_executions(job_id)
    assert len(executions) == 1, [
        (item.attempt_number, item.worker_id) for item in executions
    ]
    assert executions[0].attempt_number == 1
    assert ExecutionStatus(executions[0].status) is ExecutionStatus.SUCCESS

    # Navbat va `processing` ro'yxatlari tozalandi.
    assert await fake_redis.lrange(RedisKeys.queue("normal"), 0, -1) == []
    assert await fake_redis.lrange(RedisKeys.processing(worker.worker_id), 0, -1) == []
    assert await fake_redis.lrange(RedisKeys.processing(worker_b.worker_id), 0, -1) == []


async def test_worker_skips_job_held_by_another_lease(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    worker: Worker,
    fetch_executions: Callable[..., Awaitable[list[Execution]]],
    fake_redis: Redis,
) -> None:
    """Lease boshqa worker'da bo'lsa, job'ni olgan worker BAJARMAYDI.

    Oldingi test natijani (bitta urinish) tekshiradi, bu test esa
    MEXANIZMNI: lease `SET NX` muvaffaqiyatsiz bo'lsa worker urinish
    yozuvini ham yaratmasligi kerak — aks holda `executions` da
    "boshlangan, lekin hech kim tugatmagan" yozuv paydo bo'lardi.
    """
    job_id = await _submit(client, api_prefix, auth_headers, WORKING_CODE)

    async with session_scope() as session:
        assert await ReliabilityService(session).acquire_lease(job_id, GHOST_WORKER_ID) is True

    # Job navbatdan OLINADI (`True`), lekin bajarilmaydi.
    assert await worker.process_one(timeout=0) is True
    assert await fetch_executions(job_id) == []
    assert await fake_redis.get(RedisKeys.lease(job_id)) == GHOST_WORKER_ID

    # Lease egasi o'zi bo'shatgandan keyin job qayta navbatga tushishi
    # kerak — bu `scheduler` ning "yo'qolgan job" qadamining ishi va
    # `test_flushed_redis_queue_is_rebuilt_from_database` da tekshiriladi.
    assert await fake_redis.lrange(RedisKeys.queue("normal"), 0, -1) == []


__all__ = [
    "BACKOFF_SKIP_SECONDS",
    "FAILING_CODE",
    "GHOST_WORKER_ID",
    "LOST_SKIP_SECONDS",
    "SLEEPING_CODE",
    "WORKING_CODE",
    "test_cancelled_job_is_removed_from_queue",
    "test_crashed_worker_job_is_recovered_by_another",
    "test_flushed_redis_queue_is_rebuilt_from_database",
    "test_retry_chain_ends_in_dlq_then_manual_retry",
    "test_timeout_kills_process_and_marks_job",
    "test_two_workers_execute_job_exactly_once",
    "test_worker_skips_job_held_by_another_lease",
]
