"""Durabl — vaqt bilan ishlash yordamchilari.

Qoida: loyihada FAQAT timezone-aware UTC vaqt ishlatiladi. `datetime.utcnow()`
(naive) hech qayerda chaqirilmaydi — `utcnow()` shu moduldan olinadi.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utcnow() -> datetime:
    """Hozirgi vaqt — timezone-aware UTC."""
    return datetime.now(UTC)


def utc_timestamp() -> float:
    """Hozirgi vaqt unix timestamp (float, soniyalarda)."""
    return utcnow().timestamp()


def ensure_utc(value: datetime | None) -> datetime | None:
    """Naive datetime'ni UTC deb belgilaydi, aware bo'lsa UTC'ga o'tkazadi.

    SQLite naive datetime qaytaradi — DB'dan o'qilgan qiymatlarni shu funksiya
    orqali normallashtiriladi.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_timestamp(value: datetime) -> float:
    """datetime -> unix timestamp (UTC kafolatlangan)."""
    aware = ensure_utc(value)
    assert aware is not None  # ensure_utc faqat None uchun None qaytaradi
    return aware.timestamp()


def from_timestamp(value: float) -> datetime:
    """unix timestamp -> timezone-aware UTC datetime."""
    return datetime.fromtimestamp(value, tz=UTC)


def seconds_from_now(seconds: float) -> datetime:
    """Hozirdan N soniya keyingi vaqt."""
    return utcnow() + timedelta(seconds=seconds)


def seconds_until(value: datetime | None) -> float:
    """Berilgan vaqtgacha qancha soniya qoldi (o'tgan bo'lsa manfiy)."""
    if value is None:
        return 0.0
    aware = ensure_utc(value)
    assert aware is not None
    return (aware - utcnow()).total_seconds()


def is_expired(value: datetime | None) -> bool:
    """Berilgan muddat o'tganmi? `None` — muddat yo'q, ya'ni tugamagan."""
    if value is None:
        return False
    return seconds_until(value) <= 0


def duration_ms(start: datetime, end: datetime | None = None) -> int:
    """Ikki vaqt orasidagi davomiylik — millisekundda (butun son)."""
    finish = end or utcnow()
    start_aware = ensure_utc(start)
    finish_aware = ensure_utc(finish)
    assert start_aware is not None and finish_aware is not None
    return max(0, int((finish_aware - start_aware).total_seconds() * 1000))


def humanize_duration(milliseconds: int | float | None) -> str:
    """Millisekundni o'qishli matnga: `1.2s`, `3m 4s`, `2h 10m`."""
    if milliseconds is None:
        return "-"
    total_seconds = float(milliseconds) / 1000.0
    if total_seconds < 1:
        return f"{int(milliseconds)}ms"
    if total_seconds < 60:
        return f"{total_seconds:.1f}s"
    minutes, seconds = divmod(int(total_seconds), 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m"


def start_of_day(value: datetime | None = None) -> datetime:
    """Kunning boshlanishi (UTC 00:00:00)."""
    base = ensure_utc(value) or utcnow()
    return base.replace(hour=0, minute=0, second=0, microsecond=0)


def start_of_month(value: datetime | None = None) -> datetime:
    """Oyning birinchi kuni 00:00:00 UTC — billing hisobi uchun."""
    return start_of_day(value).replace(day=1)


def next_month(value: datetime | None = None) -> datetime:
    """Keyingi oyning birinchi kuni — obuna muddati uchun."""
    current = start_of_month(value)
    if current.month == 12:
        return current.replace(year=current.year + 1, month=1)
    return current.replace(month=current.month + 1)


def day_key(value: datetime | None = None) -> str:
    """Rate limit kaliti uchun kun: `2026-10-04`."""
    return (ensure_utc(value) or utcnow()).strftime("%Y-%m-%d")


def minute_key(value: datetime | None = None) -> str:
    """Rate limit kaliti uchun daqiqa: `2026-10-04T15:42`."""
    return (ensure_utc(value) or utcnow()).strftime("%Y-%m-%dT%H:%M")


def month_key(value: datetime | None = None) -> str:
    """Billing kaliti uchun oy: `2026-10`."""
    return (ensure_utc(value) or utcnow()).strftime("%Y-%m")


def isoformat(value: datetime | None) -> str | None:
    """ISO-8601 matn (UTC, `Z` bilan) — API javoblari uchun."""
    aware = ensure_utc(value)
    if aware is None:
        return None
    return aware.isoformat().replace("+00:00", "Z")


__all__ = [
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
]
