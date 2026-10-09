"""Durabl — bajarish vaqti limitini nazorat qiluvchi kontekst.

Nega oddiy `asyncio.timeout()` yetarli emas?

`asyncio.timeout()` muddat tugaganda joriy vazifani DARHOL bekor qiladi
(`CancelledError`). Lekin bizda bekor qilishdan OLDIN bajarilishi shart bo'lgan
ish bor: sandbox konteynerini (yoki lokal subprocess'ni) o'ldirish. Aks holda
`runner.run()` ning `finally` bloki bekor qilish shovqini ichida ishlaydi va
konteyner "orphan" bo'lib qolishi mumkin.

Shuning uchun ikki qatlamli himoya:

1. **Nazoratchi vazifa** (watchdog) — `seconds` o'tgach `on_timeout()` ni
   chaqiradi (bu odatda `runner.kill()`). Jarayon o'ldiriladi, `runner.run()`
   esa o'zining normal yo'li bilan qaytadi va qismiy loglarni saqlab qoladi.
2. **Qattiq muddat** — `asyncio.timeout(seconds + grace_seconds)`. Agar
   `on_timeout()` yordam bermasa (masalan Docker demoni javob bermayapti),
   blok majburan bekor qilinadi. Bu qatlamni `asyncio` ning o'zi bajaradi:
   `Task.uncancel()` hisob-kitobi to'g'ri yuritiladi va TASHQI bekor qilish
   (foydalanuvchi job'ni cancel qildi) bizning timeout'imiz bilan aralashmaydi.

Ishlatilishi:

    async with TimeoutGuard(spec.timeout_seconds, on_timeout=runner.kill):
        outcome = await runner.run(spec, runtime, sink)
    # <- vaqt oshgan bo'lsa shu yerda `ExecutionTimeoutError` tashlanadi
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Literal, TypeVar

from app.config import settings
from app.exceptions import ExecutionTimeoutError
from app.logging_config import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

#: `on_timeout` callback turi — argumentsiz korutina.
TimeoutCallback = Callable[[], Awaitable[None]]

#: Fonda tugayotgan nazoratchi vazifalar — vazifa `await` ichida turganda
#: GC uni yig'ib ketmasligi uchun kuchli havola saqlanadi.
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()


class TimeoutGuard:
    """Vaqt limiti nazoratchisi.

    Attributes:
        seconds: Yumshoq muddat — shundan keyin `on_timeout()` chaqiriladi.
        grace_seconds: `on_timeout()` dan keyin jarayonning o'z-o'zidan
            tugashini kutish vaqti. Shu vaqt ham o'tsa blok majburan
            bekor qilinadi.

    Xatolar ustunligi: blok ichida BOSHQA xato yuz bergan bo'lsa, u ustun
    turadi — `ExecutionTimeoutError` bilan o'rab yuborilmaydi. Sababi: asl
    xato (masalan `SandboxStartupError`) diagnostika uchun qimmatliroq, va
    `reliability_service` retry qarorini ayni shu asl sabab bo'yicha qabul
    qiladi.
    """

    __slots__ = (
        "_entered",
        "_frozen_elapsed",
        "_grace_seconds",
        "_killing",
        "_on_timeout",
        "_seconds",
        "_started_at",
        "_timeout_cm",
        "_triggered",
        "_watchdog",
    )

    def __init__(
        self,
        seconds: float,
        *,
        on_timeout: TimeoutCallback | None = None,
        grace_seconds: float | None = None,
    ) -> None:
        self._seconds = max(0.0, float(seconds))
        self._on_timeout = on_timeout
        self._grace_seconds = (
            settings.SANDBOX_KILL_GRACE_SECONDS
            if grace_seconds is None
            else max(0.0, float(grace_seconds))
        )
        self._triggered = False
        self._killing = False
        self._entered = False
        self._started_at: float | None = None
        self._frozen_elapsed: float | None = None
        self._watchdog: asyncio.Task[None] | None = None
        self._timeout_cm: asyncio.Timeout | None = None

    # ------------------------------------------------------------------
    # Xossalar
    # ------------------------------------------------------------------

    @property
    def seconds(self) -> float:
        """Yumshoq muddat (soniya)."""
        return self._seconds

    @property
    def grace_seconds(self) -> float:
        """O'ldirishdan keyin kutiladigan qo'shimcha vaqt (soniya)."""
        return self._grace_seconds

    @property
    def triggered(self) -> bool:
        """Vaqt limiti ishga tushdimi (`on_timeout` chaqirildimi)?"""
        return self._triggered

    @property
    def elapsed_seconds(self) -> float:
        """Blok boshlanganidan beri o'tgan vaqt (chiqilgandan keyin — muzlatilgan)."""
        if self._frozen_elapsed is not None:
            return self._frozen_elapsed
        if self._started_at is None:
            return 0.0
        return time.monotonic() - self._started_at

    @property
    def remaining_seconds(self) -> float:
        """Yumshoq muddatgacha qolgan vaqt (o'tib ketgan bo'lsa `0.0`)."""
        return max(0.0, self._seconds - self.elapsed_seconds)

    # ------------------------------------------------------------------
    # Kontekst protokoli
    # ------------------------------------------------------------------

    async def __aenter__(self) -> TimeoutGuard:
        """Nazoratchi vazifani va qattiq muddatni ishga tushiradi."""
        if self._entered:
            raise RuntimeError("TimeoutGuard qayta ishlatilmaydi — yangi nusxa yasang")
        self._entered = True
        self._started_at = time.monotonic()

        # Qattiq muddat: yumshoq muddat + o'ldirishdan keyingi kutish.
        self._timeout_cm = asyncio.timeout(self._seconds + self._grace_seconds)
        await self._timeout_cm.__aenter__()

        watchdog = asyncio.create_task(
            self._watch(),
            name=f"durabl-timeout-guard-{self._seconds:g}s",
        )
        _BACKGROUND_TASKS.add(watchdog)
        watchdog.add_done_callback(_BACKGROUND_TASKS.discard)
        self._watchdog = watchdog
        return self

    async def __aexit__(self, *exc: object) -> Literal[False]:
        """Nazoratchini to'xtatadi va kerak bo'lsa `ExecutionTimeoutError` tashlaydi.

        Returns:
            Har doim `False` — bu kontekst xatolarni YUTMAYDI. Tur `bool` emas,
            balki `Literal[False]`: shu tufayli tur tekshiruvchi `async with`
            blokidan keyingi kodni to'g'ri tahlil qiladi (blok xatoni yutib
            yuborishi mumkin deb o'ylamaydi).
        """
        exc_value = exc[1] if len(exc) > 1 else None
        body_error = exc_value if isinstance(exc_value, BaseException) else None

        self._stop_watchdog()

        if self._started_at is not None and self._frozen_elapsed is None:
            self._frozen_elapsed = time.monotonic() - self._started_at

        hard_deadline_hit = False
        timeout_cm, self._timeout_cm = self._timeout_cm, None
        if timeout_cm is not None:
            try:
                await timeout_cm.__aexit__(
                    type(body_error) if body_error is not None else None,
                    body_error,
                    body_error.__traceback__ if body_error is not None else None,
                )
            except TimeoutError:
                # Qattiq muddat oshdi: `asyncio` blokni bekor qildi va
                # `CancelledError`ni `TimeoutError`ga aylantirdi.
                hard_deadline_hit = True
                self._triggered = True

        if hard_deadline_hit:
            logger.warning(
                "execution.timeout_hard_deadline",
                timeout_seconds=self._seconds,
                grace_seconds=self._grace_seconds,
                elapsed_seconds=round(self.elapsed_seconds, 3),
            )
            raise ExecutionTimeoutError(self._seconds)

        # Blok ichidagi asl xato har doim ustun turadi.
        if body_error is not None:
            return False

        if self._triggered:
            raise ExecutionTimeoutError(self._seconds)

        return False

    # ------------------------------------------------------------------
    # Ichki mantiq
    # ------------------------------------------------------------------

    async def _watch(self) -> None:
        """Yumshoq muddatni kutadi va `on_timeout()` ni chaqiradi.

        Bu vazifa hech qachon xato tashlamaydi — `on_timeout` ichidagi
        muammo bajarishni buzmasligi kerak (qattiq muddat baribir ishlaydi).
        """
        try:
            await asyncio.sleep(self._seconds)
        except asyncio.CancelledError:
            raise

        self._triggered = True
        logger.warning(
            "execution.timeout_reached",
            timeout_seconds=self._seconds,
            grace_seconds=self._grace_seconds,
        )

        if self._on_timeout is None:
            return

        self._killing = True
        try:
            await self._on_timeout()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # Nazoratchi hech qachon xato tashlamaydi
            logger.warning(
                "execution.timeout_callback_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
        finally:
            self._killing = False

    def _stop_watchdog(self) -> None:
        """Nazoratchi vazifani to'xtatadi (sinxron — `__aexit__` bloklanmaydi).

        `on_timeout()` ishlab turgan paytda vazifa BEKOR QILINMAYDI: o'ldirish
        buyrug'ini yarim yo'lda to'xtatish konteynerni "orphan" qoldirishi
        mumkin. Bunday holda vazifa fonda tugaydi (`_BACKGROUND_TASKS` kuchli
        havola saqlaydi), bu esa `__aexit__` ni kutishga majburlamaydi —
        aks holda qattiq muddat bekor qilishi `__aexit__` ichida portlab,
        timeout `CancelledError`ga aylanib ketar edi.
        """
        task, self._watchdog = self._watchdog, None
        if task is None or task.done() or self._killing:
            return
        task.cancel()

    def __repr__(self) -> str:  # pragma: no cover - debug yordamchisi
        return (
            f"<TimeoutGuard seconds={self._seconds:g} grace={self._grace_seconds:g} "
            f"triggered={self._triggered}>"
        )


async def with_timeout(
    coro: Awaitable[T],
    seconds: float,
    on_timeout: TimeoutCallback | None = None,
    *,
    grace_seconds: float | None = None,
) -> T:
    """Bitta korutinani vaqt limiti bilan bajarish uchun qulay funksiya.

    Args:
        coro: Bajarilishi kerak bo'lgan korutina (yoki `await` qilinadigan obyekt).
        seconds: Yumshoq muddat.
        on_timeout: Muddat tugaganda chaqiriladigan tozalash korutinasi.
        grace_seconds: O'ldirishdan keyingi kutish (sukut bo'yicha sozlamadan).

    Raises:
        ExecutionTimeoutError: Vaqt limiti oshdi.
    """
    async with TimeoutGuard(seconds, on_timeout=on_timeout, grace_seconds=grace_seconds):
        return await coro


__all__ = [
    "TimeoutCallback",
    "TimeoutGuard",
    "with_timeout",
]
