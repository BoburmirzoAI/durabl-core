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
from app.repositories.job_repo import JobRepository
from app.repositories.subscription_repo import SubscriptionRepository
from app.repositories.usage_repo import UsageRepository
from app.schemas.billing import (
    PlanInfo,
    PlansResponse,
    UsageHistoryItem,
    UsageSummary,
)
from app.utils.time_utils import (
    month_key,
    month_key_start,
    next_month,
    start_of_month,
    utcnow,
)

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

#: ## Overage (limitdan oshish) narxi NEGA YO'Q
#:
#: Durabl kvotaga yetganda job'ni QABUL QILMAYDI (`check_quota` ->
#: `QuotaExceededError`), ya'ni "limitdan oshib ishlatish" holati
#: TEXNIK JIHATDAN mavjud emas. Shu sababli prognoz va kalkulyatorda
#: `overage_usd` har doim 0 va `overage_label` `None`.
#:
#: Agar kelgusida overage sotilsa, bu yerga narx qo'shiladi va
#: `check_quota` bloklash o'rniga hisob yozishga o'tadi — ikkisi birga
#: o'zgarishi SHART, aks holda mijozdan bloklangan ish uchun pul
#: olinardi.
OVERAGE_USD_PER_JOB: Final[float] = 0.0

#: Kvota drill-down qo'llaydigan o'lchagichlar.
#:
#: FAQAT tarixi saqlanadigan o'lchagichlar bor.
#: `max_concurrent_jobs` va `requests_per_minute` ATAYLAB yo'q: ular
#: Redis'da LAHZALIK qiymat sifatida yashaydi (hisoblagich TTL bilan
#: o'chadi), ya'ni "kunlar bo'yicha" yoki "kesim bo'yicha" tahlil
#: yasash uchun ma'lumot YO'Q. Ularni qo'shish uchun avval o'lchov
#: saqlanishi kerak.
QUOTA_MONTHLY_JOBS: Final[str] = "monthly_jobs"
QUOTA_COMPUTE_SECONDS: Final[str] = "compute_seconds"
QUOTA_KEYS: Final[frozenset[str]] = frozenset({QUOTA_MONTHLY_JOBS, QUOTA_COMPUTE_SECONDS})

#: Sarfni kamaytirish bo'yicha amaliy maslahatlar (o'lchagich bo'yicha).
#:
#: Maslahatlar UMUMIY emas, mahsulotning haqiqiy imkoniyatlariga
#: ishora qiladi — aks holda ular bo'sh gap bo'lib qolardi.
QUOTA_TIPS: Final[dict[str, list[str]]] = {
    QUOTA_MONTHLY_JOBS: [
        "`Idempotency-Key` ishlating — tarmoq qayta urinishi ikkinchi "
        "job yaratmaydi va kvotani yemaydi.",
        "Takrorlanuvchi ishni cron jadvaliga o'tkazing: bitta jadval "
        "kerakli chastotada ishlaydi, qo'lda yuborilgan takroriy "
        "job'lar esa kvotani ikkilantiradi.",
        "`max_retries` ni kamaytiring — har urinish alohida bajarish, "
        "lekin job soniga faqat BITTA job hisoblanadi, shuning uchun "
        "bu hisoblash soniyalarini tejaydi.",
    ],
    QUOTA_COMPUTE_SECONDS: [
        "`timeout_seconds` ni real ehtiyojga qisqartiring — qotib "
        "qolgan job limitgacha hisoblash yeydi.",
        "4xx qaytaradigan HTTP job'lar qayta urinilmaydi, lekin 5xx "
        "uchun `max_retries` ni kamaytirish sarfni tejaydi.",
        "Og'ir ishni bo'lib yuboring: ikki qisqa job bitta uzun "
        "job'dan ko'proq nazorat beradi va qayta urinish arzonroq.",
    ],
}

#: Prognoz uchun eng kam kun: oyning 1-kunida "joriy tezlik" tushunchasi
#: ma'nosiz (bitta kunlik ma'lumot butun oyga ko'paytirilsa, xato
#: 30 barobar bo'lishi mumkin).
MIN_DAYS_FOR_PROJECTION: Final[int] = 1

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


