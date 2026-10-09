"""Durabl — bajarish (execution) servisi: DB qatlamini sandbox bilan bog'laydi.

Bu fayl worker'ning asosiy ish zanjirini o'z ichiga oladi. `JobService` job'ning
HAYOT SIKLI bilan ishlaydi, `app/execution/` esa kodni BAJARADI — shu ikkisi
orasidagi barcha ma'lumot almashinuvi ayni shu servisdan o'tadi:

    execute_job(job, worker_id)
        ├── start()     -> `executions` yozuvi + job RUNNING + lease
        ├── run()       -> SandboxService -> ExecutionResult (+ real vaqtda loglar)
        ├── complete()  -> SUCCESS/CANCELLED yo'li
        └── fail()      -> ReliabilityService (retry yoki DLQ qarori)

## Eng muhim kafolat: job HECH QACHON "jimgina o'lmaydi"

`execute_job()` dagi har bir tarmoq — muvaffaqiyat, mijoz kodining xatosi,
timeout, bekor qilish va hatto Durabl'ning O'Z kodidagi kutilmagan
`RuntimeError` — job'ni YAKUNIY holatga yoki `RETRYING`ga olib chiqadi.
`finally` bloklari ham shu maqsadga xizmat qiladi. Agar biror joyda xato
yutilsa, job `RUNNING` holatida muzlab qolardi va faqat lease reaper'i uni
(kechikib) tiklardi — shuning uchun har bir `except` tarmog'i ochiq yozilgan.

## Loglar real vaqtda: nega bufer kerak

Sandbox har `print()` uchun callback chaqiradi. Har qator uchun alohida
`INSERT` qilish DB'ni o'ldiradi (gapdon job minutda o'n minglab qator berishi
mumkin), shuning uchun loglar `_LogPump` ichida buferlanadi va
`LOG_FLUSH_BATCH_SIZE` yozuv yoki `LOG_FLUSH_INTERVAL_SECONDS` vaqt
to'lganda BITTA `executemany` bilan yoziladi. WebSocket'ga esa ayni shu
partiya `job.log` hodisalari bo'lib uzatiladi.

Bufer `ResultCollector` ustiga qurilgan (executor ichida AYNI shu klass
ishlatiladi) — shu tufayli qatorga bo'lish, juda uzun qatorni bo'laklash va
`max_output_bytes` chegarasi IKKI joyda bir xil ishlaydi, mantiq takrorlanmaydi.

Qatlam qoidasi: `fastapi` import QILINMAYDI, `HTTPException` tashlanmaydi —
ayni shu kod worker protsesslarida ham ishlaydi.
"""

from __future__ import annotations

import asyncio
import builtins  # `list` klass ichida metod nomi — builtin'ga ochiq murojaat uchun
import contextlib
import time
import uuid
from collections import Counter
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import (
    ExecutionStatus,
    FailureReason,
    JobStatus,
    LogStream,
    WebhookEvent,
)
from app.exceptions import (
    DurablError,
    ExecutionError,
    ExecutionNotFoundError,
    InfrastructureError,
    JobCancelledError,
    ValidationError,
)
from app.execution.result_collector import ResultCollector
from app.execution.runtime_base import LogSink
from app.execution.types import ExecutionResult, LogEntry, ResourceLimits, SandboxSpec
from app.logging_config import get_logger
from app.models.execution import Execution
from app.models.execution_log import ExecutionLog
from app.models.job import Job
from app.models.user import User
from app.redis_client import get_redis
from app.repositories.execution_log_repo import (
    DEFAULT_LOG_LIMIT,
    ExecutionLogRepository,
)
from app.repositories.execution_repo import ExecutionRepository
from app.repositories.job_repo import JobRepository
from app.repositories.subscription_repo import SubscriptionRepository
from app.schemas.base import PaginationParams
from app.schemas.execution import ExecutionFilter
from app.services.billing_service import BillingService
from app.services.job_service import JobService
from app.services.queue_service import QueueService
from app.services.reliability_service import ReliabilityService
from app.services.sandbox_service import SandboxService
from app.services.webhook_service import WebhookService
from app.utils.retry_policy import NON_RETRYABLE_REASONS
from app.utils.time_utils import seconds_from_now, utcnow

logger = get_logger(__name__)

#: Bufer qancha vaqtda bir majburan bo'shatiladi (soniya).
#: Mijoz loglarni real vaqtda ko'rishi uchun kechikishning yuqori chegarasi.
LOG_FLUSH_INTERVAL_SECONDS: float = 2.0

#: Bufer qancha yozuv to'planganda darhol bo'shatiladi.
LOG_FLUSH_BATCH_SIZE: int = 200

#: Bufer holatini tekshirish davri (soniya). `LOG_FLUSH_INTERVAL_SECONDS` dan
#: kichik: aks holda 200 yozuvlik chegara faqat 2 soniyadan keyin sezilardi.
LOG_POLL_INTERVAL_SECONDS: float = 0.25

#: WebSocket log hodisasining turi (`{type, data}` konvertida).
LOG_EVENT_TYPE: str = "job.log"


# ---------------------------------------------------------------------------
# Loglarni real vaqtda uzatuvchi bufer (xususiy)
# ---------------------------------------------------------------------------


