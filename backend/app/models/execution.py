"""Durabl — `executions` jadvali: job'ning har bir bajarish urinishi.

Bitta job bir necha marta urinilishi mumkin (retry yoki lease yo'qolishi
natijasida), shuning uchun urinishlar alohida jadvalda saqlanadi. Bu DLQ
sahifasida "qancha marta urinildi va har biri nega yiqildi" savoliga javob
berish imkonini beradi.

Lease mexanizmi: worker job'ni olganda `worker_id` va `lease_expires_at`
yoziladi. Heartbeat har necha soniyada `lease_expires_at`ni surib boradi.
Worker qulasa lease muddati tugaydi va `reap_expired_leases()` urinishni
`LOST` deb belgilab job'ni qayta navbatga qo'yadi — shu tufayli
`lease_expires_at` indekslangan.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import ExecutionStatus, FailureReason
from app.models.base import (
    Base,
    DateTimeTZ,
    JSONType,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    UUIDType,
    enum_column,
)
from app.utils.time_utils import is_expired

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from app.models.execution_log import ExecutionLog
    from app.models.job import Job


class Execution(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Job'ning bitta bajarish urinishi."""

    __tablename__ = "executions"

    __table_args__ = (
        # Bitta job uchun bir xil urinish raqami ikki marta yozilmaydi
        UniqueConstraint("job_id", "attempt_number"),
    )

    # ------------------------------------------------------------------
    # Qaysi job, nechanchi urinish
    # ------------------------------------------------------------------

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Urinish raqami — 1 dan boshlanadi
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # ------------------------------------------------------------------
    # Lease (worker tiriklik nazorati)
    # ------------------------------------------------------------------

    #: Urinishni bajargan worker identifikatori
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    #: Lease qachon tugaydi — shundan keyin job boshqa worker'ga o'tadi
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True, index=True)

    # ------------------------------------------------------------------
    # Holat va vaqtlar
    # ------------------------------------------------------------------

    status: Mapped[ExecutionStatus] = mapped_column(
        enum_column(ExecutionStatus),
        default=ExecutionStatus.PENDING,
        server_default=ExecutionStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)

    # ------------------------------------------------------------------
    # Natija
    # ------------------------------------------------------------------

    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[FailureReason | None] = mapped_column(
        enum_column(FailureReason), nullable=True
    )
    #: stdout hajmi (baytda) — loglar alohida jadvalda, bu yerda faqat o'lcham
    stdout_bytes: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    #: stderr hajmi (baytda)
    stderr_bytes: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    #: Kod qaytargan qiymat
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    # ------------------------------------------------------------------
    # Sandbox tafsilotlari
    # ------------------------------------------------------------------

    #: Konteyner identifikatori (orfan konteynerlarni tozalash uchun)
    sandbox_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    #: Eng yuqori xotira iste'moli (OOM tahlili uchun)
    memory_peak_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ------------------------------------------------------------------
    # Bog'lanishlar
    # ------------------------------------------------------------------

    job: Mapped[Job] = relationship("Job", back_populates="executions", lazy="raise")
    logs: Mapped[list[ExecutionLog]] = relationship(
        "ExecutionLog",
        back_populates="execution",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ExecutionLog.sequence",
    )

    # ------------------------------------------------------------------
    # Yordamchi xossalar
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Urinish hozir bajarilmoqdami?"""
        return ExecutionStatus(self.status) is ExecutionStatus.RUNNING

    @property
    def is_successful(self) -> bool:
        """Urinish muvaffaqiyatli tugadimi?"""
        return ExecutionStatus(self.status) is ExecutionStatus.SUCCESS

    @property
    def lease_expired(self) -> bool:
        """Lease muddati o'tganmi? (`None` lease — muddat yo'q)"""
        return is_expired(self.lease_expires_at)

    @property
    def output_bytes(self) -> int:
        """stdout va stderr hajmlari yig'indisi (baytda)."""
        return self.stdout_bytes + self.stderr_bytes


__all__ = ["Execution"]
