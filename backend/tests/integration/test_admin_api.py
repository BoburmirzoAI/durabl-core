"""Durabl — `/admin/*` endpointlarining integratsiya testlari.

## Maydon ro'yxatlari frontend turlaridan

CONTRACTS "QO'SHIMCHA 3" bo'yicha `src/types/admin.ts` — javob shaklining
shartnomasi. Shuning uchun `*_FIELDS` to'plamlari aynan shu interfeyslardan
ko'chirilgan va `issubset` bilan tekshiriladi (qo'shimcha maydon mumkin,
yo'q maydon — xato).

## Xato javobidan KEYIN ORM obyektiga murojaat qilmaslik

`get_db()` dependency'si istisno chiqqanda `session.rollback()` qiladi.
SQLite xotira bazasi `StaticPool` bilan BITTA ulanishda yashagani uchun bu
rollback `db_session` dagi obyektlarni ham "eskirgan" (expired) qilib
qo'yadi. Shundan keyin `job.id` kabi oddiy murojaat DB'ga SO'ROV yuborishga
urinadi va sinxron kontekstda `MissingGreenlet` beradi.

Shuning uchun qoida: 4xx/5xx qaytaradigan so'rovdan OLDIN kerakli
qiymatlar (`str(obj.id)`) oddiy o'zgaruvchiga ko'chiriladi. Kerak bo'lsa
`await db_session.refresh(obj)` ham ishlaydi, lekin identifikatorni
oldindan olish — ancha sodda.

## "Oxirgi faol adminni himoyalash" qoidasi NEGA servis darajasida sinaladi

`AdminService._assert_other_admin_remains()` "nishondan BOSHQA kamida bitta
FAOL admin qolsin" deb talab qiladi. HTTP orqali bu qoidaga yetib bo'lmaydi:
so'rovni bajaruvchi admin (`require_admin`) o'zi faol admin, ya'ni u
boshqa adminni tushirganda ham "qolgan" ro'yxat bo'sh bo'lmaydi; o'zini
o'zgartirishni esa `_assert_not_self_lockout()` oldinroq bloklaydi (403).

Qoida haqiqatan ishlaydigan holat — bajaruvchi admin FAOL EMAS (hisobi
bloklangan, lekin `is_admin=True` qolgan). Bunday admin `require_admin` dan
o'tmaydi, shuning uchun test `AdminService` ni bevosita chaqiradi. Bu
"ichki tafsilotni sinash" emas: qoida DB holatiga bog'liq va regressiya
ma'lumot yo'qolishiga olib kelardi.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from app.constants import AuditAction, JobStatus, PlanType
from app.exceptions import PermissionDeniedError
from app.schemas.admin import AdminUserUpdate
from app.services.admin_service import AdminService
from app.utils.security import hash_password

from tests.factories import make_user

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from collections.abc import Awaitable, Callable

    import httpx
    from app.models.job import Job
    from app.models.user import User
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

#: Barcha admin yo'llari (403 testi hammasini aylanadi).
ADMIN_PATHS = (
    "/admin/stats",
    "/admin/users",
    "/admin/system",
    "/admin/jobs",
    "/admin/audit-logs",
)

#: `src/types/admin.ts` -> `AdminStats`
STATS_FIELDS = frozenset(
    {
        "total_users",
        "active_users",
        "new_users_7d",
        "total_jobs",
        "jobs_24h",
        "jobs_by_status",
        "users_by_plan",
        "success_rate",
        "avg_duration_ms",
        "dlq_depth",
        "active_workers",
        "mrr_usd",
    }
)

#: `src/types/admin.ts` -> `SystemStatus`
SYSTEM_FIELDS = frozenset(
    {
        "status",
        "version",
        "environment",
        "checks",
        "uptime_seconds",
        "workers",
        "active_workers",
        "queues",
        "delayed_jobs",
        "dlq_depth",
        "webhook_queue_depth",
        "sandbox_available",
    }
)

#: `src/types/admin.ts` -> `AdminUser`
USER_FIELDS = frozenset(
    {
        "id",
        "email",
        "full_name",
        "is_active",
        "is_admin",
        "plan",
        "last_login_at",
        "created_at",
        "updated_at",
        "job_count",
        "jobs_this_period",
        "dlq_depth",
        "api_key_count",
    }
)

#: `src/types/admin.ts` -> `AuditLog`
AUDIT_FIELDS = frozenset(
    {
        "id",
        "admin_id",
        "admin_email",
        "action",
        "target_type",
        "target_id",
        "details",
        "ip_address",
        "user_agent",
        "created_at",
    }
)


async def test_regular_user_forbidden(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Oddiy foydalanuvchi barcha admin yo'llarida 403 oladi."""
    for path in ADMIN_PATHS:
        response = await client.get(api_prefix + path, headers=auth_headers)
        assert response.status_code == 403, f"{path}: {response.text}"
        assert response.json()["error"]["code"] == "ADMIN_REQUIRED"


