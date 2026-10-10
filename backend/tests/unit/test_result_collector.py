"""Durabl — `app/execution/result_collector.py` birlik testlari.

`ResultCollector` — worker xotirasining qo'riqchisi. Mijoz kodi
`while True: print("x")` yozsa, chiqish cheksiz oqib keladi; kollektor
`max_output_bytes` chegarasida kesib, keyingi bo'laklarni UMUMAN qabul
qilmaydi. Shu himoya buzilsa bitta job butun worker'ni OOM bilan o'ldiradi.

Ikkinchi mas'uliyat — XOM natijani (`RunnerOutcome`) `ExecutionStatus` +
`FailureReason` ga aylantirish. Tasniflash tartibi QAT'IY, shuning uchun har
bir tarmoq alohida tekshiriladi: `cancelled` > `timed_out` > `oom_killed` >
`infra_error` > chiqish limiti > muvaffaqiyat > tilga xos tasnif.
"""

from __future__ import annotations

import pytest
from app.config import settings
from app.constants import ExecutionStatus, FailureReason, LogStream
from app.execution.result_collector import (
    ERROR_TAIL_CHARS,
    TRUNCATION_NOTICE,
    ResultCollector,
)
from app.execution.runtime_python import PythonRuntime
from app.execution.types import RunnerOutcome, RunnerPayload

from tests.factories import make_limits

pytestmark = pytest.mark.unit

RUNTIME = PythonRuntime()


def _collector(**limit_overrides: object) -> ResultCollector:
    """Kichik chegaralar bilan kollektor yasaydi (kesishni tez sinash uchun)."""
    return ResultCollector(limits=make_limits(**limit_overrides))  # type: ignore[arg-type]


def _ok_outcome(*, result: object = None, exit_code: int | None = 0) -> RunnerOutcome:
    """Muvaffaqiyatli runner natijasi."""
    return RunnerOutcome(
        exit_code=exit_code,
        runner_payload=RunnerPayload(ok=True, exit_code=exit_code, result=result),
    )


# ---------------------------------------------------------------------------
# feed — qatorlarga bo'lish
# ---------------------------------------------------------------------------


def test_feed_qatorlarga_boladi() -> None:
    """Har bir to'liq qator alohida `LogEntry` bo'ladi."""
    collector = _collector()
    collector.feed(LogStream.STDOUT, "birinchi\nikkinchi\n")
    contents = [entry.content for entry in collector.logs]
    assert contents == ["birinchi", "ikkinchi"]


def test_feed_toliq_bolmagan_qator_buferda_qoladi() -> None:
    """Oxirgi tugallanmagan qator `flush()` gacha log'ga chiqmaydi."""
    collector = _collector()
    collector.feed(LogStream.STDOUT, "yarim")
    assert collector.logs == []
    collector.flush()
    assert [entry.content for entry in collector.logs] == ["yarim"]


def test_feed_bolaklar_birlashtiriladi() -> None:
    """Bir `print()` bir necha bo'lakda kelsa ham BITTA yozuv bo'ladi."""
    collector = _collector()
    collector.feed(LogStream.STDOUT, "sa")
    collector.feed(LogStream.STDOUT, "lom")
    collector.feed(LogStream.STDOUT, " dunyo\n")
    assert [entry.content for entry in collector.logs] == ["salom dunyo"]


def test_feed_bosh_qatorlar_yozuvga_aylanmaydi() -> None:
    """Bo'sh qator DB'ga yozilmaydi, lekin `stdout` matnida qoladi."""
    collector = _collector()
    collector.feed(LogStream.STDOUT, "a\n\n\nb\n")
    assert [entry.content for entry in collector.logs] == ["a", "b"]
    assert collector.stdout == "a\n\n\nb\n"


def test_feed_bosh_bolak_etiborsiz() -> None:
    """Bo'sh bo'lak hech narsa qilmaydi."""
    collector = _collector()
    collector.feed(LogStream.STDOUT, "")
    assert collector.logs == []
    assert collector.total_bytes == 0


