"""Durabl — `usage_records` jadvali: oylik foydalanish hisobi (billing).

Har bir foydalanuvchi uchun har bir oyga bitta yozuv bo'ladi
(`UniqueConstraint("user_id", "period")`), `period` formati `"2026-10"`
(`app.utils.time_utils.month_key()` beradi).

Hisoblagichlar `BillingService.record_job()` / `record_execution()` orqali
o'sib boradi; kvota tekshiruvi (`check_quota`) joriy oy yozuvini
reja limitidagi `monthly_jobs` bilan solishtiradi.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    DateTimeTZ,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    UUIDType,
)
from app.utils.time_utils import utcnow

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from app.models.user import User


class UsageRecord(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bitta foydalanuvchining bitta oydagi foydalanish hisobi."""

    __tablename__ = "usage_records"

    __table_args__ = (
        # Bir foydalanuvchi + bir oy = bitta yozuv
        UniqueConstraint("user_id", "period"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Hisob davri — `"YYYY-MM"` (7 belgi)
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)

    # ------------------------------------------------------------------
    # Hisoblagichlar
    # ------------------------------------------------------------------

    #: Oyda yuborilgan job'lar soni (kvota shu bo'yicha tekshiriladi)
    job_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    success_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    failed_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    #: Jami bajarish vaqti (soniyada, kasrli)
    execution_seconds: Mapped[float] = mapped_column(
        Float, default=0.0, server_default=text("0"), nullable=False
    )
    #: Yozuv oxirgi yangilangan vaqt
    recorded_at: Mapped[datetime] = mapped_column(DateTimeTZ, default=utcnow, nullable=False)

    # ------------------------------------------------------------------
    # Bog'lanishlar
    # ------------------------------------------------------------------

    user: Mapped[User] = relationship("User", back_populates="usage_records", lazy="raise")

    # ------------------------------------------------------------------
    # Yordamchi xossalar
    # ------------------------------------------------------------------

    @property
    def success_rate(self) -> float:
        """Muvaffaqiyat foizi (0.0 - 100.0); job bo'lmasa 0.0."""
        if self.job_count <= 0:
            return 0.0
        return round(self.success_count / self.job_count * 100, 2)

    @property
    def execution_minutes(self) -> float:
        """Jami bajarish vaqti — daqiqada."""
        return round(self.execution_seconds / 60, 2)


__all__ = ["UsageRecord"]
