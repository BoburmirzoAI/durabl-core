"""Durabl — barcha enumlar va global konstantalar.

Bu modul loyihadagi eng past qatlam: hech qanday ichki modulga bog'liq emas.
Barcha boshqa qatlamlar (models, schemas, services, workers) shu yerdagi
enumlardan foydalanadi — "magic string" ishlatish qat'iyan taqiqlanadi.
"""

from __future__ import annotations

from enum import StrEnum as _NativeStrEnum

# ---------------------------------------------------------------------------
# Asosiy enumlar
# ---------------------------------------------------------------------------


class StrEnum(_NativeStrEnum):
    """Loyihadagi barcha enumlarning bazaviy klassi.

    Python 3.12 ning `enum.StrEnum`idan voris: `str` bilan solishtirish, JSON'ga
    to'g'ridan-to'g'ri serialize bo'lish va SQLAlchemy `Enum(native_enum=False)`
    bilan ishlash kafolatlangan. Bu yerda alohida klass sifatida o'ralishi
    sababi — loyiha bo'ylab yagona nom va kelajakda umumiy xatti-harakat
    qo'shish imkoniyati (`app.models.base` ham shu klassni tekshiradi).
    """


class JobStatus(StrEnum):
    """Job'ning hayot sikli holatlari.

    O'tish grafigi (faqat shu yo'nalishlar ruxsat etilgan):

        PENDING  -> QUEUED | CANCELLED
        QUEUED   -> RUNNING | CANCELLED
        RUNNING  -> SUCCESS | FAILED | RETRYING | QUEUED (lease yo'qolsa)
        RETRYING -> QUEUED | DEAD_LETTER
        FAILED   -> DEAD_LETTER | QUEUED (qo'lda retry)
    """

    PENDING = "pending"          # DB'ga yozildi, hali navbatga qo'yilmadi
    QUEUED = "queued"            # Redis navbatida, worker kutilmoqda
    RUNNING = "running"          # Worker sandbox'da bajarmoqda
    SUCCESS = "success"          # Muvaffaqiyatli tugadi (exit_code == 0)
    FAILED = "failed"            # Xato bilan tugadi, retry imkoni bor
    RETRYING = "retrying"        # Backoff kutilmoqda, qayta navbatga qo'yiladi
    CANCELLED = "cancelled"      # Mijoz bekor qildi
    DEAD_LETTER = "dead_letter"  # Barcha urinishlar tugadi -> DLQ

    @property
    def is_terminal(self) -> bool:
        """Yakuniy holatmi? (bundan keyin avtomatik o'zgarmaydi)"""
        return self in _TERMINAL_JOB_STATUSES

    @property
    def is_active(self) -> bool:
        """Job hali tizimda harakatdami?"""
        return self in _ACTIVE_JOB_STATUSES


_TERMINAL_JOB_STATUSES: frozenset[JobStatus] = frozenset(
    {
        JobStatus.SUCCESS,
        JobStatus.CANCELLED,
        JobStatus.DEAD_LETTER,
    }
)

_ACTIVE_JOB_STATUSES: frozenset[JobStatus] = frozenset(
    {
        JobStatus.PENDING,
        JobStatus.QUEUED,
        JobStatus.RUNNING,
        JobStatus.RETRYING,
    }
)

#: Ruxsat etilgan holat o'tishlari — `job_service` shu jadvalga tayanib tekshiradi.
JOB_STATUS_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.PENDING: frozenset({JobStatus.QUEUED, JobStatus.CANCELLED}),
    JobStatus.QUEUED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.SUCCESS,
            JobStatus.FAILED,
            JobStatus.RETRYING,
            JobStatus.QUEUED,      # lease muddati tugadi -> qayta navbatga
            JobStatus.CANCELLED,
        }
    ),
    JobStatus.RETRYING: frozenset({JobStatus.QUEUED, JobStatus.DEAD_LETTER, JobStatus.CANCELLED}),
    JobStatus.FAILED: frozenset({JobStatus.DEAD_LETTER, JobStatus.QUEUED, JobStatus.RETRYING}),
    JobStatus.SUCCESS: frozenset(),
    JobStatus.CANCELLED: frozenset(),
    JobStatus.DEAD_LETTER: frozenset({JobStatus.QUEUED}),  # DLQ'dan qo'lda qayta urinish
}


class ExecutionStatus(StrEnum):
    """Bitta bajarish urinishining holati."""

    PENDING = "pending"    # Yozildi, hali boshlanmadi
    RUNNING = "running"    # Sandbox ishlamoqda
    SUCCESS = "success"    # exit_code == 0
    FAILED = "failed"      # exit_code != 0 yoki ichki xato
    TIMEOUT = "timeout"    # Vaqt limiti oshdi
    CANCELLED = "cancelled"
    LOST = "lost"          # Lease tugadi, worker javob bermadi


