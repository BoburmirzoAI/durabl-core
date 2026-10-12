"""Durabl — `/webhooks` routeri: mijoz webhook'lari CRUD, sinov va tarix.

Webhook — job hodisalari (`job.succeeded`, `job.failed`, ...) mijozning
HTTP endpoint'iga yuboriladigan xabar. Har xabar `X-Durabl-Signature`
(`t=<ts>,v1=<hmac_sha256>`) bilan imzolanadi, shuning uchun mijoz uni
soxta so'rovdan ajrata oladi.

## Sirli kalit faqat BIR MARTA ko'rsatiladi

`POST /webhooks` javobi `WebhookCreated` — `secret` maydoni AYNAN shu
javobda qaytadi. `WebhookRead` da u YO'Q, ya'ni keyin hech qaysi endpoint
kalitni oshkor qilmaydi. Mijoz kalitni saqlamasa, yangi webhook yaratishi
kerak.

## `POST /{id}/test` — HAQIQIY tashqi so'rov

Sinov navbatga QO'YILMAYDI: Durabl mijozning URL'iga darhol `POST` qiladi
va natijani (HTTP kodi, davomiylik, javob tanasining boshi) qaytaradi.
Shu sababli endpoint sekin bo'lishi mumkin (`WEBHOOK_TIMEOUT_SECONDS`
gacha) va `consecutive_failures` hisoblagichiga TA'SIR QILMAYDI — "tekshirib
ko'rish" mijozning o'z webhook'ini o'chirib qo'yishiga olib kelmasligi kerak.

Qatlam qoidasi: biznes logika yo'q, `select()` yozilmaydi, `HTTPException`
tashlanmaydi — SSRF tekshiruvi ham, webhook soni chegarasi ham
`WebhookService` ichida.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Final

from fastapi import APIRouter, Body, Path, status

from app.dependencies import CurrentUser, Pagination, ScopeAdmin, WebhookSvc
from app.schemas.base import ErrorResponse, PaginatedResponse, SuccessResponse
from app.schemas.webhook import (
    WebhookCreate,
    WebhookCreated,
    WebhookDeliveryRead,
    WebhookRead,
    WebhookTestRequest,
    WebhookTestResponse,
    WebhookUpdate,
)

#: Butun router API kalit uchun `admin` doirasini talab qiladi.
#:
#: Webhook sozlamalari — frontend `admin` tavsifi bo'yicha.
#:
#: Darvoza ROUTER darajasida: yangi endpoint qo'shilganda u
#: avtomatik himoyalanadi va belgilashni unutib bo'lmaydi.
#: JWT bilan kirilganda scope tekshirilmaydi (`require_scope`).
router = APIRouter(
    prefix="/webhooks",
    tags=["webhooks"],
    dependencies=[ScopeAdmin],
)

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
        "description": "Webhook topilmadi (`WEBHOOK_NOT_FOUND`)",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": (
            "So'rov ma'lumoti noto'g'ri yoki URL ruxsat etilmagan "
            "(`VALIDATION_ERROR`, `WEBHOOK_URL_NOT_ALLOWED`)"
        ),
    },
}


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    """Berilgan kodlar uchun OpenAPI `responses` lug'atini yasaydi."""
    return {code: _ERRORS[code] for code in codes}


#: Yo'l parametri — barcha `{webhook_id}` endpointlarida bir xil ta'rif.
WebhookId = Annotated[uuid.UUID, Path(description="Webhook identifikatori")]


@router.get(
    "",
    response_model=PaginatedResponse[WebhookRead],
    status_code=status.HTTP_200_OK,
    summary="Webhook'lar ro'yxati",
    description=(
        "Foydalanuvchining barcha webhook'lari (yangisidan boshlab). "
        "`secret` qaytarilmaydi. Bitta hisobdagi webhook'lar soni servis "
        "darajasida cheklangani uchun ro'yxat qisqa bo'ladi."
    ),
    responses=_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
    ),
)
async def list_webhooks(
    user: CurrentUser,
    svc: WebhookSvc,
    pagination: Pagination,
) -> PaginatedResponse[WebhookRead]:
    """Webhook'larning sahifalangan ro'yxati.

    `WebhookService.list()` to'liq ro'yxatni qaytaradi (bitta foydalanuvchida
    ko'pi bilan `MAX_WEBHOOKS_PER_USER` ta yozuv bor), shuning uchun sahifa
    qo'shimcha SQL so'rovisiz shu ro'yxatdan kesiladi.
    """
    webhooks = await svc.list(user)
    window = webhooks[pagination.offset : pagination.offset + pagination.limit]
    return PaginatedResponse.from_params(
        [WebhookRead.model_validate(item) for item in window],
        total=len(webhooks),
        params=pagination,
    )


@router.post(
    "",
    response_model=WebhookCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Yangi webhook yaratish",
    description=(
        "Hodisalar yuboriladigan manzilni ro'yxatdan o'tkazadi. URL SSRF'ga "
        "qarshi tekshiriladi: `localhost`, xususiy tarmoq va cloud metadata "
        "manzillari 422 `WEBHOOK_URL_NOT_ALLOWED` bilan rad etiladi. "
        "Javobdagi `secret` boshqa hech qachon ko'rsatilmaydi — saqlab qoling."
    ),
    responses=_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)
