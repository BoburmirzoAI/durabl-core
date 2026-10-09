"""Durabl — fon worker'larining umumiy bazaviy halqasi.

Durabl'da to'rtta DAVRIY worker bor: `scheduler`, `dlq_processor`,
`webhook_sender` va `worker_pool`. Ularning ishi turlicha, lekin HAYOT SIKLI
bir xil:

    setup_logging() -> signal handler -> [lock -> tick -> lock bo'shat] -> ...
    -> teardown() -> close_db() -> close_redis()

Shu takrorlanishni bir joyda ushlab turish uchun `PeriodicWorker` bazaviy
klassi yozilgan. Voris klass faqat `tick()` ni (bir siklning ishini) yozadi,
qolgan hammasi — signal, taqsimlangan lock, xatoga chidamlilik, tez
to'xtash — shu modulda.

**Nega `asyncio.sleep` emas?** Oddiy `sleep(interval)` bilan `SIGTERM`
kelganda worker siklning oxirigacha kutib turadi: 30 soniyalik interval
Kubernetes'ning `terminationGracePeriod` iga urilib, pod `SIGKILL` bilan
o'ladi. Shuning uchun halqa `asyncio.wait_for(stop_event.wait(), interval)`
bilan kutadi — to'xtatish signali kelsa kutish DARHOL uziladi.

**Nega xato halqani to'xtatmaydi?** `tick()` DB yoki Redis bilan ishlaydi va
ular vaqtincha javob bermasligi mumkin. Worker shu sababli o'lsa, qayta
ko'tarilishni orkestratorga qoldirardi va "job yo'qolmaydi" kafolati
orkestrator sozlamasiga bog'lanib qolardi. Shuning uchun xato log qilinadi va
sikl davom etadi. Ammo ketma-ket xatolar ko'paysa interval ikki barobar
oshadi (`MAX_BACKOFF_INTERVAL` gacha) — "xato bo'roni" paytida qulagan
DB/Redis'ni soniyada bir marta urib turish uni tiklanishga qo'ymaydi.

**Taqsimlangan lock.** `exclusive = True` bo'lgan worker (scheduler,
dlq_processor) bir vaqtda BITTA nusxada ishlashi kerak: ikki scheduler
`promote_due()` ni parallel chaqirsa ham job ikki marta navbatga tushmaydi
(Lua atomar), lekin cron nusxalari IKKI marta yaratilib qolardi. Lock
`SET NX EX` bilan olinadi va `tick()` davomida fon vazifasi uni Lua bilan
(EGASI tekshirilib) uzaytirib turadi — uzoq `tick()` o'z lock'ini yo'qotib,
boshqa nusxani ishga qo'yib yubormaydi. Bo'shatish ham Lua bilan: oddiy `DEL`
muddati tugab boshqa nusxaga o'tgan lock'ni o'chirib yuborardi.
"""

from __future__ import annotations

import asyncio
import signal
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, Final, Protocol

from redis.asyncio import Redis
from redis.exceptions import RedisError, ResponseError

from app.constants import RedisKeys
from app.database import close_db
from app.logging_config import (
    bind_request_context,
    clear_request_context,
    get_logger,
    setup_logging,
)
from app.redis_client import close_redis, get_redis

logger = get_logger(__name__)

#: Ketma-ket shuncha xatodan keyin interval ikki barobar oshadi.
ERROR_BACKOFF_THRESHOLD: Final[int] = 10

#: Xatoga qarab oshirilgan intervalning yuqori chegarasi (soniya).
MAX_BACKOFF_INTERVAL: Final[float] = 60.0

#: Interval qanchalik kichik bo'lsa ham shundan past tushmaydi (busy-wait'dan himoya).
MIN_INTERVAL: Final[float] = 0.01

#: Lock TTL'ining qancha qismi o'tganda uzaytirish urinishi bo'ladi.
LOCK_RENEW_RATIO: Final[float] = 1 / 3

#: Lock'ni EGASI tekshirilib uzaytiradi (atomar "check-and-expire").
LOCK_EXTEND_LUA: Final[str] = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""

