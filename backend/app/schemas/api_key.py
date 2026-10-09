"""Durabl — API kalit schema'lari.

Xavfsizlik qoidasi: xom API kalit (`durabl_...`) **faqat yaratish javobida**
(`ApiKeyCreated.key`) bir marta ko'rsatiladi. DB'da uning SHA-256 hash'i
saqlanadi, shuning uchun qayta ko'rsatish imkonsiz. Keyingi barcha javoblarda
faqat `key_prefix` + `last_four` (niqoblangan ko'rinish) qaytadi.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import Field, computed_field, field_validator

from app.schemas.base import DurablSchema, ORMSchema
from app.utils.time_utils import ensure_utc, is_expired, utcnow

#: Kalit nomining maksimal uzunligi (`api_keys.name` ustuni bilan mos).
MAX_API_KEY_NAME_LENGTH = 100

#: Bitta kalitga berilishi mumkin bo'lgan ruxsatlar (scope) soni.
MAX_API_KEY_SCOPES = 32


class ApiKeyCreate(DurablSchema):
    """`POST /api-keys` — yangi kalit yaratish."""

    name: Annotated[str, Field(min_length=1, max_length=MAX_API_KEY_NAME_LENGTH)] = Field(
        description="Kalitni ajratish uchun nom (masalan `ci-pipeline`)",
        examples=["ci-pipeline"],
    )
    scopes: list[Annotated[str, Field(min_length=1, max_length=64)]] | None = Field(
        default=None,
        description=("Ruxsatlar ro'yxati. Berilmasa kalit egasining barcha huquqlarini oladi."),
        examples=[["jobs:write", "jobs:read"]],
    )
    expires_at: datetime | None = Field(
        default=None,
        description="Kalit amal qilish muddati (ISO-8601, UTC). Berilmasa cheksiz.",
    )

    @field_validator("scopes")
    @classmethod
    def _check_scopes(cls, value: list[str] | None) -> list[str] | None:
        """Ruxsatlar sonini tekshiradi va takrorlanishni olib tashlaydi."""
        if value is None:
            return None
        unique: list[str] = []
        for scope in value:
            if scope not in unique:
                unique.append(scope)
        if len(unique) > MAX_API_KEY_SCOPES:
            raise ValueError(f"Ruxsatlar soni {MAX_API_KEY_SCOPES} dan oshmasligi kerak")
        return unique

    @field_validator("expires_at")
    @classmethod
    def _check_expires_at(cls, value: datetime | None) -> datetime | None:
        """Muddat kelajakda bo'lishi shart."""
        if value is None:
            return None
        moment = ensure_utc(value)
        assert moment is not None  # ensure_utc faqat None uchun None qaytaradi
        if moment <= utcnow():
            raise ValueError("`expires_at` kelajakda bo'lishi kerak")
        return value


class ApiKeyRead(ORMSchema):
    """API kalit ma'lumoti — xom kalit BO'LMAYDI."""

    id: uuid.UUID = Field(description="Kalit identifikatori")
    user_id: uuid.UUID = Field(description="Egasi — foydalanuvchi identifikatori")
    name: str = Field(description="Kalit nomi")
    key_prefix: str = Field(
        description="Kalitning boshlang'ich qismi (`durabl_ab12...`) — tanib olish uchun"
    )
    last_four: str = Field(description="Kalitning oxirgi to'rt belgisi")
    scopes: list[str] = Field(default_factory=list, description="Berilgan ruxsatlar")
    last_used_at: datetime | None = Field(
        default=None, description="Oxirgi marta ishlatilgan vaqt (UTC)"
    )
    expires_at: datetime | None = Field(
        default=None, description="Amal qilish muddati (UTC); `null` — cheksiz"
    )
    revoked_at: datetime | None = Field(
        default=None, description="Bekor qilingan vaqt (UTC); `null` — bekor qilinmagan"
    )
    created_at: datetime = Field(description="Yaratilgan vaqt (UTC)")
    updated_at: datetime | None = Field(default=None, description="Oxirgi o'zgartirish vaqti (UTC)")

    @computed_field(description="Niqoblangan ko'rinish — UI'da ko'rsatish uchun")  # type: ignore[prop-decorator]
    @property
    def masked_key(self) -> str:
        """`durabl_ab12...cd34` ko'rinishi."""
        return f"{self.key_prefix}...{self.last_four}"

    @computed_field(description="Kalit bekor qilinganmi")  # type: ignore[prop-decorator]
    @property
    def is_revoked(self) -> bool:
        """`revoked_at` to'ldirilgan bo'lsa `True`."""
        return self.revoked_at is not None

    @computed_field(description="Kalit hozir ishlatilishi mumkinmi")  # type: ignore[prop-decorator]
    @property
    def is_valid(self) -> bool:
        """Bekor qilinmagan va muddati o'tmagan bo'lsa `True`."""
        return self.revoked_at is None and not is_expired(self.expires_at)


class ApiKeyCreated(ApiKeyRead):
    """`POST /api-keys` javobi — xom kalit FAQAT shu yerda ko'rsatiladi."""

    key: str = Field(
        description=(
            "To'liq API kalit (`durabl_...`). Bu qiymat boshqa hech qachon "
            "qaytarilmaydi — xavfsiz joyda saqlang."
        ),
        examples=["durabl_sXq7...uZ2k"],
    )


__all__ = [
    "MAX_API_KEY_NAME_LENGTH",
    "MAX_API_KEY_SCOPES",
    "ApiKeyCreate",
    "ApiKeyCreated",
    "ApiKeyRead",
]
