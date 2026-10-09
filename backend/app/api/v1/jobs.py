"""Durabl — job endpointlari (`/jobs/*`), platformaning markaziy yo'llari.

CONTRACTS "QO'SHIMCHA 2 / JOBS" jadvali (hammasi JWT yoki `X-API-Key`):

| Metod | Yo'l                    | Javob                           |
|-------|-------------------------|---------------------------------|
| GET   | `/jobs`                 | `PaginatedResponse[JobSummary]` |
| POST  | `/jobs`                 | `JobRead` (201 yoki 200)        |
| GET   | `/jobs/{id}`            | `JobRead`                       |
| GET   | `/jobs/{id}/status`     | `JobStatusResponse`             |
| GET   | `/jobs/{id}/logs`       | `JobLogsResponse`               |
| GET   | `/jobs/{id}/result`     | `JobResultResponse`             |
| GET   | `/jobs/{id}/timeline`   | `JobTimeline`                   |
| POST  | `/jobs/{id}/cancel`     | `JobCancelResponse`             |
| POST  | `/jobs/{id}/resubmit`   | `JobRead` (201)                 |

## `POST /jobs` statusi DINAMIK

`JobService.submit()` `(job, created)` qaytaradi. `created=True` — yangi job
yaratildi (**201**); `created=False` — ayni `Idempotency-Key` bilan AVVAL
yuborilgan job qaytarildi (**200**). Deklaratsiyada 201 turadi, haqiqiy
qiymat `response.status_code` orqali o'zgartiriladi — shu tufayli mijoz
"yangi yaratildimi yoki takroriy so'rovmi" degan savolga HTTP statusdan
javob oladi. Ikki holatda ham `Location: {API_V1_PREFIX}/jobs/{id}` qo'yiladi.

## Polling uchun mo'ljallangan yo'llar

`GET /jobs/{id}/status` — yengil javob (`code`, `stdout`, `stderr` YO'Q), SDK
`wait_for_result()` shuni qayta-qayta so'raydi. `GET /jobs/{id}/logs` esa
`after_sequence` kursori bilan faqat yangi qatorlarni beradi. Ikkisi ham
`Cache-Control: no-store` qo'yadi: oraliqdagi proxy eski holatni keshlab
qo'ysa mijoz abadiy kutib qolardi.

## Qatlam qoidalari

Router `select()` yozmaydi, `HTTPException` tashlamaydi va biznes qarorlar
qabul qilmaydi: `JobService` domen xatolarini tashlaydi (`JobNotFoundError`,
`ResultNotReadyError`, `QuotaExceededError`, ...), `main.py` dagi
`DurablError` handler'i ularni `ErrorResponse` ga aylantiradi. Boshqa
foydalanuvchining job'i HAR DOIM 404 bo'lib qaytadi (IDOR himoyasi —
`JobService.get()` ichida).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query, Response, status
from pydantic import ValidationError as SchemaValidationError

from app.config import settings
from app.constants import (
    MAX_TAG_LENGTH,
    FailureReason,
    JobStatus,
    LogStream,
    Priority,
    Runtime,
)
from app.dependencies import (
    CorrelationId,
    CurrentUser,
    ExecutionSvc,
    IdempotencyKey,
    JobSvc,
    Pagination,
)
from app.exceptions import ValidationError
from app.logging_config import get_logger
from app.models.execution_log import ExecutionLog
from app.schemas.base import ErrorResponse, PaginatedResponse, PaginationParams
from app.schemas.execution import (
    MAX_LOG_LIMIT,
    ExecutionFilter,
    ExecutionLogRead,
    ExecutionSummary,
)
from app.schemas.job import (
    JOB_SORT_FIELDS,
    JobCancelResponse,
    JobCreate,
    JobFilter,
    JobLogsResponse,
    JobRead,
    JobResultResponse,
    JobStatusResponse,
    JobSummary,
    JobTimeline,
)
from app.services.job_service import DEFAULT_LOG_LIMIT

logger = get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])

#: Real vaqtda so'raladigan javoblar keshlanmaydi.
NO_STORE = "no-store"

#: `GET /jobs/{id}/timeline` da ko'rsatiladigan urinishlar soni chegarasi.
#: Bitta job'da urinishlar `max_retries + 1` ta, ya'ni amalda o'nlab —
#: chegara faqat buzilgan ma'lumotdan himoya uchun.
TIMELINE_EXECUTION_LIMIT = 100


def _errors(*items: tuple[int, str]) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses` lug'atini yasaydi — barcha xatolar `ErrorResponse`."""
    return {code: {"model": ErrorResponse, "description": text} for code, text in items}


