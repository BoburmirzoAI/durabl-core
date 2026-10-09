"""Durabl — `executions` jadvali uchun repository.

Bu qatlam ikki vazifani bajaradi:

* **Urinishlar tarixi** — `list_for_job`, `current`, `next_attempt_number`
  (`UniqueConstraint("job_id", "attempt_number")` buzilmasligi uchun raqam
  shu yerdan olinadi).
* **Lease nazorati** — `renew_lease` (heartbeat chaqiradi) va `expired_leases`
  (reaper chaqiradi). PostgreSQL'da reaper so'rovi `FOR UPDATE SKIP LOCKED`
  bilan ketadi, shuning uchun bir nechta nusxa parallel ishlaganda ham bir
  urinish ikki marta "yo'qolgan" deb belgilanmaydi.

`user_id` bo'yicha filtr `jobs` jadvaliga `JOIN` bilan qo'yiladi — `executions`
da egasi saqlanmaydi (job orqali aniqlanadi).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from app.config import settings
from app.constants import ExecutionStatus, FailureReason, StrEnum
from app.exceptions import ValidationError
from app.models.execution import Execution
from app.models.job import Job
from app.repositories.base import BaseRepository
from app.utils.time_utils import ensure_utc, utcnow

#: `search()` da tartiblash uchun ruxsat etilgan ustunlar
EXECUTION_SORT_COLUMNS: frozenset[str] = frozenset(
    {
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
        "duration_ms",
        "attempt_number",
        "status",
    }
)


class ExecutionRepository(BaseRepository[Execution]):
    """Bajarish urinishlari bilan ishlash qatlami."""

    model = Execution

    # ------------------------------------------------------------------
    # O'qish
    # ------------------------------------------------------------------

    async def list_for_job(self, job_id: uuid.UUID | str) -> list[Execution]:
        """Job'ning barcha urinishlari — urinish raqami bo'yicha o'sish tartibida."""
        stmt = (
            select(Execution)
            .where(Execution.job_id == self._coerce_id(job_id))
            .order_by(Execution.attempt_number.asc())
        )
        result = await self._execute(stmt)
        return list(result.scalars().all())

    async def next_attempt_number(self, job_id: uuid.UUID | str) -> int:
        """Keyingi urinish raqami: `MAX(attempt_number) + 1` (birinchi urinish — 1).

        `UniqueConstraint("job_id", "attempt_number")` bo'lgani uchun raqam
        qo'lda yasalmaydi — har doim shu metod orqali olinadi.
        """
        stmt = select(func.max(Execution.attempt_number)).where(
            Execution.job_id == self._coerce_id(job_id)
        )
        result = await self._execute(stmt)
        highest = result.scalar_one_or_none()
        return int(highest) + 1 if highest is not None else 1

    async def current(self, job_id: uuid.UUID | str) -> Execution | None:
        """Job'ning oxirgi (eng katta raqamli) urinishi; urinish bo'lmasa `None`."""
        stmt = (
            select(Execution)
            .where(Execution.job_id == self._coerce_id(job_id))
            .order_by(Execution.attempt_number.desc())
            .limit(1)
        )
        result = await self._execute(stmt)
        return result.scalars().first()

    async def get_for_user(
        self,
        execution_id: uuid.UUID | str,
        user_id: uuid.UUID | str,
        *,
        with_job: bool = False,
    ) -> Execution | None:
        """Urinishni egasi bilan tekshirib oladi (`jobs.user_id` bo'yicha `JOIN`)."""
        stmt: Select[Any] = (
            select(Execution)
            .join(Job, Execution.job_id == Job.id)
            .where(
                Execution.id == self._coerce_id(execution_id),
                Job.user_id == self._coerce_id(user_id),
            )
            .limit(1)
        )
        if with_job:
            stmt = stmt.options(selectinload(Execution.job))
        result = await self._execute(stmt)
        return result.scalars().first()

    async def count_for_job(self, job_id: uuid.UUID | str) -> int:
        """Job uchun qilingan urinishlar soni."""
        stmt = (
            select(func.count())
            .select_from(Execution)
            .where(Execution.job_id == self._coerce_id(job_id))
        )
        result = await self._execute(stmt)
        return int(result.scalar_one() or 0)

    async def expired_leases(self, now: datetime, limit: int = 100) -> list[Execution]:
        """Lease muddati tugagan, lekin hali `RUNNING` turgan urinishlar.

        Worker qulaganda heartbeat to'xtaydi va `lease_expires_at` o'tib ketadi;
        `ReliabilityService.reap_expired_leases()` shu ro'yxatni oladi va
        urinishni `LOST` deb belgilab job'ni qayta navbatga qo'yadi.

        PostgreSQL'da `FOR UPDATE SKIP LOCKED` qo'shiladi; SQLite bu sintaksisni
        qo'llab-quvvatlamagani uchun u yerda qulflash o'tkazib yuboriladi.
        """
        moment = ensure_utc(now) or utcnow()
        stmt = (
            select(Execution)
            .where(
                Execution.status == ExecutionStatus.RUNNING,
                Execution.lease_expires_at.is_not(None),
                Execution.lease_expires_at < moment,
            )
            .order_by(Execution.lease_expires_at.asc())
            .limit(limit)
        )
        if not self._is_sqlite():
            stmt = stmt.with_for_update(skip_locked=True)
        result = await self._execute(stmt)
        return list(result.scalars().all())

    async def active_for_worker(self, worker_id: str) -> list[Execution]:
        """Worker hozir bajarayotgan urinishlar (graceful shutdown va admin panel uchun)."""
        stmt = (
            select(Execution)
            .where(
                Execution.worker_id == worker_id,
                Execution.status == ExecutionStatus.RUNNING,
            )
            .order_by(Execution.started_at.asc())
        )
        result = await self._execute(stmt)
        return list(result.scalars().all())

    async def search(
        self,
        user_id: uuid.UUID | str | None = None,
        job_id: uuid.UUID | str | None = None,
        status: ExecutionStatus | str | Sequence[ExecutionStatus | str] | None = None,
        failure_reason: FailureReason | str | Sequence[FailureReason | str] | None = None,
        worker_id: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[list[Execution], int]:
        """Dinamik filtrlar bilan urinishlar ro'yxati.

        `user_id` berilsa `jobs` bilan `JOIN` qilinadi (egalik tekshiruvi).
        Umumiy son alohida `COUNT` so'rovi bilan (subquery ustidan) olinadi.

        Returns:
            `(yozuvlar, umumiy_son)` juftligi.
        """
        needs_join = user_id is not None
        conditions: list[Any] = []
        if user_id is not None:
            conditions.append(Job.user_id == self._coerce_id(user_id))
        if job_id is not None:
            conditions.append(Execution.job_id == self._coerce_id(job_id))
        if worker_id is not None:
            conditions.append(Execution.worker_id == worker_id)

        status_condition = self._enum_condition(Execution.status, ExecutionStatus, status)
        if status_condition is not None:
            conditions.append(status_condition)

        reason_condition = self._enum_condition(
            Execution.failure_reason, FailureReason, failure_reason
        )
        if reason_condition is not None:
            conditions.append(reason_condition)

        start_at = ensure_utc(start)
        end_at = ensure_utc(end)
        if start_at is not None:
            conditions.append(Execution.created_at >= start_at)
        if end_at is not None:
            conditions.append(Execution.created_at <= end_at)

        total = await self._count_where(conditions, needs_join=needs_join)
        if total == 0:
            return [], 0

        stmt: Select[Any] = select(Execution)
        if needs_join:
            stmt = stmt.join(Job, Execution.job_id == Job.id)
        if conditions:
            stmt = stmt.where(*conditions)
        stmt = self._apply_order(stmt, sort_by=sort_by, sort_order=sort_order)
        stmt = stmt.offset(max(0, (page - 1) * page_size)).limit(page_size)
        result = await self._execute(stmt)
        return list(result.scalars().all()), total

    # ------------------------------------------------------------------
    # Yozish
    # ------------------------------------------------------------------

    async def renew_lease(self, execution: Execution, until: datetime) -> Execution:
        """Lease muddatini suradi (heartbeat har necha soniyada chaqiradi)."""
        execution.lease_expires_at = ensure_utc(until)
        await self._flush()
        return execution

    async def finish(self, execution: Execution, **fields: Any) -> Execution:
        """Urinishni yakunlaydi: berilgan maydonlarni yozadi va `finished_at` qo'yadi.

        `finished_at` ochiq berilmasa hozirgi vaqt qo'yiladi. Holat
        (`status`), `exit_code`, `duration_ms`, `failure_reason` va boshqalar
        chaqiruvchi tomonidan `fields` orqali uzatiladi — qarorni service qabul
        qiladi.
        """
        values = dict(fields)
        if "status" in values:
            values["status"] = ExecutionStatus(values["status"])
        if values.get("finished_at") is None:
            values["finished_at"] = utcnow()
        return await self.update(execution, **values)

    async def release_lease(self, execution: Execution) -> Execution:
        """Lease'ni bo'shatadi (urinish tugadi — boshqa worker uni olmaydi)."""
        execution.lease_expires_at = None
        await self._flush()
        return execution

    # ------------------------------------------------------------------
    # Ichki yordamchilar
    # ------------------------------------------------------------------

    def _is_sqlite(self) -> bool:
        """Joriy ulanish SQLite'mi (dialektga bog'liq SQL tanlash uchun)?

        Avval sessiyaning haqiqiy bind'i so'raladi — bu eng ishonchli manba va
        testlarda `reload_settings()` dan keyin ham to'g'ri ishlaydi. Sessiya
        hali hech qanday engine'ga bog'lanmagan bo'lsa `settings.is_sqlite` ga
        qaytiladi.
        """
        try:
            return self.session.get_bind().dialect.name == "sqlite"
        except SQLAlchemyError:
            return settings.is_sqlite

    async def _count_where(self, conditions: list[Any], *, needs_join: bool) -> int:
        """Shartlarga mos urinishlar sonini alohida `COUNT` so'rovi bilan oladi."""
        inner: Select[Any] = select(Execution.id)
        if needs_join:
            inner = inner.join(Job, Execution.job_id == Job.id)
        if conditions:
            inner = inner.where(*conditions)
        stmt = select(func.count()).select_from(inner.subquery())
        result = await self._execute(stmt)
        return int(result.scalar_one() or 0)

    @staticmethod
    def _apply_order(stmt: Select[Any], *, sort_by: str, sort_order: str) -> Select[Any]:
        """ORDER BY qo'shadi; faqat `EXECUTION_SORT_COLUMNS` ruxsat etilgan."""
        if sort_by not in EXECUTION_SORT_COLUMNS:
            raise ValidationError(
                f"'{sort_by}' bo'yicha tartiblash mumkin emas",
                details={"allowed": sorted(EXECUTION_SORT_COLUMNS)},
            )
        column = getattr(Execution, sort_by)
        ordering = column.asc() if sort_order.lower() == "asc" else column.desc()
        return stmt.order_by(ordering, Execution.id.asc())

    @staticmethod
    def _enum_condition(column: Any, enum_cls: type[StrEnum], value: Any) -> Any | None:
        """Enum filtri: bitta qiymat -> `=`, ro'yxat -> `IN`, `None` -> shart yo'q."""
        if value is None:
            return None
        try:
            if isinstance(value, (list, tuple, set, frozenset)):
                members = [enum_cls(item) for item in value]
                if not members:
                    return None
                return column.in_(members)
            return column == enum_cls(value)
        except ValueError as exc:
            raise ValidationError(
                f"'{enum_cls.__name__}' uchun yaroqsiz qiymat: {value}",
                details={"allowed": [member.value for member in enum_cls]},
            ) from exc


__all__ = ["EXECUTION_SORT_COLUMNS", "ExecutionRepository"]