async def test_anonymous_unauthorized(client: httpx.AsyncClient, api_prefix: str) -> None:
    """Tokensiz so'rov 401 oladi (403 emas — kim so'rayotgani ma'lum emas)."""
    response = await client.get(f"{api_prefix}/admin/stats")

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


async def test_stats_shape(
    client: httpx.AsyncClient,
    api_prefix: str,
    admin_headers: dict[str, str],
    user: User,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`/admin/stats` frontend `AdminStats` turiga mos va sonlar to'g'ri."""
    await job_factory(owner=user, status=JobStatus.SUCCESS, duration_ms=50)
    await job_factory(owner=user, status=JobStatus.FAILED)

    response = await client.get(f"{api_prefix}/admin/stats", headers=admin_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    missing = STATS_FIELDS - set(body)
    assert not missing, f"AdminStats: yo'q maydonlar {sorted(missing)}"

    assert body["total_users"] == 2
    assert body["active_users"] == 2
    assert body["total_jobs"] == 2
    assert body["jobs_by_status"][JobStatus.SUCCESS.value] == 1
    assert body["users_by_plan"][PlanType.FREE.value] == 2
    assert body["success_rate"] == 50.0
    assert body["mrr_usd"] == 0.0


async def test_users_list_and_filters(
    client: httpx.AsyncClient,
    api_prefix: str,
    admin_headers: dict[str, str],
    user: User,
    admin_user: User,
) -> None:
    """`/admin/users` barcha foydalanuvchilarni beradi va filtrlarni qo'llaydi."""
    response = await client.get(f"{api_prefix}/admin/users", headers=admin_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pagination"]["total"] == 2
    missing = USER_FIELDS - set(body["items"][0])
    assert not missing, f"AdminUser: yo'q maydonlar {sorted(missing)}"

    by_search = await client.get(
        f"{api_prefix}/admin/users?search={user.email}", headers=admin_headers
    )
    assert [item["id"] for item in by_search.json()["items"]] == [str(user.id)]

    only_admins = await client.get(f"{api_prefix}/admin/users?is_admin=true", headers=admin_headers)
    assert [item["id"] for item in only_admins.json()["items"]] == [str(admin_user.id)]

    by_plan = await client.get(
        f"{api_prefix}/admin/users?plan={PlanType.FREE.value}", headers=admin_headers
    )
    assert by_plan.json()["pagination"]["total"] == 2

    inactive = await client.get(f"{api_prefix}/admin/users?is_active=false", headers=admin_headers)
    assert inactive.json()["pagination"]["total"] == 0


async def test_update_user_writes_audit_log(
    client: httpx.AsyncClient,
    api_prefix: str,
    admin_headers: dict[str, str],
    admin_user: User,
    user: User,
) -> None:
    """`PUT /admin/users/{id}` o'zgarishni qo'llaydi va AUDIT yozuvi qoldiradi."""
    user_id = str(user.id)
    admin_id = str(admin_user.id)
    admin_email = admin_user.email

    response = await client.put(
        f"{api_prefix}/admin/users/{user_id}",
        headers=admin_headers,
        json={
            "full_name": "Admin o'zgartirdi",
            "plan": PlanType.PRO.value,
            "is_active": False,
            "reason": "to'lov muammosi",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["full_name"] == "Admin o'zgartirdi"
    assert body["plan"] == PlanType.PRO.value
    assert body["is_active"] is False

    logs = await client.get(f"{api_prefix}/admin/audit-logs", headers=admin_headers)
    assert logs.status_code == 200, logs.text
    items = logs.json()["items"]
    actions = {item["action"] for item in items}
    assert {
        AuditAction.USER_UPDATED.value,
        AuditAction.USER_DEACTIVATED.value,
        AuditAction.PLAN_CHANGED.value,
    } <= actions

    first = items[0]
    assert not AUDIT_FIELDS - set(first)
    # `admin_email` backend qo'shadigan maydon (`users` bilan LEFT JOIN).
    assert first["admin_email"] == admin_email
    assert first["admin_id"] == admin_id
    assert first["target_type"] == "user"
    assert first["target_id"] == user_id
    assert first["details"]["reason"] == "to'lov muammosi"


async def test_audit_log_filters(
    client: httpx.AsyncClient,
    api_prefix: str,
    admin_headers: dict[str, str],
    user: User,
) -> None:
    """Audit jurnali `action` va `target_type` bo'yicha filtrlanadi."""
    await client.put(
        f"{api_prefix}/admin/users/{user.id}",
        headers=admin_headers,
        json={"plan": PlanType.STARTER.value},
    )

    by_action = await client.get(
        f"{api_prefix}/admin/audit-logs?action={AuditAction.PLAN_CHANGED.value}",
        headers=admin_headers,
    )
    assert by_action.status_code == 200, by_action.text
    assert by_action.json()["pagination"]["total"] == 1

    by_other_action = await client.get(
        f"{api_prefix}/admin/audit-logs?action={AuditAction.USER_PROMOTED.value}",
        headers=admin_headers,
    )
    assert by_other_action.json()["pagination"]["total"] == 0

    by_target = await client.get(
        f"{api_prefix}/admin/audit-logs?target_type=user", headers=admin_headers
    )
    assert by_target.json()["pagination"]["total"] == 1


async def test_admin_cannot_change_own_flags(
    client: httpx.AsyncClient, api_prefix: str, admin_headers: dict[str, str], admin_user: User
) -> None:
    """Admin O'ZINING `is_active`/`is_admin` qiymatini o'zgartira olmaydi."""
    admin_id = str(admin_user.id)

    for payload in ({"is_active": False}, {"is_admin": False}):
        response = await client.put(
            f"{api_prefix}/admin/users/{admin_id}", headers=admin_headers, json=payload
        )
        assert response.status_code == 403, f"{payload}: {response.text}"
        error = response.json()["error"]
        assert error["code"] == "PERMISSION_DENIED"
        assert error["details"]["field"] in {"is_active", "is_admin"}

    # Xavfsiz maydonni o'zgartirish esa RUXSAT etilgan.
    renamed = await client.put(
        f"{api_prefix}/admin/users/{admin_id}",
        headers=admin_headers,
        json={"full_name": "O'z ismim"},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["full_name"] == "O'z ismim"


async def test_last_active_admin_is_protected(
    db_session: AsyncSession, fake_redis: object, admin_user: User
) -> None:
    """Oxirgi FAOL adminni huquqdan ayirish mumkin emas (docstring'ga qara)."""
    blocked_admin = make_user(
        email="bloklangan-admin@durabl.test",
        hashed_password=hash_password("Parol12345"),
        is_admin=True,
        is_active=False,
    )
    db_session.add(blocked_admin)
    await db_session.commit()

    service = AdminService(db_session)

    with pytest.raises(PermissionDeniedError) as demote:
        await service.update_user(blocked_admin, admin_user.id, AdminUserUpdate(is_admin=False))
    assert demote.value.details["reason"] == "demote"

    with pytest.raises(PermissionDeniedError) as deactivate:
        await service.update_user(blocked_admin, admin_user.id, AdminUserUpdate(is_active=False))
    assert deactivate.value.details["reason"] == "deactivate"

    # Hech narsa o'zgarmagan.
    await db_session.refresh(admin_user)
    assert admin_user.is_admin is True
    assert admin_user.is_active is True


async def test_update_unknown_user_not_found(
    client: httpx.AsyncClient, api_prefix: str, admin_headers: dict[str, str]
) -> None:
    """Mavjud bo'lmagan foydalanuvchi 404 `USER_NOT_FOUND` beradi."""
    response = await client.put(
        f"{api_prefix}/admin/users/{uuid.uuid4()}",
        headers=admin_headers,
        json={"full_name": "Hech kim"},
    )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "USER_NOT_FOUND"


async def test_system_status_shape(
    client: httpx.AsyncClient, api_prefix: str, admin_headers: dict[str, str]
) -> None:
    """`/admin/system` frontend `SystemStatus` turiga mos."""
    response = await client.get(f"{api_prefix}/admin/system", headers=admin_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    missing = SYSTEM_FIELDS - set(body)
    assert not missing, f"SystemStatus: yo'q maydonlar {sorted(missing)}"

    assert body["status"] in {"ok", "degraded", "down"}
    # Kalitlar `/health` bilan AYNI bo'lishi SHART (`CHECK_DATABASE`/`CHECK_REDIS`).
    assert body["checks"]["database"] is True
    assert body["checks"]["redis"] is True
    assert body["workers"] == []
    assert body["active_workers"] == 0
    assert {queue["priority"] for queue in body["queues"]}
    assert body["dlq_depth"] == 0


async def test_admin_jobs_sees_all_users(
    client: httpx.AsyncClient,
    api_prefix: str,
    admin_headers: dict[str, str],
    user: User,
    other_user: User,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`/admin/jobs` BARCHA foydalanuvchilarning job'larini beradi; `?user_id` toraytiradi."""
    mine = await job_factory(owner=user, status=JobStatus.SUCCESS)
    theirs = await job_factory(owner=other_user, status=JobStatus.FAILED)

    everything = await client.get(f"{api_prefix}/admin/jobs", headers=admin_headers)
    assert everything.status_code == 200, everything.text
    assert {item["id"] for item in everything.json()["items"]} == {
        str(mine.id),
        str(theirs.id),
    }

    filtered = await client.get(
        f"{api_prefix}/admin/jobs?user_id={other_user.id}", headers=admin_headers
    )
    assert [item["id"] for item in filtered.json()["items"]] == [str(theirs.id)]

    by_status = await client.get(
        f"{api_prefix}/admin/jobs?status={JobStatus.SUCCESS.value}", headers=admin_headers
    )
    assert [item["id"] for item in by_status.json()["items"]] == [str(mine.id)]


async def test_admin_jobs_invalid_sort_unprocessable(
    client: httpx.AsyncClient, api_prefix: str, admin_headers: dict[str, str]
) -> None:
    """`/admin/jobs?sort_by=yoq` 422 beradi (500 EMAS)."""
    response = await client.get(f"{api_prefix}/admin/jobs?sort_by=yoq", headers=admin_headers)

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_promote_user_to_admin(
    client: httpx.AsyncClient, api_prefix: str, admin_headers: dict[str, str], user: User
) -> None:
    """Huquq berish `USER_PROMOTED` audit yozuvini yaratadi."""
    response = await client.put(
        f"{api_prefix}/admin/users/{user.id}", headers=admin_headers, json={"is_admin": True}
    )

    assert response.status_code == 200, response.text
    assert response.json()["is_admin"] is True

    logs = await client.get(
        f"{api_prefix}/admin/audit-logs?action={AuditAction.USER_PROMOTED.value}",
        headers=admin_headers,
    )
    items = logs.json()["items"]
    assert len(items) == 1
    assert items[0]["details"] == {"field": "is_admin", "old": False, "new": True}


__all__ = [
    "ADMIN_PATHS",
    "AUDIT_FIELDS",
    "STATS_FIELDS",
    "SYSTEM_FIELDS",
    "USER_FIELDS",
]
