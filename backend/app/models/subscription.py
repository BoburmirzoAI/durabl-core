"""Durabl — `subscriptions` jadvali: foydalanuvchi obunasi.

Bir foydalanuvchiga bitta faol obuna to'g'ri keladi (`user_id` unique),
shuning uchun `User.subscription` bog'lanishi `uselist=False`.

Obuna rejaning O'ZINI emas, faqat uning NOMINI saqlaydi. Haqiqiy limitlar
(`monthly_jobs`, `requests_per_minute`, `max_memory_mb` ...) kodda,
`app.constants.PLAN_LIMITS` da turadi va `limits` xossasi orqali olinadi.
Shu tufayli narx/limit o'zgarganda DB migratsiyasi kerak bo'lmaydi.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import PlanLimits, PlanType, plan_limits
from app.models.base import (
    Base,
    DateTimeTZ,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    UUIDType,
    enum_column,
)
from app.utils.time_utils import is_expired, utcnow

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from app.models.user import User


class Subscription(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Foydalanuvchining obuna rejasi."""

    __tablename__ = "subscriptions"

    #: Obuna egasi — bir foydalanuvchiga bitta obuna
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # ------------------------------------------------------------------
    # Reja va muddat
    # ------------------------------------------------------------------

    plan: Mapped[PlanType] = mapped_column(
        enum_column(PlanType),
        default=PlanType.FREE,
        server_default=PlanType.FREE.value,
        nullable=False,
    )
    #: Obuna boshlangan vaqt
    started_at: Mapped[datetime] = mapped_column(DateTimeTZ, default=utcnow, nullable=False)
    #: Obuna tugash vaqti; `None` — muddatsiz (masalan FREE reja)
    expires_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)

    # ------------------------------------------------------------------
    # Holat
    # ------------------------------------------------------------------

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    #: Mijoz bekor qilgan vaqt (muddat oxirigacha xizmat davom etadi)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)
    #: Tashqi to'lov tizimidagi mijoz identifikatori
    external_customer_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # ------------------------------------------------------------------
    # Bog'lanishlar
    # ------------------------------------------------------------------

    user: Mapped[User] = relationship("User", back_populates="subscription", lazy="raise")

    # ------------------------------------------------------------------
    # Yordamchi xossalar
    # ------------------------------------------------------------------

    @property
    def limits(self) -> PlanLimits:
        """Reja limitlari (`app.constants.PLAN_LIMITS` dan)."""
        return plan_limits(self.plan)

    @property
    def is_valid(self) -> bool:
        """Obuna hozir kuchdami: faol va muddati o'tmagan."""
        return self.is_active and not is_expired(self.expires_at)

    @property
    def is_cancelled(self) -> bool:
        """Obuna bekor qilinganmi?"""
        return self.cancelled_at is not None


__all__ = ["Subscription"]
