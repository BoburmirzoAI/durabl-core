"""Durabl — worker'larning integratsiya testlari.

Har bir worker O'Z halqasidan ajratilgan kirish nuqtasi bilan sinaladi
(`Worker.process_one()`, `PeriodicWorker.tick()`), ya'ni test signal
kutmaydi va `asyncio.sleep` ga bog'lanmaydi.

## `RETRYING -> QUEUED` — eng muhim test

CONTRACTS "QO'SHIMCHA 4 §A" dagi tuzatish. `ReliabilityService.schedule_retry()`
job'ni ATAYLAB `RETRYING` holatida qoldirib faqat Redis'ning kechiktirilgan
ZSET'iga qo'yadi; `QueueService.promote_due()` esa faqat Redis'ga tegadi
(DB sessiyasi yo'q). Ya'ni DB o'tishining EGASI — `SchedulerWorker._promote()`.
Bu bo'lmasa worker promote qilingan job'ni olib `mark_running` da
`InvalidStateTransitionError('retrying' -> 'running')` olardi, chunki
`JOB_STATUS_TRANSITIONS[RETRYING] = {QUEUED, DEAD_LETTER, CANCELLED}`.

## Nega `delay_seconds=0.05` + qisqa `sleep`

`QueueService.enqueue()` faqat `delay_seconds > 0` bo'lganda ZSET'ga
yozadi (manfiy yoki nol qiymat to'g'ridan-to'g'ri navbatga qo'yadi), va
`promote_due()` chegara vaqtini O'ZI oladi. Shuning uchun kechiktirilgan
a'zoni yasashning yagona halol yo'li — kichik haqiqiy kechikish.

## `WebhookService.deliveries()` natijasini OCHIQ annotatsiyalash

Servis klassida `list` nomli metod bor, shuning uchun uning
`tuple[list[WebhookDelivery], int]` annotatsiyasidagi `list` mypy uchun
BUILTIN emas, metodga ishora qiladi (`app/services/webhook_service.py:1145`
dagi `valid-type` xatosi shundan). Natijani indekslash mypy'da xato
beradi, shuning uchun test o'zgaruvchini OCHIQ e'lon qiladi — bu ilova
kodiga tegmasdan tipni to'g'rilaydi.

## `exclusive` lock

`SchedulerWorker` va `DlqProcessor` `exclusive = True`: bir vaqtda faqat
bitta nusxa ishlashi kerak (`promote_due` ikki marta chaqirilsa job ikki
marta navbatga tushardi). Lock `RedisKeys.lock(name)` da, `SET NX EX` bilan.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

import httpx
import pytest
import respx
from app.config import settings
from app.constants import (
    DeliveryStatus,
    ExecutionStatus,
    FailureReason,
    JobStatus,
    Priority,
    RedisKeys,
    WebhookEvent,
)
from app.models.webhook_delivery import WebhookDelivery
from app.schemas.base import PaginationParams
from app.schemas.webhook import WebhookCreate
from app.services.queue_service import QueueService
from app.services.reliability_service import ReliabilityService
from app.services.webhook_service import WebhookService
from app.utils.time_utils import utcnow
from app.workers.dlq_processor import DlqProcessor
from app.workers.runner import PeriodicWorker
from app.workers.scheduler import LOST_JOB_GRACE_SECONDS, SchedulerWorker
from app.workers.webhook_sender import WebhookSender
from app.workers.worker import Worker

from tests.factories import make_execution

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from collections.abc import Awaitable, Callable

    from app.models.job import Job
    from app.models.user import User
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

#: Kechiktirilgan a'zo uchun eng kichik haqiqiy kechikish (modul docstring'i).
DELAY_SECONDS = 0.05

#: Kechikish o'tib ketganiga ishonch hosil qilish uchun kutish.
SETTLE_SECONDS = 0.15

#: Webhook yuboriladigan (yechilmaydigan) manzil.
HOOK_URL = "https://sender.durabl-test.invalid/hook"


def first_page() -> PaginationParams:
    """Standart sahifalash parametrlari (`WebhookService.deliveries()` uchun)."""
    return PaginationParams(page=1, page_size=20)


async def enqueue_delayed(job: Job) -> None:
    """Job'ni kechiktirilgan ZSET'ga qo'yadi va vaqti o'tishini kutadi."""
    await QueueService().enqueue(job.id, Priority(job.priority), delay_seconds=DELAY_SECONDS)
    await asyncio.sleep(SETTLE_SECONDS)


async def test_process_one_executes_job(
    db_session: AsyncSession,
    fake_redis: Redis,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`Worker.process_one()` navbatdagi job'ni to'liq bajaradi."""
    job = await job_factory(status=JobStatus.QUEUED, queued_at=utcnow())
    await QueueService().enqueue(job.id, Priority.NORMAL)

    assert await Worker(worker_id="w-exec").process_one(timeout=1) is True

    db_session.expire_all()
    await db_session.refresh(job)
    assert JobStatus(job.status) is JobStatus.SUCCESS
    assert job.exit_code == 0
    assert job.finished_at is not None
    # Navbat bo'shadi va `processing` ro'yxatida muallaq a'zo qolmadi.
    assert await QueueService().depth_for(Priority.NORMAL) == 0
    assert await QueueService().processing_jobs("w-exec") == []


