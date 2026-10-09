"""Durabl — `app/utils/time_utils.py` birlik testlari.

Nega bu modul alohida va sinchkov tekshiriladi: loyihada vaqt bilan ishlashning
YAGONA yo'li shu fayl (`datetime.utcnow()` taqiqlangan). Agar `ensure_utc()`
naive qiymatni xato belgilasa, SQLite'dan o'qilgan `expires_at` bir necha soat
siljib ketadi va API kalitlar muddatidan oldin "tugagan" bo'lib qoladi.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from app.utils.time_utils import (
    day_key,
    duration_ms,
    ensure_utc,
    from_timestamp,
    humanize_duration,
    is_expired,
    isoformat,
    minute_key,
    month_key,
    next_month,
    seconds_from_now,
    seconds_until,
    start_of_day,
    start_of_month,
    to_timestamp,
    utc_timestamp,
    utcnow,
)

pytestmark = pytest.mark.unit

#: Tekshiruvlarda ishlatiladigan qat'iy lahza (UTC).
SAMPLE = datetime(2026, 10, 4, 12, 30, 45, 123_000, tzinfo=UTC)


# ---------------------------------------------------------------------------
# utcnow / utc_timestamp
# ---------------------------------------------------------------------------


def test_utcnow_timezone_aware_va_utc() -> None:
    """`utcnow()` har doim timezone-aware UTC qaytaradi."""
    now = utcnow()
    assert now.tzinfo is not None
    assert now.utcoffset() == timedelta(0)


def test_utc_timestamp_utcnow_bilan_mos() -> None:
    """`utc_timestamp()` — `utcnow()` ning unix ko'rinishi (bir soniya ichida)."""
    assert abs(utc_timestamp() - utcnow().timestamp()) < 1.0


def test_utcnow_monoton_oshadi() -> None:
    """Ketma-ket chaqiruvlar orqaga qaytmaydi."""
    first = utcnow()
    second = utcnow()
    assert second >= first


# ---------------------------------------------------------------------------
# ensure_utc
# ---------------------------------------------------------------------------


def test_ensure_utc_naive_qiymatni_utc_deb_belgilaydi() -> None:
    """Naive datetime (SQLite'dan kelgan) UTC deb belgilanadi, siljimaydi."""
    naive = datetime(2026, 10, 4, 12, 0, 0)
    result = ensure_utc(naive)
    assert result is not None
    assert result.tzinfo is UTC
    assert result.hour == 12  # vaqt o'zgarmadi, faqat zona qo'shildi


def test_ensure_utc_boshqa_zonani_utcga_otkazadi() -> None:
    """Aware qiymat UTC'ga KONVERTATSIYA qilinadi (soat siljiydi)."""
    tashkent = timezone(timedelta(hours=5))
    result = ensure_utc(datetime(2026, 10, 4, 17, 0, 0, tzinfo=tashkent))
    assert result is not None
    assert result.hour == 12
    assert result.utcoffset() == timedelta(0)


def test_ensure_utc_none_uchun_none() -> None:
    """`None` kirsa `None` chiqadi (ixtiyoriy ustunlar uchun)."""
    assert ensure_utc(None) is None


# ---------------------------------------------------------------------------
# timestamp konvertatsiyasi
# ---------------------------------------------------------------------------


def test_to_timestamp_va_from_timestamp_aylanma() -> None:
    """`to_timestamp` -> `from_timestamp` asl qiymatni tiklaydi."""
    restored = from_timestamp(to_timestamp(SAMPLE))
    assert restored == SAMPLE
    assert restored.tzinfo is UTC


def test_to_timestamp_naive_qiymatni_utc_deb_oladi() -> None:
    """Naive qiymat lokal zona emas, UTC deb hisoblanadi."""
    naive = SAMPLE.replace(tzinfo=None)
    assert to_timestamp(naive) == to_timestamp(SAMPLE)


