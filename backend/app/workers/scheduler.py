"""Durabl — rejalashtiruvchi (scheduler) worker'i.

Scheduler Durabl'ning "vaqt mashinasi" va AYNI PAYTDA "job yo'qolmaydi"
kafolatining oxirgi himoya chizig'i. Har siklda to'rt ish bajariladi:

1. **`promote_due()` + DB o'tishi.** `ReliabilityService.schedule_retry()`
   job'ni ATAYLAB `RETRYING` holatida qoldiradi va faqat Redis'ning
   kechiktirilgan ZSET'iga qo'yadi (`QueueService.promote_due()` esa DB
   sessiyasiga ega emas). Ya'ni `RETRYING -> QUEUED` DB o'tishining EGASI
   shu worker. Egasi bo'lmasa worker promote qilingan job'ni olib
   `mark_running` da `InvalidStateTransitionError('retrying' -> 'running')`
   olardi — `JOB_STATUS_TRANSITIONS[RETRYING] = {QUEUED, DEAD_LETTER,
   CANCELLED}` (shartnoma "QO'SHIMCHA 4 §A").
2. **`reap_expired_leases()`.** Qulagan worker'ning job'larini tiklaydi:
   urinishni `LOST` deb yopadi va retry/DLQ qarorini chiqaradi.
3. **Yo'qolgan job'larni tiklash.** DB'da `PENDING`/`QUEUED`, lekin Redis
   navbatida YO'Q job'lar. Bu holat Redis qulab tiklanganda (`FLUSHDB`,
   `maxmemory` evicton, replikadan tiklash) yuzaga keladi: DB'da job bor,
   navbatda yo'q — hech kim uni olmaydi. Shu qadam ularni qaytaradi.
4. **Cron job'lar va reestr tozalash.** `cron_expression` bo'lgan tugagan
   job uchun keyingi nusxani yaratadi, heartbeat'i kelmay qolgan
   worker'larni reestrdan o'chiradi.

**Yagonalik.** `exclusive = True`: `RedisKeys.lock("scheduler")` bilan butun
klasterda bitta nusxa ishlaydi. `promote_due()` o'zi atomar, lekin cron
nusxalari va "yo'qolgan job" tiklanishi atomar emas — ikki nusxa ishlasa
dublikat yaratilib qolardi.

**Poyga xavfsizligi.** Yangi job avval DB'ga commit qilinadi, keyin
Redis'ga qo'yiladi. Shu oynada job "yo'qolgan" ko'rinadi, shuning uchun
3-qadam FAQAT `LOST_JOB_GRACE_SECONDS` dan eski job'larga tegadi — aks
holda har sikl navbatga dublikat qo'shilardi.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from time import monotonic
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import JobStatus, Priority, RedisKeys
from app.database import session_scope
from app.exceptions import DurablError, QueueError, ValidationError
from app.execution.executor import Executor
from app.logging_config import get_logger
from app.metrics import set_dlq_depth
from app.models.job import Job
from app.repositories.dlq_repo import DlqRepository
from app.repositories.job_repo import JobRepository
from app.services.job_service import JobService
from app.services.queue_service import MEMBER_SEPARATOR, SCAN_COUNT, QueueService
from app.services.reliability_service import ReliabilityService
from app.utils.security import generate_correlation_id
from app.utils.time_utils import ensure_utc, utcnow
from app.utils.validators import next_cron_time
from app.workers.runner import PeriodicWorker, main_entry

logger = get_logger(__name__)

#: Job navbatda yo'qligi "yo'qolish" deb hisoblanishidan oldingi kutish (soniya).
#: DB commit va Redis `RPUSH` orasidagi oynadan ancha katta bo'lishi kerak.
LOST_JOB_GRACE_SECONDS: Final[float] = 30.0

#: `RUNNING` holatda qotib qolgan job shu vaqtdan keyin "qotgan" deb hisoblanadi.
#: Lease TTL + heartbeat oynasidan katta bo'lishi shart.
STUCK_RUNNING_FACTOR: Final[int] = 4

#: Bir siklda qaytarilishi mumkin bo'lgan cron nusxalari soni.
CRON_BATCH_SIZE: Final[int] = 50

#: Job qayta navbatga qo'yilishi mumkin bo'lgan DB holatlari.
RECOVERABLE_STATUSES: Final[tuple[JobStatus, ...]] = (
    JobStatus.PENDING,
    JobStatus.QUEUED,
)

#: `promote_due()` dan keyin `QUEUED` ga o'tkaziladigan holatlar.
PROMOTABLE_STATUSES: Final[tuple[JobStatus, ...]] = (
    JobStatus.RETRYING,
    JobStatus.PENDING,
)


class SchedulerWorker(PeriodicWorker):
    """Kechiktirilgan job'lar, lease reaper, cron va tiklash worker'i."""

    name = "scheduler"
    exclusive = True

    def __init__(self) -> None:
        super().__init__()
        self.interval_seconds = float(settings.SCHEDULER_INTERVAL_SECONDS)
        self.lock_ttl = max(
            int(settings.LEASE_TTL_SECONDS),
            int(self.interval_seconds * 4) + 1,
        )
        self.batch_size = max(1, int(settings.SCHEDULER_BATCH_SIZE))
        self._promoted_total = 0
        self._recovered_total = 0
        self._cron_total = 0
        self._cleanup_every = float(settings.SANDBOX_CLEANUP_INTERVAL_SECONDS)
        #: Oxirgi tozalash vaqti (monotonik). `None` — hali bir marta ham
        #: bajarilmagan, ya'ni birinchi siklda darhol ishlaydi: scheduler
        #: ko'tarilishi odatda qulashdan KEYIN bo'ladi va aynan o'shanda
        #: qoldiq bo'lishi eng ehtimolli.
        self._last_cleanup: float | None = None
        self._orphans_total = 0

    # ------------------------------------------------------------------
    # Sikl
    # ------------------------------------------------------------------

    async def tick(self) -> None:
        """Bitta sikl: promote -> reaper -> tiklash -> cron -> metrikalar -> tozalash.

        Har qadam MUSTAQIL: biri xato bersa qolganlari baribir bajariladi.
        `promote_due()` ishlamay qolgani uchun lease reaper to'xtab qolsa,
        qulagan worker'ning job'lari muallaq qolardi.
        """
        queue = QueueService()

        async with session_scope() as session:
            await self._run_step("promote_due", self._promote(session, queue))

        async with session_scope() as session:
            await self._run_step("reap_leases", self._reap(session))

        async with session_scope() as session:
            await self._run_step("recover_lost", self._recover_lost(session, queue))

        async with session_scope() as session:
            await self._run_step("cron", self._schedule_cron(session, queue))

        async with session_scope() as session:
            await self._run_step("prune_workers", self._prune_workers(session))
            await self._run_step("metrics", self._refresh_metrics(session, queue))

        # DB sessiyasi kerak emas — Docker bilan ishlaydi.
        if self._cleanup_due():
            await self._run_step("sandbox_cleanup", self._cleanup_sandboxes())

    def _cleanup_due(self) -> bool:
        """Sandbox tozalash vaqti keldimi.

        Scheduler har soniyada ishlaydi, Docker'dan konteyner ro'yxatini esa
        har soniyada so'rash isrof bo'lardi — qoldiq faqat jarayon
        qulaganda paydo bo'ladi.
        """
        now = monotonic()
        if self._last_cleanup is None or now - self._last_cleanup >= self._cleanup_every:
            self._last_cleanup = now
            return True
        return False

    async def _cleanup_sandboxes(self) -> None:
        """Egasiz sandbox konteynerlarini o'chiradi.

        ═══════════════════════════════════════════════════════════════════
        NEGA BU SCHEDULER'DA
        ═══════════════════════════════════════════════════════════════════

        Oddiy ishda qoldiq qolmaydi: `SandboxManager.run()` konteynerni
        `finally` da o'chiradi. Lekin jarayon O'RTADA o'lsa (SIGKILL, OOM,
        deploy) `finally` umuman ishlamaydi va konteyner qoladi.

        Scheduler bu ish uchun to'g'ri joy, chunki u:

        * davriy ishlaydi — qo'lda aralashuv kerak emas;
        * butun klasterda YAGONA (`exclusive = True`), ya'ni N ta worker
          bir-birining konteynerini o'chirishga urinmaydi;
        * `docker.sock` ga ulangan (`x-worker-common` compose anchor'i).

        Lokal rejimda (`SANDBOX_ENABLED=false`) `LocalRunner.cleanup_orphans()`
        har doim `0` qaytaradi, shuning uchun qadam zararsiz.
        """
        removed = await Executor().cleanup_orphans()
        if removed:
            self._orphans_total += removed
            logger.info(
                "scheduler.sandbox_cleanup",
                removed=removed,
                total=self._orphans_total,
            )

    async def _run_step(self, step: str, coro: Any) -> None:
        """Bitta qadamni xato to'sig'i ichida bajaradi.

        `DurablError` kutilgan nosozlik (DB/Redis javob bermadi, validatsiya)
        — log qilinadi va keyingi qadam davom etadi. Kutilmagan xato ham
        shu yerda ushlanadi, chunki `PeriodicWorker` butun `tick()` ni
        to'xtatadi va boshqa qadamlar bajarilmay qolardi.
        """
        try:
            await coro
        except DurablError as exc:
            logger.error(
                "scheduler.step_failed",
                step=step,
                error=str(exc),
                error_type=type(exc).__name__,
            )
        except Exception as exc:
            logger.exception(
                "scheduler.step_crashed",
                step=step,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    # ------------------------------------------------------------------
    # 1. Kechiktirilgan job'larni navbatga ko'chirish
    # ------------------------------------------------------------------

    async def _promote(self, session: AsyncSession, queue: QueueService) -> None:
        """Vaqti kelgan job'larni navbatga ko'chiradi va DB'da `QUEUED` qiladi.

        Tartib MUHIM: avval Redis (`promote_due()` atomar, job ikki marta
        navbatga tushmaydi), keyin DB. Teskari qilsak, DB'da `QUEUED`
        bo'lgan, lekin navbatda yo'q job paydo bo'lardi.

        `promote_due()` qaytargan job holatda bo'lmasa (masalan mijoz
        orada bekor qilgan) — tegilmaydi: `promote_due()` allaqachon
        a'zoni navbatga qo'ygan, worker esa uni olib `is_terminal`
        tekshiruvida `ack` qilib o'tadi.
        """
        job_ids = await queue.promote_due(limit=self.batch_size)
        if not job_ids:
            return

        job_service = JobService(session, queue.redis)
        promoted = 0
        skipped: list[str] = []

        for raw_id in job_ids:
            job = await self._load(session, raw_id)
            if job is None:
                skipped.append(raw_id)
                continue

            status = JobStatus(job.status)
            if status not in PROMOTABLE_STATUSES:
                skipped.append(raw_id)
                logger.debug(
                    "scheduler.promote_skipped",
                    job_id=raw_id,
                    status=status.value,
                )
                continue

            await job_service.transition(job, JobStatus.QUEUED)
            promoted += 1

        self._promoted_total += promoted
        logger.info(
            "scheduler.promoted",
            promoted=promoted,
            skipped=len(skipped),
            total=self._promoted_total,
        )

    # ------------------------------------------------------------------
    # 2. Muddati tugagan lease'lar
    # ------------------------------------------------------------------

    async def _reap(self, session: AsyncSession) -> None:
        """Qulagan worker'larning job'larini tiklaydi."""
        reliability = ReliabilityService(session)
        recovered = await reliability.reap_expired_leases(limit=self.batch_size)
        if recovered:
            logger.warning("scheduler.leases_reaped", recovered=recovered)

    # ------------------------------------------------------------------
    # 3. Yo'qolgan job'larni tiklash
    # ------------------------------------------------------------------

    async def _recover_lost(self, session: AsyncSession, queue: QueueService) -> None:
        """Navbatda yo'q, lekin DB'da kutayotgan job'larni qaytaradi.

        Uch manba tekshiriladi:

        * `QUEUED` job'lar — navbatda bo'lishi SHART;
        * vaqti kelgan `PENDING` rejali job'lar (`due_scheduled`);
        * `RUNNING` holatda qotib qolganlar (`stuck_running`) — lease ham,
          `executions` yozuvi ham tozalanmay qolgan chekka holat.

        Redis'da haqiqatan nima borligi BIR MARTA o'qiladi (navbatlar +
        kechiktirilganlar + barcha worker'larning `processing` ro'yxatlari),
        shuning uchun ishlayotgan job "yo'qolgan" deb hisoblanmaydi.
        """
        known = await self._queued_members(queue)
        now = utcnow()
        cutoff = now - timedelta(seconds=LOST_JOB_GRACE_SECONDS)

        candidates = await self._lost_candidates(session, now)
        if not candidates:
            return

        job_service = JobService(session, queue.redis)
        requeued = 0

        for job in candidates:
            job_id = str(job.id)
            if job_id in known:
                continue
            if not self._is_old_enough(job, cutoff):
                continue

            status = JobStatus(job.status)
            if status not in RECOVERABLE_STATUSES and status is not JobStatus.RUNNING:
                # Holat ikki so'rov orasida o'zgargan (worker ulgurdi).
                continue

            try:
                if status is JobStatus.QUEUED:
                    # Holat allaqachon to'g'ri — faqat navbatga qaytaramiz.
                    await queue.enqueue(job.id, Priority(job.priority))
                else:
                    # `PENDING -> QUEUED` va `RUNNING -> QUEUED` ikkisi ham
                    # holat grafigida ruxsat etilgan, shuning uchun tekshiruv
                    # o'chirilmaydi.
                    await job_service.transition(job, JobStatus.QUEUED)
                    await queue.enqueue(job.id, Priority(job.priority))
            except QueueError as exc:
                logger.error("scheduler.requeue_failed", job_id=job_id, error=str(exc))
                continue

            requeued += 1
            logger.warning(
                "scheduler.lost_job_requeued",
                job_id=job_id,
                previous_status=status.value,
                priority=Priority(job.priority).value,
                correlation_id=job.correlation_id,
            )

        self._recovered_total += requeued
        if requeued:
            logger.warning(
                "scheduler.lost_jobs_recovered",
                requeued=requeued,
                total=self._recovered_total,
            )

    async def _lost_candidates(self, session: AsyncSession, now: datetime) -> list[Job]:
        """Tiklanishi mumkin bo'lgan job'lar ro'yxati (dublikatsiz)."""
        jobs = JobRepository(session)

        queued = await jobs.list(
            status=JobStatus.QUEUED,
            limit=self.batch_size,
            order_by=Job.created_at.asc(),
        )
        due = await jobs.due_scheduled(now, limit=self.batch_size)
        stuck_after = now - timedelta(seconds=settings.LEASE_TTL_SECONDS * STUCK_RUNNING_FACTOR)
        stuck = await jobs.stuck_running(stuck_after, limit=self.batch_size)

        merged: dict[uuid.UUID, Job] = {}
        for job in (*queued, *due, *stuck):
            merged.setdefault(job.id, job)
        return list(merged.values())

    @staticmethod
    def _is_old_enough(job: Job, cutoff: datetime) -> bool:
        """Job navbatga qo'yilish oynasidan o'tganmi (poygadan himoya).

        `RUNNING` job uchun `stuck_running()` o'zi vaqt filtrini qo'llagan,
        shuning uchun qo'shimcha tekshiruv kerak emas.
        """
        if JobStatus(job.status) is JobStatus.RUNNING:
            return True
        # `ensure_utc()` MAJBURIY: SQLite ustun qiymatini timezone'siz
        # (naive) `datetime` ko'rinishida qaytaradi va uni aware qiymat bilan
        # solishtirish `TypeError` beradi.
        moment = ensure_utc(job.queued_at or job.scheduled_at or job.created_at)
        if moment is None:  # pragma: no cover - `created_at` har doim bor
            return True
        return moment <= cutoff

    async def _queued_members(self, queue: QueueService) -> set[str]:
        """Redis'da HOZIR turgan barcha `job_id` lar.

        Navbatlar va kechiktirilganlar bilan birga worker'larning
        `processing` ro'yxatlari ham o'qiladi: bajarilayotgan job navbatda
        ko'rinmaydi, lekin u yo'qolgan EMAS.
        """
        redis = queue.redis
        members: set[str] = set()

        try:
            processing_keys = [
                str(key)
                async for key in redis.scan_iter(match=RedisKeys.processing("*"), count=SCAN_COUNT)
            ]
            async with redis.pipeline(transaction=False) as pipe:
                for priority in Priority:
                    pipe.lrange(RedisKeys.queue(priority), 0, -1)
                pipe.zrange(RedisKeys.DELAYED, 0, -1)
                for key in processing_keys:
                    pipe.lrange(key, 0, -1)
                results = await pipe.execute()
        except Exception as exc:
            # Redis javob bermasa tiklashni O'TKAZIB YUBORAMIZ: bo'sh
            # to'plam bilan davom etsak, navbatdagi BARCHA job "yo'qolgan"
            # deb hisoblanib dublikat qo'shilardi.
            raise QueueError(f"Navbat mazmunini o'qib bo'lmadi: {exc}") from exc

        for group in results:
            for raw in group or ():
                members.add(self._member_job_id(str(raw)))
        return members

    @staticmethod
    def _member_job_id(member: str) -> str:
        """A'zodan `job_id` ni ajratadi (`"<priority>:<job_id>"` formati)."""
        _prefix, separator, job_id = member.partition(MEMBER_SEPARATOR)
        return job_id if separator else member

    # ------------------------------------------------------------------
    # 4. Cron job'lar
    # ------------------------------------------------------------------

    async def _schedule_cron(self, session: AsyncSession, queue: QueueService) -> None:
        """Takrorlanuvchi job'ning keyingi nusxasini yaratadi.

        Nusxa FAQAT shu foydalanuvchining ayni cron ifodasi uchun
        harakatdagi job'i YO'Q bo'lsa yaratiladi. Bu tekshiruv "bir marta"
        kafolatini maxsus marker kaliti holda beradi: nusxa yaratilgandan
        keyin u `PENDING` holatda turadi, ya'ni keyingi siklda shart
        bajarilmaydi.

        Yangi yozuvda `idempotency_key` ATAYLAB `None`: `uq_jobs_user_idempotency`
        cheklovi tufayli kalit ko'chirilsa ikkinchi nusxa yaratilmasdi.
        """
        jobs = JobRepository(session)
        sources = await jobs.list(
            status=JobStatus.SUCCESS,
            limit=CRON_BATCH_SIZE,
            order_by=Job.finished_at.desc(),
        )
        recurring = [job for job in sources if job.cron_expression]
        if not recurring:
            return

        created = 0
        for source in recurring:
            if await self._has_pending_cron(jobs, source):
                continue
            if await self._spawn_cron(session, queue, source):
                created += 1

        self._cron_total += created
        if created:
            logger.info("scheduler.cron_scheduled", created=created, total=self._cron_total)

    @staticmethod
    async def _has_pending_cron(jobs: JobRepository, source: Job) -> bool:
        """Shu cron uchun harakatdagi nusxa bormi."""
        active = [status for status in JobStatus if status.is_active]
        pending = await jobs.count(
            user_id=source.user_id,
            cron_expression=source.cron_expression,
            status=active,
        )
        return pending > 0

    async def _spawn_cron(
        self,
        session: AsyncSession,
        queue: QueueService,
        source: Job,
    ) -> bool:
        """Cron job'ning keyingi nusxasini yaratadi va kechiktirib navbatga qo'yadi."""
        expression = source.cron_expression or ""
        try:
            due_at = next_cron_time(expression)
        except ValidationError as exc:
            logger.error(
                "scheduler.cron_invalid",
                job_id=str(source.id),
                expression=expression,
                error=str(exc),
            )
            return False

        jobs = JobRepository(session)
        clone = await jobs.create(
            user_id=source.user_id,
            idempotency_key=None,
            code=source.code,
            runtime=source.runtime,
            priority=source.priority,
            status=JobStatus.PENDING,
            payload=source.payload,
            env_vars=source.env_vars,
            timeout_seconds=source.timeout_seconds,
            max_retries=source.max_retries,
            retry_count=0,
            memory_mb=source.memory_mb,
            cpus=source.cpus,
            scheduled_at=due_at,
            cron_expression=expression,
            correlation_id=generate_correlation_id(),
            tags=source.tags,
        )
        await session.flush()
        await session.commit()

        await queue.enqueue_at(clone.id, due_at, Priority(clone.priority))
        logger.info(
            "scheduler.cron_spawned",
            job_id=str(clone.id),
            source_job_id=str(source.id),
            expression=expression,
            scheduled_at=due_at.isoformat(),
        )
        return True

    # ------------------------------------------------------------------
    # 5. Reestr va metrikalar
    # ------------------------------------------------------------------

    async def _prune_workers(self, session: AsyncSession) -> None:
        """Heartbeat'i kelmay qolgan worker'larni reestrdan o'chiradi."""
        pruned = await ReliabilityService(session).prune_dead_workers()
        if pruned:
            logger.warning("scheduler.dead_workers_pruned", pruned=pruned)

    async def _refresh_metrics(self, session: AsyncSession, queue: QueueService) -> None:
        """`queue_depth`, `dlq_depth` va `active_workers` metrikalarini yangilaydi.

        `QueueService.depth()` va `ReliabilityService.list_workers()`
        metrikani O'ZLARI aniq qiymatga keltiradi, shuning uchun bu yerda
        faqat chaqiriladi; `dlq_depth` esa ochiq o'rnatiladi.
        """
        depths = await queue.depth()
        dlq_depth = await DlqRepository(session).depth()
        set_dlq_depth(dlq_depth)
        workers = await ReliabilityService(session).list_workers()
        alive = sum(1 for row in workers if row.get("is_alive"))

        logger.debug(
            "scheduler.metrics",
            queue_total=depths.get("total", 0),
            queue_delayed=depths.get("delayed", 0),
            queue_processing=depths.get("processing", 0),
            dlq_depth=dlq_depth,
            active_workers=alive,
        )

    # ------------------------------------------------------------------
    # Yordamchilar
    # ------------------------------------------------------------------

    @staticmethod
    async def _load(session: AsyncSession, job_id: str) -> Job | None:
        """Job'ni o'qiydi (`None` — yetim a'zo)."""
        job = await JobRepository(session).get(job_id)
        if job is None:
            logger.warning("scheduler.job_not_found", job_id=job_id)
        return job


async def main() -> None:
    """Scheduler'ni ishga tushiradi (`python -m app.workers.scheduler`)."""
    await SchedulerWorker().run()


if __name__ == "__main__":  # pragma: no cover - protsess kirish nuqtasi
    main_entry(SchedulerWorker)


__all__ = [
    "CRON_BATCH_SIZE",
    "LOST_JOB_GRACE_SECONDS",
    "PROMOTABLE_STATUSES",
    "RECOVERABLE_STATUSES",
    "STUCK_RUNNING_FACTOR",
    "SchedulerWorker",
    "main",
]