#: Lock'ni EGASI tekshirilib o'chiradi (atomar "check-and-delete").
LOCK_RELEASE_LUA: Final[str] = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
end
return 0
"""

#: To'xtatish signallari — ikkinchi marta kelsa darhol chiqiladi.
STOP_SIGNALS: Final[tuple[signal.Signals, ...]] = (signal.SIGTERM, signal.SIGINT)


class SupportsRun(Protocol):
    """Mustaqil protsess sifatida ishga tushirilishi mumkin bo'lgan worker.

    `PeriodicWorker` ham, davriy BO'LMAGAN `Worker` (job bajaruvchi) ham shu
    shaklga mos — shuning uchun `run_worker()`/`main_entry()` ikkisi bilan
    ham ishlaydi.
    """

    @property
    def name(self) -> str:
        """Log va lock nomi."""
        ...

    async def run(self) -> None:
        """Worker'ni to'xtatish signaliga qadar olib boradi."""
        ...

    def request_stop(self) -> None:
        """Graceful to'xtashni so'raydi (halqadan chiqish)."""
        ...


class PeriodicWorker(ABC):
    """Davriy ishlaydigan fon worker'ining bazaviy klassi.

    Voris klass `name`, `interval_seconds` ni e'lon qiladi va `tick()` ni
    yozadi. `setup()`/`teardown()` ixtiyoriy.

    Klass atributlari:
        name: Worker nomi (log maydoni va lock kaliti).
        interval_seconds: Ikki sikl orasidagi kutish (soniya).
        exclusive: `True` — butun klasterda bitta nusxa ishlaydi (lock).
        lock_ttl: Taqsimlangan lock muddati (soniya).
        close_resources: Halqa tugaganda umumiy DB/Redis ulanishlari
            yopilsinmi. Mustaqil protsessda `True` (standart). Testda va
            worker boshqa worker ichida ishlayotganda `False` qilinadi —
            aks holda protsessdagi BOSHQA worker'larning ulanishi uzilardi.
    """

    name: str = "periodic"
    interval_seconds: float = 1.0
    exclusive: bool = False
    lock_ttl: int = 30
    close_resources: bool = True

    def __init__(self) -> None:
        self._stop_event = asyncio.Event()
        self._consecutive_errors = 0
        self._cycles = 0
        self._lock_token = uuid.uuid4().hex
        self._lock_held = False
        self._main_task: asyncio.Task[Any] | None = None
        self._installed_signals: list[signal.Signals] = []
        self._redis: Redis | None = None

    # ------------------------------------------------------------------
    # Voris klass uchun kengaytirish nuqtalari
    # ------------------------------------------------------------------

    async def setup(self) -> None:
        """Halqa boshlanishidan oldin bir marta chaqiriladi (ixtiyoriy)."""
        return None

    @abstractmethod
    async def tick(self) -> None:
        """Bitta siklning ishi.

        Xato tashlashi MUMKIN: halqa to'xtamaydi, xato log qilinadi va
        keyingi siklda davom etiladi.
        """

    async def teardown(self) -> None:
        """Halqa tugagandan keyin bir marta chaqiriladi (ixtiyoriy)."""
        return None

    # ------------------------------------------------------------------
    # Holat
    # ------------------------------------------------------------------

    @property
    def is_stopping(self) -> bool:
        """To'xtatish so'ralganmi."""
        return self._stop_event.is_set()

    @property
    def cycles(self) -> int:
        """Bajarilgan sikllar soni (o'tkazib yuborilganlari ham)."""
        return self._cycles

    @property
    def consecutive_errors(self) -> int:
        """Ketma-ket xatolar soni (interval oshishi shunga bog'liq)."""
        return self._consecutive_errors

    def request_stop(self) -> None:
        """Graceful to'xtashni so'raydi — halqa joriy sikldan keyin chiqadi.

        `asyncio.Event` tufayli kutib turgan halqa DARHOL uyg'onadi
        (intervalning oxirigacha kutmaydi).
        """
        if not self._stop_event.is_set():
            logger.info("worker.stopping", worker=self.name)
        self._stop_event.set()

    # ------------------------------------------------------------------
    # Asosiy halqa
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Worker'ning to'liq hayot sikli.

        Tartib: logging -> signal handler -> `setup()` -> halqa ->
        `teardown()` -> DB/Redis yopilishi. `setup()` xato bersa halqa
        boshlanmaydi, lekin `teardown()` va resurs yopilishi BARIBIR
        bajariladi (yarim ochilgan resurs qolib ketmaydi).
        """
        setup_logging()
        bind_request_context(worker=self.name)
        self._main_task = asyncio.current_task()
        self._install_signal_handlers()

        logger.info(
            "worker.started",
            worker=self.name,
            interval_seconds=self.interval_seconds,
            exclusive=self.exclusive,
        )
        try:
            await self.setup()
            await self._loop()
        finally:
            await self._shutdown()

    async def _loop(self) -> None:
        """Sikl halqasi: `tick()` + stop-ga sezgir kutish."""
        while not self._stop_event.is_set():
            self._cycles += 1
            await self._cycle()
            if self._stop_event.is_set():
                break
            await self._wait(self._current_interval())

    async def _cycle(self) -> None:
        """Bitta sikl: `exclusive` bo'lsa lock olib, keyin `tick()`."""
        if not self.exclusive:
            await self._tick_guarded()
            return

        if not await self._acquire_lock():
            logger.debug(
                "worker.cycle_skipped",
                worker=self.name,
                reason="lock_held_by_other",
            )
            return

        renewer = asyncio.create_task(self._renew_lock_forever())
        try:
            await self._tick_guarded()
        finally:
            renewer.cancel()
            try:
                await renewer
            except asyncio.CancelledError:
                # Kutilgan holat: uzaytiruvchini O'ZIMIZ bekor qildik.
                pass
            await self._release_lock()

    async def _tick_guarded(self) -> None:
        """`tick()` ni xato to'sig'i ichida chaqiradi.

        `asyncio.CancelledError` qayta tashlanadi: u "xato" emas, balki
        to'xtatish buyrug'i va uni yutib yuborish graceful shutdown zanjirini
        buzadi.
        """
        try:
            await self.tick()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._consecutive_errors += 1
            logger.exception(
                "worker.tick_failed",
                worker=self.name,
                cycle=self._cycles,
                consecutive_errors=self._consecutive_errors,
                error=str(exc),
                error_type=type(exc).__name__,
                next_interval_seconds=self._current_interval(),
            )
            return

        if self._consecutive_errors:
            logger.info(
                "worker.tick_recovered",
                worker=self.name,
                previous_errors=self._consecutive_errors,
            )
        self._consecutive_errors = 0

    def _current_interval(self) -> float:
        """Joriy kutish vaqti — ketma-ket xatolarga qarab oshadi.

        Har `ERROR_BACKOFF_THRESHOLD` xatoda interval ikki barobar oshadi,
        lekin `MAX_BACKOFF_INTERVAL` dan oshmaydi.
        """
        base = max(MIN_INTERVAL, float(self.interval_seconds))
        if self._consecutive_errors < ERROR_BACKOFF_THRESHOLD:
            return base
        steps = min(self._consecutive_errors // ERROR_BACKOFF_THRESHOLD, 16)
        return min(base * float(2**steps), MAX_BACKOFF_INTERVAL)

    async def _wait(self, delay: float) -> None:
        """To'xtatish signaliga sezgir kutish.

        `asyncio.sleep` o'rniga `stop_event.wait()` kutiladi: signal kelsa
        kutish darhol uziladi va worker intervalning oxirini kutib turmaydi.
        """
        if self._stop_event.is_set() or delay <= 0:
            return
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
        except TimeoutError:
            return

    async def _shutdown(self) -> None:
        """Chiqish yo'li: `teardown()` + lock + resurslar + kontekst.

        Har bir qadam alohida himoyalangan — biri yiqilsa qolganlari baribir
        bajariladi, aks holda protsess yarim yopilgan holatda qolardi.
        """
        self._remove_signal_handlers()
        try:
            await self.teardown()
        except Exception as exc:
            logger.exception(
                "worker.teardown_failed",
                worker=self.name,
                error=str(exc),
                error_type=type(exc).__name__,
            )

        if self._lock_held:
            await self._release_lock()

        if self.close_resources:
            await self._close_resources()

        logger.info("worker.stopped", worker=self.name, cycles=self._cycles)
        clear_request_context()

    @staticmethod
    async def _close_resources() -> None:
        """Umumiy DB va Redis ulanishlarini yopadi (protsess egasi uchun)."""
        try:
            await close_db()
        except Exception as exc:
            logger.warning("worker.close_db_failed", error=str(exc))
        try:
            await close_redis()
        except Exception as exc:
            logger.warning("worker.close_redis_failed", error=str(exc))

    # ------------------------------------------------------------------
    # Signallar
    # ------------------------------------------------------------------

    def _install_signal_handlers(self) -> None:
        """`SIGTERM`/`SIGINT` ni hodisa halqasiga bog'laydi.

        `loop.add_signal_handler` ataylab tanlangan: `signal.signal` bilan
        qo'yilgan handler C darajasida ishlaydi va `asyncio.Event` ni xavfsiz
        o'rnata olmaydi. Ba'zi muhitlarda (asosiy bo'lmagan ip, Windows)
        imkoniyat yo'q — bunda worker baribir ishlaydi, faqat signalga
        `request_stop()` bilan javob bermaydi.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - halqa yo'q holat
            return

        for sig in STOP_SIGNALS:
            try:
                loop.add_signal_handler(sig, self._on_signal, sig)
            except (NotImplementedError, RuntimeError, ValueError) as exc:
                logger.debug(
                    "worker.signal_handler_unavailable",
                    worker=self.name,
                    signal=sig.name,
                    error=str(exc),
                )
                continue
            self._installed_signals.append(sig)

    def _remove_signal_handlers(self) -> None:
        """O'rnatilgan handler'larni olib tashlaydi.

        Bitta protsessda ketma-ket bir nechta worker ishga tushsa (testlar,
        `worker_pool`), eski handler yopilgan worker'ning `stop_event` ini
        o'rnatib, yangi worker'ni e'tiborsiz qoldirardi.
        """
        if not self._installed_signals:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # pragma: no cover - halqa allaqachon yopilgan
            self._installed_signals.clear()
            return

        for sig in self._installed_signals:
            try:
                loop.remove_signal_handler(sig)
            except (NotImplementedError, RuntimeError, ValueError):  # pragma: no cover
                continue
        self._installed_signals.clear()

    def _on_signal(self, sig: signal.Signals) -> None:
        """Signal kelganda: birinchi marta graceful, ikkinchi marta darhol."""
        if self._stop_event.is_set():
            logger.warning(
                "worker.force_stop",
                worker=self.name,
                signal=sig.name,
                note="ikkinchi signal — joriy sikl bekor qilinadi",
            )
            task = self._main_task
            if task is not None and not task.done():
                task.cancel()
            return

        logger.info("worker.signal_received", worker=self.name, signal=sig.name)
        self.request_stop()

    # ------------------------------------------------------------------
    # Taqsimlangan lock
    # ------------------------------------------------------------------

    @property
    def redis(self) -> Redis:
        """Redis klienti (ilk murojaatda olinadi).

        Dangasa olinishi muhim: worker obyekti `set_redis()` dan OLDIN
        yasalgan bo'lishi mumkin (testlarda aynan shunday).
        """
        if self._redis is None:
            self._redis = get_redis()
        return self._redis

    @property
    def lock_key(self) -> str:
        """Taqsimlangan lock kaliti (`RedisKeys` dan)."""
        return RedisKeys.lock(self.name)

    async def _acquire_lock(self) -> bool:
        """Lock'ni `SET NX EX` bilan olishga urinadi.

        Redis javob bermasa `False` — bu xavfsiz standart: `exclusive`
        worker yagonalikni tasdiqlay olmasa ishni BOSHLAMAYDI.
        """
        ttl = max(1, int(self.lock_ttl))
        try:
            acquired = await self.redis.set(
                self.lock_key, self._lock_token, nx=True, ex=ttl
            )
        except RedisError as exc:
            logger.warning(
                "worker.lock_error",
                worker=self.name,
                error=str(exc),
                note="sikl o'tkazib yuborildi",
            )
            return False

        self._lock_held = bool(acquired)
        return self._lock_held

    async def _renew_lock_forever(self) -> None:
        """`tick()` davomida lock'ni davriy uzaytirib turadi.

        Uzaytirish muvaffaqiyatsiz bo'lsa (lock allaqachon boshqa nusxada)
        vazifa to'xtaydi: `tick()` ni yarim yo'lda to'xtatish bu yerda
        qilinmaydi — `tick()` lar idempotent yoki atomar amallardan iborat,
        shuning uchun yakunlanishi xavfsizroq.
        """
        ttl = max(1, int(self.lock_ttl))
        delay = max(MIN_INTERVAL, ttl * LOCK_RENEW_RATIO)
        while True:
            await asyncio.sleep(delay)
            if not await self._extend_lock(ttl):
                logger.warning(
                    "worker.lock_renew_failed",
                    worker=self.name,
                    note="lock egasi o'zgargan yoki muddati tugagan",
                )
                return

    async def _extend_lock(self, ttl: int) -> bool:
        """Lock TTL'ini ATOMAR uzaytiradi (egasi tekshirilib)."""
        result = await self._eval_lock(LOCK_EXTEND_LUA, str(ttl))
        if result is not None:
            return bool(result)

        # Lua yo'q muhit — zaxira yo'l: egasini o'qib keyin TTL qo'yamiz.
        try:
            holder = await self.redis.get(self.lock_key)
            if holder is None or str(holder) != self._lock_token:
                return False
            return bool(await self.redis.expire(self.lock_key, ttl))
        except RedisError as exc:
            logger.warning("worker.lock_extend_error", worker=self.name, error=str(exc))
            return False

    async def _release_lock(self) -> None:
        """Lock'ni ATOMAR bo'shatadi (egasi tekshirilib).

        Oddiy `DEL` xavfli: lock muddati tugab boshqa nusxaga o'tgan bo'lsa,
        kechikkan worker YANGI egasining lock'ini o'chirib yuborardi va ikki
        nusxa parallel ishlab ketardi.
        """
        self._lock_held = False
        result = await self._eval_lock(LOCK_RELEASE_LUA)
        if result is not None:
            return

        try:
            holder = await self.redis.get(self.lock_key)
            if holder is not None and str(holder) == self._lock_token:
                await self.redis.delete(self.lock_key)
        except RedisError as exc:
            logger.warning(
                "worker.lock_release_error",
                worker=self.name,
                error=str(exc),
                note="lock TTL bo'yicha o'zi yo'qoladi",
            )

    async def _eval_lock(self, source: str, *args: str) -> int | None:
        """Lock skriptini bajaradi; Lua ishlamasa `None` qaytaradi."""
        try:
            raw = await self.redis.eval(  # type: ignore[no-untyped-call]
                source, 1, self.lock_key, self._lock_token, *args
            )
        except ResponseError as exc:
            logger.debug(
                "worker.lock_lua_unsupported",
                worker=self.name,
                error=str(exc),
            )
            return None
        except RedisError as exc:
            logger.warning("worker.lock_eval_error", worker=self.name, error=str(exc))
            return 0
        return int(raw or 0)


# ---------------------------------------------------------------------------
# Protsess darajasidagi yordamchilar
# ---------------------------------------------------------------------------


async def run_worker(worker: SupportsRun) -> None:
    """Worker'ni oxirigacha olib boradi va xatoni strukturaviy log qiladi.

    `asyncio.CancelledError` yutiladi: u ikkinchi `SIGTERM` dan keladi va
    bunda chiqish KUTILGAN holat, orkestrator uchun xato kodi kerak emas.
    """
    try:
        await worker.run()
    except asyncio.CancelledError:
        logger.warning("worker.cancelled", worker=worker.name)
    except Exception as exc:
        logger.exception(
            "worker.crashed",
            worker=worker.name,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        raise


def main_entry(factory: Callable[[], SupportsRun]) -> None:
    """`python -m app.workers.<modul>` uchun yagona kirish nuqtasi.

    `factory` — worker klassining O'ZI bo'lishi mumkin
    (`main_entry(SchedulerWorker)`), chunki klass ham chaqiriladigan obyekt.

    Args:
        factory: Worker nusxasini yasaydigan chaqiriladigan obyekt.
    """
    setup_logging()
    worker = factory()
    try:
        asyncio.run(run_worker(worker))
    except KeyboardInterrupt:  # pragma: no cover - interaktiv to'xtatish
        logger.info("worker.interrupted", worker=worker.name)


__all__ = [
    "ERROR_BACKOFF_THRESHOLD",
    "LOCK_EXTEND_LUA",
    "LOCK_RELEASE_LUA",
    "LOCK_RENEW_RATIO",
    "MAX_BACKOFF_INTERVAL",
    "MIN_INTERVAL",
    "STOP_SIGNALS",
    "PeriodicWorker",
    "SupportsRun",
    "main_entry",
    "run_worker",
]
