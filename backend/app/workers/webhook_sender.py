"""Durabl — webhook yetkazuvchi worker.

`WebhookService.dispatch()` job hodisasi uchun `webhook_deliveries` yozuvini
yaratadi va uning `id` sini `RedisKeys.WEBHOOK_QUEUE` ro'yxatiga qo'yadi.
Yetkazishning O'ZI shu worker'da bajariladi — HTTP so'rov sekin (mijoz
serveri 10 soniya javob bermasligi mumkin) va uni job bajarish yo'lida
kutib turish worker'ning o'tkazuvchanligini yo'q qilardi.

`tick()` IKKI manbadan oladi:

1. **Redis navbati** — "darhol yuborish" signali. `LPOP` bilan partiya
   olinadi va yetkazishlar PARALLEL bajariladi (har biri boshqa mijozning
   serveriga ketadi, shuning uchun navbatda kutishning ma'nosi yo'q).
   Parallellik `asyncio.Semaphore` bilan `MAX_PARALLEL_DELIVERIES` ga
   cheklangan — cheksiz parallel so'rov fayl deskriptorlarini va chiquvchi
   ulanish limitini tugatardi.
2. **DB** (`retry_pending()`) — vaqti kelgan qayta urinishlar va Redis
   navbati yo'qolgan yozuvlar. Bu Redis'ning ZAXIRASI: `dispatch()` yozuvni
   `next_retry_at=utcnow()` bilan yaratadi, ya'ni Redis butunlay ishlamasa
   ham webhook yuboriladi (faqat bir sikl kechikish bilan).

`exclusive = False` — bir nechta nusxa parallel ishlashi MUMKIN va bu
ataylab: `LPOP` har `id` ni faqat BITTA nusxaga beradi, `deliver()` esa
yakuniy holatdagi yozuvni qayta yubormaydi (idempotent). Ya'ni gorizontal
masshtablash qo'shimcha sozlamasiz ishlaydi.

Har bir delivery ALOHIDA sessiyada bajariladi: `deliver()` o'z `commit()`
ini qiladi va bitta `AsyncSession` ni parallel vazifalarda ishlatish
SQLAlchemy'da taqiqlanadi.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Final

from app.config import settings
from app.constants import RedisKeys
from app.database import session_scope
from app.logging_config import get_logger
from app.services.webhook_service import WebhookService
from app.workers.runner import PeriodicWorker, main_entry

logger = get_logger(__name__)

#: Bir vaqtda bajariladigan maksimal HTTP yetkazish soni.
MAX_PARALLEL_DELIVERIES: Final[int] = 10


class WebhookSender(PeriodicWorker):
    """Webhook navbatini bo'shatadigan va qayta urinishlarni bajaradigan worker."""

    name = "webhook_sender"
    exclusive = False

    def __init__(self) -> None:
        super().__init__()
        self.interval_seconds = float(settings.WEBHOOK_SENDER_INTERVAL_SECONDS)
        self.batch_size = max(1, int(settings.WEBHOOK_SENDER_BATCH_SIZE))
        self._semaphore = asyncio.Semaphore(MAX_PARALLEL_DELIVERIES)
        self._delivered_total = 0
        self._failed_total = 0

    # ------------------------------------------------------------------
    # Sikl
    # ------------------------------------------------------------------

    async def tick(self) -> None:
        """Bitta sikl: navbatni bo'shatadi, keyin qayta urinishlarni bajaradi."""
        if not settings.WEBHOOK_ENABLED:
            return

        delivery_ids = await self._pop_batch()
        if delivery_ids:
            await self._deliver_batch(delivery_ids)

        await self._retry_pending()

    # ------------------------------------------------------------------
    # 1. Redis navbati
    # ------------------------------------------------------------------

    async def _pop_batch(self) -> list[uuid.UUID]:
        """Navbatdan partiya oladi (`LPOP count`).

        `LPOP key count` bitta murojaatda bir nechta a'zo oladi (Redis 6.2+)
        — partiya uchun `batch_size` ta alohida `LPOP` qilishdan ancha
        arzon. Noto'g'ri formatdagi a'zo (qo'lda qo'yilgan qiymat) jim
        tashlanadi: navbatni bitta buzuq yozuv bloklab qo'ymasligi kerak.
        """
        raw = await self.redis.lpop(RedisKeys.WEBHOOK_QUEUE, self.batch_size)
        if raw is None:
            return []

        members = raw if isinstance(raw, list) else [raw]
        delivery_ids: list[uuid.UUID] = []
        for member in members:
            try:
                delivery_ids.append(uuid.UUID(str(member)))
            except (ValueError, AttributeError, TypeError):
                logger.warning("webhook_sender.invalid_member", member=str(member))
        return delivery_ids

    async def _deliver_batch(self, delivery_ids: list[uuid.UUID]) -> None:
        """Partiyani parallel yetkazadi (semafor bilan cheklangan)."""
        results = await asyncio.gather(
            *(self._deliver_one(delivery_id) for delivery_id in delivery_ids),
            return_exceptions=True,
        )

        delivered = 0
        failed = 0
        for result in results:
            if isinstance(result, BaseException):
                # `deliver()` xato tashlamaydi, lekin sessiya yaratish
                # yiqilishi mumkin — yozuv DB'da qoladi va `retry_pending()`
                # uni keyingi siklda oladi.
                logger.error(
                    "webhook_sender.delivery_crashed",
                    error=str(result),
                    error_type=type(result).__name__,
                )
                failed += 1
            elif result:
                delivered += 1
            else:
                failed += 1

        self._delivered_total += delivered
        self._failed_total += failed
        logger.info(
            "webhook_sender.batch",
            batch=len(delivery_ids),
            delivered=delivered,
            failed=failed,
            delivered_total=self._delivered_total,
        )

    async def _deliver_one(self, delivery_id: uuid.UUID) -> bool:
        """Bitta delivery'ni O'Z sessiyasida yetkazadi.

        Yozuv `deliver()` ichida `selectinload(WebhookDelivery.webhook)` bilan
        qayta o'qiladi, shuning uchun bu yerda yengil obyekt yetarli —
        `lazy="raise"` bog'lanishlarga tegilmaydi.
        """
        async with self._semaphore:
            async with session_scope() as session:
                service = WebhookService(session)
                delivery = await service.deliveries_repo.get(delivery_id)
                if delivery is None:
                    logger.warning(
                        "webhook_sender.delivery_not_found",
                        delivery_id=str(delivery_id),
                    )
                    return False
                return await service.deliver(delivery)

    # ------------------------------------------------------------------
    # 2. Qayta urinishlar
    # ------------------------------------------------------------------

    async def _retry_pending(self) -> None:
        """Vaqti kelgan qayta urinishlarni bajaradi (DB manbasi)."""
        async with session_scope() as session:
            delivered = await WebhookService(session).retry_pending(limit=self.batch_size)
        if delivered:
            self._delivered_total += delivered
            logger.info(
                "webhook_sender.retried",
                delivered=delivered,
                delivered_total=self._delivered_total,
            )

    # ------------------------------------------------------------------
    # Diagnostika
    # ------------------------------------------------------------------

    @property
    def delivered_total(self) -> int:
        """Muvaffaqiyatli yetkazilganlar soni."""
        return self._delivered_total

    @property
    def failed_total(self) -> int:
        """Yetkazilmaganlar soni (qayta urinish rejalashtirilgan)."""
        return self._failed_total


async def main() -> None:
    """Webhook sender'ni ishga tushiradi (`python -m app.workers.webhook_sender`)."""
    await WebhookSender().run()


if __name__ == "__main__":  # pragma: no cover - protsess kirish nuqtasi
    main_entry(WebhookSender)


__all__ = ["MAX_PARALLEL_DELIVERIES", "WebhookSender", "main"]
