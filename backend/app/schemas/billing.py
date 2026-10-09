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
from typing import Annotated

from pydantic import Field, computed_field

from app.constants import PlanLimits as PlanLimitsSpec
from app.constants import PlanType, plan_limits
from app.schemas.base import DurablSchema, ORMSchema


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
    is_popular: bool = Field(
        default=False, description="Narx jadvalida ajratib ko'rsatilsinmi"
    )
    is_current: bool = Field(
        default=False, description="Foydalanuvchining joriy rejasimi"
    )

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
    "PlanChangeRequest",
    "PlanInfo",
    "PlanLimits",
    "PlansResponse",
    "SubscriptionRead",
    "UsageHistoryItem",
    "UsageSummary",
]
