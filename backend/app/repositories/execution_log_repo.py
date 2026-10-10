"""Durabl — `execution_logs` jadvali uchun repository.

Bu jadval loyihada eng tez o'sadigan jadval, shuning uchun yozish yo'li
ataylab "arzon" qilingan: `bulk_add()` bitta `INSERT` bayonotini `executemany`
rejimida bajaradi (har qator uchun alohida so'rov yuborilmaydi) va ORM
obyektlari yaratilmaydi.

`bulk_add()` ikki xil kirishni qabul qiladi:

* `app.execution.executor.LogEntry` dataclass'lari (`stream`, `content`,
  `sequence`, `timestamp` atributlari bilan);
* oddiy lug'atlar (`{"stream": ..., "content": ...}`).

Shu tufayli repository `app.execution` paketiga BOG'LIQ EMAS — maydonlar
`getattr`/`Mapping.get` orqali o'qiladi (qatlam yo'nalishi buzilmaydi).

O'qish yo'li kursorli: `list_for_execution(..., after_sequence=N)` —
`(execution_id, sequence)` indeksidan foydalanadi va real vaqtda log
"quyilishi"ni sahifalab olishga mos.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, insert, select
from sqlalchemy import delete as sa_delete
from sqlalchemy.exc import SQLAlchemyError

from app.constants import LogStream
from app.exceptions import DatabaseError, ValidationError
from app.models.execution_log import ExecutionLog
from app.repositories.base import BaseRepository
from app.utils.time_utils import ensure_utc, utcnow

#: Bitta so'rovda qaytariladigan log qatorlari soni (API ham shu standartni ishlatadi)
DEFAULT_LOG_LIMIT = 500


class ExecutionLogRepository(BaseRepository[ExecutionLog]):
    """Bajarish loglari bilan ishlash qatlami."""

    model = ExecutionLog

    # ------------------------------------------------------------------
    # Yozish
    # ------------------------------------------------------------------

    async def bulk_add(
        self,
        execution_id: uuid.UUID | str,
        job_id: uuid.UUID | str,
        entries: Sequence[Any],
    ) -> int:
        """Ko'p log qatorini BITTA `INSERT` (`executemany`) bilan yozadi.

        Args:
            execution_id: Qaysi urinishning loglari.
            job_id: Job identifikatori (jadvalda denormalizatsiya qilingan).
            entries: `LogEntry` dataclass'lari yoki lug'atlar ketma-ketligi.
                Har bir element `stream`, `content`, `sequence`, `timestamp`
                maydonlarini berishi mumkin.

        `sequence` berilmagan elementlar uchun raqam `next_sequence()` dan
        boshlab o'sib boradi. Agar elementlarning bir qismi `sequence` bersa,
        bir qismi bermasa — raqamlar to'qnashishi mumkin, shuning uchun
        chaqiruvchi IKKI usuldan BIRINI tanlashi kerak (hammasiga berish yoki
        hech biriga bermaslik).

        Returns:
            Yozilgan qatorlar soni.
        """
        if not entries:
            return 0

        exec_id = self._coerce_id(execution_id)
        owner_job_id = self._coerce_id(job_id)
        next_free: int | None = None
        rows: list[dict[str, Any]] = []

        for entry in entries:
            sequence = self._field(entry, "sequence")
            if sequence is None:
                if next_free is None:
                    next_free = await self.next_sequence(execution_id)
                sequence = next_free
                next_free += 1

            content = self._field(entry, "content")
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "execution_id": exec_id,
                    "job_id": owner_job_id,
                    "stream": self._coerce_stream(self._field(entry, "stream")),
                    "content": "" if content is None else str(content),
                    "sequence": int(sequence),
                    "timestamp": ensure_utc(self._field(entry, "timestamp")) or utcnow(),
                }
            )

        try:
            await self.session.execute(insert(ExecutionLog), rows)
        except SQLAlchemyError as exc:
            raise DatabaseError(
                f"Loglarni yozishda xato: {exc}",
                details={"table": ExecutionLog.__tablename__, "rows": len(rows)},
            ) from exc
        return len(rows)

    async def delete_older_than(self, cutoff: datetime) -> int:
        """`cutoff` dan eski loglarni o'chiradi (reja `log_retention_days` bo'yicha tozalash).

        `synchronize_session=False` qo'yilgan: ORM sessiyadagi yuklangan
        obyektlarni Python tomonida solishtirib ko'rmaydi. Buning ikki sababi
        bor — (1) millionlab qatorni o'chirishda qo'shimcha `SELECT` qilinmaydi,
        (2) SQLite naive `datetime` qaytargani uchun Python tomonidagi
        solishtirish `offset-naive`/`offset-aware` xatosini beradi. Shu tufayli
        bu metod FON tozalash uchun mo'ljallangan: chaqirgan sessiyada
        yuklangan `ExecutionLog` obyektlari eskirgan hisoblanadi.

        Returns:
            O'chirilgan qatorlar soni.
        """
        moment = ensure_utc(cutoff) or utcnow()
        stmt = (
            sa_delete(ExecutionLog)
            .where(ExecutionLog.timestamp < moment)
            .execution_options(synchronize_session=False)
        )
        result = await self._execute(stmt)
        return int(result.rowcount or 0)

    # ------------------------------------------------------------------
    # O'qish
    # ------------------------------------------------------------------

    async def next_sequence(self, execution_id: uuid.UUID | str) -> int:
        """Urinish uchun keyingi bo'sh tartib raqami (`MAX(sequence) + 1`, bo'sh bo'lsa `0`).

        `sequence` 0 dan boshlanadi — model izohida kelishilgan.
        """
        stmt = select(func.max(ExecutionLog.sequence)).where(
            ExecutionLog.execution_id == self._coerce_id(execution_id)
        )
        result = await self._execute(stmt)
        highest = result.scalar_one_or_none()
        return int(highest) + 1 if highest is not None else 0

    async def list_for_execution(
        self,
        execution_id: uuid.UUID | str,
        after_sequence: int | None = None,
        limit: int = DEFAULT_LOG_LIMIT,
        stream: LogStream | str | None = None,
    ) -> list[ExecutionLog]:
        """Urinish loglari — tartib raqami bo'yicha o'sish tartibida.

        `after_sequence` berilsa faqat shundan KEYINGI qatorlar qaytadi
        (real vaqtda log kuzatish uchun kursor).
        """
        conditions: list[Any] = [ExecutionLog.execution_id == self._coerce_id(execution_id)]
        if after_sequence is not None:
            conditions.append(ExecutionLog.sequence > after_sequence)
        if stream is not None:
            conditions.append(ExecutionLog.stream == self._coerce_stream(stream))

        stmt: Select[Any] = (
            select(ExecutionLog)
            .where(*conditions)
            .order_by(ExecutionLog.sequence.asc())
            .limit(limit)
        )
        result = await self._execute(stmt)
        return list(result.scalars().all())

    async def list_for_job(
        self,
        job_id: uuid.UUID | str,
        limit: int = DEFAULT_LOG_LIMIT,
        stream: LogStream | str | None = None,
    ) -> list[ExecutionLog]:
        """Job'ning barcha urinishlaridagi loglar (vaqt bo'yicha tartiblangan).

        `job_id` denormalizatsiya qilingani uchun `executions` bilan `JOIN`
        qilish kerak emas.
        """
        conditions: list[Any] = [ExecutionLog.job_id == self._coerce_id(job_id)]
        if stream is not None:
            conditions.append(ExecutionLog.stream == self._coerce_stream(stream))

        stmt: Select[Any] = (
            select(ExecutionLog)
            .where(*conditions)
            .order_by(ExecutionLog.timestamp.asc(), ExecutionLog.sequence.asc())
            .limit(limit)
        )
        result = await self._execute(stmt)
        return list(result.scalars().all())

    async def count_for_execution(self, execution_id: uuid.UUID | str) -> int:
        """Urinishdagi log qatorlari soni."""
        stmt = (
            select(func.count())
            .select_from(ExecutionLog)
            .where(ExecutionLog.execution_id == self._coerce_id(execution_id))
        )
        result = await self._execute(stmt)
        return int(result.scalar_one() or 0)

    # ------------------------------------------------------------------
    # Ichki yordamchilar
    # ------------------------------------------------------------------

    @staticmethod
    def _field(entry: Any, name: str) -> Any:
        """Elementdan maydon o'qiydi: lug'at bo'lsa `get`, obyekt bo'lsa `getattr`."""
        if isinstance(entry, Mapping):
            return entry.get(name)
        return getattr(entry, name, None)

    @staticmethod
    def _coerce_stream(value: Any) -> LogStream:
        """Oqim turini `LogStream`ga keltiradi; berilmasa `stdout` deb olinadi."""
        if value is None:
            return LogStream.STDOUT
        try:
            return LogStream(value)
        except ValueError as exc:
            raise ValidationError(
                f"Yaroqsiz log oqimi: {value}",
                details={"allowed": [member.value for member in LogStream]},
            ) from exc


__all__ = ["DEFAULT_LOG_LIMIT", "ExecutionLogRepository"]
