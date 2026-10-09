"""Durabl — `recovery_codes` jadvali: 2FA uchun bir martalik tiklash kodlari.

Mijoz telefonini yo'qotsa, TOTP kodi olinmaydi va hisob butunlay
yopilib qoladi. Tiklash kodlari — aynan shu holat uchun: 2FA yoqilganda
bir to'plam kod beriladi, har biri **bir marta** ishlaydi.

**Kod hash ko'rinishida saqlanadi** (`code_hash`), xom holda emas:
tiklash kodi amalda parolga teng kuchda, DB o'qilsa 2FA butunlay
ma'nosiz bo'lib qolardi. Shu sababli mijozga kodlar FAQAT yaratilgan
paytda bir marta ko'rsatiladi va qayta ko'rsatib bo'lmaydi.

Ishlatilgan kod o'chirilmaydi, `used_at` bilan belgilanadi: "qachon va
qaysi IP'dan tiklash kodi ishlatilgan" — xavfsizlik tekshiruvida kerak.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Final

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import (
    Base,
    DateTimeTZ,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    UUIDType,
)

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from app.models.user import User

#: 2FA yoqilganda beriladigan kodlar soni.
#: 10 — sanoat standarti (GitHub, Google ham shuncha beradi).
RECOVERY_CODE_COUNT: Final[int] = 10


class RecoveryCode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Bitta bir martalik tiklash kodi."""

    __tablename__ = "recovery_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    #: Kodning SHA-256 hashi — kodning o'zi SAQLANMAYDI
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Ishlatilgan vaqt. `NULL` — hali ishlatilmagan.
    used_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)
    #: Qaysi IP'dan ishlatilgan (xavfsizlik tekshiruvi uchun)
    used_from_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)

    user: Mapped[User] = relationship("User", back_populates="recovery_codes", lazy="raise")

    __table_args__ = (
        #: Bitta foydalanuvchida bir xil hash ikki marta bo'lmasin —
        #: generator tasodifiy takrorlasa, ikkinchisi yozilmaydi
        Index("uq_recovery_codes_user_id_code_hash", "user_id", "code_hash", unique=True),
        #: "Qolgan kodlar soni" so'rovi: `user_id` + `used_at IS NULL`
        Index("ix_recovery_codes_user_id_used_at", "user_id", "used_at"),
    )

    @property
    def is_used(self) -> bool:
        return self.used_at is not None


__all__ = ["RECOVERY_CODE_COUNT", "RecoveryCode"]
