"""Durabl — `user_sessions` jadvali: faol sessiyalar va ularni bekor qilish.

**Nega JWT ustiga jadval kerak.** Durabl access token sifatida JWT
ishlatadi, JWT esa o'z tabiatiga ko'ra bekor qilinmaydi: imzo to'g'ri
bo'lsa, muddati tugaguncha amal qiladi. "Boshqa qurilmalardan chiqish"
tugmasi ishlashi uchun server tomonida ro'yxat kerak — tokendagi `sid`
(session id) shu jadvalda tekshiriladi, yozuv `revoked_at` bilan
belgilansa token darhol kuchini yo'qotadi.

Shu sababli `token_hash` saqlanadi, tokenning o'zi emas: DB o'qib
olingan taqdirda ham undan ishlaydigan token tiklanmaydi. Hash — SHA-256
(`api_keys.key_hash` bilan bir xil yondashuv).

Qurilma ma'lumotlari (`browser`, `os`, `device_type`) User-Agent'dan
bir marta — sessiya yaratilganda — ajratiladi va saqlanadi. Har so'rovda
qayta tahlil qilish ortiqcha ish, bundan tashqari User-Agent o'zgarishi
(brauzer yangilanishi) sessiyani boshqa qurilmaga o'xshatib qo'yardi.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import DeviceType
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


class UserSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bitta faol (yoki bekor qilingan) sessiya."""

    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ------------------------------------------------------------------
    # Token
    # ------------------------------------------------------------------

    #: Refresh tokenning SHA-256 hashi — tokenning o'zi SAQLANMAYDI
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    #: Sessiya qachon o'z-o'zidan tugaydi (refresh token muddati)
    expires_at: Mapped[datetime] = mapped_column(DateTimeTZ, nullable=False, index=True)
    #: Bekor qilingan vaqt. `NULL` — hamon amal qiladi.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)

    # ------------------------------------------------------------------
    # Qurilma (User-Agent'dan bir marta ajratilgan)
    # ------------------------------------------------------------------

    browser: Mapped[str | None] = mapped_column(String(64), nullable=True)
    os: Mapped[str | None] = mapped_column(String(64), nullable=True)
    device_type: Mapped[DeviceType] = mapped_column(enum_column(DeviceType), nullable=False)
    #: To'liq User-Agent — tahlil xato bo'lsa haqiqatni tiklash uchun
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # ------------------------------------------------------------------
    # Joylashuv
    # ------------------------------------------------------------------

    #: IPv6 ham sig'ishi kerak (maksimal 45 belgi)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    #: GeoIP natijasi (`Tashkent, UZ`) — aniq emas, faqat ko'rsatish uchun
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # ------------------------------------------------------------------
    # Faollik
    # ------------------------------------------------------------------

    #: Oxirgi so'rov vaqti. ATAYLAB har so'rovda yangilanmaydi —
    #: `SESSION_ACTIVITY_THROTTLE_SECONDS` oynasida bir marta, aks holda
    #: har GET so'rov DB'ga yozish bo'lib qolardi.
    last_active_at: Mapped[datetime] = mapped_column(DateTimeTZ, nullable=False)

    # ------------------------------------------------------------------
    # Bog'lanishlar
    # ------------------------------------------------------------------

    user: Mapped[User] = relationship("User", back_populates="sessions", lazy="raise")

    # ------------------------------------------------------------------
    # Indekslar
    # ------------------------------------------------------------------

    __table_args__ = (
        #: "Faol sessiyalarim" so'rovi: `user_id` + `revoked_at IS NULL`
        Index("ix_user_sessions_user_id_revoked_at", "user_id", "revoked_at"),
    )

    # ------------------------------------------------------------------
    # Yordamchi xossalar
    # ------------------------------------------------------------------

    def is_valid(self, *, now: datetime) -> bool:
        """Sessiya hamon ishlaydimi: bekor qilinmagan va muddati tugamagan.

        `now` ataylab argument — vaqtni test ichida boshqarish uchun
        (modul darajasidagi `utcnow()` ni mock qilishdan ko'ra ishonchliroq).
        """
        return self.revoked_at is None and self.expires_at > now

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    @property
    def device_label(self) -> str:
        """UI uchun qisqa nom: `Chrome on macOS`, aniqlanmasa `Unknown device`."""
        if self.browser and self.os:
            return f"{self.browser} on {self.os}"
        return self.browser or self.os or "Unknown device"


__all__ = ["UserSession"]