#: Har bir job yo'lida uchraydigan xatolar.
_COMMON_ERRORS: tuple[tuple[int, str], ...] = (
    (401, "Autentifikatsiya ma'lumoti yo'q yoki yaroqsiz"),
    (403, "Hisob faolsizlantirilgan"),
)

#: Bitta job'ga murojaat qiladigan yo'llarda qo'shimcha.
_JOB_ERRORS: tuple[tuple[int, str], ...] = (
    *_COMMON_ERRORS,
    (404, "Bunday job yo'q yoki boshqa foydalanuvchiga tegishli"),
    (422, "`job_id` yaroqli UUID emas"),
)

#: Yo'l parametri — FastAPI yaroqsiz UUID uchun 422 qaytaradi.
JobId = Annotated[uuid.UUID, Path(description="Job identifikatori (UUID)")]


async def get_job_filter(
    status_: Annotated[
        JobStatus | None,
        Query(alias="status", description="Holat bo'yicha filtr"),
    ] = None,
    runtime: Annotated[
        Runtime | None,
        Query(description="Bajarish muhiti bo'yicha filtr"),
    ] = None,
    priority: Annotated[
        Priority | None,
        Query(description="Ustuvorlik bo'yicha filtr"),
    ] = None,
    failure_reason: Annotated[
        FailureReason | None,
        Query(description="Muvaffaqiyatsizlik sababi bo'yicha filtr"),
    ] = None,
    tag: Annotated[
        str | None,
        Query(max_length=MAX_TAG_LENGTH, description="Shu teg qo'yilgan job'lar"),
    ] = None,
    search: Annotated[
        str | None,
        Query(max_length=255, description="Kod va teglar bo'yicha matnli qidiruv"),
    ] = None,
    start: Annotated[
        datetime | None,
        Query(description="Oraliq boshlanishi (ISO-8601, UTC)"),
    ] = None,
    end: Annotated[
        datetime | None,
        Query(description="Oraliq tugashi (ISO-8601, UTC)"),
    ] = None,
    sort_by: Annotated[
        str,
        Query(description="Tartiblash ustuni: " + ", ".join(sorted(JOB_SORT_FIELDS))),
    ] = "created_at",
    sort_order: Annotated[
        Literal["asc", "desc"],
        Query(description="Tartiblash yo'nalishi"),
    ] = "desc",
) -> JobFilter:
    """`GET /jobs` query parametrlarini `JobFilter` ga aylantiradi.

    **Nega `Depends(JobFilter)` emas.** FastAPI pydantic modelini bevosita
    dependency qilib chaqirganda model ichidagi `model_validator` xatosini
    TUTMAYDI — mijoz 422 o'rniga 500 oladi. `Annotated[JobFilter, Query()]`
    ham yaramaydi: `JobFilter` da `extra="forbid"`, shuning uchun FastAPI
    `?page=` va `?page_size=` ni "noma'lum maydon" deb rad etardi (ular
    `pagination_params` ga tegishli).

    Shuning uchun parametrlar shu yerda OCHIQ e'lon qilinadi (OpenAPI
    hujjati ham shundan to'g'ri chiqadi), model esa qo'lda yasaladi va
    uning o'zaro bog'liq tekshiruvlari (`start <= end`, ruxsat etilgan
    `sort_by`) domen `ValidationError` iga — ya'ni 422 `ErrorResponse` ga —
    aylantiriladi.

    Raises:
        ValidationError: Oraliq yoki tartiblash ustuni noto'g'ri.
    """
    try:
        return JobFilter(
            status=status_,
            runtime=runtime,
            priority=priority,
            failure_reason=failure_reason,
            tag=tag,
            search=search,
            start=start,
            end=end,
            sort_by=sort_by,
            sort_order=sort_order,
        )
    except SchemaValidationError as exc:
        raise ValidationError(
            "Job filtri parametrlari noto'g'ri",
            details={
                "errors": [
                    {
                        "field": ".".join(str(part) for part in error["loc"]) or "query",
                        "message": error["msg"],
                    }
                    for error in exc.errors()
                ]
            },
        ) from exc


