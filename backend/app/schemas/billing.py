"""Durabl — obuna, reja va foydalanish (billing) schema'lari.

**Shakl manbai — frontend.** `frontend/src/types/billing.ts` TO'LIQ yozilgan
va tasdiqlangan, shuning uchun maydon nomlari va turlari AYNAN shundan
olingan (`CONTRACTS.md`, "QO'SHIMCHA 3"):

* `PlanLimits`   -> `PlanLimits`   (`app.constants.PlanLimits.as_dict()` ga AYNAN mos)
* `PlanInfo`     -> `PlanInfo`     (narx jadvali uchun: nom, tavsif, imkoniyatlar)
* `PlansResponse`-> `PlansResponse` (`items` + `current_plan`)
* `Subscription` -> `SubscriptionRead`
* `UsageSummary` -> `UsageSummary`
* `UsageHistoryItem` -> `UsageHistoryItem`

**Limitlar DB'da saqlanmaydi** — yagona manba `app.constants.PLAN_LIMITS`.
Shuning uchun narx yoki chegara o'zgarsa migratsiya kerak bo'lmaydi:

    PlanLimits.for_plan(PlanType.PRO)              # katalogdan
    PlanLimits.from_limits(plan_limits("pro"))     # mavjud obyektdan

Reja NOMI, TAVSIFI va IMKONIYATLAR ro'yxati — marketing matni, u
`billing_service.PLAN_PRESENTATION` da (schema faqat shaklni belgilaydi).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, computed_field

from app.constants import PlanLimits as PlanLimitsSpec
from app.constants import PlanType, Runtime, plan_limits
from app.schemas.base import DurablSchema, ORMSchema

#: Kalkulyator kirishining yuqori chegarasi.
#:
#: Chegara mavjud bo'lishi SHART: `monthly_jobs` cheksiz bo'lsa,
#: `compute_seconds` ko'paytmasi float toshib ketadi va javob ma'nosiz
#: bo'ladi. 100 mln — ENTERPRISE chegarasidan (10 mln) o'n barobar
#: katta, ya'ni real so'rovni cheklamaydi.
MAX_ESTIMATE_JOBS = 100_000_000

#: Bitta job'ning maksimal davomiyligi (ms) — `MAX_TIMEOUT_SECONDS`
#: dan kelib chiqadi (900s = 900 000ms), zapas bilan.
MAX_ESTIMATE_DURATION_MS = 3_600_000


class PlanLimits(ORMSchema):
    """Bitta reja uchun cheklovlar to'plami.

    Maydonlar `app.constants.PlanLimits.__slots__` bilan AYNI nomlangan,
    shuning uchun `as_dict()` natijasi to'g'ridan-to'g'ri validatsiyadan
    o'tadi.
    """

    plan: PlanType = Field(description="Reja identifikatori")
    monthly_jobs: Annotated[int, Field(ge=0)] = Field(
        description="Oyiga ruxsat etilgan job'lar soni"
    )
    requests_per_minute: Annotated[int, Field(ge=0)] = Field(
        description="Daqiqadagi API so'rovlari limiti"
    )
    max_concurrent_jobs: Annotated[int, Field(ge=0)] = Field(
        description="Bir vaqtda bajarilishi mumkin bo'lgan job'lar soni"
    )
    max_timeout_seconds: Annotated[int, Field(ge=1)] = Field(
        description="Bitta job uchun maksimal vaqt limiti (soniya)"
    )
    max_memory_mb: Annotated[int, Field(ge=1)] = Field(
        description="Sandbox uchun maksimal xotira (MB)"
    )
    max_cpus: Annotated[float, Field(gt=0)] = Field(
        description="Sandbox uchun maksimal CPU (yadro ulushi)"
    )
    log_retention_days: Annotated[int, Field(ge=0)] = Field(
        description="Loglar qancha kun saqlanadi"
    )
    allow_network: bool = Field(description="Sandbox ichidan tarmoqqa chiqishga ruxsatmi")
    price_usd_month: Annotated[float, Field(ge=0)] = Field(
        description="Oylik narx (AQSh dollarida)"
    )

    @classmethod
    def from_limits(cls, limits: PlanLimitsSpec) -> PlanLimits:
        """`app.constants.PlanLimits` obyektidan schema yasaydi."""
        return cls.model_validate(limits.as_dict())

    @classmethod
    def for_plan(cls, plan: PlanType | str) -> PlanLimits:
        """Reja nomidan katalogdagi limitlarni oladi."""
        return cls.from_limits(plan_limits(plan))


class PlanInfo(ORMSchema):
    """Narx jadvalida ko'rsatiladigan bitta reja."""

    plan: PlanType = Field(description="Reja identifikatori")
    name: str = Field(description="Reja nomi (ko'rinadigan matn)", examples=["Professional"])
    description: str = Field(description="Reja haqida qisqa tavsif (1-2 jumla)")
    price_usd_month: Annotated[float, Field(ge=0)] = Field(
        description="Oylik narx (AQSh dollarida)"
    )
    limits: PlanLimits = Field(description="Reja cheklovlari")
    features: list[str] = Field(
        default_factory=list, description="Marketing uchun asosiy imkoniyatlar ro'yxati"
    )
    is_popular: bool = Field(default=False, description="Narx jadvalida ajratib ko'rsatilsinmi")
    is_current: bool = Field(default=False, description="Foydalanuvchining joriy rejasimi")

    @classmethod
    def build(
        cls,
        limits: PlanLimitsSpec,
        *,
        name: str,
        description: str,
        features: list[str],
        is_popular: bool = False,
        is_current: bool = False,
    ) -> PlanInfo:
        """Katalog limitlari va marketing matnidan to'liq `PlanInfo` yasaydi."""
        return cls(
            plan=PlanType(limits.plan),
            name=name,
            description=description,
            price_usd_month=float(limits.price_usd_month),
            limits=PlanLimits.from_limits(limits),
            features=list(features),
            is_popular=is_popular,
            is_current=is_current,
        )