class Runtime(StrEnum):
    """Qo'llab-quvvatlanadigan bajarish muhitlari."""

    PYTHON = "python"
    NODE = "node"


class Priority(StrEnum):
    """Navbat ustuvorligi — Redis'da alohida LIST'lar."""

    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"

    @property
    def weight(self) -> int:
        """Worker navbatlarni shu tartibda tekshiradi (kichik = birinchi)."""
        return _PRIORITY_WEIGHTS[self]


_PRIORITY_WEIGHTS: dict[Priority, int] = {
    Priority.HIGH: 0,
    Priority.NORMAL: 1,
    Priority.LOW: 2,
}

#: Worker navbatdan olish tartibi (yuqori ustuvorlik birinchi).
PRIORITY_ORDER: tuple[Priority, ...] = (Priority.HIGH, Priority.NORMAL, Priority.LOW)


class LogStream(StrEnum):
    """Bajarish logi qaysi oqimdan kelgani."""

    STDOUT = "stdout"
    STDERR = "stderr"
    SYSTEM = "system"  # Durabl'ning o'z xabarlari (lease yo'qoldi, timeout...)


class WebhookEvent(StrEnum):
    """Mijoz obuna bo'lishi mumkin bo'lgan hodisalar."""

    JOB_QUEUED = "job.queued"
    JOB_STARTED = "job.started"
    JOB_SUCCEEDED = "job.succeeded"
    JOB_FAILED = "job.failed"
    JOB_CANCELLED = "job.cancelled"
    JOB_DEAD_LETTERED = "job.dead_lettered"

    @classmethod
    def all(cls) -> list[str]:
        return [event.value for event in cls]


class DeliveryStatus(StrEnum):
    """Webhook yuborish natijasi."""

    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    RETRYING = "retrying"
    EXHAUSTED = "exhausted"  # Barcha urinishlar tugadi


class FailureReason(StrEnum):
    """Job nega muvaffaqiyatsiz bo'ldi — DLQ'da tasniflash uchun."""

    NON_ZERO_EXIT = "non_zero_exit"            # Kod xato bilan tugadi
    TIMEOUT = "timeout"                        # Vaqt limiti
    OOM = "out_of_memory"                      # Xotira limiti
    SANDBOX_ERROR = "sandbox_error"            # Konteyner yaratilmadi
    VALIDATION_ERROR = "validation_error"      # Kod validatsiyadan o'tmadi
    LEASE_LOST = "lease_lost"                  # Worker qulab tushdi
    MAX_RETRIES_EXCEEDED = "max_retries_exceeded"
    INTERNAL_ERROR = "internal_error"
    OUTPUT_TOO_LARGE = "output_too_large"


class PlanType(StrEnum):
    """Obuna rejalari."""

    FREE = "free"
    STARTER = "starter"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class AuditAction(StrEnum):
    """Admin audit jurnalidagi harakatlar."""

    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DEACTIVATED = "user.deactivated"
    USER_ACTIVATED = "user.activated"
    USER_PROMOTED = "user.promoted"
    JOB_CANCELLED = "job.cancelled"
    JOB_FORCE_RETRIED = "job.force_retried"
    DLQ_PURGED = "dlq.purged"
    API_KEY_REVOKED = "api_key.revoked"
    PLAN_CHANGED = "plan.changed"


class WorkerState(StrEnum):
    """Worker holati (admin panel uchun)."""

    STARTING = "starting"
    IDLE = "idle"
    BUSY = "busy"
    DRAINING = "draining"
    STOPPED = "stopped"
    DEAD = "dead"  # Heartbeat kelmay qoldi


# ---------------------------------------------------------------------------
# Reja limitlari (billing + rate limit)
# ---------------------------------------------------------------------------


class PlanLimits:
    """Bitta reja uchun cheklovlar to'plami (immutable)."""

    __slots__ = (
        "allow_network",
        "log_retention_days",
        "max_concurrent_jobs",
        "max_cpus",
        "max_memory_mb",
        "max_timeout_seconds",
        "monthly_jobs",
        "plan",
        "price_usd_month",
        "requests_per_minute",
    )

    def __init__(
        self,
        plan: PlanType,
        monthly_jobs: int,
        requests_per_minute: int,
        max_concurrent_jobs: int,
        max_timeout_seconds: int,
        max_memory_mb: int,
        max_cpus: float,
        log_retention_days: int,
        allow_network: bool,
        price_usd_month: float,
    ) -> None:
        self.plan = plan
        self.monthly_jobs = monthly_jobs
        self.requests_per_minute = requests_per_minute
        self.max_concurrent_jobs = max_concurrent_jobs
        self.max_timeout_seconds = max_timeout_seconds
        self.max_memory_mb = max_memory_mb
        self.max_cpus = max_cpus
        self.log_retention_days = log_retention_days
        self.allow_network = allow_network
        self.price_usd_month = price_usd_month

    def as_dict(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in self.__slots__}