def test_feed_crlf_tozalanadi() -> None:
    """Windows qator oxiri (`\\r\\n`) yozuvda `\\r` qoldirmaydi."""
    collector = _collector()
    collector.feed(LogStream.STDOUT, "satr\r\n")
    assert collector.logs[0].content == "satr"


# ---------------------------------------------------------------------------
# sequence
# ---------------------------------------------------------------------------


def test_sequence_ketma_ket_oshadi() -> None:
    """`sequence` 0'dan boshlab uzilishsiz oshadi."""
    collector = _collector()
    collector.feed(LogStream.STDOUT, "a\nb\nc\n")
    assert [entry.sequence for entry in collector.logs] == [0, 1, 2]
    assert collector.next_sequence == 3


def test_sequence_ikki_oqimda_umumiy() -> None:
    """stdout va stderr AYNI hisoblagichni baham ko'radi (tartib saqlanadi)."""
    collector = _collector()
    collector.feed(LogStream.STDOUT, "out\n")
    collector.feed(LogStream.STDERR, "err\n")
    assert [(entry.stream, entry.sequence) for entry in collector.logs] == [
        (LogStream.STDOUT, 0),
        (LogStream.STDERR, 1),
    ]


def test_start_sequence_davom_ettiriladi() -> None:
    """Qayta urinish bitta `execution` ichida davom etsa tartib buzilmaydi."""
    collector = ResultCollector(limits=make_limits(), start_sequence=10)
    collector.feed(LogStream.STDOUT, "a\n")
    assert collector.logs[0].sequence == 10


def test_start_sequence_manfiy_qiymat_nolga_keltiriladi() -> None:
    """Manfiy boshlang'ich qiymat `0` ga keltiriladi."""
    collector = ResultCollector(limits=make_limits(), start_sequence=-5)
    collector.feed(LogStream.STDOUT, "a\n")
    assert collector.logs[0].sequence == 0


# ---------------------------------------------------------------------------
# Uzun qatorni bo'laklash
# ---------------------------------------------------------------------------


def test_uzun_qator_bolaklarga_bolinadi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bitta juda uzun qator `MAX_LOG_CHUNK_BYTES` bo'laklariga bo'linadi."""
    monkeypatch.setattr(settings, "MAX_LOG_CHUNK_BYTES", 4)
    collector = _collector(max_output_bytes=1000)
    collector.feed(LogStream.STDOUT, "abcdefghij\n")
    contents = [entry.content for entry in collector.logs]
    assert contents == ["abcd", "efgh", "ij"]
    assert [entry.sequence for entry in collector.logs] == [0, 1, 2]


def test_bolaklash_utf8_belgisini_buzmaydi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bo'laklash ko'p baytli belgini yarmidan kesmaydi."""
    monkeypatch.setattr(settings, "MAX_LOG_CHUNK_BYTES", 3)
    collector = _collector(max_output_bytes=1000)
    collector.feed(LogStream.STDOUT, "ёёё\n")
    for entry in collector.logs:
        entry.content.encode("utf-8")  # yaroqli matn
    assert "".join(entry.content for entry in collector.logs) == "ёёё"


# ---------------------------------------------------------------------------
# Kesish (truncation)
# ---------------------------------------------------------------------------


def test_limit_oshganda_kesiladi() -> None:
    """Chegaradan oshgan chiqish kesiladi va `truncated` qo'yiladi."""
    collector = _collector(max_output_bytes=10)
    collector.feed(LogStream.STDOUT, "0123456789abcdef\n")
    assert collector.truncated is True
    assert collector.limit_reached is True
    assert collector.total_bytes == 10
    assert collector.stdout == "0123456789"


def test_limit_oshgandan_keyin_yangi_bolaklar_tashlanadi() -> None:
    """KRITIK: limit urilgandan keyin yangi bo'laklar UMUMAN yig'ilmaydi."""
    collector = _collector(max_output_bytes=5)
    collector.feed(LogStream.STDOUT, "12345678")
    before = collector.total_bytes
    collector.feed(LogStream.STDOUT, "yana ko'p matn" * 100)
    assert collector.total_bytes == before == 5


