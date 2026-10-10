"""Durabl — job (ish) hayot siklining markaziy servisi.

Bu fayl platformaning yuragi: mijoz kodini qabul qilish, uni BARDOSHLI
(durable) saqlash, navbatga qo'yish, holatini kuzatish va natijani qaytarish.

## Durability kafolati — `submit()` dagi qadamlar TARTIBI muhim

Job avval PostgreSQL'ga yoziladi va `commit` qilinadi, FAQAT keyin Redis
navbatiga qo'yiladi:

* **Agar teskari qilsak** (avval Redis, keyin DB) va DB qulasa — navbatda
  `job_id` bor, lekin ma'lumot yo'q: worker "topilmadi" deb tashlab ketadi,
  mijoz esa 201 javobini olgan. Job JIMGINA yo'qoladi.
* **To'g'ri tartibda** eng yomon holat: DB'da job bor, navbatda yo'q. Bu
  xavfsiz — `scheduler` ning `reap`/`promote_due` jarayoni uni topib qayta
  navbatga qo'yadi. Shuning uchun navbatga qo'yish xatosi mijozga xato
  sifatida qaytarilmaydi: job yo'qolmagan, shunchaki kechikadi.

## Holat o'tishi

Holat FAQAT `app.services.job_state` orqali o'zgaradi (`JOB_STATUS_TRANSITIONS`
grafigi bo'yicha). Shu modul `reliability_service` bilan umumiy — ikki service
bir-birini import qilmaydi (aylanma bog'liqlik bo'lmasligi uchun).

## Bir vaqtdalik (concurrency) hisoblagichi

`RedisKeys.concurrency(user_id)` — reja `max_concurrent_jobs` limitini
tekshirish uchun. `submit` da OSHMAYDI (job hali bajarilmayapti): hisoblagich
`RUNNING` holatiga kirganda `INCR`, `RUNNING` dan chiqqanda `DECR` qilinadi.
Shu simmetriya tufayli hisoblagich "oqmaydi"; nolga nisbatan himoya ham bor.

Qatlam qoidasi: `fastapi` import QILINMAYDI, `HTTPException` tashlanmaydi —
ayni shu kod worker protsesslarida ham ishlaydi.
"""

from __future__ import annotations

import builtins  # `list` klass ichida metod nomi — builtin'ga ochiq murojaat uchun
import uuid
from datetime import datetime
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import (
    FailureReason,
    JobStatus,
    PlanType,
    Priority,
    RedisKeys,
    WebhookEvent,
    plan_limits,
)
from app.exceptions import (
    ConcurrencyLimitError,
    DatabaseError,
    IdempotencyConflictError,
    InfrastructureError,
    JobNotCancellableError,
    JobNotFoundError,
    ResultNotReadyError,
)
from app.execution.types import ResourceLimits
from app.logging_config import get_logger
from app.metrics import (
    observe_queue_wait,
    track_job_completed,
    track_job_submitted,
)
from app.models.execution_log import ExecutionLog
from app.models.job import Job
from app.models.user import User
from app.redis_client import get_redis
from app.repositories.dlq_repo import DlqRepository
from app.repositories.execution_log_repo import ExecutionLogRepository
from app.repositories.execution_repo import ExecutionRepository
from app.repositories.job_repo import JobRepository
from app.repositories.subscription_repo import SubscriptionRepository
from app.schemas.base import PaginationParams
from app.schemas.job import JobCreate, JobFilter
from app.services import job_state
from app.services.billing_service import BillingService
from app.services.idempotency_service import IdempotencyService
from app.services.queue_service import QueueService
from app.services.webhook_service import WebhookService
from app.utils.security import generate_correlation_id
from app.utils.serializers import job_event_payload
from app.utils.time_utils import duration_ms as elapsed_ms
from app.utils.time_utils import ensure_utc, isoformat, utcnow
from app.utils.validators import (
    assert_code_safe,
    next_cron_time,
    validate_code_size,
    validate_cron,
    validate_env_vars,
    validate_payload_size,
    validate_retries,
    validate_runtime,
    validate_tags,
)

logger = get_logger(__name__)

#: Bekor qilish signalining TTL'i uchun qo'shimcha zaxira (soniya).
#: Signal `job.timeout_seconds + shu qiymat` davomida yashaydi: worker
#: heartbeat paytida uni o'qiydi, job tugagandan keyin esa signal o'zi
#: yo'qoladi (keyingi urinishga tasodifan ta'sir qilmasligi uchun).
CANCEL_SIGNAL_GRACE_SECONDS: int = 30

#: `RedisKeys.cache()` uchun bekor qilish signalining nom maydoni.
CANCEL_NAMESPACE: str = "cancel"

#: Concurrency hisoblagichining "o'z-o'zini tiklash" muddati (soniya).
#: Hisoblagich har `INCR` da yangilanadi; agar jarayon qulab hisoblagich
#: baland qolib ketsa, bir kundan keyin kalit o'chadi va foydalanuvchi
#: abadiy bloklanib qolmaydi.
CONCURRENCY_KEY_TTL_SECONDS: int = 86_400

#: `logs()` uchun standart limit (`ExecutionLogRepository` bilan bir xil).
DEFAULT_LOG_LIMIT: int = 500


