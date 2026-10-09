"""Durabl — job bajaruvchi asosiy worker.

Bu modul Durabl'ning "ishchi qo'li": navbatdan job oladi, uni sandbox'da
bajaradi va natijani DB'ga yozadi. Barcha biznes mantiq service qatlamida,
shuning uchun bu fayl FAQAT ketma-ketlik va ishonchlilik qoidalari haqida.

Halqaning bir aylanishi:

    dequeue -> get_internal -> acquire_lease -> Heartbeat -> execute_job -> ack

**`ack` ENG OXIRIDA.** Navbat "reliable queue" namunasida ishlaydi:
`dequeue()` job'ni navbatdan olib worker'ning `processing` ro'yxatiga
ATOMAR ko'chiradi. Agar `ack` ishni boshlashdan oldin qilinsa va worker
shu lahzada qulasa (OOM, `SIGKILL`, server o'chdi), job Redis'da ham,
hech kimning qo'lida ham qolmasdi. `ack` oxirida bo'lgani uchun job
`processing` ro'yxatida qoladi va `requeue_stale()` uni qaytaradi.

**Ishga tushganda `requeue_stale(worker_id)`.** Ayni `worker_id` bilan
qayta ko'tarilgan worker (Kubernetes'dagi StatefulSet, `WORKER_ID`
sozlamasi) avvalgi nusxasidan qolgan job'larni DARHOL navbatga qaytaradi —
`reap_expired_leases()` ni kutib o'tirmaydi.

**Ikki marta bajarishdan himoya — uch qatlam:**

1. `acquire_lease()` — `SET NX`, ya'ni bitta job'ni ikki worker olmaydi.
   Olmagan worker job'ni `ack` qilib o'tadi (navbatda dublikat bo'lsa).
2. `Heartbeat` — lease boshqa worker'ga o'tsa `on_lease_lost` orqali joriy
   bajarish vazifasi `cancel()` qilinadi. Davom etish = kodni ikki marta
   bajarish.
3. `job.status.is_terminal` tekshiruvi — allaqachon tugagan job qayta
   bajarilmaydi (navbatdagi qoldiq a'zo xavfsiz).

**Graceful shutdown.** `SIGTERM` kelganda yangi job OLINMAYDI, lekin joriy
job `settings.WORKER_SHUTDOWN_GRACE_SECONDS` gacha tugatishga imkon oladi.
Vaqt yetmasa bajarish vazifasi bekor qilinadi — `execute_job()` bunda
job'ni `CANCELLED` qilib yozadi, ya'ni job "jim" yo'qolmaydi.
"""

from __future__ import annotations

import asyncio
import signal
import socket
import uuid
from typing import Any, Final

from app.config import settings
from app.constants import JobStatus, Priority, WorkerState
from app.database import session_scope
from app.exceptions import JobNotFoundError, QueueError
from app.logging_config import (
    bind_request_context,
    clear_request_context,
    get_logger,
    setup_logging,
)
from app.models.job import Job
from app.services.execution_service import ExecutionService
from app.services.job_service import JobService
from app.services.queue_service import QueueService
from app.services.reliability_service import ReliabilityService
from app.workers.heartbeat import Heartbeat
from app.workers.runner import STOP_SIGNALS, main_entry

logger = get_logger(__name__)

#: `process_one()` ning "navbat bo'sh" holatidagi javobi.
QUEUE_EMPTY: Final[bool] = False

#: `WORKER_POLL_TIMEOUT_SECONDS = 0` bo'lganda bo'sh navbatdan keyingi pauza.
#:
#: Nol kutish vaqtida `dequeue()` BLOKLANMAYDI (oddiy `LMOVE`), ya'ni halqa
#: navbat bo'sh paytda protsessorni to'liq yoqib aylanardi. Qisqa pauza shuni
#: oldini oladi va to'xtatish signaliga sezgir (`_pause` ishlatiladi).
IDLE_PAUSE_SECONDS: Final[float] = 0.05


