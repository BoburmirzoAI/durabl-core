"""Durabl — analitika endpointlari (`/api/v1/analytics/*`).

Beshta ko'rsatkich: umumiy ko'rinish (`overview`), job oqimi
(`throughput`), muvaffaqiyat foizi (`success-rate`), kechikish
persentillari (`latency`) va DLQ chuqurligi (`dlq-depth`).

**Router hisob-kitob QILMAYDI.** Barcha agregatlar `AnalyticsService` da
(u repozitoriylarning guruhlangan so'rovlarini birlashtiradi va natijani
`settings.STATS_CACHE_TTL_SECONDS` davomida keshlaydi). Bu yerda faqat:
query parametrlarini olish -> servisni chaqirish -> javobga
`Cache-Control` qo'yish.

**Oraliq qoidalari** (hammasi servisda, shu yerda takrorlanmaydi):

* `?start`/`?end` berilmasa — oxirgi 24 soat;
* `start > end` yoki oraliq `settings.ANALYTICS_MAX_RANGE_DAYS` (90 kun)
  dan katta bo'lsa `ValidationError` -> **422**;
* `?interval` noto'g'ri bo'lsa yoki qator juda uzun bo'lsa ham 422.

**Keshlash ikki qatlamda.** Servis natijani Redis'da saqlaydi, javobga esa
`Cache-Control: private, max-age=<TTL>` qo'yiladi — brauzer dashboard'ni
qayta ochganda ayni so'rovni takrorlamaydi. `private`: javob FOYDALANUVCHI
kesimi, shuning uchun umumiy (proxy) keshda saqlanishi mumkin emas.
"""

from __future__ import annotations

from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Query, Response, status

from app.config import settings
from app.dependencies import AnalyticsSvc, CurrentUser, ScopeJobsRead
from app.schemas.analytics import (
    Interval,
    LatencyStats,
    OverviewResponse,
    SuccessRateResponse,
    TimeSeriesResponse,
)
from app.schemas.base import ErrorResponse, TimeRangeParams

#: Butun router API kalit uchun `jobs:read` doirasini talab qiladi.
#:
#: Analitika — job ma'lumotining agregatsiyasi, ya'ni o'qish huquqi.
#:
#: Darvoza ROUTER darajasida: yangi endpoint qo'shilganda u
#: avtomatik himoyalanadi va belgilashni unutib bo'lmaydi.
#: JWT bilan kirilganda scope tekshirilmaydi (`require_scope`).
router = APIRouter(
    prefix="/analytics",
    tags=["analytics"],
    dependencies=[ScopeJobsRead],
)

#: `Cache-Control` header nomi.
HEADER_CACHE_CONTROL: Final = "Cache-Control"

#: `?start=&end=` query dependency'si (`TimeRangeParams` maydonlari).
TimeRange = Annotated[TimeRangeParams, Depends()]

#: Vaqt qatorining qadami.
IntervalQuery = Annotated[
    Interval,
    Query(description="Vaqt qatori qadami: `minute`, `hour` yoki `day`"),
]

#: Barcha analitika endpointlari uchun umumiy xato javoblari.
ANALYTICS_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Autentifikatsiya talab qilinadi",
    },
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "model": ErrorResponse,
        "description": "Oraliq noto'g'ri yoki 90 kundan katta",
    },
}


def _set_cache_headers(response: Response) -> None:
    """Javobga qisqa muddatli shaxsiy kesh ruxsatini qo'yadi.

    `max-age` servisning kesh TTL'i bilan AYNI: brauzer serverdagi
    keshdan ko'proq eskirgan ma'lumotni ko'rsatmaydi.
    """
    response.headers[HEADER_CACHE_CONTROL] = f"private, max-age={settings.STATS_CACHE_TTL_SECONDS}"


