"""Durabl — o'lik xatlar navbati (DLQ) schema'lari.

DLQ — Durabl'ning asosiy farqlovchi funksiyasi: barcha qayta urinishlar
tugagach ham muvaffaqiyatsiz bo'lgan job "jimgina o'lmaydi", balki shu
navbatga tushadi. Mijoz sababini ko'radi, tuzatadi va qayta uradi.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, computed_field, model_validator

from app.config import settings
from app.constants import FailureReason, JobStatus, Priority
from app.schemas.base import DurablSchema, ORMSchema
from app.schemas.job import JobSummary

#: `DlqFilter` da ruxsat etilgan tartiblash ustunlari.
DLQ_SORT_FIELDS: frozenset[str] = frozenset({"failed_at", "created_at", "retry_count"})


# ---------------------------------------------------------------------------
# So'rovlar
# ---------------------------------------------------------------------------


class DlqRetryRequest(DurablSchema):
    """`POST /dlq/{id}/retry` — DLQ yozuvidan job'ni qayta urinish.

    ## Nega `resolve` VA `mark_resolved` ikkisi ham bor

    Backend shartnomasida maydon `resolve` deb nomlangan, frontend turi
    (`frontend/src/types/dlq.ts:DlqRetryRequest`) esa `mark_resolved` deb
    e'lon qilgan va dashboard aynan shuni YUBORADI
    (`frontend/src/app/(dashboard)/dlq/page.tsx`). `DurablSchema` da
    `extra="forbid"` bo'lgani uchun noma'lum nom 422 berardi, ya'ni DLQ
    sahifasidagi "qayta urinish" tugmasi ishlamay qolardi. Shuning uchun
    `mark_resolved` QABUL QILINADI va `resolve` ga normallashtiriladi
    (ikkisi ham berilsa qiymatlari bir xil bo'lishi shart).
    """

    priority: Priority | None = Field(
        default=None,
        description="Qayta urinishda yangi ustuvorlik. Berilmasa job'ning o'zidagi saqlanadi.",
    )
    reset_retry_count: bool = Field(
        default=True,
        description="`retry_count` nolga qaytarilsinmi (job yana to'liq urinish huquqi oladi)",
    )
    max_retries: Annotated[int, Field(ge=0, le=settings.MAX_ALLOWED_RETRIES)] | None = Field(
        default=None,
        description="Qayta urinishlar sonini o'zgartirish (berilmasa eski qiymat qoladi)",
    )
    timeout_seconds: (
        Annotated[
            int,
            Field(ge=settings.MIN_TIMEOUT_SECONDS, le=settings.MAX_TIMEOUT_SECONDS),
        ]
        | None
    ) = Field(
        default=None,
        description="Qayta urinishda yangi vaqt limiti (berilmasa job'ning asl qiymati qoladi)",
    )
    notes: Annotated[str, Field(max_length=2_000)] | None = Field(
        default=None,
        description="Nima tuzatilgani haqida izoh — DLQ yozuviga saqlanadi",
    )
    resolve: bool = Field(
        default=True,
        description="Qayta urinishdan so'ng yozuv `resolved` deb belgilansinmi",
    )
    mark_resolved: bool | None = Field(
        default=None,
        description=(
            "`resolve` ning frontend'dagi nomi. Berilsa `resolve` o'rniga "
            "ishlatiladi; ikkisi birga berilsa qiymatlari mos bo'lishi shart."
        ),
    )

    @model_validator(mode="after")
    def _normalize_resolve(self) -> DlqRetryRequest:
        """`mark_resolved` ni `resolve` ga ko'chiradi va ziddiyatni rad etadi."""
        if self.mark_resolved is None:
            # Javob va servis FAQAT `resolve` ni o'qiydi, lekin maydon
            # frontend uchun ko'rinib turishi kerak — shuning uchun teskari
            # yo'nalishda ham to'ldiramiz.
            object.__setattr__(self, "mark_resolved", self.resolve)
        elif "resolve" in self.model_fields_set and self.mark_resolved != self.resolve:
            raise ValueError("`resolve` va `mark_resolved` bir-biriga zid qiymat bera olmaydi")
        else:
            object.__setattr__(self, "resolve", self.mark_resolved)
        return self


class DlqFilter(DurablSchema):
    """`GET /dlq` query parametrlari."""

    resolved: bool | None = Field(
        default=None,
        description="`true` — hal qilinganlar, `false` — hal qilinmaganlar, `null` — hammasi",
    )
    failure_reason: FailureReason | None = Field(
        default=None, description="Muvaffaqiyatsizlik sababi bo'yicha filtr"
    )
    job_id: uuid.UUID | None = Field(default=None, description="Muayyan job'ning yozuvi")
    search: Annotated[str, Field(min_length=1, max_length=255)] | None = Field(
        default=None,
        description=(
            "Matn qidiruvi: xato matni (`last_error`) yoki operator izohi "
            "(`notes`) bo'yicha registrga sezgir bo'lmagan qism-satr."
        ),
    )
    start: datetime | None = Field(
        default=None, description="`failed_at` oraliq boshlanishi (ISO-8601, UTC)"
    )
    end: datetime | None = Field(
        default=None, description="`failed_at` oraliq tugashi (ISO-8601, UTC)"
    )
    sort_by: str = Field(default="failed_at", description="Tartiblash ustuni")
    sort_order: Literal["asc", "desc"] = Field(default="desc", description="Tartiblash yo'nalishi")

    @model_validator(mode="after")
    def _check_filter(self) -> DlqFilter:
        """Oraliq mantiqan to'g'ri va tartiblash ustuni ruxsat etilganmi."""
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("`start` qiymati `end`dan keyin bo'lishi mumkin emas")
        if self.sort_by not in DLQ_SORT_FIELDS:
            raise ValueError(
                "`sort_by` noto'g'ri; ruxsat etilgan: " + ", ".join(sorted(DLQ_SORT_FIELDS))
            )
        return self


# ---------------------------------------------------------------------------
# Javoblar
# ---------------------------------------------------------------------------


class DlqEntryRead(ORMSchema):
    """DLQ'dagi bitta yozuv."""

    id: uuid.UUID = Field(description="DLQ yozuvi identifikatori")
    job_id: uuid.UUID = Field(description="Muvaffaqiyatsiz bo'lgan job identifikatori")
    user_id: uuid.UUID = Field(description="Egasi — foydalanuvchi identifikatori")
    failure_reason: FailureReason = Field(description="Tasniflangan muvaffaqiyatsizlik sababi")
    last_error: str | None = Field(default=None, description="Oxirgi xato matni")
    failed_at: datetime = Field(description="DLQ'ga tushgan vaqt (UTC)")
    retry_count: Annotated[int, Field(ge=0)] = Field(
        default=0, description="DLQ'ga tushishdan oldin bajarilgan avtomatik urinishlar soni"
    )
    manual_retry_count: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Mijoz qo'lda qancha marta qayta urgani"
    )
    resolved: bool = Field(default=False, description="Yozuv hal qilinganmi")
    resolved_at: datetime | None = Field(default=None, description="Hal qilingan vaqt (UTC)")
    resolved_by_id: uuid.UUID | None = Field(
        default=None, description="Hal qilgan foydalanuvchi identifikatori"
    )
    notes: str | None = Field(default=None, description="Qo'lda qo'shilgan izohlar")
    created_at: datetime = Field(description="Yozuv yaratilgan vaqt (UTC)")
    updated_at: datetime | None = Field(default=None, description="Oxirgi o'zgartirish vaqti (UTC)")
    job: JobSummary | None = Field(
        default=None,
        description="Tegishli job'ning qisqa ko'rinishi (so'ralganda to'ldiriladi)",
    )

    @computed_field(description="Qayta urinish mumkinmi (hal qilinmagan yozuvlar uchun)")  # type: ignore[prop-decorator]
    @property
    def is_retryable(self) -> bool:
        """Hal qilinmagan va sababi qayta urinishni man qilmaydigan yozuv."""
        return not self.resolved and self.failure_reason is not FailureReason.VALIDATION_ERROR


