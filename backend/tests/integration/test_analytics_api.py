"""Durabl — `/analytics/*` endpointlarining integratsiya testlari.

## Nega maydonlar ro'yxati QO'LDA yozilgan

CONTRACTS "QO'SHIMCHA 3" ga ko'ra frontend turlari — javob shaklining
SHARTNOMASI (`frontend/src/types/analytics.ts` TO'LIQ yozilgan va `tsc`
toza). Shuning uchun bu fayldagi `*_FIELDS` to'plamlari aynan shu
TypeScript interfeyslaridan ko'chirilgan: backend schema'si maydonni
yo'qotsa yoki qayta nomlasa, test DARHOL yiqiladi — frontend `next build`
paytida emas, balki shu yerda.

Qo'shimcha maydon bo'lishi MUMKIN (zarar qilmaydi), shuning uchun
tekshiruv `issubset` bilan — qat'iy tenglik bilan EMAS.

## Nega testlar OCHIQ oraliq yuboradi (`recent_range()`)

`AnalyticsService._resolve_range()` `end` berilmasa `_quantized_now()` ni
oladi — bu HOZIRGI vaqtni kesh oynasi (`ANALYTICS_CACHE_TTL_SECONDS`)
boshiga TUSHIRILGAN qiymati. Ya'ni standart oraliqning `end` i o'tgan
daqiqa boshida turadi va hozir yaratilgan job unga TUSHMAYDI. Bu ataylab
(javob keshlanadigan bo'lishi uchun), lekin test uchun aniq oraliq
yuborish SHART — aks holda natija test qancha tez ishlashiga bog'liq
bo'lib qolardi.

## Bo'sh ma'lumot — alohida talab

Yangi foydalanuvchida bitta ham job yo'q. Analitika bunday holatda ham
200 qaytarishi SHART (nol bilan bo'lish, bo'sh ro'yxatdan `max()` olish
kabi xatolar bo'lmasligi kerak) — frontend dashboard'i birinchi kirishda
aynan shu javobni oladi.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING, Any

import pytest
from app.constants import FailureReason, JobStatus, Priority, Runtime
from app.utils.time_utils import utcnow

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from collections.abc import Awaitable, Callable

    import httpx
    from app.models.job import Job

pytestmark = pytest.mark.integration

#: `src/types/analytics.ts` -> `Overview`
OVERVIEW_FIELDS = frozenset(
    {
        "start",
        "end",
        "jobs",
        "executions",
        "usage",
        "dlq_depth",
        "queue_depth",
        "avg_queue_wait_ms",
        "jobs_change_percent",
    }
)

#: `src/types/analytics.ts` -> `JobStats`
JOB_STATS_FIELDS = frozenset(
    {
        "total",
        "by_status",
        "success",
        "failed",
        "cancelled",
        "dead_letter",
        "active",
        "success_rate",
        "avg_duration_ms",
    }
)

#: `src/types/analytics.ts` -> `ExecutionStats`
EXECUTION_STATS_FIELDS = frozenset(
    {"total", "avg_attempts", "retried", "lost", "timeout", "by_failure_reason"}
)

#: `src/types/analytics.ts` -> `UsageStats`
USAGE_STATS_FIELDS = frozenset(
    {
        "period",
        "job_count",
        "success_count",
        "failed_count",
        "execution_seconds",
        "monthly_limit",
        "usage_percent",
    }
)

#: `src/types/analytics.ts` -> `TimeSeriesResponse`
TIME_SERIES_FIELDS = frozenset(
    {"start", "end", "interval", "unit", "points", "total", "average", "peak"}
)

#: `src/types/analytics.ts` -> `SuccessRate`
SUCCESS_RATE_FIELDS = frozenset(
    {
        "start",
        "end",
        "interval",
        "total",
        "success",
        "failed",
        "cancelled",
        "dead_letter",
        "rate",
        "points",
        "breakdown",
    }
)

#: `src/types/analytics.ts` -> `LatencyStats`
LATENCY_FIELDS = frozenset(
    {
        "start",
        "end",
        "count",
        "min_ms",
        "max_ms",
        "avg_ms",
        "p50_ms",
        "p90_ms",
        "p95_ms",
        "p99_ms",
        "queue_wait_avg_ms",
        "queue_wait_p95_ms",
        "points",
    }
)

#: `src/types/analytics.ts` -> `TimeSeriesPoint`
POINT_FIELDS = frozenset({"timestamp", "value"})

#: `src/types/analytics.ts` -> `StatusSeriesPoint`
STATUS_POINT_FIELDS = POINT_FIELDS | {"success", "failed", "cancelled", "dead_letter"}

#: Barcha analitika yo'llari (bo'sh ma'lumot testi hammasini aylanadi).
ALL_PATHS = (
    "/analytics/overview",
    "/analytics/throughput",
    "/analytics/success-rate",
    "/analytics/latency",
    "/analytics/dlq-depth",
)


def recent_range() -> dict[str, str]:
    """Hozirgi paytni ICHIGA oladigan oraliq (modul docstring'iga qara)."""
    now = utcnow()
    return {
        "start": (now - timedelta(hours=1)).isoformat(),
        "end": (now + timedelta(minutes=1)).isoformat(),
    }


def assert_has(body: dict[str, Any], expected: frozenset[str], label: str) -> None:
    """`expected` maydonlarning HAMMASI javobda borligini talab qiladi."""
    missing = expected - set(body)
    assert not missing, f"{label}: yo'q maydonlar {sorted(missing)}"


async def test_overview_shape(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`/analytics/overview` frontend `Overview` turiga TO'LIQ mos."""
    await job_factory(status=JobStatus.SUCCESS, duration_ms=100, runtime=Runtime.PYTHON)
    await job_factory(status=JobStatus.FAILED, failure_reason=FailureReason.TIMEOUT)

    response = await client.get(
        f"{api_prefix}/analytics/overview", headers=auth_headers, params=recent_range()
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert_has(body, OVERVIEW_FIELDS, "Overview")
    assert_has(body["jobs"], JOB_STATS_FIELDS, "JobStats")
    assert_has(body["executions"], EXECUTION_STATS_FIELDS, "ExecutionStats")
    assert_has(body["usage"], USAGE_STATS_FIELDS, "UsageStats")

    assert body["jobs"]["total"] == 2
    assert body["jobs"]["success"] == 1
    assert body["jobs"]["failed"] == 1
    assert 0 <= body["jobs"]["success_rate"] <= 100
    # `queue_depth` kalitlari — `Priority` enum qiymatlari (frontend
    # `Partial<Record<Priority, number>>` kutadi), `delayed`/`total` YO'Q.
    assert set(body["queue_depth"]) <= {item.value for item in Priority}
    assert "delayed" not in body["queue_depth"]
    assert "total" not in body["queue_depth"]


async def test_throughput_shape(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """`/analytics/throughput` `TimeSeriesResponse` turiga mos."""
    response = await client.get(
        f"{api_prefix}/analytics/throughput?interval=hour", headers=auth_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert_has(body, TIME_SERIES_FIELDS, "TimeSeriesResponse")
    assert body["interval"] == "hour"
    assert body["unit"]
    assert body["points"]
    assert_has(body["points"][0], POINT_FIELDS, "TimeSeriesPoint")


async def test_success_rate_shape(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`/analytics/success-rate` `breakdown` ni `StatusSeriesPoint` bilan beradi."""
    await job_factory(status=JobStatus.SUCCESS, finished_at=utcnow())

    response = await client.get(
        f"{api_prefix}/analytics/success-rate?interval=day", headers=auth_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert_has(body, SUCCESS_RATE_FIELDS, "SuccessRate")
    assert 0 <= body["rate"] <= 100
    assert body["breakdown"]
    assert_has(body["breakdown"][0], STATUS_POINT_FIELDS, "StatusSeriesPoint")


async def test_latency_shape(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`/analytics/latency` persentillarni va `points` qatorini beradi."""
    now = utcnow()
    for duration in (10, 200, 3000):
        await job_factory(
            status=JobStatus.SUCCESS,
            duration_ms=duration,
            queued_at=now - timedelta(seconds=5),
            started_at=now - timedelta(seconds=4),
            finished_at=now,
        )

    response = await client.get(
        f"{api_prefix}/analytics/latency", headers=auth_headers, params=recent_range()
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert_has(body, LATENCY_FIELDS, "LatencyStats")
    assert body["count"] == 3
    assert body["min_ms"] == 10
    assert body["max_ms"] == 3000
    assert body["p50_ms"] is not None


async def test_dlq_depth_shape(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """`/analytics/dlq-depth` ham `TimeSeriesResponse` qaytaradi."""
    response = await client.get(
        f"{api_prefix}/analytics/dlq-depth?interval=day", headers=auth_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert_has(body, TIME_SERIES_FIELDS, "TimeSeriesResponse")
    assert body["interval"] == "day"


async def test_empty_data_does_not_fail(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Bitta ham job'i yo'q foydalanuvchida barcha yo'llar 200 qaytaradi."""
    for path in ALL_PATHS:
        response = await client.get(api_prefix + path, headers=auth_headers)
        assert response.status_code == 200, f"{path}: {response.text}"

    overview = await client.get(f"{api_prefix}/analytics/overview", headers=auth_headers)
    body = overview.json()
    assert body["jobs"]["total"] == 0
    assert body["jobs"]["success_rate"] == 0
    assert body["jobs"]["avg_duration_ms"] is None
    assert body["dlq_depth"] == 0

    latency = await client.get(f"{api_prefix}/analytics/latency", headers=auth_headers)
    assert latency.json()["count"] == 0
    assert latency.json()["p95_ms"] is None


async def test_range_over_limit_unprocessable(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """90 kundan uzun oraliq 422 beradi (`ANALYTICS_MAX_RANGE_DAYS`)."""
    now = utcnow()
    params = {"start": (now - timedelta(days=120)).isoformat(), "end": now.isoformat()}

    response = await client.get(
        f"{api_prefix}/analytics/overview", headers=auth_headers, params=params
    )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]["max_range_days"] == 90


async def test_reversed_range_unprocessable(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """`start > end` bo'lsa 422 beradi."""
    now = utcnow()
    params = {"start": now.isoformat(), "end": (now - timedelta(days=1)).isoformat()}

    response = await client.get(
        f"{api_prefix}/analytics/throughput", headers=auth_headers, params=params
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_unknown_interval_unprocessable(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """`interval` faqat `minute`/`hour`/`day` bo'ladi."""
    response = await client.get(
        f"{api_prefix}/analytics/throughput?interval=yil", headers=auth_headers
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_other_users_data_excluded(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    other_user: Any,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Analitika FAQAT so'rov egasining ma'lumotini hisoblaydi."""
    await job_factory(owner=other_user, status=JobStatus.SUCCESS)
    await job_factory(status=JobStatus.FAILED)

    response = await client.get(
        f"{api_prefix}/analytics/overview", headers=auth_headers, params=recent_range()
    )

    assert response.status_code == 200, response.text
    body = response.json()
    # Oraliqda IKKI job bor, lekin bittasi begona — faqat o'zi hisoblanadi.
    assert body["jobs"]["total"] == 1
    assert body["jobs"]["failed"] == 1
    assert body["jobs"]["success"] == 0


async def test_requires_authentication(client: httpx.AsyncClient, api_prefix: str) -> None:
    """Analitika yo'llari tokensiz 401 beradi."""
    for path in ALL_PATHS:
        response = await client.get(api_prefix + path)
        assert response.status_code == 401, f"{path}: {response.text}"


async def test_api_key_allowed(
    client: httpx.AsyncClient, api_prefix: str, api_key_headers: dict[str, str]
) -> None:
    """Analitika `X-API-Key` ni ham qabul qiladi (shartnomadagi "J/K")."""
    response = await client.get(f"{api_prefix}/analytics/overview", headers=api_key_headers)

    assert response.status_code == 200, response.text


__all__ = [
    "ALL_PATHS",
    "EXECUTION_STATS_FIELDS",
    "JOB_STATS_FIELDS",
    "LATENCY_FIELDS",
    "OVERVIEW_FIELDS",
    "POINT_FIELDS",
    "STATUS_POINT_FIELDS",
    "SUCCESS_RATE_FIELDS",
    "TIME_SERIES_FIELDS",
    "USAGE_STATS_FIELDS",
    "assert_has",
    "recent_range",
]
