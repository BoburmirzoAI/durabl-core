"""Durabl — `app/execution/timeout_guard.py` birlik testlari.

`TimeoutGuard` oddiy `asyncio.timeout()` dan ikki jihati bilan farq qiladi:

1. **Tozalash imkoni.** Yumshoq muddat tugaganda avval `on_timeout()`
   (odatda `runner.kill()`) chaqiriladi, shundan keyin blok o'z yo'li bilan
   qaytadi va QISMIY loglar saqlanib qoladi. Oddiy bekor qilishda
   `runner.run()` ning `finally` bloki bekor qilish shovqini ichida ishlab,
   konteyner "orphan" bo'lib qolishi mumkin edi.
2. **Xatolar ustunligi.** Blok ichida BOSHQA xato bo'lsa, u ustun turadi —
   asl sabab (`SandboxStartupError`) diagnostika uchun qimmatliroq va
   `reliability_service` retry qarorini ayni shunga qarab qabul qiladi.

Testlarda vaqtlar ataylab kichik (0.02..0.5 s): to'plam tez ishlashi kerak,
lekin event loop'ga yetarli bo'shliq qoldiriladi.
"""

from __future__ import annotations

import asyncio

import pytest
from app.config import settings
from app.exceptions import ExecutionTimeoutError, SandboxStartupError
from app.execution.timeout_guard import TimeoutGuard, with_timeout

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Muvaffaqiyatli yo'l
# ---------------------------------------------------------------------------


async def test_vaqtida_tugasa_xato_yoq() -> None:
    """Blok muddatdan oldin tugasa hech narsa tashlanmaydi."""
    async with TimeoutGuard(1.0) as guard:
        await asyncio.sleep(0.01)
    assert guard.triggered is False


async def test_vaqtida_tugasa_on_timeout_chaqirilmaydi() -> None:
    """Muddat tugamagan bo'lsa tozalash funksiyasi chaqirilmaydi."""
    calls: list[str] = []

    async def killer() -> None:
        calls.append("kill")

    async with TimeoutGuard(1.0, on_timeout=killer):
        await asyncio.sleep(0.01)

    assert calls == []


async def test_blok_qaytargan_qiymat_saqlanadi() -> None:
    """Kontekst natijani yutmaydi — blok ichidagi qiymat ishlatilishi mumkin."""
    async with TimeoutGuard(1.0):
        value = sum(range(10))
    assert value == 45


# ---------------------------------------------------------------------------
# Yumshoq muddat
# ---------------------------------------------------------------------------


async def test_muddat_oshsa_xato_tashlanadi() -> None:
    """Yumshoq muddat oshsa blokdan chiqishda `ExecutionTimeoutError`."""
    with pytest.raises(ExecutionTimeoutError):
        async with TimeoutGuard(0.02, grace_seconds=1.0):
            await asyncio.sleep(0.15)


async def test_muddat_oshsa_on_timeout_chaqiriladi() -> None:
    """Tozalash funksiyasi AYNAN bir marta chaqiriladi."""
    calls: list[str] = []

    async def killer() -> None:
        calls.append("kill")

    with pytest.raises(ExecutionTimeoutError):
        async with TimeoutGuard(0.02, on_timeout=killer, grace_seconds=1.0):
            await asyncio.sleep(0.15)

    assert calls == ["kill"]


async def test_triggered_bayrogi_qoyiladi() -> None:
    """Muddat ishga tushgani `triggered` orqali ko'rinadi."""
    guard = TimeoutGuard(0.02, grace_seconds=1.0)
    with pytest.raises(ExecutionTimeoutError):
        async with guard:
            await asyncio.sleep(0.15)
    assert guard.triggered is True


async def test_xato_tanasida_timeout_qiymati() -> None:
    """Xato obyekti qaysi muddat oshganini saqlaydi (log va DLQ uchun)."""
    with pytest.raises(ExecutionTimeoutError) as info:
        async with TimeoutGuard(0.02, grace_seconds=1.0):
            await asyncio.sleep(0.15)
    assert "0.02" in str(info.value) or "0.02" in repr(info.value.details)


async def test_on_timeout_xatosi_yutiladi() -> None:
    """Tozalash funksiyasi yiqilsa ham timeout xatosi normal chiqadi."""

    async def failing_killer() -> None:
        raise RuntimeError("Docker demoni javob bermadi")

    with pytest.raises(ExecutionTimeoutError):
        async with TimeoutGuard(0.02, on_timeout=failing_killer, grace_seconds=1.0):
            await asyncio.sleep(0.15)


# ---------------------------------------------------------------------------
# Qattiq muddat (grace)
# ---------------------------------------------------------------------------


async def test_qattiq_muddat_blokni_bekor_qiladi() -> None:
    """`on_timeout` yordam bermasa blok majburan to'xtatiladi."""
    reached_end = False

    async def noop_killer() -> None:
        return None  # jarayonni o'ldirmaydi — qattiq muddat ishlashi kerak

    with pytest.raises(ExecutionTimeoutError):
        async with TimeoutGuard(0.02, on_timeout=noop_killer, grace_seconds=0.05):
            await asyncio.sleep(5.0)
            reached_end = True  # pragma: no cover - bu yergacha yetib kelmaydi

    assert reached_end is False


async def test_grace_sozlamadan_olinadi() -> None:
    """`grace_seconds` berilmasa sozlamadagi qiymat ishlatiladi."""
    guard = TimeoutGuard(1.0)
    assert guard.grace_seconds == settings.SANDBOX_KILL_GRACE_SECONDS


