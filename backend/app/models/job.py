"""Durabl — `jobs` jadvali: platformaning markaziy jadvali.

Durability tamoyili: job qabul qilinganda DARHOL shu jadvalga
`status=PENDING` bilan yoziladi va faqat keyin Redis navbatiga qo'yiladi.
Redis qulasa ham job yo'qolmaydi — PostgreSQL'dan tiklanadi.

Jadval ikki xil ma'lumotni birga saqlaydi:

* **So'rov** — `code`, `runtime`, `payload`, limitlar, rejalashtirish;
* **Natija xulosasi** — `result`, `stdout`/`stderr`, `exit_code`, `duration_ms`.
  Har bir alohida urinish tafsiloti `executions` jadvalida, loglar esa
  `execution_logs` da bo'ladi; bu yerda oxirgi urinish natijasi turadi
  (mijoz polling qilganda bitta SELECT bilan javob berish uchun).

Indekslar ro'yxat/filter so'rovlariga moslangan:
`(user_id, status, created_at)` — dashboard ro'yxati,
`(status, scheduled_at)` — scheduler'ning "vaqti kelganlar" so'rovi.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import FailureReason, JobStatus, Priority, Runtime
from app.models.base import (
    Base,
    DateTimeTZ,
    JSONType,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    UUIDType,
    enum_column,
)

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from app.models.dlq_entry import DlqEntry
    from app.models.execution import Execution
    from app.models.execution_log import ExecutionLog
    from app.models.user import User
    from app.models.webhook_delivery import WebhookDelivery


class Job(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Mijoz yuborgan bitta ish (kod + bajarish shartlari + natija)."""

    __tablename__ = "jobs"

    __table_args__ = (
        # Bir foydalanuvchi uchun bir xil idempotency kalit takrorlanmaydi
        UniqueConstraint("user_id", "idempotency_key", name="uq_jobs_user_idempotency"),
        # Dashboard ro'yxati: foydalanuvchi + holat bo'yicha filter, sana bo'yicha tartib
        Index("ix_jobs_user_status_created", "user_id", "status", "created_at"),
        # Scheduler: vaqti kelgan kechiktirilgan job'larni topish
        Index("ix_jobs_status_scheduled", "status", "scheduled_at"),
    )

    # ------------------------------------------------------------------
    # Egasi va takrorlanmaslik
    # ------------------------------------------------------------------

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Mijoz bergan `Idempotency-Key` — bir xil kalit bilan ikkinchi job yaratilmaydi
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ------------------------------------------------------------------
    # Bajarilishi kerak bo'lgan kod
    # ------------------------------------------------------------------

    #: Mijoz kodi (sandbox ichida `main.py` / `main.js` sifatida yoziladi)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    runtime: Mapped[Runtime] = mapped_column(enum_column(Runtime), nullable=False)
    priority: Mapped[Priority] = mapped_column(
        enum_column(Priority),
        default=Priority.NORMAL,
        server_default=Priority.NORMAL.value,
        nullable=False,
    )
    status: Mapped[JobStatus] = mapped_column(
        enum_column(JobStatus),
        default=JobStatus.PENDING,
        server_default=JobStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    #: Kodga uzatiladigan kirish ma'lumotlari (`payload.json`)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    #: Sandbox muhit o'zgaruvchilari (`{"KEY": "value"}`)
    env_vars: Mapped[dict[str, str] | None] = mapped_column(JSONType, nullable=True)

    # ------------------------------------------------------------------
    # Resurs va qayta urinish limitlari
    # ------------------------------------------------------------------

    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False)
    #: Nechta qayta urinish bo'lib o'tdi (birinchi urinish hisobga olinmaydi)
    retry_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    #: Xotira limiti; `None` — reja standarti ishlatiladi
    memory_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: CPU limiti (konteyner `--cpus`); `None` — reja standarti
    cpus: Mapped[float | None] = mapped_column(Float, nullable=True)

    # ------------------------------------------------------------------
    # Rejalashtirish
    # ------------------------------------------------------------------

    #: Kechiktirilgan bajarish vaqti; `None` — darhol navbatga
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True, index=True)
    #: Takrorlanuvchi job uchun cron ifodasi (croniter sintaksisi)
    cron_expression: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # ------------------------------------------------------------------
    # Hayot sikli belgilari
    # ------------------------------------------------------------------

    queued_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)

    # ------------------------------------------------------------------
    # Oxirgi urinish natijasi
    # ------------------------------------------------------------------

    #: Kod qaytargan qiymat (entrypoint `result.json` ga yozadi)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Xato matni (mijozga ko'rsatiladigan qisqa izoh)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Xato tasnifi — DLQ'da guruhlash va analitika uchun
    failure_reason: Mapped[FailureReason | None] = mapped_column(
        enum_column(FailureReason), nullable=True
    )

    # ------------------------------------------------------------------
    # Kuzatuvchanlik
    # ------------------------------------------------------------------

    #: Butun zanjirni (API -> navbat -> worker -> sandbox) bog'lovchi identifikator
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    #: Mijoz qo'ygan teglar — filter va guruhlash uchun
    tags: Mapped[list[str] | None] = mapped_column(JSONType, nullable=True)

    # ------------------------------------------------------------------
    # Bog'lanishlar
    # ------------------------------------------------------------------

    user: Mapped[User] = relationship("User", back_populates="jobs", lazy="raise")
    executions: Mapped[list[Execution]] = relationship(
        "Execution",
        back_populates="job",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Execution.attempt_number",
    )
    logs: Mapped[list[ExecutionLog]] = relationship(
        "ExecutionLog",
        back_populates="job",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    webhook_deliveries: Mapped[list[WebhookDelivery]] = relationship(
        "WebhookDelivery",
        back_populates="job",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    #: DLQ yozuvi — job uchun ko'pi bilan bitta (`dlq_entries.job_id` unique)
    dlq_entry: Mapped[DlqEntry | None] = relationship(
        "DlqEntry",
        back_populates="job",
        uselist=False,
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # ------------------------------------------------------------------
    # Yordamchi xossalar
    # ------------------------------------------------------------------

    @property
    def is_terminal(self) -> bool:
        """Job yakuniy holatdami (`success`, `cancelled`, `dead_letter`)?"""
        return JobStatus(self.status).is_terminal

    @property
    def is_active(self) -> bool:
        """Job hali tizimda harakatdami (navbatda yoki bajarilmoqda)?"""
        return JobStatus(self.status).is_active

    @property
    def attempts_used(self) -> int:
        """Sarflangan urinishlar soni: birinchi urinish + qayta urinishlar."""
        return self.retry_count + 1

    @property
    def is_scheduled(self) -> bool:
        """Job kechiktirilganmi (kelajakdagi vaqtga belgilangan)?"""
        return self.scheduled_at is not None

    @property
    def is_recurring(self) -> bool:
        """Job takrorlanuvchimi (cron ifodasi berilganmi)?"""
        return self.cron_expression is not None


__all__ = ["Job"]