#: Reja -> limitlar. `rate_limit` middleware va `billing_service` shundan oladi.
PLAN_LIMITS: dict[PlanType, PlanLimits] = {
    PlanType.FREE: PlanLimits(
        plan=PlanType.FREE,
        monthly_jobs=1_000,
        requests_per_minute=30,
        max_concurrent_jobs=2,
        max_timeout_seconds=30,
        max_memory_mb=256,
        max_cpus=0.5,
        log_retention_days=3,
        allow_network=False,
        price_usd_month=0.0,
    ),
    PlanType.STARTER: PlanLimits(
        plan=PlanType.STARTER,
        monthly_jobs=50_000,
        requests_per_minute=120,
        max_concurrent_jobs=10,
        max_timeout_seconds=120,
        max_memory_mb=512,
        max_cpus=1.0,
        log_retention_days=14,
        allow_network=True,
        price_usd_month=29.0,
    ),
    PlanType.PRO: PlanLimits(
        plan=PlanType.PRO,
        monthly_jobs=500_000,
        requests_per_minute=600,
        max_concurrent_jobs=50,
        max_timeout_seconds=300,
        max_memory_mb=1024,
        max_cpus=2.0,
        log_retention_days=30,
        allow_network=True,
        price_usd_month=99.0,
    ),
    PlanType.ENTERPRISE: PlanLimits(
        plan=PlanType.ENTERPRISE,
        monthly_jobs=10_000_000,
        requests_per_minute=5_000,
        max_concurrent_jobs=500,
        max_timeout_seconds=900,
        max_memory_mb=4096,
        max_cpus=4.0,
        log_retention_days=90,
        allow_network=True,
        price_usd_month=499.0,
    ),
}


def plan_limits(plan: PlanType | str) -> PlanLimits:
    """Reja bo'yicha limitlarni qaytaradi; noma'lum reja uchun FREE."""
    try:
        key = PlanType(plan)
    except ValueError:
        key = PlanType.FREE
    return PLAN_LIMITS[key]


# ---------------------------------------------------------------------------
# Redis kalit shablonlari — barcha joyda FAQAT shular ishlatiladi
# ---------------------------------------------------------------------------


class RedisKeys:
    """Redis kalitlarining yagona manbasi (single source of truth)."""

    PREFIX = "durabl"

    # Navbatlar (LIST) — RPUSH / BLMOVE
    @classmethod
    def queue(cls, priority: Priority | str) -> str:
        return f"{cls.PREFIX}:queue:{Priority(priority).value}"

    @classmethod
    def processing(cls, worker_id: str) -> str:
        """Worker olgan, lekin hali tugatmagan job'lar (reliable queue pattern)."""
        return f"{cls.PREFIX}:processing:{worker_id}"

    # Kechiktirilgan job'lar (ZSET, score = bajarish vaqti unix ts)
    DELAYED = f"{PREFIX}:delayed"

    # Lease (STRING, TTL)
    @classmethod
    def lease(cls, job_id: object) -> str:
        return f"{cls.PREFIX}:lease:{job_id}"

    # Idempotency (STRING, TTL 24s)
    @classmethod
    def idempotency(cls, user_id: object, key: str) -> str:
        return f"{cls.PREFIX}:idem:{user_id}:{key}"

    # Rate limit (STRING counter, TTL)
    @classmethod
    def rate_limit(cls, user_id: object, window: str) -> str:
        return f"{cls.PREFIX}:ratelimit:{user_id}:{window}"

    # Bir vaqtda bajarilayotgan job'lar soni (STRING counter)
    @classmethod
    def concurrency(cls, user_id: object) -> str:
        return f"{cls.PREFIX}:concurrency:{user_id}"

    # Worker ro'yxati va heartbeat
    WORKERS = f"{PREFIX}:workers"  # HASH: worker_id -> JSON holat

    @classmethod
    def worker_heartbeat(cls, worker_id: str) -> str:
        return f"{cls.PREFIX}:worker:hb:{worker_id}"

    # Pub/Sub kanallari
    EVENTS_JOBS = f"{PREFIX}:events:jobs"

    @classmethod
    def events_user(cls, user_id: object) -> str:
        return f"{cls.PREFIX}:events:user:{user_id}"

    # Cache
    @classmethod
    def cache(cls, namespace: str, key: object) -> str:
        return f"{cls.PREFIX}:cache:{namespace}:{key}"

    # Webhook navbati (LIST)
    WEBHOOK_QUEUE = f"{PREFIX}:queue:webhooks"

    # Taqsimlangan lock (scheduler/dlq_processor bitta nusxada ishlashi uchun)
    @classmethod
    def lock(cls, name: str) -> str:
        return f"{cls.PREFIX}:lock:{name}"


