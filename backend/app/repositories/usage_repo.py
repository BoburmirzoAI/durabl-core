"""Durabl — `usage_records` jadvali uchun repository (billing hisoblagichlari).

Har bir foydalanuvchi uchun har bir oyga BITTA yozuv bo'ladi
(`UniqueConstraint("user_id", "period")`, `period` formati `"2026-10"` —
`month_key()` beradi). Hisoblagichlar parallel ishlaydigan worker'lardan
oshib boradi, shuning uchun bu qatlamda ikki xil poyga (race) holati hal
qilingan:

1. **Yozuvni yaratish poygasi** — ikki tranzaksiya bir vaqtda bir oy uchun
   yozuv yaratsa, biri `IntegrityError` oladi. INSERT SAVEPOINT ichida
   bajariladi: xato bo'lsa faqat savepoint qaytariladi, so'ng g'olibning
   yozuvi qayta o'qiladi (`get_or_create`).
2. **Hisoblagichni oshirish poygasi** — qiymat Python tomonida emas, SQL
   tomonida oshiriladi (`job_count = job_count + :n`), shuning uchun
   "o'qidim-qo'shdim-yozdim" yo'qotishi bo'lmaydi.

PostgreSQL'da `increment()` bitta `INSERT ... ON CONFLICT DO UPDATE` so'rovi
bilan ishlaydi (yozuv yo'q bo'lsa ham yaratadi). SQLite'da (testlar) bu
sintaksis mavjud emas, shuning uchun `get_or_create` + atomar `UPDATE`
yo'li ishlatiladi. Ikki yo'l ham bir xil natija beradi.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from app.config import settings
from app.exceptions import DatabaseError
from app.models.usage_record import UsageRecord
from app.repositories.base import BaseRepository
from app.utils.time_utils import month_key, utcnow


class UsageRepository(BaseRepository[UsageRecord]):
    """Oylik foydalanish hisoblagichlari bilan ishlash."""

    model = UsageRecord

    # ------------------------------------------------------------------
    # O'qish
    # ------------------------------------------------------------------

    async def get_for_period(
        self,
        user_id: uuid.UUID | str,
        period: str,
    ) -> UsageRecord | None:
        """Bir oy uchun yozuv (yo'q bo'lsa `None`).

        `populate_existing=True` — identity map'dagi eski (stale) nusxa
        emas, DB'dagi HOZIRGI qiymatlar qaytadi. `increment()` SQL tomonida
        ishlagani uchun bu muhim.
        """
        stmt = (
            select(UsageRecord)
            .where(
                UsageRecord.user_id == self._coerce_id(user_id),
                UsageRecord.period == period,
            )
            .execution_options(populate_existing=True)
        )
        result = await self._execute(stmt)
        return result.scalars().first()

    async def history(
        self,
        user_id: uuid.UUID | str,
        limit: int = 12,
    ) -> list[UsageRecord]:
        """Oxirgi oylar tarixi (yangisidan boshlab).

        `period` `"YYYY-MM"` formatida, shuning uchun MATN sifatida
        tartiblash xronologik tartib bilan mos tushadi.
        """
        stmt = (
            select(UsageRecord)
            .where(UsageRecord.user_id == self._coerce_id(user_id))
            .order_by(UsageRecord.period.desc())
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        result = await self._execute(stmt)
        return list(result.scalars().all())

    async def current_period(
        self, user_id: uuid.UUID | str
    ) -> UsageRecord:
        """Joriy oy yozuvi; yo'q bo'lsa yaratiladi (nol hisoblagichlar bilan).

        Kvota tekshiruvi (`check_quota`) va `UsageSummary` har doim obyekt
        oladi — `None` holatini alohida ko'rib chiqish kerak emas.
        """
        return await self.get_or_create(user_id, month_key())

    # ------------------------------------------------------------------
    # Yozish
    # ------------------------------------------------------------------

    async def get_or_create(
        self,
        user_id: uuid.UUID | str,
        period: str,
    ) -> UsageRecord:
        """Oy yozuvini qaytaradi; yo'q bo'lsa nol hisoblagichlar bilan yaratadi.

        Poyga holati SAVEPOINT bilan hal qilinadi (modul docstring'iga qara).
        """
        existing = await self.get_for_period(user_id, period)
        if existing is not None:
            return existing

        record = UsageRecord(
            user_id=self._coerce_id(user_id),
            period=period,
            recorded_at=utcnow(),
        )
        try:
            async with self.session.begin_nested():
                self.session.add(record)
                await self.session.flush()
        except IntegrityError as exc:
            # Boshqa tranzaksiya ulgurdi — uning yozuvini o'qiymiz
            winner = await self.get_for_period(user_id, period)
            if winner is None:
                raise DatabaseError(
                    f"Foydalanish yozuvi yaratilmadi: {exc.orig}",
                    details={"table": UsageRecord.__tablename__},
                ) from exc
            return winner
        return record

    async def increment(
        self,
        user_id: uuid.UUID | str,
        period: str,
        *,
        jobs: int = 0,
        success: int = 0,
        failed: int = 0,
        seconds: float = 0.0,
    ) -> UsageRecord:
        """Hisoblagichlarni oshiradi; yozuv yo'q bo'lsa yaratadi.

        Barcha qo'shishlar SQL tomonida (`job_count = job_count + :n`)
        bajariladi, shuning uchun parallel worker'lar bir-birining
        qiymatini ustiga yozib yubormaydi.

        Dialekt bo'yicha yo'l tanlanadi: PostgreSQL —
        `INSERT ... ON CONFLICT DO UPDATE` (bitta so'rov), SQLite —
        `get_or_create` + `UPDATE`.
        """
        if self._is_sqlite():
            return await self._increment_portable(
                user_id,
                period,
                jobs=jobs,
                success=success,
                failed=failed,
                seconds=seconds,
            )
        return await self._increment_upsert(
            user_id,
            period,
            jobs=jobs,
            success=success,
            failed=failed,
            seconds=seconds,
        )

    # ------------------------------------------------------------------
    # Ichki amalga oshirishlar
    # ------------------------------------------------------------------

    def _is_sqlite(self) -> bool:
        """Joriy ulanish SQLite'mi (dialektga bog'liq SQL tanlash uchun)?

        Avval sessiyaning haqiqiy bind'i so'raladi — bu eng ishonchli manba va
        testlarda `reload_settings()` dan keyin ham to'g'ri ishlaydi (modul
        darajasidagi `settings` nomi eski obyektga bog'langan bo'lib qoladi).
        Sessiya hali hech qanday engine'ga bog'lanmagan bo'lsa
        `settings.is_sqlite` ga qaytiladi. `job_repo.py` va
        `execution_repo.py` dagi usul bilan AYNI.
        """
        try:
            return self.session.get_bind().dialect.name == "sqlite"
        except SQLAlchemyError:
            return settings.is_sqlite

    async def _increment_upsert(
        self,
        user_id: uuid.UUID | str,
        period: str,
        *,
        jobs: int,
        success: int,
        failed: int,
        seconds: float,
    ) -> UsageRecord:
        """PostgreSQL yo'li: `INSERT ... ON CONFLICT DO UPDATE` (atomar)."""
        now = utcnow()
        coerced_user_id = self._coerce_id(user_id)
        stmt = (
            pg_insert(UsageRecord)
            .values(
                id=uuid.uuid4(),
                user_id=coerced_user_id,
                period=period,
                job_count=jobs,
                success_count=success,
                failed_count=failed,
                execution_seconds=seconds,
                recorded_at=now,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                # `UniqueConstraint("user_id", "period")` indeksiga mos keladi
                index_elements=[UsageRecord.user_id, UsageRecord.period],
                set_={
                    "job_count": UsageRecord.job_count + jobs,
                    "success_count": UsageRecord.success_count + success,
                    "failed_count": UsageRecord.failed_count + failed,
                    "execution_seconds": UsageRecord.execution_seconds + seconds,
                    "recorded_at": now,
                    "updated_at": now,
                },
            )
        )
        await self._execute(stmt)
        record = await self.get_for_period(user_id, period)
        if record is None:  # pragma: no cover - upsert'dan keyin bo'lmaydi
            raise DatabaseError(
                "Foydalanish yozuvi upsert'dan keyin topilmadi",
                details={"period": period},
            )
        return record

    async def _increment_portable(
        self,
        user_id: uuid.UUID | str,
        period: str,
        *,
        jobs: int,
        success: int,
        failed: int,
        seconds: float,
    ) -> UsageRecord:
        """Dialektdan mustaqil yo'l: `get_or_create` + atomar `UPDATE`.

        `synchronize_session=False` — ORM sessiyani o'zi moslashtirishga
        urinmaydi, chunki qiymatlar SQL ifodalari. Shuning uchun
        yangilangandan keyin obyekt ochiq `refresh()` bilan qayta o'qiladi
        (async'da muddati o'tgan atributga murojaat `MissingGreenlet`
        beradi, demak buni kechiktirish mumkin emas).
        """
        record = await self.get_or_create(user_id, period)
        stmt = (
            sa_update(UsageRecord)
            .where(UsageRecord.id == record.id)
            .values(
                job_count=UsageRecord.job_count + jobs,
                success_count=UsageRecord.success_count + success,
                failed_count=UsageRecord.failed_count + failed,
                execution_seconds=UsageRecord.execution_seconds + seconds,
                recorded_at=utcnow(),
            )
            .execution_options(synchronize_session=False)
        )
        await self._execute(stmt)
        await self.session.refresh(record)
        return record


__all__ = ["UsageRepository"]
