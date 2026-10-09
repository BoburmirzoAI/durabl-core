"""Durabl — WebSocket xabar schema'lari (`/ws/jobs`).

Frontend shartnomasi: serverdan keladigan har bir xabar `{ type, data,
timestamp }` shaklida (`WsEvent`). Xatolar ham shu konvertning maxsus turi
(`WsErrorMessage`, `type="error"`).

Mijozdan keladigan yagona xabar — obuna boshqaruvi (`WsSubscribeMessage`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Final, Literal

from pydantic import Field, field_validator, model_validator

from app.constants import WebhookEvent
from app.schemas.base import DurablSchema, ORMSchema
from app.utils.time_utils import utcnow

#: Bitta obuna xabarida ko'rsatilishi mumkin bo'lgan job'lar soni.
MAX_WS_SUBSCRIBE_JOBS = 100

#: Mijoz yuborishi mumkin bo'lgan amallar.
WsAction = Literal["subscribe", "unsubscribe", "ping"]

#: Xizmat xabarlari turi — job hodisalaridan tashqari.
#: `Final` MAJBURIY: `WsErrorMessage.type` maydoni `Literal["error"]`, va
#: `Final` bo'lmasa tur tekshiruvchi konstantani oddiy `str` deb biladi
#: (`Field(default=WS_TYPE_ERROR)` uchun `arg-type` xatosi chiqardi).
WS_TYPE_ERROR: Final = "error"
WS_TYPE_PONG: Final = "pong"
WS_TYPE_SUBSCRIBED: Final = "subscribed"


class WsEvent(ORMSchema):
    """Serverdan mijozga yuboriladigan hodisa konverti."""

    type: str = Field(
        description=(
            "Hodisa turi — `WebhookEvent` qiymatlari (`job.succeeded`, `job.failed`...) "
            "yoki xizmat turi (`pong`, `subscribed`, `error`)"
        ),
        examples=[WebhookEvent.JOB_SUCCEEDED.value],
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Hodisa tanasi — job uchun `serializers.job_event_payload(job)` natijasi",
    )
    timestamp: datetime = Field(
        default_factory=utcnow, description="Hodisa yuborilgan vaqt (ISO-8601, UTC)"
    )

    @classmethod
    def for_job(cls, event: WebhookEvent | str, payload: dict[str, Any]) -> WsEvent:
        """Job hodisasidan konvert yasaydi."""
        return cls(type=str(event), data=payload)


class WsSubscribeMessage(DurablSchema):
    """Mijozdan keladigan obuna boshqaruvi xabari."""

    action: WsAction = Field(
        description="Amal: `subscribe`, `unsubscribe` yoki `ping`",
        examples=["subscribe"],
    )
    job_ids: Annotated[list[uuid.UUID], Field(max_length=MAX_WS_SUBSCRIBE_JOBS)] | None = Field(
        default=None,
        description=(
            "Faqat shu job'lar hodisalari yuborilsin. "
            "Berilmasa — foydalanuvchining barcha job'lari."
        ),
    )
    events: list[WebhookEvent] | None = Field(
        default=None,
        description="Faqat shu hodisa turlari yuborilsin. Berilmasa — hammasi.",
    )

    @field_validator("job_ids", "events")
    @classmethod
    def _drop_empty(cls, value: list[Any] | None) -> list[Any] | None:
        """Bo'sh ro'yxatni `None` ga aylantiradi ("filtrsiz" ma'nosi)."""
        if value is None or len(value) == 0:
            return None
        unique: list[Any] = []
        for item in value:
            if item not in unique:
                unique.append(item)
        return unique

    @model_validator(mode="after")
    def _check_action(self) -> WsSubscribeMessage:
        """`ping` xabarida filtrlar ma'noga ega emas."""
        if self.action == "ping" and (self.job_ids is not None or self.events is not None):
            raise ValueError("`ping` xabarida `job_ids` va `events` berilmaydi")
        return self


class WsErrorMessage(ORMSchema):
    """Serverdan mijozga yuboriladigan xato xabari."""

    type: Literal["error"] = Field(
        default=WS_TYPE_ERROR, description="Har doim `error` — mijoz shu bo'yicha ajratadi"
    )
    code: str = Field(
        description="Mashina o'qiydigan barqaror xato kodi",
        examples=["ws_connection_limit"],
    )
    message: str = Field(
        description="Inson o'qiydigan xabar (o'zbekcha)",
        examples=["Bir vaqtda ruxsat etilgan ulanishlar soni oshdi"],
    )
    details: dict[str, Any] | None = Field(default=None, description="Qo'shimcha kontekst")
    timestamp: datetime = Field(
        default_factory=utcnow, description="Xato yuzaga kelgan vaqt (ISO-8601, UTC)"
    )


__all__ = [
    "MAX_WS_SUBSCRIBE_JOBS",
    "WS_TYPE_ERROR",
    "WS_TYPE_PONG",
    "WS_TYPE_SUBSCRIBED",
    "WsAction",
    "WsErrorMessage",
    "WsEvent",
    "WsSubscribeMessage",
]
