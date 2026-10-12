"""Durabl — administrator endpointlari (`/api/v1/admin/*`).

Oltita endpoint, hammasi `AdminUser` dependency'si bilan: platforma
ko'rsatkichlari, foydalanuvchilar ro'yxati va tahriri, tizim sog'lig'i,
barcha job'lar va audit jurnali.

**O'qish kesimlari `AnalyticsService` da.** `admin_stats`, `admin_users`,
`system_status` va `audit_logs` guruhlangan so'rovlar bilan ishlaydi
(N+1 yo'q), shuning uchun router ularni faqat chaqiradi va
`PaginatedResponse` konvertiga o'raydi.

**Yozish kesimi `AdminService` da.** `PUT /admin/users/{id}` uchta ishni
BITTA tranzaksiyada bajaradi: himoya qoidalarini tekshirish, maydonlarni
yangilash va har o'zgarish uchun `AuditLog` yozuvi. Router faqat so'rov
kontekstini (IP, `User-Agent`) uzatadi.

**Himoya qoidalari** (`AdminService` da, 403 `PERMISSION_DENIED`):

* admin o'zining `is_admin`/`is_active` qiymatini o'zgartira olmaydi;
* tizimdagi oxirgi faol adminni huquqdan ayirish/bloklash mumkin emas.

Shu ikki qoida "admin o'zini qulflab qo'ydi" degan tiklab bo'lmaydigan
holatni oldini oladi.

**IP manzil `request.client.host` dan olinadi**, `X-Forwarded-For` ATAYLAB
o'qilmaydi: mijoz uni soxtalashtirib audit jurnaliga yolg'on manzil
yozdirishi mumkin edi. Proxy orqasida uvicorn `--proxy-headers` bilan
ishga tushiriladi (ayni qaror `RateLimitMiddleware` da ham qabul qilingan).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Final, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, status

from app.constants import AuditAction, PlanType
from app.dependencies import AdminUser, AnalyticsSvc, DbSession, Pagination, RedisDep, ScopeAdmin
from app.schemas.admin import (
    AdminStats,
    AdminUserRead,
    AdminUserUpdate,
    AuditLogRead,
    SystemStatus,
)
from app.schemas.base import ErrorResponse, PaginatedResponse, TimeRangeParams
from app.schemas.job import JobFilter, JobSummary
from app.services.admin_service import AdminService

#: Admin endpointlari API kalit uchun `admin` doirasini TALAB QILADI.
#:
#: `AdminUser` faqat foydalanuvchining ROLINI tekshiradi
#: (`user.is_admin`), lekin u `get_current_active_user` ustida qurilgan
#: — ya'ni API kalitni ham qabul qiladi. Busiz admin foydalanuvchining
#: TOR doiradagi kaliti (masalan `jobs:read`) butun admin paneliga
#: yetib borardi: boshqa foydalanuvchilarni o'zgartirish, DLQ tozalash,
#: audit jurnalini o'qish.
#:
#: Ikki tekshiruv BIRGA ishlaydi: rol (kim) va doira (qanday kalit bilan).
router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[ScopeAdmin],
)

#: `User-Agent` header nomi (audit yozuvi uchun).
HEADER_USER_AGENT: Final = "user-agent"

#: Barcha admin endpointlari uchun umumiy xato javoblari.
ADMIN_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Autentifikatsiya talab qilinadi",
    },
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": "Administrator huquqi yo'q (`ADMIN_REQUIRED`)",
    },
}

#: `PUT /admin/users/{id}` qo'shimcha xatolari.
USER_UPDATE_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    **ADMIN_RESPONSES,
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "Bunday foydalanuvchi yo'q",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": "So'rov tanasi noto'g'ri (hech bir maydon berilmagan)",
    },
}

#: `?start=&end=` query dependency'si.
TimeRange = Annotated[TimeRangeParams, Depends()]

#: Tartiblash yo'nalishi.
SortOrder = Annotated[
    Literal["asc", "desc"],
    Query(description="Tartiblash yo'nalishi"),
]


async def get_admin_service(session: DbSession, redis: RedisDep) -> AdminService:
    """`AdminService` dependency'si.

    `app/dependencies.py` boshqa agentning fayli, shuning uchun fabrika
    shu yerda e'lon qilingan — lekin ayni naqsh bo'yicha
    (`get_job_service` kabi: sessiya + Redis).
    """
    return AdminService(session, redis)


#: Admin servisining `Annotated` qisqartmasi.
AdminSvc = Annotated[AdminService, Depends(get_admin_service)]


@router.get(
    "/stats",
    response_model=AdminStats,
    status_code=status.HTTP_200_OK,
    summary="Platforma ko'rsatkichlari",
    description=(
        "Foydalanuvchilar, job'lar, muvaffaqiyat foizi, DLQ chuqurligi, "
        "tirik worker'lar va oylik takrorlanuvchi daromad (MRR)."
    ),
    responses=ADMIN_RESPONSES,
)
async def get_admin_stats(admin: AdminUser, svc: AnalyticsSvc) -> AdminStats:
    """Platforma bo'yicha umumiy statistika."""
    return await svc.admin_stats()


