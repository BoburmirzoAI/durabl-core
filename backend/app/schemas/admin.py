"""Durabl — admin panel schema'lari.

Bu modul `/api/v1/admin/*` endpointlari uchun: foydalanuvchi boshqaruvi,
tizim holati, worker'lar va navbat chuqurligi, audit jurnali.

**Shakl manbai — frontend.** `frontend/src/types/admin.ts` TO'LIQ yozilgan
va tasdiqlangan, shuning uchun maydon nomlari va turlari AYNAN shundan
olingan (`CONTRACTS.md`, "QO'SHIMCHA 3"):

* `AdminUser`   -> `AdminUserRead`
* `AdminStats`  -> `AdminStats`
* `SystemStatus`-> `SystemStatus`
* `QueueDepth`  -> `QueueDepth`   (bitta ustuvorlik = bitta qator!)
* `WorkerInfo`  -> `WorkerInfo`
* `AuditLog`    -> `AuditLogRead`

`WorkerInfo` Redis'dan keladigan lug'atlardan to'ldiriladi
(`ReliabilityService.list_workers()`), shuning uchun u `ORMSchema`
(`extra="ignore"`) — registrdagi qo'shimcha kalitlar xato bermaydi.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Annotated, Any, Final, Literal

from pydantic import Field, computed_field, model_validator

from app.constants import PRIORITY_ORDER, AuditAction, PlanType, Priority, WorkerState
from app.schemas.base import DurablSchema, ORMSchema

if TYPE_CHECKING:
    from collections.abc import Mapping

#: `AdminUserUpdate` da o'zgartirish mumkin bo'lgan maydonlar.
ADMIN_EDITABLE_USER_FIELDS: frozenset[str] = frozenset(
    {"full_name", "is_active", "is_admin", "plan"}
)

#: `SystemStatus.checks` lug'atining kalitlari — frontend aynan shularni kutadi
#: (`Record<string, boolean>`, lekin UI uchta nomni nomma-nom ko'rsatadi).
CHECK_DATABASE: Final = "database"
CHECK_REDIS: Final = "redis"
CHECK_SANDBOX: Final = "sandbox"

#: Tekshiruv kalitlarining barqaror tartibi (javobda ham shu tartibda chiqadi).
SYSTEM_CHECK_KEYS: Final[tuple[str, ...]] = (CHECK_DATABASE, CHECK_REDIS, CHECK_SANDBOX)


# ---------------------------------------------------------------------------
# Foydalanuvchi boshqaruvi
# ---------------------------------------------------------------------------


class AdminUserRead(ORMSchema):
    """Admin ko'radigan foydalanuvchi ma'lumoti (agregatlari bilan).

    Agregat maydonlar (`job_count`, `jobs_this_period`, `dlq_depth`,
    `api_key_count`) modelda YO'Q — ularni `AnalyticsService.admin_users()`
    GURUHLANGAN so'rovlar bilan hisoblab beradi (N+1 so'rov yo'q).
    """

    id: uuid.UUID = Field(description="Foydalanuvchi identifikatori")
    email: str = Field(description="Elektron pochta")
    full_name: str | None = Field(default=None, description="To'liq ism")
    is_active: bool = Field(description="Hisob faolmi")
    is_admin: bool = Field(description="Administrator huquqi bormi")
    plan: PlanType = Field(
        default=PlanType.FREE,
        description="Joriy obuna rejasi (obuna yozuvi bo'lmasa `free`)",
    )
    last_login_at: datetime | None = Field(default=None, description="Oxirgi kirish vaqti (UTC)")
    created_at: datetime = Field(description="Ro'yxatdan o'tgan vaqt (UTC)")
    updated_at: datetime | None = Field(default=None, description="Oxirgi o'zgartirish vaqti (UTC)")
    job_count: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Foydalanuvchi yuborgan jami job'lar soni"
    )
    jobs_this_period: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Joriy hisob davrida (oyda) yuborilgan job'lar soni"
    )
    dlq_depth: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Hal qilinmagan DLQ yozuvlari soni"
    )
    api_key_count: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Faol API kalitlar soni"
    )


class AdminUserUpdate(DurablSchema):
    """`PUT /admin/users/{id}` — qismiy yangilash."""

    full_name: Annotated[str, Field(max_length=255)] | None = Field(
        default=None, description="Yangi to'liq ism"
    )
    is_active: bool | None = Field(
        default=None, description="Hisobni bloklash (`false`) yoki tiklash (`true`)"
    )
    is_admin: bool | None = Field(
        default=None, description="Administrator huquqini berish yoki olib qo'yish"
    )
    plan: PlanType | None = Field(default=None, description="Obuna rejasini majburan o'zgartirish")
    reason: Annotated[str, Field(max_length=500)] | None = Field(
        default=None, description="Audit jurnaliga yoziladigan sabab"
    )

    @model_validator(mode="after")
    def _check_not_empty(self) -> AdminUserUpdate:
        """Kamida bitta o'zgartirish maydoni berilishi shart."""
        if not (self.model_fields_set & ADMIN_EDITABLE_USER_FIELDS):
            raise ValueError(
                "Kamida bitta maydon berilishi kerak: "
                + ", ".join(sorted(ADMIN_EDITABLE_USER_FIELDS))
            )
        return self


