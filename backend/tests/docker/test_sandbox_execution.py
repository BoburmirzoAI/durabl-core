"""Durabl — sandbox bajarish yo'li (HAQIQIY konteyner bilan).

Bu fayl `executor.execute()` ning to'liq zanjirini tekshiradi:
kod yozish -> konteyner -> chiqish oqimi -> `result.json` -> `ExecutionResult`.

Mock YO'Q. Shuning uchun aynan shu yerda `tests/unit/test_sandbox_manager.py`
topa olmaydigan narsalar ushlanadi: entrypoint shartnomasi, log oqimining
ulanishi, resurs limitlarining haqiqatan qo'llanishi.
"""

from __future__ import annotations

import asyncio

import pytest
from app.constants import ExecutionStatus, FailureReason, Runtime
from app.execution.executor import Executor
from app.execution.sandbox_manager import SandboxManager
from app.execution.types import ResourceLimits

from tests.docker.conftest import make_spec

# ---------------------------------------------------------------------------
# Asosiy oqim — natija va chiqish
# ---------------------------------------------------------------------------

ECHO_CODE = """
def main():
    print("hello from stdout")
    return {"answer": 42}
"""


async def test_payload_bilan_natija_va_stdout_qaytadi(
    executor: Executor, limits: ResourceLimits
) -> None:
    """Kirish funksiyasi chaqiriladi, natija VA chiqish ikkalasi ham keladi.

    ENG MUHIM TEST. Aynan shu tekshiruv yo'qligi sababli "natija bazaga
    yozilmayapti" degan noto'g'ri tashxis qo'yilgan edi — aslida sabab
    payload'ning yo'qligi edi, saqlash qatlami emas.
    """
    result = await executor.execute(
        make_spec(ECHO_CODE, limits=limits, payload={"args": [], "kwargs": {}})
    )

    assert result.status is ExecutionStatus.SUCCESS
    assert result.exit_code == 0
    assert result.failure_reason is None
    assert result.result == {"answer": 42}
    assert "hello from stdout" in result.stdout
    assert result.sandbox_id


async def test_payloadsiz_kirish_funksiyasi_chaqirilmaydi(
    executor: Executor, limits: ResourceLimits
) -> None:
    """Payload berilmasa `main()` CHAQIRILMAYDI — bu hujjatlashtirilgan shartnoma.

    `docs/API.md` jadvalida ochiq yozilgan:
        "payload umuman yuborilmadi -> Funksiya chaqirilmaydi, result null"

    Test shu xatti-harakatni QULFLAB qo'yadi. Agar kimdir buni "xato" deb
    o'ylab o'zgartirsa, test yiqiladi va avval hujjat yangilanishi kerak
    bo'ladi — chunki o'zgarish mijozlarning kodiga ta'sir qiladi.
    """
    result = await executor.execute(make_spec(ECHO_CODE, limits=limits, payload=None))

    assert result.status is ExecutionStatus.SUCCESS
    assert result.exit_code == 0
    assert result.result is None
    assert result.stdout == ""


async def test_payload_argumentlari_uzatiladi(executor: Executor, limits: ResourceLimits) -> None:
    """`args` va `kwargs` kirish funksiyasiga to'g'ri yetib boradi."""
    code = """
def main(a, b, *, label):
    return {"sum": a + b, "label": label}
"""
    result = await executor.execute(
        make_spec(code, limits=limits, payload={"args": [2, 3], "kwargs": {"label": "ok"}})
    )

    assert result.status is ExecutionStatus.SUCCESS
    assert result.result == {"sum": 5, "label": "ok"}


# ---------------------------------------------------------------------------
# Chiqish oqimining ISHONCHLILIGI
# ---------------------------------------------------------------------------