async def test_process_one_on_empty_queue(fake_redis: Redis) -> None:
    """Navbat bo'sh bo'lsa `False` qaytadi (xato tashlamaydi)."""
    assert await Worker(worker_id="w-idle").process_one(timeout=1) is False


async def test_process_one_skips_terminal_job(
    db_session: AsyncSession,
    fake_redis: Redis,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Yakuniy holatdagi job QAYTA bajarilmaydi, lekin `ack` qilinadi."""
    job = await job_factory(status=JobStatus.SUCCESS, finished_at=utcnow(), exit_code=0)
    await QueueService().enqueue(job.id, Priority.NORMAL)

    assert await Worker(worker_id="w-skip").process_one(timeout=1) is True

    db_session.expire_all()
    await db_session.refresh(job)
    assert JobStatus(job.status) is JobStatus.SUCCESS
    assert job.started_at is None, "job bajarilmagan bo'lishi kerak"
    assert await QueueService().processing_jobs("w-skip") == []


async def test_scheduler_promotes_retrying_to_queued(
    db_session: AsyncSession,
    fake_redis: Redis,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`SchedulerWorker.tick()` `RETRYING` job'ni `QUEUED` ga o'tkazadi.

    CONTRACTS "QO'SHIMCHA 4 §A" — modul docstring'idagi eng muhim qoida.
    """
    job = await job_factory(status=JobStatus.RETRYING, retry_count=1, queued_at=utcnow())
    await enqueue_delayed(job)

    scheduler = SchedulerWorker()
    await scheduler.tick()

    db_session.expire_all()
    await db_session.refresh(job)
    assert JobStatus(job.status) is JobStatus.QUEUED
    assert job.queued_at is not None
    # A'zo kechiktirilgandan oddiy navbatga KO'CHDI.
    assert await fake_redis.zcard(RedisKeys.DELAYED) == 0
    assert await QueueService().depth_for(Priority.NORMAL) == 1

    # Promote qilingan job'ni worker muammosiz oladi (eski xato aynan
    # shu nuqtada `InvalidStateTransitionError` berardi).
    assert await Worker(worker_id="w-after-promote").process_one(timeout=1) is True
    db_session.expire_all()
    await db_session.refresh(job)
    assert JobStatus(job.status) is JobStatus.SUCCESS


async def test_scheduler_promotes_pending_scheduled_job(
    db_session: AsyncSession,
    fake_redis: Redis,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Rejalashtirilgan `PENDING` job ham vaqti kelganda `QUEUED` bo'ladi."""
    job = await job_factory(status=JobStatus.PENDING, scheduled_at=utcnow())
    await enqueue_delayed(job)

    await SchedulerWorker().tick()

    db_session.expire_all()
    await db_session.refresh(job)
    assert JobStatus(job.status) is JobStatus.QUEUED


async def test_scheduler_recovers_lost_job(
    db_session: AsyncSession,
    fake_redis: Redis,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """DB'da `QUEUED`, lekin navbatda YO'Q job qaytarib qo'yiladi."""
    stale = utcnow() - timedelta(seconds=LOST_JOB_GRACE_SECONDS + 10)
    job = await job_factory(status=JobStatus.QUEUED, queued_at=stale)
    assert await QueueService().depth_for(Priority.NORMAL) == 0

    scheduler = SchedulerWorker()
    await scheduler.tick()

    assert await QueueService().depth_for(Priority.NORMAL) == 1
    db_session.expire_all()
    await db_session.refresh(job)
    assert JobStatus(job.status) is JobStatus.QUEUED


async def test_scheduler_ignores_fresh_queued_job(
    fake_redis: Redis, job_factory: Callable[..., Awaitable[Job]]
) -> None:
    """Hozir navbatga qo'yilgan job "yo'qolgan" deb hisoblanmaydi (poygadan himoya)."""
    await job_factory(status=JobStatus.QUEUED, queued_at=utcnow())

    await SchedulerWorker().tick()

    assert await QueueService().depth_for(Priority.NORMAL) == 0


async def test_scheduler_reaps_expired_lease(
    db_session: AsyncSession,
    fake_redis: Redis,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Scheduler sikli muddati tugagan lease'ni ham yig'adi."""
    now = utcnow()
    job = await job_factory(status=JobStatus.RUNNING, queued_at=now, started_at=now)
    execution = make_execution(
        job_id=job.id,
        status=ExecutionStatus.RUNNING,
        worker_id="qulagan-worker",
        started_at=now,
        lease_expires_at=now - timedelta(seconds=120),
    )
    db_session.add(execution)
    await db_session.commit()

    await SchedulerWorker().tick()

    db_session.expire_all()
    await db_session.refresh(job)
    assert JobStatus(job.status) in {JobStatus.RETRYING, JobStatus.QUEUED}
    await db_session.refresh(execution)
    assert ExecutionStatus(execution.status) is ExecutionStatus.LOST
    assert execution.failure_reason == FailureReason.LEASE_LOST


async def test_dlq_processor_alerts_over_threshold(
    db_session: AsyncSession,
    fake_redis: Redis,
    job_factory: Callable[..., Awaitable[Job]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`DlqProcessor.tick()` chegaradan oshgan chuqurlik uchun alert yuboradi."""
    job = await job_factory(status=JobStatus.FAILED, retry_count=3)
    await ReliabilityService(db_session).move_to_dlq(
        job, failure_reason=FailureReason.NON_ZERO_EXIT, error_text="xato"
    )
    await db_session.commit()

    monkeypatch.setattr(settings, "DLQ_ALERT_THRESHOLD", 0)
    monkeypatch.setattr(settings, "DLQ_AUTO_RETRY_ENABLED", False)

    sent: list[int] = []

    class _Notifications:
        """Soxta alert kanali — servis holatsiz, almashtirish xavfsiz."""

        async def notify_dlq_threshold(self, depth: int) -> None:
            sent.append(depth)

    processor = DlqProcessor()
    processor.notifications = _Notifications()

    await processor.tick()

    assert sent == [1]
    assert processor.alerts_sent == 1


async def test_dlq_processor_quiet_below_threshold(
    db_session: AsyncSession, fake_redis: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Chuqurlik chegaradan past bo'lsa alert YUBORILMAYDI."""
    monkeypatch.setattr(settings, "DLQ_ALERT_THRESHOLD", 100)
    monkeypatch.setattr(settings, "DLQ_AUTO_RETRY_ENABLED", False)

    sent: list[int] = []

    class _Notifications:
        """Chaqirilmasligi kerak bo'lgan soxta kanal."""

        async def notify_dlq_threshold(self, depth: int) -> None:  # pragma: no cover
            sent.append(depth)

    processor = DlqProcessor()
    processor.notifications = _Notifications()

    await processor.tick()

    assert sent == []
    assert processor.alerts_sent == 0


async def test_webhook_sender_delivers_queued_delivery(
    db_session: AsyncSession,
    fake_redis: Redis,
    user: User,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`WebhookSender.tick()` navbatdagi delivery'ni yetkazadi."""
    service = WebhookService(db_session)
    await service.create(
        user, WebhookCreate(url=HOOK_URL, events=[WebhookEvent.JOB_SUCCEEDED])
    )
    job = await job_factory(status=JobStatus.SUCCESS, finished_at=utcnow(), exit_code=0)
    assert await service.dispatch(job, WebhookEvent.JOB_SUCCEEDED) == 1
    await db_session.commit()

    sender = WebhookSender()
    with respx.mock(assert_all_called=True) as mock:
        route = mock.post(HOOK_URL).mock(return_value=httpx.Response(200, text="ok"))
        await sender.tick()

    assert route.called
    assert sender.delivered_total == 1
    assert sender.failed_total == 0

    webhooks = await service.list(user)
    deliveries: list[WebhookDelivery]
    total: int
    deliveries, total = await service.deliveries(user, webhooks[0].id, first_page())
    assert total == 1
    first = deliveries[0]
    assert first.status == DeliveryStatus.SUCCESS
    assert first.response_code == 200


async def test_webhook_sender_schedules_retry_on_failure(
    db_session: AsyncSession,
    fake_redis: Redis,
    user: User,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """5xx javob qayta urinishga rejalashtiriladi (halqa to'xtamaydi)."""
    service = WebhookService(db_session)
    webhook = await service.create(
        user, WebhookCreate(url=HOOK_URL, events=[WebhookEvent.JOB_FAILED])
    )
    job = await job_factory(status=JobStatus.FAILED, finished_at=utcnow())
    await service.dispatch(job, WebhookEvent.JOB_FAILED)
    await db_session.commit()

    sender = WebhookSender()
    with respx.mock(assert_all_called=True) as mock:
        mock.post(HOOK_URL).mock(return_value=httpx.Response(503, text="band"))
        await sender.tick()

    assert sender.delivered_total == 0
    assert sender.failed_total == 1

    deliveries: list[WebhookDelivery]
    deliveries, _total = await service.deliveries(user, webhook.id, first_page())
    first = deliveries[0]
    assert first.status == DeliveryStatus.RETRYING
    assert first.next_retry_at is not None


async def test_periodic_worker_survives_tick_errors(fake_redis: Redis) -> None:
    """`tick()` xato bersa ham halqa TO'XTAMAYDI — keyingi siklga o'tadi."""

    class _Broken(PeriodicWorker):
        """Har siklda xato tashlaydigan worker (uchinchisidan keyin to'xtaydi)."""

        name = "broken"
        exclusive = False

        def __init__(self) -> None:
            super().__init__()
            self.interval_seconds = 0.01
            self.calls = 0

        async def tick(self) -> None:
            self.calls += 1
            if self.calls >= 3:
                self.request_stop()
            raise RuntimeError("ataylab xato")

    worker = _Broken()
    await asyncio.wait_for(worker.run(), timeout=10)

    assert worker.calls == 3
    assert worker.cycles == 3
    assert worker.consecutive_errors == 3


async def test_exclusive_lock_allows_single_instance(fake_redis: Redis) -> None:
    """`exclusive` worker'ning lock'i ikkinchi nusxani kiritmaydi."""

    class _Exclusive(PeriodicWorker):
        """Faqat bitta nusxada ishlashi kerak bo'lgan worker."""

        name = "yakka"
        exclusive = True

        def __init__(self) -> None:
            super().__init__()
            self.interval_seconds = 0.01

        async def tick(self) -> None:  # pragma: no cover - lock testida chaqirilmaydi
            self.request_stop()

    first = _Exclusive()
    second = _Exclusive()
    assert first.lock_key.endswith("yakka")

    assert await first._acquire_lock() is True
    assert await second._acquire_lock() is False

    await first._release_lock()
    assert await second._acquire_lock() is True
    await second._release_lock()


__all__ = [
    "DELAY_SECONDS",
    "HOOK_URL",
    "SETTLE_SECONDS",
    "enqueue_delayed",
    "first_page",
]
