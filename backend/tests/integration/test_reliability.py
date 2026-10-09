"""Durabl — ishonchlilik qatlamining (`ReliabilityService`) integratsiya testlari.

Bu yerda HTTP qatlami YO'Q: servis DB (SQLite) va Redis (`fakeredis[lua]`)
bilan BEVOSITA ishlaydi. `fakeredis` Lua bilan o'rnatilgani uchun lease'ning
compare-and-swap skripti HAQIQATAN bajariladi — ya'ni atomarlik zaxira
(`WATCH`) yo'liga tushmasdan, ishlab chiqarishdagi kod yo'li bilan sinaladi.

## Lease — eng muhim kafolat

Durabl'ning asosiy va'dasi "job yo'qolmaydi, lekin IKKI MARTA ham
bajarilmaydi". Buni lease ushlab turadi:

* `acquire_lease` faqat BITTA worker'ga `True` qaytaradi;
* `renew_lease` faqat EGASIGA ishlaydi (aks holda qulagan worker tirilib
  boshqa worker ishlayotgan job'ning lease'ini "o'ziga qaytarib" olardi);
* lease muddati tugasa `reap_expired_leases()` job'ni qayta taqsimlaydi.

## Nega `handle_failure` commit qilmaydi

U ICHKI metod (`ExecutionService.fail()` yoki reaper tranzaksiya egasi),
shuning uchun testlar o'zi `commit()` qiladi.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from app.constants import (
    ExecutionStatus,
    FailureReason,
    JobStatus,
    Priority,
    RedisKeys,
    WorkerState,
)
from app.exceptions import ExecutionError, LeaseLostError
from app.services.queue_service import QueueService
from app.services.reliability_service import ReliabilityService
from app.utils.time_utils import utcnow

from tests.factories import make_execution

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from collections.abc import Awaitable, Callable

    from app.models.execution import Execution
    from app.models.job import Job
    from app.models.user import User
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

#: Sinovdagi worker identifikatorlari.
WORKER_A = "worker-a"
WORKER_B = "worker-b"


async def running_job(
    session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
    *,
    lease_age_seconds: int = 0,
    worker_id: str = WORKER_A,
) -> tuple[Job, Execution]:
    """`RUNNING` job va unga bog'langan urinish yozuvini yaratadi.

    `lease_age_seconds > 0` bo'lsa lease O'TGAN vaqtga qo'yiladi — ya'ni
    worker qulagan holat modellashtiriladi.

    `expire_on_commit` standart (`True`) bo'lgani uchun `commit()` dan
    keyin obyektlar "eskiradi": atributga murojaat DB'ga SO'ROV yuboradi.
    Shuning uchun yozuvlar commit'dan KEYIN `refresh()` bilan qayta
    yuklanadi — aks holda chaqiruvchi `execution.id` ni o'qiganda
    `MissingGreenlet` olardi.
    """
    now = utcnow()
    job = await job_factory(status=JobStatus.RUNNING, queued_at=now, started_at=now)
    execution = make_execution(
        job_id=job.id,
        status=ExecutionStatus.RUNNING,
        worker_id=worker_id,
        started_at=now,
        lease_expires_at=now - timedelta(seconds=lease_age_seconds)
        if lease_age_seconds
        else now + timedelta(seconds=60),
    )
    session.add(execution)
    await session.flush()
    await session.commit()
    await session.refresh(job)
    await session.refresh(execution)
    return job, execution


async def test_lease_is_exclusive(
    db_session: AsyncSession,
    fake_redis: Redis,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Bitta job uchun lease'ni FAQAT bitta worker oladi."""
    job = await job_factory(status=JobStatus.QUEUED)
    service = ReliabilityService(db_session)

    assert await service.acquire_lease(job.id, WORKER_A) is True
    assert await service.acquire_lease(job.id, WORKER_B) is False
    assert await service.lease_holder(job.id) == WORKER_A

    # `SET ... NX` qat'iy: EGASI ham qayta olmaydi. Bu ataylab — lease
    # muddatini uzaytirish uchun `renew_lease()` bor, `acquire_lease()`
    # esa "bu job'ni hali hech kim olmaganmi" degan yagona savolga
    # javob beradi (ikki ma'noli bo'lsa, poyga shartlari yashirin qolardi).
    assert await service.acquire_lease(job.id, WORKER_A) is False
    assert await service.renew_lease(job.id, WORKER_A) is True