# ---------------------------------------------------------------------------
# Boshqa konstantalar
# ---------------------------------------------------------------------------

#: HTTP header nomlari
HEADER_IDEMPOTENCY_KEY = "Idempotency-Key"
HEADER_API_KEY = "X-API-Key"
HEADER_REQUEST_ID = "X-Request-ID"
HEADER_CORRELATION_ID = "X-Correlation-ID"
HEADER_WEBHOOK_SIGNATURE = "X-Durabl-Signature"
HEADER_WEBHOOK_TIMESTAMP = "X-Durabl-Timestamp"
HEADER_WEBHOOK_EVENT = "X-Durabl-Event"
HEADER_WEBHOOK_DELIVERY = "X-Durabl-Delivery-Id"
HEADER_RATELIMIT_LIMIT = "X-RateLimit-Limit"
HEADER_RATELIMIT_REMAINING = "X-RateLimit-Remaining"
HEADER_RATELIMIT_RESET = "X-RateLimit-Reset"

#: Sandbox ichidagi yo'llar
SANDBOX_WORKDIR = "/sandbox"
SANDBOX_CODE_FILENAME = {Runtime.PYTHON: "main.py", Runtime.NODE: "main.js"}
SANDBOX_PAYLOAD_FILENAME = "payload.json"
SANDBOX_RESULT_FILENAME = "result.json"

# ---------------------------------------------------------------------------
# Job metama'lumot chegaralari
# ---------------------------------------------------------------------------
# DIQQAT: bu chegaralar IKKI joyda tekshiriladi — `app/schemas/job.py`
# (HTTP 422) va `app/utils/validators.py` (service qatlami). Agar ikkisi
# turlicha bo'lsa, schema'dan o'tgan so'rov service'da yiqiladi va mijoz
# tushunarsiz xato oladi. Shuning uchun qiymatlar shu yerda — eng past
# qatlamda — bir marta e'lon qilinadi.

#: Bitta job'ga ilova qilinadigan teglar soni va uzunligi
MAX_TAGS: int = 20
MAX_TAG_LENGTH: int = 50

#: Sandbox'ga uzatiladigan muhit o'zgaruvchilari soni va o'lchamlari
MAX_ENV_VARS: int = 50
MAX_ENV_NAME_LENGTH: int = 64
MAX_ENV_VALUE_LENGTH: int = 4096

#: Muhit o'zgaruvchisi nomi shabloni. Katta-kichik harf IKKISI ham ruxsat —
#: xavfsizlik nazorati nomning registri emas, balki taqiqlangan nomlar
#: ro'yxati (`FORBIDDEN_ENV_NAMES`, registrdan qat'i nazar tekshiriladi).
ENV_NAME_PATTERN: str = r"^[A-Za-z_][A-Za-z0-9_]*$"

#: Zararli kod tekshiruvida taqiqlangan importlar (validators.py ishlatadi)
PYTHON_FORBIDDEN_IMPORTS: frozenset[str] = frozenset(
    {"ctypes", "multiprocessing", "subprocess", "pty", "fcntl", "resource"}
)
NODE_FORBIDDEN_MODULES: frozenset[str] = frozenset(
    {"child_process", "worker_threads", "v8", "vm", "cluster", "inspector"}
)

__all__ = [
    "ENV_NAME_PATTERN",
    "JOB_STATUS_TRANSITIONS",
    "MAX_ENV_NAME_LENGTH",
    "MAX_ENV_VALUE_LENGTH",
    "MAX_ENV_VARS",
    "MAX_TAGS",
    "MAX_TAG_LENGTH",
    "NODE_FORBIDDEN_MODULES",
    "PLAN_LIMITS",
    "PRIORITY_ORDER",
    "PYTHON_FORBIDDEN_IMPORTS",
    "SANDBOX_CODE_FILENAME",
    "SANDBOX_PAYLOAD_FILENAME",
    "SANDBOX_RESULT_FILENAME",
    "SANDBOX_WORKDIR",
    "AuditAction",
    "DeliveryStatus",
    "ExecutionStatus",
    "FailureReason",
    "JobStatus",
    "LogStream",
    "PlanLimits",
    "PlanType",
    "Priority",
    "RedisKeys",
    "Runtime",
    "StrEnum",
    "WebhookEvent",
    "WorkerState",
    "plan_limits",
]
