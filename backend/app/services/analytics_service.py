"""Durabl — analitika va kuzatuvchanlik (observability) servisi.

Bu servis dashboard va `/api/v1/analytics/*` endpointlari uchun ko'rsatkichlar
tayyorlaydi: throughput, muvaffaqiyat foizi, latency persentillari, DLQ
chuqurligi va tizimning umumiy sog'lig'i.

**Hisob-kitobning asosiy qismi repozitoriylarda.** Job agregatlari tayyor
metodlar orqali bajariladi (`JobRepository.stats_overview`,
`throughput_series`, `latency_percentiles`, `count_by_status`,
`DlqRepository.depth`, `group_by_reason`). Servis ularni birlashtiradi,
schema'ga aylantiradi va keshlaydi.

**Repozitoriyda metodi BO'LMAGAN agregatlar shu yerda `select()` bilan
hisoblanadi** (`CONTRACTS.md` "QO'SHIMCHA 3" ko'rsatmasi): bajarish
urinishlari kesimi (`executions`), navbatda kutish vaqti, DLQ
ko'rsatkichlari (`added_last_24h`, `oldest_failed_at`) va admin
agregatlari (`admin_stats`, `admin_users`, `audit_logs`).
**Ularning hammasi GURUHLANGAN bitta so'rov bilan olinadi va keyin
lug'atdan to'ldiriladi — N+1 so'rov YO'Q.** Mavjud repozitoriy fayllariga
tegilmaydi (ular boshqa agentning mas'uliyati).

**Shakl manbai — frontend.** Javob schema'lari `frontend/src/types/*.ts`
ta'riflariga AYNAN moslashtirilgan, shuning uchun bu servis to'ldiradigan
maydonlar ro'yxatini o'zgartirish frontend'ni buzadi.

**Keshlash.** Og'ir agregatlar `CacheService` orqali `namespace="stats"` da
`settings.STATS_CACHE_TTL_SECONDS` davomida saqlanadi. Kesh kaliti METRIKA
NOMI bilan boshlanadi (`overview:...`, `throughput:...`): aks holda bir xil
oraliq uchun `overview` va `throughput` AYNI kalitga tushib, bir-birining
javobini qaytarardi.

**Standart oraliq kvantlangan.** Oraliq berilmasa oxirgi 24 soat olinadi,
lekin `end` kesh oynasiga (`STATS_CACHE_TTL_SECONDS`) tushiriladi
(`_quantized_now`). Busiz `end = utcnow()` har mikrosekundda o'zgarib,
kesh kaliti HAR DOIM yangi bo'lardi — ya'ni kesh umuman ishlamasdi.
Hisob-kitob ham ayni kvantlangan oraliqda bajariladi, shuning uchun
keshlangan javob o'z kalitiga to'liq mos keladi (oxirgi bir necha soniya
ma'lumoti 24 soatlik oyna uchun ahamiyatsiz).

**Bo'sh oraliqlar nol bilan to'ldiriladi** (`fill_series`): frontend
grafigida (Recharts) uzilish bo'lmasligi uchun vaqt o'qi uzluksiz qaytadi.

**Infratuzilma uzilishi javobni to'xtatmaydi.** Analitika — faqat kuzatuv
yo'li. Redis javob bermasa navbat chuqurligi nol, worker ro'yxati bo'sh
qaytadi va `warning` log qilinadi; umumiy javob baribir beriladi. Faqat
PostgreSQL xatolari tashqariga chiqadi (ular haqiqiy ma'lumot manbai).

Servis DB'ga YOZMAYDI va `commit()` QILMAYDI — barcha metodlari faqat o'qish.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Final

from pydantic import ValidationError as PydanticValidationError
from redis.exceptions import RedisError
from sqlalchemy import case, distinct, func, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.constants import (
    PLAN_LIMITS,
    AuditAction,
    ExecutionStatus,
    FailureReason,
    JobStatus,
    PlanType,
    Priority,
    RedisKeys,
)
from app.database import check_db_health
from app.exceptions import DatabaseError, DurablError, ValidationError
from app.logging_config import get_logger
from app.metrics import set_active_workers, set_dlq_depth
from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.dlq_entry import DlqEntry
from app.models.execution import Execution
from app.models.job import Job
from app.models.subscription import Subscription
from app.models.usage_record import UsageRecord
from app.models.user import User
from app.redis_client import check_redis_health, get_redis
from app.repositories.dlq_repo import DlqRepository
from app.repositories.job_repo import JobRepository
from app.repositories.usage_repo import UsageRepository
from app.schemas.admin import (
    CHECK_DATABASE,
    CHECK_REDIS,
    CHECK_SANDBOX,
    AdminStats,
    AdminUserRead,
    AuditLogRead,
    QueueDepth,
    SystemStatus,
    WorkerInfo,
)
from app.schemas.analytics import (
    ExecutionStats,
    Interval,
    JobStats,
    LatencyStats,
    OverviewResponse,
    StatusSeriesPoint,
    SuccessRateResponse,
    TimeSeriesPoint,
    TimeSeriesResponse,
    UsageStats,
)
from app.schemas.dlq import DlqStats
from app.services.billing_service import BillingService
from app.services.cache_service import CacheService
from app.services.queue_service import QueueService
from app.services.reliability_service import ReliabilityService
from app.services.sandbox_service import SandboxService
from app.utils.time_utils import (
    ensure_utc,
    from_timestamp,
    isoformat,
    month_key,
    start_of_day,
    start_of_month,
    utcnow,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping, Sequence

    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Konstantalar
# ---------------------------------------------------------------------------

#: Kesh namespace'i — `CacheService.invalidate("stats")` butun analitikani tozalaydi.
CACHE_NAMESPACE: Final = "stats"

#: Oraliq berilmaganda standart chuqurlik (soat).
DEFAULT_RANGE_HOURS: Final = 24

#: Qo'llab-quvvatlanadigan qadamlar — `app.schemas.analytics.Interval` bilan AYNI.
#: `JobRepository.throughput_series` `"month"` ni ham biladi, lekin schema uni
#: qabul qilmaydi, shuning uchun servis darajasida rad etiladi.
SUPPORTED_INTERVALS: Final[tuple[str, ...]] = ("minute", "hour", "day")

#: Qadam -> `timedelta`. UTC ishlatilgani uchun "kun" har doim aynan 24 soat.
INTERVAL_DELTAS: Final[dict[str, timedelta]] = {
    "minute": timedelta(minutes=1),
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
}

#: Bitta vaqt qatorida maksimal nuqta soni. 90 kunlik oraliq + `minute` qadami
#: 129 601 nuqta berardi — bu JSON javobni o'nlab megabaytga oshirib,
#: brauzerni ham bloklaydi. Chegara oshsa `ValidationError` (mijoz qadamni
#: kattalashtirishi kerak). 90 kun x `hour` = 2 161 nuqta — sig'adi.
MAX_SERIES_POINTS: Final = 5_000

#: `slowest_jobs` bitta so'rovda nechta yozuv o'qiydi.
SLOWEST_PAGE_SIZE: Final = 100

#: `slowest_jobs` ko'pi bilan nechta sahifa aylanadi (quyidagi izohga qara).
SLOWEST_MAX_PAGES: Final = 5

#: `slowest_jobs` qabul qiladigan maksimal `limit`.
MAX_SLOWEST_LIMIT: Final = 100

#: `top_failure_reasons` qabul qiladigan maksimal `limit`.
MAX_REASON_LIMIT: Final = 50

#: DLQ qatorini qurishda bitta sahifa hajmi va maksimal sahifa soni.
DLQ_SERIES_PAGE_SIZE: Final = 500
DLQ_SERIES_MAX_PAGES: Final = 20

#: `active_leases()` dagi `SCAN` qadami (`KEYS` ISHLATILMAYDI — u Redis'ni bloklaydi).
LEASE_SCAN_COUNT: Final = 500

#: `duration_ms` to'ldirilgan bo'lishi KUTILADIGAN yakuniy holatlar.
FINISHED_JOB_STATUSES: Final[tuple[JobStatus, ...]] = (
    JobStatus.SUCCESS,
    JobStatus.FAILED,
    JobStatus.DEAD_LETTER,
)

#: Latency va navbatda kutish namunasining maksimal hajmi.
#: Nega namuna: `started_at - queued_at` ayirmasi PostgreSQL va SQLite'da
#: TURLICHA SQL talab qiladi (`EXTRACT(EPOCH ...)` / `julianday()`), p95
#: esa SQLite'da umuman yo'q. Shuning uchun eng yangi N yozuv o'qiladi va
#: hisob Python tomonida bajariladi — natija ikki dialektda AYNI bo'ladi.
LATENCY_SAMPLE_SIZE: Final = 5_000

#: "Oxirgi sutka" oynasi — `AdminStats.jobs_24h`, `DlqStats.added_last_24h`.
RECENT_WINDOW_HOURS: Final = 24

#: `AdminStats.new_users_7d` oynasi (kun).
NEW_USERS_WINDOW_DAYS: Final = 7

#: Admin ro'yxatlarining maksimal sahifa hajmi.
MAX_ADMIN_PAGE_SIZE: Final = 200

#: `admin_users()` da ruxsat etilgan tartiblash ustunlari.
ADMIN_USER_SORT_FIELDS: Final[frozenset[str]] = frozenset(
    {"created_at", "updated_at", "email", "last_login_at"}
)

#: `audit_logs()` da ruxsat etilgan tartiblash ustunlari.
AUDIT_LOG_SORT_FIELDS: Final[frozenset[str]] = frozenset({"created_at", "action"})

#: Protsess ishga tushgan vaqt — `SystemStatus.uptime_seconds` uchun.
#: Modul import vaqtida bir marta hisoblanadi.
_STARTED_AT: Final[datetime] = utcnow()


# ---------------------------------------------------------------------------
# Vaqt qatori yordamchilari (modul darajasida — testlardan ham ishlatiladi)
# ---------------------------------------------------------------------------


def interval_delta(interval: str) -> timedelta:
    """Qadam nomini `timedelta`ga aylantiradi.

    Raises:
        ValidationError: Qadam qo'llab-quvvatlanmasa.
    """
    try:
        return INTERVAL_DELTAS[interval]
    except KeyError as exc:
        raise ValidationError(
            f"'{interval}' oralig'i qo'llab-quvvatlanmaydi",
            details={"allowed": list(SUPPORTED_INTERVALS)},
        ) from exc


def floor_to_interval(moment: datetime, interval: str) -> datetime:
    """Vaqtni qadam boshiga tushiradi (savat chegarasi).

    `JobRepository.throughput_series` DB tomonida AYNI chegaralarni beradi
    (`date_trunc` / `strftime`), shuning uchun savatlar bir-biriga aniq
    mos tushadi va to'ldirish paytida nuqta "yo'qolmaydi".
    """
    aware = ensure_utc(moment)
    if aware is None:  # pragma: no cover - `moment` har doim beriladi
        raise ValidationError("Savat chegarasi uchun vaqt berilmadi")
    if interval == "minute":
        return aware.replace(second=0, microsecond=0)
    if interval == "hour":
        return aware.replace(minute=0, second=0, microsecond=0)
    if interval == "day":
        return aware.replace(hour=0, minute=0, second=0, microsecond=0)
    raise ValidationError(
        f"'{interval}' oralig'i qo'llab-quvvatlanmaydi",
        details={"allowed": list(SUPPORTED_INTERVALS)},
    )


def expected_point_count(start: datetime, end: datetime, interval: str) -> int:
    """`fill_series` qaytaradigan nuqtalar sonini OLDINDAN hisoblaydi.

    So'rov bajarilishidan oldin chegarani tekshirish uchun kerak — og'ir
    SQL'ni bajarib, keyin javobni rad etish ma'nosiz.
    """
    step = interval_delta(interval)
    first = floor_to_interval(start, interval)
    last = floor_to_interval(end, interval)
    if last < first:
        return 0
    return int((last - first) // step) + 1


def fill_series(
    values: Mapping[datetime, float],
    *,
    start: datetime,
    end: datetime,
    interval: str,
) -> list[TimeSeriesPoint]:
    """Vaqt qatorini BO'SH oraliqlarni nol bilan to'ldirib qaytaradi.

    `values` kalitlari savat boshlanish vaqtlari bo'lishi kerak (ya'ni
    `floor_to_interval` dan o'tgan). Natijada `floor(start)` dan
    `floor(end)` gacha HAR BIR savat uchun nuqta bo'ladi — ikki chegara
    ham kiritiladi.

    Nega kerak: SQL `GROUP BY` faqat YOZUVI BOR savatlarni qaytaradi.
    Ularni to'g'ridan-to'g'ri grafikka berish "sakrab ketgan" vaqt o'qini
    beradi (soat 14 dan keyin darhol soat 19), ya'ni grafik yolg'on
    ko'rsatadi. Nol bilan to'ldirish bu xatoni yo'q qiladi.
    """
    step = interval_delta(interval)
    cursor = floor_to_interval(start, interval)
    last = floor_to_interval(end, interval)
    points: list[TimeSeriesPoint] = []
    while cursor <= last and len(points) < MAX_SERIES_POINTS:
        points.append(
            TimeSeriesPoint(timestamp=cursor, value=float(values.get(cursor, 0.0)))
        )
        cursor = cursor + step
    return points


def bucket_timeline(start: datetime, end: datetime, interval: str) -> list[datetime]:
    """Oraliqdagi barcha savat chegaralarini (ikki uchi bilan) qaytaradi."""
    step = interval_delta(interval)
    cursor = floor_to_interval(start, interval)
    last = floor_to_interval(end, interval)
    buckets: list[datetime] = []
    while cursor <= last and len(buckets) < MAX_SERIES_POINTS:
        buckets.append(cursor)
        cursor = cursor + step
    return buckets


def percentile(values: Sequence[float], fraction: float) -> float | None:
    """Chiziqli interpolyatsiyali persentil (`percentile_cont` semantikasi).

    `JobRepository` SQLite'da AYNI usuldan foydalanadi, shuning uchun
    namunadan hisoblangan qiymat repozitoriy qiymati bilan bir xil
    ma'noga ega bo'ladi.

    Args:
        values: Qiymatlar (tartiblanmagan bo'lishi mumkin).
        fraction: `0.0`–`1.0` oralig'idagi kesim (`0.95` -> p95).

    Returns:
        Persentil qiymati yoki `None` (namuna bo'sh bo'lsa).
    """
    if not values:
        return None
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return round(ordered[0], 2)
    position = max(0.0, min(1.0, fraction)) * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return round(ordered[lower] + (ordered[upper] - ordered[lower]) * weight, 2)


@dataclass(frozen=True, slots=True)
class UserTotals:
    """`admin_stats()` uchun foydalanuvchilar kesimi (bitta so'rov natijasi)."""

    total: int = 0
    active: int = 0
    admins: int = 0
    recent: int = 0


@dataclass(frozen=True, slots=True)
class PlanTotals:
    """`admin_stats()` uchun rejalar kesimi va oylik daromad.

    `counts` — reja qiymati -> obuna yozuvlari soni (hammasi, faol
    bo'lmaganlari ham); `mrr_usd` esa FAQAT amaldagi obunalar narxlari
    yig'indisi.
    """

    counts: dict[str, int] = field(default_factory=dict)
    mrr_usd: float = 0.0


@dataclass(slots=True)
class LatencySample:
    """Yakunlangan job'lardan o'qilgan namuna (latency + navbatda kutish).

    `durations` — `jobs.duration_ms` qiymatlari; `queue_waits` — navbatda
    kutish (`started_at - queued_at`) millisekundda; `by_bucket` esa
    davomiyliklarning vaqt savatlari bo'yicha taqsimoti (p95 qatori uchun).
    """

    durations: list[float] = field(default_factory=list)
    queue_waits: list[float] = field(default_factory=list)
    by_bucket: dict[datetime, list[float]] = field(default_factory=dict)

    @property
    def queue_wait_avg_ms(self) -> float | None:
        """Navbatda kutishning o'rtacha vaqti (ms); namuna bo'sh bo'lsa `None`."""
        if not self.queue_waits:
            return None
        return round(sum(self.queue_waits) / len(self.queue_waits), 2)

    @property
    def queue_wait_p95_ms(self) -> float | None:
        """Navbatda kutishning 95-persentili (ms)."""
        return percentile(self.queue_waits, 0.95)

    def p95_points(self) -> list[TimeSeriesPoint]:
        """Savat -> p95 davomiylik qatori (vaqt bo'yicha o'sish tartibida).

        BO'SH savatlar nol bilan TO'LDIRILMAYDI: latency uchun "nol" —
        "juda tez" degan ma'no beradi, holbuki haqiqatda o'lchov yo'q.
        Shuning uchun faqat ma'lumoti bor savatlar qaytadi.
        """
        points: list[TimeSeriesPoint] = []
        for bucket in sorted(self.by_bucket):
            value = percentile(self.by_bucket[bucket], 0.95)
            if value is None:  # pragma: no cover - bo'sh ro'yxat saqlanmaydi
                continue
            points.append(TimeSeriesPoint(timestamp=bucket, value=value))
        return points


# ---------------------------------------------------------------------------
# Servis
# ---------------------------------------------------------------------------


class AnalyticsService:
    """Dashboard ko'rsatkichlari va tizim holati.

    `user_id=None` — butun platforma bo'yicha (admin ko'rinishi);
    `user_id` berilsa faqat shu foydalanuvchining ma'lumoti.

    Barcha metodlar faqat O'QIYDI: DB'ga yozmaydi, `commit()` qilmaydi,
    shuning uchun ularni boshqa service ichidan chaqirish xavfsiz.
    """

    def __init__(self, session: AsyncSession, redis: Redis | None = None) -> None:
        self.session = session
        self.redis: Redis = redis or get_redis()
        self.jobs = JobRepository(session)
        self.dlq = DlqRepository(session)
        #: Oylik iste'mol yozuvlari — FAQAT o'qish uchun (`get_for_period`,
        #: `current_period` EMAS: ikkinchisi yozuv yaratadi).
        self.usage_records = UsageRepository(session)
        #: Reja limitlari uchun (`limits_for` faqat o'qiydi va `commit`
        #: qilmaydi) — reja/muddat mantig'i bitta joyda qolishi uchun.
        self.billing = BillingService(session)
        self.cache = CacheService(self.redis)
        self.queue = QueueService(self.redis)
        self.reliability = ReliabilityService(session, self.redis)
        #: `SandboxService` DANGASA yaratiladi: u Docker klientiga tegishi
        #: mumkin, analitikaning qolgan 8 metodi uchun esa umuman kerak emas.
        self._sandbox: SandboxService | None = None

    # ------------------------------------------------------------------
    # Umumiy ko'rinish
    # ------------------------------------------------------------------

    async def overview(
        self,
        user_id: uuid.UUID | str | None = None,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> OverviewResponse:
        """Dashboard bosh sahifasining to'liq to'plami.

        Tarkibi (frontend `Overview` turi bilan AYNI): oraliq chegaralari,
        `jobs` / `executions` / `usage` bloklari, DLQ chuqurligi, ustuvorlik
        bo'yicha navbat chuqurligi, navbatda kutishning o'rtacha vaqti va
        oldingi AYNI uzunlikdagi davrga nisbatan o'zgarish foizi.

        `user_id` POZITSION ham uzatilishi mumkin — CONTRACTS.md §6 dagi
        imzo (`overview(user_id=None, *, start=None, end=None)`) aynan
        shunday, ya'ni API qatlami `overview(user.id)` deb chaqirsa ham
        ishlaydi. Qolgan parametrlar faqat kalit so'z bilan.

        `user_id=None` — butun platforma kesimi (admin): bunda `usage`
        bloki BARCHA foydalanuvchilarning joriy oydagi yig'indisi bo'ladi
        va `monthly_limit` nol qaytadi (platformaga reja limiti qo'llanmaydi).
        """
        resolved_start, resolved_end = self._resolve_range(start, end)
        scope = self._scope(user_id)
        key = f"overview:{scope}:{resolved_start.isoformat()}:{resolved_end.isoformat()}"

        async def factory() -> dict[str, Any]:
            response = await self._build_overview(
                user_id=user_id, start=resolved_start, end=resolved_end
            )
            return response.model_dump(mode="json")

        payload = await self._cached(key, factory)
        return OverviewResponse.model_validate(payload)

    async def comparison(
        self,
        *,
        user_id: uuid.UUID | str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, Any]:
        """Oraliqni AYNI uzunlikdagi oldingi davr bilan solishtiradi.

        `OverviewResponse.jobs_change_percent` faqat job SONI o'zgarishini
        beradi; bu metod esa muvaffaqiyat foizining o'zgarishini va ikki
        davrning xom qiymatlarini ham qaytaradi (API qatlami uni mustaqil
        endpoint sifatida ishlatishi mumkin).

        Returns:
            `{"current": {...}, "previous": {...}, "jobs_change_percent": float,
            "success_rate_change": float, "start", "end",
            "previous_start", "previous_end"}`. O'zgarish foizi oldingi davr
            noldan iborat bo'lsa: joriy davr ham nol -> `0.0`, aks holda
            `100.0` (noldan o'sishni foizda ifodalash mumkin emas).
        """
        resolved_start, resolved_end = self._resolve_range(start, end)
        span = resolved_end - resolved_start
        previous_end = resolved_start
        previous_start = resolved_start - span
        scope = self._scope(user_id)
        key = f"comparison:{scope}:{resolved_start.isoformat()}:{resolved_end.isoformat()}"

        async def factory() -> dict[str, Any]:
            current = await self.jobs.stats_overview(
                user_id=user_id, start=resolved_start, end=resolved_end
            )
            previous = await self.jobs.stats_overview(
                user_id=user_id, start=previous_start, end=previous_end
            )
            return {
                "current": {
                    "total": int(current["total"]),
                    "success_rate": float(current["success_rate"]),
                },
                "previous": {
                    "total": int(previous["total"]),
                    "success_rate": float(previous["success_rate"]),
                },
                "jobs_change_percent": self._change_percent(
                    int(previous["total"]), int(current["total"])
                ),
                "success_rate_change": round(
                    float(current["success_rate"]) - float(previous["success_rate"]), 2
                ),
                "start": isoformat(resolved_start),
                "end": isoformat(resolved_end),
                "previous_start": isoformat(previous_start),
                "previous_end": isoformat(previous_end),
            }

        payload = await self._cached(key, factory)
        return dict(payload)

    # ------------------------------------------------------------------
    # Vaqt qatorlari
    # ------------------------------------------------------------------

    async def throughput(
        self,
        *,
        user_id: uuid.UUID | str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        interval: Interval = "hour",
    ) -> TimeSeriesResponse:
        """Vaqt bo'yicha job oqimi (nechta job yuborilgan).

        Vaqt o'qi — `created_at` (job QABUL QILINGAN payt), chunki
        throughput "platformaga qancha yuklama keldi" degan savolga javob
        beradi; `finished_at` esa yakunlanish oqimini ko'rsatadi.
        """
        resolved_start, resolved_end = self._resolve_range(start, end)
        step = self._resolve_interval(interval, resolved_start, resolved_end)
        scope = self._scope(user_id)
        key = (
            f"throughput:{scope}:{resolved_start.isoformat()}"
            f":{resolved_end.isoformat()}:{step}"
        )

        async def factory() -> dict[str, Any]:
            series = await self.jobs.throughput_series(
                user_id=user_id,
                start=resolved_start,
                end=resolved_end,
                interval=step,
                time_column="created_at",
            )
            buckets = self._bucketed(series, field="total", interval=step)
            response = TimeSeriesResponse(
                metric="throughput",
                interval=step,
                points=fill_series(
                    buckets, start=resolved_start, end=resolved_end, interval=step
                ),
                start=resolved_start,
                end=resolved_end,
                #: Birlik qadamga bog'liq: `jobs/min`, `jobs/hour`, `jobs/day`.
                #: Shu matn grafik o'qining yozuvi bo'lib chiqadi.
                unit=self._series_unit("jobs", step),
            )
            return response.model_dump(mode="json")

        payload = await self._cached(key, factory)
        return TimeSeriesResponse.model_validate(payload)

    async def success_rate(
        self,
        *,
        user_id: uuid.UUID | str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        interval: Interval = "hour",
    ) -> SuccessRateResponse:
        """Muvaffaqiyat foizi va uning vaqt bo'yicha dinamikasi.

        Foiz YAKUNLANGAN job'lar bo'yicha hisoblanadi:
        `success / (success + failed + dead_letter) * 100`. Bekor qilinganlar
        va hali ishlayotganlar maxrajga kirmaydi — aks holda navbat o'sganda
        "sifat tushdi" degan yolg'on signal chiqardi. `cancelled` baribir
        javobda beriladi (frontend uni alohida ustun sifatida ko'rsatadi).

        `breakdown` — har bir savat uchun holatlar ajratmasi (stacked
        grafik). U UCHTA guruhlangan so'rovdan yig'iladi: umumiy qator,
        `cancelled` qatori va `dead_letter` qatori. `JobRepository`
        `failed` ustunida FAILED va DEAD_LETTER ni birga sanaydi, shuning
        uchun "faqat failed" = `failed - dead_letter`.

        `top_failure_reasons` DLQ yozuvlaridan olinadi va VAQT BO'YICHA
        FILTRLANMAYDI (`DlqRepository.group_by_reason` oraliq qabul qilmaydi) —
        ya'ni u "hozirgi holat" kesimi.
        """
        resolved_start, resolved_end = self._resolve_range(start, end)
        step = self._resolve_interval(interval, resolved_start, resolved_end)
        scope = self._scope(user_id)
        key = (
            f"success_rate:{scope}:{resolved_start.isoformat()}"
            f":{resolved_end.isoformat()}:{step}"
        )

        async def factory() -> dict[str, Any]:
            stats = await self.jobs.stats_overview(
                user_id=user_id, start=resolved_start, end=resolved_end
            )
            series = await self.jobs.throughput_series(
                user_id=user_id,
                start=resolved_start,
                end=resolved_end,
                interval=step,
                time_column="created_at",
            )
            cancelled_series = await self.jobs.throughput_series(
                user_id=user_id,
                start=resolved_start,
                end=resolved_end,
                interval=step,
                time_column="created_at",
                status=JobStatus.CANCELLED,
            )
            dead_series = await self.jobs.throughput_series(
                user_id=user_id,
                start=resolved_start,
                end=resolved_end,
                interval=step,
                time_column="created_at",
                status=JobStatus.DEAD_LETTER,
            )
            reasons = await self._reason_counts(user_id)

            by_status: dict[str, int] = stats["by_status"]
            succeeded = int(by_status[JobStatus.SUCCESS.value])
            only_failed = int(by_status[JobStatus.FAILED.value])
            dead_letter = int(by_status[JobStatus.DEAD_LETTER.value])
            cancelled = int(by_status[JobStatus.CANCELLED.value])

            rows = self._rows_by_bucket(series, interval=step)
            cancelled_by_bucket = self._bucketed(
                cancelled_series, field="total", interval=step
            )
            dead_by_bucket = self._bucketed(dead_series, field="total", interval=step)
            buckets = {
                bucket: self._ratio(row["success"], row["success"] + row["failed"])
                for bucket, row in rows.items()
            }
            response = SuccessRateResponse(
                rate=float(stats["success_rate"]),
                total=succeeded + only_failed + dead_letter,
                success=succeeded,
                failed=only_failed,
                cancelled=cancelled,
                dead_letter=dead_letter,
                interval=step,
                points=fill_series(
                    buckets, start=resolved_start, end=resolved_end, interval=step
                ),
                breakdown=self._status_breakdown(
                    rows,
                    cancelled=cancelled_by_bucket,
                    dead_letter=dead_by_bucket,
                    start=resolved_start,
                    end=resolved_end,
                    interval=step,
                ),
                top_failure_reasons=reasons,
                start=resolved_start,
                end=resolved_end,
            )
            return response.model_dump(mode="json")

        payload = await self._cached(key, factory)
        return SuccessRateResponse.model_validate(payload)

    async def dlq_depth_series(
        self,
        *,
        user_id: uuid.UUID | str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        interval: Interval = "hour",
    ) -> TimeSeriesResponse:
        """DLQ chuqurligining vaqt bo'yicha o'sishi.

        **Qanday qurilgani (muhim).** "DLQ chuqurligi" =
        `DlqRepository.depth()` semantikasi, ya'ni HAL QILINMAGAN yozuvlar
        soni. Tarixiy snapshot jadvali yo'q, shuning uchun qator HOZIR hal
        qilinmagan yozuvlarning `failed_at` vaqti bo'yicha kumulyativ
        o'sishi sifatida tiklanadi:

        * `baseline` = oraliq boshlanishidan OLDIN tushgan va hamon hal
          qilinmagan yozuvlar soni;
        * har bir savatda shu savatda tushgan (hamon hal qilinmagan)
          yozuvlar qo'shiladi.

        Shu tufayli qator monoton o'sadi va oxirgi nuqta joriy chuqurlikka
        mos tushadi. Hal QILINGAN yozuvlar qatorga kirmaydi: ularning
        `resolved_at` tarixini savatlarga aniq taqsimlash uchun alohida
        snapshot jadvali kerak (`DlqRepository`da bunday metod yo'q).
        """
        resolved_start, resolved_end = self._resolve_range(start, end)
        step = self._resolve_interval(interval, resolved_start, resolved_end)
        scope = self._scope(user_id)
        key = (
            f"dlq_depth:{scope}:{resolved_start.isoformat()}"
            f":{resolved_end.isoformat()}:{step}"
        )

        async def factory() -> dict[str, Any]:
            response = await self._build_dlq_series(
                user_id=user_id,
                start=resolved_start,
                end=resolved_end,
                interval=step,
            )
            return response.model_dump(mode="json")

        payload = await self._cached(key, factory)
        return TimeSeriesResponse.model_validate(payload)

    # ------------------------------------------------------------------
    # Jamlangan kesimlar
    # ------------------------------------------------------------------

    async def latency(
        self,
        *,
        user_id: uuid.UUID | str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        interval: Interval = "hour",
    ) -> LatencyStats:
        """Bajarish davomiyligi va navbatda kutish ko'rsatkichlari.

        Bosh persentillar (`min_ms`...`p99_ms`, `count`) —
        `JobRepository.latency_percentiles` dan: PostgreSQL'da
        `percentile_cont`, SQLite'da ayni semantikadagi Python
        interpolyatsiyasi bilan. `duration_ms` to'ldirilmagan job'lar
        hisobga olinmaydi.

        `queue_wait_*` va vaqt bo'yicha p95 qatori (`points`) esa
        chegaralangan NAMUNADAN (`LATENCY_SAMPLE_SIZE`) hisoblanadi —
        sababi konstanta izohida. Shuning uchun juda katta oraliqda
        `points` eng yangi N job'ni tasvirlaydi, `count` esa oraliqdagi
        HAMMA job'ni sanaydi.
        """
        resolved_start, resolved_end = self._resolve_range(start, end)
        step = self._resolve_interval(interval, resolved_start, resolved_end)
        scope = self._scope(user_id)
        key = (
            f"latency:{scope}:{resolved_start.isoformat()}"
            f":{resolved_end.isoformat()}:{step}"
        )

        async def factory() -> dict[str, Any]:
            stats = await self._latency_stats(
                user_id=user_id,
                start=resolved_start,
                end=resolved_end,
                interval=step,
            )
            return stats.model_dump(mode="json")

        payload = await self._cached(key, factory)
        return LatencyStats.model_validate(payload)

    async def status_distribution(
        self,
        *,
        user_id: uuid.UUID | str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> dict[str, int]:
        """Holatlar kesimidagi job sonlari: `{"pending": 3, "success": 10, ...}`.

        Natijada `JobStatus` ning BARCHA qiymatlari bor (yozuvi bo'lmagani
        `0` bilan) — frontend grafigi kalit yo'qligidan qulamasligi uchun.
        """
        resolved_start, resolved_end = self._resolve_range(start, end)
        scope = self._scope(user_id)
        key = (
            f"status_distribution:{scope}:{resolved_start.isoformat()}"
            f":{resolved_end.isoformat()}"
        )

        async def factory() -> dict[str, int]:
            stats = await self.jobs.stats_overview(
                user_id=user_id, start=resolved_start, end=resolved_end
            )
            by_status: dict[str, int] = stats["by_status"]
            return {status.value: int(by_status[status.value]) for status in JobStatus}

        payload = await self._cached(key, factory)
        return {str(name): int(count) for name, count in dict(payload).items()}

    async def slowest_jobs(
        self,
        *,
        user_id: uuid.UUID | str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Eng uzoq bajarilgan job'lar (optimizatsiya uchun "qaynoq nuqtalar").

        **Nega sahifalab o'qiladi.** `JobRepository.search()` da
        `duration_ms IS NOT NULL` filtri yo'q, `NULL` qiymatlarning
        tartibi esa dialektga BOG'LIQ: PostgreSQL `DESC` da `NULLS FIRST`,
        SQLite'da `NULL` eng kichik, ya'ni `DESC` da oxirida. Shuning uchun
        yakunlangan holatlar bo'yicha filtrlangan natija chegaralangan
        sahifalarda o'qiladi (`SLOWEST_MAX_PAGES` x `SLOWEST_PAGE_SIZE`),
        `duration_ms` bo'sh yozuvlar Python tomonida chiqarib tashlanadi va
        yakuniy tartib ham Python tomonida qo'yiladi — natija ikki dialektda
        AYNI bo'ladi.
        """
        bounded = max(1, min(int(limit), MAX_SLOWEST_LIMIT))
        scope = self._scope(user_id)
        key = f"slowest_jobs:{scope}:{bounded}"

        async def factory() -> list[dict[str, Any]]:
            return await self._collect_slowest(user_id=user_id, limit=bounded)

        payload = await self._cached(key, factory)
        return [dict(row) for row in list(payload)]

    async def top_failure_reasons(
        self,
        *,
        user_id: uuid.UUID | str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Eng ko'p uchragan muvaffaqiyatsizlik sabablari (DLQ bo'yicha).

        Manba — `DlqRepository.group_by_reason()`: ya'ni BARCHA urinishlari
        tugab DLQ'ga tushgan job'lar. Bu `jobs.failure_reason` dan ataylab
        farq qiladi — bir marta yiqilib, keyin qayta urinishda muvaffaqiyatli
        tugagan job "muammo" emas.

        Returns:
            `[{"reason": str, "count": int, "percent": float}]` — kamayish
            tartibida; soni nol bo'lgan sabablar tushib qoladi.
        """
        bounded = max(1, min(int(limit), MAX_REASON_LIMIT))
        scope = self._scope(user_id)
        key = f"top_failure_reasons:{scope}:{bounded}"

        async def factory() -> list[dict[str, Any]]:
            counts = await self._reason_counts(user_id)
            total = sum(counts.values())
            ordered = self._ranked_reasons(counts)
            return [
                {
                    "reason": reason,
                    "count": count,
                    "percent": self._ratio(count, total),
                }
                for reason, count in ordered[:bounded]
            ]

        payload = await self._cached(key, factory)
        return [dict(row) for row in list(payload)]

    # ------------------------------------------------------------------
    # Tizim holati (admin)
    # ------------------------------------------------------------------

    async def system_status(self) -> SystemStatus:
        """Tizimning umumiy sog'lig'i — `GET /admin/system` uchun.

        KESHLANMAYDI: healthcheck eskirgan ma'lumot bermasligi kerak.

        Holat qoidasi: PostgreSQL javob bermasa `down` (u yagona haqiqat
        manbai — ulanmasa hech narsa ishlamaydi), Redis yoki sandbox
        ishlamasa `degraded` (job'lar yo'qolmaydi, lekin bajarilmaydi),
        aks holda `ok`.

        `checks` lug'ati uchta kalitdan iborat (`database`, `redis`,
        `sandbox`) — frontend aynan shu nomlarni ko'rsatadi.
        `sandbox_available` va `active_workers` esa schema'ning
        `computed_field` lari, shuning uchun bu yerda uzatilmaydi.

        `queues` — har bir ustuvorlik uchun qator: `depth` Redis'dan
        (navbatda kutayotganlar), `processing` esa DB'dan (shu
        ustuvorlikdagi `RUNNING` job'lar). Redis'ning
        `processing:<worker>` ro'yxatlari ustuvorlik bo'yicha
        ajratilmagan, shuning uchun ikkinchi manba DB bo'ladi.

        DIQQAT: faol lease'lar soni `SystemStatus` schema'sida maydon
        topmaydi (`ORMSchema` `extra="ignore"` — uzatilgani jimgina tashlab
        yuborilardi), shuning uchun u strukturaviy logga yoziladi va
        `active_leases()` metodidan alohida olinadi.
        """
        database_ok = await check_db_health()
        redis_ok = await check_redis_health()
        sandbox_ok = await self._sandbox_available()

        depths = await self._raw_queue_depth()
        workers = await self._workers()
        webhook_depth = await self._webhook_queue_depth()
        dlq_depth = await self.dlq.depth()
        counts = await self.jobs.count_by_status()
        running_by_priority = await self._running_by_priority()
        running_jobs = int(counts.get(JobStatus.RUNNING.value, 0))
        leases = await self.active_leases()

        alive = sum(1 for worker in workers if worker.is_alive)
        set_dlq_depth(dlq_depth)
        set_active_workers(alive)

        if not database_ok:
            status = "down"
        elif not redis_ok or not sandbox_ok:
            status = "degraded"
        else:
            status = "ok"

        logger.info(
            "analytics.system_status",
            status=status,
            database_ok=database_ok,
            redis_ok=redis_ok,
            sandbox_ok=sandbox_ok,
            active_workers=alive,
            active_leases=leases,
            dlq_depth=dlq_depth,
            running_jobs=running_jobs,
            webhook_queue_depth=webhook_depth,
        )
        return SystemStatus(
            status=status,
            version=settings.APP_VERSION,
            environment=settings.ENV,
            checks={
                CHECK_DATABASE: database_ok,
                CHECK_REDIS: redis_ok,
                CHECK_SANDBOX: sandbox_ok,
            },
            queues=QueueDepth.rows(depths, running_by_priority),
            workers=workers,
            delayed_jobs=int(depths.get("delayed", 0)),
            dlq_depth=dlq_depth,
            webhook_queue_depth=webhook_depth,
            running_jobs=running_jobs,
            uptime_seconds=round((utcnow() - _STARTED_AT).total_seconds(), 3),
            checked_at=utcnow(),
        )

    # ------------------------------------------------------------------
    # DLQ ko'rsatkichlari
    # ------------------------------------------------------------------

    async def dlq_stats(self, user_id: uuid.UUID | str | None = None) -> DlqStats:
        """`GET /dlq/stats` javobi — DLQ chuqurligi va sabablar taqsimoti.

        KESHLANMAYDI: DLQ chuqurligi alert ko'rsatkichi, u eskirgan
        bo'lmasligi kerak.

        `total`, `resolved`, `unresolved`, `added_last_24h` va
        `oldest_failed_at` BITTA guruhlanmagan agregat so'rovda olinadi
        (`DlqRepository` da bu kesimlar uchun metod yo'q), sabablar
        taqsimoti esa tayyor `group_by_reason()` dan.

        `depth` — schema'ning `computed_field` i (`unresolved` bilan ayni),
        shuning uchun bu yerda uzatilmaydi.
        """
        cutoff = utcnow() - timedelta(hours=RECENT_WINDOW_HOURS)
        conditions = []
        if user_id is not None:
            conditions.append(DlqEntry.user_id == self._as_id(user_id))

        unresolved_case = case((DlqEntry.resolved.is_(False), 1), else_=0)
        stmt = select(
            func.count(DlqEntry.id).label("total"),
            func.sum(unresolved_case).label("unresolved"),
            func.sum(case((DlqEntry.failed_at >= cutoff, 1), else_=0)).label("recent"),
            func.min(
                case((DlqEntry.resolved.is_(False), DlqEntry.failed_at))
            ).label("oldest"),
        )
        if conditions:
            stmt = stmt.where(*conditions)

        row = (await self._fetch(stmt)).one()._mapping
        total = int(row["total"] or 0)
        unresolved = int(row["unresolved"] or 0)
        reasons = await self.dlq.group_by_reason(user_id)

        return DlqStats(
            total=total,
            unresolved=unresolved,
            resolved=max(0, total - unresolved),
            by_reason={reason: int(count) for reason, count in reasons.items()},
            added_last_24h=int(row["recent"] or 0),
            oldest_failed_at=ensure_utc(row["oldest"]),
        )

    # ------------------------------------------------------------------
    # Admin agregatlari
    # ------------------------------------------------------------------

    async def admin_stats(self) -> AdminStats:
        """`GET /admin/stats` — platforma bo'yicha umumiy ko'rsatkichlar.

        KESHLANMAYDI: admin paneli haqiqiy vaqtdagi raqamlarni kutadi va
        so'rovlar soni oz (hammasi guruhlangan agregatlar).

        So'rovlar: foydalanuvchilar kesimi (1 ta agregat), obunalar kesimi
        (1 ta guruhlangan), job kesimlari (`stats_overview` — 2 ta: umumiy
        va oxirgi sutka), holatlar kesimi (1 ta), DLQ chuqurligi (1 ta).
        Hech bir joyda tsikl ichida so'rov YO'Q.

        `mrr_usd` — FAQAT amaldagi (faol va muddati o'tmagan) obunalar
        narxlari yig'indisi: narx `app.constants.PLAN_LIMITS` dan olinadi,
        ya'ni daromad hisobi reja katalogiga bog'lanadi.
        """
        now = utcnow()
        users = await self._user_totals(now=now)
        plans = await self._plan_totals(now=now)
        stats = await self.jobs.stats_overview()
        recent = await self.jobs.stats_overview(start=now - timedelta(hours=RECENT_WINDOW_HOURS))
        today = await self.jobs.stats_overview(start=start_of_day(now))
        counts = await self.jobs.count_by_status()
        dlq_depth = await self.dlq.depth()
        workers = await self._workers()

        #: Obuna yozuvi bo'lmagan foydalanuvchi — amalda FREE rejada.
        users_by_plan = {plan.value: 0 for plan in PlanType}
        for plan_value, count in plans.counts.items():
            users_by_plan[plan_value] = count
        unsubscribed = max(0, users.total - sum(plans.counts.values()))
        users_by_plan[PlanType.FREE.value] += unsubscribed

        return AdminStats(
            total_users=users.total,
            active_users=users.active,
            new_users_7d=users.recent,
            admin_users=users.admins,
            total_jobs=int(stats["total"]),
            jobs_24h=int(recent["total"]),
            jobs_today=int(today["total"]),
            running_jobs=int(counts.get(JobStatus.RUNNING.value, 0)),
            jobs_by_status={
                status.value: int(counts.get(status.value, 0)) for status in JobStatus
            },
            users_by_plan=users_by_plan,
            success_rate=float(stats["success_rate"]),
            avg_duration_ms=self._optional_number(stats.get("avg_duration_ms")),
            dlq_depth=dlq_depth,
            active_workers=sum(1 for worker in workers if worker.is_alive),
            mrr_usd=plans.mrr_usd,
            total_execution_seconds=round(int(stats["total_duration_ms"] or 0) / 1000, 2),
            generated_at=now,
        )

    async def admin_users(
        self,
        *,
        search: str | None = None,
        is_active: bool | None = None,
        is_admin: bool | None = None,
        plan: PlanType | str | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[list[AdminUserRead], int]:
        """`GET /admin/users` — filtr va sahifalash bilan foydalanuvchilar.

        Returns:
            `(yozuvlar, jami_soni)` — API qatlami undan
            `PaginatedResponse[AdminUserRead]` yasaydi.

        **N+1 YO'Q.** Sahifadagi foydalanuvchilar o'qilgandan keyin
        agregatlar TO'RT guruhlangan so'rovda olinadi (job'lar, DLQ,
        API kalitlar, obunalar) va lug'atdan to'ldiriladi — tsikl ichida
        so'rov bajarilmaydi.

        `plan` filtri obuna yozuvi bo'lmagan foydalanuvchilarni ham
        hisobga oladi: `plan="free"` so'ralganda yozuvsiz foydalanuvchilar
        ham tushadi (ular amalda FREE rejada).
        """
        bounded_size = max(1, min(int(page_size), MAX_ADMIN_PAGE_SIZE))
        bounded_page = max(1, int(page))
        column = self._sort_column(
            User, sort_by, allowed=ADMIN_USER_SORT_FIELDS, default="created_at"
        )
        ordering = column.asc() if str(sort_order).lower() == "asc" else column.desc()

        conditions = self._user_conditions(
            search=search, is_active=is_active, is_admin=is_admin
        )
        joined = plan is not None
        target_plan = PlanType(plan) if plan is not None else None
        if target_plan is not None:
            if target_plan is PlanType.FREE:
                conditions.append(
                    or_(Subscription.plan == PlanType.FREE, Subscription.id.is_(None))
                )
            else:
                conditions.append(Subscription.plan == target_plan)

        count_stmt = select(func.count(User.id))
        page_stmt = select(User)
        if joined:
            count_stmt = count_stmt.outerjoin(Subscription, Subscription.user_id == User.id)
            page_stmt = page_stmt.outerjoin(Subscription, Subscription.user_id == User.id)
        if conditions:
            count_stmt = count_stmt.where(*conditions)
            page_stmt = page_stmt.where(*conditions)

        total = int((await self._fetch(count_stmt)).scalar_one() or 0)
        page_stmt = (
            page_stmt.order_by(ordering, User.id.asc())
            .limit(bounded_size)
            .offset((bounded_page - 1) * bounded_size)
        )
        rows = list((await self._fetch(page_stmt)).scalars().all())
        if not rows:
            return [], total

        user_ids = [row.id for row in rows]
        jobs_by_user = await self._jobs_by_user(user_ids)
        dlq_by_user = await self._dlq_by_user(user_ids)
        keys_by_user = await self._api_keys_by_user(user_ids)
        plans_by_user = await self._plans_by_user(user_ids)

        items: list[AdminUserRead] = []
        for row in rows:
            submitted, this_period = jobs_by_user.get(row.id, (0, 0))
            #: Oddiy ustunlar modeldan o'qiladi (`from_attributes`), agregatlar
            #: esa lug'atlardan qo'shiladi — relationship'ga TEGILMAYDI
            #: (`lazy="raise"` ni qo'zg'atmaslik uchun).
            items.append(
                AdminUserRead.model_validate(row).model_copy(
                    update={
                        "plan": plans_by_user.get(row.id, PlanType.FREE),
                        "job_count": submitted,
                        "jobs_this_period": this_period,
                        "dlq_depth": dlq_by_user.get(row.id, 0),
                        "api_key_count": keys_by_user.get(row.id, 0),
                        #: SQLite naive datetime qaytaradi — UTC deb
                        #: belgilanmasa javobda `...Z` qo'shilmaydi va
                        #: brauzer vaqtni MAHALLIY deb o'qib, soatni
                        #: siljitib ko'rsatadi (shartnoma §12 talabi).
                        "created_at": ensure_utc(row.created_at),
                        "updated_at": ensure_utc(row.updated_at),
                        "last_login_at": ensure_utc(row.last_login_at),
                    }
                )
            )
        return items, total

    async def audit_logs(
        self,
        *,
        action: str | None = None,
        admin_id: uuid.UUID | str | None = None,
        target_type: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        page: int = 1,
        page_size: int = 20,
        sort_by: str = "created_at",
        sort_order: str = "desc",
    ) -> tuple[list[AuditLogRead], int]:
        """`GET /admin/audit-logs` — audit jurnali (admin emaili bilan).

        `AuditLogRead.admin_email` modelda YO'Q: u `User` jadvali bilan
        `LEFT JOIN` orqali AYNI so'rovda olinadi. `AuditLog.admin`
        relationship'i `lazy="raise"` bo'lgani uchun uni o'qish xato
        beradi, `join` esa qo'shimcha so'rov ham talab qilmaydi.

        `LEFT JOIN` (ichki join emas): `admin_id` `NULL` bo'lishi mumkin
        (tizim bajargan harakat) yoki admin o'chirilgan bo'lishi mumkin
        (`ondelete="SET NULL"`) — bunday yozuvlar ro'yxatdan TUSHIB
        QOLMASLIGI kerak.
        """
        bounded_size = max(1, min(int(page_size), MAX_ADMIN_PAGE_SIZE))
        bounded_page = max(1, int(page))
        column = self._sort_column(
            AuditLog, sort_by, allowed=AUDIT_LOG_SORT_FIELDS, default="created_at"
        )
        ordering = column.asc() if str(sort_order).lower() == "asc" else column.desc()

        conditions: list[Any] = []
        if action is not None:
            conditions.append(AuditLog.action == AuditAction(action))
        if admin_id is not None:
            conditions.append(AuditLog.admin_id == self._as_id(admin_id))
        if target_type is not None:
            conditions.append(AuditLog.target_type == target_type)
        resolved_start = ensure_utc(start)
        resolved_end = ensure_utc(end)
        if resolved_start is not None:
            conditions.append(AuditLog.created_at >= resolved_start)
        if resolved_end is not None:
            conditions.append(AuditLog.created_at <= resolved_end)

        count_stmt = select(func.count(AuditLog.id))
        page_stmt = select(AuditLog, User.email).outerjoin(User, AuditLog.admin_id == User.id)
        if conditions:
            count_stmt = count_stmt.where(*conditions)
            page_stmt = page_stmt.where(*conditions)

        total = int((await self._fetch(count_stmt)).scalar_one() or 0)
        page_stmt = (
            page_stmt.order_by(ordering, AuditLog.id.asc())
            .limit(bounded_size)
            .offset((bounded_page - 1) * bounded_size)
        )
        result = await self._fetch(page_stmt)

        items: list[AuditLogRead] = []
        for entry, email in result.all():
            record = AuditLogRead.model_validate(entry)
            items.append(
                record.model_copy(
                    update={
                        "admin_email": email,
                        #: SQLite naive datetime qaytaradi — shartnoma §12
                        #: bo'yicha javob `...Z` bilan chiqishi kerak.
                        "created_at": ensure_utc(entry.created_at),
                    }
                )
            )
        return items, total

    async def active_leases(self) -> int:
        """Hozir ushlab turilgan lease'lar soni (worker tiriklik nazorati).

        Manba — Redis'ning O'ZI: `durabl:lease:*` kalitlari TTL bilan
        yashaydi, shuning uchun ularning soni "hozir qancha job worker
        qo'lida" degan savolga eng aniq javob beradi (DB'dagi
        `lease_expires_at` esa worker qulasa eskirib qoladi).

        Kalit naqshi `RedisKeys.lease("*")` orqali yasaladi — qo'lda
        yozilgan satr YO'Q. Sanash `SCAN` bilan: `KEYS` butun keyspace'ni
        bitta buyruqda aylanib Redis'ni bloklaydi.

        Redis javob bermasa shu paytgacha sanalgani qaytadi (`0` bo'lishi
        mumkin) — healthcheck xato tashlamaydi.
        """
        pattern = RedisKeys.lease("*")
        count = 0
        try:
            async for _ in self.redis.scan_iter(match=pattern, count=LEASE_SCAN_COUNT):
                count += 1
        except RedisError as exc:
            logger.warning("analytics.leases_unavailable", error=str(exc))
        return count

    # ------------------------------------------------------------------
    # Ichki: hisob-kitob
    # ------------------------------------------------------------------

    async def _build_overview(
        self,
        *,
        user_id: uuid.UUID | str | None,
        start: datetime,
        end: datetime,
    ) -> OverviewResponse:
        """`overview()` ning haqiqiy hisob-kitobi (keshdan tashqarida).

        `jobs`, `executions` va `usage` — ichma-ich bloklar (frontend
        `Overview` turi shunday); `dlq_depth`, `queue_depth`,
        `active_workers` va `running_jobs` esa HOZIRGI holat kesimi
        (oraliqqa bog'liq emas), chunki ular "hozir nima bo'lib turgani"
        degan savolga javob beradi.

        `jobs_change_percent` oldingi AYNI UZUNLIKDAGI davr bilan
        solishtiradi (`start - (end - start)` dan `start` gacha). Oldingi
        davrda job bo'lmagan bo'lsa foiz matematik jihatdan aniqlanmagan,
        shuning uchun `None` qaytadi (frontend uni "ma'lumot yo'q" deb
        ko'rsatadi) — `0%` qaytarish "o'zgarish bo'lmadi" degan YOLG'ON
        signal berardi.
        """
        span = end - start
        stats = await self.jobs.stats_overview(user_id=user_id, start=start, end=end)
        previous = await self.jobs.stats_overview(
            user_id=user_id, start=start - span, end=start
        )
        executions = await self._execution_stats(user_id=user_id, start=start, end=end)
        sample = await self._latency_sample(user_id=user_id, start=start, end=end)
        usage = await self._usage_stats(user_id)
        runtimes = await self._jobs_by_runtime(user_id=user_id, start=start, end=end)
        dlq_depth = await self.dlq.depth(user_id)
        reasons = await self._reason_counts(user_id)
        depths = await self._raw_queue_depth()
        workers = await self._workers()
        counts = await self.jobs.count_by_status(user_id)

        by_status = {name: int(count) for name, count in dict(stats["by_status"]).items()}
        ranked = self._ranked_reasons(reasons)
        top_reason = ranked[0][0] if ranked else None
        previous_total = int(previous["total"])
        current_total = int(stats["total"])

        jobs_stats = JobStats(
            total=current_total,
            pending=by_status[JobStatus.PENDING.value],
            queued=by_status[JobStatus.QUEUED.value],
            running=by_status[JobStatus.RUNNING.value],
            retrying=by_status[JobStatus.RETRYING.value],
            success=by_status[JobStatus.SUCCESS.value],
            failed=by_status[JobStatus.FAILED.value],
            cancelled=by_status[JobStatus.CANCELLED.value],
            dead_letter=by_status[JobStatus.DEAD_LETTER.value],
            by_status=by_status,
            by_runtime=runtimes,
            avg_duration_ms=self._optional_number(stats.get("avg_duration_ms")),
            start=start,
            end=end,
        )

        return OverviewResponse(
            start=start,
            end=end,
            jobs=jobs_stats,
            executions=executions,
            usage=usage,
            dlq_depth=dlq_depth,
            # FAQAT ustuvorlik kalitlari: `queue_total` computed field
            # qiymatlarni YIG'ADI, shuning uchun `total`/`delayed`/`processing`
            # bu yerga tushsa chuqurlik ikki-uch marta hisoblanardi.
            queue_depth={
                priority.value: int(depths.get(priority.value, 0)) for priority in Priority
            },
            avg_queue_wait_ms=sample.queue_wait_avg_ms,
            jobs_change_percent=(
                None
                if previous_total == 0
                else self._change_percent(previous_total, current_total)
            ),
            queue_delayed=int(depths.get("delayed", 0)),
            queue_processing=int(depths.get("processing", 0)),
            active_workers=sum(1 for worker in workers if worker.is_alive),
            running_jobs=int(counts.get(JobStatus.RUNNING.value, 0)),
            top_failure_reason=FailureReason(top_reason) if top_reason else None,
            generated_at=utcnow(),
        )

    async def _build_dlq_series(
        self,
        *,
        user_id: uuid.UUID | str | None,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> TimeSeriesResponse:
        """`dlq_depth_series()` ning haqiqiy hisob-kitobi."""
        entries = await self._unresolved_dlq_entries(user_id=user_id, since=start)

        inflow: dict[datetime, float] = {}
        after_start = 0
        for entry in entries:
            failed_at = ensure_utc(entry.failed_at)
            if failed_at is None or failed_at < start:
                continue
            # Oraliqdan KEYIN tushganlar ham sanaladi: ular `depth()` ichida
            # bor, demak `baseline`ni to'g'ri chiqarish uchun ayirilishi kerak.
            after_start += 1
            if failed_at > end:
                continue
            bucket = floor_to_interval(failed_at, interval)
            inflow[bucket] = inflow.get(bucket, 0.0) + 1.0

        total_depth = await self.dlq.depth(user_id)
        baseline = float(max(0, total_depth - after_start))

        running = baseline
        points: list[TimeSeriesPoint] = []
        for point in fill_series(inflow, start=start, end=end, interval=interval):
            running += point.value
            points.append(TimeSeriesPoint(timestamp=point.timestamp, value=running))

        return TimeSeriesResponse(
            metric="dlq_depth",
            interval=interval,
            points=points,
            start=start,
            end=end,
            unit="entries",
        )

    async def _latency_stats(
        self,
        *,
        user_id: uuid.UUID | str | None,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> LatencyStats:
        """`LatencyStats` ni repozitoriy persentillari + namunadan yasaydi.

        O'lchov bo'lmasa maydonlar `None` qoladi (nolga aylantirilmaydi):
        grafik "ma'lumot yo'q" va "nol millisekund" ni ajratishi kerak.
        """
        stats = await self.jobs.latency_percentiles(
            user_id=user_id, start=start, end=end
        )
        sample = await self._latency_sample(
            user_id=user_id, start=start, end=end, interval=interval
        )
        return LatencyStats(
            start=start,
            end=end,
            interval=interval,  # type: ignore[arg-type]
            count=int(stats.get("count") or 0),
            min_ms=self._optional_number(stats.get("min")),
            max_ms=self._optional_number(stats.get("max")),
            avg_ms=self._optional_number(stats.get("avg")),
            p50_ms=self._optional_number(stats.get("p50")),
            p90_ms=self._optional_number(stats.get("p90")),
            p95_ms=self._optional_number(stats.get("p95")),
            p99_ms=self._optional_number(stats.get("p99")),
            queue_wait_avg_ms=sample.queue_wait_avg_ms,
            queue_wait_p95_ms=sample.queue_wait_p95_ms,
            points=sample.p95_points(),
        )

    async def _latency_sample(
        self,
        *,
        user_id: uuid.UUID | str | None,
        start: datetime,
        end: datetime,
        interval: str = "hour",
    ) -> LatencySample:
        """Yakunlangan job'lardan chegaralangan namuna o'qiydi.

        BITTA so'rov: eng yangi `LATENCY_SAMPLE_SIZE` yozuv. Namuna
        kerakligining sababi `LATENCY_SAMPLE_SIZE` izohida — qisqasi,
        navbatda kutish ayirmasi va p95 ikki dialektda turlicha SQL
        talab qiladi, Python esa ikkisida AYNI natija beradi.

        Vaqt o'qi: `finished_at`, u bo'lmasa `started_at`, u ham bo'lmasa
        `created_at` (bekor qilingan job hech qachon boshlanmagan bo'lishi
        mumkin).

        Navbatda kutish manfiy chiqsa (soat orqaga surilishi, replikatsiya
        kechikishi) nolga tenglashtiriladi — manfiy kutish fizik ma'noga
        ega emas va o'rtachani buzadi.
        """
        conditions: list[Any] = [
            Job.created_at >= start,
            Job.created_at <= end,
            Job.status.in_(list(FINISHED_JOB_STATUSES)),
        ]
        if user_id is not None:
            conditions.append(Job.user_id == self._as_id(user_id))

        stmt = (
            select(
                Job.created_at,
                Job.queued_at,
                Job.started_at,
                Job.finished_at,
                Job.duration_ms,
            )
            .where(*conditions)
            .order_by(Job.created_at.desc())
            .limit(LATENCY_SAMPLE_SIZE)
        )
        result = await self._fetch(stmt)

        sample = LatencySample()
        for created_at, queued_at, started_at, finished_at, duration_ms in result.all():
            if duration_ms is not None:
                value = float(duration_ms)
                sample.durations.append(value)
                moment = ensure_utc(finished_at or started_at or created_at)
                if moment is not None:
                    bucket = floor_to_interval(moment, interval)
                    sample.by_bucket.setdefault(bucket, []).append(value)

            queued = ensure_utc(queued_at)
            started = ensure_utc(started_at)
            if queued is not None and started is not None:
                waited = (started - queued).total_seconds() * 1000
                sample.queue_waits.append(max(0.0, round(waited, 2)))
        return sample

    async def _execution_stats(
        self,
        *,
        user_id: uuid.UUID | str | None,
        start: datetime,
        end: datetime,
    ) -> ExecutionStats:
        """Bajarish urinishlari kesimi — UCHTA guruhlangan so'rov.

        `ExecutionRepository` da agregat metod yo'q, shuning uchun
        hisob shu yerda (`CONTRACTS.md` "QO'SHIMCHA 3" ruxsati).
        Tsikl ichida so'rov YO'Q:

        1. holatlar kesimi (`GROUP BY status`);
        2. skalyar agregatlar (job'lar soni, qayta urinilganlar, davomiylik);
        3. sabablar kesimi (`GROUP BY failure_reason`).

        `avg_attempts` = urinishlar soni / shu oraliqda urinish ko'rgan
        job'lar soni, ya'ni "bitta job uchun o'rtacha necha urinish"
        (`AVG(attempt_number)` emas — u urinish NOMERINING o'rtachasi
        bo'lib, boshqa narsani o'lchaydi).

        Vaqt o'qi — `executions.created_at` (urinish yozuvi yaratilgan
        payt), chunki `started_at` bo'sh bo'lishi mumkin.
        """
        conditions: list[Any] = [
            Execution.created_at >= start,
            Execution.created_at <= end,
        ]

        status_stmt = select(Execution.status, func.count(Execution.id)).group_by(
            Execution.status
        )
        totals_stmt = select(
            func.count(distinct(Execution.job_id)).label("jobs"),
            func.count(
                distinct(case((Execution.attempt_number > 1, Execution.job_id)))
            ).label("retried"),
            func.avg(Execution.duration_ms).label("avg_duration_ms"),
            func.sum(Execution.duration_ms).label("total_duration_ms"),
        )
        reason_stmt = (
            select(Execution.failure_reason, func.count(Execution.id))
            .where(Execution.failure_reason.is_not(None))
            .group_by(Execution.failure_reason)
        )

        if user_id is not None:
            owner: Any = Job.user_id == self._as_id(user_id)
            join_on: Any = Job.id == Execution.job_id
            status_stmt = status_stmt.join(Job, join_on).where(owner)
            totals_stmt = totals_stmt.join(Job, join_on).where(owner)
            reason_stmt = reason_stmt.join(Job, join_on).where(owner)

        status_rows = (await self._fetch(status_stmt.where(*conditions))).all()
        totals = (await self._fetch(totals_stmt.where(*conditions))).one()._mapping
        reason_rows = (await self._fetch(reason_stmt.where(*conditions))).all()

        by_status = {status.value: 0 for status in ExecutionStatus}
        for status_value, count in status_rows:
            by_status[ExecutionStatus(status_value).value] = int(count or 0)
        total = sum(by_status.values())

        by_reason: dict[str, int] = {}
        for reason_value, count in reason_rows:
            by_reason[FailureReason(reason_value).value] = int(count or 0)

        touched_jobs = int(totals["jobs"] or 0)
        return ExecutionStats(
            total=total,
            success=by_status[ExecutionStatus.SUCCESS.value],
            failed=by_status[ExecutionStatus.FAILED.value],
            timeout=by_status[ExecutionStatus.TIMEOUT.value],
            lost=by_status[ExecutionStatus.LOST.value],
            retried=int(totals["retried"] or 0),
            avg_attempts=round(total / touched_jobs, 2) if touched_jobs else 0.0,
            avg_duration_ms=self._optional_number(totals["avg_duration_ms"]),
            total_execution_seconds=round(int(totals["total_duration_ms"] or 0) / 1000, 2),
            by_status=by_status,
            by_failure_reason=by_reason,
        )

    async def _usage_stats(self, user_id: uuid.UUID | str | None) -> UsageStats:
        """Joriy davr (oy) iste'moli — `OverviewResponse.usage` uchun.

        `user_id` berilsa yozuv FAQAT O'QILADI (`get_for_period`, ya'ni
        `current_period` EMAS): analitika yon ta'sir qilmasligi va
        `commit()` talab qilmasligi kerak. Yozuv bo'lmasa nol
        hisoblagichlar qaytadi.

        `user_id=None` (platforma kesimi) — barcha foydalanuvchilarning
        joriy oydagi yig'indisi, `monthly_limit` esa `0`: platformaga
        reja limiti qo'llanmaydi (`usage_percent` ham `0` bo'ladi).
        """
        period = month_key()
        if user_id is None:
            stmt = select(
                func.sum(UsageRecord.job_count),
                func.sum(UsageRecord.success_count),
                func.sum(UsageRecord.failed_count),
                func.sum(UsageRecord.execution_seconds),
            ).where(UsageRecord.period == period)
            jobs, success, failed, seconds = (await self._fetch(stmt)).one()
            return UsageStats(
                period=period,
                job_count=int(jobs or 0),
                success_count=int(success or 0),
                failed_count=int(failed or 0),
                execution_seconds=round(float(seconds or 0.0), 2),
                monthly_limit=0,
            )

        record = await self.usage_records.get_for_period(user_id, period)
        limits = await self.billing.limits_for(user_id)
        return UsageStats(
            period=period,
            job_count=int(record.job_count) if record else 0,
            success_count=int(record.success_count) if record else 0,
            failed_count=int(record.failed_count) if record else 0,
            execution_seconds=round(float(record.execution_seconds), 2) if record else 0.0,
            monthly_limit=int(limits.monthly_jobs),
        )

    async def _jobs_by_runtime(
        self,
        *,
        user_id: uuid.UUID | str | None,
        start: datetime,
        end: datetime,
    ) -> dict[str, int]:
        """Bajarish muhiti kesimi: `{"python": 12, "node": 3}` (bitta so'rov)."""
        conditions: list[Any] = [Job.created_at >= start, Job.created_at <= end]
        if user_id is not None:
            conditions.append(Job.user_id == self._as_id(user_id))
        stmt = (
            select(Job.runtime, func.count(Job.id)).where(*conditions).group_by(Job.runtime)
        )
        rows = (await self._fetch(stmt)).all()
        return {str(runtime): int(count or 0) for runtime, count in rows}

    async def _running_by_priority(self) -> dict[str, int]:
        """Ustuvorlik bo'yicha `RUNNING` job'lar soni (bitta guruhlangan so'rov)."""
        stmt = (
            select(Job.priority, func.count(Job.id))
            .where(Job.status == JobStatus.RUNNING)
            .group_by(Job.priority)
        )
        rows = (await self._fetch(stmt)).all()
        return {Priority(priority).value: int(count or 0) for priority, count in rows}

    async def _user_totals(self, *, now: datetime) -> UserTotals:
        """Foydalanuvchilar kesimi — BITTA agregat so'rov."""
        cutoff = now - timedelta(days=NEW_USERS_WINDOW_DAYS)
        stmt = select(
            func.count(User.id).label("total"),
            func.sum(case((User.is_active.is_(True), 1), else_=0)).label("active"),
            func.sum(case((User.is_admin.is_(True), 1), else_=0)).label("admins"),
            func.sum(case((User.created_at >= cutoff, 1), else_=0)).label("recent"),
        )
        row = (await self._fetch(stmt)).one()._mapping
        return UserTotals(
            total=int(row["total"] or 0),
            active=int(row["active"] or 0),
            admins=int(row["admins"] or 0),
            recent=int(row["recent"] or 0),
        )

    async def _plan_totals(self, *, now: datetime) -> PlanTotals:
        """Rejalar kesimi va MRR — BITTA guruhlangan so'rov.

        "Faol obuna" = `is_active` va muddati o'tmagan (`expires_at`
        bo'sh yoki kelajakda) — `Subscription.is_valid` xossasi bilan
        AYNI mantiq, lekin SQL tomonida (har bir yozuvni Python'da
        tekshirish N+1 ga olib kelardi).
        """
        valid = (Subscription.is_active.is_(True)) & (
            or_(Subscription.expires_at.is_(None), Subscription.expires_at > now)
        )
        stmt = select(
            Subscription.plan,
            func.count(Subscription.id),
            func.sum(case((valid, 1), else_=0)),
        ).group_by(Subscription.plan)
        rows = (await self._fetch(stmt)).all()

        counts: dict[str, int] = {}
        mrr = 0.0
        for plan_value, total, active in rows:
            plan = PlanType(plan_value)
            counts[plan.value] = int(total or 0)
            mrr += float(PLAN_LIMITS[plan].price_usd_month) * int(active or 0)
        return PlanTotals(counts=counts, mrr_usd=round(mrr, 2))

    async def _jobs_by_user(
        self, user_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, tuple[int, int]]:
        """Foydalanuvchi -> (jami job, joriy oydagi job) — bitta so'rov."""
        period_start = start_of_month()
        stmt = (
            select(
                Job.user_id,
                func.count(Job.id),
                func.sum(case((Job.created_at >= period_start, 1), else_=0)),
            )
            .where(Job.user_id.in_(list(user_ids)))
            .group_by(Job.user_id)
        )
        rows = (await self._fetch(stmt)).all()
        return {
            user_id: (int(total or 0), int(period or 0)) for user_id, total, period in rows
        }

    async def _dlq_by_user(self, user_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, int]:
        """Foydalanuvchi -> hal qilinmagan DLQ yozuvlari soni (bitta so'rov)."""
        stmt = (
            select(DlqEntry.user_id, func.count(DlqEntry.id))
            .where(DlqEntry.user_id.in_(list(user_ids)), DlqEntry.resolved.is_(False))
            .group_by(DlqEntry.user_id)
        )
        rows = (await self._fetch(stmt)).all()
        return {user_id: int(count or 0) for user_id, count in rows}

    async def _api_keys_by_user(
        self, user_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """Foydalanuvchi -> AMALDAGI API kalitlar soni (bitta so'rov).

        "Amaldagi" = bekor qilinmagan va muddati o'tmagan —
        `ApiKey.is_valid` xossasi bilan ayni mantiq, SQL tomonida.
        """
        now = utcnow()
        stmt = (
            select(ApiKey.user_id, func.count(ApiKey.id))
            .where(
                ApiKey.user_id.in_(list(user_ids)),
                ApiKey.revoked_at.is_(None),
                or_(ApiKey.expires_at.is_(None), ApiKey.expires_at > now),
            )
            .group_by(ApiKey.user_id)
        )
        rows = (await self._fetch(stmt)).all()
        return {user_id: int(count or 0) for user_id, count in rows}

    async def _plans_by_user(
        self, user_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, PlanType]:
        """Foydalanuvchi -> obuna rejasi (bitta so'rov; yozuvsizlar FREE)."""
        stmt = select(Subscription.user_id, Subscription.plan).where(
            Subscription.user_id.in_(list(user_ids))
        )
        rows = (await self._fetch(stmt)).all()
        return {user_id: PlanType(plan) for user_id, plan in rows}

    @staticmethod
    def _user_conditions(
        *,
        search: str | None,
        is_active: bool | None,
        is_admin: bool | None,
    ) -> list[Any]:
        """`admin_users()` filtrlarini WHERE shartlariga aylantiradi."""
        conditions: list[Any] = []
        if search:
            pattern = f"%{search.strip()}%"
            conditions.append(
                or_(User.email.ilike(pattern), User.full_name.ilike(pattern))
            )
        if is_active is not None:
            conditions.append(User.is_active.is_(is_active))
        if is_admin is not None:
            conditions.append(User.is_admin.is_(is_admin))
        return conditions

    @staticmethod
    def _sort_column(
        model: type[Any],
        name: str,
        *,
        allowed: frozenset[str],
        default: str,
    ) -> Any:
        """Tartiblash ustunini TEKSHIRIB qaytaradi (SQL injection'dan himoya).

        Nomi ro'yxatda bo'lmasa ochiq xato beriladi — jimgina standart
        ustunga o'tish mijozni "tartiblash ishlayapti" deb chalg'itardi.

        Raises:
            ValidationError: Ustun ruxsat etilganlar ro'yxatida bo'lmasa.
        """
        if not name:
            return getattr(model, default)
        if name not in allowed:
            raise ValidationError(
                f"'{name}' bo'yicha tartiblash mumkin emas",
                details={"allowed": sorted(allowed)},
            )
        return getattr(model, name)

    @staticmethod
    def _status_breakdown(
        rows: Mapping[datetime, Mapping[str, int]],
        *,
        cancelled: Mapping[datetime, float],
        dead_letter: Mapping[datetime, float],
        start: datetime,
        end: datetime,
        interval: str,
    ) -> list[StatusSeriesPoint]:
        """Savatlar bo'yicha holat ajratmasini yasaydi (bo'sh savatlar nol bilan).

        `JobRepository.throughput_series` ning `failed` ustuni FAILED va
        DEAD_LETTER ni BIRGA sanaydi, shuning uchun "faqat failed"
        qiymati `failed - dead_letter` sifatida chiqariladi (manfiy
        bo'lib ketmasligi uchun `max(0, ...)` qo'yilgan).
        """
        points: list[StatusSeriesPoint] = []
        for bucket in bucket_timeline(start, end, interval):
            row = rows.get(bucket, {})
            total = int(row.get("total", 0))
            success = int(row.get("success", 0))
            combined_failed = int(row.get("failed", 0))
            dead = int(dead_letter.get(bucket, 0.0))
            points.append(
                StatusSeriesPoint(
                    timestamp=bucket,
                    value=float(total),
                    success=success,
                    failed=max(0, combined_failed - dead),
                    cancelled=int(cancelled.get(bucket, 0.0)),
                    dead_letter=dead,
                )
            )
        return points

    @staticmethod
    def _series_unit(base: str, interval: str) -> str:
        """`"jobs"` + `"hour"` -> `"jobs/hour"` (grafik o'qi yozuvi)."""
        return f"{base}/{interval}"

    async def _webhook_queue_depth(self) -> int:
        """Yuborilishi kutilayotgan webhook'lar soni (Redis LIST uzunligi).

        Redis javob bermasa `0` qaytadi va `warning` log qilinadi —
        healthcheck o'zi qulamasligi kerak.
        """
        try:
            return int(await self.redis.llen(RedisKeys.WEBHOOK_QUEUE) or 0)
        except (RedisError, DurablError) as exc:
            logger.warning("analytics.webhook_queue_unavailable", error=str(exc))
            return 0

    async def _fetch(self, stmt: Any) -> Any:
        """`select()` ni bajaradi va drayver xatosini `DatabaseError`ga o'raydi.

        Repozitoriylardagi `_execute()` bilan AYNI shartnoma: API qatlami
        barcha DB xatolarini bitta domen xatosi sifatida ko'radi.
        """
        try:
            return await self.session.execute(stmt)
        except SQLAlchemyError as exc:  # pragma: no cover - infratuzilma xatosi
            raise DatabaseError(f"SQL bajarishda xato: {exc}") from exc

    @staticmethod
    def _as_id(value: uuid.UUID | str) -> uuid.UUID | str:
        """Matn ko'rinishidagi UUID'ni `uuid.UUID`ga aylantiradi.

        `BaseRepository._coerce_id` bilan ayni xatti-harakat: aylantirish
        imkonsiz bo'lsa qiymat o'zgarmaydi (SQL darajasida mos kelmaydi
        va natija bo'sh bo'ladi — bu xato tashlashdan ko'ra xavfsizroq,
        chunki analitika kuzatuv yo'li).
        """
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError, TypeError):
            return value

    async def _collect_slowest(
        self,
        *,
        user_id: uuid.UUID | str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Yakunlangan job'lardan eng sekinlarini chegaralangan sahifalarda topadi."""
        found: list[Job] = []
        for page in range(1, SLOWEST_MAX_PAGES + 1):
            chunk, total = await self.jobs.search(
                user_id=user_id,
                status=list(FINISHED_JOB_STATUSES),
                page=page,
                page_size=SLOWEST_PAGE_SIZE,
                sort_by="duration_ms",
                sort_order="desc",
            )
            if not chunk:
                break
            found.extend(job for job in chunk if job.duration_ms is not None)
            if len(found) >= limit or page * SLOWEST_PAGE_SIZE >= total:
                break

        # Yakuniy tartib Python tomonida — dialektdagi `NULLS FIRST/LAST`
        # farqi natijaga ta'sir qilmaydi.
        found.sort(key=lambda job: int(job.duration_ms or 0), reverse=True)
        return [self._slowest_row(job) for job in found[:limit]]

    async def _unresolved_dlq_entries(
        self,
        *,
        user_id: uuid.UUID | str | None,
        since: datetime,
    ) -> list[DlqEntry]:
        """Hal qilinmagan DLQ yozuvlarini yangisidan boshlab o'qiydi.

        `failed_at DESC` tartibida sahifalanadi va `since` dan oldingi
        yozuvga yetgach to'xtaydi — ya'ni o'qish oraliq KATTALIGIGA
        bog'liq, jadval kattaligiga emas. `DLQ_SERIES_MAX_PAGES` esa
        patologik holatda (o'n minglab hal qilinmagan yozuv) so'rovni
        cheklaydi.
        """
        collected: list[DlqEntry] = []
        for page in range(DLQ_SERIES_MAX_PAGES):
            chunk = await self.dlq.list(
                limit=DLQ_SERIES_PAGE_SIZE,
                offset=page * DLQ_SERIES_PAGE_SIZE,
                order_by=DlqEntry.failed_at.desc(),
                user_id=user_id,
                resolved=False,
            )
            if not chunk:
                break
            collected.extend(chunk)
            oldest = ensure_utc(chunk[-1].failed_at)
            if len(chunk) < DLQ_SERIES_PAGE_SIZE or (oldest is not None and oldest < since):
                break
        return collected

    async def _reason_counts(self, user_id: uuid.UUID | str | None) -> dict[str, int]:
        """HAL QILINMAGAN DLQ yozuvlarining sabablar kesimi.

        `resolved=False` ataylab: shu kesim `dlq_depth` bilan AYNI
        to'plamni tasvirlaydi, ya'ni "hozirgi chuqurlik nimadan iborat"
        degan savolga javob beradi. Hal qilingan yozuvlarni qo'shish
        allaqachon tuzatilgan muammoni "eng ko'p uchragan sabab" qilib
        ko'rsatib qo'yardi.

        Nol qiymatlar OLIB TASHLANADI: `group_by_reason()` barcha
        sabablarni (nollar bilan) qaytaradi — bu grafik ustunlari uchun
        qulay, lekin "top sabablar" ro'yxatini nol bilan to'ldirish
        ma'nosiz.
        """
        grouped = await self.dlq.group_by_reason(user_id, resolved=False)
        return {reason: int(count) for reason, count in grouped.items() if count}

    @staticmethod
    def _ranked_reasons(counts: Mapping[str, int]) -> list[tuple[str, int]]:
        """Sabablarni kamayish tartibida qaytaradi (teng sonlarda alifbo bo'yicha).

        Ikkinchi mezon BARQAROR tartib uchun kerak: lug'at tartibiga
        tayanilsa, bir xil sonli ikki sabab orasidan "eng yuqorisi"
        so'rovdan so'rovga o'zgarib ketardi.
        """
        return sorted(counts.items(), key=lambda item: (-item[1], item[0]))

    # ------------------------------------------------------------------
    # Ichki: infratuzilma (fail-soft)
    # ------------------------------------------------------------------

    async def _raw_queue_depth(self) -> dict[str, int]:
        """`QueueService.depth()` natijasi; Redis javob bermasa nol kesim.

        Analitika — kuzatuv yo'li: Redis uzilgani uchun butun dashboard
        503 bermasligi kerak. Shuning uchun `QueueError` (va umuman
        `DurablError`) ushlanadi va `warning` log qilinadi.
        """
        try:
            depths = await self.queue.depth()
        except (RedisError, DurablError) as exc:
            logger.warning("analytics.queue_depth_unavailable", error=str(exc))
            return {priority.value: 0 for priority in Priority}
        return {str(name): int(value) for name, value in depths.items()}

    async def _workers(self) -> list[WorkerInfo]:
        """Ro'yxatdan o'tgan worker'lar; Redis javob bermasa bo'sh ro'yxat.

        Registrdagi yozuv buzuq bo'lsa (eski format, qo'lda o'zgartirilgan)
        FAQAT shu yozuv tashlab yuboriladi — bitta yaroqsiz worker butun
        admin panelini qulatmasligi kerak.
        """
        try:
            rows = await self.reliability.list_workers()
        except (RedisError, DurablError) as exc:
            logger.warning("analytics.workers_unavailable", error=str(exc))
            return []

        workers: list[WorkerInfo] = []
        for row in rows:
            try:
                workers.append(WorkerInfo.model_validate(row))
            except PydanticValidationError as exc:
                logger.warning(
                    "analytics.worker_record_invalid",
                    worker=str(row.get("worker_id", "?")),
                    error=str(exc),
                )
        return workers

    async def _sandbox_available(self) -> bool:
        """Sandbox (Docker/gVisor) mavjudmi.

        `SandboxService` dangasa yaratiladi va HAR QANDAY xato `False`ga
        aylanadi: healthcheck o'zi qulashi mumkin emas, Docker SDK esa
        domen xatosi bo'lmagan istisnolar (masalan `DockerException`)
        tashlashi mumkin.
        """
        if self._sandbox is None:
            self._sandbox = SandboxService()
        try:
            return bool(await self._sandbox.available())
        except Exception as exc:
            logger.warning("analytics.sandbox_unavailable", error=str(exc))
            return False

    # ------------------------------------------------------------------
    # Ichki: kesh va oraliq
    # ------------------------------------------------------------------

    async def _cached(self, key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
        """Og'ir hisob-kitobni `stats` namespace'ida keshlaydi.

        `CacheService.get_or_set` "cache stampede" dan himoyalangan, lekin
        bitta shart qo'yadi: `factory` JSON'ga MOS qiymat qaytarishi kerak.
        Sababi — kesh TEGISHI (hit) `load_json` natijasini, ya'ni oddiy
        lug'at/ro'yxatni beradi; `factory` esa Pydantic modelini qaytarsa
        chaqiruvchi ikki xil turni olardi. Shuning uchun barcha factory'lar
        `model_dump(mode="json")` qiladi va chaqiruvchi natijani
        `model_validate` bilan qayta yig'adi.
        """
        return await self.cache.get_or_set(
            CACHE_NAMESPACE,
            key,
            factory,
            ttl=settings.STATS_CACHE_TTL_SECONDS,
        )

    def _resolve_range(
        self,
        start: datetime | None,
        end: datetime | None,
    ) -> tuple[datetime, datetime]:
        """Oraliqni normallashtiradi va chegaralarni tekshiradi.

        * `end` berilmasa — kesh oynasiga tushirilgan hozirgi vaqt;
        * `start` berilmasa — `end` dan `DEFAULT_RANGE_HOURS` oldin;
        * `start > end` -> `ValidationError`;
        * `end - start > settings.ANALYTICS_MAX_RANGE_DAYS` -> `ValidationError`.
        """
        resolved_end = ensure_utc(end) or self._quantized_now()
        resolved_start = ensure_utc(start)
        if resolved_start is None:
            resolved_start = resolved_end - timedelta(hours=DEFAULT_RANGE_HOURS)

        if resolved_start > resolved_end:
            raise ValidationError(
                "Oraliq boshlanishi tugashidan keyin bo'lishi mumkin emas",
                details={
                    "start": isoformat(resolved_start),
                    "end": isoformat(resolved_end),
                },
            )

        max_span = timedelta(days=settings.ANALYTICS_MAX_RANGE_DAYS)
        span = resolved_end - resolved_start
        if span > max_span:
            raise ValidationError(
                f"Analitika oralig'i {settings.ANALYTICS_MAX_RANGE_DAYS} kundan "
                "oshmasligi kerak",
                details={
                    "max_range_days": settings.ANALYTICS_MAX_RANGE_DAYS,
                    "requested_days": round(span.total_seconds() / 86_400, 2),
                },
            )
        return resolved_start, resolved_end

    @staticmethod
    def _resolve_interval(interval: str, start: datetime, end: datetime) -> str:
        """Qadamni tekshiradi va nuqtalar soni chegarasini qo'llaydi."""
        if interval not in SUPPORTED_INTERVALS:
            raise ValidationError(
                f"'{interval}' oralig'i qo'llab-quvvatlanmaydi",
                details={"allowed": list(SUPPORTED_INTERVALS)},
            )
        points = expected_point_count(start, end, interval)
        if points > MAX_SERIES_POINTS:
            raise ValidationError(
                "Vaqt qatori juda uzun — kattaroq qadam tanlang "
                f"(`{interval}` o'rniga `day`)",
                details={"points": points, "max_points": MAX_SERIES_POINTS},
            )
        return interval

    @staticmethod
    def _quantized_now() -> datetime:
        """Hozirgi vaqt, kesh oynasi boshiga tushirilgan.

        Kesh kaliti BARQAROR bo'lishi uchun kerak: `utcnow()` har
        chaqiruvda o'zgaradi, demak standart oraliq uchun kalit ham
        o'zgarardi va kesh hech qachon tegmasdi.
        """
        now = utcnow()
        window = settings.STATS_CACHE_TTL_SECONDS
        if window <= 0:
            return now
        epoch = int(now.timestamp())
        return from_timestamp(epoch - epoch % window)

    # ------------------------------------------------------------------
    # Ichki: sof yordamchilar
    # ------------------------------------------------------------------

    @staticmethod
    def _scope(user_id: uuid.UUID | str | None) -> str:
        """Kesh kalitining egalik qismi: `user_id` yoki `"all"` (admin)."""
        return "all" if user_id is None else str(user_id)

    @staticmethod
    def _rows_by_bucket(
        series: Sequence[Mapping[str, Any]],
        *,
        interval: str,
    ) -> dict[datetime, dict[str, int]]:
        """Repozitoriy qatorlarini savat -> qator lug'atiga aylantiradi.

        Vaqt o'qi `NULL` bo'lgan (`bucket is None`) qatorlar tashlab
        yuboriladi — ular grafikda o'rin topmaydi.
        """
        rows: dict[datetime, dict[str, int]] = {}
        for row in series:
            bucket = row.get("bucket")
            if not isinstance(bucket, datetime):
                continue
            key = floor_to_interval(bucket, interval)
            rows[key] = {
                "total": int(row.get("total") or 0),
                "success": int(row.get("success") or 0),
                "failed": int(row.get("failed") or 0),
            }
        return rows

    @classmethod
    def _bucketed(
        cls,
        series: Sequence[Mapping[str, Any]],
        *,
        field: str,
        interval: str,
    ) -> dict[datetime, float]:
        """Bitta maydonni savat -> qiymat lug'atiga chiqaradi."""
        return {
            bucket: float(row[field])
            for bucket, row in cls._rows_by_bucket(series, interval=interval).items()
        }

    @staticmethod
    def _ratio(part: int | float, whole: int | float) -> float:
        """`part / whole * 100` — maxraj nol bo'lsa `0.0`."""
        if not whole:
            return 0.0
        return round(float(part) / float(whole) * 100, 2)

    @staticmethod
    def _change_percent(previous: int | float, current: int | float) -> float:
        """Oldingi davrga nisbatan o'zgarish foizi.

        Oldingi davr nol bo'lsa foiz matematik jihatdan aniqlanmagan:
        joriy davr ham nol bo'lsa `0.0` ("o'zgarish yo'q"), aks holda
        `100.0` qaytadi ("noldan o'sish").
        """
        if not previous:
            return 0.0 if not current else 100.0
        return round((float(current) - float(previous)) / float(previous) * 100, 2)

    @staticmethod
    def _optional_number(value: Any) -> float | None:
        """Raqamni ikki xona aniqlikda qaytaradi; `None` AYNAN `None` qoladi.

        Nolga aylantirish TAQIQLANADI: frontend uchun `null` — "o'lchov
        yo'q", `0.0` esa "haqiqatan nol". Masalan oraliqda yakunlangan job
        bo'lmasa `avg_duration_ms` `null` bo'lishi kerak, aks holda UI
        "o'rtacha 0 ms" degan yolg'on ko'rsatkichni chizadi.
        """
        if value is None:
            return None
        return round(float(value), 2)

    @staticmethod
    def _slowest_row(job: Job) -> dict[str, Any]:
        """Bitta job'ning "eng sekinlar" ro'yxatidagi JSON'ga mos kesimi.

        `code`, `payload` va `env_vars` ATAYLAB kiritilmaydi: ro'yxat
        keshlanadi va mijoz kodini keshda saqlash ham xavfsizlik, ham
        hajm jihatidan keraksiz.
        """
        return {
            "job_id": str(job.id),
            "status": JobStatus(job.status).value,
            "runtime": str(job.runtime),
            "priority": str(job.priority),
            "duration_ms": int(job.duration_ms or 0),
            "exit_code": job.exit_code,
            "failure_reason": (
                FailureReason(job.failure_reason).value if job.failure_reason else None
            ),
            "retry_count": int(job.retry_count or 0),
            "correlation_id": job.correlation_id,
            "created_at": isoformat(job.created_at),
            "started_at": isoformat(job.started_at),
            "finished_at": isoformat(job.finished_at),
        }


__all__ = [
    "ADMIN_USER_SORT_FIELDS",
    "AUDIT_LOG_SORT_FIELDS",
    "CACHE_NAMESPACE",
    "DEFAULT_RANGE_HOURS",
    "DLQ_SERIES_MAX_PAGES",
    "DLQ_SERIES_PAGE_SIZE",
    "FINISHED_JOB_STATUSES",
    "INTERVAL_DELTAS",
    "LATENCY_SAMPLE_SIZE",
    "LEASE_SCAN_COUNT",
    "MAX_ADMIN_PAGE_SIZE",
    "MAX_REASON_LIMIT",
    "MAX_SERIES_POINTS",
    "MAX_SLOWEST_LIMIT",
    "NEW_USERS_WINDOW_DAYS",
    "RECENT_WINDOW_HOURS",
    "SLOWEST_MAX_PAGES",
    "SLOWEST_PAGE_SIZE",
    "SUPPORTED_INTERVALS",
    "AnalyticsService",
    "LatencySample",
    "PlanTotals",
    "UserTotals",
    "bucket_timeline",
    "expected_point_count",
    "fill_series",
    "floor_to_interval",
    "interval_delta",
    "percentile",
]
