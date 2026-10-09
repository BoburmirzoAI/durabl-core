"""Durabl — `webhooks` jadvali: mijoz webhook sozlamalari.

Mijoz job hodisalaridan (`WebhookEvent`) xabardor bo'lish uchun URL
registratsiya qiladi. Har bir yuborish `X-Durabl-Signature` HMAC imzosi
bilan boriladi — imzo kaliti shu yerdagi `secret`.

Avtomatik o'chirish: ketma-ket muvaffaqiyatsizliklar soni
(`consecutive_failures`) belgilangan chegaradan oshsa, `webhook_sender`
webhook'ni `disabled_at` bilan o'chiradi va mijozga xabar beradi. Shu tufayli
"faol" tushunchasi ikki ustundan iborat: `is_active` (mijoz qarori) va
`disabled_at` (tizim qarori).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Integer, String, text, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    DateTimeTZ,
    JSONType,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    UUIDType,
)

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from app.models.user import User
    from app.models.webhook_delivery import WebhookDelivery


class Webhook(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Mijozning bitta webhook endpoint'i."""

    __tablename__ = "webhooks"

    #: Webhook egasi
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ------------------------------------------------------------------
    # Endpoint tafsilotlari
    # ------------------------------------------------------------------

    #: Maqsad URL (SSRF tekshiruvidan o'tgan — `validate_webhook_url`)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    #: HMAC imzo kaliti (`generate_webhook_secret`)
    secret: Mapped[str] = mapped_column(String(128), nullable=False)
    #: Obuna bo'lingan hodisalar ro'yxati — `WebhookEvent` qiymatlari
    events: Mapped[list[str]] = mapped_column(JSONType, nullable=False)
    #: Mijoz izohi (UI'da ko'rsatiladi)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ------------------------------------------------------------------
    # Holat
    # ------------------------------------------------------------------

    #: Mijoz tomonidan yoqilgan/o'chirilgan
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    #: Oxirgi marta hodisa yuborilgan vaqt
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTimeTZ, nullable=True
    )
    #: Ketma-ket muvaffaqiyatsizliklar soni (muvaffaqiyatda 0 ga qaytadi)
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    #: Tizim tomonidan avtomatik o'chirilgan vaqt
    disabled_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)

    # ------------------------------------------------------------------
    # Bog'lanishlar
    # ------------------------------------------------------------------

    user: Mapped[User] = relationship(
        "User", back_populates="webhooks", lazy="raise"
    )
    deliveries: Mapped[list[WebhookDelivery]] = relationship(
        "WebhookDelivery",
        back_populates="webhook",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # ------------------------------------------------------------------
    # Yordamchi xossalar
    # ------------------------------------------------------------------

    @property
    def is_enabled(self) -> bool:
        """Webhook haqiqatan ishlayaptimi: mijoz yoqqan va tizim o'chirmagan."""
        return self.is_active and self.disabled_at is None

    @property
    def is_auto_disabled(self) -> bool:
        """Tizim tomonidan avtomatik o'chirilganmi?"""
        return self.disabled_at is not None

    @property
    def event_count(self) -> int:
        """Obuna bo'lingan hodisalar soni."""
        return len(self.events)


__all__ = ["Webhook"]
