"""Durabl — `schedule_runs` jadvali: jadvalning har bir ishga tushishi.

Nega alohida jadval kerak (job'lar ro'yxatining o'zi yetmaydi):

1. **O'tkazib yuborilgan ishga tushish** — `allow_overlap=False` bo'lib
   oldingisi hamon ishlayotgan bo'lsa, job YARATILMAYDI. Agar tarix
   faqat job'lardan yig'ilsa, bu holat butunlay ko'rinmay ketadi va
   mijoz "nega 14:00 da ishlamadi?" degan savolga javob topmaydi.
2. **Rejalashtirilgan va haqiqiy vaqt farqi** — `scheduled_for` va
   `started_at` ikki xil ustun: scheduler band bo'lsa kechikish bo'ladi,
   va bu kechikish o'lchanishi kerak.
3. **Job o'chirilsa ham tarix qolishi** — `job_id` `SET NULL`, ya'ni
   job tozalangandan keyin ham "ishga tushdi va muvaffaqiyatli tugadi"
   yozuvi saqlanadi.

Yozuv har doim yaratiladi: job yaratilgan bo'lsa ham, o'tkazib
yuborilgan bo'lsa ham.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import ScheduleRunStatus
from app.models.base import (
    Base,
    DateTimeTZ,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    UUIDType,
    enum_column,
)

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from app.models.job import Job
    from app.models.schedule import Schedule


class ScheduleRun(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Jadval bo'yicha bitta ishga tushish yozuvi."""

    __tablename__ = "schedule_runs"

    schedule_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("schedules.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Yaratilgan job. `NULL` bo'lishi ikki holatda: (a) ishga tushish
    #: o'tkazib yuborilgan, (b) job keyinroq tozalangan (`SET NULL`).
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType,
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # ------------------------------------------------------------------
    # Vaqt
    # ------------------------------------------------------------------

    #: Cron bo'yicha rejalashtirilgan vaqt (`created_at` EMAS — scheduler
    #: kechiksa ikkisi farq qiladi va aynan shu farq o'lchanadi)
    scheduled_for: Mapped[datetime] = mapped_column(DateTimeTZ, nullable=False)
    #: Haqiqatda boshlangan vaqt. `NULL` — o'tkazib yuborilgan.
    started_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)
    #: Tugagan vaqt (muvaffaqiyatli yoki xato bilan)
    finished_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)
    #: Bajarilish davomiyligi (ms) — `finished_at - started_at` dan
    #: denormalizatsiya, analitika so'rovlari uchun
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # ------------------------------------------------------------------
    # Natija
    # ------------------------------------------------------------------

    status: Mapped[ScheduleRunStatus] = mapped_column(
        enum_column(ScheduleRunStatus), nullable=False, index=True
    )
    #: O'tkazib yuborilgan bo'lsa — sababi (odam o'qiydigan matn)
    skip_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: Xato xabari — `status=FAILED` bo'lganda to'ldiriladi
    error_message: Mapped[str | None] = mapped_column(String(2048), nullable=True)

    # ------------------------------------------------------------------
    # Bog'lanishlar
    # ------------------------------------------------------------------

    schedule: Mapped[Schedule] = relationship("Schedule", back_populates="runs", lazy="raise")
    job: Mapped[Job | None] = relationship("Job", lazy="raise")

    # ------------------------------------------------------------------
    # Indekslar
    # ------------------------------------------------------------------

    __table_args__ = (
        #: Bir xil daqiqa uchun ikki marta job yaratilmasligining DB
        #: darajasidagi kafolati. Scheduler klaster bo'yicha yakka, lekin
        #: deploy paytida qisqa vaqt ikki nusxa ishlashi mumkin — bu
        #: cheklov o'sha oynada ham ikkilanishni to'xtatadi.
        Index(
            "uq_schedule_runs_schedule_id_scheduled_for",
            "schedule_id",
            "scheduled_for",
            unique=True,
        ),
        #: Jadval sahifasidagi "oxirgi ishga tushishlar" ro'yxati
        Index(
            "ix_schedule_runs_schedule_id_scheduled_for",
            "schedule_id",
            "scheduled_for",
        ),
    )

    # ------------------------------------------------------------------
    # Yordamchi xossalar
    # ------------------------------------------------------------------

    @property
    def was_skipped(self) -> bool:
        """Ishga tushish o'tkazib yuborilganmi?"""
        return self.status is ScheduleRunStatus.SKIPPED

    @property
    def delay_seconds(self) -> float | None:
        """Rejadan qancha kechikib boshlandi. O'tkazib yuborilgan — `None`."""
        if self.started_at is None:
            return None
        return (self.started_at - self.scheduled_for).total_seconds()


__all__ = ["ScheduleRun"]
