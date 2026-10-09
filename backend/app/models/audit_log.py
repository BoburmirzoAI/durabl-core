"""Durabl — `audit_logs` jadvali: admin harakatlari jurnali.

Har bir admin amali (foydalanuvchini bloklash, job'ni bekor qilish, DLQ'ni
tozalash, rejani o'zgartirish) shu yerga yoziladi. Jurnal yozuvlari
o'zgartirilmaydi — faqat qo'shiladi.

`admin_id` `SET NULL` bilan bog'langan: admin hisobi o'chirilsa ham
harakat tarixi saqlanib qoladi (kim qilganini `details` ichida ham
dublikat qilib qoldirish mumkin).

`TimestampMixin` ishlatiladi — `updated_at` bu jadvalda amalda kerak emas,
lekin barcha modellar bir xil shaklda bo'lishi uchun (oddiylik) qoldirilgan.
`action` enumi `length=48` bilan: qiymatlar `"api_key.revoked"` kabi uzun.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import AuditAction
from app.models.base import (
    Base,
    JSONType,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    UUIDType,
    enum_column,
)

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from app.models.user import User


class AuditLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Admin harakati haqida bitta jurnal yozuvi."""

    __tablename__ = "audit_logs"

    #: Harakatni bajargan admin; o'chirilsa `NULL` bo'ladi
    admin_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: Harakat turi (`AuditAction`)
    action: Mapped[AuditAction] = mapped_column(
        enum_column(AuditAction, length=48), nullable=False, index=True
    )

    # ------------------------------------------------------------------
    # Harakat obyekti
    # ------------------------------------------------------------------

    #: Obyekt turi: `"user"`, `"job"`, `"api_key"` ...
    target_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    #: Obyekt identifikatori (matn ko'rinishida — UUID yoki boshqa kalit)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    #: Qo'shimcha tafsilotlar (eski/yangi qiymatlar, sabab ...)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)

    # ------------------------------------------------------------------
    # So'rov konteksti
    # ------------------------------------------------------------------

    #: IPv4 yoki IPv6 manzil (45 belgi — IPv6 uchun yetarli)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # ------------------------------------------------------------------
    # Bog'lanishlar
    # ------------------------------------------------------------------

    #: Teskari tomoni yo'q: jurnal foydalanuvchi o'chirilgandan keyin ham qoladi
    admin: Mapped[User | None] = relationship(
        "User", foreign_keys="AuditLog.admin_id", lazy="raise"
    )

    # ------------------------------------------------------------------
    # Yordamchi xossalar
    # ------------------------------------------------------------------

    @property
    def target_ref(self) -> str | None:
        """Obyektga qisqa havola: `"job:3f1c..."`; obyekt yo'q bo'lsa `None`."""
        if self.target_type is None and self.target_id is None:
            return None
        return f"{self.target_type or '?'}:{self.target_id or '?'}"

    @property
    def is_system_action(self) -> bool:
        """Harakat tizim nomidan bajarilganmi (admin ko'rsatilmagan)?"""
        return self.admin_id is None


__all__ = ["AuditLog"]
