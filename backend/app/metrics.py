"""Durabl — Prometheus metrikalari.

`GET /metrics` endpointi `render_metrics()` natijasini qaytaradi; Prometheus
uni yig'adi, Grafana grafik qiladi.

**Muhim texnik nuqta — `Duplicated timeseries` xatosi.** `prometheus_client`
global `REGISTRY`ga bir xil nomdagi metrikani ikki marta qo'shishga ruxsat
bermaydi. Bu modul bir protsessda bir marta yuklanadi, lekin quyidagi
holatlarda ikki marta bajarilishi mumkin:

* testlarda modul `importlib.reload()` qilinsa;
* worker protsessi ilovani boshqa yo'l bilan (`app.metrics` va
  `backend.app.metrics`) import qilsa;
* `--reload` rejimida kod qayta yuklanganda.

Shu sababli har bir metrika `_metric()` yordamchisi orqali yaratiladi: nom
allaqachon ro'yxatga olingan bo'lsa, yangisini yaratish o'rniga MAVJUDI
qaytariladi. Natijada import hech qachon yiqilmaydi va hisoblagichlar
yo'qolmaydi.

Barcha `track_*`/`set_*`/`observe_*` funksiyalari `METRICS_ENABLED=False`
bo'lganda jim ishlaydi (hech narsa qilmaydi), shu tufayli chaqiruv joylarida
`if settings.METRICS_ENABLED:` yozish kerak emas.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import Enum
from typing import Any, Final, cast

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)
from prometheus_client.metrics import MetricWrapperBase

from app.config import settings
from app.constants import PRIORITY_ORDER, Priority

# ---------------------------------------------------------------------------
# Takroriy ro'yxatga olishdan himoyalangan yaratish
# ---------------------------------------------------------------------------


def _registered(name: str) -> MetricWrapperBase | None:
    """`REGISTRY`da shu nomdagi metrikani topadi (bo'lmasa `None`).

    Counter uchun kutubxona bir necha nom ro'yxatga oladi
    (`jobs_submitted`, `jobs_submitted_total`, `jobs_submitted_created`) —
    shuning uchun bir nechta ko'rinish bo'yicha qidiriladi.
    """
    collectors: Mapping[str, Any] = getattr(REGISTRY, "_names_to_collectors", {})
    for candidate in (name, name.removesuffix("_total"), f"{name}_total"):
        collector = collectors.get(candidate)
        if isinstance(collector, MetricWrapperBase):
            return collector
    return None


def _metric[MetricT: MetricWrapperBase](
    factory: Callable[..., MetricT],
    name: str,
    documentation: str,
    **kwargs: Any,
) -> MetricT:
    """Metrikani yaratadi; allaqachon mavjud bo'lsa — mavjudini qayta ishlatadi.

    Shu yordamchi tufayli modulning ikki marta yuklanishi
    `Duplicated timeseries in CollectorRegistry` xatosiga olib kelmaydi.
    """
    try:
        return factory(name, documentation, registry=REGISTRY, **kwargs)
    except ValueError:
        existing = _registered(name)
        if existing is None:
            raise  # Boshqa sabab — yashirmaymiz
        return cast("MetricT", existing)


def _label(value: object) -> str:
    """Label qiymatini matnga aylantiradi (`Enum` -> qiymati)."""
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


# ---------------------------------------------------------------------------
# Histogram bucket'lari
# ---------------------------------------------------------------------------

#: Job bajarilish vaqti — millisekunddan 10 daqiqagacha (MAX_TIMEOUT_SECONDS=900).
JOB_DURATION_BUCKETS: Final[tuple[float, ...]] = (
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
    600.0,
    900.0,
)
#: Navbatda kutish — SLA uchun eng muhim ko'rsatkich, pastda zich.
QUEUE_WAIT_BUCKETS: Final[tuple[float, ...]] = (
    0.005,
    0.01,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    300.0,
)
#: Sandbox (konteyner) yaratish — gVisor odatda 100-500 ms.
SANDBOX_CREATE_BUCKETS: Final[tuple[float, ...]] = (
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.0,
    5.0,
    10.0,
    30.0,
)
#: Webhook yuborish — tashqi HTTP (WEBHOOK_TIMEOUT_SECONDS=10).
WEBHOOK_DURATION_BUCKETS: Final[tuple[float, ...]] = (
    0.01,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)
#: HTTP so'rov — API javob tezligi.
HTTP_DURATION_BUCKETS: Final[tuple[float, ...]] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)


# ---------------------------------------------------------------------------
# Job metrikalari
# ---------------------------------------------------------------------------

jobs_submitted_total: Final = _metric(
    Counter,
    "jobs_submitted_total",
    "Qabul qilingan job'lar umumiy soni",
)

jobs_completed_total: Final = _metric(
    Counter,
    "jobs_completed_total",
    "Yakunlangan job'lar soni (yakuniy holat bo'yicha)",
    labelnames=("status",),
)

job_duration_seconds: Final = _metric(
    Histogram,
    "job_duration_seconds",
    "Job bajarilish davomiyligi (soniya)",
    buckets=JOB_DURATION_BUCKETS,
)

job_queue_wait_seconds: Final = _metric(
    Histogram,
    "job_queue_wait_seconds",
    "Job navbatda kutgan vaqti (navbatga qo'yilishdan worker olishiga qadar, soniya)",
    buckets=QUEUE_WAIT_BUCKETS,
)

retries_total: Final = _metric(
    Counter,
    "retries_total",
    "Qayta urinishlar umumiy soni",
)


# ---------------------------------------------------------------------------
# Navbat va ishonchlilik metrikalari
# ---------------------------------------------------------------------------

queue_depth: Final = _metric(
    Gauge,
    "queue_depth",
    "Navbatdagi job'lar soni (ustuvorlik bo'yicha)",
    labelnames=("priority",),
)

dlq_depth: Final = _metric(
    Gauge,
    "dlq_depth",
    "DLQ (o'lik xatlar navbati) chuqurligi — hal qilinmagan yozuvlar soni",
)

active_workers: Final = _metric(
    Gauge,
    "active_workers",
    "Tirik (heartbeat yuborayotgan) worker'lar soni",
)

lease_expirations_total: Final = _metric(
    Counter,
    "lease_expirations_total",
    "Muddati tugagan lease'lar soni (worker qulagani belgisi)",
)


# ---------------------------------------------------------------------------
# Bajarish (execution) va sandbox metrikalari
# ---------------------------------------------------------------------------

executions_total: Final = _metric(
    Counter,
    "executions_total",
    "Bajarish urinishlari soni (holat va muhit bo'yicha)",
    labelnames=("status", "runtime"),
)

sandbox_create_duration_seconds: Final = _metric(
    Histogram,
    "sandbox_create_duration_seconds",
    "Sandbox (konteyner) yaratish davomiyligi (soniya)",
    buckets=SANDBOX_CREATE_BUCKETS,
)


# ---------------------------------------------------------------------------
# Webhook metrikalari
# ---------------------------------------------------------------------------

webhook_deliveries_total: Final = _metric(
    Counter,
    "webhook_deliveries_total",
    "Webhook yuborish urinishlari soni (natija bo'yicha)",
    labelnames=("status",),
)

webhook_delivery_duration_seconds: Final = _metric(
    Histogram,
    "webhook_delivery_duration_seconds",
    "Webhook yuborish davomiyligi (soniya)",
    buckets=WEBHOOK_DURATION_BUCKETS,
)


# ---------------------------------------------------------------------------
# HTTP metrikalari
# ---------------------------------------------------------------------------

# DIQQAT: label nomi `path` — CONTRACTS.md §9, docs/RELIABILITY.md,
# docs/ARCHITECTURE.md va infra/prometheus/prometheus.yml hammasi
# `http_requests_total{method,path,status}` deb kelishgan. Grafana so'rovlari
# shu nomga tayanadi, shuning uchun uni o'zgartirish taqiqlanadi.
http_requests_total: Final = _metric(
    Counter,
    "http_requests_total",
    "HTTP so'rovlar soni (metod, yo'l shabloni, status bo'yicha)",
    labelnames=("method", "path", "status"),
)

http_request_duration_seconds: Final = _metric(
    Histogram,
    "http_request_duration_seconds",
    "HTTP so'rovga javob berish davomiyligi (soniya)",
    labelnames=("method", "path"),
    buckets=HTTP_DURATION_BUCKETS,
)


# ---------------------------------------------------------------------------
# Qulay (convenience) funksiyalar
# ---------------------------------------------------------------------------


def render_metrics() -> tuple[bytes, str]:
    """`GET /metrics` uchun tayyor javob: `(tana, content_type)`."""
    return generate_latest(REGISTRY), CONTENT_TYPE_LATEST


def track_request(method: str, path: str, status: int | str, duration: float) -> None:
    """HTTP so'rovni qayd qiladi (`RequestLoggingMiddleware` chaqiradi).

    Args:
        method: HTTP metodi.
        path: Yo'l **shabloni** (`/api/v1/jobs/{job_id}`), xom yo'l emas —
            aks holda har bir UUID yangi timeseries yaratib, metrikalar
            portlab ketadi (high cardinality).
        status: HTTP status kodi.
        duration: Davomiylik (soniya).
    """
    if not settings.METRICS_ENABLED:
        return
    method_label = method.upper()
    http_requests_total.labels(method=method_label, path=path, status=_label(status)).inc()
    http_request_duration_seconds.labels(method=method_label, path=path).observe(max(0.0, duration))


def track_job_submitted(count: int = 1) -> None:
    """Yangi job qabul qilindi."""
    if settings.METRICS_ENABLED:
        jobs_submitted_total.inc(count)


def track_job_completed(status: object, *, duration_seconds: float | None = None) -> None:
    """Job yakuniy holatga keldi (`JobStatus`), davomiyligi bilan."""
    if not settings.METRICS_ENABLED:
        return
    jobs_completed_total.labels(status=_label(status)).inc()
    if duration_seconds is not None:
        job_duration_seconds.observe(max(0.0, duration_seconds))


def observe_job_duration(duration_seconds: float) -> None:
    """Job bajarilish davomiyligini qayd qiladi (soniya)."""
    if settings.METRICS_ENABLED:
        job_duration_seconds.observe(max(0.0, duration_seconds))


def observe_job_duration_ms(duration_milliseconds: int | float) -> None:
    """`Job.duration_ms` qiymatini soniyaga aylantirib qayd qiladi."""
    observe_job_duration(float(duration_milliseconds) / 1000.0)


def observe_queue_wait(wait_seconds: float) -> None:
    """Job navbatda qancha kutganini qayd qiladi (soniya)."""
    if settings.METRICS_ENABLED:
        job_queue_wait_seconds.observe(max(0.0, wait_seconds))


def set_queue_depth(depths: Mapping[Priority | str, int]) -> None:
    """Navbat chuqurligini yangilaydi (`QueueService.depth()` natijasi)."""
    if not settings.METRICS_ENABLED:
        return
    for priority, depth in depths.items():
        queue_depth.labels(priority=_label(priority)).set(depth)


def set_dlq_depth(depth: int) -> None:
    """DLQ chuqurligini yangilaydi."""
    if settings.METRICS_ENABLED:
        dlq_depth.set(depth)


def set_active_workers(count: int) -> None:
    """Tirik worker'lar sonini yangilaydi."""
    if settings.METRICS_ENABLED:
        active_workers.set(count)


def track_execution(status: object, runtime: object) -> None:
    """Bitta bajarish urinishi yakunlandi (`ExecutionStatus`, `Runtime`)."""
    if settings.METRICS_ENABLED:
        executions_total.labels(status=_label(status), runtime=_label(runtime)).inc()


def observe_sandbox_create(duration_seconds: float) -> None:
    """Sandbox yaratish davomiyligini qayd qiladi (soniya)."""
    if settings.METRICS_ENABLED:
        sandbox_create_duration_seconds.observe(max(0.0, duration_seconds))


def track_webhook_delivery(status: object, *, duration_seconds: float | None = None) -> None:
    """Webhook yuborish urinishini qayd qiladi (`DeliveryStatus`)."""
    if not settings.METRICS_ENABLED:
        return
    webhook_deliveries_total.labels(status=_label(status)).inc()
    if duration_seconds is not None:
        webhook_delivery_duration_seconds.observe(max(0.0, duration_seconds))


def track_lease_expiration(count: int = 1) -> None:
    """Lease muddati tugadi — job boshqa worker'ga o'tkaziladi."""
    if settings.METRICS_ENABLED and count > 0:
        lease_expirations_total.inc(count)


def track_retry(count: int = 1) -> None:
    """Job qayta urinishga rejalashtirildi."""
    if settings.METRICS_ENABLED and count > 0:
        retries_total.inc(count)


def _initialize_label_values() -> None:
    """Label'li metrikalar uchun boshlang'ich (0) qiymatlar.

    Grafana paneli birinchi hodisani kutib bo'sh turmasligi uchun barcha
    ustuvorliklar darhol ko'rinadi.
    """
    for priority in PRIORITY_ORDER:
        queue_depth.labels(priority=priority.value)


_initialize_label_values()


__all__ = [
    "HTTP_DURATION_BUCKETS",
    "JOB_DURATION_BUCKETS",
    "QUEUE_WAIT_BUCKETS",
    "SANDBOX_CREATE_BUCKETS",
    "WEBHOOK_DURATION_BUCKETS",
    "active_workers",
    "dlq_depth",
    "executions_total",
    "http_request_duration_seconds",
    "http_requests_total",
    "job_duration_seconds",
    "job_queue_wait_seconds",
    "jobs_completed_total",
    "jobs_submitted_total",
    "lease_expirations_total",
    "observe_job_duration",
    "observe_job_duration_ms",
    "observe_queue_wait",
    "observe_sandbox_create",
    "queue_depth",
    "render_metrics",
    "retries_total",
    "sandbox_create_duration_seconds",
    "set_active_workers",
    "set_dlq_depth",
    "set_queue_depth",
    "track_execution",
    "track_job_completed",
    "track_job_submitted",
    "track_lease_expiration",
    "track_request",
    "track_retry",
    "track_webhook_delivery",
    "webhook_deliveries_total",
    "webhook_delivery_duration_seconds",
]
