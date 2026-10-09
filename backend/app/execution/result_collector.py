"""Durabl — chiqish oqimlarini yig'ish va yakuniy natijani yasash.

`ResultCollector` ikki vazifani bajaradi:

1. **Yig'ish** — runner `on_log(stream, chunk)` orqali kelgan bo'laklarni
   `stdout`/`stderr` buferlariga qo'shadi va AYNI vaqtda qatorlarga bo'lib
   `LogEntry` ro'yxatini shakllantiradi (real-time log va DB uchun).
2. **Tasniflash** — runner qaytargan XOM `RunnerOutcome` ni `ExecutionStatus` +
   `FailureReason` ga aylantirib `ExecutionResult` yasaydi.

Xotira himoyasi: umumiy chiqish `limits.max_output_bytes` dan oshsa kesiladi,
`truncated` belgisi qo'yiladi va keyingi bo'laklar e'tiborsiz qoldiriladi.
Ya'ni cheksiz `while True: print(...)` sikli worker xotirasini yemaydi.

Chegara BAYTlarda hisoblanadi (UTF-8), chunki DB va tarmoq chegarasi ham
baytlarda — belgi soni bilan hisoblash ko'p baytli matnlarda yetarli emas.
"""

from __future__ import annotations

from app.config import settings
from app.constants import ExecutionStatus, FailureReason, LogStream
from app.execution.runtime_base import BaseRuntime
from app.execution.types import (
    ExecutionResult,
    LogEntry,
    ResourceLimits,
    RunnerOutcome,
)
from app.logging_config import get_logger
from app.utils.serializers import truncate_bytes, truncate_output

logger = get_logger(__name__)

#: Chiqish limiti oshganda log'ga yozilgan yagona xabar.
TRUNCATION_NOTICE = "Chiqish hajmi limitidan oshdi — qolgan qismi kesildi"

#: `error_message` stderr'dan olinganda qancha belgi saqlanadi.
ERROR_TAIL_CHARS = 2000


