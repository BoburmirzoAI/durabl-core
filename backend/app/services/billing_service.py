"""Durabl — obuna, kvota va foydalanish hisobi (billing) servisi.

Bu servis uch savolga javob beradi:

1. **Nima sotiladi** — `plans()`: `app.constants.PLAN_LIMITS` katalogi.
   Limitlar DB'da SAQLANMAYDI, shuning uchun narx yoki chegara o'zgarsa
   migratsiya kerak bo'lmaydi.
2. **Foydalanuvchi nimaga haqli** — `subscription()`, `limits_for()`:
   obuna yozuvi faqat reja NOMINI saqlaydi, limitlar `plan_limits()` dan.
3. **Qancha ishlatdi va ruxsat bormi** — `usage()`, `history()`,
   `check_quota()`, `check_concurrency()`, `record_job()`,
   `record_execution()`.

**Muddati o'tgan obuna FREE'ga qaytadi.** `Subscription.is_valid`
(`is_active and not is_expired(expires_at)`) `False` bo'lsa, limitlar
FREE rejadan olinadi. Bu xavfsiz standart: to'lov to'xtaganda xizmat
butunlay uzilmaydi, lekin pullik chegaralar ham berilmaydi.

**Tranzaksiya chegarasi.** `check_quota`, `record_job`, `record_execution`,
`limits_for` va `check_concurrency` — ICHKI metodlar: ularni `JobService`
va `ExecutionService` o'z tranzaksiyasi ichidan chaqiradi, shuning uchun
`commit()` QILMAYDI (aks holda chaqiruvchining yarim tugallangan ishi
commit bo'lib ketardi). `subscription`, `usage` va `change_plan` esa
API qatlami uchun: ular yozuvni yaratishi/yangilashi mumkin va o'zi
`commit()` qiladi. `plans` va `history` hech narsa yozmaydi.

**Kvota tekshiruvi YOZMAYDI.** `check_quota` joriy oy yozuvini
`get_for_period` bilan O'QIYDI (`current_period` emas): tekshiruv har bir
`submit` da bajariladi va yozuv bo'lmasa `INSERT` qilish ma'nosiz yon
ta'sir bo'lardi. Yozuv `record_job()` paytida — ya'ni job HAQIQATAN
qabul qilinganda — yaratiladi.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from redis.exceptions import RedisError

from app.constants import PLAN_LIMITS, PlanLimits, PlanType, RedisKeys, plan_limits
from app.exceptions import (
    ConcurrencyLimitError,
    QuotaExceededError,
    ValidationError,
)
from app.logging_config import get_logger
from app.repositories.subscription_repo import SubscriptionRepository
from app.repositories.usage_repo import UsageRepository
from app.schemas.billing import (
    PlanInfo,
    PlansResponse,
    UsageHistoryItem,
    UsageSummary,
)
from app.utils.time_utils import month_key, next_month, start_of_month, utcnow

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.subscription import Subscription
    from app.models.user import User

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Konstantalar
# ---------------------------------------------------------------------------

#: `history()` ko'pi bilan nechta oyni qaytaradi (so'rov og'irligini cheklash).
MAX_HISTORY_MONTHS: Final = 60

#: `history()` standart chuqurligi — bir yil.
DEFAULT_HISTORY_MONTHS: Final = 12

#: Rejalar katalogi arzondan qimmatga shu tartibda chiqadi.
PLAN_ORDER: Final[tuple[PlanType, ...]] = (
    PlanType.FREE,
    PlanType.STARTER,
    PlanType.PRO,
    PlanType.ENTERPRISE,
)

#: Narx jadvalida "ommabop" deb ajratiladigan reja (frontend `is_popular`).
POPULAR_PLAN: Final[PlanType] = PlanType.PRO


@dataclass(frozen=True, slots=True)
class PlanCopy:
    """Rejaning MARKETING matni (nom, tavsif, imkoniyatlar).

    Nega `app.constants` da emas: `constants.py` faqat MASHINA uchun
    kerakli chegaralarni saqlaydi va u eng past qatlam (hech narsaga
    bog'liq emas). Ko'rinadigan matn esa mahsulot qarori — u o'zgarsa
    limitlar o'zgarmaydi, shuning uchun alohida turadi.
    """

    name: str
    description: str
    features: tuple[str, ...]


#: Reja -> o'zbekcha ko'rinish matni. `PlansResponse` shundan to'ladi.
PLAN_PRESENTATION: Final[dict[PlanType, PlanCopy]] = {
    PlanType.FREE: PlanCopy(
        name="Bepul",
        description=(
            "Durabl bilan tanishish uchun. Kredit karta talab qilinmaydi, "
            "barcha ishonchlilik kafolatlari (DLQ, qayta urinish) amalda."
        ),
        features=(
            "Oyiga 1 000 ta job",
            "2 ta job bir vaqtda",
            "30 soniyagacha bajarish vaqti",
            "O'lik xatlar navbati (DLQ) va qo'lda qayta urinish",
            "Loglar 3 kun saqlanadi",
        ),
    ),
    PlanType.STARTER: PlanCopy(
        name="Boshlang'ich",
        description=(
            "Birinchi mijozlari paydo bo'lgan loyihalar uchun: tarmoqqa chiqish "
            "ochiladi va navbat chuqurligi sezilarli oshadi."
        ),
        features=(
            "Oyiga 50 000 ta job",
            "10 ta job bir vaqtda",
            "2 daqiqagacha bajarish vaqti, 512 MB xotira",
            "Sandbox ichidan tarmoqqa chiqish",
            "Webhook'lar va 14 kunlik loglar",
        ),
    ),
    PlanType.PRO: PlanCopy(
        name="Professional",
        description=(
            "Ishlab chiqarishdagi yuklama uchun: yuqori ustuvorlikdagi navbat, "
            "kuchli sandbox va bir oylik log tarixi."
        ),
        features=(
            "Oyiga 500 000 ta job",
            "50 ta job bir vaqtda",
            "5 daqiqagacha bajarish vaqti, 1 GB xotira, 2 yadro",
            "Yuqori ustuvorlikdagi navbat va batafsil analitika",
            "Loglar 30 kun saqlanadi",
            "Daqiqada 600 so'rov",
        ),
    ),
    PlanType.ENTERPRISE: PlanCopy(
        name="Korporativ",
        description=(
            "Katta hajm va qat'iy talablar uchun: eng yuqori chegaralar, "
            "uzoq log tarixi va shartnoma asosida qo'llab-quvvatlash."
        ),
        features=(
            "Oyiga 10 000 000 ta job",
            "500 ta job bir vaqtda",
            "15 daqiqagacha bajarish vaqti, 4 GB xotira, 4 yadro",
            "90 kunlik log tarixi va audit jurnali",
            "Shartnoma asosida SLA va maxsus ko'rsatmalar",
            "Daqiqada 5 000 so'rov",
        ),
    ),
}


class BillingService:
    """Obuna va foydalanish hisobi.

    Konstruktor FAQAT `AsyncSession` oladi (shartnoma §6). Redis kerak
    bo'ladigan yagona metod — `check_concurrency()` — klientni argument
    sifatida qabul qiladi, shuning uchun servis Redis'ga bog'lanmaydi va
    worker protsessida ham ayni kod ishlaydi.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.subscriptions = SubscriptionRepository(session)
        #: DIQQAT: atribut nomi `usage` BO'LMAYDI — u ayni nomli public
        #: metodni instansiyada soya qilib qo'yardi (`await svc.usage(user)`
        #: repozitoriy obyektini chaqirishga urinib `TypeError` berardi).
        self.usage_records = UsageRepository(session)

    # ------------------------------------------------------------------
    # Katalog
    # ------------------------------------------------------------------

    async def plans(self, *, current_plan: PlanType | str | None = None) -> PlansResponse:
        """Barcha rejalar katalogi (arzondan qimmatga).

        Statik ma'lumot — `PLAN_LIMITS` va `PLAN_PRESENTATION` kodda
        turadi, shuning uchun keshlash ham, DB so'rovi ham kerak emas
        (endpoint autentifikatsiyasiz ham ishlaydi).

        Args:
            current_plan: Foydalanuvchining joriy rejasi. Berilmasa
                (`None` — anonim so'rov) HECH BIR rejada `is_current`
                belgilanmaydi, javobdagi `current_plan` esa standart
                `free` bo'ladi (frontend uni faqat zaxira qiymat sifatida
                ishlatadi).
        """
        resolved = self._coerce_plan(current_plan) if current_plan is not None else None
        return PlansResponse(
            items=[
                PlanInfo.build(
                    PLAN_LIMITS[plan],
                    name=PLAN_PRESENTATION[plan].name,
                    description=PLAN_PRESENTATION[plan].description,
                    features=list(PLAN_PRESENTATION[plan].features),
                    is_popular=plan is POPULAR_PLAN,
                    is_current=resolved is not None and plan is resolved,
                )
                for plan in PLAN_ORDER
            ],
            current_plan=resolved or PlanType.FREE,
        )

    # ------------------------------------------------------------------
    # Obuna
    # ------------------------------------------------------------------

    async def subscription(self, user: User) -> Subscription:
        """Foydalanuvchining obunasi; yo'q bo'lsa FREE reja bilan yaratiladi.

        Yozuv yaratilishi mumkin, shuning uchun metod o'z tranzaksiyasini
        yopadi (`commit`). Chaqiruvchi service ichidan kerak bo'lsa
        `SubscriptionRepository.ensure_for_user()` ni bevosita ishlating.
        """
        subscription = await self.subscriptions.ensure_for_user(user.id)
        await self.session.commit()
        return subscription

    async def limits_for(self, user_id: uuid.UUID | str) -> PlanLimits:
        """Foydalanuvchining amaldagi reja limitlari.

        ICHKI metod: faqat O'QIYDI (`get_for_user`), yozuv YARATMAYDI va
        `commit()` QILMAYDI — shuning uchun boshqa service'ning
        tranzaksiyasi ichidan chaqirish xavfsiz.

        Obuna yo'q bo'lsa yoki muddati o'tgan bo'lsa FREE limitlari
        qaytadi.
        """
        subscription = await self.subscriptions.get_for_user(user_id)
        return self._effective_limits(subscription)

    async def change_plan(self, user: User, plan: PlanType) -> Subscription:
        """Obuna rejasini almashtiradi.

        Reja almashtirilganda muddat QAYTA BOSHLANADI: `started_at = utcnow()`,
        `expires_at = None` (ya'ni muddatsiz), `is_active = True` va
        `cancelled_at` tozalanadi. Haqiqiy to'lov davri (`expires_at`)
        to'lov tizimi integratsiyasining mas'uliyati — u obunani keyin
        o'z muddatini qo'yib yangilaydi.

        `AuditLog` yozuvi YARATILMAYDI: audit admin harakatini qayd etadi
        va unga `admin_id`, IP, `User-Agent` kerak — bu ma'lumot faqat
        admin servisi/API qatlamida mavjud. Reja admin tomonidan
        o'zgartirilsa `AuditAction.PLAN_CHANGED` yozuvini o'sha qatlam
        yozadi.

        Raises:
            ValidationError: Noma'lum reja nomi berilsa.
        """
        target = self._coerce_plan(plan)
        subscription = await self.subscriptions.ensure_for_user(user.id)
        previous = PlanType(subscription.plan)

        await self.subscriptions.update(
            subscription,
            plan=target,
            started_at=utcnow(),
            expires_at=None,
            is_active=True,
            cancelled_at=None,
        )
        await self.session.commit()

        logger.info(
            "billing.plan_changed",
            user_id=str(user.id),
            previous_plan=previous.value,
            plan=target.value,
        )
        return subscription

    # ------------------------------------------------------------------
    # Foydalanish
    # ------------------------------------------------------------------

    async def usage(self, user: User) -> UsageSummary:
        """Joriy davr (oy) iste'moli va reja limitlari.

        Joriy oy yozuvi yo'q bo'lsa nol hisoblagichlar bilan YARATILADI
        (`UsageRepository.current_period`), shuning uchun metod `commit()`
        qiladi — aks holda yozuv sessiya yopilganda qaytarilib, keyingi
        so'rovda qaytadan yaratilishga urinilardi.

        `period_end` — `next_month()`, ya'ni limit aynan shu vaqtda
        yangilanadi (davr kalendar oyi bo'yicha).

        `remaining`, `usage_percent` va `is_over_limit` — schema'dagi
        `computed_field` lar, shuning uchun bu yerda qo'lda hisoblanmaydi
        (bitta formulaga ikki manba bo'lmaydi).
        """
        subscription = await self.subscriptions.ensure_for_user(user.id)
        limits = self._effective_limits(subscription)
        record = await self.usage_records.current_period(user.id)
        await self.session.commit()

        return UsageSummary(
            period=record.period,
            plan=limits.plan,
            job_count=record.job_count,
            success_count=record.success_count,
            failed_count=record.failed_count,
            execution_seconds=record.execution_seconds,
            monthly_limit=limits.monthly_jobs,
            concurrent_limit=limits.max_concurrent_jobs,
            period_start=start_of_month(),
            period_end=next_month(),
        )

    async def history(
        self,
        user: User,
        *,
        limit: int = DEFAULT_HISTORY_MONTHS,
    ) -> list[UsageHistoryItem]:
        """Oylik foydalanish tarixi (yangisidan boshlab).

        Faqat O'QIYDI — `commit()` qilmaydi.
        """
        bounded = max(1, min(int(limit), MAX_HISTORY_MONTHS))
        records = await self.usage_records.history(user.id, bounded)
        return [UsageHistoryItem.model_validate(record) for record in records]

    async def record_job(self, user_id: uuid.UUID | str) -> None:
        """Yuborilgan job'ni oylik hisobga qo'shadi (`job_count += 1`).

        ICHKI metod — `commit()` QILMAYDI. Tranzaksiyani chaqiruvchi
        (`JobService.submit`) yopadi: shu tufayli job yozuvi va hisob
        bitta atomar o'zgarishda qoladi.

        Hisoblagich SQL tomonida oshiriladi
        (`UsageRepository.increment`), shuning uchun parallel so'rovlar
        bir-birining qiymatini ustiga yozmaydi.
        """
        await self.usage_records.increment(user_id, month_key(), jobs=1)

    async def record_execution(
        self,
        user_id: uuid.UUID | str,
        seconds: float,
        *,
        success: bool,
    ) -> None:
        """Bajarish natijasini oylik hisobga qo'shadi.

        ICHKI metod — `commit()` QILMAYDI (`ExecutionService` o'z
        tranzaksiyasini yopadi).

        `seconds` manfiy bo'lsa nolga tenglashtiriladi: davomiylik
        hisoblashdagi xato (masalan soat orqaga surilishi) oylik
        yig'indini KAMAYTIRIB qo'ymasligi kerak.

        `job_count` BU YERDA oshirilmaydi: kvota yuborilgan job'lar
        bo'yicha hisoblanadi, qayta urinishlar esa yangi job emas —
        aks holda bitta job 4 urinish bilan kvotadan 4 ta "yeb" ketardi.
        """
        amount = max(0.0, float(seconds))
        await self.usage_records.increment(
            user_id,
            month_key(),
            success=1 if success else 0,
            failed=0 if success else 1,
            seconds=amount,
        )

    # ------------------------------------------------------------------
    # Cheklovlar
    # ------------------------------------------------------------------

    async def check_quota(self, user: User) -> None:
        """Oylik job kvotasini tekshiradi.

        ICHKI metod — hech narsa yozmaydi va `commit()` qilmaydi.

        Obuna muddati o'tgan bo'lsa FREE limitlari qo'llanadi.

        Raises:
            QuotaExceededError: Joriy oyda `job_count >= monthly_jobs`.
        """
        subscription = await self.subscriptions.get_for_user(user.id)
        limits = self._effective_limits(subscription)
        if limits.monthly_jobs <= 0:  # pragma: no cover - katalogda bunday reja yo'q
            return

        record = await self.usage_records.get_for_period(user.id, month_key())
        used = int(record.job_count) if record is not None else 0
        if used < limits.monthly_jobs:
            return

        logger.warning(
            "billing.quota_exceeded",
            user_id=str(user.id),
            plan=limits.plan.value,
            used=used,
            limit=limits.monthly_jobs,
        )
        raise QuotaExceededError(
            used=used,
            limit=limits.monthly_jobs,
            plan=limits.plan.value,
            message=(
                f"Oylik kvota tugadi: {limits.monthly_jobs} job "
                f"({limits.plan.value} reja). Keyingi oyni kuting yoki rejani oshiring"
            ),
        )

    async def check_concurrency(self, user_id: uuid.UUID | str, redis: Redis) -> None:
        """Bir vaqtda bajarilayotgan job'lar limitini tekshiradi.

        Hisoblagich Redis'da (`RedisKeys.concurrency(user_id)`) — uni
        `JobService` job `RUNNING` ga kirganda `INCR`, chiqqanda `DECR`
        qiladi.

        **FAIL-OPEN.** Redis javob bermasa tekshiruv o'tkazib yuboriladi:
        Durabl'ning asosiy kafolati "job yo'qolmaydi", shuning uchun
        Redis uzilishi job qabul qilishni to'xtatmaydi. Ortiqcha yuklanish
        lease va worker soni bilan baribir cheklangan.

        Taqqoslash `>=` bilan: hisoblagich HOZIR bajarilayotganlar sonini
        beradi, demak qiymat limitga TENG bo'lsa ham bo'sh joy yo'q
        (`JobService._assert_concurrency` bilan ayni semantika).

        Raises:
            ConcurrencyLimitError: Limit to'lgan bo'lsa.
        """
        limits = await self.limits_for(user_id)
        if limits.max_concurrent_jobs <= 0:  # pragma: no cover - katalogda yo'q
            return

        try:
            raw = await redis.get(RedisKeys.concurrency(user_id))
        except RedisError as exc:
            logger.warning(
                "billing.concurrency_check_skipped",
                user_id=str(user_id),
                error=str(exc),
            )
            return

        active = self._as_count(raw)
        if active < limits.max_concurrent_jobs:
            return

        raise ConcurrencyLimitError(
            f"Bir vaqtda {limits.max_concurrent_jobs} tadan ko'p job bajarilmaydi "
            "(hozirgi job'lar tugashini kuting yoki rejani oshiring)",
            details={
                "active": active,
                "limit": limits.max_concurrent_jobs,
                "plan": limits.plan.value,
            },
        )

    # ------------------------------------------------------------------
    # Ichki yordamchilar
    # ------------------------------------------------------------------

    @staticmethod
    def _effective_limits(subscription: Subscription | None) -> PlanLimits:
        """Amaldagi limitlar: obuna yo'q yoki muddati o'tgan bo'lsa FREE.

        `Subscription.is_valid` tayyor xossasi ishlatiladi
        (`is_active and not is_expired(expires_at)`) — muddat mantig'i
        bitta joyda qoladi.
        """
        if subscription is None or not subscription.is_valid:
            return plan_limits(PlanType.FREE)
        return subscription.limits

    @staticmethod
    def _coerce_plan(plan: PlanType | str) -> PlanType:
        """Reja nomini enumga aylantiradi.

        `plan_limits()` noma'lum rejani JIMGINA FREE'ga aylantiradi — bu
        katalogni o'qishda to'g'ri, lekin obunani O'ZGARTIRISHDA xavfli
        (mijoz `pro` deb yozmoqchi bo'lib `prо` yozsa, pulini to'lab FREE
        olardi). Shuning uchun bu yerda ochiq xato beriladi.
        """
        try:
            return PlanType(plan)
        except ValueError as exc:
            raise ValidationError(
                f"Noma'lum reja: {plan}",
                details={"allowed": [member.value for member in PlanType]},
            ) from exc

    @staticmethod
    def _as_count(raw: Any) -> int:
        """Redis hisoblagichini manfiy bo'lmagan butun songa aylantiradi.

        Qiymat yo'q, bo'sh yoki buzuq bo'lsa `0` — "band emas" degan
        xavfsiz standart (fail-open siyosatiga mos).
        """
        if raw is None:
            return 0
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            logger.warning("billing.concurrency_value_invalid", value=str(raw))
            return 0


__all__ = [
    "DEFAULT_HISTORY_MONTHS",
    "MAX_HISTORY_MONTHS",
    "PLAN_ORDER",
    "PLAN_PRESENTATION",
    "POPULAR_PLAN",
    "BillingService",
    "PlanCopy",
]