def test_limit_oshganda_tizim_xabari_qoshiladi() -> None:
    """Kesilganini log oqimida `SYSTEM` xabari bildiradi."""
    collector = _collector(max_output_bytes=5)
    collector.feed(LogStream.STDOUT, "0123456789")
    system_lines = [entry.content for entry in collector.logs if entry.stream is LogStream.SYSTEM]
    assert TRUNCATION_NOTICE in system_lines


def test_limit_xabari_bir_marta_yoziladi() -> None:
    """Xabar faqat BIR marta chiqadi (log spam bo'lmaydi)."""
    collector = _collector(max_output_bytes=5)
    for _ in range(5):
        collector.feed(LogStream.STDOUT, "0123456789")
    notices = [entry for entry in collector.logs if entry.content == TRUNCATION_NOTICE]
    assert len(notices) == 1


def test_chegarada_kesilmaydi() -> None:
    """Hajm aynan chegaraga teng bo'lsa kesish YO'Q."""
    collector = _collector(max_output_bytes=10)
    collector.feed(LogStream.STDOUT, "0123456789")
    assert collector.truncated is False
    assert collector.limit_reached is False


def test_ikki_oqim_umumiy_chegarani_bolishadi() -> None:
    """stdout va stderr BITTA umumiy chegaraga hisoblanadi."""
    collector = _collector(max_output_bytes=10)
    collector.feed(LogStream.STDOUT, "12345")
    collector.feed(LogStream.STDERR, "67890abc")
    assert collector.total_bytes == 10
    assert collector.truncated is True


# ---------------------------------------------------------------------------
# feed_system
# ---------------------------------------------------------------------------


def test_feed_system_chegaraga_hisoblanmaydi() -> None:
    """KRITIK: Durabl'ning o'z xabari mijoz chiqish hajmini yemaydi."""
    collector = _collector(max_output_bytes=10)
    collector.feed_system("Lease yo'qoldi — bajarish to'xtatildi")
    assert collector.total_bytes == 0
    assert collector.truncated is False
    assert collector.limit_reached is False


def test_feed_system_stdout_va_stderrga_tushmaydi() -> None:
    """Tizim xabari mijoz chiqishini ifloslantirmaydi."""
    collector = _collector()
    collector.feed_system("timeout")
    assert collector.stdout == ""
    assert collector.stderr == ""
    assert collector.logs[0].stream is LogStream.SYSTEM


def test_feed_system_bosh_xabar_etiborsiz() -> None:
    """Bo'sh xabar yozuv yasamaydi."""
    collector = _collector()
    collector.feed_system("")
    assert collector.logs == []


def test_feed_system_qator_oxirini_ozi_qoshadi() -> None:
    """`\\n` siz xabar ham to'liq yozuv bo'lib chiqadi (`flush` kutmaydi)."""
    collector = _collector()
    collector.feed_system("xabar")
    assert [entry.content for entry in collector.logs] == ["xabar"]


# ---------------------------------------------------------------------------
# build — tasniflash tarmoqlari
# ---------------------------------------------------------------------------


def test_build_success() -> None:
    """`ok=True` va `exit_code=0` -> SUCCESS, natija qaytariladi."""
    collector = _collector()
    collector.feed(LogStream.STDOUT, "salom\n")
    result = collector.build(_ok_outcome(result={"value": 7}), RUNTIME, duration_ms=120)

    assert result.status is ExecutionStatus.SUCCESS
    assert result.is_success is True
    assert result.failure_reason is None
    assert result.error_message is None
    assert result.result == {"value": 7}
    assert result.exit_code == 0
    assert result.duration_ms == 120
    assert result.stdout == "salom\n"
    assert len(result.logs) == 1


def test_build_cancelled_eng_ustun() -> None:
    """`cancelled=True` boshqa barcha belgilardan ustun turadi."""
    collector = _collector()
    outcome = RunnerOutcome(exit_code=1, timed_out=True, oom_killed=True)
    result = collector.build(outcome, RUNTIME, duration_ms=10, cancelled=True)

    assert result.status is ExecutionStatus.CANCELLED
    assert result.failure_reason is None
    assert result.error_message == "Bajarish bekor qilindi"