@router.get(
    "/users",
    response_model=PaginatedResponse[AdminUserRead],
    status_code=status.HTTP_200_OK,
    summary="Foydalanuvchilar ro'yxati",
    description=(
        "Filtr (`search`, `plan`, `is_active`, `is_admin`) va sahifalash "
        "bilan foydalanuvchilar. Har bir yozuvda agregatlar: jami job'lar, "
        "joriy oydagi job'lar, DLQ chuqurligi va faol API kalitlar soni."
    ),
    responses={
        **ADMIN_RESPONSES,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "`sort_by` ruxsat etilmagan ustun",
        },
    },
)
async def list_admin_users(
    admin: AdminUser,
    svc: AnalyticsSvc,
    pagination: Pagination,
    search: Annotated[
        str | None,
        Query(max_length=255, description="Email yoki ism bo'yicha qidiruv"),
    ] = None,
    plan: Annotated[PlanType | None, Query(description="Obuna rejasi bo'yicha filtr")] = None,
    is_active: Annotated[bool | None, Query(description="Faqat faol/bloklanganlar")] = None,
    is_admin: Annotated[bool | None, Query(description="Faqat adminlar/oddiylar")] = None,
    sort_by: Annotated[
        str,
        Query(
            description="Tartiblash ustuni: `created_at`, `updated_at`, `email`, `last_login_at`"
        ),
    ] = "created_at",
    sort_order: SortOrder = "desc",
) -> PaginatedResponse[AdminUserRead]:
    """Filtrlangan foydalanuvchilar sahifasi."""
    items, total = await svc.admin_users(
        search=search,
        is_active=is_active,
        is_admin=is_admin,
        plan=plan,
        page=pagination.page,
        page_size=pagination.page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedResponse.from_params(items, total=total, params=pagination)


@router.put(
    "/users/{user_id}",
    response_model=AdminUserRead,
    status_code=status.HTTP_200_OK,
    summary="Foydalanuvchini o'zgartirish",
    description=(
        "`full_name`, `is_active`, `is_admin` va `plan` maydonlarini "
        "qismiy yangilaydi. Har bir o'zgarish `AuditLog` yozuvini "
        "qoldiradi (IP va `User-Agent` bilan). Admin o'zining huquqini "
        "yoki faolligini o'zgartira olmaydi, oxirgi faol adminni "
        "huquqdan ayirish ham mumkin emas."
    ),
    responses=USER_UPDATE_RESPONSES,
)
async def update_admin_user(
    admin: AdminUser,
    svc: AdminSvc,
    request: Request,
    user_id: Annotated[uuid.UUID, Path(description="Foydalanuvchi identifikatori")],
    payload: AdminUserUpdate,
) -> AdminUserRead:
    """Foydalanuvchini yangilaydi va audit yozuvini qoldiradi."""
    return await svc.update_user(
        admin,
        user_id,
        payload,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get(HEADER_USER_AGENT),
    )


@router.get(
    "/system",
    response_model=SystemStatus,
    status_code=status.HTTP_200_OK,
    summary="Tizim sog'lig'i",
    description=(
        "Pastki tizimlar tekshiruvi (`database`, `redis`, `sandbox`), "
        "worker'lar registri, ustuvorlik bo'yicha navbatlar, "
        "kechiktirilgan job'lar, DLQ va webhook navbati chuqurligi."
    ),
    responses=ADMIN_RESPONSES,
)
async def get_system_status(admin: AdminUser, svc: AnalyticsSvc) -> SystemStatus:
    """Tizimning umumiy holati."""
    return await svc.system_status()


@router.get(
    "/jobs",
    response_model=PaginatedResponse[JobSummary],
    status_code=status.HTTP_200_OK,
    summary="Barcha job'lar",
    description=(
        "BARCHA foydalanuvchilarning job'lari. `?user_id` berilsa faqat "
        "shu foydalanuvchining job'lari qaytadi. Qolgan filtrlar "
        "mijoz `GET /jobs` endpointi bilan AYNI."
    ),
    responses=ADMIN_RESPONSES,
)
async def list_admin_jobs(
    admin: AdminUser,
    svc: AdminSvc,
    pagination: Pagination,
    filters: Annotated[JobFilter, Depends()],
    user_id: Annotated[
        uuid.UUID | None,
        Query(description="Faqat shu foydalanuvchining job'lari"),
    ] = None,
) -> PaginatedResponse[JobSummary]:
    """Platforma bo'yicha job'lar sahifasi."""
    items, total = await svc.list_jobs(filters, pagination, user_id=user_id)
    return PaginatedResponse.from_params(
        [JobSummary.model_validate(job) for job in items],
        total=total,
        params=pagination,
    )


@router.get(
    "/audit-logs",
    response_model=PaginatedResponse[AuditLogRead],
    status_code=status.HTTP_200_OK,
    summary="Audit jurnali",
    description=(
        "Admin harakatlari jurnali (yangisidan boshlab). `admin_email` "
        "`users` jadvali bilan `LEFT JOIN` orqali qo'shiladi: tizim "
        "bajargan yoki admini o'chirilgan yozuvlar ham ro'yxatda qoladi."
    ),
    responses={
        **ADMIN_RESPONSES,
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": ErrorResponse,
            "description": "`sort_by` ruxsat etilmagan ustun",
        },
    },
)
async def list_audit_logs(
    admin: AdminUser,
    svc: AnalyticsSvc,
    pagination: Pagination,
    time_range: TimeRange,
    action: Annotated[AuditAction | None, Query(description="Harakat turi bo'yicha filtr")] = None,
    admin_id: Annotated[
        uuid.UUID | None,
        Query(description="Faqat shu adminning harakatlari"),
    ] = None,
    target_type: Annotated[
        str | None,
        Query(max_length=50, description="Obyekt turi (`user`, `job`, `dlq`...)"),
    ] = None,
    sort_by: Annotated[
        str,
        Query(description="Tartiblash ustuni: `created_at` yoki `action`"),
    ] = "created_at",
    sort_order: SortOrder = "desc",
) -> PaginatedResponse[AuditLogRead]:
    """Filtrlangan audit jurnali sahifasi."""
    items, total = await svc.audit_logs(
        action=action,
        admin_id=admin_id,
        target_type=target_type,
        start=time_range.start,
        end=time_range.end,
        page=pagination.page,
        page_size=pagination.page_size,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    return PaginatedResponse.from_params(items, total=total, params=pagination)


__all__ = ["router"]