#: `GET /jobs` filtri (query parametrlari).
JobFilterDep = Annotated[JobFilter, Depends(get_job_filter)]


# ---------------------------------------------------------------------------
# Ro'yxat va yaratish
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=PaginatedResponse[JobSummary],
    status_code=status.HTTP_200_OK,
    summary="Job'lar ro'yxati",
    description=(
        "Foydalanuvchining job'lari — holat, muhit, ustuvorlik, sabab, teg va "
        "matnli qidiruv bo'yicha filtrlanadi. Javobda `code` qaytarilmaydi "
        "(ro'yxat yengil bo'lishi uchun) — to'liq tafsilot `GET /jobs/{id}` da."
    ),
    responses=_errors(
        *_COMMON_ERRORS,
        (422, "Filtr yoki tartiblash parametri noto'g'ri"),
    ),
)
async def list_jobs(
    user: CurrentUser,
    svc: JobSvc,
    pagination: Pagination,
    filters: JobFilterDep,
) -> PaginatedResponse[JobSummary]:
    """Filtrlangan va sahifalangan job ro'yxatini qaytaradi."""
    items, total = await svc.list(user, filters, pagination)
    return PaginatedResponse.from_params(
        [JobSummary.model_validate(job) for job in items],
        total=total,
        params=pagination,
    )


@router.post(
    "",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
    summary="Yangi job yuborish",
    description=(
        "Kodni bajarish uchun navbatga qo'yadi. `Idempotency-Key` header "
        "berilsa takroriy so'rov YANGI job yaratmaydi: avvalgi job 200 "
        "status bilan qaytariladi (yangi job — 201). Rejalashtirilgan "
        "(`scheduled_at`) va takrorlanuvchi (`cron_expression`) job'lar "
        "darhol navbatga tushmaydi — ularni scheduler ko'taradi."
    ),
    responses={
        # Deklaratsiyadagi status 201, lekin takroriy idempotent so'rov 200
        # qaytaradi — hujjatda ikkisi ham ko'rinishi kerak.
        200: {
            "model": JobRead,
            "description": "Ayni `Idempotency-Key` bilan avval yuborilgan job qaytarildi",
        },
        **_errors(
            *_COMMON_ERRORS,
            (402, "Oylik reja kvotasi tugadi"),
            (409, "Ayni `Idempotency-Key` boshqa so'rov tanasi bilan ishlatilgan"),
            (413, "Kod yoki payload juda katta"),
            (422, "Kod tekshiruvdan o'tmadi yoki so'rov maydonlari noto'g'ri"),
            (429, "Bir vaqtda bajarilayotgan job'lar limiti oshdi"),
        ),
    },
)
async def submit_job(
    data: JobCreate,
    user: CurrentUser,
    svc: JobSvc,
    response: Response,
    idempotency_key: IdempotencyKey,
    correlation_id: CorrelationId,
) -> JobRead:
    """Job yaratadi (yoki idempotency tufayli mavjudini qaytaradi)."""
    job, created = await svc.submit(user, data, idempotency_key=idempotency_key)

    # Takroriy so'rov yangi resurs YARATMAGANI uchun 201 emas, 200.
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    response.headers["Location"] = f"{settings.API_V1_PREFIX}/jobs/{job.id}"

    logger.info(
        "job qabul qilindi",
        job_id=str(job.id),
        created=created,
        # So'rovning correlation ID'si — job'ning O'Z `correlation_id` i
        # `JobService.submit()` da yaratiladi, shuning uchun ikkisi alohida.
        request_correlation_id=correlation_id,
        job_correlation_id=job.correlation_id,
    )
    return JobRead.model_validate(job)


# ---------------------------------------------------------------------------
# Bitta job
# ---------------------------------------------------------------------------