def test_build_timeout() -> None:
    """`timed_out` -> TIMEOUT holati va TIMEOUT sababi."""
    collector = _collector(timeout_seconds=7)
    result = collector.build(RunnerOutcome(timed_out=True), RUNTIME, duration_ms=7000)

    assert result.status is ExecutionStatus.TIMEOUT
    assert result.failure_reason is FailureReason.TIMEOUT
    assert "7 soniyalik" in (result.error_message or "")


def test_build_timeout_oomdan_ustun() -> None:
    """Vaqt limiti OOM belgisidan ustun (konteyner ikkisini ham qo'yishi mumkin)."""
    outcome = RunnerOutcome(timed_out=True, oom_killed=True)
    result = _collector().build(outcome, RUNTIME, duration_ms=1)
    assert result.failure_reason is FailureReason.TIMEOUT


def test_build_oom() -> None:
    """`oom_killed` -> FAILED + OOM, xabar xotira limitini ko'rsatadi."""
    collector = _collector(memory_mb=128)
    result = collector.build(RunnerOutcome(oom_killed=True), RUNTIME, duration_ms=50)

    assert result.status is ExecutionStatus.FAILED
    assert result.failure_reason is FailureReason.OOM
    assert "128 MB" in (result.error_message or "")


def test_build_infra_error() -> None:
    """Runner darajasidagi xato -> SANDBOX_ERROR (qayta urinishga yaroqli)."""
    outcome = RunnerOutcome(infra_error="Konteyner yaratilmadi")
    result = _collector().build(outcome, RUNTIME, duration_ms=5)

    assert result.status is ExecutionStatus.FAILED
    assert result.failure_reason is FailureReason.SANDBOX_ERROR
    assert result.error_message == "Konteyner yaratilmadi"


def test_build_output_too_large() -> None:
    """Chiqish limiti oshdi VA natija qaytmadi -> OUTPUT_TOO_LARGE."""
    collector = _collector(max_output_bytes=5)
    collector.feed(LogStream.STDOUT, "juda ko'p chiqish" * 10)
    result = collector.build(RunnerOutcome(exit_code=0), RUNTIME, duration_ms=10)

    assert result.status is ExecutionStatus.FAILED
    assert result.failure_reason is FailureReason.OUTPUT_TOO_LARGE
    assert result.truncated is True


def test_build_limit_oshgan_lekin_natija_bor_success() -> None:
    """Chiqish kesilgan bo'lsa ham natija qaytgan bo'lsa bu MUVAFFAQIYAT."""
    collector = _collector(max_output_bytes=5)
    collector.feed(LogStream.STDOUT, "ko'p chiqish" * 10)
    result = collector.build(_ok_outcome(result=1), RUNTIME, duration_ms=10)

    assert result.status is ExecutionStatus.SUCCESS
    assert result.truncated is True
    assert result.result == 1


def test_build_non_zero_exit() -> None:
    """`ok=False` va chiqish kodi noldan farqli -> NON_ZERO_EXIT."""
    outcome = RunnerOutcome(
        exit_code=1,
        runner_payload=RunnerPayload(
            ok=False, exit_code=1, error="x teng emas", error_type="ValueError"
        ),
    )
    result = _collector().build(outcome, RUNTIME, duration_ms=30)

    assert result.status is ExecutionStatus.FAILED
    assert result.failure_reason is FailureReason.NON_ZERO_EXIT
    assert result.error_message == "ValueError: x teng emas"
    assert result.result is None  # muvaffaqiyatsiz natija saqlanmaydi


def test_build_sintaksis_xatosi_validation_error() -> None:
    """Python runtime stderr'dagi `SyntaxError` ni VALIDATION_ERROR deb tasniflaydi."""
    collector = _collector()
    collector.feed(LogStream.STDERR, "SyntaxError: invalid syntax\n")
    outcome = RunnerOutcome(exit_code=1, runner_payload=RunnerPayload(ok=False, exit_code=1))
    result = collector.build(outcome, RUNTIME, duration_ms=5)

    assert result.failure_reason is FailureReason.VALIDATION_ERROR


