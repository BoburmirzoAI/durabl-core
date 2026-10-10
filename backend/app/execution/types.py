"""Durabl — bajarish qatlamining umumiy ma'lumot tuzilmalari.

Bu modul `app/execution/` va `app/services/` orasidagi SHARTNOMA: executor,
sandbox manager, runtime'lar, result collector va `execution_service` hammasi
shu dataclass'lar bilan gaplashadi. Shuning uchun bu fayl hech qanday
og'ir bog'liqlikka ega emas (faqat `constants` va `config`).

Oqim:

    JobCreate -> SandboxSpec -> Executor.execute() -> ExecutionResult
                                      |
                                      +-> list[LogEntry] (stdout/stderr/system)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.config import settings
from app.constants import (
    ExecutionStatus,
    FailureReason,
    HttpMethod,
    JobKind,
    LogStream,
    PlanLimits,
    Runtime,
)
from app.utils.time_utils import utcnow

# ---------------------------------------------------------------------------
# Log yozuvi
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class LogEntry:
    """Bajarish davomida yig'ilgan bitta log qatori.

    `sequence` — bitta bajarish ichida 0'dan boshlanadigan tartib raqami.
    Loglar real-time uzatilganda ham tartib buzilmasligini kafolatlaydi
    (mijoz `after_sequence` bilan faqat yangilarini so'raydi).
    """

    stream: LogStream
    content: str
    sequence: int
    timestamp: datetime = field(default_factory=utcnow)

    def to_row(self, execution_id: uuid.UUID, job_id: uuid.UUID) -> dict[str, Any]:
        """`execution_logs` jadvaliga yozish uchun lug'at."""
        return {
            "execution_id": execution_id,
            "job_id": job_id,
            "stream": self.stream,
            "content": self.content,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Resurs cheklovlari
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    """Bitta bajarish uchun hisoblangan resurs cheklovlari.

    Qiymatlar uch manbadan eng QAT'IYsi tanlanadi:
    job so'rovi -> foydalanuvchi rejasi (`PlanLimits`) -> global sozlama.
    """

    memory_mb: int = settings.SANDBOX_MEMORY_MB
    cpus: float = settings.SANDBOX_CPUS
    pids_limit: int = settings.SANDBOX_PIDS_LIMIT
    disk_mb: int = settings.SANDBOX_DISK_MB
    tmpfs_mb: int = settings.SANDBOX_TMPFS_SIZE_MB
    timeout_seconds: int = settings.DEFAULT_TIMEOUT_SECONDS
    max_output_bytes: int = settings.MAX_OUTPUT_BYTES
    allow_network: bool = False
    read_only_rootfs: bool = settings.SANDBOX_READ_ONLY_ROOTFS

    @classmethod
    def resolve(
        cls,
        *,
        requested_memory_mb: int | None = None,
        requested_cpus: float | None = None,
        requested_timeout: int | None = None,
        plan: PlanLimits | None = None,
    ) -> ResourceLimits:
        """So'rov va reja limitlaridan yakuniy cheklovlarni hisoblaydi.

        Mijoz rejasidan ko'proq so'rasa — reja chegarasiga QISQARTIRILADI
        (xato tashlanmaydi: bu "silent clamp", mijoz kodi baribir ishlaydi).
        """
        plan_memory = plan.max_memory_mb if plan else settings.SANDBOX_MEMORY_MB
        plan_cpus = plan.max_cpus if plan else settings.SANDBOX_CPUS
        plan_timeout = plan.max_timeout_seconds if plan else settings.MAX_TIMEOUT_SECONDS
        allow_network = plan.allow_network if plan else False

        memory = min(requested_memory_mb or plan_memory, plan_memory)
        cpus = min(requested_cpus or plan_cpus, plan_cpus)
        timeout = min(
            requested_timeout or settings.DEFAULT_TIMEOUT_SECONDS,
            plan_timeout,
            settings.MAX_TIMEOUT_SECONDS,
        )

        return cls(
            memory_mb=max(64, int(memory)),
            cpus=max(0.1, float(cpus)),
            timeout_seconds=max(settings.MIN_TIMEOUT_SECONDS, int(timeout)),
            allow_network=allow_network,
        )


# ---------------------------------------------------------------------------
# Sandbox spetsifikatsiyasi
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SandboxSpec:
    """Bitta bajarish topshirig'i (kod yoki HTTP chaqiruv).

    `Executor` va runner'lar faqat shu obyektga qaraydi — DB modeliga
    bog'liq emas. Shu tufayli bajarish qatlamini DB'siz test qilish mumkin.

    ## Ikki rejim bitta obyektda

    `kind` qaysi runner ishlashini belgilaydi:

    * `JobKind.CODE` — `code` va `runtime` to'ldiriladi,
      `SandboxManager`/`LocalRunner` ishlaydi;
    * `JobKind.HTTP` — `target_url` va `http_method` to'ldiriladi,
      `HttpRunner` ishlaydi; `code` BO'SH bo'ladi.

    Ikki rejim uchun ikkita alohida spec turi ATAYLAB yasalmadi: shunda
    `Executor`, `ResultCollector`, `TimeoutGuard` va butun ishonchlilik
    zanjiri ikki martalab yozilishi kerak bo'lardi. Bitta obyekt bilan
    HTTP job AYNI kafolatlarni (lease, retry, DLQ, log) tekinga oladi.
    """

    job_id: str
    runtime: Runtime
    limits: ResourceLimits
    #: `kind=CODE` uchun mijoz kodi. `kind=HTTP` da `None`.
    code: str | None = None
    #: Bajarish rejimi. Standart `CODE` — mavjud chaqiruvlar o'zgarmaydi.
    kind: JobKind = JobKind.CODE
    #: `kind=HTTP` uchun chaqiriladigan manzil.
    target_url: str | None = None
    #: `kind=HTTP` uchun metod.
    http_method: HttpMethod | None = None
    #: `kind=HTTP` uchun qo'shimcha header'lar.
    http_headers: dict[str, str] | None = None
    payload: dict[str, Any] | None = None
    env_vars: dict[str, str] | None = None
    correlation_id: str = ""
    attempt_number: int = 1

    @property
    def timeout_seconds(self) -> int:
        """Qulaylik uchun — `limits.timeout_seconds`."""
        return self.limits.timeout_seconds

    @property
    def is_http(self) -> bool:
        """HTTP rejimimi (`HttpRunner` ishlaydimi)."""
        return self.kind is JobKind.HTTP

    @property
    def code_filename(self) -> str:
        """Sandbox ichidagi kod fayli nomi (`main.py` yoki `main.js`)."""
        from app.constants import SANDBOX_CODE_FILENAME  # aylanma importdan qochish

        return SANDBOX_CODE_FILENAME[self.runtime]

    def safe_env(self) -> dict[str, str]:
        """Sandbox'ga uzatiladigan muhit o'zgaruvchilari (xavfsiz nomlar bilan)."""
        base: dict[str, str] = {
            "DURABL_JOB_ID": self.job_id,
            "DURABL_ATTEMPT": str(self.attempt_number),
            "DURABL_TIMEOUT": str(self.timeout_seconds),
        }
        if self.correlation_id:
            base["DURABL_CORRELATION_ID"] = self.correlation_id
        if self.env_vars:
            base.update(self.env_vars)
        return base


# ---------------------------------------------------------------------------
# Bajarish natijasi
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ExecutionResult:
    """Bajarish yakunidagi to'liq natija.

    `execution_service` shu obyektni `executions` va `jobs` jadvallariga
    yozadi, `logs` ni esa `execution_logs` ga ko'chiradi.
    """

    status: ExecutionStatus
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    result: Any | None = None
    duration_ms: int = 0
    logs: list[LogEntry] = field(default_factory=list)
    failure_reason: FailureReason | None = None
    error_message: str | None = None
    traceback: str | None = None
    memory_peak_mb: int | None = None
    truncated: bool = False
    sandbox_id: str | None = None
    #: `JobKind.HTTP` uchun javobning HTTP status kodi.
    #:
    #: Nega `exit_code` yetmaydi: `ResultCollector` muvaffaqiyatni
    #: "`ok` VA `exit_code == 0`" deb aniqlaydi, ya'ni muvaffaqiyatli
    #: HTTP job'da `exit_code` 0 bo'lishi SHART. Natijada 200 va 201
    #: farqi yo'qolardi. Shu maydon aynan o'sha ma'lumotni saqlaydi.
    #: `kind=CODE` uchun har doim `None`.
    response_status: int | None = None

    @property
    def is_success(self) -> bool:
        """Muvaffaqiyatli tugadimi?"""
        return self.status is ExecutionStatus.SUCCESS

    @property
    def stdout_bytes(self) -> int:
        return len(self.stdout.encode("utf-8", errors="replace"))

    @property
    def stderr_bytes(self) -> int:
        return len(self.stderr.encode("utf-8", errors="replace"))

    @classmethod
    def success(cls, **kwargs: Any) -> ExecutionResult:
        """Muvaffaqiyatli natija yasash uchun qisqa yo'l."""
        kwargs.setdefault("exit_code", 0)
        return cls(status=ExecutionStatus.SUCCESS, **kwargs)

    @classmethod
    def failure(
        cls,
        *,
        failure_reason: FailureReason,
        error_message: str,
        status: ExecutionStatus = ExecutionStatus.FAILED,
        **kwargs: Any,
    ) -> ExecutionResult:
        """Xato natijasini yasash uchun qisqa yo'l."""
        return cls(
            status=status,
            failure_reason=failure_reason,
            error_message=error_message,
            **kwargs,
        )

    def to_execution_fields(self) -> dict[str, Any]:
        """`executions` jadvalini yangilash uchun maydonlar."""
        return {
            "status": self.status,
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "error_message": self.error_message,
            "failure_reason": self.failure_reason,
            "stdout_bytes": self.stdout_bytes,
            "stderr_bytes": self.stderr_bytes,
            "result": {"value": self.result} if self.result is not None else None,
            "sandbox_id": self.sandbox_id,
            "memory_peak_mb": self.memory_peak_mb,
        }

    def to_job_fields(self) -> dict[str, Any]:
        """`jobs` jadvalini yangilash uchun maydonlar."""
        return {
            "exit_code": self.exit_code,
            "duration_ms": self.duration_ms,
            "stdout": self.stdout or None,
            "stderr": self.stderr or None,
            "result": {"value": self.result} if self.result is not None else None,
            "error": self.error_message,
            "failure_reason": self.failure_reason,
            # `kind=CODE` da `None` — ustun baribir `NULL` bo'lib qoladi.
            "response_status": self.response_status,
        }


# ---------------------------------------------------------------------------
# Sandbox runner natijasi (entrypoint `result.json` fayli)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RunnerPayload:
    """Sandbox entrypoint yozgan `result.json` ning tiplangan ko'rinishi.

    Sandbox shartnomasi (`sandbox/runners/*/entrypoint.*` shunday yozadi):
        {"ok": bool, "exit_code": int, "result": Any, "error": str | None,
         "error_type": str | None, "traceback": str | None,
         "duration_ms": int, "stdout_bytes": int, "stderr_bytes": int}
    """

    ok: bool = False
    exit_code: int | None = None
    result: Any | None = None
    error: str | None = None
    error_type: str | None = None
    traceback: str | None = None
    duration_ms: int = 0
    stdout_bytes: int = 0
    stderr_bytes: int = 0
    truncated: bool = False

    @classmethod
    def parse(cls, raw: dict[str, Any] | None) -> RunnerPayload:
        """`result.json` lug'atidan obyekt yasaydi (yo'q/buzilgan bo'lsa bo'sh)."""
        if not isinstance(raw, dict):
            return cls()
        return cls(
            ok=bool(raw.get("ok", False)),
            exit_code=raw.get("exit_code"),
            result=raw.get("result"),
            error=raw.get("error"),
            error_type=raw.get("error_type"),
            traceback=raw.get("traceback"),
            duration_ms=int(raw.get("duration_ms") or 0),
            stdout_bytes=int(raw.get("stdout_bytes") or 0),
            stderr_bytes=int(raw.get("stderr_bytes") or 0),
            truncated=bool(raw.get("truncated", False)),
        )


# ---------------------------------------------------------------------------
# Runner natijasi (sandbox yoki lokal subprocess qaytaradi)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class RunnerOutcome:
    """Runner (sandbox/lokal) qaytaradigan XOM natija.

    Runner faqat "jarayon qanday tugadi" ni biladi; uni `ExecutionStatus` va
    `FailureReason` ga aylantirish `ResultCollector` ning mas'uliyati.
    """

    exit_code: int | None = None
    runner_payload: RunnerPayload = field(default_factory=RunnerPayload)
    sandbox_id: str | None = None
    #: Konteyner xotira limiti sababli o'ldirilganmi (Docker `OOMKilled`)
    oom_killed: bool = False
    #: Vaqt limiti tufayli majburan to'xtatilganmi
    timed_out: bool = False
    memory_peak_mb: int | None = None
    #: Runner darajasidagi infratuzilma xatosi (konteyner yaratilmadi va h.k.)
    infra_error: str | None = None
    #: `HttpRunner` to'ldiradi — javobning HTTP status kodi. Sandbox va
    #: lokal runner uchun har doim `None`.
    response_status: int | None = None


__all__ = [
    "ExecutionResult",
    "LogEntry",
    "ResourceLimits",
    "RunnerOutcome",
    "RunnerPayload",
    "SandboxSpec",
]