async def create_webhook(
    user: CurrentUser,
    svc: WebhookSvc,
    data: WebhookCreate,
) -> WebhookCreated:
    """Webhook yaratadi va sirli kalit bilan qaytaradi."""
    webhook = await svc.create(user, data)
    return WebhookCreated.model_validate(webhook)


@router.get(
    "/{webhook_id}",
    response_model=WebhookRead,
    status_code=status.HTTP_200_OK,
    summary="Bitta webhook tafsiloti",
    description=(
        "Webhook sozlamasi va salomatligi: obuna bo'lingan hodisalar, "
        "oxirgi ishga tushish vaqti, ketma-ket xatolar soni va avtomatik "
        "o'chirilgan vaqt (`disabled_at`)."
    ),
    responses=_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
    ),
)
async def get_webhook(
    user: CurrentUser,
    svc: WebhookSvc,
    webhook_id: WebhookId,
) -> WebhookRead:
    """Bitta webhook (egalik tekshirilgan)."""
    webhook = await svc.get(user, webhook_id)
    return WebhookRead.model_validate(webhook)


@router.put(
    "/{webhook_id}",
    response_model=WebhookRead,
    status_code=status.HTTP_200_OK,
    summary="Webhook'ni yangilash",
    description=(
        "Faqat yuborilgan maydonlar o'zgaradi. URL o'zgarsa SSRF tekshiruvi "
        "qaytadan bajariladi. `is_active=true` yuborilsa avtomatik o'chirish "
        "holati va xato hisoblagichi ham tozalanadi."
    ),
    responses=_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)
async def update_webhook(
    user: CurrentUser,
    svc: WebhookSvc,
    webhook_id: WebhookId,
    data: WebhookUpdate,
) -> WebhookRead:
    """Webhook sozlamasini qismiy yangilaydi."""
    webhook = await svc.update(user, webhook_id, data)
    return WebhookRead.model_validate(webhook)


@router.delete(
    "/{webhook_id}",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Webhook'ni o'chirish",
    description=(
        "Webhook va uning yuborish tarixi (`webhook_deliveries`) birga "
        "o'chiriladi. Amal qaytarib bo'lmaydi — sirli kalit ham yo'qoladi."
    ),
    responses=_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
    ),
)
async def delete_webhook(
    user: CurrentUser,
    svc: WebhookSvc,
    webhook_id: WebhookId,
) -> SuccessResponse:
    """Webhook'ni o'chiradi."""
    await svc.delete(user, webhook_id)
    return SuccessResponse(
        message="Webhook o'chirildi",
        data={"webhook_id": str(webhook_id)},
    )


@router.post(
    "/{webhook_id}/test",
    response_model=WebhookTestResponse,
    status_code=status.HTTP_200_OK,
    summary="Sinov hodisasini DARHOL yuborish (tashqi HTTP so'rov)",
    description=(
        "Mijozning URL'iga navbatdan o'tmasdan, shu so'rov ichida haqiqiy "
        "`POST` qiladi — ya'ni javob mijoz serverining tezligiga bog'liq. "
        "Imzo, header'lar va tana shakli ishlab chiqarishdagi bilan aynan "
        "bir xil. Natija muvaffaqiyatsiz bo'lsa ham webhook o'chirilmaydi va "
        "xato hisoblagichi oshmaydi. Tana berilmasa namuna payload yuboriladi."
    ),
    responses=_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
    ),
)
async def test_webhook(
    user: CurrentUser,
    svc: WebhookSvc,
    webhook_id: WebhookId,
    data: Annotated[
        WebhookTestRequest | None,
        Body(description="Sinov parametrlari. Butunlay tashlab ketish mumkin."),
    ] = None,
) -> WebhookTestResponse:
    """Sinov hodisasini yuboradi va natijani qaytaradi.

    Tana IXTIYORIY: SDK'lar `POST /webhooks/{id}/test` ni tanasiz chaqiradi,
    shuning uchun berilmasa standart `WebhookTestRequest` ishlatiladi.
    """
    return await svc.test(user, webhook_id, data or WebhookTestRequest())


@router.get(
    "/{webhook_id}/deliveries",
    response_model=PaginatedResponse[WebhookDeliveryRead],
    status_code=status.HTTP_200_OK,
    summary="Webhook yuborish tarixi",
    description=(
        "Shu webhook uchun qilingan urinishlar: hodisa turi, holat, masofaviy "
        "HTTP kodi, javob tanasi (4 KB gacha), xato matni va keyingi qayta "
        "urinish vaqti. Sinov yuborishlari ham shu tarixda ko'rinadi "
        "(`job_id` bo'sh bo'ladi)."
    ),
    responses=_responses(
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_403_FORBIDDEN,
        status.HTTP_404_NOT_FOUND,
    ),
)
async def list_webhook_deliveries(
    user: CurrentUser,
    svc: WebhookSvc,
    pagination: Pagination,
    webhook_id: WebhookId,
) -> PaginatedResponse[WebhookDeliveryRead]:
    """Yuborish tarixining sahifalangan ro'yxati."""
    items, total = await svc.deliveries(user, webhook_id, pagination)
    return PaginatedResponse.from_params(
        [WebhookDeliveryRead.model_validate(item) for item in items],
        total=total,
        params=pagination,
    )


__all__ = ["router"]
