"""Durabl — `dlq_entries` jadvali: o'lik xatlar navbati (Dead Letter Queue).

Barcha avtomatik qayta urinishlar tugagach job hali ham muvaffaqiyatsiz
bo'lsa, u "jimgina o'lmaydi" — shu jadvalga tushadi. Mijoz dashboard'da
sababini ko'radi (`failure_reason`, `last_error`), tuzatib qo'lda qayta
urinishi (`manual_retry_count`) yoki yozuvni hal qilingan deb belgilashi
mumkin (`resolved`).

Bir job uchun ko'pi bilan bitta DLQ yozuvi bo'ladi (`job_id` unique) —
qayta urinish yangi yozuv yaratmaydi, mavjudini yangilaydi.

Jadvalda `users` ga ikki havola bor:
* `user_id` — job egasi (`CASCADE`: foydalanuvchi o'chsa yozuv ham o'chadi);
* `resolved_by_id` — yozuvni hal qilgan admin (`SET NULL`: admin o'chirilsa
  hal qilish tarixi saqlanadi, faqat havola bo'shaydi).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, Text, false, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import FailureReason
from app.models.base import (
    Base,
    DateTimeTZ,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    UUIDType,
    enum_column,
)
from app.utils.time_utils import utcnow

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from app.models.job import Job
    from app.models.user import User


class DlqEntry(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """DLQ'dagi bitta yozuv — muvaffaqiyatsiz tugagan job."""

    __tablename__ = "dlq_entries"

    # ------------------------------------------------------------------
    # Manba
    # ------------------------------------------------------------------

    #: Bir job uchun bitta yozuv — shuning uchun unique
    job_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    #: Job egasi
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ------------------------------------------------------------------
    # Nega yiqildi
    # ------------------------------------------------------------------

    #: Xato tasnifi — DLQ sahifasida guruhlash uchun indekslangan
    failure_reason: Mapped[FailureReason] = mapped_column(
        enum_column(FailureReason), nullable=False, index=True
    )
    #: Oxirgi urinishdagi xato matni
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: DLQ'ga tushgan vaqt
    failed_at: Mapped[datetime] = mapped_column(
        DateTimeTZ, default=utcnow, nullable=False, index=True
    )
    #: DLQ'ga tushishdan oldin bo'lib o'tgan avtomatik qayta urinishlar soni
    retry_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    # ------------------------------------------------------------------
    # Hal qilish
    # ------------------------------------------------------------------

    #: Yozuv hal qilinganmi — ro'yxat filtri uchun indekslangan
    resolved: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False, index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)
    #: Kim hal qildi (admin o'chirilsa `NULL` bo'ladi)
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    #: Admin izohi
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: DLQ'dan qo'lda qayta urinishlar soni
    manual_retry_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    # ------------------------------------------------------------------
    # Bog'lanishlar
    # ------------------------------------------------------------------

    job: Mapped[Job] = relationship(
        "Job", back_populates="dlq_entry", lazy="raise"
    )
    user: Mapped[User] = relationship(
        "User",
        back_populates="dlq_entries",
        foreign_keys="DlqEntry.user_id",
        lazy="raise",
    )
    #: Hal qilgan admin — teskari tomoni yo'q (audit uchun bir tomonlama)
    resolved_by: Mapped[User | None] = relationship(
        "User",
        foreign_keys="DlqEntry.resolved_by_id",
        lazy="raise",
    )

    # ------------------------------------------------------------------
    # Yordamchi xossalar
    # ------------------------------------------------------------------

    @property
    def is_resolved(self) -> bool:
        """Yozuv hal qilinganmi?"""
        return self.resolved

    @property
    def total_attempts(self) -> int:
        """Jami urinishlar: avtomatik + qo'lda qayta urinishlar."""
        return self.retry_count + self.manual_retry_count

    @property
    def was_manually_retried(self) -> bool:
        """Yozuv qo'lda hech bo'lmasa bir marta qayta urilganmi?"""
        return self.manual_retry_count > 0


__all__ = ["DlqEntry"]
