"""Durabl — autentifikatsiya va foydalanuvchi schema'lari.

Bu modul `/api/v1/auth/*` endpointlari uchun so'rov va javob shakllarini
belgilaydi: ro'yxatdan o'tish, kirish, token yangilash va parol o'zgartirish.

Parol kuchini tekshirish ikki joyda bajariladi:

* Shu yerda (schema) — mijozga darhol 422 javobi qaytishi uchun;
* `app.utils.security.validate_password_strength` — service qatlamida yakuniy
  himoya sifatida. Qoidalar bir xil (`settings.PASSWORD_MIN_LENGTH`).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import EmailStr, Field, field_validator, model_validator

from app.config import settings
from app.schemas.base import DurablSchema, ORMSchema

# Parol maydonining umumiy turi — minimal uzunlik sozlamadan olinadi.
PasswordStr = Annotated[
    str,
    Field(
        min_length=settings.PASSWORD_MIN_LENGTH,
        max_length=256,
        description=(
            f"Parol: kamida {settings.PASSWORD_MIN_LENGTH} belgi, kamida bitta harf va bitta raqam"
        ),
    ),
]


def _assert_password_strength(password: str) -> str:
    """Parol minimal talablarga javob beradimi (pydantic uchun `ValueError`)."""
    violations: list[str] = []
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        violations.append(f"kamida {settings.PASSWORD_MIN_LENGTH} belgi bo'lishi kerak")
    if not any(char.isalpha() for char in password):
        violations.append("kamida bitta harf bo'lishi kerak")
    if not any(char.isdigit() for char in password):
        violations.append("kamida bitta raqam bo'lishi kerak")
    if violations:
        raise ValueError("Parol talablarga javob bermaydi: " + ", ".join(violations))
    return password


# ---------------------------------------------------------------------------
# So'rovlar
# ---------------------------------------------------------------------------


class RegisterRequest(DurablSchema):
    """`POST /auth/register` — yangi foydalanuvchi yaratish."""

    email: EmailStr = Field(
        max_length=320,
        description="Elektron pochta — tizimdagi yagona identifikator",
        examples=["dev@durabl.dev"],
    )
    password: PasswordStr
    full_name: Annotated[str, Field(max_length=255)] | None = Field(
        default=None,
        description="Foydalanuvchining to'liq ismi (majburiy emas)",
        examples=["Alisher Navoiy"],
    )

    @field_validator("password")
    @classmethod
    def _check_password(cls, value: str) -> str:
        """Parol kuchini tekshiradi."""
        return _assert_password_strength(value)


class LoginRequest(DurablSchema):
    """`POST /auth/login` — email va parol bilan kirish."""

    email: EmailStr = Field(
        max_length=320,
        description="Ro'yxatdan o'tgan elektron pochta",
        examples=["dev@durabl.dev"],
    )
    password: Annotated[str, Field(min_length=1, max_length=256)] = Field(
        description="Foydalanuvchi paroli (xom holda, faqat TLS orqali)",
    )


class RefreshRequest(DurablSchema):
    """`POST /auth/refresh` — refresh token orqali yangi juftlik olish."""

    refresh_token: Annotated[str, Field(min_length=10, max_length=4096)] = Field(
        description="Avval berilgan refresh JWT",
    )


class PasswordChangeRequest(DurablSchema):
    """`POST /auth/change-password` — joriy parolni bilgan holda almashtirish."""

    current_password: Annotated[str, Field(min_length=1, max_length=256)] = Field(
        description="Hozirgi parol — egalikni tasdiqlash uchun",
    )
    new_password: PasswordStr = Field(description="Yangi parol")

    @field_validator("new_password")
    @classmethod
    def _check_new_password(cls, value: str) -> str:
        """Yangi parol kuchini tekshiradi."""
        return _assert_password_strength(value)

    @model_validator(mode="after")
    def _check_different(self) -> PasswordChangeRequest:
        """Yangi parol eskisidan farq qilishi shart."""
        if self.current_password == self.new_password:
            raise ValueError("Yangi parol joriy paroldan farq qilishi kerak")
        return self


class UserUpdate(DurablSchema):
    """`PUT /auth/me` — profil ma'lumotlarini o'zgartirish.

    Hozircha faqat `full_name` o'zgaradi. Email — tizimdagi yagona
    identifikator (uni almashtirish pochtani tasdiqlash oqimini talab
    qiladi), parol esa alohida `POST /auth/change-password` orqali
    almashtiriladi.

    Maydon `null` qilib yuborilsa ism TOZALANADI; umuman yuborilmasa ham
    natija ayni shu (PUT semantikasi — profil to'liq almashtiriladi).
    """

    full_name: Annotated[str, Field(max_length=255)] | None = Field(
        default=None,
        description="To'liq ism; `null` berilsa ism tozalanadi",
        examples=["Alisher Navoiy"],
    )


# ---------------------------------------------------------------------------
# Javoblar
# ---------------------------------------------------------------------------


class TokenResponse(ORMSchema):
    """Kirish va token yangilash javobi — JWT juftligi."""

    access_token: str = Field(description="Qisqa muddatli access JWT")
    refresh_token: str = Field(description="Uzoq muddatli refresh JWT")
    token_type: Literal["bearer"] = Field(
        default="bearer",
        description="`Authorization: Bearer <access_token>` sxemasi",
    )
    expires_in: Annotated[int, Field(ge=1)] = Field(
        default=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        description="Access token amal qilish muddati (soniya)",
    )


class UserRead(ORMSchema):
    """Foydalanuvchi ma'lumoti — `GET /auth/me` va boshqa javoblarda."""

    id: uuid.UUID = Field(description="Foydalanuvchi identifikatori")
    email: str = Field(description="Elektron pochta")
    full_name: str | None = Field(default=None, description="To'liq ism")
    is_active: bool = Field(description="Hisob faolmi (bloklanmaganmi)")
    is_admin: bool = Field(description="Administrator huquqi bormi")
    last_login_at: datetime | None = Field(
        default=None, description="Oxirgi muvaffaqiyatli kirish vaqti (UTC)"
    )
    created_at: datetime = Field(description="Hisob yaratilgan vaqt (UTC)")
    updated_at: datetime | None = Field(default=None, description="Oxirgi o'zgartirish vaqti (UTC)")


__all__ = [
    "LoginRequest",
    "PasswordChangeRequest",
    "PasswordStr",
    "RefreshRequest",
    "RegisterRequest",
    "TokenResponse",
    "UserRead",
    "UserUpdate",
]