class JobService:
    """Job yuborish, kuzatish, bekor qilish va holat o'tishi."""

    def __init__(self, session: AsyncSession, redis: Redis | None = None) -> None:
        self.session = session
        self.redis = redis or get_redis()
        self.jobs = JobRepository(session)
        self.executions = ExecutionRepository(session)
        self.execution_logs = ExecutionLogRepository(session)
        self.dlq = DlqRepository(session)
        self.subscriptions = SubscriptionRepository(session)
        self.queue = QueueService(self.redis)
        self.idempotency = IdempotencyService(self.redis)
        self.billing = BillingService(session)
        self.webhooks = WebhookService(session, self.redis)

    # ------------------------------------------------------------------
    # Job yuborish (durability yadrosi)
    # ------------------------------------------------------------------

    async def submit(
        self,
        user: User,
        data: JobCreate,
        *,
        idempotency_key: str | None = None,
    ) -> tuple[Job, bool]:
        """Yangi job qabul qiladi.

        Qadamlar (TARTIB O'ZGARTIRILMAYDI — modul docstring'iga qara):

        1. Kvota (`BillingService.check_quota`);
        2. Bir vaqtdalik limiti (Redis hisoblagichi);
        3. Kod/muhit/teg/cron validatsiyasi;
        4. Resurs limitlarini rejaga moslash (so'rov rejadan ko'p bo'lsa
           QISQARTIRILADI — xato emas);
        5. Idempotency: ayni kalit bilan ikkinchi so'rov MAVJUD job'ni
           qaytaradi, yangisini yaratmaydi;
        6. DB'ga `PENDING` holatda yozish;
        7. `commit` — job endi BARDOSHLI;
        8. Idempotency yozuvini yakunlash;
        9. Navbatga qo'yish (yoki kechiktirilgan ZSET'ga);
        10. Hodisa chop etish + webhook;
        11. Metrikalar va log.

        Args:
            user: Job egasi.
            data: Tekshirilgan so'rov.
            idempotency_key: `Idempotency-Key` header qiymati — tanadagi
                `data.idempotency_key` dan USTUN turadi.

        Returns:
            `(job, created)` — `created=False` bo'lsa mavjud job qaytarilgan.

        Raises:
            QuotaExceededError: Oylik reja kvotasi tugadi.
            ConcurrencyLimitError: Bir vaqtda bajarilayotgan job'lar limiti.
            CodeValidationError / CodeSyntaxError: Kod tekshiruvdan o'tmadi.
            ValidationError: Teg, muhit o'zgaruvchisi yoki cron noto'g'ri.
            PayloadTooLargeError: Kod yoki payload juda katta.
            IdempotencyConflictError: Ayni kalit boshqa so'rov tanasi bilan.
        """
        key = self._clean_idempotency_key(idempotency_key or data.idempotency_key)

        # --- 1. Kvota -------------------------------------------------
        await self.billing.check_quota(user)

        # --- 2. Bir vaqtdalik ----------------------------------------
        subscription = await self.subscriptions.ensure_for_user(user.id)
        plan = subscription.limits
        await self._assert_concurrency(user, plan.max_concurrent_jobs)

        # --- 3. Validatsiya ------------------------------------------
        runtime = validate_runtime(data.runtime)
        validate_code_size(data.code)
        assert_code_safe(data.code, runtime)
        validate_payload_size(data.payload)
        env_vars = validate_env_vars(data.env_vars) or None
        tags = validate_tags(data.tags) or None
        if data.cron_expression:
            validate_cron(data.cron_expression)

        # --- 4. Limitlarni rejaga moslash ----------------------------
        limits = ResourceLimits.resolve(
            requested_memory_mb=data.memory_mb,
            requested_cpus=data.cpus,
            requested_timeout=data.timeout_seconds,
            plan=plan,
        )
        max_retries = validate_retries(data.max_retries)

        # --- 5. Idempotency ------------------------------------------
        fingerprint: str | None = None
        if key is not None:
            fingerprint = IdempotencyService.fingerprint(
                self._fingerprint_source(
                    code=data.code,
                    runtime=runtime,
                    priority=Priority(data.priority),
                    payload=data.payload,
                    env_vars=env_vars,
                    timeout_seconds=limits.timeout_seconds,
                    max_retries=max_retries,
                    memory_mb=limits.memory_mb,
                    cpus=limits.cpus,
                    scheduled_at=data.scheduled_at,
                    cron_expression=data.cron_expression,
                    tags=tags,
                )
            )
            existing = await self._lookup_idempotent(user, key, fingerprint)
            if existing is not None:
                logger.info(
                    "idempotent so'rov — mavjud job qaytarildi",
                    job_id=str(existing.id),
                    user_id=str(user.id),
                    idempotency_key=key,
                )
                return existing, False

        # --- 6-7. DB'ga yozish va commit -----------------------------
        try:
            job = await self.jobs.create(
                user_id=user.id,
                idempotency_key=key,
                code=data.code,
                runtime=runtime,
                priority=Priority(data.priority),
                status=JobStatus.PENDING,
                payload=data.payload,
                env_vars=env_vars,
                timeout_seconds=limits.timeout_seconds,
                max_retries=max_retries,
                retry_count=0,
                memory_mb=limits.memory_mb,
                cpus=limits.cpus,
                scheduled_at=data.scheduled_at,
                cron_expression=data.cron_expression,
                correlation_id=generate_correlation_id(),
                tags=tags,
            )
            await self.session.commit()
        except DatabaseError as exc:
            # `uq_jobs_user_idempotency` buzilgan bo'lishi mumkin: ayni kalit
            # bilan parallel so'rov ulgurgan (Redis yordam bermagan holat).
            # G'olibning job'ini qaytaramiz — mijoz uchun bu baribir idempotent.
            if key is not None:
                winner = await self.jobs.find_by_idempotency(user.id, key)
                if winner is not None:
                    if fingerprint is not None and self._job_fingerprint(winner) != fingerprint:
                        raise IdempotencyConflictError(key) from exc
                    return winner, False
                await self._release_idempotency(user.id, key)
            raise
        except Exception:
            if key is not None:
                await self._release_idempotency(user.id, key)
            raise

        # --- 8. Idempotency yozuvini yakunlash -----------------------
        if key is not None:
            await self._commit_idempotency(user.id, key, job.id)

        # Foydalanish hisobi — `check_quota` (1-qadam) shu hisoblagichga
        # qaraydi, shuning uchun qabul qilingan job ALBATTA qayd etiladi.
        # API qatlami `record_job` ni QAYTA chaqirmasligi kerak.
        await self._record_usage(user)

        # --- 9. Navbatga qo'yish -------------------------------------
        published = await self._enqueue_new(job)

        # --- 10. Hodisa + webhook ------------------------------------
        if not published:
            # `transition()` hodisani o'zi chop etgan bo'lsa takrorlamaymiz.
            await self._publish(job)
        await self._dispatch(job, WebhookEvent.JOB_QUEUED)

        # --- 11. Metrikalar va log -----------------------------------
        track_job_submitted()
        logger.info(
            "job qabul qilindi",
            job_id=str(job.id),
            user_id=str(user.id),
            status=job.status,
            runtime=job.runtime,
            priority=job.priority,
            timeout_seconds=job.timeout_seconds,
            scheduled=job.is_scheduled,
            recurring=job.is_recurring,
            correlation_id=job.correlation_id,
            idempotent=key is not None,
        )
        return job, True

    # ------------------------------------------------------------------
    # O'qish
    # ------------------------------------------------------------------

    async def get(self, user: User, job_id: uuid.UUID | str) -> Job:
        """Foydalanuvchining job'i.

        Boshqa foydalanuvchining job'i ham "topilmadi" deb qaytariladi —
        resurs mavjudligini oshkor qilmaymiz (IDOR himoyasi).

        Raises:
            JobNotFoundError: Job yo'q yoki boshqa egaga tegishli.
        """
        job = await self.jobs.get_for_user(job_id, user.id)
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    async def get_internal(self, job_id: uuid.UUID | str) -> Job:
        """Job'ni egalikni tekshirmasdan oladi — FAQAT worker uchun.

        Worker navbatdan `job_id` oladi va uning egasini bilmaydi, shuning
        uchun bu metodda `user` tekshiruvi yo'q. HTTP qatlamidan HECH QACHON
        chaqirilmaydi.

        Raises:
            JobNotFoundError: Bunday job yo'q.
        """
        job = await self.jobs.get(job_id)
        if job is None:
            raise JobNotFoundError(job_id)
        return job

    async def list(
        self,
        user: User,
        filters: JobFilter,
        pagination: PaginationParams,
    ) -> tuple[list[Job], int]:
        """Filtrlangan va sahifalangan job ro'yxati: `(yozuvlar, umumiy_son)`.

        `failure_reason` va `tag` filtrlari `JobRepository.search()` da yo'q,
        shuning uchun ular sahifa ustida Python tomonida qo'llanadi (qarang:
        `notes` — repository'ga qo'shilishi kerak bo'lgan imkoniyat).
        """
        items, total = await self.jobs.search(
            user_id=user.id,
            status=filters.status,
            runtime=filters.runtime,
            priority=filters.priority,
            start=filters.start,
            end=filters.end,
            search=filters.search,
            page=pagination.page,
            page_size=pagination.page_size,
            sort_by=filters.sort_by,
            sort_order=filters.sort_order,
        )
        if filters.failure_reason is not None or filters.tag is not None:
            items = [job for job in items if self._matches_refinements(job, filters)]
        return items, total

    async def result(self, user: User, job_id: uuid.UUID | str) -> Job:
        """Yakuniy natija.

        Raises:
            JobNotFoundError: Job topilmadi.
            ResultNotReadyError: Job hali yakuniy holatda emas.
        """
        job = await self.get(user, job_id)
        if not JobStatus(job.status).is_terminal:
            raise ResultNotReadyError(job.status)
        return job

    async def logs(
        self,
        user: User,
        job_id: uuid.UUID | str,
        *,
        after_sequence: int | None = None,
        limit: int = DEFAULT_LOG_LIMIT,
    ) -> builtins.list[ExecutionLog]:
        """Job loglari.

        `after_sequence` berilmasa — job'ning BARCHA urinishlari loglari
        (vaqt bo'yicha). Berilsa — OXIRGI urinishning shu raqamdan keyingi
        qatorlari (real vaqtda kuzatish kursori; `sequence` har urinish
        ichida 0'dan boshlanadi, shuning uchun kursor bitta urinishga tegishli).
        """
        job = await self.get(user, job_id)

        if after_sequence is None:
            return await self.execution_logs.list_for_job(job.id, limit=limit)

        current = await self.executions.current(job.id)
        if current is None:
            return []
        return await self.execution_logs.list_for_execution(
            current.id,
            after_sequence=after_sequence,
            limit=limit,
        )

    async def timeline(self, user: User, job_id: uuid.UUID | str) -> dict[str, Any]:
        """Job hayot siklining vaqt o'qi (dashboard "timeline" bloki uchun).

        Urinishlar `selectinload(Job.executions)` bilan OCHIQ yuklanadi —
        modellarda bog'lanishlar `lazy="raise"`.

        Returns:
            `created_at`, `queued_at`, `started_at`, `finished_at`,
            `queue_wait_ms`, `execution_ms`, `total_ms`, `attempts` (har bir
            urinish tafsiloti) va `dlq` (DLQ yozuvi yoki `None`).
        """
        job = await self.jobs.get_for_user(job_id, user.id, with_executions=True)
        if job is None:
            raise JobNotFoundError(job_id)

        created_at = ensure_utc(job.created_at)
        queued_at = ensure_utc(job.queued_at)
        started_at = ensure_utc(job.started_at)
        finished_at = ensure_utc(job.finished_at)
        cancelled_at = ensure_utc(job.cancelled_at)
        ended_at = finished_at or cancelled_at

        attempts = [
            {
                "attempt_number": execution.attempt_number,
                "worker_id": execution.worker_id,
                "status": execution.status,
                "started_at": ensure_utc(execution.started_at),
                "finished_at": ensure_utc(execution.finished_at),
                "duration_ms": self._span_ms(
                    execution.started_at,
                    execution.finished_at,
                    fallback=execution.duration_ms,
                ),
                "exit_code": execution.exit_code,
                "failure_reason": execution.failure_reason,
            }
            for execution in job.executions
        ]

        dlq_entry = await self.dlq.get_by_job(job.id)

        return {
            "job_id": job.id,
            "status": JobStatus(job.status),
            "created_at": created_at,
            "scheduled_at": ensure_utc(job.scheduled_at),
            "queued_at": queued_at,
            "started_at": started_at,
            "finished_at": finished_at,
            "cancelled_at": cancelled_at,
            # Navbatda kutish: navbatga qo'yilgandan ishga tushgangacha
            "queue_wait_ms": self._span_ms(queued_at, started_at),
            # Sof bajarish vaqti (DB'dagi `duration_ms` zaxira sifatida)
            "execution_ms": self._span_ms(started_at, ended_at, fallback=job.duration_ms),
            # Mijoz nuqtai nazaridan umumiy vaqt: qabuldan yakungacha
            "total_ms": self._span_ms(created_at, ended_at),
            "attempt_count": len(attempts),
            "attempts": attempts,
            "dlq": self._dlq_summary(dlq_entry),
        }

    async def stats(self, user: User) -> dict[str, Any]:
        """Foydalanuvchi dashboard'i uchun umumiy ko'rsatkichlar.

        `JobRepository.stats_overview()` (bitta agregat so'rov) ustiga
        holatlar kesimi, harakatdagi job'lar soni, DLQ chuqurligi va
        Redis'dagi bir vaqtdalik hisoblagichi qo'shiladi.
        """
        overview = await self.jobs.stats_overview(user_id=user.id)
        by_status = await self.jobs.count_by_status(user.id)
        active = await self.jobs.active_count(user.id)
        dlq_depth = await self.dlq.depth(user.id)

        # Faqat O'QIYMIZ: `ensure_for_user` yozuv yaratishi mumkin, statistika
        # esa yon ta'sirsiz bo'lishi kerak. Obuna yo'q bo'lsa FREE deb olinadi.
        subscription = await self.subscriptions.get_for_user(user.id)
        limits = subscription.limits if subscription is not None else plan_limits(PlanType.FREE)

        stats: dict[str, Any] = dict(overview)
        stats.update(
            {
                "by_status": by_status,
                "active": active,
                "dlq_depth": dlq_depth,
                "running": await self._concurrency_value(user.id),
                "plan": limits.plan,
                "max_concurrent_jobs": limits.max_concurrent_jobs,
                "monthly_job_limit": limits.monthly_jobs,
            }
        )
        return stats

    # ------------------------------------------------------------------
    # Bekor qilish va qayta yuborish
    # ------------------------------------------------------------------

    async def cancel(self, user: User, job_id: uuid.UUID | str) -> Job:
        """Job'ni bekor qiladi.

        * `PENDING`/`QUEUED` — navbatdan olib tashlanadi (hali hech kim
          olmagan, shuning uchun darhol `CANCELLED`);
        * `RUNNING` — Redis'ga bekor qilish signali yoziladi. Worker
          heartbeat paytida shu kalitni tekshiradi va sandbox'ni to'xtatadi
          (protsessni tashqaridan "o'ldirish" mumkin emas, shuning uchun
          kooperativ to'xtatish ishlatiladi).

        Raises:
            JobNotFoundError: Job topilmadi.
            JobNotCancellableError: Job yakuniy holatda.
        """
        job = await self.get(user, job_id)

        if not job_state.is_cancellable(job.status):
            raise JobNotCancellableError(job.status)

        previous = JobStatus(job.status)
        if previous is JobStatus.CANCELLED:
            # Idempotent: takroriy bekor qilish yangi hodisa chiqarmaydi va
            # `cancelled_at` ni qayta yozmaydi (tarmoq qayta urinishi normal).
            return job

        if previous in (JobStatus.PENDING, JobStatus.QUEUED):
            await self._remove_from_queue(job)
        elif previous is JobStatus.RUNNING:
            await self._signal_cancel(job)

        job = await self.transition(job, JobStatus.CANCELLED, commit=True)
        await self._dispatch(job, WebhookEvent.JOB_CANCELLED)

        logger.info(
            "job bekor qilindi",
            job_id=str(job.id),
            user_id=str(user.id),
            previous_status=previous,
        )
        return job

    async def resubmit(self, user: User, job_id: uuid.UUID | str) -> Job:
        """Mavjud job'ning kodi bilan YANGI job yaratadi.

        Eski job o'zgarmaydi (tarix saqlanadi). Yangi job'da yangi `id`,
        yangi `correlation_id` va `idempotency_key=None` bo'ladi —
        takrorlanmaslik kaliti ko'chirilsa yangi job yaratilmas edi.
        Rejalashtirish maydonlari (`scheduled_at`, `cron_expression`) ham
        ko'chirilmaydi: qayta yuborish DARHOL bajarilishini bildiradi.
        """
        source = await self.get(user, job_id)

        data = JobCreate(
            code=source.code,
            runtime=source.runtime,
            priority=source.priority,
            payload=source.payload,
            env_vars=source.env_vars,
            timeout_seconds=source.timeout_seconds,
            max_retries=source.max_retries,
            tags=source.tags,
            memory_mb=source.memory_mb,
            cpus=source.cpus,
        )
        job, _ = await self.submit(user, data, idempotency_key=None)
        logger.info(
            "job qayta yuborildi",
            job_id=str(job.id),
            source_job_id=str(source.id),
            user_id=str(user.id),
        )
        return job

    # ------------------------------------------------------------------
    # Holat o'tishi
    # ------------------------------------------------------------------

    async def transition(
        self,
        job: Job,
        target: JobStatus,
        *,
        validate: bool = True,
        commit: bool = False,
        **fields: Any,
    ) -> Job:
        """Job holatini o'zgartiradi: tekshiruv -> `flush` -> hodisa -> commit.

        Holat grafigi `job_state.apply_transition()` da tekshiriladi, vaqt
        ustunlari (`queued_at`, `started_at`, ...) avtomatik to'ldiriladi.

        Args:
            job: O'zgartiriladigan job.
            target: Yangi holat.
            validate: `False` — grafik tekshirilmaydi (admin/tiklash amallari).
            commit: `True` — tranzaksiya shu yerda yopiladi. Standart `False`:
                bu metod ko'pincha boshqa service ichidan chaqiriladi va
                tranzaksiya egasi chaqiruvchi bo'ladi.
            **fields: Qo'shimcha maydonlar (`error`, `failure_reason`, ...).

        Raises:
            InvalidStateTransitionError: O'tish grafikka mos emas.
        """
        previous = JobStatus(job.status)
        job_state.apply_transition(job, target, validate=validate, **fields)
        await self.session.flush()

        if commit:
            # Hodisa DB'ga YOZILGANDAN KEYIN chiqadi: aks holda commit xato
            # bersa mijoz hech qachon bo'lmagan holat haqida xabar olardi.
            await self.session.commit()

        current = JobStatus(job.status)
        await self._sync_concurrency(job, previous, current)
        self._track_transition(job, previous, current)
        await self._publish(job)

        logger.info(
            "job holati o'zgardi",
            job_id=str(job.id),
            previous_status=previous,
            status=current,
            retry_count=job.retry_count,
            correlation_id=job.correlation_id,
        )
        return job

    async def mark_queued(self, job: Job) -> Job:
        """`QUEUED` holatiga o'tkazadi. Ichki metod — commit QILMAYDI."""
        return await self.transition(job, JobStatus.QUEUED)

    async def mark_running(self, job: Job, worker_id: str) -> Job:
        """`RUNNING` holatiga o'tkazadi va bir vaqtdalik hisoblagichini oshiradi.

        `worker_id` `jobs` jadvalida saqlanmaydi (u `executions.worker_id` da
        bo'ladi) — bu yerda faqat logga yoziladi. Ichki metod — commit
        QILMAYDI (worker `session_scope()` ichida ishlaydi).
        """
        job = await self.transition(job, JobStatus.RUNNING)
        logger.info("job worker tomonidan olindi", job_id=str(job.id), worker_id=worker_id)
        return job

    async def mark_success(self, job: Job, **fields: Any) -> Job:
        """`SUCCESS` holatiga o'tkazadi. Ichki metod — commit QILMAYDI."""
        return await self.transition(job, JobStatus.SUCCESS, **fields)

    async def mark_failed(
        self,
        job: Job,
        *,
        error: str,
        failure_reason: FailureReason,
        **fields: Any,
    ) -> Job:
        """`FAILED` holatiga o'tkazadi. Ichki metod — commit QILMAYDI.

        `FAILED` YAKUNIY holat emas: `reliability_service` keyin retry yoki
        DLQ (`DEAD_LETTER`) qarorini qabul qiladi.
        """
        return await self.transition(
            job,
            JobStatus.FAILED,
            error=error,
            failure_reason=failure_reason,
            **fields,
        )

    async def mark_cancelled(self, job: Job) -> Job:
        """`CANCELLED` holatiga o'tkazadi. Ichki metod — commit QILMAYDI."""
        return await self.transition(job, JobStatus.CANCELLED)

    async def requeue(self, job: Job, *, delay_seconds: float = 0) -> Job:
        """Job'ni qayta navbatga qo'yadi.

        `retry_count` OSHIRILMAYDI — qayta urinishlarni hisoblash
        `reliability_service` ning vazifasi. Bu metod faqat "navbatga
        qaytarish" mexanikasini beradi (lease yo'qolgan yoki backoff tugagan
        job uchun).

        Durability: avval holat `QUEUED` bo'lib `commit` qilinadi, keyin
        Redis'ga qo'yiladi. Redis xato bersa job DB'da qoladi va
        `scheduler` uni qayta oladi.
        """
        job = await self.transition(job, JobStatus.QUEUED, commit=True)
        await self._enqueue(job, delay_seconds=delay_seconds)
        return job

    # ------------------------------------------------------------------
    # Navbat bilan ishlash
    # ------------------------------------------------------------------

    async def _enqueue_new(self, job: Job) -> bool:
        """Yangi job'ni navbatga qo'yadi (9-qadam).

        Kechiktirilgan yoki cron job `PENDING` holatida qoladi va ZSET'ga
        tushadi — `scheduler` vaqti kelganda navbatga ko'chiradi. Oddiy job
        darhol `QUEUED` bo'ladi.

        Returns:
            `True` — `transition()` chaqirilgan (hodisa allaqachon chop
            etilgan), `False` — hodisani chaqiruvchi chop etishi kerak.
        """
        when = self._scheduled_moment(job)
        if when is not None:
            try:
                await self.queue.enqueue_at(job.id, when, job.priority)
            except (RedisError, InfrastructureError) as exc:
                await self._queue_failure(job, exc)
            return False

        job = await self.transition(job, JobStatus.QUEUED, commit=True)
        await self._enqueue(job)
        return True

    async def _enqueue(self, job: Job, *, delay_seconds: float = 0) -> None:
        """Job'ni ustuvorlik navbatiga qo'yadi; xato bo'lsa zaxira yo'lga o'tadi."""
        try:
            await self.queue.enqueue(job.id, job.priority, delay_seconds=delay_seconds)
        except (RedisError, InfrastructureError) as exc:
            await self._queue_failure(job, exc)

    async def _queue_failure(self, job: Job, exc: Exception) -> None:
        """Navbatga qo'yish muvaffaqiyatsiz tugadi — job'ni tiklanadigan holga keltiradi.

        Mijozga XATO QAYTARILMAYDI: job DB'da bor, ya'ni yo'qolmagan.
        Job `PENDING` holatiga qaytariladi va `scheduled_at` to'ldiriladi —
        shu tufayli `JobRepository.due_scheduled()` uni topadi va
        `scheduler` navbatga qo'yadi. Holat grafigi `QUEUED -> PENDING`
        o'tishini ruxsat etmaydi, shuning uchun `validate=False` bilan
        majburiy qo'llanadi (bu tiklash amali).

        MUHIM: kechiktirilgan va cron job'larning vaqti SAQLANADI. Agar
        `scheduled_at` ni ko'r-ko'rona `utcnow()` qilib qo'ysak, bir
        soatdan keyin ishlashi kerak bo'lgan job Redis uzilishi tufayli
        DARHOL ishga tushib ketardi.
        """
        now = utcnow()
        when = self._scheduled_moment(job)
        recovery_at = when if when is not None and when > now else now

        logger.error(
            "job navbatga qo'yilmadi — scheduler qayta urinadi",
            job_id=str(job.id),
            status=job.status,
            recover_at=isoformat(recovery_at),
            error=str(exc),
        )
        try:
            job_state.apply_transition(
                job,
                JobStatus.PENDING,
                validate=False,
                scheduled_at=recovery_at,
            )
            await self.session.commit()
        except Exception as inner:  # pragma: no cover - DB ham ishlamayotgan holat
            await self.session.rollback()
            logger.error(
                "job'ni tiklash holatiga o'tkazish ham muvaffaqiyatsiz",
                job_id=str(job.id),
                error=str(inner),
            )

    async def _remove_from_queue(self, job: Job) -> None:
        """Job'ni navbatdan olib tashlaydi (bekor qilishda)."""
        try:
            await self.queue.remove(job.id, job.priority)
        except (RedisError, InfrastructureError) as exc:
            # Navbatdan o'chmasa ham xavfli emas: worker job'ni olganda
            # `CANCELLED` holatini ko'radi va bajarmaydi.
            logger.warning(
                "job navbatdan o'chirilmadi",
                job_id=str(job.id),
                error=str(exc),
            )

    async def _signal_cancel(self, job: Job) -> None:
        """`RUNNING` job uchun Redis'ga bekor qilish signalini yozadi."""
        # Signal job bajarilib bo'lgandan keyin ham qisqa vaqt yashashi kerak:
        # worker uni keyingi heartbeat/lease oynasida o'qiydi.
        ttl = int(job.timeout_seconds) + settings.LEASE_TTL_SECONDS + CANCEL_SIGNAL_GRACE_SECONDS
        try:
            await self.redis.set(
                RedisKeys.cache(CANCEL_NAMESPACE, job.id),
                JobStatus.CANCELLED.value,
                ex=ttl,
            )
        except RedisError as exc:
            logger.warning(
                "bekor qilish signali yozilmadi",
                job_id=str(job.id),
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Idempotency
    # ------------------------------------------------------------------

    async def _lookup_idempotent(self, user: User, key: str, fingerprint: str) -> Job | None:
        """Ayni kalit bilan avval yaratilgan job'ni topadi (5-qadam).

        Uch manba ketma-ket tekshiriladi:

        1. Redis yozuvi (`reserve`) — tez yo'l;
        2. `jobs.idempotency_key` (DB) — Redis TTL tugagan yoki Redis
           qulagan holat uchun BARDOSHLI zaxira;
        3. Hech biri bo'lmasa — kalit band qilinadi va `None` qaytadi.

        Barmoq izi (fingerprint) mavjud job'ning O'Z maydonlaridan qayta
        hisoblanadi va solishtiriladi: bir xil kalit boshqa tana bilan
        kelsa `IdempotencyConflictError`. Shu tufayli himoya Redis'dagi
        yozuvga bog'liq emas.

        `IdempotencyConflictError` va `IdempotencyInProgressError` MIJOZGA
        yetib boradi (409) — ular "qayta urinib ko'r" degan ma'noli javob.
        Faqat Redis UZILISHI (`InfrastructureError`/`RedisError`) yutiladi:
        bunda DB'dagi `uq_jobs_user_idempotency` cheklovi va quyidagi
        barmoq izi tekshiruvi kafolatni saqlab turadi.

        Raises:
            IdempotencyConflictError: Kalit bir xil, so'rov tanasi boshqa.
            IdempotencyInProgressError: Ayni kalit bilan so'rov hozir
                bajarilmoqda (`IdempotencyService` tashlaydi).
        """
        reserved: object | None = None
        reserve_failed = False
        try:
            reserved = await self.idempotency.reserve(user.id, key, fingerprint)
        except (RedisError, InfrastructureError) as exc:
            reserve_failed = True
            logger.warning(
                "idempotency kalitini band qilish muvaffaqiyatsiz",
                user_id=str(user.id),
                idempotency_key=key,
                error=str(exc),
            )

        #: `reserve` `None` qaytardi — kalitni AYNI SHU chaqiruv band qildi.
        #: Keyin job yaratilmasa, shu bandlovni O'ZIMIZ bo'shatishimiz kerak.
        fresh_reservation = reserved is None and not reserve_failed

        existing: Job | None = None
        reserved_uuid = self._as_uuid(self._reserved_job_id(reserved))
        if reserved_uuid is not None:
            existing = await self.jobs.get_for_user(reserved_uuid, user.id)

        from_db = False
        if existing is None:
            existing = await self.jobs.find_by_idempotency(user.id, key)
            from_db = existing is not None

        if existing is None:
            return None

        if self._job_fingerprint(existing) != fingerprint:
            if fresh_reservation:
                # Redis yozuvi yo'q edi (TTL tugagan), biz uni YANGI barmoq izi
                # bilan band qilib qo'ydik. Konflikt tashlashdan oldin
                # bo'shatamiz — aks holda mijoz TO'G'RI tanani qayta yuborganda
                # ham "konflikt" javobini olib, boshi berk ko'chaga kirardi.
                await self._release_idempotency(user.id, key)
            raise IdempotencyConflictError(key)

        if from_db and fresh_reservation:
            # Redis yozuvi yo'qolgan (TTL yoki flush) — tiklab qo'yamiz.
            await self._commit_idempotency(user.id, key, existing.id)

        return existing

    async def _commit_idempotency(
        self,
        user_id: uuid.UUID | str,
        key: str,
        job_id: uuid.UUID,
    ) -> None:
        """Idempotency yozuvini yakunlaydi (8-qadam) — xatosi job'ni buzmaydi."""
        try:
            await self.idempotency.commit(user_id, key, job_id)
        except (RedisError, InfrastructureError) as exc:
            logger.warning(
                "idempotency yozuvi yakunlanmadi",
                job_id=str(job_id),
                idempotency_key=key,
                error=str(exc),
            )

    async def _release_idempotency(self, user_id: uuid.UUID | str, key: str) -> None:
        """Band qilingan kalitni bo'shatadi (job yaratilmay qolganda)."""
        try:
            await self.idempotency.release(user_id, key)
        except (RedisError, InfrastructureError) as exc:
            logger.warning(
                "idempotency kaliti bo'shatilmadi",
                idempotency_key=key,
                error=str(exc),
            )

    @staticmethod
    def _reserved_job_id(reserved: object) -> str | None:
        """`reserve()` natijasidan job identifikatorini ajratadi.

        CONTRACTS.md §6 imzosi `str | None` deydi, `IdempotencyService` esa
        boyroq `IdempotencyRecord` qaytaradi (unda `job_id` maydoni bor).
        Ikki shakl ham qabul qilinadi — shu tufayli `job_service` hamkor
        service'ning ichki ko'rinishiga bog'lanib qolmaydi.
        """
        if reserved is None:
            return None
        job_id = getattr(reserved, "job_id", reserved)
        return str(job_id) if job_id else None

    @staticmethod
    def _as_uuid(value: object) -> uuid.UUID | None:
        """Redis'dan kelgan matnni `UUID`ga aylantiradi; yaroqsiz bo'lsa `None`.

        Redis'dagi yozuv buzilgan bo'lishi mumkin (qo'lda o'zgartirilgan,
        eski format), shuning uchun u DB so'roviga TO'G'RIDAN-TO'G'RI
        uzatilmaydi — aks holda `Uuid` ustuniga yaroqsiz qiymat borib
        tushunarsiz SQL xatosi beradi.
        """
        if isinstance(value, uuid.UUID):
            return value
        if not value:
            return None
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError, AttributeError):
            return None

    @staticmethod
    def _clean_idempotency_key(value: str | None) -> str | None:
        """Kalitni tozalaydi; bo'sh qiymat `None` ga aylanadi."""
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @staticmethod
    def _fingerprint_source(
        *,
        code: str,
        runtime: object,
        priority: object,
        payload: dict[str, Any] | None,
        env_vars: dict[str, str] | None,
        timeout_seconds: int,
        max_retries: int,
        memory_mb: int | None,
        cpus: float | None,
        scheduled_at: datetime | None,
        cron_expression: str | None,
        tags: builtins.list[str] | None,
    ) -> dict[str, Any]:
        """Barmoq izi uchun kanonik lug'at.

        MUHIM: qiymatlar REJAGA MOSLANGANDAN KEYIN (4-qadam) olinadi —
        aynan shular `jobs` jadvaliga yoziladi. Shu tufayli mavjud job'dan
        qayta hisoblangan iz yangi so'rovning izi bilan solishtirilishi
        mumkin bo'ladi.
        """
        return {
            "code": code,
            "runtime": str(runtime),
            "priority": str(priority),
            "payload": payload,
            "env_vars": env_vars,
            "timeout_seconds": int(timeout_seconds),
            "max_retries": int(max_retries),
            "memory_mb": memory_mb,
            "cpus": cpus,
            "scheduled_at": isoformat(scheduled_at),
            "cron_expression": cron_expression,
            "tags": tags,
        }

    @classmethod
    def _job_fingerprint(cls, job: Job) -> str:
        """Mavjud job'ning barmoq izini uning o'z maydonlaridan hisoblaydi."""
        return IdempotencyService.fingerprint(
            cls._fingerprint_source(
                code=job.code,
                runtime=job.runtime,
                priority=job.priority,
                payload=job.payload,
                env_vars=job.env_vars,
                timeout_seconds=job.timeout_seconds,
                max_retries=job.max_retries,
                memory_mb=job.memory_mb,
                cpus=job.cpus,
                scheduled_at=job.scheduled_at,
                cron_expression=job.cron_expression,
                tags=job.tags,
            )
        )

    # ------------------------------------------------------------------
    # Bir vaqtdalik hisoblagichi
    # ------------------------------------------------------------------

    async def _assert_concurrency(self, user: User, limit: int) -> None:
        """Bir vaqtda bajarilayotgan job'lar limitini tekshiradi.

        Hisoblagich Redis'da — arzon va tez. Redis javob bermasa tekshiruv
        O'TKAZIB YUBORILADI (fail-open): Durabl'ning asosiy kafolati "job
        yo'qolmaydi", shuning uchun Redis uzilishi job qabul qilishni
        to'xtatmaydi. Ortiqcha yuklanish lease va worker soni bilan
        baribir cheklangan.
        """
        current = await self._concurrency_value(user.id)
        if current is None:
            return
        if current >= limit:
            raise ConcurrencyLimitError(
                f"Bir vaqtda {limit} tadan ko'p job bajarilmaydi "
                "(hozirgi job'lar tugashini kuting yoki rejani oshiring)",
                details={"active": current, "limit": limit},
            )

    async def _concurrency_value(self, user_id: uuid.UUID | str) -> int | None:
        """Hisoblagichning joriy qiymati; Redis javob bermasa `None`."""
        try:
            raw = await self.redis.get(RedisKeys.concurrency(user_id))
        except RedisError as exc:
            logger.warning(
                "bir vaqtdalik hisoblagichi o'qilmadi",
                user_id=str(user_id),
                error=str(exc),
            )
            return None
        try:
            return max(0, int(raw)) if raw is not None else 0
        except (TypeError, ValueError):
            return 0

    async def _sync_concurrency(
        self,
        job: Job,
        previous: JobStatus,
        current: JobStatus,
    ) -> None:
        """`RUNNING` ga kirish/chiqishga qarab hisoblagichni moslaydi.

        Simmetriya muhim: `RUNNING` ga kirganda `INCR`, `RUNNING` dan
        chiqqanda (yakuniy holat ham, lease yo'qolib qayta navbatga qaytish
        ham) `DECR`. Aks holda hisoblagich asta-sekin "oqib", foydalanuvchini
        noto'g'ri bloklab qo'yardi.
        """
        if current is previous:
            return
        if current is JobStatus.RUNNING:
            await self._adjust_concurrency(job.user_id, 1)
        elif previous is JobStatus.RUNNING:
            await self._adjust_concurrency(job.user_id, -1)

    async def _adjust_concurrency(self, user_id: uuid.UUID | str, delta: int) -> None:
        """Hisoblagichni o'zgartiradi (0 dan pastga tushmaydi)."""
        key = RedisKeys.concurrency(user_id)
        try:
            if delta > 0:
                await self.redis.incrby(key, delta)
                # Kalit abadiy qolib ketmasligi uchun muddat yangilanadi.
                await self.redis.expire(key, CONCURRENCY_KEY_TTL_SECONDS)
            else:
                value = await self.redis.decrby(key, -delta)
                if value is not None and int(value) < 0:
                    await self.redis.set(key, 0, ex=CONCURRENCY_KEY_TTL_SECONDS)
        except RedisError as exc:
            logger.warning(
                "bir vaqtdalik hisoblagichi yangilanmadi",
                user_id=str(user_id),
                delta=delta,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Hodisa, webhook, metrika
    # ------------------------------------------------------------------

    async def _publish(self, job: Job) -> None:
        """Job hodisasini Pub/Sub orqali tarqatadi (WebSocket uchun).

        Hodisa chop etilmasa job buzilmaydi — faqat real vaqtdagi yangilanish
        kechikadi (mijoz polling bilan ham holatni oladi).
        """
        try:
            # `user_id` OCHIQ uzatiladi: WebSocket `RedisKeys.events_user(...)`
            # kanaliga obuna bo'ladi. `publish_event` hodisa tanasidagi
            # `user_id` ni zaxira sifatida ishlatadi, lekin hodisa shakli
            # kelajakda o'zgarsa o'sha zaxira jimgina ishlamay qolardi.
            await self.queue.publish_event(job_event_payload(job), user_id=job.user_id)
        except Exception as exc:
            # ATAYLAB keng: hodisa — faqat XABARDOR QILISH yo'li. Job holati
            # PostgreSQL'da saqlangan va mijoz uni polling bilan oladi,
            # shuning uchun Pub/Sub muammosi holat o'tishini HECH QACHON
            # buzmasligi kerak.
            logger.warning(
                "job hodisasi chop etilmadi",
                job_id=str(job.id),
                error=str(exc),
            )

    async def _record_usage(self, user: User) -> None:
        """Oylik foydalanish hisoblagichini oshiradi (best-effort).

        Job allaqachon `commit` qilingan — hisobni yozib bo'lmasa job
        qaytarilmaydi: mijozning ishi hisobdan muhimroq. Xato ERROR
        darajasida log qilinadi (hisob-kitob uchun kuzatilishi kerak).
        """
        try:
            await self.billing.record_job(user.id)
            await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            logger.error(
                "foydalanish hisobi yozilmadi",
                user_id=str(user.id),
                error=str(exc),
            )

    async def _dispatch(self, job: Job, event: WebhookEvent) -> None:
        """Mos webhook'larga yetkazish yozuvlarini yaratadi (best-effort).

        `WebhookService.dispatch()` DB'ga `webhook_deliveries` yozadi,
        shuning uchun yozuvlar yaratilgan bo'lsa `commit` qilinadi. Xato
        bo'lsa sessiya `rollback` bilan tozalanadi: job allaqachon
        commit qilingan, ya'ni yo'qolmaydi.
        """
        try:
            created = await self.webhooks.dispatch(job, event)
            if created:
                await self.session.commit()
        except Exception as exc:
            await self.session.rollback()
            logger.warning(
                "webhook yetkazish yozuvlari yaratilmadi",
                job_id=str(job.id),
                # DIQQAT: structlog `event` kalitini BAND qilgan (bound logger
                # metodining birinchi pozitsion parametri) — `event=` uzatilsa
                # `TypeError: got multiple values for argument 'event'` chiqadi.
                webhook_event=WebhookEvent(event).value,
                error=str(exc),
            )

    @staticmethod
    def _track_transition(job: Job, previous: JobStatus, current: JobStatus) -> None:
        """Holat o'zgarishiga mos Prometheus metrikalarini yangilaydi."""
        if current is previous:
            return
        if current is JobStatus.RUNNING and job.queued_at is not None:
            queued_at = ensure_utc(job.queued_at)
            started_at = ensure_utc(job.started_at) or utcnow()
            if queued_at is not None:
                observe_queue_wait(max(0.0, (started_at - queued_at).total_seconds()))
        if current.is_terminal or current is JobStatus.FAILED:
            track_job_completed(current)
            # `job_duration_seconds` ni BU YERDA yozmaymiz: `Executor._record()`
            # har urinish uchun allaqachon yozadi (`result.duration_ms`), va
            # `job.duration_ms` ayni o'sha urinishning davomiyligi — ikki marta
            # yozilsa oxirgi urinish gistogrammada ikki hissa qoldirardi.

    # ------------------------------------------------------------------
    # Mayda yordamchilar
    # ------------------------------------------------------------------

    @staticmethod
    def _scheduled_moment(job: Job) -> datetime | None:
        """Job kechiktirilgan bo'lsa birinchi bajarish vaqti, aks holda `None`."""
        if job.scheduled_at is not None:
            return ensure_utc(job.scheduled_at)
        if job.cron_expression:
            return next_cron_time(job.cron_expression)
        return None

    @staticmethod
    def _span_ms(
        start: datetime | None,
        end: datetime | None,
        *,
        fallback: int | None = None,
    ) -> int | None:
        """Ikki vaqt orasidagi oraliq (ms); biri yo'q bo'lsa `fallback`."""
        if start is None or end is None:
            return fallback
        return elapsed_ms(start, end)

    @staticmethod
    def _dlq_summary(entry: Any) -> dict[str, Any] | None:
        """DLQ yozuvining timeline uchun qisqa ko'rinishi."""
        if entry is None:
            return None
        return {
            "id": entry.id,
            "failure_reason": entry.failure_reason,
            "last_error": entry.last_error,
            "failed_at": ensure_utc(entry.failed_at),
            "retry_count": entry.retry_count,
            "manual_retry_count": entry.manual_retry_count,
            "resolved": entry.resolved,
            "resolved_at": ensure_utc(entry.resolved_at),
        }

    @staticmethod
    def _matches_refinements(job: Job, filters: JobFilter) -> bool:
        """`failure_reason`/`tag` filtrlarini sahifa ustida qo'llaydi."""
        if filters.failure_reason is not None and job.failure_reason != filters.failure_reason:
            return False
        if filters.tag is not None and filters.tag not in (job.tags or []):
            return False
        return True


__all__ = [
    "CANCEL_NAMESPACE",
    "CANCEL_SIGNAL_GRACE_SECONDS",
    "CONCURRENCY_KEY_TTL_SECONDS",
    "DEFAULT_LOG_LIMIT",
    "JobService",
]
