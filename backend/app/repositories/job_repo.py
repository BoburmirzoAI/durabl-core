"""Durabl — `jobs` jadvali uchun repository (loyihadagi eng yuklangan qatlam).

Bu yerda uch xil so'rov to'plami bor:

1. **CRUD va egalik tekshiruvi** — `get_for_user`, `find_by_idempotency`, `recent`.
2. **Operatsion so'rovlar** — scheduler va reliability uchun: `due_scheduled`
   (PostgreSQL'da `FOR UPDATE SKIP LOCKED` bilan, bir job ikki worker'ga
   tushmasligi uchun), `stuck_running`, `active_count`.
3. **Analitika** — `stats_overview` (bitta so'rovda `COUNT`/`AVG`/`SUM` va
   `CASE` kesimlari), `throughput_series` (vaqt bo'yicha guruhlash),
   `latency_percentiles`.

**Dialekt farqlari.** Analitik so'rovlarda PostgreSQL va SQLite yo'llari
alohida: `date_trunc` ↔ `strftime`, `percentile_cont` ↔ Python tomonida
hisoblash. Dialekt sessiyaning haqiqiy bind'idan aniqlanadi (`_is_sqlite()`,
zaxira variant — `settings.is_sqlite`), shuning uchun testlar (SQLite
in-memory) ham production (PostgreSQL) ham bir xil natija beradi.

Munosabatlar modellarda `lazy="raise"`, shuning uchun bog'lanish kerak bo'lsa
ochiq `selectinload()` qo'shiladi (`get_for_user(..., with_executions=True)`).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, Text, and_, case, cast, func, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from app.config import settings
from app.constants import FailureReason, JobStatus, Priority, Runtime, StrEnum
from app.exceptions import ValidationError
from app.models.job import Job
from app.repositories.base import BaseRepository
from app.utils.time_utils import ensure_utc, utcnow

#: `search()` da tartiblash uchun ruxsat etilgan ustunlar
JOB_SORT_COLUMNS: frozenset[str] = frozenset(
    {
        "created_at",
        "updated_at",
        "queued_at",
        "started_at",
        "finished_at",
        "scheduled_at",
        "duration_ms",
        "status",
        "priority",
        "runtime",
        "retry_count",
    }
)

#: Analitik so'rovlarda vaqt o'qi sifatida ishlatilishi mumkin bo'lgan ustunlar
JOB_TIME_COLUMNS: frozenset[str] = frozenset(
    {"created_at", "updated_at", "queued_at", "started_at", "finished_at", "scheduled_at"}
)

#: `throughput_series()` qo'llab-quvvatlaydigan guruhlash oraliqlari
JOB_BUCKET_INTERVALS: tuple[str, ...] = ("minute", "hour", "day", "month")

#: `latency_percentiles()` ning standart kesimlari
DEFAULT_PERCENTILES: tuple[float, ...] = (0.5, 0.9, 0.95, 0.99)

#: SQLite uchun `strftime` shablonlari (PostgreSQL'da `date_trunc` ishlatiladi)
_SQLITE_BUCKET_FORMATS: dict[str, str] = {
    "minute": "%Y-%m-%d %H:%M:00",
    "hour": "%Y-%m-%d %H:00:00",
    "day": "%Y-%m-%d 00:00:00",
    "month": "%Y-%m-01 00:00:00",
}

#: SQLite `strftime` qaytaradigan matnni `datetime`ga o'girish shabloni
_SQLITE_BUCKET_PARSE = "%Y-%m-%d %H:%M:%S"


class JobRepository(BaseRepository[Job]):
    """Job'lar bilan ishlash qatlami."""

    model = Job

    def _tag_condition(self, tag: str) -> Any:
        """`tags` JSON massivida teg bor-yo'qligini tekshiruvchi shart.

        PostgreSQL'da `tags` ustuni `JSONB`, shuning uchun `?` operatori
        (kalit/element mavjudligi) ishlaydi va GIN indeks bilan tezlashadi.
        SQLite'da `JSON` oddiy matn sifatida saqlanadi — u yerda
        `json_each` mavjud, lekin korrelyatsiyali subquery kerak bo'ladi,
        shuning uchun oddiy `LIKE '%"teg"%'` ishlatiladi. Teg ichidagi
        qo'shtirnoq va `%`/`_` belgilari ekranlanadi.
        """
        if self._is_sqlite():
            escaped = tag.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            needle = f'%"{escaped}"%'
            return and_(Job.tags.is_not(None), cast(Job.tags, Text).like(needle, escape="\\"))
        # PostgreSQL: JSONB massivida element mavjudligi
        return and_(Job.tags.is_not(None), cast(Job.tags, JSONB).has_key(tag))

    # ------------------------------------------------------------------
    # CRUD va egalik
    # ------------------------------------------------------------------

    async def get_for_user(
        self,
        job_id: uuid.UUID | str,
        user_id: uuid.UUID | str,
        *,
        with_executions: bool = False,
    ) -> Job | None:
        """Job'ni egasi bilan birga tekshirib oladi.

        Boshqa foydalanuvchining job'i so'ralsa `None` qaytadi (service uni
        `JobNotFoundError`ga aylantiradi — resurs borligini oshkor qilmaslik uchun).
        `with_executions=True` bo'lsa urinishlar ham yuklanadi (`timeline` uchun).
        """
        stmt: Select[Any] = (
            select(Job)
            .where(
                Job.id == self._coerce_id(job_id),
                Job.user_id == self._coerce_id(user_id),
            )
            .limit(1)
        )
        if with_executions:
            stmt = stmt.options(selectinload(Job.executions))
        result = await self._execute(stmt)
        return result.scalars().first()

    async def find_by_idempotency(self, user_id: uuid.UUID | str, key: str) -> Job | None:
        """`Idempotency-Key` bo'yicha mavjud job (takroriy so'rovda qaytariladi)."""
        if not key:
            return None
        stmt = (
            select(Job)
            .where(
                Job.user_id == self._coerce_id(user_id),
                Job.idempotency_key == key,
            )
            .limit(1)
        )
        result = await self._execute(stmt)
        return result.scalars().first()

    async def recent(self, user_id: uuid.UUID | str, limit: int = 10) -> list[Job]:
        """Foydalanuvchining eng yangi job'lari (dashboard "oxirgi job'lar" bloki)."""
        stmt = (
            select(Job)
            .where(Job.user_id == self._coerce_id(user_id))
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(limit)
        )
        result = await self._execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Qidiruv va ro'yxat
    # ------------------------------------------------------------------

    async def search(
        self,
        user_id: uuid.UUID | str | None = None,
        status: JobStatus | str | Sequence[JobStatus | str] | None = None,
        runtime: Runtime | str | Sequence[Runtime | str] | None = None,
        priority: Priority | str | Sequence[Priority | str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        search: str | None = None,
        failure_reason: FailureReason | str | Sequence[FailureReason | str] | None = None,
        tag: str | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[list[Job], int]:
        """Dinamik filtrlar bilan job qidiruvi.

        Args:
            user_id: Faqat shu foydalanuvchining job'lari (`None` — hammasi, admin).
            status: Bitta holat yoki holatlar ro'yxati (`IN`).
            runtime: Bitta runtime yoki ro'yxat.
            priority: Bitta ustuvorlik yoki ro'yxat.
            start: `created_at >= start`.
            end: `created_at <= end`.
            search: `code` yoki `correlation_id` ichidan `ILIKE` qidiruv.
            failure_reason: Xato sababi (bitta yoki ro'yxat). DLQ sahifasi va
                analitika "eng ko'p uchraydigan sabab" filtri uchun.
            tag: Bitta teg. `tags` ustuni JSON massiv, shuning uchun filtr
                dialektga bog'liq: PostgreSQL'da JSONB `?` operatori
                (`tags ? :tag`), SQLite'da matn ko'rinishida `LIKE`.
                MUHIM: filtr SQL darajasida qo'llanadi, shuning uchun `total`
                va sahifa mazmuni har doim bir-biriga mos keladi.
            page: 1'dan boshlanadigan sahifa raqami.
            page_size: Sahifadagi yozuvlar soni.
            sort_by: `JOB_SORT_COLUMNS` ichidagi ustun.
            sort_order: `"asc"` yoki `"desc"`.

        Returns:
            `(yozuvlar, umumiy_son)` juftligi. Umumiy son ALOHIDA `COUNT`
            so'rovi bilan (subquery ustidan) hisoblanadi — `LIMIT` ta'sir qilmasin.
        """
        conditions = self._conditions(
            user_id=user_id,
            status=status,
            runtime=runtime,
            priority=priority,
            start=start,
            end=end,
            time_column="created_at",
        )
        if search:
            pattern = f"%{search.strip()}%"
            conditions.append(or_(Job.code.ilike(pattern), Job.correlation_id.ilike(pattern)))
        if failure_reason is not None:
            reasons = (
                [failure_reason]
                if isinstance(failure_reason, (str, FailureReason))
                else list(failure_reason)
            )
            values = [FailureReason(item).value for item in reasons]
            conditions.append(
                Job.failure_reason == values[0]
                if len(values) == 1
                else Job.failure_reason.in_(values)
            )
        if tag:
            conditions.append(self._tag_condition(tag.strip()))

        total = await self._count_where(conditions)
        if total == 0:
            return [], 0

        stmt: Select[Any] = select(Job)
        if conditions:
            stmt = stmt.where(*conditions)
        stmt = self._apply_order(stmt, sort_by=sort_by, sort_order=sort_order)
        stmt = stmt.offset(max(0, (page - 1) * page_size)).limit(page_size)
        result = await self._execute(stmt)
        return list(result.scalars().all()), total

    # ------------------------------------------------------------------
    # Holat o'zgartirish
    # ------------------------------------------------------------------

    async def update_status(self, job: Job, status: JobStatus | str, **fields: Any) -> Job:
        """Job holatini (va berilgan qo'shimcha maydonlarni) yangilaydi.

        O'tish qoidalarini (`JOB_STATUS_TRANSITIONS`) repository TEKSHIRMAYDI —
        bu `JobService.transition()` vazifasi. Bu yerda faqat yozish bor.
        """
        job.status = JobStatus(status)
        return await self.update(job, **fields)

    async def increment_retry(self, job: Job) -> Job:
        """Qayta urinish hisoblagichini bittaga oshiradi."""
        job.retry_count = (job.retry_count or 0) + 1
        await self._flush()
        return job

    # ------------------------------------------------------------------
    # Operatsion so'rovlar (scheduler / reliability)
    # ------------------------------------------------------------------

    async def due_scheduled(self, now: datetime, limit: int = 100) -> list[Job]:
        """Vaqti kelgan kechiktirilgan job'lar: `PENDING` va `scheduled_at <= now`.

        PostgreSQL'da `FOR UPDATE SKIP LOCKED` qo'shiladi — bir nechta scheduler
        nusxasi parallel ishlaganda bir job ikki marta navbatga tushmaydi.
        SQLite bu sintaksisni qo'llab-quvvatlamaydi, shuning uchun u yerda
        qulflash o'tkazib yuboriladi (testlarda yetarli).
        """
        moment = ensure_utc(now) or utcnow()
        stmt = (
            select(Job)
            .where(
                Job.status == JobStatus.PENDING,
                Job.scheduled_at.is_not(None),
                Job.scheduled_at <= moment,
            )
            .order_by(Job.scheduled_at.asc())
            .limit(limit)
        )
        if not self._is_sqlite():
            stmt = stmt.with_for_update(skip_locked=True)
        result = await self._execute(stmt)
        return list(result.scalars().all())

    async def stuck_running(
        self,
        older_than: datetime,
        limit: int | None = None,
    ) -> list[Job]:
        """`RUNNING` holatda qotib qolgan job'lar (`started_at < older_than`).

        Worker qulab, lease ham tozalanmay qolgan hollarni topish uchun —
        `ReliabilityService` ularni qayta navbatga qo'yadi yoki DLQ'ga yuboradi.
        """
        moment = ensure_utc(older_than) or utcnow()
        stmt = (
            select(Job)
            .where(
                Job.status == JobStatus.RUNNING,
                or_(Job.started_at.is_(None), Job.started_at < moment),
            )
            .order_by(Job.started_at.asc())
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._execute(stmt)
        return list(result.scalars().all())

    async def active_count(self, user_id: uuid.UUID | str) -> int:
        """Foydalanuvchining harakatdagi job'lari soni (concurrency limiti uchun).

        Harakatdagi holatlar: `pending`, `queued`, `running`, `retrying`
        (`JobStatus.is_active`).
        """
        active = [status for status in JobStatus if status.is_active]
        stmt = (
            select(func.count())
            .select_from(Job)
            .where(Job.user_id == self._coerce_id(user_id), Job.status.in_(active))
        )
        result = await self._execute(stmt)
        return int(result.scalar_one() or 0)

    async def count_by_status(self, user_id: uuid.UUID | str | None = None) -> dict[str, int]:
        """Holatlar kesimidagi job sonlari: `{"pending": 3, "success": 10, ...}`.

        Natijada BARCHA holatlar bor — yozuv bo'lmagan holat uchun `0`
        (frontend grafiklari bo'sh kalitdan qulamasligi uchun).
        """
        stmt = select(Job.status, func.count(Job.id)).group_by(Job.status)
        if user_id is not None:
            stmt = stmt.where(Job.user_id == self._coerce_id(user_id))
        result = await self._execute(stmt)

        counts: dict[str, int] = {status.value: 0 for status in JobStatus}
        for status_value, total in result.all():
            counts[JobStatus(status_value).value] = int(total or 0)
        return counts

    # ------------------------------------------------------------------
    # Analitika
    # ------------------------------------------------------------------

    async def stats_overview(
        self,
        user_id: uuid.UUID | str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, Any]:
        """Umumiy statistika — BITTA so'rovda.

        `COUNT`, `AVG`, `MIN`, `MAX`, `SUM` va har bir holat uchun
        `SUM(CASE WHEN status = ... THEN 1 ELSE 0 END)` kesimi bitta
        `SELECT` ichida hisoblanadi.

        Returns:
            Lug'at: `total`, har bir holat nomi (`pending`, `success`, ...),
            `by_status`, `success_rate`, `failure_rate`, `avg_duration_ms`,
            `min_duration_ms`, `max_duration_ms`, `total_duration_ms`,
            `measured` (davomiyligi ma'lum job'lar soni), `total_retries`,
            `avg_retry_count`.
        """
        conditions = self._conditions(user_id=user_id, start=start, end=end)

        status_columns = [
            func.sum(case((Job.status == status, 1), else_=0)).label(f"st_{status.name.lower()}")
            for status in JobStatus
        ]
        stmt = select(
            func.count(Job.id).label("total"),
            func.count(Job.duration_ms).label("measured"),
            func.avg(Job.duration_ms).label("avg_duration_ms"),
            func.min(Job.duration_ms).label("min_duration_ms"),
            func.max(Job.duration_ms).label("max_duration_ms"),
            func.sum(Job.duration_ms).label("total_duration_ms"),
            func.sum(Job.retry_count).label("total_retries"),
            *status_columns,
        )
        if conditions:
            stmt = stmt.where(*conditions)

        result = await self._execute(stmt)
        row = result.one()._mapping

        by_status = {
            status.value: int(row[f"st_{status.name.lower()}"] or 0) for status in JobStatus
        }
        total = int(row["total"] or 0)
        succeeded = by_status[JobStatus.SUCCESS.value]
        failed = by_status[JobStatus.FAILED.value]
        dead_letter = by_status[JobStatus.DEAD_LETTER.value]
        #: Muvaffaqiyat foizi yakunlangan job'lar bo'yicha hisoblanadi
        #: (bekor qilinganlar va hali ishlayotganlar hisobga olinmaydi)
        completed = succeeded + failed + dead_letter
        total_retries = int(row["total_retries"] or 0)

        stats: dict[str, Any] = {
            "total": total,
            "by_status": by_status,
            "measured": int(row["measured"] or 0),
            "avg_duration_ms": self._as_float(row["avg_duration_ms"]),
            "min_duration_ms": self._as_int(row["min_duration_ms"]),
            "max_duration_ms": self._as_int(row["max_duration_ms"]),
            "total_duration_ms": int(row["total_duration_ms"] or 0),
            "total_retries": total_retries,
            "avg_retry_count": round(total_retries / total, 4) if total else 0.0,
            "success_rate": round(succeeded / completed * 100, 2) if completed else 0.0,
            "failure_rate": (
                round((failed + dead_letter) / completed * 100, 2) if completed else 0.0
            ),
        }
        # Qulaylik uchun holatlarni yuqori darajada ham beramiz
        stats.update(by_status)
        return stats

    async def throughput_series(
        self,
        user_id: uuid.UUID | str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        interval: str = "hour",
        time_column: str = "created_at",
        status: JobStatus | str | Sequence[JobStatus | str] | None = None,
    ) -> list[dict[str, Any]]:
        """Vaqt bo'yicha job oqimi (throughput).

        PostgreSQL'da `date_trunc(interval, timezone('UTC', col))`, SQLite'da
        `strftime(shablon, col)` bilan guruhlanadi — ikki yo'l ham bir xil
        UTC chegaralarini beradi.

        Args:
            interval: `JOB_BUCKET_INTERVALS` dan biri (`minute`/`hour`/`day`/`month`).
            time_column: Vaqt o'qi ustuni (`JOB_TIME_COLUMNS` dan).

        Returns:
            Tartiblangan ro'yxat: `{"bucket": datetime, "total": int,
            "success": int, "failed": int}`.
        """
        column = self._time_column(time_column)
        bucket = self._bucket_expression(column, interval)

        conditions = self._conditions(
            user_id=user_id,
            status=status,
            start=start,
            end=end,
            time_column=time_column,
        )
        # Vaqt o'qi `NULL` bo'lgan yozuvlar grafikka tushmaydi
        conditions.append(column.is_not(None))

        stmt = select(
            bucket.label("bucket"),
            func.count(Job.id).label("total"),
            func.sum(case((Job.status == JobStatus.SUCCESS, 1), else_=0)).label("success"),
            func.sum(
                case(
                    (Job.status.in_([JobStatus.FAILED, JobStatus.DEAD_LETTER]), 1),
                    else_=0,
                )
            ).label("failed"),
        ).where(*conditions)
        stmt = stmt.group_by(bucket).order_by(bucket.asc())

        result = await self._execute(stmt)
        series: list[dict[str, Any]] = []
        for row in result.all():
            series.append(
                {
                    "bucket": self._parse_bucket(row.bucket),
                    "total": int(row.total or 0),
                    "success": int(row.success or 0),
                    "failed": int(row.failed or 0),
                }
            )
        return series

    async def latency_percentiles(
        self,
        user_id: uuid.UUID | str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        percentiles: Sequence[float] = DEFAULT_PERCENTILES,
        status: JobStatus | str | Sequence[JobStatus | str] | None = None,
    ) -> dict[str, Any]:
        """Bajarish davomiyligi (`duration_ms`) kesimlari.

        PostgreSQL'da `percentile_cont(p) WITHIN GROUP (ORDER BY duration_ms)`
        ishlatiladi. SQLite'da bu funksiya YO'Q, shuning uchun u yerda
        `duration_ms` qiymatlari o'qib olinadi va kesimlar Python tomonida
        xuddi `percentile_cont` kabi (chiziqli interpolyatsiya bilan) hisoblanadi.

        Returns:
            `{"count": int, "avg": float|None, "min": int|None, "max": int|None,
            "p50": float|None, "p90": ..., ...}` — kalitlar `percentiles`dan yasaladi.
        """
        keys = [self._percentile_key(value) for value in percentiles]
        for value in percentiles:
            if not 0.0 <= value <= 1.0:
                raise ValidationError(
                    "Persentil 0.0 va 1.0 orasida bo'lishi kerak",
                    details={"percentile": value},
                )

        conditions = self._conditions(user_id=user_id, status=status, start=start, end=end)
        conditions.append(Job.duration_ms.is_not(None))

        if self._is_sqlite():
            return await self._latency_sqlite(conditions, percentiles, keys)
        return await self._latency_postgres(conditions, percentiles, keys)

    async def _latency_postgres(
        self,
        conditions: list[Any],
        percentiles: Sequence[float],
        keys: Sequence[str],
    ) -> dict[str, Any]:
        """PostgreSQL yo'li — barcha kesimlar bitta `SELECT` ichida."""
        percentile_columns = [
            func.percentile_cont(value).within_group(Job.duration_ms.asc()).label(key)
            for value, key in zip(percentiles, keys, strict=True)
        ]
        stmt = select(
            func.count(Job.duration_ms).label("count"),
            func.avg(Job.duration_ms).label("avg"),
            func.min(Job.duration_ms).label("min"),
            func.max(Job.duration_ms).label("max"),
            *percentile_columns,
        ).where(*conditions)

        result = await self._execute(stmt)
        row = result.one()._mapping

        stats: dict[str, Any] = {
            "count": int(row["count"] or 0),
            "avg": self._as_float(row["avg"]),
            "min": self._as_int(row["min"]),
            "max": self._as_int(row["max"]),
        }
        for key in keys:
            stats[key] = self._as_float(row[key])
        return stats

    async def _latency_sqlite(
        self,
        conditions: list[Any],
        percentiles: Sequence[float],
        keys: Sequence[str],
    ) -> dict[str, Any]:
        """SQLite yo'li — qiymatlar o'qiladi va kesimlar Python tomonida hisoblanadi."""
        stmt = select(Job.duration_ms).where(*conditions).order_by(Job.duration_ms.asc())
        result = await self._execute(stmt)
        values = [int(value) for value in result.scalars().all() if value is not None]

        stats: dict[str, Any] = {
            "count": len(values),
            "avg": round(sum(values) / len(values), 2) if values else None,
            "min": values[0] if values else None,
            "max": values[-1] if values else None,
        }
        for value, key in zip(percentiles, keys, strict=True):
            stats[key] = self._interpolate_percentile(values, value)
        return stats

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

    def _conditions(
        self,
        *,
        user_id: uuid.UUID | str | None = None,
        status: JobStatus | str | Sequence[JobStatus | str] | None = None,
        runtime: Runtime | str | Sequence[Runtime | str] | None = None,
        priority: Priority | str | Sequence[Priority | str] | None = None,
        failure_reason: FailureReason | str | Sequence[FailureReason | str] | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        time_column: str = "created_at",
    ) -> list[Any]:
        """Umumiy filtrlarni WHERE shartlari ro'yxatiga aylantiradi.

        `None` qiymatlar e'tiborsiz qoldiriladi — shu tufayli barcha analitik
        metodlar bir xil filtr to'plamidan foydalanadi.
        """
        conditions: list[Any] = []
        if user_id is not None:
            conditions.append(Job.user_id == self._coerce_id(user_id))

        status_condition = self._enum_condition(Job.status, JobStatus, status)
        if status_condition is not None:
            conditions.append(status_condition)

        runtime_condition = self._enum_condition(Job.runtime, Runtime, runtime)
        if runtime_condition is not None:
            conditions.append(runtime_condition)

        priority_condition = self._enum_condition(Job.priority, Priority, priority)
        if priority_condition is not None:
            conditions.append(priority_condition)

        reason_condition = self._enum_condition(Job.failure_reason, FailureReason, failure_reason)
        if reason_condition is not None:
            conditions.append(reason_condition)

        column = self._time_column(time_column)
        start_at = ensure_utc(start)
        end_at = ensure_utc(end)
        if start_at is not None:
            conditions.append(column >= start_at)
        if end_at is not None:
            conditions.append(column <= end_at)
        return conditions

    async def _count_where(self, conditions: list[Any]) -> int:
        """Shartlarga mos yozuvlar sonini alohida `COUNT` so'rovi (subquery) bilan oladi."""
        inner = select(Job.id)
        if conditions:
            inner = inner.where(*conditions)
        stmt = select(func.count()).select_from(inner.subquery())
        result = await self._execute(stmt)
        return int(result.scalar_one() or 0)

    @staticmethod
    def _apply_order(stmt: Select[Any], *, sort_by: str, sort_order: str) -> Select[Any]:
        """ORDER BY qo'shadi; faqat `JOB_SORT_COLUMNS` ichidagi ustunlar ruxsat etilgan."""
        if sort_by not in JOB_SORT_COLUMNS:
            raise ValidationError(
                f"'{sort_by}' bo'yicha tartiblash mumkin emas",
                details={"allowed": sorted(JOB_SORT_COLUMNS)},
            )
        column = getattr(Job, sort_by)
        ordering = column.asc() if sort_order.lower() == "asc" else column.desc()
        # `id` — barqaror ikkinchi mezon, aks holda bir xil sanalarda sahifalar takrorlanadi
        return stmt.order_by(ordering, Job.id.asc())

    @staticmethod
    def _time_column(name: str) -> Any:
        """Vaqt o'qi ustunini nomi bo'yicha qaytaradi (ruxsat etilganlar ro'yxatidan)."""
        if name not in JOB_TIME_COLUMNS:
            raise ValidationError(
                f"'{name}' vaqt ustuni sifatida ishlatilmaydi",
                details={"allowed": sorted(JOB_TIME_COLUMNS)},
            )
        return getattr(Job, name)

    def _bucket_expression(self, column: Any, interval: str) -> Any:
        """Vaqt ustunini oraliq bo'yicha "savat" (bucket) ifodasiga aylantiradi."""
        if interval not in JOB_BUCKET_INTERVALS:
            raise ValidationError(
                f"'{interval}' oralig'i qo'llab-quvvatlanmaydi",
                details={"allowed": list(JOB_BUCKET_INTERVALS)},
            )
        if self._is_sqlite():
            return func.strftime(_SQLITE_BUCKET_FORMATS[interval], column)
        # `timezone('UTC', col)` — sessiya vaqt zonasiga bog'liq bo'lmasligi uchun
        return func.date_trunc(interval, func.timezone("UTC", column))

    @staticmethod
    def _parse_bucket(value: Any) -> datetime | None:
        """Guruhlash natijasini `datetime`ga keltiradi (SQLite matn qaytaradi)."""
        if value is None:
            return None
        if isinstance(value, datetime):
            return ensure_utc(value)
        parsed = datetime.strptime(str(value), _SQLITE_BUCKET_PARSE)
        return ensure_utc(parsed)

    @staticmethod
    def _enum_condition(
        column: Any,
        enum_cls: type[StrEnum],
        value: Any,
    ) -> Any | None:
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

    @staticmethod
    def _percentile_key(value: float) -> str:
        """`0.95` -> `"p95"`, `0.999` -> `"p99_9"` (SQL label va lug'at kaliti sifatida)."""
        return "p" + f"{value * 100:g}".replace(".", "_")

    @staticmethod
    def _interpolate_percentile(values: Sequence[int], fraction: float) -> float | None:
        """`percentile_cont` semantikasi: tartiblangan ro'yxatda chiziqli interpolyatsiya."""
        if not values:
            return None
        if len(values) == 1:
            return float(values[0])
        position = fraction * (len(values) - 1)
        lower = int(position)
        upper = min(lower + 1, len(values) - 1)
        weight = position - lower
        return round(values[lower] + (values[upper] - values[lower]) * weight, 2)

    @staticmethod
    def _as_float(value: Any) -> float | None:
        """`AVG`/`percentile_cont` natijasini `float`ga keltiradi (`Decimal` ham bo'lishi mumkin)."""
        if value is None:
            return None
        return round(float(value), 2)

    @staticmethod
    def _as_int(value: Any) -> int | None:
        """`MIN`/`MAX` natijasini `int`ga keltiradi."""
        if value is None:
            return None
        return int(value)


__all__ = [
    "DEFAULT_PERCENTILES",
    "JOB_BUCKET_INTERVALS",
    "JOB_SORT_COLUMNS",
    "JOB_TIME_COLUMNS",
    "JobRepository",
]