# ---------------------------------------------------------------------------
# Tizim holati
# ---------------------------------------------------------------------------


class QueueDepth(ORMSchema):
    """BITTA ustuvorlik navbatining holati.

    Frontend `SystemStatus.queues` ni ro'yxat sifatida kutadi, ya'ni har
    bir ustuvorlik uchun alohida qator (`{priority, depth, processing}`).

    `depth` — Redis LIST uzunligi (bajarishga tayyor, kutayotganlar),
    `processing` — shu ustuvorlikdagi `RUNNING` job'lar soni (worker olgan,
    lekin hali tugatmagan). Ikkinchisi DB'dan olinadi: Redis'ning
    `processing:<worker>` ro'yxatlari ustuvorlik bo'yicha ajratilmagan.
    """

    priority: Priority = Field(description="Navbat ustuvorligi")
    depth: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Navbatda kutayotgan job'lar soni"
    )
    processing: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Worker olgan, lekin hali tugatmagan job'lar soni"
    )

    @classmethod
    def rows(
        cls,
        depths: Mapping[str, int],
        processing: Mapping[str, int] | None = None,
    ) -> list[QueueDepth]:
        """`QueueService.depth()` natijasidan qatorlar ro'yxatini yasaydi.

        Tartib `PRIORITY_ORDER` bo'yicha (yuqori ustuvorlik birinchi) —
        UI ro'yxatni qayta tartiblashi shart emas.

        Args:
            depths: Ustuvorlik qiymati -> navbat uzunligi. `delayed`,
                `processing` va `total` kalitlari E'TIBORSIZ qoldiriladi
                (ular `SystemStatus` ning alohida maydonlari).
            processing: Ustuvorlik qiymati -> bajarilayotgan job'lar soni.
        """
        running = processing or {}
        return [
            cls(
                priority=priority,
                depth=int(depths.get(priority.value, 0) or 0),
                processing=int(running.get(priority.value, 0) or 0),
            )
            for priority in PRIORITY_ORDER
        ]


class WorkerInfo(ORMSchema):
    """Bitta worker haqidagi ma'lumot (Redis registridan)."""

    worker_id: str = Field(description="Worker identifikatori (`hostname-pid`)")
    state: WorkerState = Field(default=WorkerState.IDLE, description="Worker holati")
    hostname: str | None = Field(default=None, description="Worker ishlayotgan host nomi")
    pid: int | None = Field(default=None, description="Protsess identifikatori")
    current_job_id: uuid.UUID | None = Field(
        default=None, description="Hozir bajarilayotgan job identifikatori"
    )
    concurrency: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Worker parallel bajarishi mumkin bo'lgan job'lar soni"
    )
    jobs_processed: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Ishga tushgandan beri bajargan job'lar soni"
    )
    started_at: datetime | None = Field(default=None, description="Ishga tushgan vaqt (UTC)")
    last_heartbeat_at: datetime | None = Field(
        default=None, description="Oxirgi heartbeat vaqti (UTC)"
    )
    version: str | None = Field(default=None, description="Worker ishlatayotgan Durabl versiyasi")

    @computed_field(description="Worker tirikmi (holati `dead`/`stopped` emasmi)")  # type: ignore[prop-decorator]
    @property
    def is_alive(self) -> bool:
        """`WorkerState.DEAD` va `STOPPED` dan boshqa barcha holatlar tirik hisoblanadi."""
        return self.state not in (WorkerState.DEAD, WorkerState.STOPPED)


