"""Durabl — `login_events` jadvali: kirish urinishlari jurnali.

**Muvaffaqiyatsiz urinishlar ham yoziladi** — buzilgan hisobni aniqlashda
eng qimmatli ma'lumot aynan shu: begona IP'dan ketma-ket 20 ta
`FAILED_PASSWORD`, keyin bitta `SUCCESS` — bu hujum izi.

`user_id` NULLABLE va `SET NULL`: mavjud bo'lmagan email bilan kirishga
urinish ham yozilishi kerak (foydalanuvchi yo'q, lekin urinish bor), va
foydalanuvchi o'chirilganda jurnal saqlanib qolishi kerak. Shuning uchun
`email` ustuni alohida saqlanadi — `user_id` yo'qolgandan keyin ham
"kim bo'lishga harakat qilgan" ma'lum bo'ladi.

Parol yoki token bu jadvalga HECH QACHON yozilmaydi — hatto hash
ko'rinishida ham. Noto'g'ri parolni saqlash hujumchiga mijozning boshqa
saytdagi parolini beradi.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import LoginMethod, LoginResult
from app.models.base import (
    Base,
    DateTimeTZ,
    UUIDPrimaryKeyMixin,
    UUIDType,
    enum_column,
)

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from app.models.user import User


class LoginEvent(UUIDPrimaryKeyMixin, Base):
    """Bitta kirish urinishi.

    `TimestampMixin` ATAYLAB ishlatilmaydi: jurnal yozuvi o'zgarmaydi,
    shuning uchun `updated_at` ma'nosiz. Vaqt `occurred_at` da.
    """

    __tablename__ = "login_events"

    #: Kim kirishga urindi. `NULL` — bunday foydalanuvchi topilmadi
    #: yoki keyinchalik o'chirildi.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    #: Urinishda kiritilgan email — `user_id` yo'qolsa ham qoladi
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)

    # ------------------------------------------------------------------
    # Natija
    # ------------------------------------------------------------------

    occurred_at: Mapped[datetime] = mapped_column(DateTimeTZ, nullable=False, index=True)
    result: Mapped[LoginResult] = mapped_column(
        enum_column(LoginResult), nullable=False, index=True
    )
    method: Mapped[LoginMethod] = mapped_column(enum_column(LoginMethod), nullable=False)
    #: Muvaffaqiyatsizlik tafsiloti (`account inactive`, `rate limited`) —
    #: mijozga KO'RSATILMAYDI, faqat admin tekshiruvi uchun
    detail: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ------------------------------------------------------------------
    # Qayerdan
    # ------------------------------------------------------------------

    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    location: Mapped[str | None] = mapped_column(String(128), nullable=True)
    browser: Mapped[str | None] = mapped_column(String(64), nullable=True)
    os: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ------------------------------------------------------------------
    # Bog'lanishlar
    # ------------------------------------------------------------------

    user: Mapped[User | None] = relationship("User", back_populates="login_events", lazy="raise")

    # ------------------------------------------------------------------
    # Indekslar
    # ------------------------------------------------------------------

    __table_args__ = (
        #: "Mening kirish tarixim" — eng yangi birinchi
        Index("ix_login_events_user_id_occurred_at", "user_id", "occurred_at"),
        #: Brute-force aniqlash: bitta IP'dan oxirgi urinishlar
        Index("ix_login_events_ip_address_occurred_at", "ip_address", "occurred_at"),
    )

    # ------------------------------------------------------------------
    # Yordamchi xossalar
    # ------------------------------------------------------------------

    @property
    def succeeded(self) -> bool:
        return self.result is LoginResult.SUCCESS


__all__ = ["LoginEvent"]