class _LogPump:
    """Sandbox loglarini buferlab DB'ga va WebSocket'ga uzatadi.

    Ikki qismdan iborat:

    * **sink** — `executor` chaqiradigan SINXRON callback (`LogSink` imzosi).
      U faqat buferga qo'shadi, hech qanday `await` qilmaydi: aks holda
      mijoz kodining chiqishi DB tezligiga bog'lanib qolardi.
    * **pump()** — fon vazifasi. Davriy ravishda buferni tekshiradi va
      to'lgan partiyani yozadi.

    Bufer sifatida `ResultCollector` ishlatiladi — u chunk'larni qatorlarga
    bo'lish, juda uzun qatorni bo'laklash va chiqish limitini nazorat qilish
    mantig'ini allaqachon beradi (executor ichida ham ayni shu klass).
    """

    __slots__ = (
        "_collector",
        "_execution",
        "_job",
        "_last_flush",
        "_publish_failed",
        "_service",
        "_start_sequence",
        "_written",
    )

    def __init__(
        self,
        service: ExecutionService,
        job: Job,
        execution: Execution,
        *,
        limits: ResourceLimits,
        start_sequence: int,
    ) -> None:
        self._service = service
        self._job = job
        self._execution = execution
        self._start_sequence = start_sequence
        self._collector = ResultCollector(limits=limits, start_sequence=start_sequence)
        self._written = 0
        self._last_flush = time.monotonic()
        self._publish_failed = False

    # ------------------------------------------------------------------
    # Executor bilan shartnoma
    # ------------------------------------------------------------------

    @property
    def sink(self) -> LogSink:
        """`Executor.execute(on_log=...)` ga uzatiladigan callback."""
        return self._feed

    def _feed(self, stream: LogStream, chunk: str) -> None:
        """Bo'lakni buferga qo'shadi; HECH QACHON xato tashlamaydi.

        Executor tashqi callback xatosini yutib yuboradi, lekin biz unga
        tayanmaymiz: bu yerdagi xato mijoz loglarining BIR QISMI yo'qolishiga
        olib keladi, shuning uchun u ko'rinadigan bo'lishi kerak.
        """
        try:
            self._collector.feed(stream, chunk)
        except Exception as exc:  # pragma: no cover - himoya qatlami
            logger.warning(
                "execution.log_buffer_failed",
                job_id=str(self._job.id),
                error=str(exc),
                error_type=type(exc).__name__,
            )

    # ------------------------------------------------------------------
    # Fon vazifasi
    # ------------------------------------------------------------------

    async def pump(self) -> None:
        """Buferni davriy bo'shatadi (bajarish davomida ishlaydi).

        Vazifa `run()` dagi `finally` da bekor qilinadi. `CancelledError`
        bu yerda ushlanmaydi — u normal to'xtatish yo'li.
        """
        while True:
            await asyncio.sleep(LOG_POLL_INTERVAL_SECONDS)
            if self._should_flush():
                await self._flush()

    def _should_flush(self) -> bool:
        """Partiya to'ldimi yoki vaqt keldimi?"""
        pending = self._pending_count()
        if pending <= 0:
            return False
        if pending >= LOG_FLUSH_BATCH_SIZE:
            return True
        return (time.monotonic() - self._last_flush) >= LOG_FLUSH_INTERVAL_SECONDS

    def _pending_count(self) -> int:
        """Hali yozilmagan yozuvlar soni (ro'yxat NUSXALANMAYDI).

        `ResultCollector.next_sequence` har yozuv uchun aynan bir marta
        o'sadi, shuning uchun sanoq uchun shu arzon yo'l ishlatiladi —
        `.logs` ni har 0.25 soniyada nusxalash katta loglarda qimmat.
        """
        return self._collector.next_sequence - self._start_sequence - self._written

    async def _flush(self) -> int:
        """Yangi yozuvlarni DB'ga yozadi, commit qiladi va WebSocket'ga uzatadi.

        **Commit ATAYLAB bu yerda:** mijoz `GET /jobs/{id}/logs` bilan job
        bajarilayotgan paytda loglarni ko'rishi kerak, commit qilinmagan
        qatorlar esa boshqa sessiyaga ko'rinmaydi. `start()` allaqachon
        commit qilgani uchun bu yerda "yarim tayyor" holat yo'q.

        Xato bo'lsa bajarish TO'XTAMAYDI — loglar ikkinchi darajali
        ma'lumot, mijoz kodining ishlashi ulardan muhimroq.
        """
        pending = self._collector.logs[self._written :]
        if not pending:
            return 0

        try:
            written = await self._service.persist_logs(self._execution, pending)
            await self._service.session.commit()
        except Exception as exc:
            with contextlib.suppress(Exception):
                await self._service.session.rollback()
            logger.warning(
                "execution.log_flush_failed",
                job_id=str(self._job.id),
                execution_id=str(self._execution.id),
                entries=len(pending),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return 0

        self._written += len(pending)
        self._last_flush = time.monotonic()
        await self._publish(pending)
        return written

    async def _publish(self, entries: list[LogEntry]) -> None:
        """Partiyani `job.log` hodisalari sifatida Pub/Sub'ga uzatadi.

        Birinchi xatodan keyin shu bajarish uchun chop etish TO'XTATILADI:
        Redis javob bermayotgan bo'lsa qolgan minglab qator uchun ham
        urinish faqat vaqtni yo'qotadi (loglar DB'da saqlangan va mijoz
        ularni polling bilan oladi).
        """
        if self._publish_failed:
            return
        for entry in entries:
            event = {
                "type": LOG_EVENT_TYPE,
                "data": {
                    "job_id": str(self._job.id),
                    "execution_id": str(self._execution.id),
                    "stream": LogStream(entry.stream).value,
                    "content": entry.content,
                    "sequence": entry.sequence,
                },
            }
            try:
                await self._service.queue.publish_event(event, user_id=self._job.user_id)
            except Exception as exc:
                self._publish_failed = True
                logger.warning(
                    "execution.log_publish_failed",
                    job_id=str(self._job.id),
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                return

    # ------------------------------------------------------------------
    # Yakunlash
    # ------------------------------------------------------------------

    async def finalize(self, result: ExecutionResult | None) -> int:
        """Qolgan loglarni oxirigacha yozadi; yozilgan yozuv sonini qaytaradi.

        Ikki qadam:

        1. Buferdagi to'liq bo'lmagan oxirgi qator `flush()` bilan chiqariladi
           va qolgan hamma narsa yoziladi.
        2. Executor O'ZI qo'shgan `SYSTEM` xabarlari (timeout, bekor qilish,
           runner xatosi) ko'chiriladi. Bu xabarlar `collector.feed_system()`
           orqali EXECUTOR ichidagi nusxaga yozilgani uchun bizning buferga
           tushmaydi — shuning uchun ularni `result.logs` dan ajratib olamiz.
           Ajratish mazmun bo'yicha (`Counter`) qilinadi: bizda allaqachon
           bor `SYSTEM` xabarlari (masalan kesish ogohlantirishi) ikki marta
           yozilmaydi.
        """
        total = await self._flush_final()
        if result is None:
            return total
        total += await self._persist_extra_system(result)
        return total

    async def _flush_final(self) -> int:
        """Buferni to'liq bo'shatadi (yarim qator ham chiqariladi)."""
        try:
            self._collector.flush()
        except Exception as exc:  # pragma: no cover - himoya qatlami
            logger.warning(
                "execution.log_buffer_flush_failed",
                job_id=str(self._job.id),
                error=str(exc),
            )
        return await self._flush()

    async def _persist_extra_system(self, result: ExecutionResult) -> int:
        """Executor qo'shgan, bizda yo'q `SYSTEM` xabarlarini yozadi."""
        seen: Counter[str] = Counter(
            entry.content
            for entry in self._collector.logs
            if LogStream(entry.stream) is LogStream.SYSTEM
        )
        sequence = self._collector.next_sequence
        extras: list[LogEntry] = []

        for entry in result.logs:
            if LogStream(entry.stream) is not LogStream.SYSTEM:
                continue
            if seen[entry.content] > 0:
                seen[entry.content] -= 1
                continue
            extras.append(
                LogEntry(
                    stream=LogStream.SYSTEM,
                    content=entry.content,
                    sequence=sequence,
                    timestamp=entry.timestamp,
                )
            )
            sequence += 1

        if not extras:
            return 0

        try:
            written = await self._service.persist_logs(self._execution, extras)
            await self._service.session.commit()
        except Exception as exc:
            with contextlib.suppress(Exception):
                await self._service.session.rollback()
            logger.warning(
                "execution.system_log_write_failed",
                job_id=str(self._job.id),
                entries=len(extras),
                error=str(exc),
            )
            return 0

        await self._publish(extras)
        return written

    @property
    def next_sequence(self) -> int:
        """Keyingi bo'sh log tartib raqami (diagnostika uchun)."""
        return self._collector.next_sequence


# ---------------------------------------------------------------------------
# Asosiy servis
# ---------------------------------------------------------------------------


class ExecutionService:
    """Bajarish urinishlarini boshqaradi: boshlash, bajarish, yakunlash.

    Args:
        session: Tranzaksiya sessiyasi.
        redis: Redis ulanishi. `None` bo'lsa global nusxa olinadi.
        sandbox: Bajarish fasadi. `None` bo'lsa standart nusxa yasaladi.
            Ochiq berish FAQAT testlar uchun: soxta runner bilan yasalgan
            `SandboxService` uzatiladi va Docker kerak bo'lmaydi.
    """

    def __init__(
        self,
        session: AsyncSession,
        redis: Redis | None = None,
        *,
        sandbox: SandboxService | None = None,
    ) -> None:
        self.session = session
        self.redis = redis or get_redis()
        self.executions = ExecutionRepository(session)
        self.execution_logs = ExecutionLogRepository(session)
        self.jobs = JobRepository(session)
        self.subscriptions = SubscriptionRepository(session)
        self.sandbox = sandbox or SandboxService()
        self.queue = QueueService(self.redis)
        self.job_service = JobService(session, self.redis)
        self.reliability = ReliabilityService(session, self.redis)
        self.billing = BillingService(session)
        self.webhooks = WebhookService(session, self.redis)

    # ------------------------------------------------------------------
    # 1. Urinishni boshlash
    # ------------------------------------------------------------------

    async def start(self, job: Job, worker_id: str) -> Execution:
        """Yangi bajarish urinishini ochadi va job'ni `RUNNING` ga o'tkazadi.

        Tartib muhim: avval holat o'tishi TEKSHIRILADI (`mark_running`), faqat
        keyin `executions` yozuvi yaratiladi. Teskari qilsak, grafikka mos
        kelmaydigan o'tishda bo'sh urinish yozuvi qolib ketardi va
        `attempt_number` behuda sarflanardi.

        Lease `settings.LEASE_TTL_SECONDS` ga qo'yiladi — worker heartbeat
        bilan uni surib boradi; worker qulasa lease tugaydi va
        `reap_expired_leases()` job'ni boshqa worker'ga o'tkazadi.

        Public metod — tranzaksiyani O'ZI yopadi (`commit`): worker shu
        nuqtadan keyin qulasa ham urinish DB'da ko'rinib turadi va lease
        reaper'i job'ni tiklaydi.

        Raises:
            InvalidStateTransitionError: Job `RUNNING` ga o'tolmaydi
                (masalan allaqachon bekor qilingan).
        """
        attempt_number = await self.executions.next_attempt_number(job.id)

        await self.job_service.mark_running(job, worker_id)

        execution = await self.executions.create(
            job_id=job.id,
            attempt_number=attempt_number,
            worker_id=worker_id,
            status=ExecutionStatus.RUNNING,
            started_at=utcnow(),
            lease_expires_at=seconds_from_now(settings.LEASE_TTL_SECONDS),
        )

        await self.persist_logs(
            execution,
            [
                LogEntry(
                    stream=LogStream.SYSTEM,
                    content=f"Worker {worker_id} job'ni oldi (urinish {attempt_number})",
                    sequence=0,
                )
            ],
        )

        await self.session.commit()

        logger.info(
            "execution.attempt_started",
            job_id=str(job.id),
            execution_id=str(execution.id),
            attempt=attempt_number,
            worker_id=worker_id,
            correlation_id=job.correlation_id,
            lease_ttl_seconds=settings.LEASE_TTL_SECONDS,
        )
        return execution

    # ------------------------------------------------------------------
    # 2. Kodni bajarish
    # ------------------------------------------------------------------

    async def run(self, job: Job, execution: Execution) -> ExecutionResult:
        """Kodni sandbox'da bajaradi va loglarni real vaqtda uzatadi.

        Loglar har bir qator uchun DB'ga yozilmaydi — `_LogPump` ularni
        buferlab partiyalar bilan yozadi va AYNI vaqtda `job.log` hodisasi
        sifatida WebSocket'ga uzatadi.

        Ichki metod — commit QILMAYDI (loglar partiyasi istisno: ular
        mijozga real vaqtda ko'rinishi uchun `_LogPump` ichida alohida
        commit qilinadi; job holati bu metodda O'ZGARMAYDI).

        Returns:
            `ExecutionResult` — xato holatida ham (executor shartnomasi).

        Raises:
            asyncio.CancelledError: Bajarish tashqaridan bekor qilindi.
            ValidationError: `job.runtime` qo'llab-quvvatlanmaydi (bajarish
                hatto boshlanmaydi).
        """
        spec = await self._build_spec(job, execution)

        # Loglar `start()` dagi SYSTEM xabaridan KEYIN davom etadi, shuning
        # uchun tartib raqami DB'dan olinadi (`sequence` takrorlanmaydi).
        start_sequence = await self.execution_logs.next_sequence(execution.id)
        pump = _LogPump(
            self,
            job,
            execution,
            limits=spec.limits,
            start_sequence=start_sequence,
        )

        pump_task = asyncio.create_task(pump.pump())
        result: ExecutionResult | None = None
        try:
            result = await self.sandbox.run(spec, on_log=pump.sink)
            return result
        finally:
            await self._stop_pump(pump, pump_task, result)

    @staticmethod
    async def _stop_pump(
        pump: _LogPump,
        task: asyncio.Task[None],
        result: ExecutionResult | None,
    ) -> None:
        """Fon vazifasini to'xtatadi va qolgan loglarni yozadi.

        Avval vazifa BEKOR QILINADI, keyin yakuniy yozuv bajariladi — aks
        holda ikkisi AYNI `AsyncSession` ni bir vaqtda ishlatib qo'yardi
        (SQLAlchemy sessiyasi parallel foydalanishga mo'ljallanmagan).

        `asyncio.shield` bekor qilish paytida ham yakuniy yozuvning
        tugashiga imkon beradi: aks holda `CancelledError` yo'lida oxirgi
        partiya butunlay yo'qolardi.
        """
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

        finalize_task = asyncio.ensure_future(pump.finalize(result))
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.shield(finalize_task)

        if not finalize_task.done():
            # TAKRORIY bekor qilish (`task.cancel()` ikki marta) `shield` ni
            # ham uzadi. Bunda yakunlash vazifasi FONDA qolib ketardi va
            # `execute_job()` dagi `fail()` bilan AYNI `AsyncSession` ni
            # parallel ishlatardi — SQLAlchemy sessiyasi bunga
            # mo'ljallanmagan. Oxirgi log partiyasidan voz kechish
            # sessiyaning buzilishidan afzal: loglar ikkinchi darajali,
            # job holatini yozish esa Durabl'ning asosiy kafolati.
            finalize_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await finalize_task
            logger.warning("execution.log_finalize_abandoned")

    async def _build_spec(self, job: Job, execution: Execution) -> SandboxSpec:
        """Job va foydalanuvchi rejasidan `SandboxSpec` yasaydi.

        Reja limitlari `SubscriptionRepository.ensure_for_user()` dan olinadi
        (obuna yo'q bo'lsa FREE yaratiladi) — bu yozuv keyingi `commit` bilan
        saqlanadi. Obunani o'qib bo'lmasa bajarish TO'XTAMAYDI: `plan=None`
        bilan global sozlama chegaralari qo'llanadi, ya'ni eng QAT'IY
        variant tanlanadi (mijozga ortiqcha resurs berilmaydi).
        """
        plan = None
        try:
            subscription = await self.subscriptions.ensure_for_user(job.user_id)
            plan = subscription.limits
        except DurablError as exc:
            logger.warning(
                "execution.plan_lookup_failed",
                job_id=str(job.id),
                user_id=str(job.user_id),
                error=str(exc),
            )

        return self.sandbox.build_spec(
            job,
            attempt_number=execution.attempt_number,
            plan=plan,
        )

    # ------------------------------------------------------------------
    # 3. Muvaffaqiyatli (yoki bekor qilingan) yakun
    # ------------------------------------------------------------------

    async def complete(
        self,
        job: Job,
        execution: Execution,
        result: ExecutionResult,
    ) -> Job:
        """Natijani DB'ga yozadi va job'ni yakuniy holatga o'tkazadi.

        `result.status` bo'yicha uch yo'l:

        * `SUCCESS` -> job `SUCCESS`, `JOB_SUCCEEDED` webhook'i, hisob yozuvi;
        * `CANCELLED` -> job `CANCELLED`, `JOB_CANCELLED` webhook'i;
        * qolgan hammasi (`FAILED`, `TIMEOUT`, `LOST`) -> `fail()` ga
          o'tkaziladi, ya'ni retry/DLQ qarorini `ReliabilityService` qabul
          qiladi.

        Public metod — tranzaksiyani O'ZI yopadi (`commit`).

        Returns:
            Yangilangan `Job`.
        """
        status = ExecutionStatus(result.status)

        if status is ExecutionStatus.SUCCESS:
            return await self._complete_success(job, execution, result)
        if status is ExecutionStatus.CANCELLED:
            return await self._complete_cancelled(job, execution, result)

        return await self.fail(job, execution, self._error_from(result), result=result)

    async def _complete_success(
        self,
        job: Job,
        execution: Execution,
        result: ExecutionResult,
    ) -> Job:
        """`SUCCESS` yo'li: urinish va job yakunlanadi, hisob yoziladi."""
        await self.executions.finish(execution, **result.to_execution_fields())
        job = await self.job_service.mark_success(job, **result.to_job_fields())

        await self._release_lease(job, execution)
        await self.session.commit()

        logger.info(
            "execution.completed",
            job_id=str(job.id),
            execution_id=str(execution.id),
            attempt=execution.attempt_number,
            status=JobStatus(job.status).value,
            duration_ms=result.duration_ms,
            truncated=result.truncated,
            correlation_id=job.correlation_id,
        )

        await self._record_execution_usage(job, result, success=True)
        await self._dispatch(job, WebhookEvent.JOB_SUCCEEDED)
        return job

    async def _complete_cancelled(
        self,
        job: Job,
        execution: Execution,
        result: ExecutionResult,
    ) -> Job:
        """`CANCELLED` yo'li: qismiy natija saqlanadi, retry QILINMAYDI."""
        fields = result.to_execution_fields()
        fields["status"] = ExecutionStatus.CANCELLED
        await self.executions.finish(execution, **fields)

        # Qismiy chiqish mijozga kerak: bekor qilishdan oldin kod nima
        # chiqargani diagnostika uchun eng qimmatli ma'lumot.
        await self.jobs.update(job, **self._partial_job_fields(result))
        job = await self.job_service.mark_cancelled(job)

        await self._release_lease(job, execution)
        await self.session.commit()

        logger.info(
            "execution.cancelled",
            job_id=str(job.id),
            execution_id=str(execution.id),
            attempt=execution.attempt_number,
            duration_ms=result.duration_ms,
            correlation_id=job.correlation_id,
        )

        await self._record_execution_usage(job, result, success=False)
        await self._dispatch(job, WebhookEvent.JOB_CANCELLED)
        return job

    # ------------------------------------------------------------------
    # 4. Xatoli yakun
    # ------------------------------------------------------------------

    async def fail(
        self,
        job: Job,
        execution: Execution,
        error: ExecutionError,
        *,
        result: ExecutionResult | None = None,
    ) -> Job:
        """Urinishni xato bilan yakunlaydi va retry/DLQ qarorini so'raydi.

        Qarorni `ReliabilityService.handle_failure()` qabul qiladi — u
        `RetryPolicy` va `NON_RETRYABLE_REASONS` bo'yicha job'ni `RETRYING`
        yoki `DEAD_LETTER` holatiga o'tkazadi. DLQ hodisasini (`JOB_DEAD_LETTERED`)
        ham AYNI shu servis yuboradi, shuning uchun bu yerdan FAQAT
        `JOB_FAILED` chiqadi.

        `JobCancelledError` MAXSUS holat: u `retryable=False` bo'lgani uchun
        `handle_failure()` job'ni to'g'ridan-to'g'ri DLQ'ga tashlardi, mijoz
        esa o'zi bekor qilgan job'ni "o'lik xat" sifatida ko'rardi. Shuning
        uchun u `CANCELLED` yo'liga burib yuboriladi.

        Args:
            job: Bajarilayotgan job.
            execution: Joriy urinish.
            error: Bajarish xatosi (`failure_reason` va `retryable` bilan).
            result: Bor bo'lsa — urinish natijasi. Undan `stdout`/`stderr`,
                `exit_code` va `duration_ms` olinadi: xato bo'lganda ham
                mijoz chiqishni ko'rishi SHART (shartnomadagi imzoga
                standart qiymatli qo'shimcha argument).

        Public metod — tranzaksiyani O'ZI yopadi (`commit`).
        """
        if isinstance(error, JobCancelledError):
            return await self._complete_cancelled(
                job,
                execution,
                result or ExecutionResult(status=ExecutionStatus.CANCELLED),
            )

        reason = error.failure_reason or FailureReason.INTERNAL_ERROR
        status = (
            ExecutionStatus.TIMEOUT
            if reason is FailureReason.TIMEOUT
            else ExecutionStatus.FAILED
        )

        fields: dict[str, Any] = (
            dict(result.to_execution_fields()) if result is not None else {}
        )
        fields.update(
            status=status,
            failure_reason=reason,
            error_message=error.message,
        )
        if fields.get("exit_code") is None and error.exit_code is not None:
            fields["exit_code"] = error.exit_code
        await self.executions.finish(execution, **fields)

        # Job ustunlari HOLAT O'TISHIDAN OLDIN yoziladi: `handle_failure()`
        # job'ni `RETRYING`/`DEAD_LETTER` ga o'tkazadi va chiqish maydonlari
        # bilan ishlamaydi, ya'ni bu yerda yozmasak DLQ'dagi job'da
        # `stderr` bo'sh qolardi — diagnostika imkonsiz bo'lardi.
        job_fields = self._partial_job_fields(result)
        job_fields["error"] = error.message
        job_fields["failure_reason"] = reason
        await self.jobs.update(job, **job_fields)

        decided = await self._handle_failure(job, execution, error)

        await self._release_lease(job, execution)
        await self.session.commit()

        final = JobStatus(job.status)
        logger.warning(
            "execution.failed",
            job_id=str(job.id),
            execution_id=str(execution.id),
            attempt=execution.attempt_number,
            execution_status=status.value,
            job_status=final.value,
            failure_reason=reason.value,
            retryable=error.retryable,
            exit_code=fields.get("exit_code"),
            decided=JobStatus(decided).value if decided is not None else None,
            correlation_id=job.correlation_id,
        )

        if result is not None:
            await self._record_execution_usage(job, result, success=False)

        # Webhook siyosati (ikki servis orasida kelishilgan):
        #
        # * `RETRYING` -> hodisa YUBORILMAYDI. `ReliabilityService` buni
        #   ataylab shunday qo'ygan: har qayta urinish uchun webhook mijozga
        #   spam bo'lardi, u faqat YAKUNIY natijani bilishi kerak.
        # * `DEAD_LETTER` -> `JOB_DEAD_LETTERED`ni `move_to_dlq()` O'ZI
        #   yuboradi, shuning uchun bu yerdan faqat umumiy `JOB_FAILED`
        #   chiqadi: faqat `job.failed` ga obuna bo'lgan mijoz ham xabardor
        #   bo'ladi (umumiy + aniq hodisa juftligi).
        if final is not JobStatus.RETRYING:
            await self._dispatch(job, WebhookEvent.JOB_FAILED)
        return job

    async def _handle_failure(
        self,
        job: Job,
        execution: Execution,
        error: ExecutionError,
    ) -> JobStatus | None:
        """`ReliabilityService` qarorini oladi; qulasa zaxira yo'lga o'tadi.

        Ikki himoya qatlami bor, chunki job HECH QACHON `RUNNING` holatida
        muzlab qolmasligi kerak:

        1. `handle_failure()` xato tashlasa — job majburan `FAILED` qilinadi
           (lease reaper'i yoki admin keyin DLQ'ga o'tkazadi).
        2. Xato tashlamasa, lekin holatni qo'llamagan bo'lsa — qaytgan qiymat
           o'zimiz qo'llanadi.
        """
        try:
            decided = await self.reliability.handle_failure(job, execution, error)
        except Exception as exc:
            logger.error(
                "execution.failure_handler_failed",
                job_id=str(job.id),
                execution_id=str(execution.id),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            await self._force_status(job, JobStatus.FAILED, error)
            return JobStatus(job.status)

        if JobStatus(job.status) is JobStatus.RUNNING:
            target = self._as_job_status(decided) or JobStatus.FAILED
            logger.warning(
                "execution.failure_status_applied",
                job_id=str(job.id),
                status=target.value,
            )
            await self._force_status(job, target, error)

        return self._as_job_status(decided)

    async def _force_status(
        self,
        job: Job,
        target: JobStatus,
        error: ExecutionError,
    ) -> None:
        """Job'ni majburan berilgan holatga o'tkazadi (grafik tekshirilmaydi).

        Faqat zaxira yo'lda chaqiriladi: `validate=False` chunki bu TIKLASH
        amali — asosiy maqsad job'ni `RUNNING` dan chiqarib olish.
        """
        with contextlib.suppress(Exception):
            await self.job_service.transition(
                job,
                target,
                validate=False,
                error=error.message,
                failure_reason=error.failure_reason,
            )

    # ------------------------------------------------------------------
    # 5. To'liq zanjir (worker chaqiradi)
    # ------------------------------------------------------------------

    async def execute_job(self, job: Job, worker_id: str) -> Job:
        """Job'ni boshidan oxirigacha bajaradi — worker'ning asosiy chaqiruvi.

        Zanjir: `start()` -> `run()` -> `complete()`/`fail()`. HAR BIR yo'lda
        job yakuniy holatga yoki `RETRYING`ga o'tadi — "jim o'lish" holati
        yo'q. Kutilmagan `RuntimeError` ham `INTERNAL_ERROR` sababli xatoga
        aylanadi va retry siyosatidan o'tadi.

        Bekor qilish IKKI yo'l bilan keladi:

        * Mijoz `POST /jobs/{id}/cancel` qilgan — signal Redis'da turadi,
          bajarish tugagach `is_cancel_requested()` bilan tekshiriladi va
          natija `CANCELLED` deb qayta belgilanadi;
        * worker vazifasi bekor qilingan (`asyncio.CancelledError`) — job
          `CANCELLED` qilinadi va xato chaqiruvchiga qayta tashlanadi
          (graceful shutdown zanjiri buzilmasligi uchun).

        Public metod — ichidagi `start/complete/fail` har biri o'z
        tranzaksiyasini yopadi.

        Returns:
            Yakuniy holatdagi `Job`.
        """
        execution = await self.start(job, worker_id)

        try:
            result = await self.run(job, execution)

            if await self._is_cancel_requested(job):
                logger.info(
                    "execution.cancel_requested",
                    job_id=str(job.id),
                    execution_id=str(execution.id),
                    runner_status=ExecutionStatus(result.status).value,
                )
                result.status = ExecutionStatus.CANCELLED

            job = await self.complete(job, execution, result)

        except asyncio.CancelledError:
            await self._fail_quietly(job, execution, JobCancelledError())
            raise

        except ValidationError as exc:
            # Kod yoki muhit validatsiyadan o'tmadi — qayta urinish befoyda.
            job = await self.fail(
                job,
                execution,
                ExecutionError(
                    exc.message,
                    failure_reason=FailureReason.VALIDATION_ERROR,
                    retryable=False,
                ),
            )

        except ExecutionError as exc:
            job = await self.fail(job, execution, exc)

        except Exception as exc:
            # Durabl'ning O'Z kodidagi xato ham job'ni yo'qotmasligi kerak.
            logger.exception(
                "execution.chain_unexpected_error",
                job_id=str(job.id),
                execution_id=str(execution.id),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            job = await self.fail(
                job,
                execution,
                ExecutionError(
                    f"{type(exc).__name__}: {exc}",
                    failure_reason=FailureReason.INTERNAL_ERROR,
                    retryable=True,
                ),
            )

        finally:
            await self._clear_cancel(job)

        return job

    # ------------------------------------------------------------------
    # 6. Loglar
    # ------------------------------------------------------------------

    async def persist_logs(self, execution: Execution, logs: list[LogEntry]) -> int:
        """Log yozuvlarini BITTA `INSERT` (`executemany`) bilan saqlaydi.

        Ichki metod — commit QILMAYDI. Chaqiruvchi tranzaksiya egasi:
        `complete()`/`fail()` o'z commit'i bilan yopadi, real vaqtdagi
        partiya esa `_LogPump` ichida alohida commit qilinadi.

        Args:
            execution: Qaysi urinishning loglari.
            logs: `LogEntry` ro'yxati (`sequence` har birida to'ldirilgan
                bo'lishi kerak — aks holda repozitoriy o'zi raqamlaydi).

        Returns:
            Yozilgan qatorlar soni (bo'sh ro'yxatda `0`).
        """
        if not logs:
            return 0
        return await self.execution_logs.bulk_add(execution.id, execution.job_id, logs)

    # ------------------------------------------------------------------
    # 7. O'qish (API qatlami uchun)
    # ------------------------------------------------------------------

    async def list(
        self,
        user: User,
        filters: ExecutionFilter,
        pagination: PaginationParams,
    ) -> tuple[list[Execution], int]:
        """Foydalanuvchining bajarish urinishlari: `(yozuvlar, umumiy_son)`.

        `user_id` repozitoriyda `jobs` bilan `JOIN` orqali qo'llanadi, ya'ni
        boshqa foydalanuvchining urinishi natijaga HECH QACHON tushmaydi.
        """
        return await self.executions.search(
            user_id=user.id,
            job_id=filters.job_id,
            status=filters.status,
            failure_reason=filters.failure_reason,
            worker_id=filters.worker_id,
            start=filters.start,
            end=filters.end,
            page=pagination.page,
            page_size=pagination.page_size,
            sort_by=filters.sort_by,
            sort_order=filters.sort_order,
        )

    async def get(self, user: User, execution_id: uuid.UUID | str) -> Execution:
        """Bitta urinish tafsiloti (egalik tekshirilgan).

        Boshqa foydalanuvchining urinishi ham "topilmadi" deb qaytariladi —
        resurs mavjudligini oshkor qilmaymiz (IDOR himoyasi).

        Raises:
            ExecutionNotFoundError: Urinish yo'q yoki boshqa egaga tegishli.
        """
        execution = await self.executions.get_for_user(execution_id, user.id)
        if execution is None:
            raise ExecutionNotFoundError(execution_id)
        return execution

    async def logs(
        self,
        user: User,
        execution_id: uuid.UUID | str,
        *,
        after_sequence: int | None = None,
        limit: int = DEFAULT_LOG_LIMIT,
        stream: LogStream | str | None = None,
    ) -> tuple[Execution, builtins.list[ExecutionLog]]:
        """Bitta urinishning loglari: `(urinish, qatorlar)`.

        `GET /executions/{id}/logs` endpoint'i uchun qo'shilgan (API qatlami
        repozitoriyga bevosita tegmaydi). `JobService.logs()` dan farqi:
        bu yerda kursor BITTA urinishga tegishli, shuning uchun
        `after_sequence` har doim ishonchli ishlaydi (`sequence` har urinish
        ichida 0'dan boshlanadi).

        Urinishning O'ZI ham qaytariladi: javob shakli (`JobLogsResponse`)
        `job_id` va `execution_id` ni talab qiladi, loglar ro'yxati esa bo'sh
        bo'lishi mumkin — ya'ni ularni qatorlardan olish ishonchsiz. Egalik
        `get()` ichida tekshiriladi, shuning uchun ikkinchi so'rov kerak emas.

        Args:
            user: So'rovchi (egalik tekshiruvi uchun).
            execution_id: Urinish identifikatori.
            after_sequence: Shu tartib raqamidan KEYINGI qatorlar (kursor).
            limit: Bir sahifadagi qatorlar soni.
            stream: Faqat shu oqim (`stdout`/`stderr`/`system`).

        Returns:
            `(urinish, log qatorlari)` — qatorlar `sequence` bo'yicha o'sish
            tartibida.

        Raises:
            ExecutionNotFoundError: Urinish yo'q yoki boshqa egaga tegishli.
        """
        execution = await self.get(user, execution_id)
        entries = await self.execution_logs.list_for_execution(
            execution.id,
            after_sequence=after_sequence,
            limit=limit,
            stream=stream,
        )
        return execution, entries

    # ------------------------------------------------------------------
    # Ichki yordamchilar
    # ------------------------------------------------------------------

    @staticmethod
    def _error_from(result: ExecutionResult) -> ExecutionError:
        """Muvaffaqiyatsiz natijadan `ExecutionError` yasaydi.

        `retryable` natijaning SABABIGA qarab aniqlanadi: `OOM`,
        `OUTPUT_TOO_LARGE` va `VALIDATION_ERROR` uchun qayta urinish ayni
        natijani beradi, shuning uchun ular `NON_RETRYABLE_REASONS` ro'yxatida.
        """
        reason = result.failure_reason or FailureReason.INTERNAL_ERROR
        message = result.error_message or (
            f"Bajarish {ExecutionStatus(result.status).value} holatida tugadi"
        )
        return ExecutionError(
            message,
            failure_reason=reason,
            retryable=reason not in NON_RETRYABLE_REASONS,
            exit_code=result.exit_code,
        )

    @staticmethod
    def _partial_job_fields(result: ExecutionResult | None) -> dict[str, Any]:
        """Natijadan `jobs` jadvalining chiqish ustunlarini ajratadi.

        `status`, `error` va `failure_reason` QAYTARILMAYDI — holatni
        `job_state` boshqaradi, xato matnini esa chaqiruvchi o'zi qo'yadi.
        """
        if result is None:
            return {}
        fields = dict(result.to_job_fields())
        fields.pop("error", None)
        fields.pop("failure_reason", None)
        return fields

    @staticmethod
    def _as_job_status(value: object) -> JobStatus | None:
        """Qaytgan qiymatni `JobStatus` ga keltiradi (mos kelmasa `None`).

        `handle_failure()` shartnoma bo'yicha `JobStatus` qaytaradi, lekin
        bu zanjirning eng muhim nuqtasi — mos kelmagan qiymat tufayli
        istisno tashlanmasligi kerak.
        """
        if isinstance(value, JobStatus):
            return value
        if not isinstance(value, str):
            # `None` ham, kutilmagan tur ham bir xil: qaror yo'q.
            return None
        try:
            return JobStatus(value)
        except ValueError:
            return None

    async def _release_lease(self, job: Job, execution: Execution) -> None:
        """Lease'ni IKKI joyda bo'shatadi: DB ustunida va Redis kalitida.

        DB ustuni (`lease_expires_at = NULL`) reaper so'rovidan chiqaradi,
        Redis kaliti esa boshqa worker job'ni darhol olishi uchun. Redis
        xatosi yakunlashni TO'XTATMAYDI — kalit o'z TTL'i bilan baribir
        o'chadi.
        """
        with contextlib.suppress(Exception):
            await self.executions.release_lease(execution)

        worker_id = execution.worker_id
        if not worker_id:
            return
        try:
            await self.reliability.release_lease(job.id, worker_id)
        except (RedisError, InfrastructureError) as exc:
            logger.warning(
                "execution.lease_release_failed",
                job_id=str(job.id),
                worker_id=worker_id,
                error=str(exc),
            )

    async def _is_cancel_requested(self, job: Job) -> bool:
        """Mijoz job'ni bekor qilishni so'raganmi (Redis signali)?

        Redis javob bermasa `False` (fail-open): signalni o'qiy olmaslik
        tugagan bajarishni bekor qilish uchun asos emas — natija allaqachon
        qo'lda.
        """
        try:
            return bool(await self.reliability.is_cancel_requested(job.id))
        except Exception as exc:
            logger.warning(
                "execution.cancel_check_failed",
                job_id=str(job.id),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False

    async def _clear_cancel(self, job: Job) -> None:
        """Bekor qilish signalini o'chiradi (keyingi urinishga ta'sir qilmasligi uchun)."""
        try:
            await self.reliability.clear_cancel(job.id)
        except Exception as exc:
            logger.warning(
                "execution.cancel_clear_failed",
                job_id=str(job.id),
                error=str(exc),
                error_type=type(exc).__name__,
            )

    async def _fail_quietly(
        self,
        job: Job,
        execution: Execution,
        error: ExecutionError,
    ) -> None:
        """Bekor qilish yo'lida yakunlash: xatolar yutiladi, `shield` bilan.

        `asyncio.CancelledError` yo'lidagi har qanday `await` darhol
        uzilishi mumkin, shuning uchun yakunlash `shield` ichida bajariladi
        — aks holda job `RUNNING` holatida qolib ketardi. Yangi xato ham
        yutiladi: u asl `CancelledError`ni yashirib qo'ygan bo'lardi.
        """
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.shield(self.fail(job, execution, error))

    async def _record_execution_usage(
        self,
        job: Job,
        result: ExecutionResult,
        *,
        success: bool,
    ) -> None:
        """Bajarish vaqtini oylik hisobga qo'shadi (best-effort).

        Job allaqachon commit qilingan: hisobni yozib bo'lmasa natija
        qaytarilmaydi. Xato `ERROR` darajasida log qilinadi — hisob-kitob
        uchun kuzatilishi kerak.
        """
        seconds = max(0.0, result.duration_ms / 1000.0)
        try:
            await self.billing.record_execution(job.user_id, seconds, success=success)
            await self.session.commit()
        except Exception as exc:
            with contextlib.suppress(Exception):
                await self.session.rollback()
            logger.error(
                "execution.usage_record_failed",
                job_id=str(job.id),
                user_id=str(job.user_id),
                seconds=seconds,
                error=str(exc),
            )

    async def _dispatch(self, job: Job, event: WebhookEvent) -> None:
        """Mos webhook'larga yetkazish yozuvlarini yaratadi (best-effort).

        Job holati allaqachon commit qilingan, shuning uchun webhook
        muammosi job'ni buzmaydi. Yozuvlar yaratilgan bo'lsa commit
        qilinadi, xato bo'lsa sessiya `rollback` bilan tozalanadi.
        """
        try:
            created = await self.webhooks.dispatch(job, event)
            if created:
                await self.session.commit()
        except Exception as exc:
            with contextlib.suppress(Exception):
                await self.session.rollback()
            # DIQQAT (structlog): maydon `webhook_event` deb nomlangan,
            # `event` EMAS. `event` — bound logger metodining BIRINCHI
            # pozitsion parametri nomi, shuning uchun `logger.warning("...",
            # event=...)` `TypeError: got multiple values for argument
            # 'event'` beradi. Bu xato ayni shu `except` blokida yuzaga
            # kelib, asl webhook xatosini yashirib qo'yardi.
            logger.warning(
                "execution.webhook_dispatch_failed",
                job_id=str(job.id),
                webhook_event=WebhookEvent(event).value,
                error=str(exc),
            )

    def __repr__(self) -> str:  # pragma: no cover - debug yordamchisi
        return f"<ExecutionService sandbox={self.sandbox!r}>"


__all__ = [
    "LOG_EVENT_TYPE",
    "LOG_FLUSH_BATCH_SIZE",
    "LOG_FLUSH_INTERVAL_SECONDS",
    "LOG_POLL_INTERVAL_SECONDS",
    "ExecutionService",
]
