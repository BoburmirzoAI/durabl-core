"""Durabl — webhook sozlamalari va yuborish tarixi schema'lari.

Xavfsizlik qoidasi: webhook **sirli kaliti** (`secret`) faqat yaratish
javobida (`WebhookCreated`) bir marta ko'rsatiladi. `WebhookRead` da u
BO'LMAYDI — mijoz kalitni saqlab qolishi, aks holda yangisini yaratishi kerak.

URL ning to'liq tekshiruvi (SSRF, xususiy IP bloklash) `utils.validators.
validate_webhook_url`da — bu yerda faqat sxema va uzunlik nazorat qilinadi.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import Field, computed_field, field_validator, model_validator

from app.config import settings
from app.constants import DeliveryStatus, WebhookEvent
from app.schemas.base import DurablSchema, ORMSchema

#: Webhook URL ning maksimal uzunligi (`webhooks.url` ustuni bilan mos).
MAX_WEBHOOK_URL_LENGTH = 2_048

#: Test javob tanasining ko'rsatiladigan qismi (bayt).
MAX_TEST_RESPONSE_BODY = 4_096


def _assert_url_scheme(url: str) -> str:
    """URL sxemasi ruxsat etilganlar ro'yxatida ekanini tekshiradi."""
    scheme, separator, remainder = url.partition("://")
    if not separator or not remainder:
        raise ValueError("URL to'liq bo'lishi kerak, masalan `https://example.com/hook`")
    allowed = [item.lower() for item in settings.WEBHOOK_ALLOWED_SCHEMES]
    if scheme.lower() not in allowed:
        raise ValueError(f"URL sxemasi ruxsat etilmagan; ruxsat etilgan: {', '.join(allowed)}")
    return url


def _assert_unique_events(events: list[WebhookEvent]) -> list[WebhookEvent]:
    """Hodisalar takrorlanmasligini ta'minlaydi (tartib saqlanadi)."""
    unique: list[WebhookEvent] = []
    for event in events:
        if event not in unique:
            unique.append(event)
    return unique


# ---------------------------------------------------------------------------
# So'rovlar
# ---------------------------------------------------------------------------


class WebhookCreate(DurablSchema):
    """`POST /webhooks` — yangi webhook ro'yxatdan o'tkazish."""

    url: Annotated[str, Field(min_length=8, max_length=MAX_WEBHOOK_URL_LENGTH)] = Field(
        description="Hodisalar POST qilinadigan manzil",
        examples=["https://example.com/durabl/hook"],
    )
    events: Annotated[list[WebhookEvent], Field(min_length=1)] = Field(
        description="Obuna bo'linadigan hodisalar ro'yxati",
        examples=[[WebhookEvent.JOB_SUCCEEDED.value, WebhookEvent.JOB_FAILED.value]],
    )
    description: Annotated[str, Field(max_length=255)] | None = Field(
        default=None, description="Erkin izoh (nima uchun kerakligi)"
    )
    is_active: bool = Field(default=True, description="Yaratilgandan so'ng darhol faol bo'lsinmi")
    secret: Annotated[str, Field(min_length=16, max_length=128)] | None = Field(
        default=None,
        description=(
            "Imzo uchun sirli kalit. Berilmasa Durabl xavfsiz tasodifiy kalit yasaydi "
            "va javobda bir marta ko'rsatadi."
        ),
    )

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        """URL sxemasini tekshiradi."""
        return _assert_url_scheme(value)

    @field_validator("events")
    @classmethod
    def _check_events(cls, value: list[WebhookEvent]) -> list[WebhookEvent]:
        """Takrorlangan hodisalarni olib tashlaydi."""
        return _assert_unique_events(value)


class WebhookUpdate(DurablSchema):
    """`PUT /webhooks/{id}` — qismiy yangilash (faqat berilgan maydonlar)."""

    url: Annotated[str, Field(min_length=8, max_length=MAX_WEBHOOK_URL_LENGTH)] | None = Field(
        default=None, description="Yangi manzil"
    )
    events: Annotated[list[WebhookEvent], Field(min_length=1)] | None = Field(
        default=None, description="Yangi hodisalar ro'yxati (to'liq almashtiradi)"
    )
    description: Annotated[str, Field(max_length=255)] | None = Field(
        default=None, description="Yangi izoh"
    )
    is_active: bool | None = Field(default=None, description="Faollikni yoqish yoki o'chirish")

    @field_validator("url")
    @classmethod
    def _check_url(cls, value: str | None) -> str | None:
        """URL berilgan bo'lsa sxemasini tekshiradi."""
        return None if value is None else _assert_url_scheme(value)

    @field_validator("events")
    @classmethod
    def _check_events(cls, value: list[WebhookEvent] | None) -> list[WebhookEvent] | None:
        """Takrorlangan hodisalarni olib tashlaydi."""
        return None if value is None else _assert_unique_events(value)

    @model_validator(mode="after")
    def _check_not_empty(self) -> WebhookUpdate:
        """Kamida bitta maydon berilishi shart."""
        if not self.model_fields_set:
            raise ValueError("Yangilash uchun kamida bitta maydon berilishi kerak")
        return self


