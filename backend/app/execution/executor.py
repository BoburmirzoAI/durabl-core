"""Durabl — bajarish yadrosining koordinatori.

`Executor` — bajarish qatlamining YAGONA kirish nuqtasi. U uch narsani
bir-biriga ulaydi:

    SandboxSpec ──▶ Executor.execute()
                      ├── get_runtime(spec.runtime)   -> qaysi til
                      ├── runner (SandboxManager | LocalRunner) -> qaysi muhit
                      ├── TimeoutGuard                -> vaqt nazorati
                      └── ResultCollector             -> loglar + tasniflash
                                                         ▼
                                                   ExecutionResult

**Eng muhim shartnoma:** `execute()` bajarish xatolarini TASHLAMAYDI — har
doim `ExecutionResult` qaytaradi (yagona istisno: `asyncio.CancelledError`,
u strukturaviy bekor qilish signali bo'lgani uchun o'tkazib yuboriladi).

Nega shunday? Retry yoki DLQ qarorini `reliability_service` qabul qiladi va u
buning uchun TO'LIQ ma'lumot talab qiladi: qancha vaqt ketdi, qanday loglar
yig'ildi, xotira cho'qqisi qancha bo'ldi. Agar executor xato tashlasa, bu
ma'lumotlar yo'qolar edi. Natijani `ExecutionError`ga aylantirish —
`execution_service` ning vazifasi.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime

from app.config import settings
from app.constants import FailureReason, LogStream
from app.exceptions import ExecutionError, ExecutionTimeoutError
from app.execution.http_runner import HttpRunner, HttpRuntime
from app.execution.result_collector import ResultCollector
from app.execution.runtime_base import (
    BaseRuntime,
    LogSink,
    SandboxRunner,
    get_runtime,
)
from app.execution.timeout_guard import TimeoutGuard
from app.execution.types import ExecutionResult, RunnerOutcome, SandboxSpec
from app.logging_config import get_logger
from app.metrics import observe_job_duration_ms, track_execution
from app.utils.time_utils import duration_ms, utcnow

logger = get_logger(__name__)


class _LogFanout:
    """Log bo'laklarini `ResultCollector`ga va tashqi callback'ga uzatadi.

    Tashqi callback (real-time WebSocket/Redis Pub/Sub) xato tashlasa bajarish
    BUZILMAYDI: xato yutib yuboriladi va bir marta log qilinadi. Mijoz kodining
    bajarilishi tashqi kuzatuvchining ishlashiga bog'liq bo'lmasligi kerak.
    """

    __slots__ = ("_collector", "_failures", "_on_log")

    def __init__(self, collector: ResultCollector, on_log: LogSink | None) -> None:
        self._collector = collector
        self._on_log = on_log
        self._failures = 0

    def __call__(self, stream: LogStream, chunk: str) -> None:
        self._collector.feed(stream, chunk)
        if self._on_log is None:
            return
        try:
            self._on_log(stream, chunk)
        except Exception as exc:
            self._failures += 1
            if self._failures == 1:
                logger.warning(
                    "execution.log_callback_failed",
                    error=str(exc),
                    error_type=type(exc).__name__,
                )

    @property
    def failures(self) -> int:
        """Tashqi callback necha marta xato tashladi."""
        return self._failures


class Executor:
    """Job'ni bajaradigan asosiy koordinator.

    Args:
        runner: Bajarish muhiti. `None` bo'lsa sozlamaga qarab BIRINCHI
            ishlatilganda tanlanadi (`default_runner()`). Ochiq berish testlar
            va maxsus holatlar uchun (soxta runner bilan sinash).
    """

    __slots__ = ("_runner",)

    def __init__(self, runner: SandboxRunner | None = None) -> None:
        self._runner = runner

    # ------------------------------------------------------------------
    # Runner tanlash
    # ------------------------------------------------------------------

    @staticmethod
    def default_runner() -> SandboxRunner:
        """Sozlamaga mos runner yasaydi.

        `SANDBOX_ENABLED=True` -> `SandboxManager` (gVisor/Docker konteyner),
        aks holda `LocalRunner` (lokal subprocess, FAQAT development/test).

        Import funksiya ICHIDA: bajarish qatlamining og'ir bog'liqliklari
        (`docker` SDK) faqat haqiqatan kerak bo'lganda yuklanadi va aylanma
        import yuzaga kelmaydi.
        """
        if settings.SANDBOX_ENABLED:
            from app.execution.sandbox_manager import SandboxManager

            return SandboxManager()

        from app.execution.local_runner import LocalRunner

        return LocalRunner()

    @property
    def runner(self) -> SandboxRunner:
        """Joriy runner (birinchi murojaatda tanlanadi va keshlanadi)."""
        if self._runner is None:
            self._runner = self.default_runner()
        return self._runner

    # ------------------------------------------------------------------
    # Holat tekshiruvlari
    # ------------------------------------------------------------------

    async def available(self) -> bool:
        """Bajarish muhiti ishlashga tayyormi (`/ready` tekshiruvi uchun).

        Xato tashlamaydi — tekshiruvning o'zi qulasa `False` qaytadi.
        """
        try:
            return await self.runner.available()
        except Exception as exc:
            logger.warning(
                "execution.runner_unavailable",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False

    async def cleanup_orphans(self) -> int:
        """Qolib ketgan konteyner/jarayonlarni tozalaydi; sonini qaytaradi."""
        try:
            removed = await self.runner.cleanup_orphans()
        except Exception as exc:
            logger.warning(
                "execution.cleanup_failed",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return 0
        if removed:
            logger.info("execution.orphans_cleaned", removed=removed)
        return removed

    # ------------------------------------------------------------------
    # Asosiy bajarish
    # ------------------------------------------------------------------

    async def execute(
        self,
        spec: SandboxSpec,
        *,
        on_log: LogSink | None = None,
    ) -> ExecutionResult:
        """Kodni bajaradi va to'liq natijani qaytaradi.

        Args:
            spec: Bajarish topshirig'i (kod, muhit, limitlar).
            on_log: Real-time log callback'i. Har bo'lak uchun
                `on_log(stream, chunk)` chaqiriladi. Xato tashlasa yutib
                yuboriladi — bajarish buzilmaydi.

        Returns:
            Har doim `ExecutionResult` (xato holatida ham — `status` va
            `failure_reason` sababni ko'rsatadi).

        Raises:
            asyncio.CancelledError: Bajarish tashqaridan bekor qilindi
                (worker to'xtayapti yoki job cancel qilindi). Bunda runner
                o'ldiriladi, natija log qilinadi va xato qayta tashlanadi.
            UnsupportedRuntimeError: `spec.runtime` qo'llab-quvvatlanmaydi.
                Bu VALIDATSIYA xatosi (bajarish hatto boshlanmaydi), shuning
                uchun natijaga aylantirilmaydi.
        """
        # HTTP job bajarish uchun kod emas, MIJOZNING ENDPOINTI chaqiriladi.
        # Shu sababli runtime va runner boshqa, lekin undan keyingi butun
        # zanjir (TimeoutGuard, ResultCollector, log fanout, `_finish`)
        # AYNI — ishonchlilik mantig'i ikki martalab yozilmaydi.
        #
        # `HttpRunner` har bajarish uchun YANGI yasaladi (`self.runner`
        # keshlanmaydi): u ketayotgan so'rov vazifasini o'zida saqlaydi va
        # `kill()` aynan o'shani bekor qilishi kerak.
        runtime: BaseRuntime = HttpRuntime() if spec.is_http else get_runtime(spec.runtime)
        collector = ResultCollector(limits=spec.limits)
        sink = _LogFanout(collector, on_log)
        start = utcnow()

        logger.info(
            "execution.started",
            job_id=spec.job_id,
            kind=spec.kind.value,
            # HTTP job'da "runtime" ma'nosiz (`HttpRuntime` uni `python`
            # deb ko'rsatadi) — shuning uchun `kind` yonida turadi.
            runtime=runtime.runtime.value,
            attempt=spec.attempt_number,
            correlation_id=spec.correlation_id or None,
            timeout_seconds=spec.timeout_seconds,
            memory_mb=spec.limits.memory_mb,
            sandbox_enabled=settings.SANDBOX_ENABLED,
            target_host=_target_host(spec),
        )

        try:
            runner: SandboxRunner = HttpRunner() if spec.is_http else self.runner
        except Exception as exc:
            logger.error(
                "execution.runner_init_failed",
                job_id=spec.job_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return self._finish(
                spec,
                runtime,
                collector,
                RunnerOutcome(infra_error=f"Runner yuklanmadi: {exc}"),
                start=start,
                fanout=sink,
            )

        partial: RunnerOutcome | None = None
        try:
            async with TimeoutGuard(spec.timeout_seconds, on_timeout=runner.kill):
                partial = await runner.run(spec, runtime, sink)
                outcome = partial

        except ExecutionTimeoutError:
            # Qismiy natija (loglar, exit_code) saqlanadi — faqat belgi qo'yiladi.
            outcome = replace(partial or RunnerOutcome(), timed_out=True)
            collector.feed_system(
                f"Vaqt limiti ({spec.timeout_seconds}s) oshdi — bajarish majburan to'xtatildi"
            )

        except asyncio.CancelledError:
            await self._kill_quietly(runner, spec)
            collector.feed_system("Bajarish bekor qilindi")
            cancelled = collector.build(
                partial or RunnerOutcome(),
                runtime,
                duration_ms=duration_ms(start),
                cancelled=True,
            )
            self._record(spec, runtime, cancelled, fanout=sink)
            raise

        except ExecutionError as exc:
            # Runner domen xatosini xom natijaga aylantiramiz — tasniflashni
            # `ResultCollector` bajaradi (yagona joy, yagona mantiq).
            logger.warning(
                "execution.runner_error",
                job_id=spec.job_id,
                code=exc.code,
                failure_reason=exc.failure_reason.value,
                error=exc.message,
            )
            outcome = self._outcome_from_error(partial or RunnerOutcome(), exc)
            collector.feed_system(exc.message)

        except Exception as exc:
            logger.exception(
                "execution.unexpected_error",
                job_id=spec.job_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            outcome = replace(
                partial or RunnerOutcome(),
                infra_error=f"{type(exc).__name__}: {exc}",
            )

        return self._finish(spec, runtime, collector, outcome, start=start, fanout=sink)

    # ------------------------------------------------------------------
    # Ichki yordamchilar
    # ------------------------------------------------------------------

    def _finish(
        self,
        spec: SandboxSpec,
        runtime: BaseRuntime,
        collector: ResultCollector,
        outcome: RunnerOutcome,
        *,
        start: datetime,
        fanout: _LogFanout | None = None,
    ) -> ExecutionResult:
        """Natijani yasaydi, metrika va yakuniy strukturaviy log yozadi."""
        result = collector.build(outcome, runtime, duration_ms=duration_ms(start))
        self._record(spec, runtime, result, fanout=fanout)
        return result

    @staticmethod
    def _record(
        spec: SandboxSpec,
        runtime: BaseRuntime,
        result: ExecutionResult,
        *,
        fanout: _LogFanout | None,
    ) -> None:
        """Metrikalar va yakuniy log yozuvi."""
        track_execution(result.status, runtime.runtime)
        observe_job_duration_ms(result.duration_ms)

        write = logger.info if result.is_success else logger.warning
        write(
            "execution.finished",
            job_id=spec.job_id,
            runtime=runtime.runtime.value,
            attempt=spec.attempt_number,
            correlation_id=spec.correlation_id or None,
            status=result.status.value,
            exit_code=result.exit_code,
            failure_reason=result.failure_reason.value if result.failure_reason else None,
            duration_ms=result.duration_ms,
            stdout_bytes=result.stdout_bytes,
            stderr_bytes=result.stderr_bytes,
            log_entries=len(result.logs),
            truncated=result.truncated,
            sandbox_id=result.sandbox_id,
            log_callback_failures=fanout.failures if fanout is not None else 0,
        )

    @staticmethod
    def _outcome_from_error(base: RunnerOutcome, exc: ExecutionError) -> RunnerOutcome:
        """Runner tashlagan `ExecutionError`ni xom `RunnerOutcome`ga o'giradi."""
        reason = exc.failure_reason
        if reason is FailureReason.TIMEOUT:
            return replace(base, timed_out=True)
        if reason is FailureReason.OOM:
            return replace(base, oom_killed=True)
        if reason is FailureReason.NON_ZERO_EXIT:
            exit_code = exc.exit_code if exc.exit_code is not None else base.exit_code
            return replace(base, exit_code=exit_code if exit_code is not None else 1)
        return replace(base, infra_error=exc.message)

    @staticmethod
    async def _kill_quietly(runner: SandboxRunner, spec: SandboxSpec) -> None:
        """Bekor qilishda runner'ni o'ldiradi; xatoni log'ga yozib yutib yuboradi.

        Bekor qilish yo'lida yangi xato ko'tarilishi asl `CancelledError`ni
        yashirib qo'yadi, shuning uchun hamma narsa yutiladi.
        """
        try:
            await runner.kill()
        except (Exception, asyncio.CancelledError) as exc:
            logger.warning(
                "execution.kill_failed",
                job_id=spec.job_id,
                error=str(exc),
                error_type=type(exc).__name__,
            )

    def __repr__(self) -> str:  # pragma: no cover - debug yordamchisi
        runner = type(self._runner).__name__ if self._runner is not None else "lazy"
        return f"<Executor runner={runner}>"


def default_executor() -> Executor:
    """Sozlamaga mos standart `Executor` nusxasi (`execution_service` uchun)."""
    return Executor()


def _target_host(spec: SandboxSpec) -> str | None:
    """HTTP job'ning maqsad HOSTINI qaytaradi (log uchun).

    To'liq URL ATAYLAB log qilinmaydi: query qismida token yoki imzo
    bo'lishi mumkin. `kind=CODE` uchun `None`.
    """
    if not spec.is_http or not spec.target_url:
        return None
    from urllib.parse import urlparse

    return urlparse(spec.target_url).hostname


__all__ = [
    "Executor",
    "default_executor",
]
