"""Durabl — `WorkerPool` (production kirish nuqtasi) integratsiya testlari.

`python -m app.workers.worker_pool` deploy'da N ta `Worker` ni boshqaradigan
supervisor sifatida ishlaydi, lekin uning o'zi hech qaerda tekshirilmagan
edi: integratsiya testlari `Worker.process_one()` ni bevosita chaqiradi,
ya'ni `setup()`/`_supervise()`/`_handle_crash()`/`teardown()` zanjiri
qoplanmay qolardi. Aynan shu zanjir ishlab chiqarishda eng ko'p vaqt
ishlaydigan kod.

## Nega `WORKER_POLL_TIMEOUT_SECONDS = 0` SHART

`Worker.run()` navbatni `QueueService.dequeue()` bilan o'qiydi, u esa
oxirgi navbatni `BLMOVE` bilan kutadi. `fakeredis` da bloklanuvchi
`BLMOVE` SERVER tomonida emas, MIJOZ hodisa halqasida kutadi — ya'ni
butun event loop qotib qoladi. Nol kutish vaqtida `dequeue()`
bloklanmaydigan `LMOVE` ga o'tadi va `Worker.run()` o'zining
`IDLE_PAUSE_SECONDS` pauzasi bilan aylanadi.

## Nega `close_resources = False`

`PeriodicWorker` standart holatda halqa tugagach `close_db()` va
`close_redis()` chaqiradi — mustaqil protsess uchun to'g'ri, lekin testda
bu `test_engine`/`fake_redis` fixture'larining ulanishini uzib, keyingi
assert'larni yiqitardi.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import pytest
from app.config import settings
from app.constants import JobStatus, Priority, RedisKeys, WorkerState
from app.database import get_sessionmaker
from app.models.job import Job
from app.services.queue_service import QueueService
from app.workers import worker_pool as worker_pool_module
from app.workers.worker_pool import WorkerPool
from sqlalchemy import select

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from collections.abc import AsyncIterator, Awaitable, Callable

    from app.models.user import User
    from redis.asyncio import Redis

pytestmark = pytest.mark.integration

#: Kutish chegarasi (soniya) — test qotib qolmasligi uchun.
#: Ataylab saxiy: `--cov` bilan ishlaganda butun to'plam ikki barobar
#: sekinlashadi va bu test HAQIQIY `Worker.run()` halqasini (jarayon
#: yaratish bilan) kutadi. Chegara "osilib qolmaslik" uchun, tezlikni
#: o'lchash uchun emas.
WAIT_TIMEOUT_SECONDS = 30.0

#: Holat o'zgarishini kutish qadami.
POLL_STEP_SECONDS = 0.02


@pytest.fixture
async def pool(
    test_engine: Any,
    fake_redis: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[WorkerPool]:
    """Ikki slotli pool — `setup()` chaqirilmagan holda qaytariladi.

    `teardown()` fixture'da kafolatlanadi: test assert'da yiqilsa ham
    `TaskGroup` yopiladi, aks holda pytest "Task was destroyed" bilan
    keyingi testlarni ham ifloslantirardi.
    """
    monkeypatch.setattr(settings, "WORKER_POLL_TIMEOUT_SECONDS", 0)
    # Qayta ishga tushirish pauzasi testni sekinlashtirmasligi uchun.
    monkeypatch.setattr(worker_pool_module, "RESTART_DELAY_SECONDS", 0.0)

    instance = WorkerPool(concurrency=2)
    instance.close_resources = False
    try:
        yield instance
    finally:
        if instance._stack is not None:
            instance.request_stop()
            await asyncio.wait_for(instance.teardown(), timeout=WAIT_TIMEOUT_SECONDS)


async def _wait_until(condition: Callable[[], bool]) -> None:
    """Shart bajarilguncha kutadi (chegara bilan).

    `asyncio.Event` (ASYNC110 tavsiyasi) bu yerda yaramaydi: kuzatilayotgan
    holat worker'ning ICHKI maydoni va u hech qanday hodisa qo'ymaydi,
    ya'ni polling yagona yo'l. Chegara `asyncio.timeout` bilan qo'yilgan,
    demak test qotib qolmaydi.
    """
    async with asyncio.timeout(WAIT_TIMEOUT_SECONDS):
        while not condition():  # noqa: ASYNC110 - hodisa manbai yo'q, polling SHART
            await asyncio.sleep(POLL_STEP_SECONDS)


# ---------------------------------------------------------------------------
# Hayot sikli
# ---------------------------------------------------------------------------


async def test_setup_starts_one_worker_per_slot(pool: WorkerPool) -> None:
    """`setup()` har slot uchun bitta `Worker` yasaydi va kuzatuvchi ochadi."""
    assert pool.state is WorkerState.STARTING

    await pool.setup()
    await _wait_until(lambda: len(pool.workers) == pool.concurrency)

    ids = [worker.worker_id for worker in pool.workers]
    assert ids == [WorkerPool.worker_id_for(0), WorkerPool.worker_id_for(1)]
    # Har slot UNIKAL identifikator oladi — reestrda bir-birini bosmaydi.
    assert len(set(ids)) == pool.concurrency
    assert pool.restarts == 0
    assert pool.state is WorkerState.IDLE


async def test_teardown_stops_all_workers(pool: WorkerPool) -> None:
    """`teardown()` barcha worker'ni to'xtatadi va `TaskGroup` ni yopadi."""
    await pool.setup()
    await _wait_until(lambda: len(pool.workers) == pool.concurrency)

    pool.request_stop()
    assert pool.state is WorkerState.DRAINING
    await asyncio.wait_for(pool.teardown(), timeout=WAIT_TIMEOUT_SECONDS)

    assert all(task.done() for task in pool._tasks.values())
    # Takroriy `teardown()` xavfsiz (stack allaqachon yopilgan).
    await pool.teardown()


async def test_tick_requests_stop_when_all_supervisors_finished(pool: WorkerPool) -> None:
    """Barcha kuzatuvchi tugagan bo'lsa `tick()` pool'ni to'xtatadi.

    Bu "navbat bo'sh, ish qolmadi" holati emas — worker'lar o'z xohishi
    bilan chiqqanda (masalan graceful shutdown) pool osilib qolmasligi
    kerak.
    """
    await pool.setup()
    await _wait_until(lambda: len(pool.workers) == pool.concurrency)

    # Worker'lar chiqishini KUTAMIZ: `request_stop()` dan keyin `run()`
    # halqasi tugaydi va kuzatuvchi `_supervise()` ham qaytadi.
    for worker in pool.workers:
        worker.request_stop()
    await _wait_until(lambda: all(task.done() for task in pool._tasks.values()))

    assert pool.is_stopping is False
    await pool.tick()
    assert pool.is_stopping is True


async def test_tick_keeps_running_while_supervisors_alive(pool: WorkerPool) -> None:
    """Hech bo'lmasa bitta kuzatuvchi tirik bo'lsa `tick()` to'xtatmaydi."""
    await pool.setup()
    await _wait_until(lambda: len(pool.workers) == pool.concurrency)

    await pool.tick()

    assert pool.is_stopping is False


