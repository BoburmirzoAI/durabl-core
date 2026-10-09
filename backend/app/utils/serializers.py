"""Durabl — JSON serializatsiya va hodisa (event) shakllari.

Nega alohida modul:

* Durabl'da JSON bir nechta chegaradan o'tadi — HTTP javobi, Redis Pub/Sub,
  webhook tanasi, sandbox ichidagi `payload.json`. Hamma joyda **bir xil**
  qoidalar ishlashi uchun yagona encoder (`DurablJSONEncoder`) ishlatiladi:
  UUID, `datetime`, `Enum`, `Decimal`, `set`, dataclass avtomatik aylanadi.
* `job_event_payload()` — WebSocket va webhook uchun YAGONA shakl. Frontend va
  SDK ayni shu maydonlarni kutadi, shuning uchun shakl faqat shu yerda o'zgaradi.
* Barcha vaqtlar ISO-8601 UTC (`...Z`) matn ko'rinishida chiqadi.

Muhim: `job_event_payload()` va `job_result_payload()` SQLAlchemy modeli bilan
ishlaydi, lekin FAQAT `getattr` orqali — `lazy="raise"` munosabatlarga (user,
executions...) tegmaydi, shu sababli async kontekstda `MissingGreenlet`
bermaydi.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from typing import Any, Final
from uuid import UUID

from app.config import settings
from app.exceptions import ValidationError
from app.utils.time_utils import isoformat

#: Hodisa payload'idagi `error` maydoni shu belgidan uzun bo'lsa kesiladi.
#: Sabab: webhook/WebSocket tanasi 1 MB stack trace bilan to'lib ketmasligi kerak
#: (to'liq matn baribir `GET /jobs/{id}` javobida mavjud).
MAX_EVENT_ERROR_CHARS: Final = 2_000

#: Idempotency barmoq izi (fingerprint) uzunligi — SHA-256 hex.
FINGERPRINT_LENGTH: Final = 64


# ---------------------------------------------------------------------------
# JSON encoder
# ---------------------------------------------------------------------------


def json_default(value: Any) -> Any:
    """Standart `json` qo'llab-quvvatlamaydigan turlarni JSON'ga mos qiymatga aylantiradi.

    Qo'llab-quvvatlanadi:
        `Enum` -> qiymati, `datetime` -> ISO-8601 `Z`, `date`/`time` -> ISO matn,
        `timedelta` -> soniya (float), `UUID` -> matn, `Decimal` -> float,
        `set`/`frozenset` -> ro'yxat, `bytes` -> base64 matn,
        dataclass -> lug'at, pydantic modeli -> `model_dump(mode="json")`,
        `to_dict()` metodi bor obyekt -> shu metod natijasi.

    Raises:
        TypeError: Tur tanilmadi (chaqiruvchi o'zi hal qilishi kerak).
    """
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return isoformat(value)
    if isinstance(value, date | time):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, set | frozenset):
        items = list(value)
        try:
            return sorted(items)
        except TypeError:
            # Turlari aralash to'plam — tartiblash imkonsiz, shundayligicha beriladi
            return items
    if isinstance(value, bytes | bytearray | memoryview):
        return base64.b64encode(bytes(value)).decode("ascii")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return model_dump(mode="json")
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return to_dict()
    raise TypeError(f"{type(value).__name__} turi JSON'ga aylantirilmaydi")


class DurablJSONEncoder(json.JSONEncoder):
    """Loyihaning yagona JSON encoder'i (`json_default` qoidalariga tayanadi)."""

    def default(self, o: Any) -> Any:
        """Noma'lum turni aylantiradi; qo'lidan kelmasa standart xatoni beradi."""
        try:
            return json_default(o)
        except TypeError:
            return super().default(o)


# ---------------------------------------------------------------------------
# Umumiy dump/load
# ---------------------------------------------------------------------------


def dump_json(value: Any, *, sort_keys: bool = False, indent: int | None = None) -> str:
    """Har qanday qiymatni JSON matnga aylantiradi.

    `ensure_ascii=False` — o'zbekcha matnlar o'qishli qoladi; ajratgichlar
    zich (`,`/`:`) — tarmoq va Redis uchun kichik hajm.

    Raises:
        ValidationError: Qiymat JSON'ga aylanmaydi (masalan aylanma havola).
    """
    try:
        return json.dumps(
            value,
            cls=DurablJSONEncoder,
            ensure_ascii=False,
            separators=(",", ":") if indent is None else None,
            sort_keys=sort_keys,
            indent=indent,
        )
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Qiymatni JSON'ga aylantirib bo'lmadi: {exc}") from exc


def load_json(raw: str | bytes | bytearray | None) -> Any:
    """JSON matnni Python qiymatiga aylantiradi. Bo'sh qiymat -> `None`.

    Raises:
        ValidationError: Matn yaroqli JSON emas.
    """
    if raw is None:
        return None
    if isinstance(raw, bytes | bytearray):
        try:
            raw = bytes(raw).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationError("JSON UTF-8 kodlashda emas") from exc
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"JSON yaroqsiz: {exc}") from exc


