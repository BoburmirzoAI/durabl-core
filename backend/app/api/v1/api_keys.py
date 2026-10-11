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
from app.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyExpiryUpdate,
    ApiKeyRead,
    ApiKeyRotation,
    ApiKeyScopesUpdate,
)
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


#: Yo'l parametri — barcha bitta kalitga murojaat qiladigan yo'llarda.
KeyId = Annotated[uuid.UUID, Path(description="Kalit identifikatori")]

#: Bitta kalitga murojaat qiladigan yo'llardagi umumiy xatolar.
_KEY_ERRORS: tuple[tuple[int, str], ...] = (
    (401, "Autentifikatsiya ma'lumoti yo'q yoki yaroqsiz"),
    (403, "API kalit bilan ruxsat etilmaydi yoki hisob faolsizlantirilgan"),
    (404, "Bunday kalit yo'q yoki boshqa foydalanuvchiga tegishli"),
)


@router.get(
    "/{key_id}",
    response_model=ApiKeyRead,
    status_code=status.HTTP_200_OK,
    summary="Bitta API kalit",
    description=(
        "Kalit tafsiloti — xom qiymat QAYTARILMAYDI (u faqat yaratilgan va "
        "almashtirilgan paytda bir marta ko'rsatiladi)."
    ),
    responses=_errors(*_KEY_ERRORS),
)
async def get_api_key(user: JwtUser, svc: AuthSvc, key_id: KeyId) -> ApiKeyRead:
    """Bitta kalitni qaytaradi."""
    return ApiKeyRead.model_validate(await svc.get_api_key(user, key_id))


@router.put(
    "/{key_id}/scopes",
    response_model=ApiKeyRead,
    status_code=status.HTTP_200_OK,
    summary="Kalit huquqlarini o'zgartirish",
    description=(
        "Ruxsatlar ro'yxatini BUTUNLAY almashtiradi (qo'shmaydi). Bekor "
        "qilingan kalit uchun 409.\n\n"
        "Diqqat: scope'lar hozircha saqlanadi, lekin endpointlar tomonidan "
        "MAJBURLANMAYDI — `jobs:read` bergan kalit ham to'liq huquqqa ega."
    ),
    responses=_errors(
        *_KEY_ERRORS,
        (409, "Kalit bekor qilingan"),
        (422, "Ruxsatlar ro'yxati noto'g'ri"),
    ),
)
async def update_api_key_scopes(
    user: JwtUser,
    svc: AuthSvc,
    key_id: KeyId,
    data: ApiKeyScopesUpdate,
) -> ApiKeyRead:
    """Kalit huquqlarini almashtiradi."""
    return ApiKeyRead.model_validate(await svc.update_api_key_scopes(user, key_id, data.scopes))


@router.put(
    "/{key_id}/expiry",
    response_model=ApiKeyRead,
    status_code=status.HTTP_200_OK,
    summary="Kalit muddatini o'zgartirish",
    description=(
        "Muddatni uzaytiradi, qisqartiradi yoki butunlay olib tashlaydi "
        "(`expires_at: null`). O'tmishdagi vaqt rad etiladi — kalitni darhol "
        "to'xtatish uchun `DELETE /api-keys/{id}` ishlatiladi."
    ),
    responses=_errors(
        *_KEY_ERRORS,
        (409, "Kalit bekor qilingan"),
        (422, "Muddat o'tmishda"),
    ),
)
async def update_api_key_expiry(
    user: JwtUser,
    svc: AuthSvc,
    key_id: KeyId,
    data: ApiKeyExpiryUpdate,
) -> ApiKeyRead:
    """Kalit muddatini o'zgartiradi."""
    return ApiKeyRead.model_validate(await svc.update_api_key_expiry(user, key_id, data.expires_at))


@router.post(
    "/{key_id}/rotate",
    response_model=ApiKeyRotation,
    status_code=status.HTTP_200_OK,
    summary="API kalitni almashtirish",
    description=(
        "Kalit qiymatini JOYIDA almashtiradi: `id`, nom va huquqlar "
        "saqlanadi. Eski kalit darhol o'lmaydi — unga qisqa grace muddati "
        "beriladi, shunda mijoz yangi kalitni CI, server va lokal muhitga "
        "tarqatib ulguradi.\n\n"
        "Kalit HAQIQATAN sizib ketgan bo'lsa, rotatsiya emas, "
        "`DELETE /api-keys/{id}` ishlatiladi — u grace bermaydi."
    ),
    responses=_errors(
        *_KEY_ERRORS,
        (409, "Kalit bekor qilingan"),
    ),
)
async def rotate_api_key(user: JwtUser, svc: AuthSvc, key_id: KeyId) -> ApiKeyRotation:
    """Kalitni almashtiradi va YANGI xom qiymatni bir marta qaytaradi."""
    api_key, raw_key = await svc.rotate_api_key(user, key_id)
    # `rotated_at` va `previous_key_expires_at` `rotate_api_key()` da
    # birga yoziladi, ya'ni ikkisi ham to'ldirilgan bo'lishi KAFOLATLI.
    assert api_key.rotated_at is not None
    assert api_key.previous_key_expires_at is not None
    return ApiKeyRotation(
        key_id=api_key.id,
        key=raw_key,
        masked_key=api_key.masked,
        rotated_at=api_key.rotated_at,
        old_key_valid_until=api_key.previous_key_expires_at,
    )


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