# ---------------------------------------------------------------------------
# seconds_from_now / seconds_until / is_expired
# ---------------------------------------------------------------------------


def test_seconds_from_now_kelajakdagi_vaqt() -> None:
    """`seconds_from_now(60)` taxminan bir daqiqa keyingi vaqtni beradi."""
    assert 59.0 <= seconds_until(seconds_from_now(60)) <= 60.0


def test_seconds_until_otgan_vaqt_manfiy() -> None:
    """O'tgan vaqt uchun qoldiq manfiy bo'ladi."""
    assert seconds_until(utcnow() - timedelta(seconds=30)) < 0


def test_seconds_until_none_nol() -> None:
    """Muddat yo'q bo'lsa `0.0`."""
    assert seconds_until(None) == 0.0


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, False),  # muddat yo'q — tugamagan
        (datetime(2000, 1, 1, tzinfo=UTC), True),
        (datetime(2999, 1, 1, tzinfo=UTC), False),
    ],
)
def test_is_expired(value: datetime | None, expected: bool) -> None:
    """`is_expired` — `None` tugamagan, o'tmish tugagan, kelajak tugamagan."""
    assert is_expired(value) is expected


def test_is_expired_naive_qiymat_bilan_ishlaydi() -> None:
    """Naive qiymat ham UTC deb olinadi — `TypeError` chiqmaydi."""
    assert is_expired(datetime(2000, 1, 1)) is True


# ---------------------------------------------------------------------------
# duration_ms
# ---------------------------------------------------------------------------


def test_duration_ms_aniq_qiymat() -> None:
    """Ikki lahza orasidagi masofa millisekundda."""
    start = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)
    assert duration_ms(start, start + timedelta(milliseconds=1500)) == 1500


def test_duration_ms_tartib_teskari_bolsa_nol() -> None:
    """Oxiri boshidan OLDIN bo'lsa natija manfiy emas, `0`."""
    start = datetime(2026, 10, 4, 12, 0, 10, tzinfo=UTC)
    assert duration_ms(start, start - timedelta(seconds=5)) == 0


def test_duration_ms_end_berilmasa_hozirgi_vaqt() -> None:
    """`end` berilmasa hozirgi vaqt olinadi."""
    assert duration_ms(utcnow() - timedelta(seconds=1)) >= 900


def test_duration_ms_naive_va_aware_aralash() -> None:
    """Naive va aware qiymatlar aralash kelsa ham hisob to'g'ri."""
    start = datetime(2026, 10, 4, 12, 0, 0)
    end = datetime(2026, 10, 4, 12, 0, 2, tzinfo=UTC)
    assert duration_ms(start, end) == 2000


# ---------------------------------------------------------------------------
# humanize_duration
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("milliseconds", "expected"),
    [
        (None, "-"),
        (0, "0ms"),
        (500, "500ms"),
        (999, "999ms"),
        (1000, "1.0s"),
        (1234, "1.2s"),
        (59_000, "59.0s"),
        (60_000, "1m 0s"),
        (184_000, "3m 4s"),
        (3_599_000, "59m 59s"),
        (3_600_000, "1h 0m"),
        (7_800_000, "2h 10m"),
    ],
)
def test_humanize_duration_barcha_diapazonlar(milliseconds: int | None, expected: str) -> None:
    """Har bir diapazon o'z formatida chiqadi (ms -> s -> m s -> h m)."""
    assert humanize_duration(milliseconds) == expected


def test_humanize_duration_float_qabul_qiladi() -> None:
    """Float kirish ham ishlaydi (`duration_ms` har doim int, lekin imzo ruxsat beradi)."""
    assert humanize_duration(1500.4) == "1.5s"


# ---------------------------------------------------------------------------
# Kun / oy chegaralari
# ---------------------------------------------------------------------------


