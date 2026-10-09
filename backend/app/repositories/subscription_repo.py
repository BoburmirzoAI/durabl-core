"""Durabl — `subscriptions` jadvali uchun repository.

Bir foydalanuvchiga bitta obuna to'g'ri keladi (`user_id` unique), shuning
uchun bu qatlamning asosiy vazifasi — obuna BORLIGINI kafolatlash
(`ensure_for_user`). Ro'yxatdan o'tgan har bir foydalanuvchi FREE rejada
boshlaydi, lekin yozuv har doim mavjud bo'lishi shart emas (masalan eski
foydalanuvchilar yoki migratsiyadan keyin), shuning uchun kvota tekshiruvi
yozuvni "yo'q bo'lsa yaratish" yo'li bilan oladi.

Reja limitlari DB'da SAQLANMAYDI — `Subscription.limits` xossasi orqali
`app.constants.PLAN_LIMITS` dan olinadi. Bu qatlam faqat reja NOMI bilan
ishlaydi.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.constants import PlanType
from app.exceptions import DatabaseError
from app.models.subscription import Subscription
from app.repositories.base import BaseRepository
from app.utils.time_utils import utcnow


class SubscriptionRepository(BaseRepository[Subscription]):
    """Foydalanuvchi obunasi bilan ishlash."""

    model = Subscription

    # ------------------------------------------------------------------
    # O'qish
    # ------------------------------------------------------------------

    async def get_for_user(
        self, user_id: uuid.UUID | str
    ) -> Subscription | None:
        """Foydalanuvchining obunasi (yo'q bo'lsa `None`)."""
        stmt = select(Subscription).where(
            Subscription.user_id == self._coerce_id(user_id)
        )
        result = await self._execute(stmt)
        return result.scalars().first()

    async def list_by_plan(self, plan: PlanType | str) -> list[Subscription]:
        """Berilgan rejadagi obunalar (admin hisobotlari uchun)."""
        stmt = (
            select(Subscription)
            .where(Subscription.plan == PlanType(plan))
            .order_by(Subscription.started_at.desc())
        )
        result = await self._execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Yozish
    # ------------------------------------------------------------------

    async def ensure_for_user(
        self, user_id: uuid.UUID | str
    ) -> Subscription:
        """Obunani qaytaradi; yo'q bo'lsa FREE reja bilan yaratadi.

        **Poyga (race) holati.** Ikki parallel so'rov bir vaqtda obuna
        yaratishga urinishi mumkin — `user_id` unique bo'lgani uchun biri
        `IntegrityError` oladi. Shuning uchun INSERT SAVEPOINT ichida
        bajariladi: xato bo'lsa faqat shu savepoint qaytariladi (tashqi
        tranzaksiya buzilmaydi), so'ng yozuv qayta o'qiladi va g'olibning
        obunasi qaytariladi.
        """
        existing = await self.get_for_user(user_id)
        if existing is not None:
            return existing

        subscription = Subscription(
            user_id=self._coerce_id(user_id),
            plan=PlanType.FREE,
            started_at=utcnow(),
            is_active=True,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(subscription)
                await self.session.flush()
        except IntegrityError as exc:
            # Boshqa tranzaksiya ulgurdi — uning yozuvini o'qiymiz
            winner = await self.get_for_user(user_id)
            if winner is None:
                raise DatabaseError(
                    f"Obuna yaratilmadi: {exc.orig}",
                    details={"table": Subscription.__tablename__},
                ) from exc
            return winner
        return subscription


__all__ = ["SubscriptionRepository"]