class PlansResponse(ORMSchema):
    """`GET /billing/plans` — barcha rejalar katalogi."""

    items: list[PlanInfo] = Field(
        default_factory=list, description="Mavjud rejalar (arzondan qimmatga)"
    )
    current_plan: PlanType = Field(
        default=PlanType.FREE,
        description="Foydalanuvchining joriy rejasi (autentifikatsiya bo'lmasa `free`)",
    )


class PlanChangeRequest(DurablSchema):
    """`POST /billing/subscription` — rejani almashtirish."""

    plan: PlanType = Field(description="Yangi reja identifikatori")


class SubscriptionRead(ORMSchema):
    """Foydalanuvchining obunasi."""

    id: uuid.UUID = Field(description="Obuna identifikatori")
    user_id: uuid.UUID = Field(description="Egasi — foydalanuvchi identifikatori")
    plan: PlanType = Field(description="Joriy reja")
    started_at: datetime = Field(description="Obuna boshlangan vaqt (UTC)")
    expires_at: datetime | None = Field(
        default=None, description="Obuna tugash vaqti (UTC); `null` — cheksiz"
    )
    is_active: bool = Field(default=True, description="Obuna faolmi")
    cancelled_at: datetime | None = Field(default=None, description="Bekor qilingan vaqt (UTC)")
    external_customer_id: str | None = Field(
        default=None, description="To'lov tizimidagi mijoz identifikatori"
    )
    created_at: datetime = Field(description="Yozuv yaratilgan vaqt (UTC)")
    updated_at: datetime | None = Field(default=None, description="Oxirgi o'zgartirish vaqti (UTC)")
    limits: PlanLimits | None = Field(
        default=None,
        description="Reja cheklovlari — modeldagi `limits` xossasidan avtomatik to'ladi",
    )


