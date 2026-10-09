"""Durabl — markazlashgan sozlamalar (.env orqali).

Barcha modullar sozlamani FAQAT `from app.config import settings` orqali oladi.
`os.environ`ga bevosita murojaat qilish taqiqlanadi.
"""

from __future__ import annotations

import os
import socket
from functools import lru_cache
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Ilova sozlamalari. Har bir maydon .env faylidan yoki muhit o'zgaruvchisidan o'qiladi."""

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------
    # Ilova
    # ------------------------------------------------------------------
    APP_NAME: str = "Durabl"
    APP_VERSION: str = "1.0.0"
    ENV: Literal["development", "test", "staging", "production"] = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    #: Hujjatlar yoqilganmi (production'da o'chirilishi mumkin)
    ENABLE_DOCS: bool = True

    # ------------------------------------------------------------------
    # Ma'lumotlar bazasi (async SQLAlchemy)
    # ------------------------------------------------------------------
    DATABASE_URL: str = "postgresql+asyncpg://durabl:durabl@localhost:5432/durabl"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_POOL_RECYCLE: int = 1800
    #: `test` muhitida har test uchun yangi sxema yaratiladi
    DB_STATEMENT_TIMEOUT_MS: int = 30_000

    # ------------------------------------------------------------------
    # Redis (navbat, lease, cache, pub/sub)
    # ------------------------------------------------------------------
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_MAX_CONNECTIONS: int = 50
    REDIS_SOCKET_TIMEOUT: float = 5.0
    REDIS_SOCKET_CONNECT_TIMEOUT: float = 5.0
    #: Testlarda `fakeredis` ishlatish uchun
    REDIS_FAKE: bool = False

    # ------------------------------------------------------------------
    # Xavfsizlik
    # ------------------------------------------------------------------
    SECRET_KEY: str = "CHANGE-ME-insecure-development-secret-key-min-32-chars"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    #: API kalit prefiksi — mijoz ko'radigan kalit shu bilan boshlanadi
    API_KEY_PREFIX: str = "durabl_"
    API_KEY_RANDOM_BYTES: int = 32
    #: bcrypt murakkabligi (test'da 4 qilib tezlashtiriladi)
    BCRYPT_ROUNDS: int = 12
    PASSWORD_MIN_LENGTH: int = 8

    # ------------------------------------------------------------------
    # CORS
    # ------------------------------------------------------------------
    #: `NoDecode` — pydantic-settings bu maydonni JSON deb ochmaydi, xom matn
    #: `_split_csv` validatoriga yetib boradi. Shu tufayli `.env` da ikki shakl
    #: ham ishlaydi: `A,B,C` va `["A","B","C"]`.
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    CORS_ALLOW_CREDENTIALS: bool = True

    # ------------------------------------------------------------------
    # Navbat va ishonchlilik (Durabl yadrosi)
    # ------------------------------------------------------------------
    #: Worker job'ni olganda beriladigan lease muddati (soniya)
    LEASE_TTL_SECONDS: int = 15
    #: Worker har necha soniyada heartbeat yuboradi (LEASE_TTL/3 bo'lishi kerak)
    HEARTBEAT_INTERVAL_SECONDS: int = 5
    #: Lease tugaganini tekshirish davri (reaper)
    LEASE_REAPER_INTERVAL_SECONDS: int = 5

    #: Retry siyosati — eksponensial backoff
    DEFAULT_MAX_RETRIES: int = 3
    MAX_ALLOWED_RETRIES: int = 10
    RETRY_BASE_DELAY_SECONDS: float = 1.0
    RETRY_MULTIPLIER: float = 2.0
    RETRY_MAX_DELAY_SECONDS: float = 300.0
    #: Jitter — bir vaqtda ko'p job qayta urinmasligi uchun tasodifiy qo'shimcha
    RETRY_JITTER: bool = True
    RETRY_JITTER_RATIO: float = 0.25

    #: Idempotency kaliti qancha saqlanadi (24 soat)
    IDEMPOTENCY_TTL_SECONDS: int = 86_400

    # ------------------------------------------------------------------
    # Bajarish (execution)
    # ------------------------------------------------------------------
    DEFAULT_TIMEOUT_SECONDS: int = 30
    MAX_TIMEOUT_SECONDS: int = 900
    MIN_TIMEOUT_SECONDS: int = 1
    #: Mijoz yuborishi mumkin bo'lgan kod hajmi (256 KB)
    MAX_CODE_SIZE_BYTES: int = 262_144
    #: Payload (argumentlar) hajmi (1 MB)
    MAX_PAYLOAD_SIZE_BYTES: int = 1_048_576
    #: Yig'iladigan stdout/stderr hajmi (1 MB) — oshsa kesiladi
    MAX_OUTPUT_BYTES: int = 1_048_576
    #: Bitta log yozuvi hajmi
    MAX_LOG_CHUNK_BYTES: int = 16_384
    #: Kod validatsiyasi qat'iyligi
    CODE_VALIDATION_ENABLED: bool = True
    CODE_VALIDATION_STRICT: bool = False

    # ------------------------------------------------------------------
    # Sandbox (gVisor)
    # ------------------------------------------------------------------
    #: False bo'lsa — kod lokal subprocess'da bajariladi (FAQAT development/test)
    SANDBOX_ENABLED: bool = False
    #: Docker runtime: production'da `runsc` (gVisor), lokalda `runc`
    SANDBOX_RUNTIME: str = "runsc"
    SANDBOX_NETWORK_MODE: str = "none"
    SANDBOX_MEMORY_MB: int = 256
    SANDBOX_CPUS: float = 0.5
    SANDBOX_PIDS_LIMIT: int = 50
    SANDBOX_DISK_MB: int = 64
    SANDBOX_READ_ONLY_ROOTFS: bool = True
    SANDBOX_IMAGE_PYTHON: str = "durabl/runner-python:latest"
    SANDBOX_IMAGE_NODE: str = "durabl/runner-node:latest"
    SANDBOX_DOCKER_HOST: str | None = None
    #: Konteyner o'ldirilgandan keyin tozalashni kutish vaqti
    SANDBOX_KILL_GRACE_SECONDS: float = 2.0
    #: Sandbox yaratish uchun maksimal kutish
    SANDBOX_STARTUP_TIMEOUT_SECONDS: float = 30.0
    SANDBOX_SECCOMP_PROFILE: str | None = None
    SANDBOX_TMPFS_SIZE_MB: int = 32
    SANDBOX_USER: str = "10001:10001"

    # ------------------------------------------------------------------
    # Worker
    # ------------------------------------------------------------------
    #: Bitta worker protsessida nechta job parallel bajariladi
    WORKER_CONCURRENCY: int = 4
    #: Navbatdan olishda BLPOP kutish vaqti
    WORKER_POLL_TIMEOUT_SECONDS: int = 5
    #: Worker identifikatori (bo'sh bo'lsa hostname+pid'dan yasaladi)
    WORKER_ID: str = ""
    #: To'xtatishda joriy job'larni tugatishni kutish
    WORKER_SHUTDOWN_GRACE_SECONDS: float = 30.0
    #: Worker heartbeat'i Redis'da qancha yashaydi
    WORKER_REGISTRY_TTL_SECONDS: int = 30

    # ------------------------------------------------------------------
    # Scheduler (kechiktirilgan va cron job'lar)
    # ------------------------------------------------------------------
    SCHEDULER_ENABLED: bool = True
    SCHEDULER_INTERVAL_SECONDS: float = 1.0
    SCHEDULER_BATCH_SIZE: int = 100

    # ------------------------------------------------------------------
    # DLQ processor
    # ------------------------------------------------------------------
    DLQ_PROCESSOR_ENABLED: bool = True
    DLQ_PROCESSOR_INTERVAL_SECONDS: float = 30.0
    DLQ_AUTO_RETRY_ENABLED: bool = False
    DLQ_AUTO_RETRY_MAX_ATTEMPTS: int = 1
    #: DLQ chuqurligi shu qiymatdan oshsa alert yuboriladi
    DLQ_ALERT_THRESHOLD: int = 100

    # ------------------------------------------------------------------
    # Webhook
    # ------------------------------------------------------------------
    WEBHOOK_ENABLED: bool = True
    WEBHOOK_TIMEOUT_SECONDS: float = 10.0
    WEBHOOK_MAX_RETRIES: int = 5
    WEBHOOK_BASE_DELAY_SECONDS: float = 2.0
    WEBHOOK_MAX_DELAY_SECONDS: float = 3600.0
    WEBHOOK_SENDER_INTERVAL_SECONDS: float = 1.0
    WEBHOOK_SENDER_BATCH_SIZE: int = 50
    #: Imzo eskirgan deb hisoblanadigan vaqt (replay hujumiga qarshi)
    WEBHOOK_SIGNATURE_TOLERANCE_SECONDS: int = 300
    #: SSRF himoyasi — mahalliy manzillarga webhook yuborilmaydi
    WEBHOOK_BLOCK_PRIVATE_IPS: bool = True
    WEBHOOK_ALLOWED_SCHEMES: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["https", "http"]
    )

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------
    RATE_LIMIT_ENABLED: bool = True
    #: Autentifikatsiyasiz so'rovlar uchun IP bo'yicha limit (daqiqada)
    RATE_LIMIT_ANONYMOUS_PER_MINUTE: int = 20

    # ------------------------------------------------------------------
    # Analitika va cache
    # ------------------------------------------------------------------
    STATS_CACHE_TTL_SECONDS: int = 30
    ANALYTICS_MAX_RANGE_DAYS: int = 90

    # ------------------------------------------------------------------
    # WebSocket
    # ------------------------------------------------------------------
    WS_HEARTBEAT_INTERVAL_SECONDS: float = 30.0
    WS_MAX_CONNECTIONS_PER_USER: int = 5
    WS_SEND_QUEUE_SIZE: int = 256

    # ------------------------------------------------------------------
    # Observability
    # ------------------------------------------------------------------
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    #: `json` — production, `console` — development
    LOG_FORMAT: Literal["json", "console"] = "console"
    METRICS_ENABLED: bool = True
    METRICS_PATH: str = "/metrics"
    SENTRY_DSN: str | None = None
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1

    # ------------------------------------------------------------------
    # Notifications
    # ------------------------------------------------------------------
    NOTIFICATIONS_ENABLED: bool = False
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str = "noreply@durabl.dev"
    ALERT_WEBHOOK_URL: str | None = None

    # ------------------------------------------------------------------
    # Bootstrap admin (birinchi ishga tushirishda yaratiladi)
    # ------------------------------------------------------------------
    BOOTSTRAP_ADMIN_EMAIL: str | None = None
    BOOTSTRAP_ADMIN_PASSWORD: str | None = None

    # ------------------------------------------------------------------
    # Validatorlar
    # ------------------------------------------------------------------

    @field_validator("CORS_ORIGINS", "WEBHOOK_ALLOWED_SCHEMES", mode="before")
    @classmethod
    def _split_csv(cls, value: Any) -> Any:
        """Ro'yxat sozlamasini ikki shaklda qabul qiladi.

        * `A,B,C` — vergul bilan ajratilgan (odatdagi `.env` uslubi)
        * `["A","B","C"]` — JSON massiv

        Maydonlar `Annotated[list[str], NoDecode]` bilan belgilangani uchun
        pydantic-settings qiymatni JSON deb ochishga URINMAYDI va xom matn
        shu validatorga yetib keladi. `NoDecode` bo'lmasa `EnvSettingsSource`
        avval `json.loads` qilib, CSV qiymatda `SettingsError` bilan yiqiladi
        (ya'ni ilova umuman ko'tarilmaydi).
        """
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return []
            if stripped.startswith("["):
                import json  # faqat JSON shakli uchun

                try:
                    parsed = json.loads(stripped)
                except ValueError as exc:
                    raise ValueError(
                        f"Ro'yxat sozlamasi yaroqsiz JSON: {stripped[:60]}"
                    ) from exc
                if not isinstance(parsed, list):
                    raise ValueError("Ro'yxat sozlamasi JSON massiv bo'lishi kerak")
                return [str(item).strip() for item in parsed if str(item).strip()]
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def _normalize_database_url(cls, value: Any) -> Any:
        """Sinxron URL berilsa, async drayverga o'tkazadi."""
        if isinstance(value, str):
            if value.startswith("postgresql://"):
                return value.replace("postgresql://", "postgresql+asyncpg://", 1)
            if value.startswith("postgres://"):
                return value.replace("postgres://", "postgresql+asyncpg://", 1)
            if value.startswith("sqlite://") and "+aiosqlite" not in value:
                return value.replace("sqlite://", "sqlite+aiosqlite://", 1)
        return value

    @model_validator(mode="after")
    def _validate_coherence(self) -> Settings:
        """O'zaro bog'liq sozlamalarni tekshiradi."""
        if self.HEARTBEAT_INTERVAL_SECONDS >= self.LEASE_TTL_SECONDS:
            raise ValueError(
                "HEARTBEAT_INTERVAL_SECONDS LEASE_TTL_SECONDS'dan kichik bo'lishi shart "
                "(aks holda lease yangilanishga ulgurmaydi)"
            )
        if self.MIN_TIMEOUT_SECONDS > self.DEFAULT_TIMEOUT_SECONDS:
            raise ValueError("MIN_TIMEOUT_SECONDS > DEFAULT_TIMEOUT_SECONDS bo'lishi mumkin emas")
        if self.DEFAULT_TIMEOUT_SECONDS > self.MAX_TIMEOUT_SECONDS:
            raise ValueError("DEFAULT_TIMEOUT_SECONDS > MAX_TIMEOUT_SECONDS bo'lishi mumkin emas")
        if self.is_production:
            if "CHANGE-ME" in self.SECRET_KEY or len(self.SECRET_KEY) < 32:
                raise ValueError(
                    "Production muhitida SECRET_KEY almashtirilishi va kamida 32 belgi bo'lishi shart"
                )
            if not self.SANDBOX_ENABLED:
                # DARHOL yiqilamiz, chunki aks holda ilova ko'tariladi, job'larni
                # qabul qiladi va har biri bajarish paytida `SandboxUnavailableError`
                # bilan yiqiladi (`LocalRunner` production'da ataylab ishlamaydi).
                # Mijoz uchun bu "job'lar jimgina ishlamaydi" degani — xato
                # konfiguratsiyani ishga tushishda ko'rsatish ancha yaxshi.
                raise ValueError(
                    "Production muhitida SANDBOX_ENABLED=True bo'lishi SHART. "
                    "Aks holda mijoz kodini bajaradigan izolyatsiyalangan muhit yo'q: "
                    "lokal subprocess runner production'da ataylab ishlamaydi. "
                    "gVisor o'rnatish: `make gvisor-install`, image'lar: `make sandbox-build`."
                )
        return self

    # ------------------------------------------------------------------
    # Hisoblanadigan xossalar
    # ------------------------------------------------------------------

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"

    @property
    def is_test(self) -> bool:
        return self.ENV == "test"

    @property
    def is_development(self) -> bool:
        return self.ENV == "development"

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @property
    def sync_database_url(self) -> str:
        """Alembic uchun sinxron URL (asyncpg -> psycopg2 emas, balki asyncpg'ni olib tashlash)."""
        return (
            self.DATABASE_URL.replace("+asyncpg", "")
            .replace("+aiosqlite", "")
        )

    @property
    def worker_id(self) -> str:
        """Worker identifikatori: sozlamada bo'lmasa hostname-pid."""
        return self.WORKER_ID or f"{socket.gethostname()}-{os.getpid()}"

    @property
    def docs_url(self) -> str | None:
        return "/docs" if self.ENABLE_DOCS else None

    @property
    def redoc_url(self) -> str | None:
        return "/redoc" if self.ENABLE_DOCS else None

    @property
    def openapi_url(self) -> str | None:
        return "/openapi.json" if self.ENABLE_DOCS else None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Sozlamalarni bir marta o'qib keshlaydi (FastAPI dependency sifatida ham ishlaydi)."""
    return Settings()


#: Global sozlamalar — hamma joyda shundan foydalaniladi.
settings: Settings = get_settings()


def reload_settings() -> Settings:
    """Testlarda muhit o'zgargandan keyin sozlamani qayta o'qish uchun."""
    global settings
    get_settings.cache_clear()
    settings = get_settings()
    return settings


__all__ = ["Settings", "get_settings", "reload_settings", "settings"]