@pytest.mark.slow
async def test_stdout_parallel_ishda_ham_yoqolmaydi(limits: ResourceLimits) -> None:
    """Chiqish PARALLEL yuklamada ham har safar ushlanishi kerak.

    ## Nega bu test parallel

    Diagnostika paytida 72 ta job'dan 2 tasida (~2.8%) `stdout` butunlay
    yo'qolgani o'lchangan: natija to'g'ri saqlangan, chiqish esa bo'sh.
    Muhim tafsilot — HAR IKKALA yo'qolish ham bir vaqtda ko'p job
    yuborilgan paytda sodir bo'lgan. Ketma-ket 56 ta ishga tushirishda
    (12 ta yolg'iz + 20 + 24) bir marta ham takrorlanmagan.

    Shuning uchun test ataylab PARALLEL: taxmin qilinayotgan sabab —
    konteyner chiqishiga ULANISH (`sandbox_manager._open_log_stream`)
    bilan uning tugashi orasidagi poyga, va u faqat thread havzasi band
    bo'lganda yuzaga keladi.

    ## Har bir ishga tushirish O'Z menejerini oladi

    `SandboxManager` holatni o'zida saqlaydi (`self._container`), ya'ni
    bitta nusxa bir vaqtda ikkita job bajara olmaydi. Worker havzasi ham
    har bir slot uchun alohida nusxa yasaydi — test shu shaklni
    takrorlaydi.

    ## Agar yiqilsa

    Bu "beqaror test" EMAS. Yiqilish — haqiqiy nuqsonning dalili:
    `status=success`, natija joyida, chiqish esa yo'qolgan.
    """
    runs = 10

    async def one(index: int) -> tuple[int, str, bool]:
        manager = SandboxManager()
        try:
            result = await Executor(runner=manager).execute(
                make_spec(
                    ECHO_CODE,
                    limits=limits,
                    payload={"args": [], "kwargs": {}},
                    job_id=f"stdout-race-{index}",
                )
            )
            ok = result.status is ExecutionStatus.SUCCESS
            return index, result.stdout, ok
        finally:
            await manager.close()

    outcomes = await asyncio.gather(*(one(i) for i in range(runs)))

    failed = [i for i, _, ok in outcomes if not ok]
    assert not failed, f"bajarilmagan urinishlar: {failed}"

    empty = [i for i, out, _ in outcomes if "hello from stdout" not in out]
    assert not empty, (
        f"{len(empty)}/{runs} parallel urinishda stdout yo'qoldi (urinishlar: {empty}). "
        "Natija to'g'ri, chiqish esa yo'q — konteyner log oqimiga ulanish poygasi "
        "(sandbox_manager._execute -> _open_log_stream)."
    )


async def test_stderr_stdoutdan_ajratiladi(executor: Executor, limits: ResourceLimits) -> None:
    """Ikki oqim aralashmasligi kerak — xatoni tasniflash shunga tayanadi."""
    code = """
import sys

def main():
    print("bu stdout")
    print("bu stderr", file=sys.stderr)
    return None
"""
    result = await executor.execute(
        make_spec(code, limits=limits, payload={"args": [], "kwargs": {}})
    )

    assert result.status is ExecutionStatus.SUCCESS
    assert "bu stdout" in result.stdout
    assert "bu stderr" not in result.stdout
    assert "bu stderr" in result.stderr


async def test_loglar_qatorlarga_bolinadi(executor: Executor, limits: ResourceLimits) -> None:
    """`logs` ro'yxati `execution_logs` jadvaliga ko'chiriladi — bo'sh bo'lmasin."""
    code = """
def main():
    for i in range(3):
        print(f"qator {i}")
    return None
"""
    result = await executor.execute(
        make_spec(code, limits=limits, payload={"args": [], "kwargs": {}})
    )

    contents = [entry.content for entry in result.logs]
    assert "qator 0" in contents
    assert "qator 2" in contents


# ---------------------------------------------------------------------------
# Muvaffaqiyatsizlik turlari — DLQ tasnifi shularga tayanadi
# ---------------------------------------------------------------------------


async def test_kod_xatosi_non_zero_exit_beradi(executor: Executor, limits: ResourceLimits) -> None:
    """Mijoz kodidagi istisno `non_zero_exit` sifatida tasniflanadi."""
    code = """
def main():
    raise ValueError("ataylab yiqitildi")
"""
    result = await executor.execute(
        make_spec(code, limits=limits, payload={"args": [], "kwargs": {}})
    )

    assert result.status is ExecutionStatus.FAILED
    assert result.failure_reason is FailureReason.NON_ZERO_EXIT
    assert result.exit_code != 0
    assert "ataylab yiqitildi" in (result.error_message or "")
    assert result.traceback