class UsageHistoryItem(ORMSchema):
    """Bir oylik foydalanish yozuvi (tarix uchun)."""

    period: str = Field(description="Davr (`YYYY-MM`)", examples=["2026-09"])
    job_count: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Davr ichida yuborilgan job'lar"
    )
    success_count: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Muvaffaqiyatli tugaganlar"
    )
    failed_count: Annotated[int, Field(ge=0)] = Field(default=0, description="Muvaffaqiyatsizlar")
    execution_seconds: Annotated[float, Field(ge=0)] = Field(
        default=0.0, description="Jami bajarish vaqti (soniya)"
    )
    recorded_at: datetime | None = Field(
        default=None, description="Oxirgi hisobga olish vaqti (UTC)"
    )

    @computed_field(description="Davr bo'yicha muvaffaqiyat foizi (0–100)")  # type: ignore[prop-decorator]
    @property
    def success_rate(self) -> float:
        """`success_count / (success_count + failed_count) * 100`."""
        finished = self.success_count + self.failed_count
        if finished <= 0:
            return 0.0
        return round(self.success_count / finished * 100, 2)


class StatementRead(DurablSchema):
    """`GET /billing/invoices` — oylik hisob-kitob.

    ## Nega ba'zi maydonlar `null`

    Loyihada TO'LOV TIZIMI yo'q (`stripe`/`paddle` integratsiyasi,
    `invoices` jadvali, PDF generatsiyasi mavjud emas). Shuning uchun
    `status` va `pdf_url` `null` qaytadi — "paid" deb qaytarish mijozga
    to'lov o'tgani haqida YOLG'ON xabar berardi.

    Foydalanish ma'lumoti esa HAQIQIY: `job_count` va
    `execution_seconds` `usage_records` dan, `amount_usd` reja
    narxidan hisoblanadi.
    """

    id: str = Field(description="`{reja}-{davr}` ko'rinishidagi identifikator")
    period: str = Field(description="Davr kaliti (`2026-10`)")
    date: datetime = Field(description="Davr boshi (UTC)")
    plan: PlanType = Field(description="Narx hisoblangan reja")
    job_count: Annotated[int, Field(ge=0)] = Field(description="Davrdagi job soni")
    execution_seconds: Annotated[float, Field(ge=0)] = Field(
        description="Davrdagi bajarish soniyalari"
    )
    amount_usd: Annotated[float, Field(ge=0)] = Field(description="Reja asosiy to'lovi ($)")
    overage_usd: Annotated[float, Field(ge=0)] = Field(
        default=0.0,
        description=(
            "Limitdan oshish uchun qo'shimcha. Har doim 0: Durabl kvotada "
            "job'ni RAD ETADI, qo'shimcha hisob yozmaydi."
        ),
    )
    status: Literal["paid", "pending", "failed"] | None = Field(
        default=None, description="To'lov holati. `null` — to'lov tizimi ulanmagan."
    )
    pdf_url: str | None = Field(
        default=None, description="Hujjat havolasi. `null` — generatsiya yo'q."
    )
    payments_enabled: bool = Field(
        default=False, description="To'lov tizimi ulanganmi (`status`/`pdf_url` ma'nosi)"
    )
    plan_history_tracked: bool = Field(
        default=False,
        description=(
            "O'tgan davrlarda qaysi reja amal qilgani saqlanadimi. `false` — "
            "narx JORIY reja bo'yicha hisoblangan."
        ),
    )