@router.get(
    "/overview",
    response_model=OverviewResponse,
    status_code=status.HTTP_200_OK,
    summary="Umumiy ko'rinish",
    description=(
        "Dashboard bosh sahifasi uchun to'liq to'plam: job'lar, bajarish "
        "urinishlari va iste'mol kesimlari, DLQ chuqurligi, navbat holati. "
        "Oraliq berilmasa oxirgi 24 soat olinadi."
    ),
    responses=ANALYTICS_RESPONSES,
)
async def get_overview(
    user: CurrentUser,
    svc: AnalyticsSvc,
    response: Response,
    time_range: TimeRange,
) -> OverviewResponse:
    """Foydalanuvchining umumiy ko'rsatkichlari."""
    _set_cache_headers(response)
    return await svc.overview(user.id, start=time_range.start, end=time_range.end)


@router.get(
    "/throughput",
    response_model=TimeSeriesResponse,
    status_code=status.HTTP_200_OK,
    summary="Job oqimi",
    description=(
        "Vaqt bo'yicha yuborilgan job'lar soni. Vaqt o'qi — job qabul "
        "qilingan payt (`created_at`), birlik esa qadamga bog'liq "
        "(`jobs/hour`)."
    ),
    responses=ANALYTICS_RESPONSES,
)
async def get_throughput(
    user: CurrentUser,
    svc: AnalyticsSvc,
    response: Response,
    time_range: TimeRange,
    interval: IntervalQuery = "hour",
) -> TimeSeriesResponse:
    """Job oqimining vaqt qatori."""
    _set_cache_headers(response)
    return await svc.throughput(
        user_id=user.id,
        start=time_range.start,
        end=time_range.end,
        interval=interval,
    )


@router.get(
    "/success-rate",
    response_model=SuccessRateResponse,
    status_code=status.HTTP_200_OK,
    summary="Muvaffaqiyat foizi",
    description=(
        "Yakunlangan job'lar bo'yicha muvaffaqiyat foizi va uning "
        "dinamikasi. Bekor qilinganlar maxrajga kirmaydi; `breakdown` "
        "har bir interval uchun holatlar ajratmasini beradi."
    ),
    responses=ANALYTICS_RESPONSES,
)
async def get_success_rate(
    user: CurrentUser,
    svc: AnalyticsSvc,
    response: Response,
    time_range: TimeRange,
    interval: IntervalQuery = "hour",
) -> SuccessRateResponse:
    """Muvaffaqiyat foizi va holatlar ajratmasi."""
    _set_cache_headers(response)
    return await svc.success_rate(
        user_id=user.id,
        start=time_range.start,
        end=time_range.end,
        interval=interval,
    )


@router.get(
    "/latency",
    response_model=LatencyStats,
    status_code=status.HTTP_200_OK,
    summary="Kechikish persentillari",
    description=(
        "Job bajarilish vaqti (`p50`..`p99`, ms) va navbatda kutish "
        "ko'rsatkichlari. O'lchov bo'lmasa maydonlar `null` qaytadi — "
        "nol emas, chunki `0 ms` haqiqiy qiymat ma'nosini beradi."
    ),
    responses=ANALYTICS_RESPONSES,
)
async def get_latency(
    user: CurrentUser,
    svc: AnalyticsSvc,
    response: Response,
    time_range: TimeRange,
    interval: IntervalQuery = "hour",
) -> LatencyStats:
    """Kechikish statistikasi."""
    _set_cache_headers(response)
    return await svc.latency(
        user_id=user.id,
        start=time_range.start,
        end=time_range.end,
        interval=interval,
    )


@router.get(
    "/dlq-depth",
    response_model=TimeSeriesResponse,
    status_code=status.HTTP_200_OK,
    summary="DLQ chuqurligi",
    description=(
        "Hal qilinmagan DLQ yozuvlarining vaqt bo'yicha o'sishi "
        "(kumulyativ qator, birlik — `entries`). Oxirgi nuqta joriy "
        "chuqurlikka mos keladi."
    ),
    responses=ANALYTICS_RESPONSES,
)
async def get_dlq_depth(
    user: CurrentUser,
    svc: AnalyticsSvc,
    response: Response,
    time_range: TimeRange,
    interval: IntervalQuery = "hour",
) -> TimeSeriesResponse:
    """DLQ chuqurligining vaqt qatori."""
    _set_cache_headers(response)
    return await svc.dlq_depth_series(
        user_id=user.id,
        start=time_range.start,
        end=time_range.end,
        interval=interval,
    )


__all__ = ["router"]
