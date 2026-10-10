"""Durabl — `webhook_deliveries` jadvali uchun repository.

Webhook "at-least-once" kafolatining DB tomoni shu yerda: har bir yuborish
urinishi jadvalda qoladi, shuning uchun server qulasa ham `webhook_sender`
qayta ko'tarilganda `pending_retries()` orqali tugallanmagan yuborishlarni
topadi va davom ettiradi.

Bu qatlam HTTP so'rov YUBORMAYDI va `commit()` qilmaydi — faqat SQL.
Haqiqiy yuborish va retry siyosati (`webhook_policy()`) `webhook_service` da.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.constants import DeliveryStatus
from app.models.webhook_delivery import WebhookDelivery
from app.repositories.base import BaseRepository
from app.utils.time_utils import utcnow

#: Standart sahifa hajmi — `app.schemas.base.DEFAULT_PAGE_SIZE` bilan bir xil
#: (repository qatlami `schemas`ga bog'lanmasligi uchun takrorlangan).
DEFAULT_PAGE_SIZE = 20

#: Hali tugallanmagan — qayta urinish mumkin bo'lgan holatlar
RETRYABLE_STATUSES: tuple[DeliveryStatus, ...] = (
    DeliveryStatus.PENDING,
    DeliveryStatus.RETRYING,
)


class WebhookDeliveryRepository(BaseRepository[WebhookDelivery]):
    """Webhook yuborish tarixi va navbatdagi qayta urinishlar."""

    model = WebhookDelivery

    # ------------------------------------------------------------------
    # O'qish
    # ------------------------------------------------------------------

    async def list_for_webhook(
        self,
        webhook_id: uuid.UUID | str,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[WebhookDelivery], int]:
        """Bitta webhook'ning yuborish tarixi: `(yozuvlar, umumiy_son)`.

        Tartib: yangisidan boshlab (`created_at DESC`). Umumiy son
        `PaginatedResponse` metama'lumotlari uchun qaytariladi.
        """
        condition = WebhookDelivery.webhook_id == self._coerce_id(webhook_id)

        total_stmt = select(func.count()).select_from(WebhookDelivery).where(condition)
        total_result = await self._execute(total_stmt)
        total = int(total_result.scalar_one() or 0)

        stmt = (
            select(WebhookDelivery)
            .where(condition)
            .order_by(WebhookDelivery.created_at.desc())
            .offset(max(0, (page - 1) * page_size))
            .limit(page_size)
        )
        result = await self._execute(stmt)
        return list(result.scalars().all()), total

    async def pending_retries(
        self,
        now: datetime,
        limit: int = 100,
    ) -> list[WebhookDelivery]:
        """Vaqti kelgan qayta urinishlar (eng kechikkanidan boshlab).

        Shart: holat `PENDING` yoki `RETRYING`, va `next_retry_at <= now`.
        `next_retry_at` indekslangan, shuning uchun bu so'rov `webhook_sender`
        halqasida arzon turadi.
        """
        stmt = (
            select(WebhookDelivery)
            .where(
                WebhookDelivery.status.in_(RETRYABLE_STATUSES),
                WebhookDelivery.next_retry_at.is_not(None),
                WebhookDelivery.next_retry_at <= now,
            )
            .order_by(WebhookDelivery.next_retry_at.asc())
            .limit(limit)
        )
        result = await self._execute(stmt)
        return list(result.scalars().all())

    async def count_by_status(
        self,
        webhook_id: uuid.UUID | str | None = None,
    ) -> dict[str, int]:
        """Holatlar kesimidagi yuborishlar soni (monitoring uchun)."""
        stmt = select(WebhookDelivery.status, func.count()).group_by(WebhookDelivery.status)
        if webhook_id is not None:
            stmt = stmt.where(WebhookDelivery.webhook_id == self._coerce_id(webhook_id))
        result = await self._execute(stmt)
        counts: dict[str, int] = {status.value: 0 for status in DeliveryStatus}
        for status, amount in result.all():
            counts[DeliveryStatus(status).value] = int(amount or 0)
        return counts

    # ------------------------------------------------------------------
    # Yozish
    # ------------------------------------------------------------------

    async def record_attempt(
        self,
        delivery: WebhookDelivery,
        **fields: Any,
    ) -> WebhookDelivery:
        """Urinish natijasini yozadi (`status`, `response_code`, `duration_ms` ...).

        Qulaylik qoidalari:

        * `status=SUCCESS` berilsa va `delivered_at` ko'rsatilmasa — hozirgi
          vaqt qo'yiladi, `next_retry_at` esa `None` ga tushadi (boshqa
          urinilmaydi).
        * `status=EXHAUSTED` berilsa — `next_retry_at` ham `None` qilinadi.
        * `attempt` AVTOMATIK oshmaydi: uni chaqiruvchi ochiq uzatadi, chunki
          retry siyosati (`webhook_policy()`) urinish raqamini o'zi biladi.
        """
        values = dict(fields)
        status = values.get("status")
        if status is not None:
            status = DeliveryStatus(status)
            values["status"] = status
            if status is DeliveryStatus.SUCCESS:
                values.setdefault("delivered_at", utcnow())
                values["next_retry_at"] = None
            elif status is DeliveryStatus.EXHAUSTED:
                values["next_retry_at"] = None
        return await self.update(delivery, **values)


__all__ = ["DEFAULT_PAGE_SIZE", "RETRYABLE_STATUSES", "WebhookDeliveryRepository"]
