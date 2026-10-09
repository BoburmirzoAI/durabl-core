"""Durabl — analitika va kuzatuvchanlik (observability) schema'lari.

Bu modul dashboard va `/analytics/*` endpointlari uchun ko'rsatkich shakllarini
belgilaydi: throughput, success rate, latency persentillari va DLQ chuqurligi.

**Shakl manbai — frontend.** `frontend/src/types/analytics.ts` TO'LIQ yozilgan
va tasdiqlangan (`tsc --noEmit` toza), shuning uchun maydon nomlari va turlari
AYNAN shu ta'riflardan olingan (`CONTRACTS.md`, "QO'SHIMCHA 3"):

* `Overview`         -> `OverviewResponse`
* `JobStats`         -> `JobStats`
* `ExecutionStats`   -> `ExecutionStats`
* `UsageStats`       -> `UsageStats`
* `TimeSeriesPoint`  -> `TimeSeriesPoint`
* `StatusSeriesPoint`-> `StatusSeriesPoint`
* `TimeSeriesResponse` -> `TimeSeriesResponse`
* `SuccessRate`      -> `SuccessRateResponse`
* `LatencyStats`     -> `LatencyStats`

Barcha vaqt qatorlari bir xil shaklda — frontend (Recharts) uchun yagona
kontrakt: `points[].timestamp` + `points[].value`.

**Nol/`None` farqi.** Latency maydonlari `float | None`: `None` — "o'lchov
yo'q" (oraliqda yakunlangan job bo'lmagan), `0.0` esa "haqiqatan nol"
degan ma'noni beradi. Grafik bu ikkisini turlicha ko'rsatishi kerak,
shuning uchun nolga aylantirilmaydi.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field, computed_field

from app.constants import FailureReason
from app.schemas.base import ORMSchema

#: Vaqt qatori qadamlari — frontend `AnalyticsInterval` bilan AYNI.
Interval = Literal["minute", "hour", "day"]


# ---------------------------------------------------------------------------
# Vaqt qatorlari
# ---------------------------------------------------------------------------


class TimeSeriesPoint(ORMSchema):
    """Vaqt qatoridagi bitta nuqta."""

    timestamp: datetime = Field(description="Oraliq boshlanish vaqti (ISO-8601, UTC)")
    value: float = Field(description="Shu oraliqdagi ko'rsatkich qiymati")


class StatusSeriesPoint(TimeSeriesPoint):
    """Holatlar bo'yicha ajratilgan nuqta — "stacked" grafik uchun.

    `value` — savatdagi JAMI job'lar soni, qolgan maydonlar esa shu
    jamining holatlar bo'yicha ajratmasi.
    """

    success: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Savatdagi muvaffaqiyatli job'lar"
    )
    failed: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Savatdagi muvaffaqiyatsiz job'lar"
    )
    cancelled: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Savatdagi bekor qilingan job'lar"
    )
    dead_letter: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Savatda DLQ'ga tushgan job'lar"
    )


class TimeSeriesResponse(ORMSchema):
    """Vaqt qatori javobi — grafiklar uchun yagona shakl.

    `total`, `average` va `peak` — `computed_field`: ular HAR DOIM
    `points` dan hisoblanadi, shuning uchun qator bilan jamlanma
    bir-biriga qarama-qarshi bo'lib qolishi mumkin emas.
    """

    start: datetime = Field(description="Oraliq boshlanishi (UTC)")
    end: datetime = Field(description="Oraliq tugashi (UTC)")
    interval: Interval = Field(default="hour", description="Qadam: daqiqa, soat yoki kun")
    unit: str = Field(
        default="jobs",
        description="Qiymatning o'lchov birligi (`jobs`, `entries`, `percent`)",
        examples=["jobs"],
    )
    points: list[TimeSeriesPoint] = Field(
        default_factory=list, description="Nuqtalar (vaqt bo'yicha o'sish tartibida)"
    )
    metric: str = Field(
        default="",
        description="Ko'rsatkich nomi (`throughput`, `dlq_depth`) — kuzatuv uchun",
        examples=["throughput"],
    )

    @computed_field(description="Nuqtalar soni")  # type: ignore[prop-decorator]
    @property
    def count(self) -> int:
        """`points` uzunligi."""
        return len(self.points)

    @computed_field(description="Barcha nuqtalar qiymatlarining yig'indisi")  # type: ignore[prop-decorator]
    @property
    def total(self) -> float:
        """Yig'indi — throughput uchun "jami job" ma'nosini beradi."""
        return round(float(sum(point.value for point in self.points)), 2)

    @computed_field(description="Nuqtalarning o'rtacha qiymati")  # type: ignore[prop-decorator]
    @property
    def average(self) -> float:
        """`total / count` — nuqta bo'lmasa `0.0`."""
        if not self.points:
            return 0.0
        return round(self.total / len(self.points), 2)

    @computed_field(description="Eng yuqori nuqta qiymati")  # type: ignore[prop-decorator]
    @property
    def peak(self) -> float:
        """Maksimal qiymat — nuqta bo'lmasa `0.0`."""
        if not self.points:
            return 0.0
        return round(max(point.value for point in self.points), 2)


