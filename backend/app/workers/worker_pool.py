"""Durabl — worker pool (bitta protsessda bir nechta worker).

Bitta `Worker` nusxasi har doim BITTA job bajaradi: navbatdan oladi,
sandbox'ni kutadi, yozadi. Job'lar ko'pincha I/O kutadi (konteyner
ishlayapti), shuning uchun bitta protsessda `settings.WORKER_CONCURRENCY` ta
worker'ni parallel yuritish protsessor va xotira jihatidan ancha arzon —
har biri uchun alohida Python protsessi ko'tarishdan ko'ra.

Har bir worker'ga BARQAROR identifikator beriladi:
`f"{settings.worker_id}-{i}"`. Barqarorlik muhim, chunki `processing`
ro'yxati `worker_id` bo'yicha ajratiladi: pool qayta ko'tarilganda AYNI
identifikatorli worker `requeue_stale()` bilan o'z job'larini qaytaradi.

**Nazorat (supervision).** `asyncio.TaskGroup` strukturaviy konkurentlikni
beradi: chiqishda hamma vazifa yakunlanishi KAFOLATLANADI va "orphan task"
qolmaydi. Ammo `TaskGroup` ichidagi xato BARCHA aka-uka vazifalarni bekor
qiladi — bu bizga yaramaydi, chunki bitta worker qulasa qolganlari ishlashi
kerak. Shuning uchun har bir worker `_supervise()` korpusiga o'rab
qo'yilgan: u xatoni USHLAB qoladi, log qiladi va worker'ni qayta ishga
tushiradi (`MAX_RESTARTS` gacha). Shu tufayli `TaskGroup` hech qachon xato
ko'rmaydi va faqat o'z vazifasini — tartibli yopilishni — bajaradi.

Chegaradan oshgan qayta ishga tushirish BUTUN pool'ni to'xtatadi: worker
muntazam qulayotgan bo'lsa muammo kodda yoki muhitda, va cheksiz qayta
ko'tarish faqat loglarni to'ldiradi. Protsess chiqadi, orkestrator (Docker
`restart: unless-stopped`, Kubernetes) uni toza holatda qayta ko'taradi.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Final

from app.config import settings
from app.constants import WorkerState
from app.database import session_scope
from app.logging_config import get_logger
from app.services.reliability_service import ReliabilityService
from app.workers.runner import PeriodicWorker, main_entry
from app.workers.worker import Worker

logger = get_logger(__name__)

#: Bitta worker shuncha marta qayta ishga tushiriladi, keyin pool to'xtaydi.
MAX_RESTARTS: Final[int] = 5

#: Qayta ishga tushirishdan oldin kutish (soniya) — qattiq halqadan himoya.
RESTART_DELAY_SECONDS: Final[float] = 1.0

#: Pool nazorat sikli (soniya) — worker'lar holatini tekshirish davriyligi.
SUPERVISION_INTERVAL_SECONDS: Final[float] = 5.0


class WorkerPool(PeriodicWorker):
    """`settings.WORKER_CONCURRENCY` ta `Worker` ni boshqaradigan pool.

    `PeriodicWorker` dan voris: signal, graceful shutdown va xatoga
    chidamli halqa AYNI mexanizmdan keladi. `tick()` bu yerda "nazorat
    sikli" — worker'lar holatini tekshiradi va hammasi tugagan bo'lsa
    pool'ni to'xtatadi.

    Args:
        concurrency: Worker'lar soni. `None` — `settings.WORKER_CONCURRENCY`.
    """

    name = "worker_pool"
    exclusive = False

    def __init__(self, concurrency: int | None = None) -> None:
        super().__init__()
        self.interval_seconds = SUPERVISION_INTERVAL_SECONDS
        self.concurrency = max(
            1,
            int(settings.WORKER_CONCURRENCY if concurrency is None else concurrency),
        )
        self._workers: dict[int, Worker] = {}
        self._restarts: dict[int, int] = {}
        self._tasks: dict[int, asyncio.Task[None]] = {}
        self._group: asyncio.TaskGroup | None = None
        self._stack: contextlib.AsyncExitStack | None = None

    # ------------------------------------------------------------------
    # Hayot sikli
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        """`TaskGroup` ni ochadi va worker nazoratchilarini ishga tushiradi.

        `AsyncExitStack` kerak, chunki `TaskGroup` konteksti `setup()` da
        ochilib `teardown()` da yopiladi — ya'ni `async with` bitta
        funksiya ichiga sig'maydi.
        """
        self._stack = contextlib.AsyncExitStack()
        await self._stack.__aenter__()
        self._group = await self._stack.enter_async_context(asyncio.TaskGroup())

        for index in range(self.concurrency):
            self._restarts[index] = 0
            self._tasks[index] = self._group.create_task(
                self._supervise(index),
                name=f"durabl-worker-{index}",
            )

        logger.info(
            "worker_pool.started",
            concurrency=self.concurrency,
            base_worker_id=settings.worker_id,
        )

    async def tick(self) -> None:
        """Nazorat sikli: barcha nazoratchi tugagan bo'lsa pool to'xtaydi.

        Qayta ishga tushirishning O'ZI `_supervise()` ichida — u ancha
        aniqroq, chunki worker'ning chiqish sababini to'g'ridan-to'g'ri
        ko'radi. Bu yerda faqat "ish qoldimi" nazorati.
        """
        alive = [index for index, task in self._tasks.items() if not task.done()]
        if alive:
            logger.debug(
                "worker_pool.supervision",
                alive=len(alive),
                concurrency=self.concurrency,
                restarts=sum(self._restarts.values()),
            )
            return

        logger.info("worker_pool.drained", note="barcha worker'lar tugadi")
        self.request_stop()

    async def teardown(self) -> None:
        """Barcha worker'ni parallel to'xtatadi va yakunini kutadi.

        `request_stop()` har bir worker'ga graceful to'xtash beradi (joriy
        job `WORKER_SHUTDOWN_GRACE_SECONDS` gacha tugatiladi), keyin
        `TaskGroup.__aexit__` hamma vazifa tugashini kutadi.
        """
        for worker in self._workers.values():
            worker.request_stop()
        logger.info(
            "worker_pool.stopping",
            workers=len(self._workers),
            jobs_processed=self.jobs_processed,
        )

        stack = self._stack
        self._stack = None
        self._group = None
        if stack is None:
            return

        try:
            await stack.aclose()
        except Exception as exc:
            logger.exception(
                "worker_pool.teardown_error",
                error=str(exc),
                error_type=type(exc).__name__,
            )

        await self._unregister_all()
        logger.info(
            "worker_pool.stopped",
            jobs_processed=self.jobs_processed,
            restarts=sum(self._restarts.values()),
        )

    # ------------------------------------------------------------------
    # Worker nazorati
    # ------------------------------------------------------------------

    async def _supervise(self, index: int) -> None:
        """Bitta worker'ni kuzatadi: qulasa qayta ishga tushiradi.

        Bu korpus HECH QACHON xato tashlamaydi (`CancelledError` dan
        tashqari) — aks holda `TaskGroup` qolgan worker'larni bekor qilib
        yuborardi.
        """
        worker_id = self.worker_id_for(index)

        while not self.is_stopping:
            worker = Worker(worker_id, concurrency=self.concurrency)
            self._workers[index] = worker

            try:
                await worker.run()
            except asyncio.CancelledError:
                logger.info(
                    "worker_pool.worker_cancelled",
                    worker_id=worker_id,
                    slot=index,
                )
                raise
            except Exception as exc:
                if not await self._handle_crash(index, worker_id, exc):
                    return
                continue

            logger.info(
                "worker_pool.worker_exited",
                worker_id=worker_id,
                slot=index,
                jobs_processed=worker.jobs_processed,
            )
            return

    async def _handle_crash(self, index: int, worker_id: str, exc: Exception) -> bool:
        """Qulagan worker uchun qaror: qayta ishga tushirish yoki pool'ni to'xtatish.

        Returns:
            `True` — qayta ishga tushiriladi; `False` — chegara tugadi.
        """
        self._restarts[index] = self._restarts.get(index, 0) + 1
        attempts = self._restarts[index]

        logger.exception(
            "worker_pool.worker_crashed",
            worker_id=worker_id,
            slot=index,
            restarts=attempts,
            max_restarts=MAX_RESTARTS,
            error=str(exc),
            error_type=type(exc).__name__,
        )

        if attempts > MAX_RESTARTS:
            logger.error(
                "worker_pool.restart_limit_reached",
                worker_id=worker_id,
                slot=index,
                restarts=attempts,
                note="pool to'xtatiladi, orkestrator protsessni qayta ko'taradi",
            )
            self.request_stop()
            return False

        await self._wait(RESTART_DELAY_SECONDS)
        if self.is_stopping:
            return False

        logger.warning(
            "worker_pool.worker_restarting",
            worker_id=worker_id,
            slot=index,
            attempt=attempts,
        )
        return True

    async def _unregister_all(self) -> None:
        """Pool to'xtaganda reestrda qolgan yozuvlarni tozalaydi.

        `Worker.run()` o'zini reestrdan o'chiradi, lekin qulagan worker
        (`CancelledError` yoki `SIGKILL` bilan uzilgan) buni ulgurmagan
        bo'lishi mumkin — admin panelida "o'lik" yozuv qolib ketardi.
        """
        worker_ids = [worker.worker_id for worker in self._workers.values()]
        if not worker_ids:
            return
        try:
            async with session_scope() as session:
                reliability = ReliabilityService(session)
                for worker_id in worker_ids:
                    await reliability.unregister_worker(worker_id)
        except Exception as exc:
            logger.warning(
                "worker_pool.unregister_failed",
                workers=len(worker_ids),
                error=str(exc),
            )

    # ------------------------------------------------------------------
    # Diagnostika
    # ------------------------------------------------------------------

    @staticmethod
    def worker_id_for(index: int) -> str:
        """Slot uchun barqaror worker identifikatori."""
        return f"{settings.worker_id}-{index}"

    @property
    def workers(self) -> list[Worker]:
        """Hozirgi worker nusxalari (slot tartibida)."""
        return [self._workers[index] for index in sorted(self._workers)]

    @property
    def jobs_processed(self) -> int:
        """Pool bajargan job'larning umumiy soni."""
        return sum(worker.jobs_processed for worker in self._workers.values())

    @property
    def restarts(self) -> int:
        """Qayta ishga tushirishlarning umumiy soni."""
        return sum(self._restarts.values())

    @property
    def state(self) -> WorkerState:
        """Pool'ning umumiy holati (admin diagnostikasi uchun)."""
        if self.is_stopping:
            return WorkerState.DRAINING
        if not self._workers:
            return WorkerState.STARTING
        return WorkerState.BUSY if self.jobs_processed else WorkerState.IDLE


async def main() -> None:
    """Pool'ni ishga tushiradi (`python -m app.workers.worker_pool`)."""
    await WorkerPool().run()


if __name__ == "__main__":  # pragma: no cover - protsess kirish nuqtasi
    main_entry(WorkerPool)


__all__ = [
    "MAX_RESTARTS",
    "RESTART_DELAY_SECONDS",
    "SUPERVISION_INTERVAL_SECONDS",
    "WorkerPool",
    "main",
]
