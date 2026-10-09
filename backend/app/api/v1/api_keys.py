"""Durabl — API kalitlar endpointlari (`/api-keys/*`).

CONTRACTS "QO'SHIMCHA 2 / API KEYS" jadvali:

| Metod  | Yo'l              | Auth | Javob                            |
|--------|-------------------|------|----------------------------------|
| GET    | `/api-keys`       | J    | `PaginatedResponse[ApiKeyRead]`  |
| POST   | `/api-keys`       | J    | `ApiKeyCreated` (201)            |
| DELETE | `/api-keys/{id}`  | J    | `SuccessResponse`                |

## Xavfsizlik qarorlari

1. **Faqat JWT.** Kalitlarni boshqarish `JwtUser` dependency'si bilan
   himoyalangan (`auth.py` da ta'riflangan): mavjud API kalit bilan YANGI
   kalit yaratish yoki boshqasini bekor qilish mumkin emas. Aks holda bitta
   oshkor bo'lgan kalit cheksiz davom etadigan egalikka aylanardi.
2. **Xom kalit bir marta.** `POST /api-keys` javobidagi `ApiKeyCreated.key`
   — xom kalitni ko'rish mumkin bo'lgan YAGONA joy; DB'da faqat SHA-256
   hash saqlanadi. Shu sababli javob keshlanmasligi uchun endpoint
   `Cache-Control: no-store` qo'yadi.
3. **O'chirish — bekor qilish.** `DELETE /api-keys/{id}` yozuvni fizik
   o'chirmaydi, `revoked_at` ni to'ldiradi: audit uchun "qaysi kalit qachon
   ishlatilgan" tarixi saqlanishi kerak.

## Sahifalash haqida

`AuthService.list_api_keys()` to'liq ro'yxatni qaytaradi (bitta
foydalanuvchida faol kalitlar soni `MAX_ACTIVE_API_KEYS` bilan
cheklangan, ya'ni ro'yxat kichik). Shartnoma esa `PaginatedResponse`
talab qiladi, shuning uchun sahifa shu ro'yxat ustida kesiladi — SQL
`LIMIT/OFFSET` emas. Bu ataylab: repozitoriyga yangi metod qo'shish
(boshqa agentning fayli) yoki API'da `select()` yozish mumkin emas,
ro'yxat hajmi esa bu yondashuvni xavfsiz qiladi.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query, Response, status

from app.api.v1.auth import JwtUser
from app.dependencies import AuthSvc, Pagination
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreated, ApiKeyRead
from app.schemas.base import ErrorResponse, PaginatedResponse, SuccessResponse

router = APIRouter(prefix="/api-keys", tags=["api-keys"])

#: Xom kalit qaytaradigan javob uchun keshni butunlay o'chirish.
NO_STORE = "no-store"


def _errors(*items: tuple[int, str]) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses` lug'atini yasaydi — barcha xatolar `ErrorResponse`."""
    return {code: {"model": ErrorResponse, "description": text} for code, text in items}


@router.get(
    "",
    response_model=PaginatedResponse[ApiKeyRead],
    status_code=status.HTTP_200_OK,
    summary="API kalitlar ro'yxati",
    description=(
        "Foydalanuvchining kalitlari (yangisi birinchi). Xom kalit "
        "qaytarilmaydi — faqat `key_prefix` va `last_four` ko'rinadi."
    ),
    responses=_errors(
        (401, "Autentifikatsiya ma'lumoti yo'q yoki yaroqsiz"),
        (403, "API kalit bilan ruxsat etilmaydi yoki hisob faolsizlantirilgan"),
    ),
)
async def list_api_keys(
    user: JwtUser,
    svc: AuthSvc,
    pagination: Pagination,
    include_revoked: Annotated[
        bool,
        Query(description="Bekor qilingan kalitlar ham ko'rsatilsinmi"),
    ] = False,
) -> PaginatedResponse[ApiKeyRead]:
    """Kalitlar ro'yxatini sahifalab qaytaradi."""
    keys = await svc.list_api_keys(user, include_revoked=include_revoked)
    page = keys[pagination.offset : pagination.offset + pagination.limit]
    return PaginatedResponse.from_params(
        [ApiKeyRead.model_validate(key) for key in page],
        total=len(keys),
        params=pagination,
    )


@router.post(
    "",
    response_model=ApiKeyCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Yangi API kalit yaratish",
    description=(
        "Yangi kalit yaratadi va uni javobda BIR MARTA ko'rsatadi. Qiymat "
        "boshqa hech qachon qaytarilmaydi — xavfsiz joyda saqlang."
    ),
    responses=_errors(
        (401, "Autentifikatsiya ma'lumoti yo'q yoki yaroqsiz"),
        (403, "API kalit bilan ruxsat etilmaydi yoki hisob faolsizlantirilgan"),
        (422, "Nom, ruxsatlar yoki muddat noto'g'ri; faol kalitlar limiti oshdi"),
    ),
)
async def create_api_key(
    data: ApiKeyCreate,
    user: JwtUser,
    svc: AuthSvc,
    response: Response,
) -> ApiKeyCreated:
    """Kalit yaratadi va xom qiymatini qaytaradi."""
    api_key, raw_key = await svc.create_api_key(user, data)
    # Xom kalit proxy yoki brauzer keshida qolmasligi kerak.
    response.headers["Cache-Control"] = NO_STORE
    # `include=` faqat E'LON QILINGAN maydonlarni oladi: `masked_key`,
    # `is_revoked`, `is_valid` — `computed_field`, ularni konstruktorga
    # uzatish mumkin emas.
    fields = ApiKeyRead.model_validate(api_key).model_dump(include=set(ApiKeyRead.model_fields))
    return ApiKeyCreated(**fields, key=raw_key)


@router.delete(
    "/{key_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="API kalitni bekor qilish",
    description=(
        "Kalitni bekor qiladi (`revoked_at` to'ldiriladi). Yozuv audit uchun "
        "saqlanadi, lekin kalit shu daqiqadan boshlab ishlamaydi."
    ),
    responses=_errors(
        (401, "Autentifikatsiya ma'lumoti yo'q yoki yaroqsiz"),
        (403, "API kalit bilan ruxsat etilmaydi yoki hisob faolsizlantirilgan"),
        (404, "Bunday kalit yo'q yoki boshqa foydalanuvchiga tegishli"),
    ),
)
async def revoke_api_key(
    user: JwtUser,
    svc: AuthSvc,
    key_id: Annotated[uuid.UUID, Path(description="Kalit identifikatori")],
) -> SuccessResponse:
    """Kalitni bekor qiladi."""
    await svc.revoke_api_key(user, key_id)
    return SuccessResponse(
        success=True,
        message="API kalit bekor qilindi",
        data={"api_key_id": str(key_id)},
    )


__all__ = ["router"]
