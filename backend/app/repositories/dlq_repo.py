"""Durabl — `dlq_entries` jadvali uchun repository (o'lik xatlar navbati).

DLQ — Durabl'ning raqobatchilardan ajralib turadigan qismi: job "jimgina
o'lmaydi", balki sababi bilan shu jadvalda qoladi. Shuning uchun bu
repository ikki xil so'rovni beradi:

* ro'yxat/qidiruv (`list_for_user`, `get_for_user`, `get_by_job`);
* agregatsiya (`depth`, `group_by_reason`) — dashboard va alert uchun.

`depth()` ATAYIN faqat hal qilinmagan yozuvlarni sanaydi: "DLQ chuqurligi"
operator uchun hozir e'tibor talab qiladigan yozuvlar soni degani
(`dlq_processor` alert chegarasini shu bilan solishtiradi).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import ColumnElement, func, select

from app.constants import FailureReason
from app.models.dlq_entry import DlqEntry
from app.repositories.base import BaseRepository
from app.utils.time_utils import utcnow

#: Standart sahifa hajmi — `app.schemas.base.DEFAULT_PAGE_SIZE` bilan bir xil
#: (repository qatlami `schemas`ga bog'lanmasligi uchun takrorlangan).
DEFAULT_PAGE_SIZE = 20


class DlqRepository(BaseRepository[DlqEntry]):
    """O'lik xatlar navbati yozuvlari bilan ishlash."""

    model = DlqEntry

    # ------------------------------------------------------------------
    # O'qish
    # ------------------------------------------------------------------

    async def get_for_user(
        self,
        entry_id: uuid.UUID | str,
        user_id: uuid.UUID | str,
    ) -> DlqEntry | None:
        """Yozuvni EGASI bo'yicha ham tekshirib oladi (IDOR himoyasi)."""
        stmt = select(DlqEntry).where(
            DlqEntry.id == self._coerce_id(entry_id),
            DlqEntry.user_id == self._coerce_id(user_id),
        )
        result = await self._execute(stmt)
        return result.scalars().first()

    async def get_by_job(self, job_id: uuid.UUID | str) -> DlqEntry | None:
        """Job bo'yicha DLQ yozuvi.

        `job_id` unique, shuning uchun ko'pi bilan bitta yozuv bo'ladi:
        qayta urinish yangi yozuv yaratmaydi, mavjudini yangilaydi.
        """
        stmt = select(DlqEntry).where(DlqEntry.job_id == self._coerce_id(job_id))
        result = await self._execute(stmt)
        return result.scalars().first()

    async def list_for_user(
        self,
        user_id: uuid.UUID | str,
        resolved: bool | None = None,
        failure_reason: FailureReason | str | None = None,
        page: int = 1,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> tuple[list[DlqEntry], int]:
        """Foydalanuvchining DLQ yozuvlari: `(yozuvlar, umumiy_son)`.

        `resolved=None` — hal qilingani ham, qilinmagani ham qaytadi.
        Tartib: eng yangi yiqilganidan boshlab (`failed_at DESC`).
        """
        conditions = self._conditions(
            user_id=user_id, resolved=resolved, failure_reason=failure_reason
        )

        total_stmt = select(func.count()).select_from(DlqEntry).where(*conditions)
        total_result = await self._execute(total_stmt)
        total = int(total_result.scalar_one() or 0)

        stmt = (
            select(DlqEntry)
            .where(*conditions)
            .order_by(DlqEntry.failed_at.desc())
            .offset(max(0, (page - 1) * page_size))
            .limit(page_size)
        )
        result = await self._execute(stmt)
        return list(result.scalars().all()), total

    async def depth(self, user_id: uuid.UUID | str | None = None) -> int:
        """DLQ chuqurligi — HAL QILINMAGAN yozuvlar soni.

        `user_id` berilmasa butun tizim bo'yicha hisoblanadi (admin paneli
        va `dlq_processor` alert chegarasi uchun).
        """
        stmt = (
            select(func.count())
            .select_from(DlqEntry)
            .where(*self._conditions(user_id=user_id, resolved=False))
        )
        result = await self._execute(stmt)
        return int(result.scalar_one() or 0)

    async def group_by_reason(
        self,
        user_id: uuid.UUID | str | None = None,
        resolved: bool | None = None,
    ) -> dict[str, int]:
        """Xato sababi kesimidagi yozuvlar soni: `{"timeout": 12, ...}`.

        Kalit — `FailureReason` qiymati (matn), shuning uchun natija
        to'g'ridan-to'g'ri JSON javobga qo'yilishi mumkin. Hech bir yozuvi
        yo'q sabablar ham `0` bilan chiqadi — grafik ustunlari "sakrab
        ketmasligi" uchun.

        `resolved=None` (standart) — barcha yozuvlar; `False` bersangiz
        faqat hozirgi chuqurlik kesimi chiqadi.
        """
        stmt = (
            select(DlqEntry.failure_reason, func.count())
            .where(*self._conditions(user_id=user_id, resolved=resolved))
            .group_by(DlqEntry.failure_reason)
        )
        result = await self._execute(stmt)
        counts: dict[str, int] = {reason.value: 0 for reason in FailureReason}
        for reason, amount in result.all():
            counts[FailureReason(reason).value] = int(amount or 0)
        return counts

    # ------------------------------------------------------------------
    # Yozish
    # ------------------------------------------------------------------

    async def mark_resolved(
        self,
        entry: DlqEntry,
        resolved_by_id: uuid.UUID | str | None = None,
        notes: str | None = None,
    ) -> DlqEntry:
        """Yozuvni hal qilingan deb belgilaydi.

        Idempotent: allaqachon hal qilingan yozuv uchun ham xato bermaydi,
        faqat `resolved_at` va izohni yangilaydi. "Allaqachon hal qilingan"
        tekshiruvi (`DlqEntryAlreadyResolvedError`) service qatlamida.

        `notes=None` berilsa, mavjud izoh O'ZGARMAYDI (o'chirilmaydi).
        """
        values: dict[str, Any] = {
            "resolved": True,
            "resolved_at": utcnow(),
        }
        if resolved_by_id is not None:
            values["resolved_by_id"] = self._coerce_id(resolved_by_id)
        if notes is not None:
            values["notes"] = notes
        return await self.update(entry, **values)

    # ------------------------------------------------------------------
    # Yordamchilar
    # ------------------------------------------------------------------

    def _conditions(
        self,
        *,
        user_id: uuid.UUID | str | None = None,
        resolved: bool | None = None,
        failure_reason: FailureReason | str | None = None,
    ) -> list[ColumnElement[Any]]:
        """Ixtiyoriy filtrlarni WHERE shartlariga aylantiradi (`None` — filtr yo'q)."""
        conditions: list[ColumnElement[Any]] = []
        if user_id is not None:
            conditions.append(DlqEntry.user_id == self._coerce_id(user_id))
        if resolved is not None:
            conditions.append(DlqEntry.resolved.is_(resolved))
        if failure_reason is not None:
            conditions.append(
                DlqEntry.failure_reason == FailureReason(failure_reason)
            )
        return conditions


__all__ = ["DEFAULT_PAGE_SIZE", "DlqRepository"]
