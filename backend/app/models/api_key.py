"""Durabl — `api_keys` jadvali: mijoz API kalitlari.

Xom kalit (`durabl_...`) DB'da SAQLANMAYDI — faqat uning SHA-256 hash'i
(`key_hash`) yoziladi. Mijozga kalit bir martagina, yaratish javobida
ko'rsatiladi. Keyinchalik UI'da faqat `key_prefix` va `last_four` orqali
niqoblangan ko'rinish ko'rsatiladi.

Autentifikatsiya oqimi: `X-API-Key` header -> `hash_api_key()` -> `key_hash`
bo'yicha unique indeks orqali qidirish (shuning uchun `key_hash` unique).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    DateTimeTZ,
    JSONType,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    UUIDType,
)
from app.utils.time_utils import is_expired

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from app.models.user import User


class ApiKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Foydalanuvchining API kaliti (hash holda saqlanadi)."""

    __tablename__ = "api_keys"

    #: Kalit egasi
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ------------------------------------------------------------------
    # Kalitning o'zi
    # ------------------------------------------------------------------

    #: SHA-256 hex digest (64 belgi) — autentifikatsiyada shu bo'yicha qidiriladi
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    #: Mijoz ko'radigan prefiks (masalan `durabl_`) — niqoblangan ko'rinish uchun
    key_prefix: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Kalitning oxirgi 4 belgisi — foydalanuvchi kalitni tanib olishi uchun
    last_four: Mapped[str] = mapped_column(String(8), nullable=False)
    #: Mijoz bergan nom ("CI pipeline", "Lokal test" ...)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    #: Ruxsat doiralari ro'yxati; bo'sh ro'yxat — barcha standart huquqlar
    scopes: Mapped[list[str]] = mapped_column(JSONType, default=list, nullable=False)

    # ------------------------------------------------------------------
    # Hayot sikli
    # ------------------------------------------------------------------

    #: Oxirgi ishlatilgan vaqt (`ApiKeyRepository.touch` yangilaydi)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)
    #: Amal qilish muddati; `None` — muddatsiz
    expires_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)
    #: Bekor qilingan vaqt; `None` — kalit bekor qilinmagan
    revoked_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)

    # ------------------------------------------------------------------
    # Bog'lanishlar
    # ------------------------------------------------------------------

    user: Mapped[User] = relationship("User", back_populates="api_keys", lazy="raise")

    # ------------------------------------------------------------------
    # Yordamchi xossalar
    # ------------------------------------------------------------------

    @property
    def is_valid(self) -> bool:
        """Kalit ishlatilishi mumkinmi: bekor qilinmagan va muddati o'tmagan."""
        return self.revoked_at is None and not is_expired(self.expires_at)

    @property
    def is_revoked(self) -> bool:
        """Kalit bekor qilinganmi?"""
        return self.revoked_at is not None

    @property
    def masked(self) -> str:
        """UI'da ko'rsatiladigan niqoblangan ko'rinish: `durabl_...a1b2`."""
        return f"{self.key_prefix}...{self.last_four}"


__all__ = ["ApiKey"]