def test_build_memory_error_oom_deb_tasniflanadi() -> None:
    """Lokal rejimda OOM belgisi yo'q — stderr'dagi `MemoryError` yetarli."""
    collector = _collector()
    collector.feed(LogStream.STDERR, "MemoryError\n")
    outcome = RunnerOutcome(exit_code=1, runner_payload=RunnerPayload(ok=False, exit_code=1))
    result = collector.build(outcome, RUNTIME, duration_ms=5)

    assert result.failure_reason is FailureReason.OOM


def test_build_xato_xabari_stderrdan_olinadi() -> None:
    """`result.json` da xato bo'lmasa stderr OXIRI ishlatiladi."""
    collector = _collector(max_output_bytes=100_000)
    collector.feed(LogStream.STDERR, "Traceback...\nRuntimeError: buzildi\n")
    outcome = RunnerOutcome(exit_code=1, runner_payload=RunnerPayload(ok=False, exit_code=1))
    result = collector.build(outcome, RUNTIME, duration_ms=5)

    assert result.error_message is not None
    assert result.error_message.endswith("RuntimeError: buzildi")
    assert len(result.error_message) <= ERROR_TAIL_CHARS


def test_build_xato_xabari_stderr_bosh_bolsa_chiqish_kodi() -> None:
    """stderr ham bo'sh bo'lsa xabar chiqish kodini ko'rsatadi."""
    outcome = RunnerOutcome(exit_code=3, runner_payload=RunnerPayload(ok=False, exit_code=3))
    result = _collector().build(outcome, RUNTIME, duration_ms=5)
    assert result.error_message == "Kod 3 chiqish kodi bilan tugadi"


def test_build_exit_code_payloaddan_olinadi() -> None:
    """Runner chiqish kodini bermasa `result.json` dagi qiymat olinadi."""
    outcome = RunnerOutcome(
        exit_code=None, runner_payload=RunnerPayload(ok=True, exit_code=0, result="x")
    )
    result = _collector().build(outcome, RUNTIME, duration_ms=1)
    assert result.exit_code == 0
    assert result.status is ExecutionStatus.SUCCESS


def test_build_flush_qiladi() -> None:
    """`build()` tugallanmagan qatorni ham log'ga chiqaradi."""
    collector = _collector()
    collector.feed(LogStream.STDOUT, "oxirgi qator yakunlanmagan")
    result = collector.build(_ok_outcome(), RUNTIME, duration_ms=1)
    assert [entry.content for entry in result.logs] == ["oxirgi qator yakunlanmagan"]


def test_build_metama_lumotlarni_kochiradi() -> None:
    """`sandbox_id`, `memory_peak_mb`, `traceback` natijaga o'tadi."""
    outcome = RunnerOutcome(
        exit_code=1,
        sandbox_id="container-abc",
        memory_peak_mb=77,
        runner_payload=RunnerPayload(ok=False, exit_code=1, traceback="satr 1\nsatr 2"),
    )
    result = _collector().build(outcome, RUNTIME, duration_ms=1)

    assert result.sandbox_id == "container-abc"
    assert result.memory_peak_mb == 77
    assert result.traceback == "satr 1\nsatr 2"


def test_build_payload_truncated_bayrogini_hurmat_qiladi() -> None:
    """Sandbox entrypoint'i o'zi kesgan bo'lsa ham `truncated` qo'yiladi."""
    outcome = RunnerOutcome(
        exit_code=0, runner_payload=RunnerPayload(ok=True, exit_code=0, truncated=True)
    )
    assert _collector().build(outcome, RUNTIME, duration_ms=1).truncated is True


def test_logs_xossasi_nusxa_qaytaradi() -> None:
    """`logs` nusxa beradi — tashqi kod ichki ro'yxatni buzmaydi."""
    collector = _collector()
    collector.feed(LogStream.STDOUT, "a\n")
    snapshot = collector.logs
    snapshot.clear()
    assert len(collector.logs) == 1