async def test_lease_renew_only_by_holder(
    db_session: AsyncSession,
    fake_redis: Redis,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`renew_lease` faqat egasiga ishlaydi (modul docstring'iga qara)."""
    job = await job_factory(status=JobStatus.QUEUED)
    service = ReliabilityService(db_session)
    await service.acquire_lease(job.id, WORKER_A)

    assert await service.renew_lease(job.id, WORKER_A) is True
    assert await service.renew_lease(job.id, WORKER_B) is False
    # Begona worker'ning urinishi egalikni O'ZGARTIRMADI.
    assert await service.lease_holder(job.id) == WORKER_A


async def test_lease_release_frees_job(
    db_session: AsyncSession,
    fake_redis: Redis,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Bo'shatilgan lease'ni boshqa worker olishi mumkin."""
    job = await job_factory(status=JobStatus.QUEUED)
    service = ReliabilityService(db_session)
    await service.acquire_lease(job.id, WORKER_A)

    await service.release_lease(job.id, WORKER_A)

    assert await service.lease_holder(job.id) is None
    assert await service.acquire_lease(job.id, WORKER_B) is True


async def test_release_by_stranger_is_ignored(
    db_session: AsyncSession,
    fake_redis: Redis,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Begona worker lease'ni bo'shata OLMAYDI — bu ikki marta bajarishga yo'l ochardi."""
    job = await job_factory(status=JobStatus.QUEUED)
    service = ReliabilityService(db_session)
    await service.acquire_lease(job.id, WORKER_A)

    await service.release_lease(job.id, WORKER_B)

    assert await service.lease_holder(job.id) == WORKER_A


async def test_expired_lease_is_reaped(
    db_session: AsyncSession,
    fake_redis: Redis,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Muddati tugagan lease'li job qayta urinishga qaytadi."""
    job, execution = await running_job(db_session, job_factory, lease_age_seconds=120)
    service = ReliabilityService(db_session)

    recovered = await service.reap_expired_leases(limit=10)
    await db_session.commit()

    assert recovered == 1
    db_session.expire_all()
    await db_session.refresh(job)
    assert JobStatus(job.status) is JobStatus.RETRYING
    assert job.retry_count == 1

    await db_session.refresh(execution)
    assert ExecutionStatus(execution.status) is ExecutionStatus.LOST
    assert execution.failure_reason == FailureReason.LEASE_LOST


async def test_live_lease_is_not_reaped(
    db_session: AsyncSession,
    fake_redis: Redis,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Redis'da lease TIRIK bo'lsa reaper job'ga tegmaydi (DB qiymati eskirgan)."""
    job, _execution = await running_job(db_session, job_factory, lease_age_seconds=120)
    service = ReliabilityService(db_session)
    # Worker hamon ishlayapti: lease Redis'da bor.
    assert await service.acquire_lease(job.id, WORKER_A) is True

    recovered = await service.reap_expired_leases(limit=10)
    await db_session.commit()

    assert recovered == 0
    db_session.expire_all()
    await db_session.refresh(job)
    assert JobStatus(job.status) is JobStatus.RUNNING


async def test_handle_failure_schedules_retry(
    db_session: AsyncSession,
    fake_redis: Redis,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Urinish qolganda qaror — `RETRYING` va kechiktirilgan navbatga qo'yish."""
    job, execution = await running_job(db_session, job_factory)
    await db_session.refresh(job)
    job.max_retries = 3
    await db_session.flush()
    service = ReliabilityService(db_session)

    decision = await service.handle_failure(
        job, execution, ExecutionError("yiqildi", failure_reason=FailureReason.NON_ZERO_EXIT)
    )
    await db_session.commit()

    assert decision is JobStatus.RETRYING
    assert JobStatus(job.status) is JobStatus.RETRYING
    assert job.retry_count == 1
    # Kechiktirilgan ZSET'ga tushdi, oddiy navbatga TUSHMADI.
    assert await fake_redis.zcard(RedisKeys.DELAYED) == 1
    assert await QueueService().depth_for(Priority.NORMAL) == 0


async def test_handle_failure_moves_to_dlq(
    db_session: AsyncSession,
    fake_redis: Redis,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Urinishlar tugaganda qaror — `DEAD_LETTER` va DLQ yozuvi."""
    job, execution = await running_job(db_session, job_factory)
    await db_session.refresh(job)
    job.max_retries = 0
    await db_session.flush()
    service = ReliabilityService(db_session)

    decision = await service.handle_failure(job, execution, LeaseLostError())
    await db_session.commit()

    assert decision is JobStatus.DEAD_LETTER
    assert JobStatus(job.status) is JobStatus.DEAD_LETTER

    entry = await service.dlq.get_by_job(job.id)
    assert entry is not None
    assert entry.resolved is False
    assert entry.failure_reason == FailureReason.LEASE_LOST


async def test_retry_from_dlq_requeues_job(
    db_session: AsyncSession,
    fake_redis: Redis,
    user: User,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """To'liq zanjir: xato -> DLQ -> `retry_from_dlq()` -> `QUEUED`."""
    job = await job_factory(status=JobStatus.FAILED, retry_count=3)
    service = ReliabilityService(db_session)

    entry = await service.move_to_dlq(
        job, failure_reason=FailureReason.NON_ZERO_EXIT, error_text="chiqish kodi 1"
    )
    await db_session.commit()
    assert JobStatus(job.status) is JobStatus.DEAD_LETTER
    assert await service.dlq.depth() == 1

    revived = await service.retry_from_dlq(entry, by_user_id=user.id, notes="tuzatildi")
    await db_session.commit()

    assert revived.id == job.id
    assert JobStatus(revived.status) is JobStatus.QUEUED
    assert revived.retry_count == 0
    assert entry.resolved is True
    assert entry.manual_retry_count == 1
    # Chuqurlik bo'shadi va job HAQIQIY navbatga tushdi.
    assert await service.dlq.depth() == 0
    assert await QueueService().depth_for(Priority.NORMAL) == 1


async def test_move_to_dlq_is_idempotent(
    db_session: AsyncSession,
    fake_redis: Redis,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Ikkinchi `move_to_dlq()` YANGI yozuv yaratmaydi (`job_id` UNIQUE)."""
    job = await job_factory(status=JobStatus.FAILED, retry_count=3)
    service = ReliabilityService(db_session)

    first = await service.move_to_dlq(
        job, failure_reason=FailureReason.TIMEOUT, error_text="birinchi"
    )
    await db_session.commit()
    second = await service.move_to_dlq(
        job, failure_reason=FailureReason.TIMEOUT, error_text="ikkinchi"
    )
    await db_session.commit()

    assert second.id == first.id
    assert second.last_error == "ikkinchi"
    assert await service.dlq.depth() == 1


async def test_worker_registry_lifecycle(
    db_session: AsyncSession, fake_redis: Redis
) -> None:
    """Worker reestri: ro'yxatdan o'tish -> heartbeat -> o'chirish."""
    service = ReliabilityService(db_session)

    await service.register_worker(WORKER_A, state=WorkerState.IDLE, concurrency=2)
    workers = await service.list_workers()
    assert [row["worker_id"] for row in workers] == [WORKER_A]
    assert workers[0]["state"] is WorkerState.IDLE
    assert workers[0]["is_alive"] is True
    assert workers[0]["concurrency"] == 2

    await service.heartbeat_worker(WORKER_A, state=WorkerState.BUSY, jobs_processed=7)
    updated = (await service.list_workers())[0]
    assert updated["state"] is WorkerState.BUSY
    assert updated["jobs_processed"] == 7
    assert updated["seconds_since_heartbeat"] >= 0

    await service.unregister_worker(WORKER_A)
    assert await service.list_workers() == []


async def test_prune_dead_workers(db_session: AsyncSession, fake_redis: Redis) -> None:
    """Heartbeat kaliti yo'qolgan worker reestrdan o'chiriladi."""
    service = ReliabilityService(db_session)
    await service.register_worker(WORKER_A, state=WorkerState.IDLE)
    await service.register_worker(WORKER_B, state=WorkerState.IDLE)

    # Tirik worker'da hech narsa o'chmaydi.
    assert await service.prune_dead_workers() == 0

    # `WORKER_B` quladi: TTL'li tiriklik kaliti yo'qoldi (HASH yozuvi qoldi).
    await fake_redis.delete(RedisKeys.worker_heartbeat(WORKER_B))
    dead = (await service.list_workers())
    assert {row["worker_id"]: row["state"] for row in dead}[WORKER_B] is WorkerState.DEAD

    assert await service.prune_dead_workers() == 1
    assert [row["worker_id"] for row in await service.list_workers()] == [WORKER_A]


async def test_cancel_signal_roundtrip(
    db_session: AsyncSession,
    fake_redis: Redis,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Bekor qilish signali yoziladi, o'qiladi va tozalanadi."""
    job = await job_factory(status=JobStatus.RUNNING)
    service = ReliabilityService(db_session)

    assert await service.is_cancel_requested(job.id) is False

    await service.request_cancel(job.id)
    assert await service.is_cancel_requested(job.id) is True

    await service.clear_cancel(job.id)
    assert await service.is_cancel_requested(job.id) is False


__all__ = ["WORKER_A", "WORKER_B", "running_job"]
