"""Durabl — bazaviy repository: umumiy async CRUD amallari.

**Konvensiya (barcha repository'lar uchun majburiy):**

* Repository konstruktorga `AsyncSession` oladi: `JobRepository(session)`.
* Repository `commit()` QILMAYDI — tranzaksiya chegarasini service/dependency
  belgilaydi. Repository faqat `flush()` qiladi (ID va standart qiymatlar
  kerak bo'lganda).
* Repository domen xatolarini tashlamaydi (NotFound'dan tashqari — u ham
  faqat `get_or_raise` da). Biznes qoidalar service qatlamida.
"""

from __future__ import annotations

import builtins  # `list` klass ichida metod nomi — builtin'ga ochiq murojaat uchun
import uuid
from collections.abc import Callable, Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import Select, func, inspect, select
from sqlalchemy import delete as sa_delete
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import DatabaseError, NotFoundError
from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """Umumiy CRUD. Voris klassda `model` atributini belgilash shart.

    Misol:
        class UserRepository(BaseRepository[User]):
            model = User
    """

    #: Voris klass shu atributni belgilaydi
    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        if not hasattr(self, "model"):
            raise TypeError(
                f"{type(self).__name__} klassida `model` atributi belgilanmagan"
            )
        self.session = session

    # ------------------------------------------------------------------
    # O'qish
    # ------------------------------------------------------------------

    async def get(self, entity_id: uuid.UUID | str) -> ModelT | None:
        """ID bo'yicha bitta yozuv (yo'q bo'lsa `None`)."""
        return await self.session.get(self.model, self._coerce_id(entity_id))

    async def get_or_raise(
        self,
        entity_id: uuid.UUID | str,
        *,
        error: Callable[[Any], NotFoundError] = NotFoundError,
    ) -> ModelT:
        """ID bo'yicha yozuv; topilmasa `NotFoundError` tashlaydi.

        `error` — identifikatordan xato yasaydigan FABRIKA
        (`JobNotFoundError(job_id)` kabi), oddiy `type[NotFoundError]` emas:
        bazaviy `NotFoundError` ning birinchi argumenti resurs NOMI, voris
        klasslarda esa IDENTIFIKATOR. Shuning uchun standart qiymat alohida
        shoxda (`error is NotFoundError`) ishlatiladi.
        """
        instance = await self.get(entity_id)
        if instance is None:
            if error is NotFoundError:
                raise NotFoundError(self.model.__name__, entity_id)
            raise error(entity_id)
        return instance

    async def get_by(self, **filters: Any) -> ModelT | None:
        """Maydonlar bo'yicha birinchi mos yozuv."""
        stmt = self._apply_filters(select(self.model), filters).limit(1)
        result = await self._execute(stmt)
        return result.scalars().first()

    async def list(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
        order_by: Any = None,
        **filters: Any,
    ) -> list[ModelT]:
        """Filtrlangan ro'yxat."""
        stmt = self._apply_filters(select(self.model), filters)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        elif hasattr(self.model, "created_at"):
            stmt = stmt.order_by(self.model.created_at.desc())  # type: ignore[attr-defined]
        if offset:
            stmt = stmt.offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self._execute(stmt)
        return list(result.scalars().all())

    async def list_paginated(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        order_by: Any = None,
        **filters: Any,
    ) -> tuple[builtins.list[ModelT], int]:
        """`(yozuvlar, umumiy_son)` juftligi — `PaginatedResponse` uchun."""
        total = await self.count(**filters)
        items = await self.list(
            limit=page_size,
            offset=max(0, (page - 1) * page_size),
            order_by=order_by,
            **filters,
        )
        return items, total

    async def count(self, **filters: Any) -> int:
        """Filtrga mos yozuvlar soni."""
        stmt = self._apply_filters(
            select(func.count()).select_from(self.model), filters
        )
        result = await self._execute(stmt)
        return int(result.scalar_one() or 0)

    async def exists(self, **filters: Any) -> bool:
        """Mos yozuv bormi (LIMIT 1 bilan tez tekshiruv)."""
        stmt = self._apply_filters(select(self.model.id), filters).limit(1)  # type: ignore[attr-defined]
        result = await self._execute(stmt)
        return result.scalars().first() is not None

    # ------------------------------------------------------------------
    # Yozish
    # ------------------------------------------------------------------

    async def create(self, **values: Any) -> ModelT:
        """Yangi yozuv yaratadi va `flush` qiladi (ID darhol mavjud bo'ladi)."""
        instance = self.model(**values)
        return await self.add(instance)

    async def add(self, instance: ModelT) -> ModelT:
        """Tayyor obyektni sessiyaga qo'shadi."""
        self.session.add(instance)
        await self._flush()
        return instance

    async def create_many(self, rows: Sequence[dict[str, Any]]) -> builtins.list[ModelT]:
        """Bir nechta yozuvni birdan yaratadi."""
        instances = [self.model(**row) for row in rows]
        self.session.add_all(instances)
        await self._flush()
        return instances

    async def update(self, instance: ModelT, **values: Any) -> ModelT:
        """Obyekt maydonlarini yangilaydi (faqat modelda bor maydonlar)."""
        allowed = {column.key for column in inspect(self.model).mapper.column_attrs}
        for key, value in values.items():
            if key in allowed:
                setattr(instance, key, value)
        await self._flush()
        return instance

    async def update_by_id(self, entity_id: uuid.UUID | str, **values: Any) -> ModelT | None:
        """ID bo'yicha topib yangilaydi."""
        instance = await self.get(entity_id)
        if instance is None:
            return None
        return await self.update(instance, **values)

    async def bulk_update(self, filters: dict[str, Any], values: dict[str, Any]) -> int:
        """Bitta SQL bilan ko'p yozuvni yangilaydi; yangilangan yozuv sonini qaytaradi."""
        stmt = sa_update(self.model).values(**values)
        for key, value in filters.items():
            stmt = stmt.where(getattr(self.model, key) == value)
        result = await self._execute(stmt)
        return int(result.rowcount or 0)

    # ------------------------------------------------------------------
    # O'chirish
    # ------------------------------------------------------------------

    async def delete(self, instance: ModelT) -> None:
        """Obyektni o'chiradi."""
        await self.session.delete(instance)
        await self._flush()

    async def delete_by_id(self, entity_id: uuid.UUID | str) -> bool:
        """ID bo'yicha o'chiradi; o'chirilganini `bool` bilan qaytaradi."""
        instance = await self.get(entity_id)
        if instance is None:
            return False
        await self.delete(instance)
        return True

    async def delete_where(self, **filters: Any) -> int:
        """Filtrga mos barcha yozuvlarni bitta SQL bilan o'chiradi."""
        stmt = sa_delete(self.model)
        for key, value in filters.items():
            stmt = stmt.where(getattr(self.model, key) == value)
        result = await self._execute(stmt)
        return int(result.rowcount or 0)

    # ------------------------------------------------------------------
    # Yordamchilar
    # ------------------------------------------------------------------

    async def refresh(
        self, instance: ModelT, *, attributes: builtins.list[str] | None = None
    ) -> ModelT:
        """Obyektni DB'dan qayta o'qiydi."""
        await self.session.refresh(instance, attribute_names=attributes)
        return instance

    def _apply_filters(self, stmt: Select[Any], filters: dict[str, Any]) -> Select[Any]:
        """Lug'at filtrlarini WHERE shartlariga aylantiradi.

        * `None` qiymatlar e'tiborsiz qoldiriladi (ixtiyoriy filtr).
        * `list`/`tuple`/`set` -> `IN (...)`.
        * Modelda mavjud bo'lmagan maydon -> `DatabaseError`.
        """
        for key, value in filters.items():
            if value is None:
                continue
            column = getattr(self.model, key, None)
            if column is None:
                raise DatabaseError(
                    f"{self.model.__name__} modelida '{key}' maydoni yo'q",
                    details={"field": key},
                )
            if isinstance(value, (list, tuple, set, frozenset)):
                values = list(value)
                if not values:
                    # Bo'sh ro'yxat — hech narsa mos kelmaydi
                    stmt = stmt.where(column.in_([None]))
                    continue
                stmt = stmt.where(column.in_(values))
            else:
                stmt = stmt.where(column == value)
        return stmt

    @staticmethod
    def _coerce_id(entity_id: uuid.UUID | str) -> uuid.UUID | str:
        """Matn ko'rinishidagi UUID'ni `uuid.UUID`ga aylantiradi."""
        if isinstance(entity_id, uuid.UUID):
            return entity_id
        try:
            return uuid.UUID(str(entity_id))
        except (ValueError, AttributeError, TypeError):
            return entity_id

    async def _execute(self, stmt: Any) -> Any:
        """SQL bajaradi va drayver xatolarini `DatabaseError`ga o'raydi."""
        try:
            return await self.session.execute(stmt)
        except SQLAlchemyError as exc:  # pragma: no cover - infratuzilma xatosi
            raise DatabaseError(f"SQL bajarishda xato: {exc}") from exc

    async def _flush(self) -> None:
        """`flush` qiladi; cheklov buzilsa tushunarli xato beradi."""
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise DatabaseError(
                f"Ma'lumot butunligi cheklovi buzildi: {exc.orig}",
                details={"table": getattr(self.model, "__tablename__", None)},
            ) from exc
        except SQLAlchemyError as exc:  # pragma: no cover
            raise DatabaseError(f"flush xatosi: {exc}") from exc


__all__ = ["BaseRepository", "ModelT"]
