"""Durabl — `/executions` routeri: bajarish urinishlari va ularning loglari.

Bitta job bir necha marta urinilishi mumkin (retry), har urinish alohida
`executions` yozuvi. Shu router aynan URINISHLAR kesimini beradi:

* `GET /executions` — filtrlangan, sahifalangan ro'yxat;
* `GET /executions/{id}` — bitta urinishning to'liq tafsiloti;
* `GET /executions/{id}/logs` — SHU urinishning loglari (kursorli).

Nega alohida log endpoint'i kerak: `GET /jobs/{id}/logs` job'ning BARCHA
urinishlari qatorlarini aralashtirib beradi, `sequence` esa har urinish
ichida 0'dan boshlanadi — ya'ni job kesimida kursor ishonchsiz. Urinish
kesimida esa `after_sequence` aniq ishlaydi va "jonli log" uchun mos.

Qatlam qoidasi: biznes logika yo'q, `select()` yozilmaydi, `HTTPException`
tashlanmaydi — servis domen xatolarini tashlaydi, `main.py` handler'i ularni
`ErrorResponse` ga aylantiradi.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Path, Query, status

from app.constants import LogStream
from app.dependencies import CurrentUser, ExecutionSvc, Pagination, ScopeJobsRead
from app.schemas.base import ErrorResponse, PaginatedResponse
from app.schemas.execution import (
    MAX_LOG_LIMIT,
    ExecutionFilter,
    ExecutionLogRead,
    ExecutionRead,
)
from app.schemas.job import JobLogsResponse

# `/jobs/{id}/logs` bilan AYNI standart sahifa hajmi (500). Konstanta
# servis qatlamidan olinadi — api -> services yo'nalishi qoidaga mos va
# ikki log endpoint'i bitta standartni ishlatadi.
from app.services.job_service import DEFAULT_LOG_LIMIT

#: Butun router API kalit uchun `jobs:read` doirasini talab qiladi.
#:
#: Urinishlar — job tafsilotining qismi (`jobs:read` tavsifi: "read status, logs, results and attempts").
#:
#: Darvoza ROUTER darajasida: yangi endpoint qo'shilganda u
#: avtomatik himoyalanadi va belgilashni unutib bo'lmaydi.
#: JWT bilan kirilganda scope tekshirilmaydi (`require_scope`).
router = APIRouter(
    prefix="/executions",
    tags=["executions"],
    dependencies=[ScopeJobsRead],
)

#: Barcha endpointlar uchun mumkin bo'lgan xato javoblari (OpenAPI uchun).
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
        "description": "Urinish topilmadi (`EXECUTION_NOT_FOUND`)",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": "So'rov parametrlari noto'g'ri (`VALIDATION_ERROR`)",
    },
}


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Berilgan kodlar uchun OpenAPI `responses` lug'atini yasaydi."""
    return {code: _ERRORS[code] for code in codes}


@router.get(
    "",
    response_model=PaginatedResponse[ExecutionRead],
    status_code=status.HTTP_200_OK,
    summary="Bajarish urinishlari ro'yxati",
    description=(
        "Foydalanuvchining barcha bajarish urinishlarini sahifalangan holda "
        "qaytaradi. Job, holat, xato sababi, worker va vaqt oralig'i bo'yicha "
        "filtrlash mumkin. Boshqa foydalanuvchining urinishi natijaga tushmaydi."
    ),
    responses=_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)
async def list_executions(
    user: CurrentUser,
    svc: ExecutionSvc,
    pagination: Pagination,
    filters: Annotated[ExecutionFilter, Depends()],
) -> PaginatedResponse[ExecutionRead]:
    """Urinishlar ro'yxati (`ExecutionFilter` + sahifalash)."""
    items, total = await svc.list(user, filters, pagination)
    return PaginatedResponse.from_params(
        [ExecutionRead.model_validate(item) for item in items],
        total=total,
        params=pagination,
    )


@router.get(
    "/{execution_id}",
    response_model=ExecutionRead,
    status_code=status.HTTP_200_OK,
    summary="Bitta urinish tafsiloti",
    description=(
        "Urinishning to'liq ko'rinishi: holat, worker, lease muddati, chiqish "
        "kodi, davomiylik va natija. `memory_peak_mb` ishonchli manba "
        "bo'lmagani uchun har doim `null` qaytadi."
    ),
    responses=_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
    ),
)
async def get_execution(
    user: CurrentUser,
    svc: ExecutionSvc,
    execution_id: Annotated[uuid.UUID, Path(description="Bajarish urinishi identifikatori")],
) -> ExecutionRead:
    """Bitta urinish (egalik tekshirilgan)."""
    execution = await svc.get(user, execution_id)
    return ExecutionRead.model_validate(execution)


@router.get(
    "/{execution_id}/logs",
    response_model=JobLogsResponse,
    status_code=status.HTTP_200_OK,
    summary="Urinish loglari (kursorli)",
    description=(
        "Shu urinishning log qatorlari `sequence` bo'yicha o'sish tartibida "
        "qaytadi. Jonli kuzatish uchun javobdagi `next_sequence` ni keyingi "
        "so'rovda `after_sequence` sifatida yuboring. `stream` bilan faqat "
        "`stdout`, `stderr` yoki Durabl'ning `system` xabarlarini olish mumkin."
    ),
    responses=_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)
async def get_execution_logs(
    user: CurrentUser,
    svc: ExecutionSvc,
    execution_id: Annotated[uuid.UUID, Path(description="Bajarish urinishi identifikatori")],
    after_sequence: Annotated[
        int | None,
        Query(ge=0, description="Shu tartib raqamidan KEYINGI qatorlar (kursor)"),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_LOG_LIMIT, description="Bir sahifadagi qatorlar soni"),
    ] = DEFAULT_LOG_LIMIT,
    stream: Annotated[
        LogStream | None,
        Query(description="Faqat shu oqim: `stdout`, `stderr` yoki `system`"),
    ] = None,
) -> JobLogsResponse:
    """Urinish loglarining bir sahifasi."""
    execution, entries = await svc.logs(
        user,
        execution_id,
        after_sequence=after_sequence,
        limit=limit,
        stream=stream,
    )
    rows = [ExecutionLogRead.model_validate(entry) for entry in entries]
    return JobLogsResponse(
        job_id=execution.job_id,
        execution_id=execution.id,
        entries=rows,
        # Qatorlar bo'lmasa kursor O'ZGARMAYDI — mijoz ayni shu qiymat bilan
        # qayta so'rab, yangi qatorlarni kutishda davom etadi.
        next_sequence=rows[-1].sequence if rows else after_sequence,
        has_more=len(rows) == limit,
    )


__all__ = ["router"]