class CostProjection(DurablSchema):
    """`GET /billing/projection` — oy oxirigacha prognoz.

    `will_exceed` "qo'shimcha pul to'laysiz" EMAS, "limitga yetib
    job'lar rad etila boshlaydi" degani — Durabl kvotada bloklaydi.
    """

    spent_usd: Annotated[float, Field(ge=0)] = Field(description="Davr boshidan sarflangan ($)")
    projected_usd: Annotated[float, Field(ge=0)] = Field(description="Oy oxiriga prognoz ($)")
    base_usd: Annotated[float, Field(ge=0)] = Field(description="Reja asosiy to'lovi ($)")
    overage_usd: Annotated[float, Field(ge=0)] = Field(
        default=0.0, description="Qo'shimcha to'lov — har doim 0 (kvotada bloklanadi)"
    )
    days_remaining: Annotated[int, Field(ge=0)] = Field(description="Davr tugashiga qolgan kun")
    days_total: Annotated[int, Field(ge=1)] = Field(description="Davrdagi jami kun")
    will_exceed: bool = Field(
        description="Joriy tezlikda oylik job limitidan oshadimi (job'lar rad etiladi)"
    )
    projected_jobs: Annotated[int, Field(ge=0)] = Field(description="Oy oxiriga prognoz job soni")
    current_jobs: Annotated[int, Field(ge=0)] = Field(description="Hozirgacha yuborilgan job")
    monthly_limit: Annotated[int, Field(ge=0)] = Field(description="Reja oylik chegarasi")
    jobs_per_day: Annotated[float, Field(ge=0)] = Field(description="Kunlik o'rtacha tezlik")


class RuntimeCost(DurablSchema):
    """Runtime bo'yicha xarajat ulushi.

    Reja narxi oylik va yagona — runtime bo'yicha alohida tarif yo'q.
    Shuning uchun xarajat BAJARISH SONIYALARI nisbatida taqsimlanadi.
    """

    runtime: Runtime = Field(description="Bajarish muhiti")
    jobs: Annotated[int, Field(ge=0)] = Field(description="Job soni")
    compute_seconds: Annotated[float, Field(ge=0)] = Field(description="Bajarish soniyalari")
    cost_usd: Annotated[float, Field(ge=0)] = Field(description="Taqsimlangan xarajat ($)")
    percent: Annotated[float, Field(ge=0, le=100)] = Field(description="Ulush (%)")


class QuotaSlice(DurablSchema):
    """Kvota ichidagi bitta ulush (runtime yoki kalit bo'yicha)."""

    label: str = Field(description="Ulush nomi")
    value: float = Field(description="Xom qiymat")
    value_label: str = Field(description="Ko'rsatish uchun formatlangan qiymat")
    percent: Annotated[float, Field(ge=0, le=100)] = Field(description="Ulush (%)")


class QuotaDailyPoint(DurablSchema):
    """Kvota grafigining bitta kunlik nuqtasi."""

    date: datetime = Field(description="Kun (UTC)")
    label: str = Field(description="Ko'rsatish uchun yorliq")
    value: float = Field(description="Qiymat")


class QuotaBreakdown(DurablSchema):
    """`GET /billing/usage/{key}` — bitta o'lchagich ortidagi tafsilot.

    O'lchagich faqat "82%" deydi. Foydalanuvchiga esa uchta narsa
    kerak: NIMA hisoblanadi, KIM sarflayapti va limitga yetganda NIMA
    bo'ladi.

    ## `daily` va `by_api_key` NEGA BO'SH

    * `daily` — `usage_records` OYLIK agregat (`period` ustuni
      `YYYY-MM`), kunlik kesim u yerda yo'q. Kunlik grafik uchun
      `GET /analytics/throughput` ishlatiladi.
    * `by_api_key` — `api_key_usage` jadvalini talab qiladi, u hali
      yozilmagan.

    Ikkisi ham to'qib chiqarilmaydi: `daily_tracked` va
    `by_api_key_tracked` ochiq `false` qaytaradi.
    """

    key: str = Field(description="O'lchagich kaliti")
    label: str = Field(description="O'lchagich nomi")
    current: float = Field(description="Joriy qiymat")
    limit: float = Field(description="Chegara")
    percent: Annotated[float, Field(ge=0, le=100)] = Field(description="Foiz")
    current_label: str = Field(description="Formatlangan joriy qiymat")
    limit_label: str = Field(description="Formatlangan chegara")
    resets_at: datetime = Field(description="Kvota qachon nollanadi (UTC)")
    counted: str = Field(description="Nima hisoblanadi — bir gapda")
    at_limit: str = Field(description="Limitga yetganda nima bo'ladi")
    overage_label: str | None = Field(
        default=None,
        description="Limitdan oshish narxi. Har doim `null` — oshirib bo'lmaydi.",
    )
    daily: list[QuotaDailyPoint] = Field(
        default_factory=list, description="Kunlik kesim (hozircha bo'sh)"
    )
    daily_tracked: bool = Field(default=False, description="Kunlik kesim saqlanadimi")
    by_runtime: list[QuotaSlice] = Field(
        default_factory=list, description="Runtime bo'yicha taqsim"
    )
    by_api_key: list[QuotaSlice] = Field(
        default_factory=list, description="Kalit bo'yicha taqsim (hozircha bo'sh)"
    )
    by_api_key_tracked: bool = Field(default=False, description="Kalit bo'yicha taqsim saqlanadimi")
    tips: list[str] = Field(default_factory=list, description="Sarfni kamaytirish maslahatlari")