async def test_qattiq_muddat_cancelled_errorga_aylanmaydi() -> None:
    """Bekor qilish `CancelledError` emas, DOMEN xatosi bo'lib chiqadi.

    `asyncio.timeout()` blokni `CancelledError` bilan to'xtatadi; agar
    `TimeoutGuard` uni domen xatosiga aylantirmasa, chaqiruvchi (worker)
    "job bekor qilindi" deb o'ylab job'ni DLQ'ga yubormasdan qoldirardi.
    """
    with pytest.raises(ExecutionTimeoutError) as info:
        async with TimeoutGuard(0.02, grace_seconds=0.03):
            await asyncio.sleep(5.0)

    assert not isinstance(info.value, asyncio.CancelledError)


# ---------------------------------------------------------------------------
# Xatolar ustunligi
# ---------------------------------------------------------------------------


async def test_blok_ichidagi_xato_ustun_turadi() -> None:
    """Blok ichidagi asl xato `ExecutionTimeoutError` bilan o'ralmaydi."""
    with pytest.raises(SandboxStartupError):
        async with TimeoutGuard(1.0):
            raise SandboxStartupError("Konteyner ishga tushmadi")


async def test_timeout_boshlangandan_keyingi_xato_ham_ustun() -> None:
    """Muddat ishga tushgan bo'lsa ham asl xato ustun turadi."""
    guard = TimeoutGuard(0.02, grace_seconds=1.0)
    with pytest.raises(ValueError, match="asl sabab"):
        async with guard:
            await asyncio.sleep(0.1)
            raise ValueError("asl sabab")
    assert guard.triggered is True  # muddat ishga tushgan, lekin xato ustun


async def test_kontekst_xatoni_yutmaydi() -> None:
    """`__aexit__` har doim `False` qaytaradi — xato tashqariga chiqadi."""
    with pytest.raises(ZeroDivisionError):
        async with TimeoutGuard(1.0):
            _ = 1 / 0


# ---------------------------------------------------------------------------
# Xossalar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("given", "expected"), [(5.0, 5.0), (0, 0.0), (-3.0, 0.0)])
async def test_seconds_manfiy_qiymat_nolga_keltiriladi(given: float, expected: float) -> None:
    """Manfiy muddat `0.0` ga keltiriladi."""
    assert TimeoutGuard(given).seconds == expected


async def test_elapsed_seconds_blokdan_keyin_muzlatiladi() -> None:
    """Chiqilgandan keyin `elapsed_seconds` o'smaydi (o'lchov yakunlangan)."""
    async with TimeoutGuard(1.0) as guard:
        await asyncio.sleep(0.02)
    first = guard.elapsed_seconds
    await asyncio.sleep(0.02)
    assert guard.elapsed_seconds == first
    assert first >= 0.02


async def test_elapsed_seconds_kirishdan_oldin_nol() -> None:
    """Blok boshlanmagan bo'lsa o'tgan vaqt `0.0`."""
    assert TimeoutGuard(1.0).elapsed_seconds == 0.0


async def test_remaining_seconds_kamayadi() -> None:
    """Blok ichida qolgan vaqt kamayib boradi va manfiy bo'lmaydi."""
    async with TimeoutGuard(0.5) as guard:
        first = guard.remaining_seconds
        await asyncio.sleep(0.05)
        assert guard.remaining_seconds < first
        assert guard.remaining_seconds >= 0.0


async def test_remaining_seconds_muddat_otgandan_keyin_nol() -> None:
    """Muddat o'tgandan keyin qoldiq aynan `0.0`."""
    guard = TimeoutGuard(0.02, grace_seconds=1.0)
    with pytest.raises(ExecutionTimeoutError):
        async with guard:
            await asyncio.sleep(0.1)
    assert guard.remaining_seconds == 0.0


# ---------------------------------------------------------------------------
# Qayta ishlatish
# ---------------------------------------------------------------------------


async def test_qayta_ishlatish_taqiqlangan() -> None:
    """Bitta nusxa ikki marta ishlatilmaydi (holat aralashib ketardi)."""
    guard = TimeoutGuard(1.0)
    async with guard:
        assert guard.triggered is False

    with pytest.raises(RuntimeError, match="qayta ishlatilmaydi"):
        async with guard:
            pytest.fail("ikkinchi kirish amalga oshmasligi kerak")


# ---------------------------------------------------------------------------
# with_timeout yordamchisi
# ---------------------------------------------------------------------------


async def test_with_timeout_natijani_qaytaradi() -> None:
    """Korutina vaqtida tugasa qaytargan qiymat uzatiladi."""

    async def work() -> str:
        await asyncio.sleep(0.01)
        return "tayyor"

    assert await with_timeout(work(), 1.0) == "tayyor"


async def test_with_timeout_muddat_oshsa_xato() -> None:
    """Muddat oshsa `ExecutionTimeoutError` tashlanadi."""
    with pytest.raises(ExecutionTimeoutError):
        await with_timeout(asyncio.sleep(5.0), 0.02, grace_seconds=0.05)


async def test_with_timeout_on_timeout_chaqiradi() -> None:
    """Tozalash funksiyasi yordamchi orqali ham ishlaydi."""
    calls: list[str] = []

    async def killer() -> None:
        calls.append("kill")

    with pytest.raises(ExecutionTimeoutError):
        await with_timeout(asyncio.sleep(5.0), 0.02, killer, grace_seconds=0.05)

    assert calls == ["kill"]


async def test_with_timeout_blok_xatosini_ochiq_qoldiradi() -> None:
    """Korutinaning o'z xatosi o'ralmaydi."""

    async def failing() -> None:
        raise SandboxStartupError("ishga tushmadi")

    with pytest.raises(SandboxStartupError):
        await with_timeout(failing(), 1.0)