# ---------------------------------------------------------------------------
# Job payload'i
# ---------------------------------------------------------------------------


def serialize_payload(payload: Mapping[str, Any] | None) -> str:
    """Job argumentlarini (payload) sandbox'ga yoziladigan JSON matnga aylantiradi.

    `None` -> `"null"` (shu bilan `deserialize_payload` bilan simmetrik bo'ladi).
    """
    if payload is None:
        return "null"
    if not isinstance(payload, Mapping):
        raise ValidationError("Payload JSON obyekt (lug'at) bo'lishi kerak")
    return dump_json(dict(payload))


def deserialize_payload(raw: str | bytes | None) -> dict[str, Any] | None:
    """JSON matndan job payload'ini qaytaradi; bo'sh yoki `null` -> `None`.

    Raises:
        ValidationError: JSON yaroqsiz yoki obyekt (lug'at) emas.
    """
    decoded = load_json(raw)
    if decoded is None:
        return None
    if not isinstance(decoded, dict):
        raise ValidationError("Payload JSON obyekt (lug'at) bo'lishi kerak")
    return decoded


# ---------------------------------------------------------------------------
# Kesish (truncate)
# ---------------------------------------------------------------------------


def truncate(text: str | None, limit: int) -> tuple[str, bool]:
    """Matnni `limit` BELGIgacha kesadi.

    Returns:
        `(matn, kesildimi)` — ikkinchi qiymat `True` bo'lsa ma'lumot yo'qolgan.
    """
    if not text:
        return "", False
    if limit <= 0:
        return "", True
    if len(text) <= limit:
        return text, False
    return text[:limit], True


def truncate_bytes(text: str | None, limit: int) -> tuple[str, bool]:
    """Matnni `limit` BAYTgacha kesadi, UTF-8 belgisini yarmidan bo'lmaydi.

    Chegarada qolgan to'liqsiz bayt ketma-ketligi tashlab yuboriladi
    (`errors="ignore"`), shu tufayli natija har doim yaroqli UTF-8 matn.
    """
    if not text:
        return "", False
    if limit <= 0:
        return "", True
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    return encoded[:limit].decode("utf-8", errors="ignore"), True


def truncate_output(text: str | None) -> tuple[str, bool]:
    """stdout/stderr'ni `MAX_OUTPUT_BYTES` chegarasigacha kesadi (baytlar bo'yicha)."""
    return truncate_bytes(text, settings.MAX_OUTPUT_BYTES)


# ---------------------------------------------------------------------------
# Yordamchi o'qish funksiyalari (lazy="raise" munosabatlarga tegmaydi)
# ---------------------------------------------------------------------------


def _as_str(value: object) -> str | None:
    """Qiymatni matnga aylantiradi; `None` saqlanadi."""
    return None if value is None else str(value)