@router.get(
    "/{job_id}",
    response_model=JobRead,
    status_code=status.HTTP_200_OK,
    summary="Job tafsiloti",
    description="Bitta job'ning to'liq ma'lumoti: kod, payload, natija va chiqish oqimlari.",
    responses=_errors(*_JOB_ERRORS),
)
async def get_job(user: CurrentUser, svc: JobSvc, job_id: JobId) -> JobRead:
    """Bitta job'ni qaytaradi."""
    job = await svc.get(user, job_id)
    return JobRead.model_validate(job)


@router.get(
    "/{job_id}/status",
    response_model=JobStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Job holati (yengil)",
    description=(
        "Tez polling uchun qisqa javob: holat, urinishlar soni, vaqt belgilari "
        "va davomiylik. `code`, `stdout`, `stderr` va `result` QAYTARILMAYDI."
    ),
    responses=_errors(*_JOB_ERRORS),
)
async def get_job_status(
    user: CurrentUser,
    svc: JobSvc,
    job_id: JobId,
    response: Response,
) -> JobStatusResponse:
    """Job holatini yengil shaklda qaytaradi."""
    job = await svc.get(user, job_id)
    response.headers["Cache-Control"] = NO_STORE
    return JobStatusResponse.model_validate(job)


@router.get(
    "/{job_id}/logs",
    response_model=JobLogsResponse,
    status_code=status.HTTP_200_OK,
    summary="Job loglari",
    description=(
        "Log qatorlari `sequence` bo'yicha o'sish tartibida. `after_sequence` "
        "berilmasa job'ning BARCHA urinishlari loglari qaytadi; berilsa — "
        "faqat OXIRGI urinishning shu raqamdan keyingi qatorlari (real vaqt "
        "kursori). Keyingi so'rovda javobdagi `next_sequence` ni yuboring."
    ),
    responses=_errors(*_JOB_ERRORS),
)
async def get_job_logs(
    user: CurrentUser,
    svc: JobSvc,
    job_id: JobId,
    response: Response,
    after_sequence: Annotated[
        int | None,
        Query(ge=0, description="Shu `sequence` dan KEYINGI qatorlar (kursor)"),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_LOG_LIMIT, description="Maksimal qatorlar soni"),
    ] = DEFAULT_LOG_LIMIT,
    stream: Annotated[
        LogStream | None,
        Query(description="Faqat shu oqim: `stdout`, `stderr` yoki `system`"),
    ] = None,
) -> JobLogsResponse:
    """Log sahifasini kursor bilan qaytaradi."""
    # Tur OCHIQ ko'rsatilgan: `JobService.list` metodi klass ichida `list`
    # nomini soyalaydi, shuning uchun servisning `list[ExecutionLog]`
    # annotatsiyasi tur tekshiruvchisi uchun noaniq bo'lib qoladi.
    rows: list[ExecutionLog] = await svc.logs(
        user, job_id, after_sequence=after_sequence, limit=limit
    )

    # Kursor va "yana bor" belgisi O'QILGAN sahifadan hisoblanadi — oqim
    # filtridan OLDIN. Aks holda `stream=stderr` bilan polling qilgan mijoz
    # faqat stdout qatori kelgan sahifada kursorni siljitmay qotib qolardi.
    # `limit` shu bilan "server nechta qator O'QIDI" ma'nosini oladi;
    # `entries` esa shu sahifaning tanlangan oqimga mos qismi.
    fetched = len(rows)
    last = rows[-1] if rows else None
    if stream is not None:
        rows = [row for row in rows if row.stream == stream]

    response.headers["Cache-Control"] = NO_STORE
    return JobLogsResponse(
        job_id=job_id,
        execution_id=last.execution_id if last is not None else None,
        entries=[ExecutionLogRead.model_validate(row) for row in rows],
        next_sequence=last.sequence if last is not None else None,
        has_more=fetched >= limit,
    )


