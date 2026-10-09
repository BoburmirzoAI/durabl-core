"""Durabl — `app.utils` paketi: barcha yordamchilarni bitta joydan beradi.

```python
from app.utils import utcnow, hash_password, validate_cron, dump_json
```

**Nega dangasa (lazy) import.** Nomlar paket yuklanganda emas, balki ularga
birinchi murojaat paytida `__getattr__` (PEP 562) orqali keltiriladi.
Buning ikki sababi bor:

1. `app.utils.pagination` FastAPI va `app.schemas`ni tortib keladi. Agar
   paket import qilinishida hammasi birdan yuklansa, `app.models.base`
   ichidagi oddiy `from app.utils.time_utils import utcnow` ham butun
   FastAPI'ni ko'tarib kelardi — worker protsesslari behuda og'irlashadi.
2. Aylanma import (circular import) xavfi yo'qoladi: `app.schemas.job`
   `app.utils.validators`ni import qilsa ham, `app.utils` paketi
   `app.schemas`ni kutib qolmaydi.

Shunga qaramay nomlarning hammasi re-export qilinadi: `from app.utils import X`
ishlaydi, `dir(app.utils)` to'liq ro'yxatni ko'rsatadi. Aniq qatlamlarda
to'g'ridan-to'g'ri submodulni import qilish ham (`from app.utils.security
import hash_password`) afzal ko'riladi — o'qishga tushunarliroq.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

#: Submodul -> shu submodul beradigan ommaviy nomlar.
#: Manba: har bir submodulning o'z `__all__` ro'yxati.
_MODULE_EXPORTS: dict[str, tuple[str, ...]] = {
    "pagination": (
        "apply_sorting",
        "build_cursor_page",
        "decode_cursor",
        "encode_cursor",
        "paginate",
        "pagination_params",
    ),
    "retry_policy": (
        "NON_RETRYABLE_REASONS",
        "RetryPolicy",
        "compute_backoff",
        "webhook_policy",
    ),
    "security": (
        "API_KEY_DISPLAY_PREFIX_LENGTH",
        "GeneratedApiKey",
        "TokenType",
        "constant_time_compare",
        "create_access_token",
        "create_refresh_token",
        "create_token",
        "decode_token",
        "generate_api_key",
        "generate_correlation_id",
        "generate_token",
        "generate_webhook_secret",
        "hash_api_key",
        "hash_password",
        "is_api_key_format",
        "mask_api_key",
        "sign_webhook",
        "token_subject",
        "validate_password_strength",
        "verify_password",
        "verify_webhook_signature",
    ),
    "serializers": (
        "DurablJSONEncoder",
        "FINGERPRINT_LENGTH",
        "MAX_EVENT_ERROR_CHARS",
        "deserialize_payload",
        "dump_json",
        "fingerprint",
        "job_event_payload",
        "job_result_payload",
        "json_default",
        "load_json",
        "serialize_payload",
        "truncate",
        "truncate_bytes",
        "truncate_output",
    ),
    "time_utils": (
        "day_key",
        "duration_ms",
        "ensure_utc",
        "from_timestamp",
        "humanize_duration",
        "is_expired",
        "isoformat",
        "minute_key",
        "month_key",
        "next_month",
        "seconds_from_now",
        "seconds_until",
        "start_of_day",
        "start_of_month",
        "to_timestamp",
        "utc_timestamp",
        "utcnow",
    ),
    "validators": (
        "BLOCKED_HOSTNAMES",
        "BLOCKED_HOST_SUFFIXES",
        "CRON_ALIASES",
        "CodeInspection",
        "FORBIDDEN_ENV_NAMES",
        "FORBIDDEN_ENV_PREFIXES",
        "MAX_CRON_LENGTH",
        "MAX_ENV_VALUE_LENGTH",
        "MAX_ENV_VARS",
        "MAX_TAGS",
        "MAX_TAG_LENGTH",
        "MAX_WEBHOOK_URL_LENGTH",
        "PYTHON_FORBIDDEN_ATTRIBUTE_CALLS",
        "PYTHON_FORBIDDEN_CALLS",
        "WRITE_FILE_MODE_CHARS",
        "assert_code_safe",
        "inspect_code",
        "next_cron_time",
        "validate_code",
        "validate_code_size",
        "validate_cron",
        "validate_env_vars",
        "validate_payload_size",
        "validate_retries",
        "validate_runtime",
        "validate_tags",
        "validate_timeout",
        "validate_webhook_url",
        "validate_webhook_url_async",
    ),
}

#: Nom -> qaysi submoduldan olinadi (tekis ko'rinish, `__getattr__` uchun).
_EXPORTS: dict[str, str] = {
    name: module for module, names in _MODULE_EXPORTS.items() for name in names
}

# DIQQAT: nomlar dangasa yuklanganligi uchun statik tahlilchilar (mypy, IDE)
# `from app.utils import utcnow` ko'rinishini "aniqlanmagan" deb belgilashi
# mumkin. Aniq qatlamlarda submodulni to'g'ridan-to'g'ri import qilish afzal:
#     from app.utils.time_utils import utcnow
# Paket darajasidagi import esa tezkor ish va skriptlar uchun qulaylik.


def __getattr__(name: str) -> Any:
    """Nomni kerakli submoduldan dangasa yuklaydi (PEP 562)."""
    module_name = _EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"'app.utils' paketida '{name}' nomi mavjud emas")
    value = getattr(import_module(f"{__name__}.{module_name}"), name)
    globals()[name] = value  # keyingi murojaatlar uchun keshlab qo'yamiz
    return value


def __dir__() -> list[str]:
    """`dir(app.utils)` to'liq ro'yxatni ko'rsatadi."""
    return sorted(set(_EXPORTS) | set(globals()))


__all__ = sorted(_EXPORTS)