def _as_enum_value(value: object) -> str | None:
    """`Enum` bo'lsa qiymatini, aks holda matn ko'rinishini qaytaradi."""
    if value is None:
        return None
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _as_int(value: object) -> int | None:
    """Faqat son turlarini butun songa aylantiradi, boshqasi uchun `None`."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _as_iso(value: object) -> str | None:
    """`datetime` bo'lsa ISO-8601 UTC (`Z`) matn, aks holda `None`."""
    if isinstance(value, datetime):
        return isoformat(value)
    return None


# ---------------------------------------------------------------------------
# Job hodisasi — WebSocket va webhook uchun yagona shakl
# ---------------------------------------------------------------------------


def job_event_payload(job: Any) -> dict[str, Any]:
    """Job holati o'zgarganda tarqatiladigan yagona payload shakli.

    Ayni shu lug'at WebSocket xabari (`{type, data, timestamp}` ichidagi `data`)
    va webhook tanasi sifatida ishlatiladi — frontend bilan SDK bir xil
    maydonlarni ko'rishi uchun shakl FAQAT shu funksiyada o'zgaradi.

    Args:
        job: `Job` modeli (yoki ayni maydonlarga ega har qanday obyekt).
    """
    raw_error = _as_str(getattr(job, "error", None))
    return {
        "job_id": _as_str(getattr(job, "id", None)),
        "user_id": _as_str(getattr(job, "user_id", None)),
        "status": _as_enum_value(getattr(job, "status", None)),
        "runtime": _as_enum_value(getattr(job, "runtime", None)),
        "priority": _as_enum_value(getattr(job, "priority", None)),
        "created_at": _as_iso(getattr(job, "created_at", None)),
        "started_at": _as_iso(getattr(job, "started_at", None)),
        "finished_at": _as_iso(getattr(job, "finished_at", None)),
        "duration_ms": _as_int(getattr(job, "duration_ms", None)),
        "exit_code": _as_int(getattr(job, "exit_code", None)),
        "retry_count": _as_int(getattr(job, "retry_count", None)) or 0,
        "failure_reason": _as_enum_value(getattr(job, "failure_reason", None)),
        "error": truncate(raw_error, MAX_EVENT_ERROR_CHARS)[0] if raw_error else None,
        "correlation_id": _as_str(getattr(job, "correlation_id", None)),
    }


def job_result_payload(job: Any) -> dict[str, Any]:
    """Job natijasi — hodisa shakliga stdout/stderr/result qo'shiladi.

    `stdout`/`stderr` `MAX_OUTPUT_BYTES` bo'yicha kesiladi; kesilgani
    `stdout_truncated`/`stderr_truncated` bayroqlarida bildiriladi.
    """
    payload = job_event_payload(job)
    stdout, stdout_truncated = truncate_output(_as_str(getattr(job, "stdout", None)))
    stderr, stderr_truncated = truncate_output(_as_str(getattr(job, "stderr", None)))
    payload.update(
        {
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "result": getattr(job, "result", None),
            "exit_code": _as_int(getattr(job, "exit_code", None)),
        }
    )
    return payload


# ---------------------------------------------------------------------------
# Barmoq izi (idempotency)
# ---------------------------------------------------------------------------


def fingerprint(payload: Mapping[str, Any]) -> str:
    """So'rov tanasining barqaror SHA-256 barmoq izi (hex, 64 belgi).

    Kalitlar tartiblanadi, ajratgichlar zich — shu tufayli bir xil mazmunli
    lug'at (maydonlar tartibi boshqa bo'lsa ham) HAR DOIM bir xil natija
    beradi. `IdempotencyService` shu izni solishtirib, bir xil
    `Idempotency-Key` boshqa tana bilan kelganini aniqlaydi.
    """
    if not isinstance(payload, Mapping):
        raise ValidationError("Barmoq izi uchun lug'at kerak")
    canonical = dump_json(dict(payload), sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "FINGERPRINT_LENGTH",
    "MAX_EVENT_ERROR_CHARS",
    "DurablJSONEncoder",
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
]
