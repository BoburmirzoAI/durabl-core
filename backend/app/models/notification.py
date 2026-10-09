"""Durabl — `notifications` jadvali: ilova ichidagi bildirishnomalar.

Panel qo'ng'irog'i va `/notifications` sahifasi shu jadvaldan o'qiydi.
Webhook'dan farqi: webhook mijoz TIZIMIGA xabar beradi, bildirishnoma
mijoz O'ZIGA ko'rsatiladi. Ikkisi bir hodisadan tug'ilishi mumkin.

**O'qilganlik ikki ustun bilan** emas, bitta `read_at` bilan ifodalanadi:
`NULL` — o'qilmagan. `is_read` boolean + `read_at` juftligi ikki manbadan
haqiqat yaratadi va ular bir-biriga mos kelmay qolishi mumkin.

`href` — bosilganda qayerga olib borishi. Backend to'ldiradi, chunki
yo'l tuzilishi (`/jobs/{id}`) frontend bilan shartnoma; frontendda
`kind` bo'yicha qayta hisoblash har yangi tur uchun ikki joyda
o'zgartirish talab qilardi.

**Tozalash:** yozuvlar cheksiz to'planmaydi — `cleanup` worker
`NOTIFICATION_RETENTION_DAYS` dan eski o'qilgan bildirishnomalarni
o'chiradi. O'qilmaganlar saqlanadi (mijoz hali ko'rmagan).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import NotificationKind, NotificationSeverity
from app.models.base import (
    Base,
    DateTimeTZ,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    UUIDType,
    enum_column,
)

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from app.models.user import User


class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bitta ilova ichidagi bildirishnoma."""

    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ------------------------------------------------------------------
    # Mazmun
    # ------------------------------------------------------------------

    kind: Mapped[NotificationKind] = mapped_column(
        enum_column(NotificationKind), nullable=False, index=True
    )
    severity: Mapped[NotificationSeverity] = mapped_column(
        enum_column(NotificationSeverity), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(String(2048), nullable=False)
    #: Bosilganda ochiladigan ilova ichidagi yo'l (`/jobs/{id}`).
    #: `NULL` — havolasiz bildirishnoma.
    href: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # ------------------------------------------------------------------
    # Holat
    # ------------------------------------------------------------------

    #: O'qilgan vaqt. `NULL` — o'qilmagan (yagona haqiqat manbasi).
    read_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)

    # ------------------------------------------------------------------
    # Manba — ixtiyoriy havola
    # ------------------------------------------------------------------

    #: Qaysi resurs sabab bo'ldi (`job`, `webhook`, `dlq_entry`).
    #: Foreign key ATAYLAB qo'yilmaydi: turli jadvallarga ishora qiladi
    #: va manba o'chirilganda bildirishnoma yo'qolib ketmasligi kerak.
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_id: Mapped[uuid.UUID | None] = mapped_column(UUIDType, nullable=True)

    # ------------------------------------------------------------------
    # Bog'lanishlar
    # ------------------------------------------------------------------

    user: Mapped[User] = relationship("User", back_populates="notifications", lazy="raise")

    # ------------------------------------------------------------------
    # Indekslar
    # ------------------------------------------------------------------

    __table_args__ = (
        #: Asosiy so'rov: mening bildirishnomalarim, eng yangi birinchi
        Index("ix_notifications_user_id_created_at", "user_id", "created_at"),
        #: Qo'ng'iroqdagi o'qilmaganlar soni: `user_id` + `read_at IS NULL`
        Index("ix_notifications_user_id_read_at", "user_id", "read_at"),
    )

    # ------------------------------------------------------------------
    # Yordamchi xossalar
    # ------------------------------------------------------------------

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    @property
    def has_link(self) -> bool:
        return self.href is not None


__all__ = ["Notification"]
