"""Durabl — `/dlq` routeri: o'lik xatlar navbati (Dead Letter Queue).

DLQ — Durabl'ni raqobatchilardan ajratib turadigan funksiya. Barcha
avtomatik qayta urinishlar tugagach job "jimgina o'lmaydi": u sababi,
oxirgi xato matni va urinishlar tarixi bilan `dlq_entries` jadvalida
qoladi. Mijoz muammoni ko'radi, kodini tuzatadi va QO'LDA qayta uradi.

## Yo'l tartibi — qat'iy talab

`GET /dlq/stats` AYNAN `GET /dlq/{entry_id}` dan OLDIN e'lon qilingan.
Teskari tartibda FastAPI `"stats"` matnini `{entry_id}` yo'l parametri deb
o'qiydi, UUID validatsiyasi yiqiladi va endpoint 422 qaytaradi. Pastdagi
tartibni O'ZGARTIRMANG.

## "O'chirish" aslida nima qiladi

`DELETE /dlq/{id}` yozuvni fizik o'chirmaydi, `resolved=True` deb
belgilaydi: `dlq_entries.job_id` unique, ya'ni o'chirilgan yozuv job yana
yiqilganda qaytadan yaratilardi va "men buni ko'rib chiqdim" tarixi
yo'qolardi. Chuqurlik (`depth`) esa faqat hal qilinmagan yozuvlarni
sanaydi, shuning uchun operator uchun natija "o'chirish" bilan bir xil.

Qatlam qoidasi: biznes logika yo'q, `select()` yozilmaydi, `HTTPException`
tashlanmaydi.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Final

from fastapi import APIRouter, Body, Depends, Path, status

from app.constants import JobStatus
from app.dependencies import AnalyticsSvc, CurrentUser, DlqSvc, Pagination
from app.schemas.base import ErrorResponse, PaginatedResponse, SuccessResponse
from app.schemas.dlq import (
    DlqEntryRead,
    DlqFilter,
    DlqRetryRequest,
    DlqRetryResponse,
    DlqStats,
)
from app.utils.time_utils import ensure_utc, utcnow

router = APIRouter(prefix="/dlq", tags=["dlq"])

#: Mumkin bo'lgan xato javoblari (OpenAPI uchun).
_ERRORS: Final[dict[int, dict[str, Any]]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Autentifikatsiya talab qilinadi (`AUTHENTICATION_REQUIRED`)",
    },
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": "Hisob faolsizlantirilgan (`INACTIVE_USER`)",
    },
    status.HTTP_404_NOT_FOUND: {
        "model": ErrorResponse,
        "description": "DLQ yozuvi topilmadi (`DLQ_ENTRY_NOT_FOUND`)",
    },
    status.HTTP_409_CONFLICT: {
        "model": ErrorResponse,
        "description": "Yozuv allaqachon hal qilingan (`DLQ_ALREADY_RESOLVED`)",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": "So'rov ma'lumoti noto'g'ri (`VALIDATION_ERROR`)",
    },
}


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Berilgan kodlar uchun OpenAPI `responses` lug'atini yasaydi."""
    return {code: _ERRORS[code] for code in codes}


#: Yo'l parametri — barcha `{entry_id}` endpointlarida bir xil ta'rif.
EntryId = Annotated[uuid.UUID, Path(description="DLQ yozuvi identifikatori")]


@router.get(
    "",
    response_model=PaginatedResponse[DlqEntryRead],
    status_code=status.HTTP_200_OK,
    summary="DLQ yozuvlari ro'yxati",
    description=(
        "Foydalanuvchining o'lik xatlari. Hal qilinganlik, xato sababi, job va "
        "`failed_at` oralig'i bo'yicha filtrlanadi. Har yozuv bilan tegishli "
        "job'ning qisqa ko'rinishi ham qaytadi."
    ),
    responses=_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)
async def list_dlq_entries(
    user: CurrentUser,
    svc: DlqSvc,
    pagination: Pagination,
    filters: Annotated[DlqFilter, Depends()],
) -> PaginatedResponse[DlqEntryRead]:
    """DLQ yozuvlarining sahifalangan ro'yxati."""
    items, total = await svc.list_dlq(user.id, filters, pagination)
    return PaginatedResponse.from_params(
        [DlqEntryRead.model_validate(item) for item in items],
        total=total,
        params=pagination,
    )