# ---------------------------------------------------------------------------
# Haqiqiy ish
# ---------------------------------------------------------------------------


async def test_pool_processes_queued_job(
    pool: WorkerPool,
    fake_redis: Redis,
    user: User,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Pool navbatdagi job'ni HAQIQATAN bajaradi (`_supervise` -> `Worker.run`)."""
    job = await job_factory(
        status=JobStatus.QUEUED,
        code="print('pool ishladi')\n",
        priority=Priority.NORMAL,
    )
    job_id = job.id
    # `QueueService` FAQAT Redis bilan ishlaydi (DB sessiyasi kerak emas).
    await QueueService().enqueue(job_id, Priority.NORMAL)

    await pool.setup()
    await _wait_until(lambda: len(pool.workers) == pool.concurrency)

    async def finished() -> bool:
        async with get_sessionmaker()() as session:
            status = await session.scalar(select(Job.status).where(Job.id == job_id))
        return JobStatus(status) is JobStatus.SUCCESS

    async with asyncio.timeout(WAIT_TIMEOUT_SECONDS):
        while not await finished():  # noqa: ASYNC110 - DB holati pollingi
            await asyncio.sleep(POLL_STEP_SECONDS)

    # `Worker.jobs_processed` DB commit'idan KEYIN oshadi, shuning uchun
    # hisoblagich alohida kutiladi — aks holda test poyga tufayli
    # (holat `success`, hisoblagich hamon 0) tasodifiy yiqilardi.
    await _wait_until(lambda: pool.jobs_processed == 1)
    assert pool.state is WorkerState.BUSY
    assert await fake_redis.lrange(RedisKeys.queue(Priority.NORMAL), 0, -1) == []


# ---------------------------------------------------------------------------
# Qulash va qayta ishga tushirish
# ---------------------------------------------------------------------------


async def test_handle_crash_restarts_until_limit(pool: WorkerPool) -> None:
    """Qulagan worker `MAX_RESTARTS` gacha qayta ishga tushiriladi, keyin pool to'xtaydi."""
    limit = worker_pool_module.MAX_RESTARTS
    decisions = [
        await pool._handle_crash(0, "w-0", RuntimeError("qulash")) for _ in range(limit + 1)
    ]

    # Chegaraga yetguncha hammasi `True` (qayta ishga tushiriladi).
    assert decisions[:limit] == [True] * limit
    # Chegara oshgach — `False` va pool to'xtatiladi.
    assert decisions[limit] is False
    assert pool.is_stopping is True
    assert pool.restarts == limit + 1


async def test_handle_crash_gives_up_when_already_stopping(pool: WorkerPool) -> None:
    """To'xtash so'ralgan bo'lsa qulagan worker QAYTA ishga tushirilmaydi."""
    pool.request_stop()

    assert await pool._handle_crash(0, "w-0", RuntimeError("qulash")) is False


async def test_crashing_worker_is_restarted_in_place(
    pool: WorkerPool, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_supervise()` qulagan worker o'rniga YANGI nusxa yasaydi.

    `Worker.run()` birinchi chaqiruvda xato tashlaydi, ikkinchisida
    normal kutadi — shunda slot uchun ikki xil `Worker` nusxasi
    yaratilgani ko'rinadi, ya'ni qayta ishga tushirish ishlagan.
    """
    calls: list[int] = []
    original_run = worker_pool_module.Worker.run

    async def flaky_run(self: Any) -> None:
        calls.append(id(self))
        if len(calls) == 1:
            raise RuntimeError("birinchi urinishda qulash")
        await original_run(self)

    monkeypatch.setattr(worker_pool_module.Worker, "run", flaky_run)

    pool.concurrency = 1
    await pool.setup()
    await _wait_until(lambda: pool.restarts >= 1)

    assert pool.restarts == 1
    # Ikkinchi nusxa ishga tushdi va u BIRINCHISIDAN boshqa obyekt.
    await _wait_until(lambda: len(calls) >= 2)
    assert calls[0] != calls[1]


__all__ = ["POLL_STEP_SECONDS", "WAIT_TIMEOUT_SECONDS"]