class DlqDepthPoint(ORMSchema):
    """DLQ chuqurligining bir vaqtdagi kesimi (sabablar ajratmasi bilan)."""

    timestamp: datetime = Field(description="O'lchov vaqti (ISO-8601, UTC)")
    depth: Annotated[int, Field(ge=0)] = Field(description="Hal qilinmagan DLQ yozuvlari soni")
    by_reason: dict[str, int] = Field(
        default_factory=dict, description="Sabab -> yozuvlar soni (`FailureReason` kalitlari)"
    )


# ---------------------------------------------------------------------------
# Jamlangan statistikalar
# ---------------------------------------------------------------------------


class LatencyStats(ORMSchema):
    """`GET /analytics/latency` — kechikish persentillari (millisekundda).

    Ikki xil kechikish beriladi:

    * `*_ms` — job'ning BAJARILISH vaqti (`jobs.duration_ms`);
    * `queue_wait_*` — navbatda KUTISH vaqti (`started_at - queued_at`).

    Ikkinchisi mijoz uchun ko'pincha muhimroq: kod tez ishlasa ham
    navbat uzun bo'lsa javob kech keladi.
    """

    start: datetime = Field(description="Oraliq boshlanishi (UTC)")
    end: datetime = Field(description="Oraliq tugashi (UTC)")
    interval: Interval = Field(default="hour", description="`points` qatorining qadami")
    count: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Hisobga olingan job'lar soni (`duration_ms` ma'lum bo'lganlar)"
    )
    min_ms: float | None = Field(default=None, description="Eng kichik bajarish vaqti (ms)")
    max_ms: float | None = Field(default=None, description="Eng katta bajarish vaqti (ms)")
    avg_ms: float | None = Field(default=None, description="O'rtacha bajarish vaqti (ms)")
    p50_ms: float | None = Field(default=None, description="Median (50-persentil), ms")
    p90_ms: float | None = Field(default=None, description="90-persentil, ms")
    p95_ms: float | None = Field(default=None, description="95-persentil, ms")
    p99_ms: float | None = Field(default=None, description="99-persentil, ms")
    queue_wait_avg_ms: float | None = Field(
        default=None, description="Navbatda kutishning o'rtacha vaqti (ms)"
    )
    queue_wait_p95_ms: float | None = Field(
        default=None, description="Navbatda kutishning 95-persentili (ms)"
    )
    points: list[TimeSeriesPoint] = Field(
        default_factory=list,
        description="Vaqt bo'yicha p95 bajarish vaqti qatori (ms) — grafik uchun",
    )


