"""Durabl — audit jurnali servisi (`audit_logs` jadvali).

Admin panelidagi har bir o'zgartirish (foydalanuvchini bloklash, admin
huquqini berish, rejani almashtirish) o'zgarmaydigan jurnal yozuvini
qoldirishi SHART. Bu servis ayni shu yozuvni yaratadi va o'qiydi.

**Nega alohida servis?** API qatlami modelga bevosita tegmaydi
(`CONTRACTS.md` §2): router `session.add(AuditLog(...))` yozsa, audit
mantig'i (qaysi maydonlar majburiy, `details` shakli, matn uzunligi
chegaralari) endpointlar bo'ylab tarqalib ketardi va har yangi admin
amalida qaytadan yozilardi.

**Tranzaksiya chegarasi.** `record()` ATAYLAB `commit()` QILMAYDI — audit
yozuvi o'zi qayd etayotgan o'zgartirish bilan BIR tranzaksiyada bo'lishi
kerak. Aks holda ikki yolg'on holat paydo bo'ladi: o'zgarish bor, audit
yo'q (yoki teskarisi). Commit chaqiruvchining (`AdminService`) ishi.

**Jadvalda audit uchun repozitoriy yo'q** (`app/repositories/` da
`audit_repo.py` mavjud emas), shuning uchun so'rovlar shu yerda
`select()` bilan yoziladi — `analytics_service.py` dagi ayni ruxsat
("QO'SHIMCHA 3") va ayni xato shartnomasi bilan: SQL xatolari
`DatabaseError` ga o'raladi.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.exceptions import DatabaseError
from app.logging_config import get_logger
from app.models.audit_log import AuditLog
from app.models.user import User
from app.schemas.admin import AuditLogRead
from app.utils.time_utils import ensure_utc

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi uchun
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.constants import AuditAction
    from app.schemas.base import PaginationParams

logger = get_logger(__name__)

#: `target_type` uchun barqaror qiymatlar — UI va qidiruv shularga tayanadi.
TARGET_USER: Final = "user"
TARGET_JOB: Final = "job"
TARGET_DLQ: Final = "dlq"
TARGET_API_KEY: Final = "api_key"

#: `audit_logs.ip_address` ustuni uzunligi (IPv6 uchun yetarli).
MAX_IP_LENGTH: Final = 45

#: `audit_logs.user_agent` ustuni uzunligi.
MAX_USER_AGENT_LENGTH: Final = 512


class AuditService:
    """Admin harakatlarini qayd etadi va jurnalni o'qiydi."""

    def __init__(self, session: AsyncSession) -> None:
        """Servisni so'rov sessiyasi bilan yaratadi.

        Args:
            session: Joriy tranzaksiya sessiyasi. `record()` unga yozadi,
                lekin `commit()` qilmaydi.
        """
        self.session = session

    # ------------------------------------------------------------------
    # Yozish
    # ------------------------------------------------------------------

    async def record(
        self,
        admin: User | uuid.UUID | str | None,
        action: AuditAction,
        *,
        target_type: str | None = None,
        target_id: uuid.UUID | str | None = None,
        details: dict[str, Any] | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AuditLog:
        """Bitta audit yozuvini yaratadi (`flush` qiladi, `commit` QILMAYDI).

        Args:
            admin: Harakatni bajargan admin — `User`, ID yoki `None`
                (tizim o'zi bajargan harakat: scheduler, DLQ protsessori).
            action: `AuditAction` qiymati.
            target_type: Obyekt turi (`TARGET_USER`, `TARGET_JOB`...).
            target_id: Obyekt identifikatori (matnga aylantiriladi).
            details: Qo'shimcha kontekst — odatda
                `{"field": ..., "old": ..., "new": ..., "reason": ...}`.
            ip_address: So'rov kelgan IP (ustun uzunligiga kesiladi).
            user_agent: Mijoz `User-Agent` qiymati (ustun uzunligiga kesiladi).

        Returns:
            Yaratilgan (hali commit qilinmagan) `AuditLog` yozuvi.

        Raises:
            DatabaseError: `flush` paytida DB xatosi.
        """
        entry = AuditLog(
            admin_id=self._admin_id(admin),
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=details,
            ip_address=self._clip(ip_address, MAX_IP_LENGTH),
            user_agent=self._clip(user_agent, MAX_USER_AGENT_LENGTH),
        )
        self.session.add(entry)
        try:
            await self.session.flush()
        except SQLAlchemyError as exc:  # pragma: no cover - infratuzilma xatosi
            raise DatabaseError(f"Audit yozuvi saqlanmadi: {exc}") from exc

        logger.info(
            "audit.recorded",
            action=str(action),
            admin_id=str(entry.admin_id) if entry.admin_id else None,
            target=entry.target_ref,
        )
        return entry

    # ------------------------------------------------------------------
    # O'qish
    # ------------------------------------------------------------------

    async def list(
        self,
        pagination: PaginationParams,
    ) -> tuple[list[AuditLogRead], int]:
        """Jurnal yozuvlari (yangisidan boshlab) va umumiy son.

        `AuditLogRead.admin_email` modelda YO'Q va `AuditLog.admin`
        relationship'i `lazy="raise"` bilan e'lon qilingan, shuning uchun
        email AYNI so'rovda `LEFT JOIN` orqali olinadi. `LEFT` ataylab:
        `admin_id` `NULL` bo'lishi mumkin (tizim harakati) yoki admin
        o'chirilgan bo'lishi mumkin (`ondelete="SET NULL"`) — bunday
        yozuvlar ro'yxatdan tushib qolmasligi kerak.

        Filtrlangan (harakat turi, oraliq, admin bo'yicha) ro'yxat uchun
        `AnalyticsService.audit_logs()` ishlatiladi — `GET /admin/audit-logs`
        aynan shuni chaqiradi. Bu metod esa filtrsiz, eng sodda kesim
        (boshqa servislar va diagnostika uchun).

        Returns:
            `(yozuvlar, jami_soni)` — API qatlami undan
            `PaginatedResponse[AuditLogRead]` yasaydi.

        Raises:
            DatabaseError: SQL bajarishda xato.
        """
        total = int((await self._fetch(select(func.count(AuditLog.id)))).scalar_one() or 0)
        if total == 0:
            return [], 0

        stmt = (
            select(AuditLog, User.email)
            .outerjoin(User, AuditLog.admin_id == User.id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.asc())
            .limit(pagination.limit)
            .offset(pagination.offset)
        )
        result = await self._fetch(stmt)
        return [self._to_schema(entry, email) for entry, email in result.all()], total

    # ------------------------------------------------------------------
    # Ichki yordamchilar
    # ------------------------------------------------------------------

    @staticmethod
    def _to_schema(entry: AuditLog, admin_email: str | None) -> AuditLogRead:
        """`AuditLog` + join natijasini javob schema'siga aylantiradi.

        SQLite naive `datetime` qaytaradi, shuning uchun `created_at`
        `ensure_utc()` bilan normallashtiriladi — aks holda javobda `...Z`
        chiqmaydi va brauzer vaqtni mahalliy deb o'qiydi (shartnoma §12).
        """
        return AuditLogRead.model_validate(entry).model_copy(
            update={
                "admin_email": admin_email,
                "created_at": ensure_utc(entry.created_at),
            }
        )

    @staticmethod
    def _admin_id(admin: User | uuid.UUID | str | None) -> uuid.UUID | None:
        """Admin argumentidan `admin_id` ni ajratadi.

        `User` obyekti, `uuid.UUID` yoki matn qabul qiladi. Matnni UUID'ga
        aylantirish imkonsiz bo'lsa `None` qaytadi: audit yozuvi yaroqsiz
        ID tufayli YO'QOLMASLIGI kerak (yozuv "tizim harakati" bo'lib
        qoladi, tafsilotlar esa `details` da saqlanadi).
        """
        if admin is None:
            return None
        if isinstance(admin, User):
            return admin.id
        if isinstance(admin, uuid.UUID):
            return admin
        try:
            return uuid.UUID(str(admin))
        except (ValueError, AttributeError, TypeError):
            logger.warning("audit.invalid_admin_id", value=str(admin))
            return None

    @staticmethod
    def _clip(value: str | None, limit: int) -> str | None:
        """Matnni ustun uzunligiga kesadi; bo'sh qiymat `None` bo'ladi."""
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            return None
        return trimmed[:limit]

    async def _fetch(self, stmt: Any) -> Any:
        """`select()` ni bajaradi va drayver xatosini `DatabaseError`ga o'raydi."""
        try:
            return await self.session.execute(stmt)
        except SQLAlchemyError as exc:  # pragma: no cover - infratuzilma xatosi
            raise DatabaseError(f"SQL bajarishda xato: {exc}") from exc


__all__ = [
    "MAX_IP_LENGTH",
    "MAX_USER_AGENT_LENGTH",
    "TARGET_API_KEY",
    "TARGET_DLQ",
    "TARGET_JOB",
    "TARGET_USER",
    "AuditService",
]
