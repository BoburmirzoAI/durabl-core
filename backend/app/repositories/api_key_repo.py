"""Durabl — `api_keys` jadvali uchun repository.

API kalit autentifikatsiyasi eng tez-tez bajariladigan so'rov, shuning uchun
qidiruv faqat `key_hash` unique indeksi bo'yicha boradi (xom kalit DB'da
saqlanmaydi — `app.utils.security.hash_api_key()` hash'i izlanadi).

`User` bog'lanishi modellarda `lazy="raise"` bo'lgani uchun, kalit bilan birga
egasini olish kerak bo'lsa `get_by_hash(..., with_user=True)` chaqiriladi —
u `selectinload(ApiKey.user)` qo'shadi (`AuthService.resolve_api_key` shundan
foydalanadi).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import selectinload

from app.models.api_key import ApiKey
from app.repositories.base import BaseRepository
from app.utils.time_utils import utcnow


class ApiKeyRepository(BaseRepository[ApiKey]):
    """API kalitlar bilan ishlash qatlami."""

    model = ApiKey

    # ------------------------------------------------------------------
    # O'qish
    # ------------------------------------------------------------------

    async def get_by_hash(self, key_hash: str, *, with_user: bool = False) -> ApiKey | None:
        """Hash bo'yicha kalit; `with_user=True` bo'lsa egasi ham yuklanadi.

        Kalitning yaroqliligini (`is_valid`) repository tekshirmaydi — bu
        `AuthService` vazifasi, chunki bekor qilingan kalit uchun boshqa xato
        qaytarilishi kerak.
        """
        stmt: Select[Any] = select(ApiKey).where(ApiKey.key_hash == key_hash).limit(1)
        if with_user:
            stmt = stmt.options(selectinload(ApiKey.user))
        result = await self._execute(stmt)
        return result.scalars().first()

    async def list_for_user(
        self,
        user_id: uuid.UUID | str,
        include_revoked: bool = False,
    ) -> list[ApiKey]:
        """Foydalanuvchining kalitlari (yangisi birinchi).

        `include_revoked=False` — bekor qilingan kalitlar ro'yxatга kirmaydi.
        """
        conditions: list[Any] = [ApiKey.user_id == self._coerce_id(user_id)]
        if not include_revoked:
            conditions.append(ApiKey.revoked_at.is_(None))
        stmt = select(ApiKey).where(*conditions).order_by(ApiKey.created_at.desc())
        result = await self._execute(stmt)
        return list(result.scalars().all())

    async def get_for_user(
        self,
        key_id: uuid.UUID | str,
        user_id: uuid.UUID | str,
    ) -> ApiKey | None:
        """Kalitni egasi bilan birga tekshirib oladi (boshqa mijoz kalitiga kirmaslik uchun)."""
        stmt = (
            select(ApiKey)
            .where(
                ApiKey.id == self._coerce_id(key_id),
                ApiKey.user_id == self._coerce_id(user_id),
            )
            .limit(1)
        )
        result = await self._execute(stmt)
        return result.scalars().first()

    async def count_active(self, user_id: uuid.UUID | str) -> int:
        """Foydalanuvchining amalda ishlaydigan kalitlari soni.

        Amalda ishlaydigan = bekor qilinmagan va muddati o'tmagan.
        """
        now = utcnow()
        stmt = (
            select(func.count())
            .select_from(ApiKey)
            .where(
                ApiKey.user_id == self._coerce_id(user_id),
                ApiKey.revoked_at.is_(None),
                or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > now),
            )
        )
        result = await self._execute(stmt)
        return int(result.scalar_one() or 0)

    async def list_expired(self, now: datetime | None = None, limit: int = 100) -> list[ApiKey]:
        """Muddati o'tgan, lekin hali bekor qilinmagan kalitlar (tozalash uchun)."""
        moment = now or utcnow()
        stmt = (
            select(ApiKey)
            .where(
                ApiKey.revoked_at.is_(None),
                ApiKey.expires_at.is_not(None),
                ApiKey.expires_at <= moment,
            )
            .order_by(ApiKey.expires_at.asc())
            .limit(limit)
        )
        result = await self._execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Yozish
    # ------------------------------------------------------------------

    async def revoke(self, api_key: ApiKey) -> ApiKey:
        """Kalitni bekor qiladi. Allaqachon bekor qilingan bo'lsa vaqt o'zgarmaydi."""
        if api_key.revoked_at is None:
            api_key.revoked_at = utcnow()
            await self._flush()
        return api_key

    async def touch(self, api_key: ApiKey) -> ApiKey:
        """Kalitning oxirgi ishlatilgan vaqtini yangilaydi (har autentifikatsiyada)."""
        api_key.last_used_at = utcnow()
        await self._flush()
        return api_key


__all__ = ["ApiKeyRepository"]
