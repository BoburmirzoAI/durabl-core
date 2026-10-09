"""Durabl — o'lik xatlar navbati (DLQ) kuzatuvchisi.

DLQ — barcha qayta urinishlar tugagandan keyin job tushadigan joy. Bu
worker DLQ ustidan operatsion nazorat qiladi:

1. **Chuqurlikni o'lchaydi** va `dlq_depth` metrikasini yangilaydi (Grafana
   paneli va alert qoidalari shu metrikaga tayanadi).
2. **Chegaradan oshsa alert yuboradi** (`settings.DLQ_ALERT_THRESHOLD`).
   DLQ'ning tez o'sishi deyarli har doim TIZIMLI nosozlik belgisi: sandbox
   obrazi buzilgan, tashqi API o'lgan, migratsiya yarim qolgan. Operator
   buni mijoz shikoyatidan OLDIN bilishi kerak.
3. **`DLQ_AUTO_RETRY_ENABLED` bo'lsa avtomatik qayta uradi.** Standart
   `False` — chunki aksariyat DLQ yozuvlari mijoz kodidagi xato va
   avtomatik qayta urinish faqat resursni yoqadi. Yoqilganda har yozuv
   `DLQ_AUTO_RETRY_MAX_ATTEMPTS` martadan oshmaydi: hisob
   `dlq_entries.manual_retry_count` da saqlanadi va `_upsert_dlq_entry()`
   uni nollamaydi, shuning uchun job abadiy aylanib yurmaydi.
4. **Eski loglarni tozalaydi.** `execution_logs` eng tez o'sadigan jadval.
   Tozalash eng SAXIY reja bo'yicha bajariladi (`log_retention_days` ning
   maksimumi) — shunda hech bir mijozning loglari o'z muddatidan oldin
   o'chmaydi, lekin jadval ham cheksiz o'smaydi.

`exclusive = True`: ikki nusxa parallel ishlasa bir yozuv ikki marta qayta
urilib, ikkita bir xil job navbatga tushardi.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.constants import PLAN_LIMITS
from app.database import session_scope
from app.exceptions import DurablError
from app.logging_config import get_logger
from app.metrics import set_dlq_depth
from app.models.dlq_entry import DlqEntry
from app.repositories.dlq_repo import DlqRepository
from app.repositories.execution_log_repo import ExecutionLogRepository
from app.services.notification_service import NotificationService
from app.services.reliability_service import ReliabilityService
from app.utils.time_utils import utcnow
from app.workers.runner import PeriodicWorker, main_entry

logger = get_logger(__name__)

#: Bitta siklda avtomatik qayta urilishi mumkin bo'lgan yozuvlar soni.
AUTO_RETRY_BATCH_SIZE: Final[int] = 25

#: Log tozalash shuncha siklda bir marta bajariladi (har siklda kerak emas).
CLEANUP_EVERY_CYCLES: Final[int] = 20


class DlqProcessor(PeriodicWorker):
    """DLQ chuqurligini kuzatuvchi, alert beruvchi va tozalovchi worker.

    Atributlar:
        notifications: Alert yuboruvchi servis. Ochiq maydon — testlar
            uni soxta obyekt bilan almashtiradi (servis holatsiz).
    """

    name = "dlq_processor"
    exclusive = True

    def __init__(self) -> None:
        super().__init__()
        self.interval_seconds = float(settings.DLQ_PROCESSOR_INTERVAL_SECONDS)
        self.lock_ttl = max(30, int(self.interval_seconds * 2) + 1)
        self.notifications: Any = NotificationService()
        self._alerts_sent = 0
        self._retried_total = 0
        self._logs_deleted_total = 0

    # ------------------------------------------------------------------
    # Sikl
    # ------------------------------------------------------------------

    async def tick(self) -> None:
        """Bitta sikl: chuqurlik -> alert -> avtomatik retry -> tozalash."""
        async with session_scope() as session:
            depth = await self._measure(session)
            await self._maybe_alert(depth)

        if settings.DLQ_AUTO_RETRY_ENABLED:
            async with session_scope() as session:
                await self._auto_retry(session)

        if self._cycles % CLEANUP_EVERY_CYCLES == 1:
            async with session_scope() as session:
                await self._cleanup_logs(session)

    # ------------------------------------------------------------------
    # 1. Chuqurlik va alert
    # ------------------------------------------------------------------

    async def _measure(self, session: AsyncSession) -> int:
        """Hal qilinmagan DLQ yozuvlari sonini o'lchab metrikaga yozadi."""
        depth = await DlqRepository(session).depth()
        set_dlq_depth(depth)
        logger.debug(
            "dlq.depth_measured",
            depth=depth,
            threshold=settings.DLQ_ALERT_THRESHOLD,
        )
        return depth

    async def _maybe_alert(self, depth: int) -> None:
        """Chegaradan oshsa alert yuboradi.

        Bo'g'ish (throttling) `NotificationService` ichida — shuning uchun
        har 30 soniyada chaqirilsa ham operator spam olmaydi.
        """
        if depth <= settings.DLQ_ALERT_THRESHOLD:
            return

        try:
            await self.notifications.notify_dlq_threshold(depth)
        except Exception as exc:
            logger.warning(
                "dlq.alert_failed",
                depth=depth,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return

        self._alerts_sent += 1
        logger.warning(
            "dlq.threshold_exceeded",
            depth=depth,
            threshold=settings.DLQ_ALERT_THRESHOLD,
            alerts_sent=self._alerts_sent,
        )

    # ------------------------------------------------------------------
    # 2. Avtomatik qayta urinish
    # ------------------------------------------------------------------

    async def _auto_retry(self, session: AsyncSession) -> None:
        """Hal qilinmagan yozuvlarni chegaraga qadar qayta uradi."""
        dlq = DlqRepository(session)
        entries = await dlq.list(
            resolved=False,
            limit=AUTO_RETRY_BATCH_SIZE,
            order_by=DlqEntry.failed_at.asc(),
        )
        if not entries:
            return

        limit = max(0, int(settings.DLQ_AUTO_RETRY_MAX_ATTEMPTS))
        reliability = ReliabilityService(session)
        retried = 0

        for entry in entries:
            if int(entry.manual_retry_count or 0) >= limit:
                continue
            if await self._retry_one(reliability, entry):
                retried += 1

        self._retried_total += retried
        if retried:
            logger.info(
                "dlq.auto_retried",
                retried=retried,
                scanned=len(entries),
                total=self._retried_total,
            )

    async def _retry_one(
        self,
        reliability: ReliabilityService,
        entry: DlqEntry,
    ) -> bool:
        """Bitta yozuvni qayta uradi.

        `by_user_id=None` — qayta urinishni TIZIM boshladi, ya'ni audit
        yozuvida "operator" ko'rsatilmaydi. Bitta yozuvdagi xato qolganlarni
        to'xtatmasligi kerak, shuning uchun xato shu yerda yutiladi.
        """
        entry_id = entry.id
        job_id = entry.job_id
        try:
            job = await reliability.retry_from_dlq(
                entry,
                by_user_id=None,
                notes="DLQ avtomatik qayta urinishi (tizim)",
            )
        except DurablError as exc:
            logger.warning(
                "dlq.auto_retry_skipped",
                dlq_entry_id=str(entry_id),
                job_id=str(job_id),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False
        except Exception as exc:
            logger.exception(
                "dlq.auto_retry_failed",
                dlq_entry_id=str(entry_id),
                job_id=str(job_id),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False

        logger.info(
            "dlq.auto_retry",
            dlq_entry_id=str(entry_id),
            job_id=str(job.id),
            correlation_id=job.correlation_id,
        )
        return True

    # ------------------------------------------------------------------
    # 3. Eski loglarni tozalash
    # ------------------------------------------------------------------

    async def _cleanup_logs(self, session: AsyncSession) -> None:
        """`execution_logs` dan muddati o'tgan qatorlarni o'chiradi.

        Soddalik uchun eng UZUN reja muddati ishlatiladi: har job uchun
        egasining rejasini aniqlash qo'shimcha `JOIN` talab qiladi va bu
        fon tozalashi uchun ortiqcha. Natijada ba'zi loglar kerakdan
        uzoq saqlanadi — bu xavfsiz tomon.
        """
        days = self.retention_days()
        cutoff = utcnow() - timedelta(days=days)
        deleted = await ExecutionLogRepository(session).delete_older_than(cutoff)

        self._logs_deleted_total += deleted
        if deleted:
            logger.info(
                "dlq.logs_pruned",
                deleted=deleted,
                retention_days=days,
                cutoff=cutoff.isoformat(),
                total=self._logs_deleted_total,
            )

    @staticmethod
    def retention_days() -> int:
        """Rejalardagi eng uzun log saqlash muddati (kun)."""
        return max(limits.log_retention_days for limits in PLAN_LIMITS.values())

    # ------------------------------------------------------------------
    # Diagnostika
    # ------------------------------------------------------------------

    @property
    def alerts_sent(self) -> int:
        """Yuborilgan alertlar soni."""
        return self._alerts_sent

    @property
    def retried_total(self) -> int:
        """Avtomatik qayta urilgan yozuvlar soni."""
        return self._retried_total


async def main() -> None:
    """DLQ processor'ni ishga tushiradi (`python -m app.workers.dlq_processor`)."""
    await DlqProcessor().run()


if __name__ == "__main__":  # pragma: no cover - protsess kirish nuqtasi
    main_entry(DlqProcessor)


__all__ = [
    "AUTO_RETRY_BATCH_SIZE",
    "CLEANUP_EVERY_CYCLES",
    "DlqProcessor",
    "main",
]