class CostEstimateRequest(DurablSchema):
    """`POST /billing/estimate` so'rovi."""

    monthly_jobs: Annotated[int, Field(ge=0, le=MAX_ESTIMATE_JOBS)] = Field(
        description=f"Oylik job soni (maksimal {MAX_ESTIMATE_JOBS:,})",
        examples=[50_000],
    )
    avg_duration_ms: Annotated[int, Field(ge=0, le=MAX_ESTIMATE_DURATION_MS)] = Field(
        description="Bitta job'ning o'rtacha davomiyligi (ms)",
        examples=[1_500],
    )


class PlanCostEstimate(DurablSchema):
    """Bitta reja uchun hisoblangan narx."""

    plan: PlanType = Field(description="Reja")
    base_usd: Annotated[float, Field(ge=0)] = Field(description="Asosiy to'lov ($)")
    overage_usd: Annotated[float, Field(ge=0)] = Field(
        default=0.0, description="Qo'shimcha — har doim 0 (kvotada bloklanadi)"
    )
    total_usd: Annotated[float, Field(ge=0)] = Field(description="Jami ($)")
    fits: bool = Field(description="Kiritilgan hajm shu rejaga sig'adimi")
    over_by: Annotated[float, Field(ge=0)] = Field(
        default=0.0, description="Hajm limitdan necha barobar ko'p (sig'masa)"
    )


class CostEstimate(DurablSchema):
    """`POST /billing/estimate` javobi.

    `recommended` FAQAT sig'adigan rejalar orasidan tanlanadi: Durabl
    kvotada bloklaydi, ya'ni sig'maydigan reja arzon bo'lsa ham
    mijozga yaramaydi.
    """

    monthly_jobs: Annotated[int, Field(ge=0)] = Field(description="Kiritilgan job soni")
    avg_duration_ms: Annotated[int, Field(ge=0)] = Field(description="Kiritilgan davomiylik")
    compute_seconds: Annotated[float, Field(ge=0)] = Field(description="Hisoblangan soniyalar")
    plans: list[PlanCostEstimate] = Field(description="Har reja uchun narx")
    recommended: PlanType = Field(description="Eng arzon MOS reja")
    savings_usd: float = Field(
        default=0.0, description="Joriy reja bilan farq ($/oy); manfiy — qimmatroq"
    )


class PlanChangeRow(DurablSchema):
    """Reja almashtirish solishtiruvining bitta qatori."""

    label: str = Field(description="Ko'rsatkich nomi")
    from_: str = Field(alias="from", description="Joriy qiymat")
    to: str = Field(description="Yangi qiymat")
    direction: Literal["better", "worse", "same"] = Field(
        description="Mijoz nuqtai nazaridan yaxshi, yomon yoki bir xil"
    )


