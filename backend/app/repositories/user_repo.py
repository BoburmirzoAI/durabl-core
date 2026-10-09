"""Durabl — `users` jadvali uchun repository.

Faqat SQL: `commit()` qilinmaydi (tranzaksiya chegarasini service belgilaydi),
biznes qoidalar ham bu yerda yozilmaydi.

**Email solishtirish haqida.** Email amalda registr (katta/kichik harf) ga
sezgir emas, shuning uchun qidiruvlar `lower(users.email) = lower(:email)`
ko'rinishida bajariladi. Bu yozuvdagi email qanday saqlanganidan qat'i nazar
to'g'ri ishlaydi; PostgreSQL'da unique indeksdan foydalanish uchun keyinchalik
`lower(email)` ustiga funksional indeks qo'shish mumkin.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Select, func, or_, select

from app.exceptions import ValidationError
from app.models.user import User
from app.repositories.base import BaseRepository
from app.utils.time_utils import utcnow

#: `search()` da tartiblash uchun ruxsat etilgan ustunlar (noto'g'ri ustundan himoya)
USER_SORT_COLUMNS: frozenset[str] = frozenset(
    {"created_at", "updated_at", "email", "full_name", "last_login_at", "is_active"}
)


class UserRepository(BaseRepository[User]):
    """Foydalanuvchilar bilan ishlash qatlami."""

    model = User

    # ------------------------------------------------------------------
    # O'qish
    # ------------------------------------------------------------------

    async def get_by_email(self, email: str) -> User | None:
        """Email bo'yicha foydalanuvchi (registrga sezgir emas); yo'q bo'lsa `None`."""
        normalized = self._normalize_email(email)
        stmt = select(User).where(func.lower(User.email) == normalized).limit(1)
        result = await self._execute(stmt)
        return result.scalars().first()

    async def email_exists(self, email: str) -> bool:
        """Shu email bilan foydalanuvchi bormi (ro'yxatdan o'tishda tekshiriladi)."""
        normalized = self._normalize_email(email)
        stmt = select(User.id).where(func.lower(User.email) == normalized).limit(1)
        result = await self._execute(stmt)
        return result.scalars().first() is not None

    async def list_admins(self) -> list[User]:
        """Barcha admin foydalanuvchilar (alert yuborish va audit uchun)."""
        stmt = select(User).where(User.is_admin.is_(True)).order_by(User.created_at.asc())
        result = await self._execute(stmt)
        return list(result.scalars().all())

    async def search(
        self,
        query: str | None = None,
        is_active: bool | None = None,
        is_admin: bool | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[list[User], int]:
        """Admin panel uchun foydalanuvchi qidiruvi.

        `query` — `email` yoki `full_name` ichidan `ILIKE` bo'yicha qidiradi.
        Umumiy son alohida `COUNT` so'rovi bilan olinadi.
        """
        conditions: list[Any] = []
        if query:
            pattern = f"%{query.strip()}%"
            conditions.append(or_(User.email.ilike(pattern), User.full_name.ilike(pattern)))
        if is_active is not None:
            conditions.append(User.is_active.is_(is_active))
        if is_admin is not None:
            conditions.append(User.is_admin.is_(is_admin))

        total = await self._count_where(conditions)
        if total == 0:
            return [], 0

        stmt: Select[Any] = select(User)
        if conditions:
            stmt = stmt.where(*conditions)
        stmt = self._apply_order(stmt, sort_by=sort_by, sort_order=sort_order)
        stmt = stmt.offset(max(0, (page - 1) * page_size)).limit(page_size)
        result = await self._execute(stmt)
        return list(result.scalars().all()), total

    # ------------------------------------------------------------------
    # Yozish
    # ------------------------------------------------------------------

    async def mark_login(self, user: User) -> User:
        """Muvaffaqiyatli login vaqtini belgilaydi (`last_login_at`)."""
        user.last_login_at = utcnow()
        await self._flush()
        return user

    async def set_active(self, user: User, *, active: bool) -> User:
        """Hisobni bloklaydi yoki qayta yoqadi (admin amali)."""
        user.is_active = active
        await self._flush()
        return user

    async def set_admin(self, user: User, *, admin: bool) -> User:
        """Admin huquqini beradi yoki olib qo'yadi."""
        user.is_admin = admin
        await self._flush()
        return user

    async def set_password(self, user: User, hashed_password: str) -> User:
        """Parol hash'ini almashtiradi (xom parol repositoryga kelmaydi)."""
        user.hashed_password = hashed_password
        await self._flush()
        return user

    # ------------------------------------------------------------------
    # Ichki yordamchilar
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_email(email: str) -> str:
        """Email'ni solishtirish uchun normallashtiradi: bo'shliq olib, kichik harf."""
        return email.strip().lower()

    async def _count_where(self, conditions: list[Any]) -> int:
        """Shartlarga mos yozuvlar sonini alohida `COUNT` so'rovi bilan hisoblaydi."""
        inner = select(User.id)
        if conditions:
            inner = inner.where(*conditions)
        stmt = select(func.count()).select_from(inner.subquery())
        result = await self._execute(stmt)
        return int(result.scalar_one() or 0)

    @staticmethod
    def _apply_order(stmt: Select[Any], *, sort_by: str, sort_order: str) -> Select[Any]:
        """ORDER BY qo'shadi; faqat `USER_SORT_COLUMNS` ichidagi ustunlar ruxsat etilgan."""
        if sort_by not in USER_SORT_COLUMNS:
            raise ValidationError(
                f"'{sort_by}' bo'yicha tartiblash mumkin emas",
                details={"allowed": sorted(USER_SORT_COLUMNS)},
            )
        column = getattr(User, sort_by)
        ordering = column.asc() if sort_order.lower() == "asc" else column.desc()
        # `id` — barqaror ikkinchi mezon: bir xil qiymatlarda sahifalar takrorlanmasin
        return stmt.order_by(ordering, User.id.asc())


__all__ = ["USER_SORT_COLUMNS", "UserRepository"]