class DlqRetryResponse(ORMSchema):
    """`POST /dlq/{id}/retry` javobi."""

    entry_id: uuid.UUID = Field(description="DLQ yozuvi identifikatori")
    job_id: uuid.UUID = Field(description="Qayta navbatga qo'yilgan job identifikatori")
    status: JobStatus = Field(description="Job'ning yangi holati")
    requeued: bool = Field(description="Job navbatga qo'yildimi")
    resolved: bool = Field(default=False, description="DLQ yozuvi hal qilingan deb belgilandimi")
    retried_at: datetime | None = Field(default=None, description="Qayta urinish vaqti (UTC)")
    message: str = Field(default="Job qayta navbatga qo'yildi", description="Inson o'qiydigan izoh")


class DlqStats(ORMSchema):
    """`GET /dlq/stats` — DLQ bo'yicha umumlashtirilgan ko'rsatkichlar.

    Shakl `frontend/src/types/dlq.ts` dagi `DlqStats` bilan AYNI
    (`CONTRACTS.md`, "QO'SHIMCHA 3"): `depth`, `total`, `resolved`,
    `unresolved`, `by_reason`, `added_last_24h`, `oldest_failed_at`.
    """

    total: Annotated[int, Field(ge=0)] = Field(default=0, description="Jami DLQ yozuvlari")
    unresolved: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Hal qilinmagan yozuvlar soni (haqiqiy DLQ chuqurligi)"
    )
    resolved: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Hal qilingan yozuvlar soni"
    )
    by_reason: dict[str, int] = Field(
        default_factory=dict,
        description="Sabab -> yozuvlar soni (`FailureReason` qiymatlari kalit sifatida)",
    )
    added_last_24h: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Oxirgi 24 soatda DLQ'ga tushgan yozuvlar soni"
    )
    oldest_failed_at: datetime | None = Field(
        default=None, description="Eng qadimgi hal qilinmagan yozuvning vaqti (UTC)"
    )
    alert_threshold: Annotated[int, Field(ge=0)] = Field(
        default=settings.DLQ_ALERT_THRESHOLD,
        description="Shu chuqurlikdan oshsa ogohlantirish yuboriladi",
    )

    @computed_field(description="DLQ chuqurligi — hal qilinmagan yozuvlar soni")  # type: ignore[prop-decorator]
    @property
    def depth(self) -> int:
        """`unresolved` bilan AYNI qiymat — alert uchun asosiy ko'rsatkich.

        `computed_field` sifatida berilgani ataylab: ikki maydon bir-biriga
        qarama-qarshi qiymat ko'rsatishi mumkin bo'lmasligi kerak.
        """
        return self.unresolved

    @computed_field(description="DLQ chuqurligi ogohlantirish chegarasidan oshdimi")  # type: ignore[prop-decorator]
    @property
    def over_threshold(self) -> bool:
        """`unresolved > alert_threshold` bo'lsa `True`."""
        return self.unresolved > self.alert_threshold


__all__ = [
    "DLQ_SORT_FIELDS",
    "DlqEntryRead",
    "DlqFilter",
    "DlqRetryRequest",
    "DlqRetryResponse",
    "DlqStats",
]