# DIQQAT: `/stats` `/{entry_id}` dan OLDIN turishi SHART (modul docstring'i).
@router.get(
    "/stats",
    response_model=DlqStats,
    status_code=status.HTTP_200_OK,
    summary="DLQ chuqurligi va sabablar taqsimoti",
    description=(
        "Dashboard paneli uchun umumlashtirilgan ko'rsatkichlar: chuqurlik "
        "(hal qilinmagan yozuvlar), jami va hal qilinganlar soni, sabab "
        "bo'yicha taqsimot, oxirgi 24 soatda qo'shilganlar va eng qadimgi hal "
        "qilinmagan yozuvning vaqti. Keshlanmaydi — bu ogohlantirish ko'rsatkichi."
    ),
    responses=_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    ),
)
async def get_dlq_stats(
    user: CurrentUser,
    analytics: AnalyticsSvc,
) -> DlqStats:
    """DLQ bo'yicha agregat ko'rsatkichlar (faqat shu foydalanuvchi kesimida)."""
    return await analytics.dlq_stats(user.id)


@router.get(
    "/{entry_id}",
    response_model=DlqEntryRead,
    status_code=status.HTTP_200_OK,
    summary="Bitta DLQ yozuvi tafsiloti",
    description=(
        "Xato sababi, oxirgi xato matni (to'liq traceback bo'lishi mumkin), "
        "avtomatik va qo'lda urinishlar soni, operator izohlari va tegishli "
        "job'ning qisqa ko'rinishi."
    ),
    responses=_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
    ),
)
async def get_dlq_entry(
    user: CurrentUser,
    svc: DlqSvc,
    entry_id: EntryId,
) -> DlqEntryRead:
    """Bitta DLQ yozuvi (egalik tekshirilgan)."""
    entry = await svc.get_dlq_entry(user.id, entry_id)
    return DlqEntryRead.model_validate(entry)


@router.post(
    "/{entry_id}/retry",
    response_model=DlqRetryResponse,
    status_code=status.HTTP_200_OK,
    summary="Job'ni DLQ'dan qayta navbatga qo'yish",
    description=(
        "Job `QUEUED` holatiga qaytadi va xato maydonlari tozalanadi — bu "
        "yangi urinishlar seriyasi (mijoz muammoni tuzatgan deb hisoblanadi). "
        "`priority`, `max_retries` va `timeout_seconds` berilsa job'ga "
        "qo'llanadi. `reset_retry_count=false` bo'lsa `retry_count` saqlanadi "
        "(job faqat QOLGAN urinishlardan foydalanadi). `resolve=false` "
        "(frontend'da `mark_resolved=false`) bo'lsa yozuv DLQ'da hal "
        "qilinmagan holda qoladi. "
        "Allaqachon hal qilingan yozuvda 409 `DLQ_ALREADY_RESOLVED` qaytadi. "
        "Tana ixtiyoriy — tashlab ketish mumkin."
    ),
    responses=_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_409_CONFLICT,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)
async def retry_dlq_entry(
    user: CurrentUser,
    svc: DlqSvc,
    entry_id: EntryId,
    data: Annotated[
        DlqRetryRequest | None,
        Body(description="Qayta urinish parametrlari. Butunlay tashlab ketish mumkin."),
    ] = None,
) -> DlqRetryResponse:
    """Job'ni qayta navbatga qo'yadi va yangi holatini qaytaradi."""
    entry, job = await svc.retry_dlq_entry(user.id, entry_id, data or DlqRetryRequest())
    status_value = JobStatus(job.status)
    return DlqRetryResponse(
        entry_id=entry.id,
        job_id=job.id,
        status=status_value,
        # `QUEUED` — DB'da tasdiqlangan holat. Redis'ga qo'yish xato bersa
        # servis uni yutadi (job yo'qolmaydi, `scheduler` qayta oladi),
        # shuning uchun "navbatga qo'yildi" belgisi DB holatidan olinadi.
        requeued=status_value is JobStatus.QUEUED,
        resolved=bool(entry.resolved),
        retried_at=ensure_utc(entry.resolved_at) or utcnow(),
        message="Job DLQ'dan qayta navbatga qo'yildi",
    )


@router.delete(
    "/{entry_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="DLQ yozuvini hal qilingan deb belgilash",
    description=(
        "Yozuvni DLQ chuqurligidan olib tashlaydi (`resolved=true`). Yozuvning "
        "o'zi tarix uchun saqlanadi va `?resolved=true` filtri bilan ko'rinadi. "
        "Amal idempotent: takroriy `DELETE` ham 200 qaytaradi."
    ),
    responses=_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
    ),
)
async def delete_dlq_entry(
    user: CurrentUser,
    svc: DlqSvc,
    entry_id: EntryId,
) -> SuccessResponse:
    """Yozuvni hal qilingan deb belgilaydi."""
    entry = await svc.resolve_dlq_entry(user.id, entry_id)
    return SuccessResponse(
        message="DLQ yozuvi hal qilingan deb belgilandi",
        data={
            "entry_id": str(entry.id),
            "job_id": str(entry.job_id),
            "resolved": bool(entry.resolved),
        },
    )


__all__ = ["router"]