@pytest.mark.slow
async def test_vaqt_chegarasi_timeout_beradi(executor: Executor) -> None:
    """Timeout `TIMEOUT` sababini berishi kerak, `non_zero_exit` emas.

    Farq muhim: `timeout` qayta urinishga arziydi (tashqi xizmat sekin
    bo'lgandir), kod xatosi esa arzimaydi.
    """
    code = """
import time

def main():
    time.sleep(30)
    return "yetib bo'lmaydi"
"""
    short = ResourceLimits(timeout_seconds=3, memory_mb=256, allow_network=False)
    result = await executor.execute(
        make_spec(code, limits=short, payload={"args": [], "kwargs": {}})
    )

    assert result.status is not ExecutionStatus.SUCCESS
    assert result.failure_reason is FailureReason.TIMEOUT


async def test_sintaksis_xatosi_ushlanadi(executor: Executor, limits: ResourceLimits) -> None:
    """Kompilyatsiya xatosi ham natija sifatida qaytadi, istisno tashlamaydi."""
    result = await executor.execute(
        make_spec("def main(:\n    pass\n", limits=limits, payload={"args": [], "kwargs": {}})
    )

    assert result.status is ExecutionStatus.FAILED
    assert result.exit_code != 0
    assert result.error_message


# ---------------------------------------------------------------------------
# Izolyatsiya — xavfsizlik va'dalari
# ---------------------------------------------------------------------------


async def test_tarmoq_yopiq(executor: Executor, limits: ResourceLimits) -> None:
    """Sandbox'dan tashqariga chiqib bo'lmasligi kerak.

    Bu Durabl'ning asosiy xavfsizlik va'dalaridan biri: mijoz kodi
    ichki xizmatlarga yeta olmaydi.
    """
    code = """
import socket

def main():
    socket.setdefaulttimeout(4)
    try:
        socket.create_connection(("1.1.1.1", 53), timeout=4)
    except OSError as exc:
        return {"blocked": True, "error": type(exc).__name__}
    return {"blocked": False}
"""
    result = await executor.execute(
        make_spec(code, limits=limits, payload={"args": [], "kwargs": {}})
    )

    assert result.status is ExecutionStatus.SUCCESS
    assert result.result is not None
    assert result.result.get("blocked") is True, (
        f"sandbox'dan tarmoqqa chiqib bo'ldi: {result.result}"
    )


async def test_root_fayl_tizimi_faqat_oqish_uchun(
    executor: Executor, limits: ResourceLimits
) -> None:
    """`/` ga yozib bo'lmasligi kerak — bajarish takrorlanadigan qolsin."""
    code = """
def main():
    try:
        with open("/ozgartirildi", "w") as handle:
            handle.write("x")
    except OSError as exc:
        return {"readonly": True, "error": type(exc).__name__}
    return {"readonly": False}
"""
    result = await executor.execute(
        make_spec(code, limits=limits, payload={"args": [], "kwargs": {}})
    )

    assert result.status is ExecutionStatus.SUCCESS
    assert result.result is not None
    assert result.result.get("readonly") is True


# ---------------------------------------------------------------------------
# Node runtime
# ---------------------------------------------------------------------------


async def test_node_runtime_natija_qaytaradi(executor: Executor, limits: ResourceLimits) -> None:
    """Node runner ham ayni shartnomaga bo'ysunadi."""
    code = """
export default async function main() {
  console.log("salom node");
  return { answer: 42 };
}
"""
    result = await executor.execute(
        make_spec(
            code,
            limits=limits,
            runtime=Runtime.NODE,
            payload={"args": [], "kwargs": {}},
        )
    )

    assert result.status is ExecutionStatus.SUCCESS
    assert result.result == {"answer": 42}
    assert "salom node" in result.stdout


async def test_node_payloadsiz_ham_chaqirmaydi(executor: Executor, limits: ResourceLimits) -> None:
    """Shartnoma ikkala runtime'da BIR XIL bo'lishi kerak."""
    code = """
export default async function main() {
  console.log("chaqirilmasligi kerak");
  return { answer: 42 };
}
"""
    result = await executor.execute(
        make_spec(code, limits=limits, runtime=Runtime.NODE, payload=None)
    )

    assert result.status is ExecutionStatus.SUCCESS
    assert result.result is None
    assert result.stdout == ""