class SystemStatus(ORMSchema):
    """`GET /admin/system` — tizimning umumiy sog'lig'i."""

    status: Literal["ok", "degraded", "down"] = Field(description="Umumiy holat")
    version: str = Field(description="Ilova versiyasi")
    environment: str = Field(description="Muhit (`development`, `production`...)")
    checks: dict[str, bool] = Field(
        default_factory=dict,
        description="Pastki tizimlar sog'lig'i: `database`, `redis`, `sandbox`",
    )
    uptime_seconds: float | None = Field(
        default=None, description="Ilova ishga tushganidan beri o'tgan vaqt (soniya)"
    )
    workers: list[WorkerInfo] = Field(
        default_factory=list, description="Ro'yxatdan o'tgan worker'lar"
    )
    queues: list[QueueDepth] = Field(
        default_factory=list, description="Ustuvorlik bo'yicha navbatlar holati"
    )
    delayed_jobs: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Kechiktirilgan (scheduled/retry) job'lar soni"
    )
    dlq_depth: Annotated[int, Field(ge=0)] = Field(
        default=0, description="DLQ chuqurligi — hal qilinmagan yozuvlar soni"
    )
    webhook_queue_depth: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Yuborilishi kutilayotgan webhook'lar soni"
    )
    running_jobs: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Hozir bajarilayotgan job'lar soni"
    )
    checked_at: datetime | None = Field(default=None, description="Tekshiruv vaqti (UTC)")

    @computed_field(description="Tirik worker'lar soni")  # type: ignore[prop-decorator]
    @property
    def active_workers(self) -> int:
        """Holati `dead`/`stopped` bo'lmagan worker'lar soni."""
        return sum(1 for worker in self.workers if worker.is_alive)

    @computed_field(description="Sandbox (Docker/gVisor) ishlayaptimi")  # type: ignore[prop-decorator]
    @property
    def sandbox_available(self) -> bool:
        """`checks["sandbox"]` qiymati — yagona manbadan olinadi."""
        return bool(self.checks.get(CHECK_SANDBOX, False))


class AdminStats(ORMSchema):
    """`GET /admin/stats` — platforma bo'yicha umumiy ko'rsatkichlar."""

    total_users: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Ro'yxatdan o'tgan foydalanuvchilar soni"
    )
    active_users: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Faol (bloklanmagan) foydalanuvchilar soni"
    )
    new_users_7d: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Oxirgi 7 kunda ro'yxatdan o'tganlar soni"
    )
    admin_users: Annotated[int, Field(ge=0)] = Field(default=0, description="Administratorlar soni")
    total_jobs: Annotated[int, Field(ge=0)] = Field(default=0, description="Jami job'lar soni")
    jobs_24h: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Oxirgi 24 soatda yuborilgan job'lar soni"
    )
    jobs_today: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Bugun (UTC yarim kechadan) yuborilgan job'lar soni"
    )
    running_jobs: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Hozir bajarilayotgan job'lar soni"
    )
    jobs_by_status: dict[str, int] = Field(
        default_factory=dict, description="Holat -> job'lar soni (`JobStatus` kalitlari)"
    )
    users_by_plan: dict[str, int] = Field(
        default_factory=dict, description="Reja -> foydalanuvchilar soni (`PlanType` kalitlari)"
    )
    success_rate: float = Field(
        default=0.0, description="Platforma bo'yicha muvaffaqiyat foizi (0–100)"
    )
    avg_duration_ms: float | None = Field(
        default=None, description="O'rtacha bajarish vaqti (ms); o'lchov bo'lmasa `null`"
    )
    dlq_depth: Annotated[int, Field(ge=0)] = Field(default=0, description="DLQ chuqurligi")
    active_workers: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Tirik worker'lar soni"
    )
    mrr_usd: float = Field(
        default=0.0,
        description="Oylik takrorlanuvchi daromad (USD) — faol obunalar narxlari yig'indisi",
    )
    total_execution_seconds: Annotated[float, Field(ge=0)] = Field(
        default=0.0, description="Platformada sarflangan jami hisoblash vaqti (soniya)"
    )
    generated_at: datetime | None = Field(
        default=None, description="Ko'rsatkichlar hisoblangan vaqt (UTC)"
    )


class AuditLogRead(ORMSchema):
    """Audit jurnalidagi bitta yozuv (admin harakati)."""

    id: uuid.UUID = Field(description="Yozuv identifikatori")
    admin_id: uuid.UUID | None = Field(
        default=None, description="Harakatni bajargan admin (o'chirilgan bo'lsa `null`)"
    )
    admin_email: str | None = Field(
        default=None,
        description="Admin emaili — `User` bilan `join` orqali qo'shiladi (tizim uchun `null`)",
    )
    action: AuditAction = Field(description="Bajarilgan harakat")
    target_type: str | None = Field(
        default=None, description="Ob'ekt turi (`user`, `job`, `api_key`...)"
    )
    target_id: str | None = Field(default=None, description="Ob'ekt identifikatori")
    details: dict[str, Any] | None = Field(
        default=None, description="Qo'shimcha kontekst (eski/yangi qiymatlar, sabab)"
    )
    ip_address: str | None = Field(default=None, description="So'rov kelgan IP manzil")
    user_agent: str | None = Field(default=None, description="Mijoz `User-Agent` qiymati")
    created_at: datetime = Field(description="Harakat bajarilgan vaqt (UTC)")


__all__ = [
    "ADMIN_EDITABLE_USER_FIELDS",
    "CHECK_DATABASE",
    "CHECK_REDIS",
    "CHECK_SANDBOX",
    "SYSTEM_CHECK_KEYS",
    "AdminStats",
    "AdminUserRead",
    "AdminUserUpdate",
    "AuditLogRead",
    "QueueDepth",
    "SystemStatus",
    "WorkerInfo",
]
