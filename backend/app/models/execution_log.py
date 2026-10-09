"""Durabl — `execution_logs` jadvali: sandbox chiqish oqimlari.

Bu jadval loyihada eng tez o'sadigan jadval (har job yuzlab qator log
yozishi mumkin), shuning uchun ataylab yengil tutilgan:

* **`TimestampMixin` ISHLATILMAYDI** — `created_at`/`updated_at` o'rniga
  bitta `timestamp` ustuni yetarli (ikki ortiqcha ustun va bitta ortiqcha
  indeks tejaladi).
* `job_id` denormalizatsiya qilingan — "job'ning barcha loglari" so'rovi
  `executions` bilan JOIN qilmasdan bajariladi.
* `(execution_id, sequence)` indeksi — loglarni tartib bilan va kursor
  (`after_sequence`) orqali sahifalab o'qish uchun.

Eski loglar reja `log_retention_days` muddatidan keyin
`ExecutionLogRepository.delete_older_than()` bilan o'chiriladi.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import LogStream
from app.models.base import Base, DateTimeTZ, UUIDPrimaryKeyMixin, UUIDType, enum_column
from app.utils.time_utils import utcnow

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from app.models.execution import Execution
    from app.models.job import Job


class ExecutionLog(UUIDPrimaryKeyMixin, Base):
    """Bitta log qatori (stdout / stderr / tizim xabari)."""

    __tablename__ = "execution_logs"

    __table_args__ = (
        # Loglarni tartib bilan o'qish va kursor bo'yicha davom etish uchun
        Index("ix_execution_logs_exec_seq", "execution_id", "sequence"),
    )

    #: Qaysi urinishga tegishli
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Denormalizatsiya: job bo'yicha tez qidiruv (JOIN qilmasdan)
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: Oqim turi: `stdout`, `stderr` yoki Durabl'ning o'z xabari (`system`)
    stream: Mapped[LogStream] = mapped_column(enum_column(LogStream), nullable=False)
    #: Log matni
    content: Mapped[str] = mapped_column(Text, nullable=False)
    #: Urinish ichidagi tartib raqami (0 dan o'sib boradi)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Log yozilgan vaqt
    timestamp: Mapped[datetime] = mapped_column(
        DateTimeTZ, default=utcnow, nullable=False, index=True
    )

    # ------------------------------------------------------------------
    # Bog'lanishlar
    # ------------------------------------------------------------------

    execution: Mapped[Execution] = relationship(
        "Execution", back_populates="logs", lazy="raise"
    )
    job: Mapped[Job] = relationship("Job", back_populates="logs", lazy="raise")

    # ------------------------------------------------------------------
    # Yordamchi xossalar
    # ------------------------------------------------------------------

    @property
    def is_error(self) -> bool:
        """Qator xato oqimidan kelganmi?"""
        return LogStream(self.stream) is LogStream.STDERR

    @property
    def length(self) -> int:
        """Log matnining uzunligi (belgilar soni)."""
        return len(self.content)


__all__ = ["ExecutionLog"]