class Worker:
    """Navbatdan job olib bajaradigan worker.

    Args:
        worker_id: Worker identifikatori. `None` — `settings.worker_id`
            (`WORKER_ID` sozlamasi yoki `hostname-pid`).
        concurrency: Shu worker reestrda ko'rsatadigan bir vaqtdalik.
            BITTA `Worker` nusxasi har doim BITTA job bajaradi (parallelizm
            `WorkerPool` ning vazifasi) — bu qiymat faqat admin paneli uchun
            ma'lumot.
    """

    def __init__(self, worker_id: str | None = None, *, concurrency: int = 1) -> None:
        self.worker_id = worker_id or settings.worker_id
        self.concurrency = max(1, int(concurrency))
        self._stop_event = asyncio.Event()
        self._queue: QueueService | None = None
        self._execution_task: asyncio.Task[Job] | None = None
        self._grace_task: asyncio.Task[None] | None = None
        self._jobs_processed = 0
        self._installed_signals: list[signal.Signals] = []

    # ------------------------------------------------------------------
    # Holat
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """Log va `SupportsRun` protokoli uchun nom."""
        return f"worker:{self.worker_id}"

    @property
    def is_stopping(self) -> bool:
        """To'xtatish so'ralganmi."""
        return self._stop_event.is_set()

    @property
    def jobs_processed(self) -> int:
        """Shu nusxa bajargan job'lar soni."""
        return self._jobs_processed

    @property
    def queue(self) -> QueueService:
        """Navbat servisi (ilk murojaatda yasaladi).

        Dangasa yasalishi muhim: worker obyekti `set_redis()` dan OLDIN
        yasalgan bo'lishi mumkin (testlarda aynan shunday).
        """
        if self._queue is None:
            self._queue = QueueService()
        return self._queue

    def request_stop(self) -> None:
        """Graceful to'xtashni so'raydi.

        Joriy job bajarilayotgan bo'lsa unga `WORKER_SHUTDOWN_GRACE_SECONDS`
        beriladi; vaqt yetmasa bajarish vazifasi bekor qilinadi.
        """
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        logger.info(
            "worker.stopping",
            worker_id=self.worker_id,
            grace_seconds=settings.WORKER_SHUTDOWN_GRACE_SECONDS,
            jobs_processed=self._jobs_processed,
        )

        task = self._execution_task
        if task is not None and not task.done():
            self._grace_task = asyncio.create_task(self._enforce_grace(task))

    # ------------------------------------------------------------------
    # Asosiy halqa
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Worker'ning to'liq hayot sikli.

        `unregister_worker()` `finally` da: worker qanday chiqsa ham
        (signal, xato, bekor qilish) reestrda "o'lik" yozuv qolmasligi
        kerak, aks holda admin paneli mavjud bo'lmagan worker'ni ko'rsatardi.
        """
        setup_logging()
        bind_request_context(worker=self.name, worker_id=self.worker_id)
        self._install_signal_handlers()

        await self._register()
        try:
            recovered = await self._recover_stale()
            logger.info(
                "worker.started",
                worker_id=self.worker_id,
                concurrency=self.concurrency,
                poll_timeout_seconds=settings.WORKER_POLL_TIMEOUT_SECONDS,
                recovered_jobs=recovered,
            )
            while not self._stop_event.is_set():
                claimed = await self.process_one()
                if not claimed and settings.WORKER_POLL_TIMEOUT_SECONDS <= 0:
                    await self._pause(IDLE_PAUSE_SECONDS)
        finally:
            await self._cancel_grace_task()
            await self._unregister()
            self._remove_signal_handlers()
            logger.info(
                "worker.stopped",
                worker_id=self.worker_id,
                jobs_processed=self._jobs_processed,
            )
            clear_request_context()

    # ASYNC109 bu yerda qo'llanmaydi: `timeout` mijoz tomoni kutishi EMAS —
    # u to'g'ridan-to'g'ri `QueueService.dequeue()` ga, u yerdan Redis'ning
    # `BLMOVE` buyrug'iga SERVER tomoni kutish vaqti sifatida uzatiladi.
    # `asyncio.timeout()` bilan almashtirish bloklanib turgan Redis ulanishini
    # yarim yo'lda qoldiradi va keyingi buyruq javobini buzadi. Imzo
    # `docs/CONTRACTS.md` da kelishilgan.
    async def process_one(self, timeout: int | None = None) -> bool:  # noqa: ASYNC109
        """Navbatdan BITTA job oladi va to'liq bajaradi.

        Testlar uchun qulay kirish nuqtasi: halqa, signal va reestrdan
        mustaqil ishlaydi.

        `ack` `finally` da — job navbatning `processing` ro'yxatida
        "muallaq" qolmasligi uchun. Kutilmagan xato bo'lsa job DB'da
        `queued`/`running` holatida qoladi va `SchedulerWorker` ning
        yo'qolgan job'larni tiklash qadami uni qayta navbatga qo'yadi
        (oxirgi himoya chizig'i).

        Args:
            timeout: Navbatni kutish vaqti (soniya). `None` —
                `settings.WORKER_POLL_TIMEOUT_SECONDS`.

        Returns:
            `True` — job navbatdan olindi (bajarildi yoki o'tkazib
            yuborildi); `False` — navbat bo'sh edi.
        """
        job_id = await self._dequeue(timeout)
        if job_id is None:
            return QUEUE_EMPTY

        try:
            await self._process(job_id)
        finally:
            await self._ack(job_id)
        return True

    # ------------------------------------------------------------------
    # Bitta job'ni bajarish
    # ------------------------------------------------------------------

    async def _process(self, job_id: str) -> None:
        """Job'ni lease olib bajaradi (bitta tranzaksiya konteksti).

        `session_scope()` chiqishda commit qiladi, lekin service'lar o'z
        yakuniy holatlarini allaqachon commit qilgan bo'ladi — bu yerdagi
        commit faqat qoldiq o'zgarishlar uchun.
        """
        bind_request_context(job_id=job_id)
        try:
            async with session_scope() as session:
                reliability = ReliabilityService(session)
                job = await self._load(session, job_id)
                if job is None:
                    return
                if not await self._claim(reliability, job):
                    return
                await self._execute(session, reliability, job)
        finally:
            bind_request_context(worker=self.name, worker_id=self.worker_id)

    async def _load(self, session: Any, job_id: str) -> Job | None:
        """Job'ni DB'dan o'qiydi; bajarish kerak bo'lmasa `None`.

        Ikki holatda `None` qaytadi va job `ack` qilinadi:

        * job DB'da yo'q — navbatdagi yetim a'zo (DB tozalangan yoki
          job o'chirilgan), uni abadiy aylantirib yurishning ma'nosi yo'q;
        * job allaqachon YAKUNIY holatda — dublikat a'zo yoki boshqa worker
          ulgurgan; qayta bajarish Durabl kafolatini buzardi.
        """
        job_service = JobService(session)
        try:
            job = await job_service.get_internal(job_id)
        except JobNotFoundError:
            logger.warning(
                "worker.job_skipped",
                job_id=job_id,
                worker_id=self.worker_id,
                reason="not_found",
            )
            return None

        if JobStatus(job.status).is_terminal:
            logger.info(
                "worker.job_skipped",
                job_id=job_id,
                worker_id=self.worker_id,
                reason="already_terminal",
                status=JobStatus(job.status).value,
            )
            return None
        return job

    async def _claim(self, reliability: ReliabilityService, job: Job) -> bool:
        """Job uchun lease olishga urinadi.

        `False` — boshqa worker lease'ni ushlab turibdi. Bunda job `ack`
        qilinadi: a'zo navbatda dublikat bo'lgan, haqiqiy egasi esa ishni
        davom ettirmoqda.
        """
        acquired = await reliability.acquire_lease(job.id, self.worker_id)
        if not acquired:
            holder = await self._lease_holder(reliability, job.id)
            logger.info(
                "worker.job_skipped",
                job_id=str(job.id),
                worker_id=self.worker_id,
                reason="lease_not_acquired",
                lease_holder=holder,
            )
            return False

        logger.info(
            "worker.job_claimed",
            job_id=str(job.id),
            worker_id=self.worker_id,
            status=JobStatus(job.status).value,
            priority=Priority(job.priority).value,
            attempt=job.attempts_used,
            correlation_id=job.correlation_id,
        )
        return True

    async def _execute(
        self,
        session: Any,
        reliability: ReliabilityService,
        job: Job,
    ) -> None:
        """Job'ni heartbeat ostida bajaradi va lease'ni bo'shatadi."""
        execution_service = ExecutionService(session)
        job_id = job.id

        task: asyncio.Task[Job] | None = None

        async def _on_lease_lost() -> None:
            """Lease yo'qoldi — bajarishni DARHOL to'xtatamiz."""
            if task is not None and not task.done():
                task.cancel()

        async def _on_cancel() -> None:
            """Mijoz bekor qildi — bajarishni to'xtatamiz."""
            logger.info(
                "worker.job_cancelling",
                job_id=str(job_id),
                worker_id=self.worker_id,
            )
            if task is not None and not task.done():
                task.cancel()

        heartbeat = Heartbeat(
            reliability,
            on_lease_lost=_on_lease_lost,
            on_cancel=_on_cancel,
        )
        try:
            async with heartbeat:
                await heartbeat.start(job_id, self.worker_id)
                task = asyncio.create_task(
                    execution_service.execute_job(job, self.worker_id)
                )
                self._execution_task = task
                finished = await self._await_execution(task, job_id)

            if finished is None:
                # Bajarish uzildi (lease yo'qoldi, bekor qilindi yoki grace
                # tugadi). `execute_job()` job'ni DB'da yopib qo'ygan,
                # shuning uchun halqa keyingi job'ga o'tadi.
                return

            self._jobs_processed += 1
            logger.info(
                "worker.job_done",
                job_id=str(job_id),
                worker_id=self.worker_id,
                status=JobStatus(finished.status).value,
                duration_ms=finished.duration_ms,
                attempt=finished.attempts_used,
                lease_lost=heartbeat.lease_lost,
                jobs_processed=self._jobs_processed,
            )
        finally:
            self._execution_task = None
            await self._finish(reliability, job_id)

    async def _await_execution(
        self,
        task: asyncio.Task[Job],
        job_id: uuid.UUID,
    ) -> Job | None:
        """Bajarish vazifasini kutadi; uzilsa `None` qaytaradi.

        Bekor qilish IKKI manbadan keladi va ularni AJRATISH shart:

        * **ichki vazifa** bekor qilindi (lease yo'qoldi, mijoz bekor qildi,
          grace tugadi) — bu oddiy ish oqimi, worker halqasi DAVOM ETADI.
          `execute_job()` job'ni `CANCELLED` deb yozib qo'ygan, ya'ni job
          yo'qolmaydi. Shuning uchun `None` qaytariladi.
        * **worker'ning O'ZI** bekor qilindi (ikkinchi `SIGTERM`, `TaskGroup`
          uzdi) — bunda xato qayta tashlanishi SHART, aks holda graceful
          shutdown zanjiri uzilib, protsess to'xtamay qolardi.

        Ikkisi `Task.cancelling()` bilan ajratiladi: bu hisoblagich FAQAT
        joriy vazifaga `cancel()` qilinganda noldan katta bo'ladi.
        """
        outer = asyncio.current_task()
        try:
            return await task
        except asyncio.CancelledError:
            logger.warning(
                "worker.job_aborted",
                job_id=str(job_id),
                worker_id=self.worker_id,
                reason="lease yo'qoldi yoki bekor qilindi",
            )
            if outer is not None and outer.cancelling() > 0:
                raise
            return None

    async def _finish(self, reliability: ReliabilityService, job_id: uuid.UUID) -> None:
        """Lease'ni bo'shatadi va worker'ni `IDLE` deb belgilaydi."""
        try:
            await reliability.release_lease(job_id, self.worker_id)
        except Exception as exc:
            logger.warning(
                "worker.release_lease_failed",
                job_id=str(job_id),
                worker_id=self.worker_id,
                error=str(exc),
            )
        await self._mark_idle()

    # ------------------------------------------------------------------
    # Navbat bilan ishlash
    # ------------------------------------------------------------------

    async def _dequeue(self, timeout: int | None) -> str | None:  # noqa: ASYNC109
        """Navbatdan `job_id` oladi; to'xtash so'ralgan bo'lsa olmaydi."""
        if self._stop_event.is_set():
            return None

        poll = settings.WORKER_POLL_TIMEOUT_SECONDS if timeout is None else timeout
        try:
            return await self.queue.dequeue(self.worker_id, timeout=poll)
        except QueueError as exc:
            logger.error(
                "worker.dequeue_failed",
                worker_id=self.worker_id,
                error=str(exc),
            )
            # Redis javob bermaydi — qattiq halqaga tushib qolmaslik uchun
            # intervalga teng kutamiz (to'xtatish signaliga sezgir).
            await self._pause(max(1.0, float(poll or 1)))
            return None

    async def _ack(self, job_id: str) -> None:
        """Job'ni `processing` ro'yxatidan o'chiradi (ish TUGAGANDAN keyin)."""
        try:
            await self.queue.ack(self.worker_id, job_id)
        except QueueError as exc:
            logger.error(
                "worker.ack_failed",
                job_id=job_id,
                worker_id=self.worker_id,
                error=str(exc),
                note="job processing ro'yxatida qoldi, requeue_stale() qaytaradi",
            )

    async def _recover_stale(self) -> int:
        """Avvalgi nusxadan qolgan job'larni navbatga qaytaradi."""
        try:
            recovered = await self.queue.requeue_stale(self.worker_id)
        except QueueError as exc:
            logger.error(
                "worker.requeue_stale_failed",
                worker_id=self.worker_id,
                error=str(exc),
            )
            return 0

        if recovered:
            logger.warning(
                "worker.stale_requeued",
                worker_id=self.worker_id,
                recovered=recovered,
            )
        return recovered

    # ------------------------------------------------------------------
    # Worker reestri
    # ------------------------------------------------------------------

    async def _register(self) -> None:
        """Worker'ni reestrga yozadi (xato halqani boshlashga to'sqinlik qilmaydi)."""
        try:
            async with session_scope() as session:
                await ReliabilityService(session).register_worker(
                    self.worker_id,
                    state=WorkerState.STARTING,
                    concurrency=self.concurrency,
                    hostname=socket.gethostname(),
                )
        except Exception as exc:
            logger.warning(
                "worker.register_failed",
                worker_id=self.worker_id,
                error=str(exc),
                note="worker baribir ishlaydi, admin panelida ko'rinmaydi",
            )

    async def _unregister(self) -> None:
        """Worker'ni reestrdan o'chiradi (graceful shutdown)."""
        try:
            async with session_scope() as session:
                await ReliabilityService(session).unregister_worker(self.worker_id)
        except Exception as exc:
            logger.warning(
                "worker.unregister_failed",
                worker_id=self.worker_id,
                error=str(exc),
            )

    async def _mark_idle(self) -> None:
        """Reestrda holatni `IDLE` qiladi va joriy job'ni tozalaydi."""
        state = WorkerState.DRAINING if self._stop_event.is_set() else WorkerState.IDLE
        try:
            async with session_scope() as session:
                await ReliabilityService(session).heartbeat_worker(
                    self.worker_id,
                    state=state,
                    current_job_id=None,
                    jobs_processed=self._jobs_processed,
                )
        except Exception as exc:
            logger.debug(
                "worker.idle_heartbeat_failed",
                worker_id=self.worker_id,
                error=str(exc),
            )

    @staticmethod
    async def _lease_holder(
        reliability: ReliabilityService,
        job_id: uuid.UUID,
    ) -> str | None:
        """Lease egasini o'qiydi (faqat log uchun — xato yutiladi)."""
        try:
            return await reliability.lease_holder(job_id)
        except Exception:
            return None

    # ------------------------------------------------------------------
    # To'xtatish mexanikasi
    # ------------------------------------------------------------------

    async def _enforce_grace(self, task: asyncio.Task[Job]) -> None:
        """Joriy job'ga belgilangan vaqt beradi, keyin bekor qiladi.

        `asyncio.wait` vazifani O'ZI bekor qilmaydi (`wait_for` dan farqli),
        shuning uchun muddat tugaganda bekor qilish ochiq bajariladi.
        """
        grace = max(0.0, float(settings.WORKER_SHUTDOWN_GRACE_SECONDS))
        done, _pending = await asyncio.wait({task}, timeout=grace)
        if done:
            return
        logger.warning(
            "worker.grace_expired",
            worker_id=self.worker_id,
            grace_seconds=grace,
            note="joriy job bekor qilinadi",
        )
        task.cancel()

    async def _cancel_grace_task(self) -> None:
        """Grace kuzatuvchisini to'xtatadi (halqa tugagandan keyin kerak emas)."""
        task = self._grace_task
        self._grace_task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            # Kutilgan holat: grace kuzatuvchisini O'ZIMIZ bekor qildik.
            pass

    async def _pause(self, delay: float) -> None:
        """To'xtatish signaliga sezgir kutish."""
        if self._stop_event.is_set() or delay <= 0:
            return
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
        except TimeoutError:
            return

    def _install_signal_handlers(self) -> None:
        """`SIGTERM`/`SIGINT` ni graceful to'xtashga bog'laydi."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover
            return
        for sig in STOP_SIGNALS:
            try:
                loop.add_signal_handler(sig, self._on_signal, sig)
            except (NotImplementedError, RuntimeError, ValueError):
                continue
            self._installed_signals.append(sig)

    def _remove_signal_handlers(self) -> None:
        """Handler'larni olib tashlaydi (protsessda keyingi worker uchun)."""
        if not self._installed_signals:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover
            self._installed_signals.clear()
            return
        for sig in self._installed_signals:
            try:
                loop.remove_signal_handler(sig)
            except (NotImplementedError, RuntimeError, ValueError):  # pragma: no cover
                continue
        self._installed_signals.clear()

    def _on_signal(self, sig: signal.Signals) -> None:
        """Birinchi signal — graceful; ikkinchisi — joriy job'ni darhol uzadi."""
        if self._stop_event.is_set():
            logger.warning(
                "worker.force_stop",
                worker_id=self.worker_id,
                signal=sig.name,
            )
            task = self._execution_task
            if task is not None and not task.done():
                task.cancel()
            return
        logger.info("worker.signal_received", worker_id=self.worker_id, signal=sig.name)
        self.request_stop()

    def __repr__(self) -> str:  # pragma: no cover - diagnostika yordamchisi
        return (
            f"Worker(worker_id={self.worker_id!r}, "
            f"jobs_processed={self._jobs_processed}, stopping={self.is_stopping})"
        )


async def main() -> None:
    """Bitta worker'ni ishga tushiradi (`python -m app.workers.worker`)."""
    await Worker().run()


if __name__ == "__main__":  # pragma: no cover - protsess kirish nuqtasi
    main_entry(Worker)


__all__ = ["IDLE_PAUSE_SECONDS", "QUEUE_EMPTY", "Worker", "main"]