class WebhookTestRequest(DurablSchema):
    """`POST /webhooks/{id}/test` — sinov hodisasini yuborish."""

    event: WebhookEvent = Field(
        default=WebhookEvent.JOB_SUCCEEDED,
        description="Sinovda yuboriladigan hodisa turi",
    )
    payload: dict[str, Any] | None = Field(
        default=None,
        description="Maxsus sinov tanasi. Berilmasa Durabl namuna payload yasaydi.",
    )


# ---------------------------------------------------------------------------
# Javoblar
# ---------------------------------------------------------------------------


class WebhookRead(ORMSchema):
    """Webhook sozlamasi — `secret` QAYTARILMAYDI."""

    id: uuid.UUID = Field(description="Webhook identifikatori")
    user_id: uuid.UUID = Field(description="Egasi — foydalanuvchi identifikatori")
    url: str = Field(description="Hodisalar yuboriladigan manzil")
    events: list[WebhookEvent] = Field(
        default_factory=list, description="Obuna bo'lingan hodisalar"
    )
    is_active: bool = Field(default=True, description="Webhook faolmi")
    description: str | None = Field(default=None, description="Erkin izoh")
    last_triggered_at: datetime | None = Field(
        default=None, description="Oxirgi marta ishga tushgan vaqt (UTC)"
    )
    consecutive_failures: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Ketma-ket muvaffaqiyatsiz urinishlar soni"
    )
    disabled_at: datetime | None = Field(
        default=None,
        description="Ko'p xatolik sababli avtomatik o'chirilgan vaqt (UTC)",
    )
    created_at: datetime = Field(description="Yaratilgan vaqt (UTC)")
    updated_at: datetime | None = Field(default=None, description="Oxirgi o'zgartirish vaqti (UTC)")

    @computed_field(description="Xatolik sababli avtomatik o'chirilganmi")  # type: ignore[prop-decorator]
    @property
    def is_disabled(self) -> bool:
        """`disabled_at` to'ldirilgan bo'lsa `True`."""
        return self.disabled_at is not None


class WebhookCreated(WebhookRead):
    """`POST /webhooks` javobi — sirli kalit FAQAT shu yerda ko'rsatiladi."""

    secret: str = Field(
        description=(
            "Imzo kaliti (`X-Durabl-Signature` ni tekshirish uchun). "
            "Bu qiymat boshqa hech qachon qaytarilmaydi — saqlab qoling."
        )
    )


class WebhookTestResponse(ORMSchema):
    """Sinov yuborish natijasi."""

    success: bool = Field(description="Yuborish muvaffaqiyatli bo'ldimi (2xx javob)")
    event: WebhookEvent = Field(description="Yuborilgan hodisa turi")
    status_code: int | None = Field(
        default=None, description="Masofaviy server qaytargan HTTP kodi"
    )
    duration_ms: Annotated[int, Field(ge=0)] = Field(
        default=0, description="So'rov davomiyligi (ms)"
    )
    response_body: Annotated[str, Field(max_length=MAX_TEST_RESPONSE_BODY)] | None = Field(
        default=None, description="Javob tanasining boshlang'ich qismi (kesilgan)"
    )
    error: str | None = Field(default=None, description="Tarmoq yoki boshqa xato matni")
    sent_at: datetime | None = Field(default=None, description="Yuborilgan vaqt (UTC)")


class WebhookDeliveryRead(ORMSchema):
    """Bitta webhook yuborish urinishi (tarix yozuvi)."""

    id: uuid.UUID = Field(description="Yuborish yozuvi identifikatori")
    webhook_id: uuid.UUID = Field(description="Qaysi webhook")
    job_id: uuid.UUID | None = Field(default=None, description="Tegishli job (bo'lsa)")
    event: WebhookEvent = Field(description="Hodisa turi")
    status: DeliveryStatus = Field(description="Yuborish holati")
    attempt: Annotated[int, Field(ge=1)] = Field(default=1, description="Urinish tartib raqami")
    response_code: int | None = Field(default=None, description="Masofaviy HTTP kodi")
    response_body: str | None = Field(
        default=None, description="Javob tanasi (4 KB gacha kesilgan)"
    )
    error_message: str | None = Field(default=None, description="Xato matni (bo'lsa)")
    payload: dict[str, Any] | None = Field(default=None, description="Yuborilgan tana (JSON)")
    next_retry_at: datetime | None = Field(
        default=None, description="Keyingi qayta urinish vaqti (UTC)"
    )
    delivered_at: datetime | None = Field(
        default=None, description="Muvaffaqiyatli yetib borgan vaqt (UTC)"
    )
    duration_ms: int | None = Field(default=None, description="So'rov davomiyligi (ms)")
    created_at: datetime = Field(description="Yozuv yaratilgan vaqt (UTC)")
    updated_at: datetime | None = Field(default=None, description="Oxirgi o'zgartirish vaqti (UTC)")


__all__ = [
    "MAX_TEST_RESPONSE_BODY",
    "MAX_WEBHOOK_URL_LENGTH",
    "WebhookCreate",
    "WebhookCreated",
    "WebhookDeliveryRead",
    "WebhookRead",
    "WebhookTestRequest",
    "WebhookTestResponse",
    "WebhookUpdate",
]
