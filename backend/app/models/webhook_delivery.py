"""Durabl — `webhook_deliveries` jadvali: webhook yuborish tarixi.

Har bir hodisa uchun avval `PENDING` holatda yozuv yaratiladi, keyin
`webhook_sender` worker'i uni HTTP orqali yuboradi. Muvaffaqiyatsiz bo'lsa
`next_retry_at` belgilanadi va `retry_policy` bo'yicha qayta urinadi; barcha
urinishlar tugasa holat `EXHAUSTED` bo'ladi.

Shu tufayli webhook "at-least-once" kafolatiga ega bo'ladi: yuborish
urinishi DB'da qoladi, server qulasa ham qayta tiklanadi. `next_retry_at`
indekslangan — `pending_retries(now, limit)` so'rovi shundan foydalanadi.

`response_body` 4KB dan kesib saqlanadi (`truncate()`), aks holda jadval
javob tanalari bilan to'lib ketadi.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import DeliveryStatus, WebhookEvent
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
    from app.models.job import Job
    from app.models.webhook import Webhook


class WebhookDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bitta webhook yuborish urinishi va uning natijasi."""

    __tablename__ = "webhook_deliveries"

    # ------------------------------------------------------------------
    # Manba
    # ------------------------------------------------------------------

    webhook_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("webhooks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Hodisa job bilan bog'liq bo'lmasligi mumkin (masalan test yuborish)
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    event: Mapped[WebhookEvent] = mapped_column(
        enum_column(WebhookEvent), nullable=False
    )

    # ------------------------------------------------------------------
    # Yuborish holati
    # ------------------------------------------------------------------

    status: Mapped[DeliveryStatus] = mapped_column(
        enum_column(DeliveryStatus),
        default=DeliveryStatus.PENDING,
        server_default=DeliveryStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    #: Nechanchi urinish (1 dan boshlanadi)
    attempt: Mapped[int] = mapped_column(
        Integer, default=1, server_default=text("1"), nullable=False
    )
    #: Keyingi urinish vaqti — `pending_retries()` shu bo'yicha tanlaydi
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTimeTZ, nullable=True, index=True
    )
    #: Muvaffaqiyatli yetib borgan vaqt
    delivered_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)

    # ------------------------------------------------------------------
    # So'rov va javob
    # ------------------------------------------------------------------

    #: Yuborilgan JSON tana (imzo shu tanadan hisoblanadi)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONType, nullable=False)
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: Javob tanasi — 4KB dan kesilgan holda saqlanadi
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Tarmoq/ichki xato matni (HTTP javob bo'lmagan hollarda)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: Yuborish davomiyligi (millisekundda)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # ------------------------------------------------------------------
    # Bog'lanishlar
    # ------------------------------------------------------------------

    webhook: Mapped[Webhook] = relationship(
        "Webhook", back_populates="deliveries", lazy="raise"
    )
    job: Mapped[Job | None] = relationship(
        "Job", back_populates="webhook_deliveries", lazy="raise"
    )

    # ------------------------------------------------------------------
    # Yordamchi xossalar
    # ------------------------------------------------------------------

    @property
    def is_successful(self) -> bool:
        """Yuborish muvaffaqiyatli tugadimi?"""
        return DeliveryStatus(self.status) is DeliveryStatus.SUCCESS

    @property
    def is_exhausted(self) -> bool:
        """Barcha urinishlar tugadimi (boshqa urinilmaydi)?"""
        return DeliveryStatus(self.status) is DeliveryStatus.EXHAUSTED

    @property
    def is_terminal(self) -> bool:
        """Yuborish yakuniy holatdami (muvaffaqiyat yoki urinishlar tugashi)?"""
        return self.is_successful or self.is_exhausted


__all__ = ["WebhookDelivery"]
