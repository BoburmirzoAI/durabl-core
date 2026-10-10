"""Durabl — `webhooks` jadvali uchun repository.

Faqat SQL: biznes qoidalar (SSRF tekshiruvi, imzo kaliti yaratish, avtomatik
o'chirish chegarasi) `webhook_service` da qoladi. Bu qatlam `commit()`
qilmaydi — tranzaksiya chegarasini service belgilaydi.

**"Faol" tushunchasi ikki ustundan iborat** (`app/models/webhook.py` ga qara):

* `is_active` — mijozning o'z qarori (UI'dagi tugma);
* `disabled_at` — tizim qarori (ketma-ket xatolar chegarasidan oshdi).

Shuning uchun `active_only=True` filtri IKKALASINI ham tekshiradi:
`is_active IS TRUE AND disabled_at IS NULL` — bu `Webhook.is_enabled`
xossasining SQL ko'rinishi.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ColumnElement, func, select

from app.constants import WebhookEvent
from app.models.webhook import Webhook
from app.repositories.base import BaseRepository


class WebhookRepository(BaseRepository[Webhook]):
    """Mijoz webhook sozlamalari bilan ishlash."""

    model = Webhook

    # ------------------------------------------------------------------
    # O'qish
    # ------------------------------------------------------------------

    async def list_for_user(
        self,
        user_id: uuid.UUID | str,
        active_only: bool = False,
    ) -> list[Webhook]:
        """Foydalanuvchining webhook'lari (yangisidan boshlab).

        `active_only=True` bo'lsa, faqat haqiqatan ishlayotganlari qaytadi:
        mijoz yoqqan (`is_active`) va tizim o'chirmagan (`disabled_at IS NULL`).
        """
        stmt = select(Webhook).where(*self._user_conditions(user_id, active_only))
        stmt = stmt.order_by(Webhook.created_at.desc())
        result = await self._execute(stmt)
        return list(result.scalars().all())

    async def get_for_user(
        self,
        webhook_id: uuid.UUID | str,
        user_id: uuid.UUID | str,
    ) -> Webhook | None:
        """Webhook'ni EGASI bo'yicha ham tekshirib oladi.

        Boshqa foydalanuvchining webhook'i so'ralsa `None` qaytadi — shu
        tufayli API qatlami "topilmadi" deb javob beradi va yozuvning
        mavjudligi oshkor bo'lmaydi (IDOR himoyasi).
        """
        stmt = select(Webhook).where(
            Webhook.id == self._coerce_id(webhook_id),
            Webhook.user_id == self._coerce_id(user_id),
        )
        result = await self._execute(stmt)
        return result.scalars().first()

    async def active_for_event(
        self,
        user_id: uuid.UUID | str,
        event: WebhookEvent | str,
    ) -> list[Webhook]:
        """Berilgan hodisaga obuna bo'lgan FAOL webhook'lar.

        `events` — JSON ustun va unga SQL filtri yozish dialektga bog'liq
        (PostgreSQL'da `@>`, SQLite'da `json_each`). Shuning uchun faol
        webhook'lar SQL bilan olinadi, hodisa bo'yicha saralash esa Python
        tomonida bajariladi: bitta foydalanuvchida webhook'lar soni kam
        (odatda birnechta), demak bu arzon va dialektdan mustaqil.
        """
        event_value = WebhookEvent(event).value
        candidates = await self.list_for_user(user_id, active_only=True)
        return [webhook for webhook in candidates if event_value in (webhook.events or [])]

    async def count_for_user(
        self,
        user_id: uuid.UUID | str,
        active_only: bool = False,
    ) -> int:
        """Foydalanuvchi webhook'larining soni (reja limitini tekshirish uchun)."""
        stmt = (
            select(func.count())
            .select_from(Webhook)
            .where(*self._user_conditions(user_id, active_only))
        )
        result = await self._execute(stmt)
        return int(result.scalar_one() or 0)

    # ------------------------------------------------------------------
    # Yordamchilar
    # ------------------------------------------------------------------

    def _user_conditions(
        self,
        user_id: uuid.UUID | str,
        active_only: bool,
    ) -> list[ColumnElement[Any]]:
        """`list_for_user` va `count_for_user` uchun umumiy WHERE shartlari."""
        conditions: list[ColumnElement[Any]] = [Webhook.user_id == self._coerce_id(user_id)]
        if active_only:
            conditions.append(Webhook.is_active.is_(True))
            conditions.append(Webhook.disabled_at.is_(None))
        return conditions


__all__ = ["WebhookRepository"]
