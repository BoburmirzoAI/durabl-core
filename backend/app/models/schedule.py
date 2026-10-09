"""Durabl — `schedules` jadvali: cron bo'yicha takroriy job'lar.

Jadval — job'ning o'zi EMAS, balki job yaratish **retsepti**: kod,
runtime, limitlar va cron ifodasi bir joyda saqlanadi. Scheduler worker
har tikda `next_run_at <= now()` bo'lgan faol jadvallarni oladi, har biri
uchun yangi `Job` yaratadi va `next_run_at` ni qayta hisoblaydi.

Nega kod shu yerda saqlanadi (job'dan nusxalanmaydi): mijoz jadval
kodini bir marta o'zgartirsa, keyingi barcha ishga tushishlar yangi kod
bilan ketishi kerak. Agar kod faqat yaratilgan job'da bo'lsa, eski
job'ni nusxalash eski kodni ham olib kelardi.

**Uch xil "to'xtagan" holat farqlanadi** (`webhooks` bilan bir xil
mantiq):

* `status=PAUSED` — mijoz o'zi to'xtatdi, qayta yoqishi mumkin.
* `status=ERRORED` — ketma-ket `SCHEDULE_FAILURE_THRESHOLD` marta
  yiqilgandan keyin TIZIM to'xtatdi. Mijoz tuzatib qayta yoqadi.
* `deleted_at IS NOT NULL` — o'chirilgan. Yumshoq o'chirish ishlatiladi,
  chunki `schedule_runs` tarixi saqlanib qolishi kerak.

`next_run_at` ustuni ATAYLAB denormalizatsiya: cron'ni har tikda barcha
jadvallar uchun qayta hisoblash o'rniga bitta indeksli solishtirish
bo'ladi — scheduler sekundda bir marta ishlaydi, shuning uchun bu muhim.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    false,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.constants import Priority, Runtime, ScheduleStatus
from app.models.base import (
    Base,
    DateTimeTZ,
    JSONType,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    UUIDType,
    enum_column,
)

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from app.models.schedule_run import ScheduleRun
    from app.models.user import User

#: Ketma-ket shuncha marta yiqilgandan keyin jadval `ERRORED` ga o'tadi.
#: 3 — frontend ko'rsatayotgan qiymat; past tutilgan, chunki har bir
#: muvaffaqiyatsiz ishga tushish mijoz kvotasini yeydi.
SCHEDULE_FAILURE_THRESHOLD: Final[int] = 3

#: Cron ifodasi uchun maksimal uzunlik (5 maydon + bo'shliqlar bilan
#: eng uzun realistik ifoda ~100 belgi; zapas bilan olingan).
MAX_CRON_LENGTH: Final[int] = 128

#: IANA zona nomining eng uzuni ~32 belgi (`America/Argentina/Buenos_Aires`).
MAX_TIMEZONE_LENGTH: Final[int] = 64


class Schedule(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """Cron bo'yicha takroriy ishga tushadigan job retsepti."""

    __tablename__ = "schedules"

    #: Jadval egasi
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ------------------------------------------------------------------
    # Identifikatsiya
    # ------------------------------------------------------------------

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    # ------------------------------------------------------------------
    # Rejalashtirish
    # ------------------------------------------------------------------

    #: 5 maydonli POSIX cron ifodasi (`*/15 * * * *`)
    cron: Mapped[str] = mapped_column(String(MAX_CRON_LENGTH), nullable=False)
    #: IANA zona nomi — cron AYNI shu zonada hisoblanadi, UTC'da emas.
    #: Busiz "har kuni ertalab 9 da" yozgi/qishki vaqtda siljib ketadi.
    timezone: Mapped[str] = mapped_column(
        String(MAX_TIMEZONE_LENGTH),
        default="UTC",
        server_default=text("'UTC'"),
        nullable=False,
    )
    #: Keyingi ishga tushish vaqti (UTC) — scheduler shu ustun bo'yicha
    #: tanlaydi. `NULL` — jadval faol emas yoki hisoblash kutilmoqda.
    next_run_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)
    #: Oldingi ishga tushish davom etayotgan bo'lsa, yangisi boshlanaveradimi
    allow_overlap: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=false(), nullable=False
    )

    # ------------------------------------------------------------------
    # Job retsepti — yaratiladigan job'ga ko'chiriladigan maydonlar
    # ------------------------------------------------------------------

    runtime: Mapped[Runtime] = mapped_column(enum_column(Runtime), nullable=False)
    #: Bajarilishi kerak bo'lgan kod (job'ga nusxalanadi)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    #: Kirish ma'lumotlari — har ishga tushishda bir xil
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONType, nullable=True)
    #: Muhit o'zgaruvchilari (job'ga nusxalanadi)
    env_vars: Mapped[dict[str, str] | None] = mapped_column(JSONType, nullable=True)
    priority: Mapped[Priority] = mapped_column(
        enum_column(Priority),
        default=Priority.NORMAL,
        server_default=text(f"'{Priority.NORMAL.value}'"),
        nullable=False,
    )
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_mb: Mapped[int] = mapped_column(Integer, nullable=False)
    max_retries: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    # ------------------------------------------------------------------
    # Holat
    # ------------------------------------------------------------------

    status: Mapped[ScheduleStatus] = mapped_column(
        enum_column(ScheduleStatus),
        default=ScheduleStatus.ACTIVE,
        server_default=text(f"'{ScheduleStatus.ACTIVE.value}'"),
        nullable=False,
        index=True,
    )
    #: Oxirgi ishga tushish vaqti (`schedule_runs` dan denormalizatsiya —
    #: ro'yxat sahifasi har qator uchun alohida so'rov qilmasligi uchun)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTimeTZ, nullable=True)
    #: Oxirgi ishga tushishning natijasi (`ScheduleRunStatus` qiymati)
    last_run_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    #: Ketma-ket muvaffaqiyatsizliklar — muvaffaqiyatda 0 ga qaytadi
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    total_runs: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )
    failed_runs: Mapped[int] = mapped_column(
        Integer, default=0, server_default=text("0"), nullable=False
    )

    # ------------------------------------------------------------------
    # Bog'lanishlar
    # ------------------------------------------------------------------

    user: Mapped[User] = relationship("User", back_populates="schedules", lazy="raise")
    runs: Mapped[list[ScheduleRun]] = relationship(
        "ScheduleRun",
        back_populates="schedule",
        lazy="raise",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    # ------------------------------------------------------------------
    # Indekslar
    # ------------------------------------------------------------------

    __table_args__ = (
        #: Bir foydalanuvchida bir xil nomli ikki jadval bo'lmasin.
        #: `deleted_at` kiritilmagan: yumshoq o'chirilgan jadval nomi band
        #: qoladi — bu ataylab, chunki `schedule_runs` tarixi nom bo'yicha
        #: izlanadi va nomni qayta ishlatish tarixni chalkashtiradi.
        Index("uq_schedules_user_id_name", "user_id", "name", unique=True),
        #: Scheduler'ning asosiy so'rovi: faol va vaqti kelgan jadvallar.
        #: Ustunlar tartibi muhim — `status` tanlab oladi, `next_run_at`
        #: saralaydi.
        Index("ix_schedules_status_next_run_at", "status", "next_run_at"),
    )

    # ------------------------------------------------------------------
    # Yordamchi xossalar
    # ------------------------------------------------------------------

    @property
    def is_runnable(self) -> bool:
        """Jadval haqiqatan ishga tushadimi: faol va o'chirilmagan."""
        return self.status is ScheduleStatus.ACTIVE and self.deleted_at is None

    @property
    def is_auto_disabled(self) -> bool:
        """Tizim ketma-ket xatolar tufayli to'xtatganmi?"""
        return self.status is ScheduleStatus.ERRORED

    @property
    def success_rate(self) -> float | None:
        """Muvaffaqiyat ulushi (0..1). Hali ishga tushmagan bo'lsa — `None`."""
        if self.total_runs == 0:
            return None
        return (self.total_runs - self.failed_runs) / self.total_runs


__all__ = [
    "MAX_CRON_LENGTH",
    "MAX_TIMEZONE_LENGTH",
    "SCHEDULE_FAILURE_THRESHOLD",
    "Schedule",
]