def test_start_of_day_vaqtni_nollaydi() -> None:
    """Kun boshlanishi — 00:00:00.000 UTC."""
    result = start_of_day(SAMPLE)
    assert (result.hour, result.minute, result.second, result.microsecond) == (0, 0, 0, 0)
    assert result.date() == SAMPLE.date()


def test_start_of_month_birinchi_kun() -> None:
    """Oy boshlanishi — 1-kun 00:00:00 UTC."""
    result = start_of_month(SAMPLE)
    assert (result.year, result.month, result.day) == (2026, 10, 1)
    assert result.hour == 0


def test_next_month_oddiy_holat() -> None:
    """Oddiy oyda oy raqami bittaga oshadi."""
    assert next_month(SAMPLE) == datetime(2026, 11, 1, tzinfo=UTC)


def test_next_month_dekabrda_yil_oshadi() -> None:
    """Dekabrdan keyin yanvar — YIL ham oshishi SHART (billing uchun kritik)."""
    december = datetime(2026, 12, 31, 23, 59, 59, tzinfo=UTC)
    assert next_month(december) == datetime(2027, 1, 1, tzinfo=UTC)


def test_next_month_natijasi_har_doim_keyinroq() -> None:
    """Har bir oy uchun natija kirish qiymatidan keyin turadi."""
    for month in range(1, 13):
        base = datetime(2026, month, 15, tzinfo=UTC)
        assert next_month(base) > base


# ---------------------------------------------------------------------------
# Kalit shakllari
# ---------------------------------------------------------------------------


def test_day_key_shakli() -> None:
    """`day_key` — `YYYY-MM-DD`."""
    assert day_key(SAMPLE) == "2026-10-04"


def test_minute_key_shakli() -> None:
    """`minute_key` — rate limit oynasi uchun daqiqa aniqligida."""
    assert minute_key(SAMPLE) == "2026-10-04T12:30"


def test_month_key_shakli() -> None:
    """`month_key` — `usage_records.period` ustuni bilan AYNI shakl (7 belgi)."""
    key = month_key(SAMPLE)
    assert key == "2026-10"
    assert len(key) == 7


def test_kalitlar_argumentsiz_ham_ishlaydi() -> None:
    """Argumentsiz chaqiruv hozirgi vaqtni oladi va to'g'ri uzunlik beradi."""
    assert len(day_key()) == 10
    assert len(month_key()) == 7
    assert len(minute_key()) == 16


def test_kalitlar_naive_qiymatni_utc_deb_oladi() -> None:
    """Naive qiymat uchun ham kalit UTC bo'yicha hisoblanadi."""
    assert day_key(SAMPLE.replace(tzinfo=None)) == "2026-10-04"


# ---------------------------------------------------------------------------
# isoformat
# ---------------------------------------------------------------------------


def test_isoformat_z_bilan_tugaydi() -> None:
    """API javoblarida vaqt `+00:00` emas, `Z` bilan chiqadi."""
    result = isoformat(SAMPLE)
    assert result is not None
    assert result.endswith("Z")
    assert "+00:00" not in result


def test_isoformat_none_uchun_none() -> None:
    """`None` uchun `None` (ixtiyoriy maydonlar uchun)."""
    assert isoformat(None) is None


def test_isoformat_naive_qiymatni_utc_deb_belgilaydi() -> None:
    """Naive qiymat ham `Z` bilan chiqadi — mijoz zonani taxmin qilmaydi."""
    result = isoformat(SAMPLE.replace(tzinfo=None))
    assert result == "2026-10-04T12:30:45.123000Z"


# ---------------------------------------------------------------------------
# `frozen_time` fixture'i bilan
# ---------------------------------------------------------------------------


def test_frozen_time_utcnow_muzlatadi(frozen_time: object) -> None:
    """`frozen_time` fixture'i `utcnow()` ni ham muzlatadi."""
    first = utcnow()
    second = utcnow()
    assert first == second
    assert day_key() == "2026-10-04"
    assert month_key() == "2026-10"
