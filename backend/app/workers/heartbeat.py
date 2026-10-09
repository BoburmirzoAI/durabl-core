"""Durabl — job bajarilayotgan paytdagi "tiriklik" signali (heartbeat).

Worker job'ni olganda uning uchun **lease** oladi: Redis'dagi TTL'li kalit
"shu job hozir MENDA" degan ma'noni beradi. Lease TTL'i qisqa
(`settings.LEASE_TTL_SECONDS`, standart 15s) — worker qulasa boshqa worker
job'ni TEZ olishi uchun. Ammo job 900 soniyagacha ishlashi mumkin, shuning
uchun TTL muntazam uzaytirilishi kerak. Ayni shu ish — `Heartbeat`.

Heartbeat ALOHIDA `asyncio` vazifasida ishlaydi, chunki asosiy vazifa
sandbox'ni kutib turadi va o'zi lease'ni uzaytira olmaydi.

Har bir "zarba" (beat) UCH ishni bajaradi:

1. `renew_lease()` — lease TTL'ini uzaytiradi. `False` qaytsa lease
   BOSHQA worker'ga o'tgan: bu holatda job allaqachon qayta bajarilmoqda,
   shuning uchun joriy bajarishni DAVOM ETTIRISH kodni IKKI MARTA
   bajarishga olib keladi. `lease_lost` belgisi qo'yiladi va
   `on_lease_lost()` chaqiriladi (worker bajarish vazifasini `cancel()` qiladi).
2. `heartbeat_worker()` — worker reestridagi yozuvni yangilaydi
   (`state=BUSY`, `current_job_id`). Shu tufayli admin paneli worker
   nima qilayotganini ko'radi, `prune_dead_workers()` esa uni "o'lgan"
   deb hisoblab tashlamaydi.
3. `is_cancel_requested()` — mijoz `POST /jobs/{id}/cancel` qilganmi.
   Bekor qilish KOOPERATIV: signal Redis'da turadi, worker esa shu
   oynada ko'rib `on_cancel()` ni chaqiradi. Shu sxema tufayli bekor
   qilish buyrug'i BOSHQA protsessdan (API) kelishi mumkin.

**DB'ga tegmaydi.** `renew_lease()` ataylab faqat Redis bilan ishlaydi:
bitta `AsyncSession` ni ikki `asyncio` vazifasida parallel ishlatish
SQLAlchemy'da aniqlanmagan xatti-harakat (`MissingGreenlet`,
"concurrent operations"). `executions.lease_expires_at` ni esa
`reap_expired_leases()` o'zi oldinga suradi.

Ishlatilishi (`workers/worker.py`):

    async with Heartbeat(reliability, on_lease_lost=..., on_cancel=...) as hb:
        await hb.start(job.id, worker_id)
        job = await execution_service.execute_job(job, worker_id)
    if hb.lease_lost:
        ...
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from types import TracebackType

from app.config import settings
from app.constants import WorkerState
from app.logging_config import get_logger
from app.services.reliability_service import ReliabilityService

logger = get_logger(__name__)

#: Callback turi — argumentsiz async funksiya.
HeartbeatCallback = Callable[[], Awaitable[None]]


class Heartbeat:
    """Job bajarilayotganda lease'ni uzaytirib turadigan fon vazifasi.

    Args:
        reliability: Lease va worker reestri servisi.
        interval: Zarbalar orasidagi vaqt (soniya). `None` —
            `settings.HEARTBEAT_INTERVAL_SECONDS`.
        on_lease_lost: Lease boshqa worker'ga o'tganda chaqiriladi.
            Worker odatda bu callback'da joriy bajarish vazifasini
            `cancel()` qiladi.
        on_cancel: Mijoz job'ni bekor qilganda chaqiriladi (bir marta).
    """

    __slots__ = (
        "_cancel_requested",
        "_interval",
        "_job_id",
        "_lease_lost",
        "_on_cancel",
        "_on_lease_lost",
        "_stop_event",
        "_task",
        "_worker_id",
        "beats",
        "reliability",
    )

    def __init__(
        self,
        reliability: ReliabilityService,
        *,
        interval: float | None = None,
        on_lease_lost: HeartbeatCallback | None = None,
        on_cancel: HeartbeatCallback | None = None,
    ) -> None:
        self.reliability = reliability
        self._interval = self._resolve_interval(interval)
        self._on_lease_lost = on_lease_lost
        self._on_cancel = on_cancel
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._job_id: uuid.UUID | str | None = None
        self._worker_id: str = ""
        self._lease_lost = False
        self._cancel_requested = False
        self.beats = 0

    # ------------------------------------------------------------------
    # Holat
    # ------------------------------------------------------------------

    @property
    def lease_lost(self) -> bool:
        """Lease boshqa worker'ga o'tdimi (job'ni davom ettirish TAQIQLANADI)."""
        return self._lease_lost

    @property
    def cancel_requested(self) -> bool:
        """Mijoz job'ni bekor qilishni so'radimi."""
        return self._cancel_requested

    @property
    def interval(self) -> float:
        """Zarbalar orasidagi vaqt (soniya)."""
        return self._interval

    @property
    def is_running(self) -> bool:
        """Fon vazifasi hozir ishlab turibdimi."""
        task = self._task
        return task is not None and not task.done()

    # ------------------------------------------------------------------
    # Hayot sikli
    # ------------------------------------------------------------------

    async def start(self, job_id: uuid.UUID | str, worker_id: str) -> None:
        """Fon vazifasini ishga tushiradi.

        Takroriy chaqiruv e'tiborsiz qoldiriladi — bitta `Heartbeat` nusxasi
        bitta job'ga xizmat qiladi.

        Args:
            job_id: Lease uzaytiriladigan job.
            worker_id: Lease egasi.
        """
        if self.is_running:
            logger.debug(
                "heartbeat.already_running",
                job_id=str(job_id),
                worker_id=worker_id,
            )
            return

        self._job_id = job_id
        self._worker_id = worker_id
        self._lease_lost = False
        self._cancel_requested = False
        self._stop_event = asyncio.Event()
        self._task = asyncio.create_task(self._loop())
        logger.debug(
            "heartbeat.started",
            job_id=str(job_id),
            worker_id=worker_id,
            interval_seconds=self._interval,
        )

    async def stop(self) -> None:
        """Fon vazifasini to'xtatadi va yakunini kutadi.

        Kutish MUHIM: kutmasdan chiqsak, vazifa Redis murojaati o'rtasida
        bekor qilinib "Task was destroyed but it is pending" ogohlantirishini
        berardi va keyingi job'ning lease'iga xalaqit qilishi mumkin edi.
        """
        self._stop_event.set()
        task = self._task
        self._task = None
        if task is None:
            return

        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            # Kutilgan holat: vazifani O'ZIMIZ bekor qildik.
            pass
        except Exception as exc:  # pragma: no cover - `_loop` xatolarni yutadi
            logger.warning(
                "heartbeat.stop_error",
                job_id=str(self._job_id),
                error=str(exc),
            )

        logger.debug(
            "heartbeat.stopped",
            job_id=str(self._job_id),
            worker_id=self._worker_id,
            beats=self.beats,
            lease_lost=self._lease_lost,
        )

    async def __aenter__(self) -> Heartbeat:
        """Kontekst menejeri — `start()` ni chaqiruvchi o'zi bajaradi."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Kontekstdan chiqishda fon vazifasi HAR DOIM to'xtatiladi."""
        await self.stop()

    # ------------------------------------------------------------------
    # Ichki halqa
    # ------------------------------------------------------------------

    async def _loop(self) -> None:
        """Davriy zarba halqasi.

        Birinchi zarba `interval` dan KEYIN bo'ladi: lease allaqachon
        `acquire_lease()` da olingan va TTL'i to'liq, shuning uchun darhol
        uzaytirishning ma'nosi yo'q.
        """
        try:
            while not self._stop_event.is_set():
                if not await self._sleep():
                    return
                if not await self._beat():
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - himoya to'sig'i
            logger.exception(
                "heartbeat.loop_error",
                job_id=str(self._job_id),
                worker_id=self._worker_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    async def _sleep(self) -> bool:
        """Intervalni kutadi; `False` — to'xtatish so'ralgan."""
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
        except TimeoutError:
            return True
        return False

    async def _beat(self) -> bool:
        """Bitta zarba. `False` — halqa to'xtashi kerak (lease yo'qoldi)."""
        job_id = self._job_id
        if job_id is None:  # pragma: no cover - `start()` dan oldin bo'lmaydi
            return False

        try:
            alive = await self.reliability.renew_lease(job_id, self._worker_id)
        except Exception as exc:
            # Vaqtinchalik nosozlik job'ni o'ldirmaydi: lease TTL'i hali
            # tugamagan bo'lishi mumkin, keyingi zarbada qayta urinamiz.
            logger.warning(
                "heartbeat.renew_error",
                job_id=str(job_id),
                worker_id=self._worker_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return True

        self.beats += 1

        if not alive:
            self._lease_lost = True
            logger.warning(
                "worker.lease_lost",
                job_id=str(job_id),
                worker_id=self._worker_id,
                beats=self.beats,
            )
            await self._invoke(self._on_lease_lost, "on_lease_lost")
            return False

        await self._touch_registry(job_id)
        await self._check_cancel(job_id)
        return True

    async def _touch_registry(self, job_id: uuid.UUID | str) -> None:
        """Worker reestridagi yozuvni yangilaydi (`BUSY` + joriy job)."""
        try:
            await self.reliability.heartbeat_worker(
                self._worker_id,
                state=WorkerState.BUSY,
                current_job_id=str(job_id),
            )
        except Exception as exc:
            logger.warning(
                "heartbeat.registry_error",
                job_id=str(job_id),
                worker_id=self._worker_id,
                error=str(exc),
            )

    async def _check_cancel(self, job_id: uuid.UUID | str) -> None:
        """Bekor qilish signalini tekshiradi va bir marta xabar beradi."""
        if self._cancel_requested:
            return
        try:
            requested = await self.reliability.is_cancel_requested(job_id)
        except Exception as exc:
            logger.warning(
                "heartbeat.cancel_check_error",
                job_id=str(job_id),
                error=str(exc),
            )
            return

        if not requested:
            return

        self._cancel_requested = True
        logger.info(
            "worker.cancel_requested",
            job_id=str(job_id),
            worker_id=self._worker_id,
        )
        await self._invoke(self._on_cancel, "on_cancel")

    @staticmethod
    async def _invoke(callback: HeartbeatCallback | None, label: str) -> None:
        """Callback'ni xato to'sig'i ichida chaqiradi.

        Callback'dagi xato heartbeat'ni yiqitmasligi kerak: u worker
        mantig'iga tegishli va heartbeat uning to'g'riligi uchun javobgar
        emas.
        """
        if callback is None:
            return
        try:
            await callback()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception(
                "heartbeat.callback_failed",
                callback=label,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    @staticmethod
    def _resolve_interval(interval: float | None) -> float:
        """Intervalni normallashtiradi (noldan katta bo'lishi shart)."""
        candidate = (
            float(settings.HEARTBEAT_INTERVAL_SECONDS) if interval is None else float(interval)
        )
        return max(0.01, candidate)

    def __repr__(self) -> str:  # pragma: no cover - diagnostika yordamchisi
        return (
            f"Heartbeat(job_id={self._job_id!r}, worker_id={self._worker_id!r}, "
            f"beats={self.beats}, lease_lost={self._lease_lost})"
        )


__all__ = ["Heartbeat", "HeartbeatCallback"]