class ResultCollector:
    """stdout/stderr oqimlarini yig'adi va `ExecutionResult` yasaydi.

    Thread-safe EMAS: bitta bajarish bitta `asyncio` vazifasida yig'iladi,
    shuning uchun qulf kerak emas.

    Args:
        limits: Bajarish resurs cheklovlari (`max_output_bytes` shundan olinadi).
        start_sequence: `LogEntry.sequence` qaysi raqamdan boshlanadi. Qayta
            urinish bitta `execution` ichida davom etsa (`execution_logs` da
            `(execution_id, sequence)` unikal) tartibni davom ettirish uchun.
    """

    __slots__ = (
        "_buffers",
        "_limit_notice_sent",
        "_limit_reached",
        "_limits",
        "_logs",
        "_pending",
        "_sequence",
        "_total_bytes",
        "_truncated",
    )

    def __init__(self, *, limits: ResourceLimits, start_sequence: int = 0) -> None:
        self._limits = limits
        self._sequence = max(0, int(start_sequence))
        self._logs: list[LogEntry] = []
        self._buffers: dict[LogStream, list[str]] = {
            LogStream.STDOUT: [],
            LogStream.STDERR: [],
        }
        self._pending: dict[LogStream, str] = {
            LogStream.STDOUT: "",
            LogStream.STDERR: "",
            LogStream.SYSTEM: "",
        }
        self._total_bytes = 0
        self._truncated = False
        self._limit_reached = False
        self._limit_notice_sent = False

    # ------------------------------------------------------------------
    # Oqimlarni yig'ish
    # ------------------------------------------------------------------

    def feed(self, stream: LogStream, chunk: str) -> None:
        """Runner'dan kelgan bo'lakni qabul qiladi (`LogSink` imzosi).

        `SYSTEM` oqimi chiqish limitiga hisoblanmaydi — u Durabl'ning o'z
        xabari, mijoz kodi hajmiga aloqasi yo'q.
        """
        if not chunk:
            return

        if stream not in self._buffers:
            # SYSTEM (yoki kutilmagan) oqim — faqat log yozuvi bo'lib qoladi.
            self._emit_lines(stream, chunk)
            return

        if self._limit_reached:
            return  # Xotira himoyasi: limit oshgan, boshqa yig'maymiz.

        accepted = chunk
        remaining = self._limits.max_output_bytes - self._total_bytes
        chunk_bytes = len(chunk.encode("utf-8", errors="replace"))

        if chunk_bytes > remaining:
            accepted, _ = truncate_bytes(chunk, max(0, remaining))
            self._truncated = True
            self._limit_reached = True

        if accepted:
            self._buffers[stream].append(accepted)
            self._total_bytes += len(accepted.encode("utf-8", errors="replace"))
            self._emit_lines(stream, accepted)

        if self._limit_reached:
            self._flush_stream(stream)
            if not self._limit_notice_sent:
                self._limit_notice_sent = True
                self.feed_system(TRUNCATION_NOTICE)

    def feed_system(self, message: str) -> None:
        """Durabl'ning o'z xabarini log'ga qo'shadi (timeout, lease yo'qoldi...).

        Bu xabar `stdout`/`stderr` ga TUSHMAYDI — mijoz kodi chiqishi toza
        qoladi, xabar esa log oqimida `SYSTEM` belgisi bilan ko'rinadi.
        """
        if not message:
            return
        self._emit_lines(LogStream.SYSTEM, message if message.endswith("\n") else f"{message}\n")

    def flush(self) -> None:
        """Barcha oqimlardagi to'liq bo'lmagan oxirgi qatorlarni log'ga chiqaradi."""
        for stream in tuple(self._pending):
            self._flush_stream(stream)

    # ------------------------------------------------------------------
    # Xossalar
    # ------------------------------------------------------------------

    @property
    def stdout(self) -> str:
        """Yig'ilgan stdout (kesilgan bo'lishi mumkin)."""
        return "".join(self._buffers[LogStream.STDOUT])

    @property
    def stderr(self) -> str:
        """Yig'ilgan stderr (kesilgan bo'lishi mumkin)."""
        return "".join(self._buffers[LogStream.STDERR])

    @property
    def logs(self) -> list[LogEntry]:
        """Yig'ilgan log yozuvlari (nusxa — tashqi kod ro'yxatni buzmasligi uchun)."""
        return list(self._logs)

    @property
    def truncated(self) -> bool:
        """Chiqish kesildimi?"""
        return self._truncated

    @property
    def total_bytes(self) -> int:
        """Qabul qilingan stdout + stderr hajmi (bayt)."""
        return self._total_bytes

    @property
    def limit_reached(self) -> bool:
        """`max_output_bytes` chegarasi urildimi (keyingi bo'laklar tashlanadi)?"""
        return self._limit_reached

    @property
    def next_sequence(self) -> int:
        """Keyingi `LogEntry.sequence` qiymati."""
        return self._sequence

    # ------------------------------------------------------------------
    # Yakuniy natija
    # ------------------------------------------------------------------

    def build(
        self,
        outcome: RunnerOutcome,
        runtime: BaseRuntime,
        *,
        duration_ms: int,
        cancelled: bool = False,
    ) -> ExecutionResult:
        """XOM runner natijasini to'liq `ExecutionResult`ga aylantiradi.

        Tasniflash tartibi QAT'IY (yuqoridagi shart ustun turadi):

        1. `cancelled` -> `CANCELLED`
        2. `timed_out` -> `TIMEOUT` + `TIMEOUT`
        3. `oom_killed` -> `FAILED` + `OOM`
        4. `infra_error` -> `FAILED` + `SANDBOX_ERROR`
        5. chiqish limiti oshgan VA natija qaytmagan -> `FAILED` + `OUTPUT_TOO_LARGE`
        6. `runner_payload.ok` va `exit_code == 0` -> `SUCCESS`
        7. aks holda -> `FAILED` + `runtime.classify_failure(...)`

        Args:
            outcome: Runner qaytargan xom natija.
            runtime: Xatoni tilga xos tasniflash uchun (`classify_failure`).
            duration_ms: Bajarishning to'liq davomiyligi (executor hisoblaydi).
            cancelled: Bajarish tashqaridan bekor qilindimi.
        """
        self.flush()

        payload = outcome.runner_payload
        stdout, stdout_cut = truncate_output(self.stdout)
        stderr, stderr_cut = truncate_output(self.stderr)
        truncated = self._truncated or stdout_cut or stderr_cut or payload.truncated

        exit_code = outcome.exit_code if outcome.exit_code is not None else payload.exit_code

        status, failure_reason, error_message = self._classify(
            outcome,
            runtime,
            cancelled=cancelled,
            exit_code=exit_code,
            stderr=stderr,
        )

        return ExecutionResult(
            status=status,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            result=payload.result if status is ExecutionStatus.SUCCESS else None,
            duration_ms=duration_ms,
            logs=list(self._logs),
            failure_reason=failure_reason,
            error_message=error_message,
            traceback=payload.traceback,
            memory_peak_mb=outcome.memory_peak_mb,
            truncated=truncated,
            sandbox_id=outcome.sandbox_id,
        )

    # ------------------------------------------------------------------
    # Ichki mantiq — tasniflash
    # ------------------------------------------------------------------

    def _classify(
        self,
        outcome: RunnerOutcome,
        runtime: BaseRuntime,
        *,
        cancelled: bool,
        exit_code: int | None,
        stderr: str,
    ) -> tuple[ExecutionStatus, FailureReason | None, str | None]:
        """Holat, xato sababi va xato xabarini aniqlaydi."""
        payload = outcome.runner_payload

        if cancelled:
            return ExecutionStatus.CANCELLED, None, "Bajarish bekor qilindi"

        if outcome.timed_out:
            return (
                ExecutionStatus.TIMEOUT,
                FailureReason.TIMEOUT,
                f"Bajarish {self._limits.timeout_seconds} soniyalik vaqt limitidan oshdi",
            )

        if outcome.oom_killed:
            return (
                ExecutionStatus.FAILED,
                FailureReason.OOM,
                f"Bajarish {self._limits.memory_mb} MB xotira limitidan oshdi",
            )

        if outcome.infra_error:
            return ExecutionStatus.FAILED, FailureReason.SANDBOX_ERROR, outcome.infra_error

        if self._limit_reached and not payload.ok:
            return (
                ExecutionStatus.FAILED,
                FailureReason.OUTPUT_TOO_LARGE,
                f"Chiqish hajmi {self._limits.max_output_bytes} bayt limitidan oshdi",
            )

        if payload.ok and (exit_code is None or exit_code == 0):
            if self._limit_reached:
                # Natija qaytgan — bu halokat emas, faqat ogohlantirish.
                logger.warning(
                    "execution.output_truncated",
                    total_bytes=self._total_bytes,
                    max_output_bytes=self._limits.max_output_bytes,
                )
            return ExecutionStatus.SUCCESS, None, None

        reason = runtime.classify_failure(outcome, stderr=stderr)
        return ExecutionStatus.FAILED, reason, self._error_message(outcome, stderr=stderr)

    def _error_message(self, outcome: RunnerOutcome, *, stderr: str) -> str:
        """Xato xabarini `result.json` dan, bo'lmasa stderr oxiridan oladi."""
        payload = outcome.runner_payload
        if payload.error:
            if payload.error_type:
                return f"{payload.error_type}: {payload.error}"
            return payload.error
        if stderr.strip():
            return stderr[-ERROR_TAIL_CHARS:].strip()
        exit_code = outcome.exit_code if outcome.exit_code is not None else payload.exit_code
        return f"Kod {exit_code} chiqish kodi bilan tugadi"

    # ------------------------------------------------------------------
    # Ichki mantiq — log yozuvlari
    # ------------------------------------------------------------------

    def _emit_lines(self, stream: LogStream, text: str) -> None:
        """Matnni qatorlarga bo'lib log yozuvlariga aylantiradi.

        To'liq bo'lmagan oxirgi qator buferda qoladi va keyingi bo'lak bilan
        qo'shiladi (`flush()` da majburan chiqariladi). Shu tufayli bitta
        `print()` natijasi bitta log yozuvi bo'ladi, bo'laklarga sochilmaydi.
        """
        pending = self._pending.get(stream, "") + text
        lines = pending.split("\n")
        self._pending[stream] = lines.pop()
        for line in lines:
            self._add_entry(stream, line)

    def _flush_stream(self, stream: LogStream) -> None:
        """Bitta oqimdagi to'liq bo'lmagan qatorni log'ga chiqaradi."""
        pending = self._pending.get(stream, "")
        if pending:
            self._pending[stream] = ""
            self._add_entry(stream, pending)

    def _add_entry(self, stream: LogStream, content: str) -> None:
        """Bitta qatorni `LogEntry`(lar)ga aylantiradi.

        Juda uzun qator `settings.MAX_LOG_CHUNK_BYTES` bo'laklariga bo'linadi —
        bitta `execution_logs` yozuvi cheklangan hajmda qoladi. Bo'sh qatorlar
        yozuvga aylanmaydi (DB'ni keraksiz satrlar bilan to'ldirmaslik uchun);
        ular `stdout`/`stderr` matnida o'z o'rnida saqlanadi.
        """
        line = content.rstrip("\r")
        if not line:
            return
        remaining = line
        while remaining:
            piece, _ = truncate_bytes(remaining, settings.MAX_LOG_CHUNK_BYTES)
            if not piece:  # pragma: no cover - chegara 4 baytdan kichik bo'lsa
                break
            self._logs.append(
                LogEntry(stream=stream, content=piece, sequence=self._sequence)
            )
            self._sequence += 1
            remaining = remaining[len(piece) :]

    def __repr__(self) -> str:  # pragma: no cover - debug yordamchisi
        return (
            f"<ResultCollector bytes={self._total_bytes} logs={len(self._logs)} "
            f"truncated={self._truncated}>"
        )


__all__ = [
    "ERROR_TAIL_CHARS",
    "TRUNCATION_NOTICE",
    "ResultCollector",
]
