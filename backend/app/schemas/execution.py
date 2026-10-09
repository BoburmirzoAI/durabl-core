"""Durabl — bajarish urinishlari (`executions`) va loglar schema'lari.

Bitta job bir necha marta urinilishi mumkin (retry), har urinish alohida
`Execution` yozuvi. Loglar `execution_logs` jadvalida — `sequence` bo'yicha
tartiblangan, kursorli sahifalash uchun qulay.

Diqqat: bu modul `app.schemas.job`ni import QILMAYDI (aylanma import bo'lmasligi
uchun) — `job.py` aksincha shu moduldan `ExecutionLogRead`ni oladi.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, computed_field, model_validator

from app.constants import ExecutionStatus, FailureReason, LogStream
from app.schemas.base import DurablSchema, ORMSchema

#: Bitta so'rovda qaytariladigan log yozuvlarining maksimal soni.
MAX_LOG_LIMIT = 2_000

#: `ExecutionFilter` da ruxsat etilgan tartiblash ustunlari.
EXECUTION_SORT_FIELDS: frozenset[str] = frozenset(
    {"created_at", "started_at", "finished_at", "duration_ms", "attempt_number"}
)


# ---------------------------------------------------------------------------
# Javoblar
# ---------------------------------------------------------------------------


class ExecutionRead(ORMSchema):
    """Bitta bajarish urinishining to'liq tafsiloti."""

    id: uuid.UUID = Field(description="Bajarish urinishi identifikatori")
    job_id: uuid.UUID = Field(description="Tegishli job identifikatori")
    attempt_number: Annotated[int, Field(ge=1)] = Field(
        description="Urinish tartib raqami (1 — birinchi urinish)"
    )
    status: ExecutionStatus = Field(description="Urinish holati")
    worker_id: str | None = Field(
        default=None, description="Urinishni bajargan worker identifikatori"
    )
    lease_expires_at: datetime | None = Field(
        default=None,
        description="Lease (egalik huquqi) qachon tugaydi — heartbeat uni yangilaydi",
    )
    started_at: datetime | None = Field(default=None, description="Boshlangan vaqt (UTC)")
    finished_at: datetime | None = Field(default=None, description="Tugagan vaqt (UTC)")
    exit_code: int | None = Field(default=None, description="Sandbox protsessining chiqish kodi")
    duration_ms: int | None = Field(default=None, description="Bajarish davomiyligi (ms)")
    error_message: str | None = Field(default=None, description="Xato matni (bo'lsa)")
    failure_reason: FailureReason | None = Field(
        default=None, description="Muvaffaqiyatsizlik sababi (tasniflangan)"
    )
    stdout_bytes: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Yig'ilgan stdout hajmi (bayt)"
    )
    stderr_bytes: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Yig'ilgan stderr hajmi (bayt)"
    )
    result: Any | None = Field(default=None, description="Mijoz kodi qaytargan qiymat (JSON)")
    sandbox_id: str | None = Field(
        default=None, description="Sandbox/konteyner identifikatori (diagnostika uchun)"
    )
    memory_peak_mb: int | None = Field(default=None, description="Eng yuqori xotira iste'moli (MB)")
    created_at: datetime = Field(description="Yozuv yaratilgan vaqt (UTC)")
    updated_at: datetime | None = Field(default=None, description="Oxirgi o'zgartirish vaqti (UTC)")

    @computed_field(description="Urinish yakunlanganmi (yangi o'zgarish kutilmaydi)")  # type: ignore[prop-decorator]
    @property
    def is_finished(self) -> bool:
        """Holat yakuniy bo'lsa `True`."""
        return self.status not in (ExecutionStatus.PENDING, ExecutionStatus.RUNNING)


class ExecutionSummary(ORMSchema):
    """Ro'yxat uchun yengil ko'rinish (natija va loglarsiz)."""

    id: uuid.UUID = Field(description="Bajarish urinishi identifikatori")
    job_id: uuid.UUID = Field(description="Tegishli job identifikatori")
    attempt_number: Annotated[int, Field(ge=1)] = Field(description="Urinish tartib raqami")
    status: ExecutionStatus = Field(description="Urinish holati")
    worker_id: str | None = Field(default=None, description="Bajargan worker")
    started_at: datetime | None = Field(default=None, description="Boshlangan vaqt (UTC)")
    finished_at: datetime | None = Field(default=None, description="Tugagan vaqt (UTC)")
    exit_code: int | None = Field(default=None, description="Chiqish kodi")
    duration_ms: int | None = Field(default=None, description="Davomiylik (ms)")
    failure_reason: FailureReason | None = Field(
        default=None, description="Muvaffaqiyatsizlik sababi"
    )
    created_at: datetime = Field(description="Yozuv yaratilgan vaqt (UTC)")


class ExecutionLogRead(ORMSchema):
    """Bitta log yozuvi (stdout/stderr/system qatori)."""

    id: uuid.UUID = Field(description="Log yozuvi identifikatori")
    execution_id: uuid.UUID = Field(description="Qaysi bajarish urinishiga tegishli")
    job_id: uuid.UUID = Field(description="Job identifikatori (tez qidiruv uchun denormalizatsiya)")
    stream: LogStream = Field(description="Oqim: stdout, stderr yoki system")
    content: str = Field(description="Log matni")
    sequence: Annotated[int, Field(ge=0)] = Field(
        description="Urinish ichidagi tartib raqami — kursorli sahifalash kaliti"
    )
    timestamp: datetime = Field(description="Log yozilgan vaqt (UTC)")


# ---------------------------------------------------------------------------
# Filtrlar
# ---------------------------------------------------------------------------


class ExecutionFilter(DurablSchema):
    """`GET /executions` query parametrlari."""

    job_id: uuid.UUID | None = Field(default=None, description="Faqat shu job'ning urinishlari")
    status: ExecutionStatus | None = Field(default=None, description="Holat bo'yicha filtr")
    failure_reason: FailureReason | None = Field(
        default=None, description="Muvaffaqiyatsizlik sababi bo'yicha filtr"
    )
    worker_id: Annotated[str, Field(max_length=128)] | None = Field(
        default=None, description="Muayyan worker bajargan urinishlar"
    )
    start: datetime | None = Field(default=None, description="Oraliq boshlanishi (ISO-8601, UTC)")
    end: datetime | None = Field(default=None, description="Oraliq tugashi (ISO-8601, UTC)")
    sort_by: str = Field(default="created_at", description="Tartiblash ustuni")
    sort_order: Literal["asc", "desc"] = Field(default="desc", description="Tartiblash yo'nalishi")

    @model_validator(mode="after")
    def _check_filter(self) -> ExecutionFilter:
        """Oraliq mantiqan to'g'ri va tartiblash ustuni ruxsat etilganmi."""
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("`start` qiymati `end`dan keyin bo'lishi mumkin emas")
        if self.sort_by not in EXECUTION_SORT_FIELDS:
            raise ValueError(
                "`sort_by` noto'g'ri; ruxsat etilgan: " + ", ".join(sorted(EXECUTION_SORT_FIELDS))
            )
        return self


__all__ = [
    "EXECUTION_SORT_FIELDS",
    "MAX_LOG_LIMIT",
    "ExecutionFilter",
    "ExecutionLogRead",
    "ExecutionRead",
    "ExecutionSummary",
]
