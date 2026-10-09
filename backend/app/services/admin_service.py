"""Durabl — admin panel biznes logikasi (`/api/v1/admin/*`).

Bu servis admin endpointlarining IKKI ishini bajaradi, chunki ikkisi ham
HTTP qatlamiga sig'maydi (`CONTRACTS.md` §2: router `select()` yozmaydi va
modelga bevosita tegmaydi):

1. **Foydalanuvchini o'zgartirish** (`PUT /admin/users/{id}`) — himoya
   qoidalari, reja almashtirish va audit yozuvlari bitta tranzaksiyada.
2. **Barcha foydalanuvchilarning job'lari** (`GET /admin/jobs`) —
   `JobService.list()` har doim `user.id` bo'yicha filtrlaydi (mijoz
   endpointlari uchun TO'G'RI xatti-harakat), admin kesimi esa
   `user_id=None` bilan qidiruvni talab qiladi.

**O'qish kesimlari bu yerda TAKRORLANMAYDI.** `admin_stats`, `admin_users`,
`audit_logs` va `system_status` — `AnalyticsService` da (u guruhlangan
so'rovlar bilan N+1 ni oldini oladi). Bu servis ularni faqat chaqiradi.

## Himoya qoidalari (nega kerak)

Admin panelida eng xavfli amal — **o'zini tizimdan chiqarib qulflab
qo'yish**. Shuning uchun ikki qoida:

* admin O'ZINING `is_admin` yoki `is_active` qiymatini O'ZGARTIRA olmaydi
  (bir qadamda o'zini bloklash yoki huquqdan ayirish mumkin emas);
* tizimdagi OXIRGI faol adminning admin huquqini olib qo'yish yoki uni
  bloklash mumkin emas — aks holda admin panelga hech kim kira olmaydi va
  tiklash faqat DB'ga qo'lda murojaat bilan bo'lardi.

Ikkisi ham `PermissionDeniedError` (403) beradi.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Final

from redis.asyncio import Redis

from app.constants import AuditAction, PlanType
from app.exceptions import PermissionDeniedError, UserNotFoundError
from app.logging_config import get_logger
from app.models.user import User
from app.redis_client import get_redis
from app.repositories.job_repo import JobRepository
from app.repositories.subscription_repo import SubscriptionRepository
from app.repositories.user_repo import UserRepository
from app.schemas.admin import AdminUserRead
from app.services.analytics_service import AnalyticsService
from app.services.audit_service import TARGET_USER, AuditService
from app.services.billing_service import BillingService
from app.services.cache_service import CacheService
from app.utils.time_utils import ensure_utc

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi uchun
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.job import Job
    from app.schemas.admin import AdminUserUpdate
    from app.schemas.base import PaginationParams
    from app.schemas.job import JobFilter

logger = get_logger(__name__)

#: Reja cache namespace'i — `dependencies._prime_plan_cache` va
#: `RateLimitMiddleware` AYNI nomni o'qiydi. Reja o'zgarganda yozuv
#: o'chiriladi, aks holda yangi limit TTL (300s) tugaguncha kuchga kirmaydi.
PLAN_CACHE_NAMESPACE: Final = "user_plan"

#: `AdminUserRead` ni agregatlari bilan qaytarish uchun `admin_users()`
#: email bo'yicha qidiriladi. Qidiruv `ILIKE '%email%'` bo'lgani uchun
#: bir necha mos kelishi mumkin — shuning uchun sahifa kichik, lekin bitta
#: yozuvdan kattaroq olinadi va keraklisi `id` bo'yicha tanlanadi.
USER_LOOKUP_PAGE_SIZE: Final = 50


class AdminService:
    """Admin amallari: foydalanuvchini o'zgartirish va platforma kesimlari."""

    def __init__(self, session: AsyncSession, redis: Redis | None = None) -> None:
        """Servisni so'rov sessiyasi va Redis klienti bilan yaratadi.

        Args:
            session: Joriy tranzaksiya sessiyasi.
            redis: Redis klienti; berilmasa global pool ishlatiladi
                (reja cache'ini tozalash va analitika uchun kerak).
        """
        self.session = session
        self.redis = redis or get_redis()
        self.users = UserRepository(session)
        self.jobs = JobRepository(session)
        self.subscriptions = SubscriptionRepository(session)
        self.audit = AuditService(session)
        self.billing = BillingService(session)
        self.analytics = AnalyticsService(session, self.redis)
        self.cache = CacheService(self.redis)

    # ------------------------------------------------------------------
    # Foydalanuvchini o'zgartirish
    # ------------------------------------------------------------------

    async def update_user(
        self,
        admin: User,
        user_id: uuid.UUID | str,
        data: AdminUserUpdate,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> AdminUserRead:
        """Foydalanuvchini qismiy yangilaydi va har o'zgarishni audit qiladi.

        Tartib ATAYLAB shunday: avval BARCHA tekshiruvlar, keyin yozish.
        Shu tufayli qoida buzilganda hech narsa o'zgarmaydi — qismiy
        bajarilgan o'zgartirish qolmaydi.

        Har bir o'zgargan maydon uchun BITTA `AuditLog` yozuvi yaratiladi:

        | Maydon | Harakat |
        |---|---|
        | `is_active=True` | `USER_ACTIVATED` |
        | `is_active=False` | `USER_DEACTIVATED` |
        | `is_admin=True` | `USER_PROMOTED` |
        | `is_admin=False` | `USER_UPDATED` (enumda `USER_DEMOTED` yo'q) |
        | `plan` | `PLAN_CHANGED` |
        | `full_name` | `USER_UPDATED` |

        Args:
            admin: Amalni bajarayotgan administrator (`require_admin`).
            user_id: O'zgartirilayotgan foydalanuvchi identifikatori.
            data: Qismiy yangilash so'rovi.
            ip_address: So'rov kelgan IP (audit uchun).
            user_agent: Mijoz `User-Agent` qiymati (audit uchun).

        Returns:
            Yangilangan foydalanuvchi — agregatlari bilan (`AdminUserRead`).

        Raises:
            UserNotFoundError: Bunday foydalanuvchi yo'q.
            PermissionDeniedError: Himoya qoidasi buzildi (o'zini
                o'zgartirish yoki oxirgi faol adminni huquqdan ayirish).
            ValidationError: Reja nomi noma'lum.
        """
        user = await self.users.get(user_id)
        if user is None:
            raise UserNotFoundError(user_id)

        fields = data.model_fields_set
        wants_active = "is_active" in fields and data.is_active is not None
        wants_admin = "is_admin" in fields and data.is_admin is not None
        wants_plan = "plan" in fields and data.plan is not None
        wants_name = "full_name" in fields

        #: Faqat HAQIQATAN o'zgarayotgan maydonlar tekshiriladi: o'z
        #: hisobiga ayni qiymatni qayta yuborish (`is_active=True`) zararsiz.
        changes_active = wants_active and bool(user.is_active) != bool(data.is_active)
        changes_admin = wants_admin and bool(user.is_admin) != bool(data.is_admin)

        self._assert_not_self_lockout(
            admin, user, changes_active=changes_active, changes_admin=changes_admin
        )
        if changes_admin and not data.is_admin:
            await self._assert_other_admin_remains(user, reason="demote")
        if changes_active and not data.is_active and user.is_admin:
            await self._assert_other_admin_remains(user, reason="deactivate")

        #: Eski reja YOZUVDAN o'qiladi, `limits_for()` dan EMAS: muddati
        #: o'tgan obuna uchun amaldagi limitlar FREE bo'ladi, lekin
        #: jadvalda hamon `pro` turadi. Yozuvga qaramasak, admin
        #: `plan=free` deb normallashtirganda o'zgarish SEZILMAY qolardi
        #: va `expires_at` yangilanishi bilan reja o'z-o'zidan tiklanardi.
        subscription = await self.subscriptions.get_for_user(user.id)
        previous_plan = PlanType(subscription.plan) if subscription is not None else PlanType.FREE
        records: list[tuple[AuditAction, dict[str, Any]]] = []

        if wants_name and user.full_name != data.full_name:
            records.append(
                (AuditAction.USER_UPDATED, self._diff("full_name", user.full_name, data.full_name))
            )
            await self.users.update(user, full_name=data.full_name)

        if changes_active:
            action = AuditAction.USER_ACTIVATED if data.is_active else AuditAction.USER_DEACTIVATED
            records.append(
                (action, self._diff("is_active", user.is_active, bool(data.is_active)))
            )
            await self.users.set_active(user, active=bool(data.is_active))

        if changes_admin:
            #: `AuditAction` da `USER_DEMOTED` yo'q, shuning uchun huquqni
            #: OLIB QO'YISH `USER_UPDATED` bilan qayd etiladi — `details`
            #: da maydon nomi va eski/yangi qiymat ko'rinadi.
            action = AuditAction.USER_PROMOTED if data.is_admin else AuditAction.USER_UPDATED
            records.append((action, self._diff("is_admin", user.is_admin, bool(data.is_admin))))
            await self.users.set_admin(user, admin=bool(data.is_admin))

        plan_changed = wants_plan and data.plan is not None and data.plan is not previous_plan
        if plan_changed and data.plan is not None:
            records.append(
                (AuditAction.PLAN_CHANGED, self._diff("plan", previous_plan.value, data.plan.value))
            )

        #: Audit yozuvlari reja almashtirishdan OLDIN qo'shiladi (lekin
        #: commit QILINMAYDI): `BillingService.change_plan()` o'z
        #: tranzaksiyasini yopadi, shuning uchun u chaqirilganda audit
        #: yozuvlari ham AYNI commit bilan saqlanadi. Teskari tartibda
        #: reja o'zgarishi auditdan OLDIN commit bo'lib, keyingi xato
        #: "audit izi yo'q o'zgarish" holatini qoldirardi.
        for action, details in records:
            if data.reason:
                details["reason"] = data.reason
            await self.audit.record(
                admin,
                action,
                target_type=TARGET_USER,
                target_id=user.id,
                details=details,
                ip_address=ip_address,
                user_agent=user_agent,
            )

        if plan_changed and data.plan is not None:
            await self.billing.change_plan(user, data.plan)
            #: Reja cache'i o'chiriladi — aks holda yangi limit TTL
            #: tugaguncha (`rate_limit` middleware uchun) kuchga kirmaydi.
            await self.cache.delete(PLAN_CACHE_NAMESPACE, user.id)

        await self.session.commit()
        logger.info(
            "admin.user_updated",
            admin_id=str(admin.id),
            user_id=str(user.id),
            changes=[action.value for action, _ in records],
        )
        return await self._read_user(user)

    # ------------------------------------------------------------------
    # Job'lar (platforma kesimi)
    # ------------------------------------------------------------------

    async def list_jobs(
        self,
        filters: JobFilter,
        pagination: PaginationParams,
        *,
        user_id: uuid.UUID | str | None = None,
    ) -> tuple[list[Job], int]:
        """BARCHA foydalanuvchilarning job'lari (`?user_id` bilan toraytirilishi mumkin).

        `JobRepository.search()` `failure_reason` va `tag` filtrlarini SQL
        darajasida qo'llaydi, shuning uchun `total` va sahifa mazmuni har
        doim mos keladi (Python tomonida qayta filtrlash YO'Q).

        Returns:
            `(job'lar, jami_soni)`.

        Raises:
            DatabaseError: SQL bajarishda xato.
        """
        return await self.jobs.search(
            user_id=user_id,
            status=filters.status,
            runtime=filters.runtime,
            priority=filters.priority,
            start=filters.start,
            end=filters.end,
            search=filters.search,
            failure_reason=filters.failure_reason,
            tag=filters.tag,
            page=pagination.page,
            page_size=pagination.page_size,
            sort_by=filters.sort_by,
            sort_order=filters.sort_order,
        )

    # ------------------------------------------------------------------
    # Ichki yordamchilar
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_not_self_lockout(
        admin: User,
        target: User,
        *,
        changes_active: bool,
        changes_admin: bool,
    ) -> None:
        """Admin o'zini bloklashi yoki huquqdan ayirishini taqiqlaydi.

        Raises:
            PermissionDeniedError: Nishon — o'zi va xavfli maydon o'zgaradi.
        """
        if admin.id != target.id or not (changes_active or changes_admin):
            return
        field = "is_admin" if changes_admin else "is_active"
        logger.warning("admin.self_lockout_blocked", admin_id=str(admin.id), field=field)
        raise PermissionDeniedError(
            "O'z hisobingizning `is_admin` yoki `is_active` qiymatini "
            "o'zgartirish mumkin emas — boshqa administratordan so'rang",
            details={"field": field},
        )

    async def _assert_other_admin_remains(self, target: User, *, reason: str) -> None:
        """Tizimda kamida bitta BOSHQA faol admin qolishini talab qiladi.

        Args:
            target: Huquqi olinayotgan yoki bloklanayotgan foydalanuvchi.
            reason: `details` ga yoziladigan sabab (`demote`/`deactivate`).

        Raises:
            PermissionDeniedError: Boshqa faol admin yo'q.
        """
        admins = await self.users.list_admins()
        remaining = [row for row in admins if row.id != target.id and row.is_active]
        if remaining:
            return
        logger.warning("admin.last_admin_protected", user_id=str(target.id), reason=reason)
        raise PermissionDeniedError(
            "Tizimdagi oxirgi faol administratorni huquqdan ayirish yoki "
            "bloklash mumkin emas",
            details={"reason": reason, "user_id": str(target.id)},
        )

    @staticmethod
    def _diff(field: str, old: Any, new: Any) -> dict[str, Any]:
        """Audit `details` uchun eski/yangi qiymat juftligi."""
        return {"field": field, "old": old, "new": new}

    async def _read_user(self, user: User) -> AdminUserRead:
        """Yangilangan foydalanuvchini agregatlari bilan o'qiydi.

        Agregatlar (`job_count`, `jobs_this_period`, `dlq_depth`,
        `api_key_count`) `AnalyticsService.admin_users()` dan olinadi —
        u guruhlangan so'rovlar bilan ishlaydi, shuning uchun bu yerda
        hisob-kitob TAKRORLANMAYDI.

        Qidiruv `ILIKE '%email%'` bo'lgani uchun natijada boshqa
        foydalanuvchilar ham bo'lishi mumkin — keraklisi `id` bo'yicha
        tanlanadi. Topilmasa (nazariy holat: email bir xil bo'lgan 50+
        yozuv) agregatsiz, lekin TO'G'RI asosiy maydonlar bilan javob
        qaytadi — o'zgartirish allaqachon bajarilgan, uni xato bilan
        yashirish noto'g'ri bo'lardi.
        """
        items, _ = await self.analytics.admin_users(
            search=user.email, page=1, page_size=USER_LOOKUP_PAGE_SIZE
        )
        for item in items:
            if item.id == user.id:
                return item

        logger.warning("admin.user_aggregates_missing", user_id=str(user.id))
        #: Reja obuna YOZUVIDAN olinadi — `AnalyticsService.admin_users()`
        #: ham shu manbadan foydalanadi, shuning uchun zaxira yo'l bilan
        #: asosiy yo'l bir xil qiymatni ko'rsatadi.
        subscription = await self.subscriptions.get_for_user(user.id)
        plan = PlanType(subscription.plan) if subscription is not None else PlanType.FREE
        return AdminUserRead.model_validate(user).model_copy(
            update={
                "plan": plan,
                "created_at": ensure_utc(user.created_at),
                "updated_at": ensure_utc(user.updated_at),
                "last_login_at": ensure_utc(user.last_login_at),
            }
        )


__all__ = [
    "PLAN_CACHE_NAMESPACE",
    "USER_LOOKUP_PAGE_SIZE",
    "AdminService",
]