def _compare_rows(source: PlanLimits, target: PlanLimits) -> list[dict[str, Any]]:
    """Ikki reja limitini solishtirish jadvali.

    `direction` mijoz nuqtai nazaridan: KATTA limit — `better`. Narx
    esa teskari — qimmatroq `worse`, chunki u mijozning xarajati.
    Shuning uchun har qator uchun yo'nalish ALOHIDA aniqlanadi,
    umumiy formula bilan emas.
    """

    def row(
        label: str, left: Any, right: Any, *, higher_is_better: bool, fmt: str = "{}"
    ) -> dict[str, Any]:
        if left == right:
            direction = "same"
        elif (right > left) is higher_is_better:
            direction = "better"
        else:
            direction = "worse"
        return {
            "label": label,
            "from": fmt.format(left),
            "to": fmt.format(right),
            "direction": direction,
        }

    return [
        row(
            "Narx ($/oy)",
            source.price_usd_month,
            target.price_usd_month,
            higher_is_better=False,
            fmt="${:,.0f}",
        ),
        row(
            "Oylik job", source.monthly_jobs, target.monthly_jobs, higher_is_better=True, fmt="{:,}"
        ),
        row(
            "Bir vaqtda",
            source.max_concurrent_jobs,
            target.max_concurrent_jobs,
            higher_is_better=True,
            fmt="{:,}",
        ),
        row(
            "Maks. timeout",
            source.max_timeout_seconds,
            target.max_timeout_seconds,
            higher_is_better=True,
            fmt="{}s",
        ),
        row(
            "Xotira", source.max_memory_mb, target.max_memory_mb, higher_is_better=True, fmt="{} MB"
        ),
        row("CPU", source.max_cpus, target.max_cpus, higher_is_better=True, fmt="{}"),
        row(
            "So'rov/daqiqa",
            source.requests_per_minute,
            target.requests_per_minute,
            higher_is_better=True,
            fmt="{:,}",
        ),
        row(
            "Log tarixi",
            source.log_retention_days,
            target.log_retention_days,
            higher_is_better=True,
            fmt="{} kun",
        ),
        row("Tarmoq", source.allow_network, target.allow_network, higher_is_better=True, fmt="{}"),
    ]


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
        #: Xarajat taqsimoti va kvota kesimi uchun — billing job
        #: FAKTLARIGA tayanadi (qancha ishlatilgan), job'larni
        #: BOSHQARMAYDI.
        self.jobs = JobRepository(session)
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

    async def statements(
        self,
        user: User,
        *,
        limit: int = DEFAULT_HISTORY_MONTHS,
    ) -> list[dict[str, Any]]:
        """Oylik hisob-kitoblar (`GET /billing/invoices`).

        ## Nega "hisob-faktura" emas, "hisob-kitob"

        Loyihada TO'LOV TIZIMI YO'Q: `stripe`/`paddle` integratsiyasi,
        `invoices` jadvali va PDF generatsiyasi mavjud emas
        (`subscriptions.external_customer_id` — kelgusi uchun qoldirilgan
        ilgak). Shuning uchun:

        * `amount_usd` — HAQIQIY: `usage_records` dagi haqiqiy
          foydalanishdan va reja narxidan hisoblanadi;
        * `status` — `None`: to'lov holati tushunchasi yo'q. "paid" deb
          qaytarish mijozga to'lov o'tgani haqida YOLG'ON xabar berardi;
        * `pdf_url` — `None`: hujjat generatsiyasi yo'q.

        `payments_enabled=False` maydoni buni ochiq aytadi, UI esa
        "to'lov ulanmagan" deb ko'rsatishi mumkin.

        ## Narx qaysi reja bo'yicha hisoblanadi

        `subscriptions` faqat JORIY rejani saqlaydi — o'tgan davrlarda
        qaysi reja amal qilganini bilish imkoni yo'q. Shuning uchun
        barcha davrlar joriy reja narxi bilan hisoblanadi va javobda
        `plan` maydoni ko'rsatiladi, `plan_history_tracked=False`
        esa cheklovni aytadi.

        Bu to'qib chiqarish EMAS: foydalanish ma'lumoti (job soni,
        bajarish soniyalari) haqiqiy, faqat narx joriy rejaga tayanadi.
        """
        records = await self.history(user, limit=limit)
        subscription = await self.subscriptions.ensure_for_user(user.id)
        limits = self._effective_limits(subscription)

        return [
            {
                # `id` alohida yozuv emas — davr kaliti identifikator
                # sifatida ishlatiladi (`2026-10`). UI uchun yetarli va
                # barqaror.
                "id": f"{limits.plan.value}-{item.period}",
                "period": item.period,
                "date": month_key_start(item.period),
                "plan": limits.plan,
                "job_count": item.job_count,
                "execution_seconds": item.execution_seconds,
                "amount_usd": round(limits.price_usd_month, 2),
                "overage_usd": OVERAGE_USD_PER_JOB,
                "status": None,
                "pdf_url": None,
                "payments_enabled": False,
                "plan_history_tracked": False,
            }
            for item in records
        ]

    async def projection(self, user: User) -> dict[str, Any]:
        """Oy oxirigacha xarajat va kvota prognozi.

        ## Prognoz qanday hisoblanadi

        Joriy tezlik = `job_count / o'tgan_kunlar`. Shu tezlik oy
        oxirigacha davom etadi deb olinadi.

        Oyning BIRINCHI kunida prognoz berilmaydi (`projected` = joriy
        qiymat): bir kunlik ma'lumotni 30 ga ko'paytirish xatoni
        30 barobar kattalashtiradi va mijozni behuda qo'rqitadi.

        ## `will_exceed` nimani bildiradi

        "Qo'shimcha pul to'laysiz" EMAS, "limitga yetib job'lar RAD
        ETILA boshlaydi" degani — Durabl kvotada bloklaydi
        (`OVERAGE_USD_PER_JOB` izohiga qarang). Shu sababli
        `overage_usd` har doim 0.
        """
        subscription = await self.subscriptions.ensure_for_user(user.id)
        limits = self._effective_limits(subscription)
        record = await self.usage_records.current_period(user.id)
        await self.session.commit()

        now = utcnow()
        period_end = next_month()
        days_total = (period_end - start_of_month()).days
        days_elapsed = max(MIN_DAYS_FOR_PROJECTION, (now - start_of_month()).days)
        days_remaining = max(0, (period_end - now).days)

        per_day = record.job_count / days_elapsed
        projected_jobs = (
            record.job_count
            if days_elapsed <= MIN_DAYS_FOR_PROJECTION
            else round(per_day * days_total)
        )

        base = round(limits.price_usd_month, 2)
        return {
            # Reja narxi oy boshida to'liq hisoblanadi — bo'lib to'lash
            # yo'q, shuning uchun "sarflangan" ham "prognoz" ham ayni
            # asosiy to'lovdan boshlanadi.
            "spent_usd": base,
            "projected_usd": base,
            "base_usd": base,
            "overage_usd": OVERAGE_USD_PER_JOB,
            "days_remaining": days_remaining,
            "days_total": days_total,
            "will_exceed": projected_jobs > limits.monthly_jobs,
            "projected_jobs": projected_jobs,
            "current_jobs": record.job_count,
            "monthly_limit": limits.monthly_jobs,
            "jobs_per_day": round(per_day, 2),
        }

    async def runtime_costs(self, user: User) -> list[dict[str, Any]]:
        """Joriy davrda runtime bo'yicha xarajat taqsimoti.

        ## Narx qanday taqsimlanadi

        Reja narxi OYLIK va yagona — runtime bo'yicha alohida tarif
        yo'q. Shuning uchun xarajat BAJARISH SONIYALARI nisbatida
        taqsimlanadi: "pulimning qancha qismi Node'ga ketdi" savoliga
        shu javob beradi.

        Bu o'ylab topilgan narx EMAS, balki mavjud to'lovning haqiqiy
        hisoblash sarfi bo'yicha taqsimi. Hech qanday soniya
        bajarilmagan bo'lsa (`total == 0`), taqsim ham nol bo'ladi —
        teng bo'lib berish noto'g'ri xulosa berardi.
        """
        subscription = await self.subscriptions.ensure_for_user(user.id)
        limits = self._effective_limits(subscription)
        rows = await self.jobs.runtime_totals(user_id=user.id, start=start_of_month(), end=utcnow())

        total_seconds = sum(seconds for _, _, seconds in rows)
        base = limits.price_usd_month

        result: list[dict[str, Any]] = []
        for runtime, jobs, seconds in sorted(rows, key=lambda row: -row[2]):
            share = (seconds / total_seconds) if total_seconds > 0 else 0.0
            result.append(
                {
                    "runtime": runtime,
                    "jobs": jobs,
                    "compute_seconds": round(seconds, 2),
                    "cost_usd": round(base * share, 2),
                    "percent": round(share * 100, 1),
                }
            )
        return result

    async def quota_breakdown(self, user: User, key: str) -> dict[str, Any]:
        """Bitta kvota o'lchagichi ortidagi tafsilot.

        O'lchagich faqat "82%" deydi. Foydalanuvchiga esa uchta narsa
        kerak: NIMA hisoblanadi, KIM sarflayapti va limitga yetganda
        NIMA bo'ladi.

        ## Qo'llanadigan kalitlar

        Faqat HAQIQIY o'lchanadigan o'lchagichlar:

        * `monthly_jobs` — oylik job soni (`usage_records.job_count`);
        * `compute_seconds` — bajarish soniyalari.

        `max_concurrent_jobs` va `requests_per_minute` ATAYLAB YO'Q:
        ular Redis'da LAHZALIK qiymat sifatida yashaydi va tarixi
        saqlanmaydi, ya'ni "kunlar bo'yicha" grafik yasab bo'lmaydi.
        Noma'lum kalit uchun `ValidationError` — jim bo'sh javob
        qaytarish mijozni chalg'itardi.

        ## `at_limit` nima deydi

        Durabl kvotada job'ni RAD ETADI (`check_quota`), qo'shimcha
        hisob yozmaydi. Shuning uchun `overage_label` har doim `None` —
        shartnoma ham shuni "oshirib bo'lmaydi" deb ta'riflaydi.

        Raises:
            ValidationError: Noma'lum o'lchagich kaliti.
        """
        if key not in QUOTA_KEYS:
            raise ValidationError(
                f"'{key}' kvota o'lchagichi mavjud emas",
                details={"allowed": sorted(QUOTA_KEYS)},
            )

        subscription = await self.subscriptions.ensure_for_user(user.id)
        limits = self._effective_limits(subscription)
        record = await self.usage_records.current_period(user.id)
        await self.session.commit()

        runtime_rows = await self.jobs.runtime_totals(
            user_id=user.id, start=start_of_month(), end=utcnow()
        )

        if key == QUOTA_MONTHLY_JOBS:
            current: float = float(record.job_count)
            limit = float(limits.monthly_jobs)
            label = "Oylik job soni"
            counted = "Qabul qilingan har bir job (bekor qilingani ham)"
            at_limit = "Yangi job'lar 402 bilan rad etiladi, davr yangilanguncha"
            current_label = f"{record.job_count:,}"
            limit_label = f"{limits.monthly_jobs:,}"
            slices = [
                {
                    "label": runtime,
                    "value": jobs,
                    "value_label": f"{jobs:,}",
                    "percent": round(jobs / record.job_count * 100, 1) if record.job_count else 0.0,
                }
                for runtime, jobs, _ in sorted(runtime_rows, key=lambda row: -row[1])
            ]
        else:
            current = round(record.execution_seconds, 2)
            # Hisoblash soniyalariga REJA limiti yo'q — chegara job soni
            # bo'yicha. Shuning uchun "limit" sifatida joriy rejadagi
            # maksimal nazariy qiymat olinadi: har job o'z timeout'iga
            # to'liq ishlagan holat.
            limit = float(limits.monthly_jobs * limits.max_timeout_seconds)
            label = "Hisoblash soniyalari"
            counted = "Har bir urinishning sof bajarish vaqti"
            at_limit = "Alohida limit yo'q — chegara job soni bo'yicha qo'yiladi"
            current_label = f"{current:,.0f}s"
            limit_label = f"{limit:,.0f}s (nazariy)"
            slices = [
                {
                    "label": runtime,
                    "value": round(seconds, 2),
                    "value_label": f"{seconds:,.0f}s",
                    "percent": round(seconds / record.execution_seconds * 100, 1)
                    if record.execution_seconds
                    else 0.0,
                }
                for runtime, _, seconds in sorted(runtime_rows, key=lambda row: -row[2])
            ]

        percent = round(current / limit * 100, 1) if limit > 0 else 0.0
        return {
            "key": key,
            "label": label,
            "current": current,
            "limit": limit,
            "percent": min(percent, 100.0),
            "current_label": current_label,
            "limit_label": limit_label,
            "resets_at": next_month(),
            "counted": counted,
            "at_limit": at_limit,
            # Durabl kvotada BLOKLAYDI — qo'shimcha narx yo'q.
            "overage_label": None,
            "by_runtime": slices,
            # Kalit bo'yicha taqsim `api_key_usage` jadvalini talab
            # qiladi (1A-12) — u hali yozilmagan, shuning uchun bo'sh.
            "by_api_key": [],
            "by_api_key_tracked": False,
            # Kunlik grafik `usage_records` da YO'Q: yozuv OYLIK
            # agregat (`period` ustuni `YYYY-MM`). Kunlik kesim uchun
            # `jobs.created_at` bo'yicha alohida so'rov kerak —
            # `GET /analytics/throughput` aynan shuni beradi.
            "daily": [],
            "daily_tracked": False,
            "tips": QUOTA_TIPS[key],
        }

    async def estimate(
        self,
        *,
        monthly_jobs: int,
        avg_duration_ms: int,
        current_plan: PlanType | str | None = None,
    ) -> dict[str, Any]:
        """ "Nima bo'lardi" kalkulyatori: hajm -> har reja uchun narx.

        Hech narsani o'qimaydi va yozmaydi — faqat katalog
        (`PLAN_LIMITS`) ustidagi hisob. Shuning uchun anonim ham
        chaqirilishi mumkin.

        ## `fits` va `over_by`

        Durabl kvotada bloklaydi, ya'ni rejaga SIG'MAGAN hajm uchun
        "qo'shimcha to'lov" yo'q — ish shunchaki bajarilmaydi. Shuning
        uchun `fits=False` bo'lgan reja `total_usd` bersa ham mijozga
        YARAMAYDI, va `recommended` faqat sig'adiganlar orasidan
        tanlanadi.
        """
        jobs = max(0, monthly_jobs)
        duration = max(0, avg_duration_ms)
        compute_seconds = round(jobs * duration / 1000.0, 2)
        current = self._coerce_plan(current_plan) if current_plan is not None else None

        plans: list[dict[str, Any]] = []
        for plan_type, limits in PLAN_LIMITS.items():
            fits = jobs <= limits.monthly_jobs
            over_by = (
                round(jobs / limits.monthly_jobs, 2)
                if not fits and limits.monthly_jobs > 0
                else 0.0
            )
            plans.append(
                {
                    "plan": plan_type,
                    "base_usd": round(limits.price_usd_month, 2),
                    "overage_usd": OVERAGE_USD_PER_JOB,
                    "total_usd": round(limits.price_usd_month, 2),
                    "fits": fits,
                    "over_by": over_by,
                }
            )

        affordable = [item for item in plans if item["fits"]]
        recommended = (
            min(affordable, key=lambda item: float(item["total_usd"]))["plan"]
            if affordable
            else PlanType.ENTERPRISE
        )
        savings = 0.0
        if current is not None:
            current_total = next(
                float(item["total_usd"]) for item in plans if item["plan"] is current
            )
            recommended_total = next(
                float(item["total_usd"]) for item in plans if item["plan"] is recommended
            )
            savings = round(current_total - recommended_total, 2)

        return {
            "monthly_jobs": jobs,
            "avg_duration_ms": duration,
            "compute_seconds": compute_seconds,
            "plans": plans,
            "recommended": recommended,
            "savings_usd": savings,
        }

    async def plan_change_preview(self, user: User, target: PlanType | str) -> dict[str, Any]:
        """Reja almashtirish oqibatini OLDINDAN ko'rsatadi.

        ## Nega to'siqlar (`blockers`) muhim

        Pastga tushishda joriy sarf yangi rejaning limitidan oshgan
        bo'lishi mumkin. Bunda almashtirish DARHOL kvota xatosiga olib
        keladi: mijozning job'lari 402 bilan rad etila boshlaydi.

        Buni almashtirishdan OLDIN aytish kerak — aks holda mijoz
        "nega hamma narsa buzildi?" degan savolda qoladi va sabab
        ko'rinmaydi.

        ## `prorated_usd` NEGA 0

        To'lov tizimi yo'q, ya'ni davr o'rtasida qayta hisoblash
        (proration) ham yo'q — reja darhol almashadi va pul
        undirilmaydi. Nol qaytarish YOLG'ON emas: haqiqatan hech qanday
        to'lov amalga oshmaydi. `payments_enabled=False` buni ochiq
        aytadi.
        """
        subscription = await self.subscriptions.ensure_for_user(user.id)
        await self.session.commit()
        source_limits = self._effective_limits(subscription)
        target_plan = self._coerce_plan(target)
        target_limits = plan_limits(target_plan)

        record = await self.usage_records.current_period(user.id)

        price_delta = round(target_limits.price_usd_month - source_limits.price_usd_month, 2)
        if price_delta > 0:
            direction = "upgrade"
        elif price_delta < 0:
            direction = "downgrade"
        else:
            direction = "same"

        blockers: list[str] = []
        if record.job_count > target_limits.monthly_jobs:
            blockers.append(
                f"Joriy davrda {record.job_count:,} job yuborilgan — "
                f"{target_plan.value} rejasining chegarasi {target_limits.monthly_jobs:,}. "
                "Almashtirilsa yangi job'lar davr oxirigacha rad etiladi."
            )

        return {
            "from": source_limits.plan,
            "to": target_plan,
            "direction": direction,
            "price_delta_usd": price_delta,
            "prorated_usd": 0.0,
            "effective_at": utcnow(),
            "rows": _compare_rows(source_limits, target_limits),
            "blockers": blockers,
            "payments_enabled": False,
        }

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
