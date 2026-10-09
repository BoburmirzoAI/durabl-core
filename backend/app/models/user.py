"""Durabl — `users` jadvali: platforma foydalanuvchilari.

Foydalanuvchi — tizimdagi barcha resurslarning egasi: job'lar, API kalitlar,
webhook'lar, obuna va foydalanish hisoblari. Foydalanuvchi o'chirilganda
unga tegishli yozuvlar DB darajasida `ON DELETE CASCADE` bilan o'chadi
(`audit_logs` va `dlq_entries.resolved_by_id` esa `SET NULL` bo'ladi — admin
harakatlari tarixi saqlanib qolishi uchun).

Barcha `relationship()` lar `lazy="raise"` — async muhitda tasodifiy lazy
yuklash `MissingGreenlet` xatosiga olib keladi, shuning uchun kerakli
bog'lanishlar repository qatlamida `selectinload()` bilan ochiq so'raladi.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, DateTimeTZ, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from app.models.api_key import ApiKey
    from app.models.dlq_entry import DlqEntry
    from app.models.job import Job
    from app.models.subscription import Subscription
    from app.models.usage_record import UsageRecord
    from app.models.webhook import Webhook


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Foydalanuvchi hisobi."""

    __tablename__ = "users"

    # ------------------------------------------------------------------
    # Identifikatsiya
    # ------------------------------------------------------------------

    #: Email — login identifikatori (RFC bo'yicha maksimal 320 belgi)
    email: Mapped[str] = mapped_column(
        String(320), unique=True, index=True, nullable=False
    )
    #: bcrypt hash (`app.utils.security.hash_password`) — xom parol saqlanmaydi
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)
    #: To'liq ism — ixtiyoriy, UI'da ko'rsatish uchun
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ------------------------------------------------------------------
    # Holat va huquqlar
    # ------------------------------------------------------------------

    #: Faol emas bo'lsa — login va job yuborish taqiqlanadi
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default=true(), nullable=False
    )
    #: Admin panelga kirish huquqi
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )
    #: Oxirgi muvaffaqiyatli login vaqti (`AuthService.login` yangilaydi)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)

    # ------------------------------------------------------------------
    # Bog'lanishlar
    # ------------------------------------------------------------------

    api_keys: Mapped[list[ApiKey]] = relationship(
        "ApiKey",
        back_populates="user",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    jobs: Mapped[list[Job]] = relationship(
        "Job",
        back_populates="user",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    webhooks: Mapped[list[Webhook]] = relationship(
        "Webhook",
        back_populates="user",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    #: Bitta foydalanuvchi — bitta obuna (`subscriptions.user_id` unique)
    subscription: Mapped[Subscription | None] = relationship(
        "Subscription",
        back_populates="user",
        uselist=False,
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    usage_records: Mapped[list[UsageRecord]] = relationship(
        "UsageRecord",
        back_populates="user",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    #: DLQ yozuvlari — `dlq_entries.user_id` bo'yicha (egasi), `resolved_by_id` emas
    dlq_entries: Mapped[list[DlqEntry]] = relationship(
        "DlqEntry",
        back_populates="user",
        foreign_keys="DlqEntry.user_id",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # ------------------------------------------------------------------
    # Yordamchi xossalar
    # ------------------------------------------------------------------

    @property
    def display_name(self) -> str:
        """UI'da ko'rsatiladigan nom: to'liq ism bo'lsa u, aks holda email."""
        return self.full_name or self.email

    @property
    def has_logged_in(self) -> bool:
        """Foydalanuvchi hech bo'lmasa bir marta kirganmi?"""
        return self.last_login_at is not None


__all__ = ["User"]