class JobStats(ORMSchema):
    """Job'lar bo'yicha jamlangan statistika."""

    total: Annotated[int, Field(ge=0)] = Field(default=0, description="Jami job'lar soni")
    pending: Annotated[int, Field(ge=0)] = Field(default=0, description="Navbatga qo'yilmaganlar")
    queued: Annotated[int, Field(ge=0)] = Field(default=0, description="Navbatda kutayotganlar")
    running: Annotated[int, Field(ge=0)] = Field(default=0, description="Bajarilayotganlar")
    success: Annotated[int, Field(ge=0)] = Field(default=0, description="Muvaffaqiyatli tugaganlar")
    failed: Annotated[int, Field(ge=0)] = Field(default=0, description="Xato bilan tugaganlar")
    retrying: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Qayta urinish kutayotganlar"
    )
    cancelled: Annotated[int, Field(ge=0)] = Field(default=0, description="Bekor qilinganlar")
    dead_letter: Annotated[int, Field(ge=0)] = Field(default=0, description="DLQ'ga tushganlar")
    by_status: dict[str, int] = Field(
        default_factory=dict, description="Holat -> soni (`JobStatus` qiymatlari kalit)"
    )
    by_runtime: dict[str, int] = Field(default_factory=dict, description="Bajarish muhiti -> soni")
    avg_duration_ms: float | None = Field(
        default=None, description="O'rtacha bajarish vaqti (ms); o'lchov bo'lmasa `null`"
    )
    start: datetime | None = Field(default=None, description="Oraliq boshlanishi (UTC)")
    end: datetime | None = Field(default=None, description="Oraliq tugashi (UTC)")

    @computed_field(description="Muvaffaqiyat foizi (0–100), yakunlangan job'lar asosida")  # type: ignore[prop-decorator]
    @property
    def success_rate(self) -> float:
        """`success / (success + failed + dead_letter) * 100`."""
        finished = self.success + self.failed + self.dead_letter
        if finished <= 0:
            return 0.0
        return round(self.success / finished * 100, 2)

    @computed_field(description="Hozir tizimda harakatda bo'lgan job'lar soni")  # type: ignore[prop-decorator]
    @property
    def active(self) -> int:
        """`pending + queued + running + retrying`."""
        return self.pending + self.queued + self.running + self.retrying


class ExecutionStats(ORMSchema):
    """Bajarish urinishlari bo'yicha statistika (retry bosimi ko'rsatkichi)."""

    total: Annotated[int, Field(ge=0)] = Field(default=0, description="Jami urinishlar soni")
    success: Annotated[int, Field(ge=0)] = Field(default=0, description="Muvaffaqiyatli urinishlar")
    failed: Annotated[int, Field(ge=0)] = Field(default=0, description="Muvaffaqiyatsiz urinishlar")
    timeout: Annotated[int, Field(ge=0)] = Field(default=0, description="Vaqt limitidan oshganlar")
    lost: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Lease yo'qolgani sababli bekor bo'lganlar"
    )
    retried: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Kamida bir marta qayta urinilgan job'lar soni"
    )
    avg_attempts: float = Field(
        default=0.0, description="Bitta job'ga to'g'ri keladigan o'rtacha urinish soni"
    )
    avg_duration_ms: float | None = Field(
        default=None, description="O'rtacha urinish davomiyligi (ms)"
    )
    total_execution_seconds: float = Field(
        default=0.0, description="Jami sarflangan hisoblash vaqti (soniya)"
    )
    by_status: dict[str, int] = Field(
        default_factory=dict, description="Holat -> soni (`ExecutionStatus` qiymatlari kalit)"
    )
    by_failure_reason: dict[str, int] = Field(
        default_factory=dict, description="Sabab -> soni (`FailureReason` qiymatlari kalit)"
    )

    @computed_field(description="Urinishlar bo'yicha muvaffaqiyat foizi (0–100)")  # type: ignore[prop-decorator]
    @property
    def success_rate(self) -> float:
        """`success / total * 100`."""
        if self.total <= 0:
            return 0.0
        return round(self.success / self.total * 100, 2)


class UsageStats(ORMSchema):
    """Foydalanuvchining joriy davr (oy) bo'yicha iste'moli."""

    period: str = Field(description="Davr (`YYYY-MM`)", examples=["2026-10"])
    job_count: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Davr ichida yuborilgan job'lar"
    )
    success_count: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Muvaffaqiyatli tugaganlar"
    )
    failed_count: Annotated[int, Field(ge=0)] = Field(default=0, description="Muvaffaqiyatsizlar")
    execution_seconds: float = Field(default=0.0, description="Jami bajarish vaqti (soniya)")
    monthly_limit: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Reja bo'yicha oylik job limiti"
    )

    @computed_field(description="Limitdan qancha job qolgani")  # type: ignore[prop-decorator]
    @property
    def remaining(self) -> int:
        """`monthly_limit - job_count` (manfiy bo'lmaydi)."""
        return max(0, self.monthly_limit - self.job_count)

    @computed_field(description="Limitning qancha foizi ishlatilgani (0–100+)")  # type: ignore[prop-decorator]
    @property
    def usage_percent(self) -> float:
        """`job_count / monthly_limit * 100`."""
        if self.monthly_limit <= 0:
            return 0.0
        return round(self.job_count / self.monthly_limit * 100, 2)