class PlanChangePreview(DurablSchema):
    """`GET /billing/plans/{plan}/preview` javobi.

    `blockers` eng muhim maydon: pastga tushishda joriy sarf yangi
    rejaning limitidan oshgan bo'lsa, almashtirish DARHOL kvota
    xatosiga olib keladi. Buni OLDINDAN aytish kerak.
    """

    from_: PlanType = Field(alias="from", description="Joriy reja")
    to: PlanType = Field(description="Yangi reja")
    direction: Literal["upgrade", "downgrade", "same"] = Field(description="Yo'nalish")
    price_delta_usd: float = Field(description="Narx farqi ($/oy)")
    prorated_usd: Annotated[float, Field(ge=0)] = Field(
        default=0.0,
        description="Davr o'rtasidagi qayta hisob. Har doim 0 — to'lov tizimi yo'q.",
    )
    effective_at: datetime = Field(description="Qachon kuchga kiradi (UTC)")
    rows: list[PlanChangeRow] = Field(default_factory=list, description="Solishtiruv jadvali")
    blockers: list[str] = Field(
        default_factory=list,
        description="Almashtirishga to'sqinlik qiladigan holatlar (bo'sh — to'siq yo'q)",
    )
    payments_enabled: bool = Field(default=False, description="To'lov tizimi ulanganmi")


class UsageSummary(ORMSchema):
    """`GET /billing/usage` — joriy davr iste'moli va limitlar."""

    period: str = Field(description="Joriy davr (`YYYY-MM`)", examples=["2026-10"])
    plan: PlanType = Field(default=PlanType.FREE, description="Joriy reja")
    job_count: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Davr ichida yuborilgan job'lar"
    )
    success_count: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Muvaffaqiyatli tugaganlar"
    )
    failed_count: Annotated[int, Field(ge=0)] = Field(default=0, description="Muvaffaqiyatsizlar")
    execution_seconds: Annotated[float, Field(ge=0)] = Field(
        default=0.0, description="Jami bajarish vaqti (soniya)"
    )
    monthly_limit: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Reja bo'yicha oylik job limiti"
    )
    concurrent_limit: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Bir vaqtdagi job'lar limiti"
    )
    period_start: datetime = Field(description="Davr boshlanishi (UTC)")
    period_end: datetime = Field(
        description="Davr tugashi — limit shu vaqtda yangilanadi (keyingi oy boshi, UTC)"
    )

    @computed_field(description="Limitdan qancha job qolgani")  # type: ignore[prop-decorator]
    @property
    def remaining(self) -> int:
        """`monthly_limit - job_count` (manfiy bo'lmaydi)."""
        return max(0, self.monthly_limit - self.job_count)

    @computed_field(description="Limitning qancha foizi ishlatilgani (0–100+)")  # type: ignore[prop-decorator]
    @property
    def usage_percent(self) -> float:
        """`job_count / monthly_limit * 100`."""
        if self.monthly_limit <= 0:
            return 0.0
        return round(self.job_count / self.monthly_limit * 100, 2)

    @computed_field(description="Oylik limit tugaganmi (yangi job qabul qilinmaydi)")  # type: ignore[prop-decorator]
    @property
    def is_over_limit(self) -> bool:
        """`job_count >= monthly_limit` bo'lsa `True`."""
        return self.monthly_limit > 0 and self.job_count >= self.monthly_limit


__all__ = [
    "MAX_ESTIMATE_DURATION_MS",
    "MAX_ESTIMATE_JOBS",
    "CostEstimate",
    "CostEstimateRequest",
    "CostProjection",
    "PlanChangePreview",
    "PlanChangeRequest",
    "PlanChangeRow",
    "PlanCostEstimate",
    "PlanInfo",
    "PlanLimits",
    "PlansResponse",
    "QuotaBreakdown",
    "QuotaDailyPoint",
    "QuotaSlice",
    "RuntimeCost",
    "StatementRead",
    "SubscriptionRead",
    "UsageHistoryItem",
    "UsageSummary",
]
