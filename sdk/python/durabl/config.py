"""Durabl SDK sozlamalari.

Sozlama uch manbadan olinadi (ustuvorlik tartibida):

  1. Konstruktorga bevosita berilgan qiymat — `DurablClient(api_key="durabl_...")`;
  2. Muhit o'zgaruvchisi — `DURABL_API_KEY`, `DURABL_BASE_URL`, ...;
  3. Standart qiymat — `https://api.durabl.dev`, timeout 30s va h.k.

SDK backend paketiga bog'lanmaydi: bu yerda `app.config` emas, oddiy
`os.environ` ishlatiladi (mustaqil kutubxona uchun shu to'g'ri yo'l).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any

from ._version import USER_AGENT
from .exceptions import DurablConfigError

# ---------------------------------------------------------------------------
# Standart qiymatlar
# ---------------------------------------------------------------------------

#: Durabl bulutining standart manzili.
DEFAULT_BASE_URL = "https://api.durabl.dev"
#: API versiyasi prefiksi (backend `settings.API_V1_PREFIX` bilan bir xil).
DEFAULT_API_PREFIX = "/api/v1"
#: Bitta HTTP so'rov uchun kutish vaqti (soniya).
DEFAULT_TIMEOUT = 30.0
#: Qayta urinishlar soni (429 va 5xx uchun).
DEFAULT_MAX_RETRIES = 3
#: Eksponensial backoff bazasi: 0.5s -> 1s -> 2s -> 4s ...
DEFAULT_RETRY_BACKOFF = 0.5
#: Backoff qancha o'ssa ham shu qiymatdan oshmaydi (soniya).
DEFAULT_RETRY_MAX_DELAY = 30.0

# ---------------------------------------------------------------------------
# Muhit o'zgaruvchilari
# ---------------------------------------------------------------------------

ENV_API_KEY = "DURABL_API_KEY"
ENV_BASE_URL = "DURABL_BASE_URL"
ENV_TIMEOUT = "DURABL_TIMEOUT"
ENV_MAX_RETRIES = "DURABL_MAX_RETRIES"
ENV_RETRY_BACKOFF = "DURABL_RETRY_BACKOFF"

#: HTTP sarlavha nomlari (backend `app/constants.py` bilan bir xil).
HEADER_API_KEY = "X-API-Key"
HEADER_IDEMPOTENCY_KEY = "Idempotency-Key"
HEADER_REQUEST_ID = "X-Request-ID"


@dataclass
class DurablConfig:
    """Mijoz sozlamalari.

    Maydonlar:
        api_key: API kalit (`durabl_...`). Berilmasa `DURABL_API_KEY`dan olinadi.
        base_url: Server manzili. Berilmasa `DURABL_BASE_URL` yoki standart qiymat.
        timeout: Bitta HTTP so'rov uchun kutish vaqti (soniya).
        max_retries: 429/5xx javoblarda necha marta qayta urinish.
        retry_backoff: Eksponensial backoff bazasi (soniya).
        retry_max_delay: Backoff uchun yuqori chegara (soniya).
        api_prefix: API prefiksi — odatda `/api/v1`.
        verify_ssl: TLS sertifikatini tekshirish (lokal serverda `False` qilish mumkin).
        user_agent: `User-Agent` sarlavhasi.
        extra_headers: Har so'rovga qo'shiladigan qo'shimcha sarlavhalar.

    `base_url` va `api_key` konstruktorda `None` bo'lishi mumkin, lekin
    obyekt yaratilgandan keyin `base_url` har doim to'ldirilgan matn bo'ladi.
    """

    api_key: str | None = None
    base_url: str | None = None
    timeout: float = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_MAX_RETRIES
    retry_backoff: float = DEFAULT_RETRY_BACKOFF
    retry_max_delay: float = DEFAULT_RETRY_MAX_DELAY
    api_prefix: str = DEFAULT_API_PREFIX
    verify_ssl: bool = True
    user_agent: str = USER_AGENT
    extra_headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Muhit o'zgaruvchilarini qo'shadi va qiymatlarni tekshiradi."""
        if not self.api_key:
            self.api_key = os.environ.get(ENV_API_KEY) or None
        if not self.base_url:
            self.base_url = os.environ.get(ENV_BASE_URL) or DEFAULT_BASE_URL

        # Manzil oxiridagi `/` olib tashlanadi — yo'llar qo'shilganda ikki `//`
        # paydo bo'lmasligi uchun.
        self.base_url = self.base_url.rstrip("/")
        if not self.base_url:
            raise DurablConfigError("base_url bo'sh bo'lishi mumkin emas")
        if "://" not in self.base_url:
            raise DurablConfigError(
                f"base_url sxema bilan boshlanishi kerak (http:// yoki https://): {self.base_url!r}"
            )

        self.api_prefix = "/" + self.api_prefix.strip("/") if self.api_prefix.strip("/") else ""

        self.timeout = float(self.timeout)
        if self.timeout <= 0:
            raise DurablConfigError("timeout noldan katta bo'lishi kerak")

        self.max_retries = int(self.max_retries)
        if self.max_retries < 0:
            raise DurablConfigError("max_retries manfiy bo'lishi mumkin emas")

        self.retry_backoff = float(self.retry_backoff)
        if self.retry_backoff < 0:
            raise DurablConfigError("retry_backoff manfiy bo'lishi mumkin emas")

        self.retry_max_delay = float(self.retry_max_delay)
        if self.retry_max_delay < 0:
            raise DurablConfigError("retry_max_delay manfiy bo'lishi mumkin emas")

    # ------------------------------------------------------------------
    # Yaratuvchilar
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls, **overrides: Any) -> DurablConfig:
        """Sozlamani to'liq muhit o'zgaruvchilaridan yasaydi.

        `overrides` orqali alohida maydonlarni ustun qilib berish mumkin:
        `DurablConfig.from_env(timeout=5)`.
        """
        values: dict[str, Any] = {
            "api_key": os.environ.get(ENV_API_KEY) or None,
            "base_url": os.environ.get(ENV_BASE_URL) or None,
            "timeout": _env_float(ENV_TIMEOUT, DEFAULT_TIMEOUT),
            "max_retries": _env_int(ENV_MAX_RETRIES, DEFAULT_MAX_RETRIES),
            "retry_backoff": _env_float(ENV_RETRY_BACKOFF, DEFAULT_RETRY_BACKOFF),
        }
        values.update({key: value for key, value in overrides.items() if value is not None})
        return cls(**values)

    def merge(self, **overrides: Any) -> DurablConfig:
        """Joriy sozlama asosida yangi nusxa qaytaradi (`None` qiymatlar e'tiborsiz).

        `extra_headers` nusxalanadi — yangi mijoz sarlavha qo'shganda asl
        sozlama o'zgarmasligi kerak.
        """
        clean = {key: value for key, value in overrides.items() if value is not None}
        clean.setdefault("extra_headers", dict(self.extra_headers))
        return replace(self, **clean)

    # ------------------------------------------------------------------
    # Yordamchilar
    # ------------------------------------------------------------------

    def require_api_key(self) -> str:
        """API kalitni qaytaradi; bo'lmasa tushunarli xato beradi."""
        if not self.api_key:
            raise DurablConfigError(
                "API kalit berilmagan. DurablClient(api_key=...) deb uzating "
                f"yoki {ENV_API_KEY} muhit o'zgaruvchisini o'rnating."
            )
        return self.api_key

    @property
    def api_url(self) -> str:
        """API ildizi, masalan `https://api.durabl.dev/api/v1`."""
        return f"{self.base_url}{self.api_prefix}"

    def path(self, *parts: Any) -> str:
        """API yo'lini yasaydi: `path("jobs", job_id)` -> `/api/v1/jobs/<id>`."""
        segments = [str(part).strip("/") for part in parts if str(part).strip("/")]
        return "/".join([self.api_prefix, *segments]) if segments else self.api_prefix or "/"

    def headers(self) -> dict[str, str]:
        """Har bir so'rovda yuboriladigan standart sarlavhalar."""
        result = {
            HEADER_API_KEY: self.require_api_key(),
            "Accept": "application/json",
            "User-Agent": self.user_agent,
        }
        result.update(self.extra_headers)
        return result

    def masked_api_key(self) -> str:
        """Kalitni loglarda ko'rsatish uchun yashiradi: `durabl_...a1b2`."""
        if not self.api_key:
            return "<yo'q>"
        if len(self.api_key) <= 10:
            return "***"
        return f"{self.api_key[:7]}...{self.api_key[-4:]}"

    def __repr__(self) -> str:
        return (
            f"DurablConfig(base_url={self.base_url!r}, api_key={self.masked_api_key()!r}, "
            f"timeout={self.timeout!r}, max_retries={self.max_retries!r})"
        )


def _env_float(name: str, default: float) -> float:
    """Muhitdan `float` o'qiydi; noto'g'ri qiymatda standartni qaytaradi."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    """Muhitdan `int` o'qiydi; noto'g'ri qiymatda standartni qaytaradi."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        return default


__all__ = [
    "DEFAULT_API_PREFIX",
    "DEFAULT_BASE_URL",
    "DEFAULT_MAX_RETRIES",
    "DEFAULT_RETRY_BACKOFF",
    "DEFAULT_RETRY_MAX_DELAY",
    "DEFAULT_TIMEOUT",
    "ENV_API_KEY",
    "ENV_BASE_URL",
    "ENV_MAX_RETRIES",
    "ENV_RETRY_BACKOFF",
    "ENV_TIMEOUT",
    "HEADER_API_KEY",
    "HEADER_IDEMPOTENCY_KEY",
    "HEADER_REQUEST_ID",
    "DurablConfig",
]
