"""Durabl — `/billing/*` endpointlarining integratsiya testlari.

## `/billing/plans` — yagona OCHIQ billing yo'li

Narx jadvali marketing sahifasida ham ko'rsatiladi, shuning uchun u
`PUBLIC_PATHS` ro'yxatida. Lekin token BERILSA `is_current` to'ldiriladi —
`resolve_optional_plan` dependency'si autentifikatsiyani IXTIYORIY qiladi
va yaroqsiz token uchun ham 401 TASHLAMAYDI (ochiq yo'l ochiq qolishi
kerak). Ikki holat ham shu faylda tekshiriladi.

## `/billing/history` — massiv, sahifalanmagan

CONTRACTS "QO'SHIMCHA 2 / BILLING" jadvalida javob turi `list[UsageHistoryItem]`
(qalin yozilgan: "sahifalanmagan!"). Frontend `UsageHistoryItem[]` kutadi,
ya'ni `{items: [...]}` qaytarish uni buzardi — shuning uchun javob turi
alohida test bilan muzlatilgan.

## Kvota hisobi

`JobService.submit()` har qabul qilingan job uchun `UsageRecord.job_count`
ni oshiradi (`check_quota` ayni shu hisoblagichga qaraydi). Shuning uchun
`POST /jobs` dan keyin `/billing/usage` darhol o'zgaradi — worker ishga
tushishini kutish KERAK EMAS.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from app.constants import PLAN_LIMITS, PlanType

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    import httpx
    from app.models.user import User

pytestmark = pytest.mark.integration

#: `src/types/billing.ts` -> `UsageSummary`
USAGE_FIELDS = frozenset(
    {
        "period",
        "plan",
        "job_count",
        "success_count",
        "failed_count",
        "execution_seconds",
        "monthly_limit",
        "remaining",
        "usage_percent",
        "period_start",
        "period_end",
        "is_over_limit",
    }
)

#: `src/types/billing.ts` -> `PlanInfo`
PLAN_FIELDS = frozenset(
    {
        "plan",
        "name",
        "description",
        "price_usd_month",
        "limits",
        "features",
        "is_popular",
        "is_current",
    }
)

#: `src/types/billing.ts` -> `PlanLimits` (`app.constants.PlanLimits.as_dict()`)
LIMIT_FIELDS = frozenset(
    {
        "plan",
        "monthly_jobs",
        "requests_per_minute",
        "max_concurrent_jobs",
        "max_timeout_seconds",
        "max_memory_mb",
        "max_cpus",
        "log_retention_days",
        "allow_network",
        "price_usd_month",
    }
)

#: Oddiy job tanasi (kvota hisobi uchun).
JOB_BODY = {"code": "def main(payload):\n    return 1\n", "runtime": "python"}


async def test_plans_without_authentication(client: httpx.AsyncClient, api_prefix: str) -> None:
    """`/billing/plans` tokensiz ishlaydi va BARCHA rejalarni beradi."""
    response = await client.get(f"{api_prefix}/billing/plans")

    assert response.status_code == 200, response.text
    body = response.json()
    assert {item["plan"] for item in body["items"]} == {item.value for item in PlanType}
    # `current_plan` anonim so'rovda ZAXIRA qiymat (`free`) bo'ladi, lekin
    # HECH BIR reja "joriy" deb belgilanmaydi — frontend narx jadvalida
    # "Sizning rejangiz" nishonini aynan `is_current` bo'yicha chizadi.
    assert body["current_plan"] == PlanType.FREE.value
    assert all(item["is_current"] is False for item in body["items"])

    first = body["items"][0]
    missing = PLAN_FIELDS - set(first)
    assert not missing, f"PlanInfo: yo'q maydonlar {sorted(missing)}"
    assert not LIMIT_FIELDS - set(first["limits"])


async def test_plans_marks_current_plan(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Token berilganda foydalanuvchining rejasi `is_current=true` bo'ladi."""
    response = await client.get(f"{api_prefix}/billing/plans", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["current_plan"] == PlanType.FREE.value
    current = [item["plan"] for item in body["items"] if item["is_current"]]
    assert current == [PlanType.FREE.value]


async def test_plans_tolerates_broken_token(client: httpx.AsyncClient, api_prefix: str) -> None:
    """Ochiq yo'l yaroqsiz token bilan ham 200 qaytaradi (401 EMAS)."""
    response = await client.get(
        f"{api_prefix}/billing/plans", headers={"Authorization": "Bearer yaroqsiz"}
    )

    assert response.status_code == 200, response.text
    assert all(item["is_current"] is False for item in response.json()["items"])


async def test_usage_shape(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """`/billing/usage` frontend `UsageSummary` turiga mos."""
    response = await client.get(f"{api_prefix}/billing/usage", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    missing = USAGE_FIELDS - set(body)
    assert not missing, f"UsageSummary: yo'q maydonlar {sorted(missing)}"

    limits = PLAN_LIMITS[PlanType.FREE]
    assert body["plan"] == PlanType.FREE.value
    assert body["job_count"] == 0
    assert body["monthly_limit"] == limits.monthly_jobs
    assert body["remaining"] == limits.monthly_jobs
    assert body["usage_percent"] == 0
    assert body["is_over_limit"] is False
    assert body["period_start"] < body["period_end"]


async def test_usage_counts_submitted_jobs(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Har qabul qilingan job hisobga tushadi va `remaining` kamayadi."""
    for _ in range(3):
        created = await client.post(f"{api_prefix}/jobs", headers=auth_headers, json=JOB_BODY)
        assert created.status_code == 201, created.text

    response = await client.get(f"{api_prefix}/billing/usage", headers=auth_headers)

    body = response.json()
    limit = PLAN_LIMITS[PlanType.FREE].monthly_jobs
    assert body["job_count"] == 3
    assert body["remaining"] == limit - 3
    assert body["usage_percent"] == pytest.approx(3 / limit * 100, abs=0.01)


async def test_subscription_get(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str], user: User
) -> None:
    """`GET /billing/subscription` faol FREE obunani va limitlarni beradi."""
    response = await client.get(f"{api_prefix}/billing/subscription", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user_id"] == str(user.id)
    assert body["plan"] == PlanType.FREE.value
    assert body["is_active"] is True
    assert body["cancelled_at"] is None
    assert not LIMIT_FIELDS - set(body["limits"])


async def test_subscription_change_plan(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """`POST /billing/subscription` rejani almashtiradi va limitlar yangilanadi."""
    response = await client.post(
        f"{api_prefix}/billing/subscription",
        headers=auth_headers,
        json={"plan": PlanType.PRO.value},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plan"] == PlanType.PRO.value
    assert body["limits"]["monthly_jobs"] == PLAN_LIMITS[PlanType.PRO].monthly_jobs

    usage = await client.get(f"{api_prefix}/billing/usage", headers=auth_headers)
    assert usage.json()["plan"] == PlanType.PRO.value
    assert usage.json()["monthly_limit"] == PLAN_LIMITS[PlanType.PRO].monthly_jobs


async def test_subscription_unknown_plan_unprocessable(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Noma'lum reja nomi 422 beradi."""
    response = await client.post(
        f"{api_prefix}/billing/subscription", headers=auth_headers, json={"plan": "platinum"}
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_history_returns_bare_array(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """`/billing/history` MASSIV qaytaradi (modul docstring'iga qara)."""
    await client.post(f"{api_prefix}/jobs", headers=auth_headers, json=JOB_BODY)

    response = await client.get(f"{api_prefix}/billing/history", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert isinstance(body, list), "javob massiv bo'lishi SHART"
    assert body
    item = body[0]
    for field in (
        "period",
        "job_count",
        "success_count",
        "failed_count",
        "execution_seconds",
        "recorded_at",
    ):
        assert field in item, field
    assert item["job_count"] == 1


async def test_history_respects_limit(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """`?limit` qabul qilinadi; chegaradan tashqari qiymat 422 beradi."""
    allowed = await client.get(f"{api_prefix}/billing/history?limit=1", headers=auth_headers)
    assert allowed.status_code == 200, allowed.text
    assert len(allowed.json()) <= 1

    rejected = await client.get(f"{api_prefix}/billing/history?limit=0", headers=auth_headers)
    assert rejected.status_code == 422, rejected.text


async def test_private_endpoints_require_authentication(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    """`/plans` dan tashqari barcha billing yo'llari token talab qiladi."""
    for path in ("/billing/usage", "/billing/subscription", "/billing/history"):
        response = await client.get(api_prefix + path)
        assert response.status_code == 401, f"{path}: {response.text}"
        assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


async def test_api_key_can_read_usage(
    client: httpx.AsyncClient, api_prefix: str, api_key_headers: dict[str, str]
) -> None:
    """Billing o'qish yo'llari `X-API-Key` ni ham qabul qiladi.

    Shartnoma jadvalida ustun "J" deb yozilgan, lekin router `CurrentUser`
    dependency'sini ishlatadi (`JwtUser` EMAS) — ya'ni API kalit ham
    o'tadi. Bu ataylab: foydalanish hisobini CI skripti o'qishi normal
    holat, va kalit hech narsani O'ZGARTIRMAYDI (`POST /subscription`
    ham `CurrentUser`, lekin u reja almashtirishdan boshqa huquq bermaydi).
    Test shu haqiqiy xatti-harakatni qayd etadi.
    """
    response = await client.get(f"{api_prefix}/billing/usage", headers=api_key_headers)

    assert response.status_code == 200, response.text
    assert response.json()["plan"] == PlanType.FREE.value


__all__ = ["JOB_BODY", "LIMIT_FIELDS", "PLAN_FIELDS", "USAGE_FIELDS"]