class SuccessRateResponse(ORMSchema):
    """`GET /analytics/success-rate` — muvaffaqiyat foizi va uning dinamikasi."""

    start: datetime = Field(description="Oraliq boshlanishi (UTC)")
    end: datetime = Field(description="Oraliq tugashi (UTC)")
    interval: Interval = Field(default="hour", description="Vaqt qatori qadami")
    total: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Hisobga olingan yakunlangan job'lar soni"
    )
    success: Annotated[int, Field(ge=0)] = Field(default=0, description="Muvaffaqiyatli job'lar")
    failed: Annotated[int, Field(ge=0)] = Field(default=0, description="Muvaffaqiyatsiz job'lar")
    cancelled: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Bekor qilingan job'lar (foizga kirmaydi)"
    )
    dead_letter: Annotated[int, Field(ge=0)] = Field(
        default=0, description="DLQ'ga tushgan job'lar"
    )
    rate: float = Field(default=0.0, description="Umumiy muvaffaqiyat foizi (0–100)")
    points: list[TimeSeriesPoint] = Field(
        default_factory=list, description="Foizning vaqt bo'yicha o'zgarishi (0–100)"
    )
    breakdown: list[StatusSeriesPoint] = Field(
        default_factory=list, description="Har bir interval uchun holatlar bo'yicha ajratma"
    )
    top_failure_reasons: dict[str, int] = Field(
        default_factory=dict,
        description="Eng ko'p uchragan sabablar: sabab -> soni (`FailureReason` kalitlari)",
    )


class OverviewResponse(ORMSchema):
    """`GET /analytics/overview` — dashboard bosh sahifasining to'liq to'plami.

    Uchta ichma-ich blok (`jobs`, `executions`, `usage`) ataylab: frontend
    dashboard va analitika sahifalari AYNI javobdan foydalanadi, shuning
    uchun bitta so'rovda hamma kesim beriladi.

    `dlq_depth`, `queue_depth`, `active_workers` va `running_jobs` —
    HOZIRGI holat kesimi (oraliqqa bog'liq emas), chunki ular "hozir nima
    bo'lib turgani" degan savolga javob beradi.
    """

    start: datetime = Field(description="Oraliq boshlanishi (UTC)")
    end: datetime = Field(description="Oraliq tugashi (UTC)")
    jobs: JobStats = Field(description="Job'lar kesimi")
    executions: ExecutionStats = Field(description="Bajarish urinishlari kesimi")
    usage: UsageStats = Field(description="Joriy davr iste'moli va limiti")
    dlq_depth: Annotated[int, Field(ge=0)] = Field(
        default=0, description="DLQ chuqurligi — hal qilinmagan yozuvlar soni"
    )
    queue_depth: dict[str, int] = Field(
        default_factory=dict,
        description="Navbat chuqurligi: ustuvorlik -> kutayotgan job'lar soni",
    )
    avg_queue_wait_ms: float | None = Field(
        default=None, description="Navbatda kutishning o'rtacha vaqti (ms)"
    )
    jobs_change_percent: float | None = Field(
        default=None,
        description=(
            "Job sonining AYNI uzunlikdagi oldingi davrga nisbatan o'zgarishi (%); "
            "oldingi davrda ma'lumot bo'lmasa `null`"
        ),
    )
    queue_delayed: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Kechiktirilgan (ZSET) job'lar soni"
    )
    queue_processing: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Worker olgan, lekin hali tugatmagan job'lar soni"
    )
    active_workers: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Heartbeat yuborib turgan worker'lar soni"
    )
    running_jobs: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Hozir bajarilayotgan job'lar soni"
    )
    top_failure_reason: FailureReason | None = Field(
        default=None, description="Eng ko'p uchragan muvaffaqiyatsizlik sababi"
    )
    generated_at: datetime | None = Field(
        default=None, description="Ko'rsatkichlar hisoblangan vaqt (UTC)"
    )

    @computed_field(description="Navbatdagi barcha ustuvorliklar bo'yicha umumiy chuqurlik")  # type: ignore[prop-decorator]
    @property
    def queue_total(self) -> int:
        """`queue_depth` qiymatlarining yig'indisi."""
        return sum(self.queue_depth.values())


__all__ = [
    "DlqDepthPoint",
    "ExecutionStats",
    "Interval",
    "JobStats",
    "LatencyStats",
    "OverviewResponse",
    "StatusSeriesPoint",
    "SuccessRateResponse",
    "TimeSeriesPoint",
    "TimeSeriesResponse",
    "UsageStats",
]