@router.get(
    "/{job_id}/result",
    response_model=JobResultResponse,
    status_code=status.HTTP_200_OK,
    summary="Job natijasi",
    description=(
        "Yakuniy natija: qaytarilgan qiymat, chiqish oqimlari, chiqish kodi "
        "va davomiylik. Job hali yakuniy holatda bo'lmasa 409 "
        "(`RESULT_NOT_READY`) qaytadi — kutish uchun `/status` ni polling qiling."
    ),
    responses=_errors(
        *_JOB_ERRORS,
        (409, "Job hali tugamagan — natija tayyor emas"),
    ),
)
async def get_job_result(user: CurrentUser, svc: JobSvc, job_id: JobId) -> JobResultResponse:
    """Job natijasini qaytaradi."""
    job = await svc.result(user, job_id)
    return JobResultResponse.model_validate(job)


@router.get(
    "/{job_id}/timeline",
    response_model=JobTimeline,
    status_code=status.HTTP_200_OK,
    summary="Job vaqt o'qi",
    description=(
        "Job hayot siklining o'lchangan bosqichlari: navbatda kutish, sof "
        "bajarish va umumiy vaqt, hamda har bir urinish (retry tarixi)."
    ),
    responses=_errors(*_JOB_ERRORS),
)
async def get_job_timeline(
    user: CurrentUser,
    svc: JobSvc,
    executions_svc: ExecutionSvc,
    job_id: JobId,
) -> JobTimeline:
    """Vaqt o'qi va urinishlar tarixini qaytaradi."""
    timeline = await svc.timeline(user, job_id)

    # `JobService.timeline()` urinishlarni qisqartirilgan lug'at ko'rinishida
    # beradi (`id`, `created_at` yo'q), frontend `JobTimeline.executions` esa
    # to'liq `ExecutionSummary` kutadi — shuning uchun urinishlar
    # `ExecutionService` dan, egalik tekshiruvi bilan, alohida olinadi.
    executions, _ = await executions_svc.list(
        user,
        ExecutionFilter(job_id=job_id, sort_by="attempt_number", sort_order="asc"),
        PaginationParams(page=1, page_size=TIMELINE_EXECUTION_LIMIT),
    )

    payload: dict[str, Any] = dict(timeline)
    payload["attempts"] = payload.pop("attempt_count", 0)
    payload["executions"] = [ExecutionSummary.model_validate(item) for item in executions]
    return JobTimeline.model_validate(payload)


# ---------------------------------------------------------------------------
# Amallar
# ---------------------------------------------------------------------------


@router.post(
    "/{job_id}/cancel",
    response_model=JobCancelResponse,
    status_code=status.HTTP_200_OK,
    summary="Job'ni bekor qilish",
    description=(
        "Navbatdagi job'ni darhol bekor qiladi; bajarilayotgan job'ga esa "
        "kooperativ to'xtatish signali yuboriladi (worker uni heartbeat "
        "paytida o'qiydi). Yakuniy holatdagi job 409 qaytaradi."
    ),
    responses=_errors(
        *_JOB_ERRORS,
        (409, "Job yakuniy holatda — bekor qilinmaydi"),
    ),
)
async def cancel_job(user: CurrentUser, svc: JobSvc, job_id: JobId) -> JobCancelResponse:
    """Job'ni bekor qiladi."""
    job = await svc.cancel(user, job_id)
    return JobCancelResponse.model_validate(job)


@router.post(
    "/{job_id}/resubmit",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
    summary="Job'ni qayta yuborish",
    description=(
        "Mavjud job'ning kodi va sozlamalari bilan YANGI job yaratadi. "
        "Eski job o'zgarmaydi. Rejalashtirish maydonlari va takrorlanmaslik "
        "kaliti ko'chirilmaydi — qayta yuborish darhol bajarilishni bildiradi."
    ),
    responses=_errors(
        *_JOB_ERRORS,
        (402, "Oylik reja kvotasi tugadi"),
        (429, "Bir vaqtda bajarilayotgan job'lar limiti oshdi"),
    ),
)
async def resubmit_job(
    user: CurrentUser,
    svc: JobSvc,
    job_id: JobId,
    response: Response,
) -> JobRead:
    """Job'ni qayta yuboradi (yangi job yaratiladi)."""
    job = await svc.resubmit(user, job_id)
    response.headers["Location"] = f"{settings.API_V1_PREFIX}/jobs/{job.id}"
    return JobRead.model_validate(job)


__all__ = ["router"]
