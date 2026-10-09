"""Durabl — `app/utils/serializers.py` birlik testlari.

Uch kritik xususiyat tekshiriladi:

1. **Yagona encoder.** UUID, `datetime`, `Enum`, dataclass — hammasi HTTP
   javobida, Redis Pub/Sub'da va webhook tanasida BIR XIL ko'rinishda chiqadi.
2. **Barmoq izi barqarorligi.** `fingerprint()` kalitlar tartibiga BOG'LIQ
   EMAS — aks holda mijoz bir xil tanani boshqa tartibda yuborsa
   `IdempotencyConflictError` olardi (soxta 409).
3. **`lazy="raise"` xavfsizligi.** `job_event_payload()` faqat `getattr`
   bilan ishlaydi, shuning uchun munosabatga (`job.user`) TEGMAYDI va async
   kontekstda `MissingGreenlet`/`InvalidRequestError` bermaydi.
"""

from __future__ import annotations

import base64
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest
from app.constants import FailureReason, JobStatus, Priority, Runtime
from app.exceptions import ValidationError
from app.utils.serializers import (
    MAX_EVENT_ERROR_CHARS,
    deserialize_payload,
    dump_json,
    fingerprint,
    job_event_payload,
    job_result_payload,
    json_default,
    load_json,
    serialize_payload,
    truncate,
    truncate_bytes,
    truncate_output,
)

from tests.factories import make_job

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from app.models.user import User
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.unit


@dataclass
class _Point:
    """Test uchun oddiy dataclass (encoder uni lug'atga aylantirishi kerak)."""

    x: int
    y: str


# ---------------------------------------------------------------------------
# dump_json
# ---------------------------------------------------------------------------


def test_dump_json_uuid_matn_boladi() -> None:
    """UUID JSON'da matn ko'rinishida chiqadi."""
    identifier = uuid.uuid4()
    assert dump_json({"id": identifier}) == f'{{"id":"{identifier}"}}'


def test_dump_json_datetime_iso_z() -> None:
    """`datetime` ISO-8601 UTC (`Z`) ko'rinishida chiqadi."""
    moment = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)
    assert dump_json({"at": moment}) == '{"at":"2026-10-04T12:00:00Z"}'


def test_dump_json_enum_qiymatini_yozadi() -> None:
    """`Enum` nomi emas, QIYMATI yoziladi (frontend shu matnni kutadi)."""
    assert dump_json({"status": JobStatus.RUNNING}) == '{"status":"running"}'
    assert dump_json([Priority.HIGH, Runtime.NODE]) == '["high","node"]'


def test_dump_json_dataclass_lugat_boladi() -> None:
    """Dataclass maydonlari lug'atga aylanadi."""
    assert dump_json(_Point(x=1, y="a")) == '{"x":1,"y":"a"}'


def test_dump_json_set_tartiblangan_royxat() -> None:
    """`set` tartiblangan ro'yxatga aylanadi — natija takrorlanadigan bo'ladi."""
    assert dump_json({"tags": {"b", "a", "c"}}) == '{"tags":["a","b","c"]}'


def test_dump_json_bytes_base64() -> None:
    """`bytes` base64 matnga aylanadi (JSON'da xom bayt bo'lmaydi)."""
    raw = b"durabl"
    expected = base64.b64encode(raw).decode("ascii")
    assert dump_json(raw) == f'"{expected}"'


def test_dump_json_ozbekcha_matnni_buzmaydi() -> None:
    """`ensure_ascii=False` — o'zbekcha matn o'qishli qoladi."""
    assert dump_json({"msg": "muvaffaqiyatli"}) == '{"msg":"muvaffaqiyatli"}'
    assert "\\u" not in dump_json({"msg": "o'zbekcha ğ"})


def test_dump_json_sort_keys_barqaror_tartib() -> None:
    """`sort_keys=True` kalitlarni alifbo tartibida yozadi."""
    assert dump_json({"b": 1, "a": 2}, sort_keys=True) == '{"a":2,"b":1}'


def test_dump_json_aylanma_havola_validation_error() -> None:
    """Aylanma havola JSON'ga aylanmaydi — domen xatosi tashlanadi."""
    cyclic: dict[str, Any] = {}
    cyclic["self"] = cyclic
    with pytest.raises(ValidationError):
        dump_json(cyclic)


def test_json_default_notanish_tur_typeerror() -> None:
    """`json_default` qo'lidan kelmasa `TypeError` beradi (encoder uni tutadi)."""
    with pytest.raises(TypeError):
        json_default(object())


# ---------------------------------------------------------------------------
# load_json
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("raw", [None, "", "   "])
def test_load_json_bosh_qiymat_none(raw: str | None) -> None:
    """Bo'sh kirish `None` beradi (Redis'da kalit yo'q holati)."""
    assert load_json(raw) is None


def test_load_json_baytlarni_oqiydi() -> None:
    """Redis `decode_responses=False` rejimida bayt qaytaradi — qo'llanadi."""
    assert load_json(b'{"a":1}') == {"a": 1}


def test_load_json_yaroqsiz_matn_validation_error() -> None:
    """Buzilgan JSON domen xatosi beradi (`json.JSONDecodeError` chiqmaydi)."""
    with pytest.raises(ValidationError):
        load_json("{not json")


def test_load_json_utf8_bolmagan_bayt_validation_error() -> None:
    """UTF-8 bo'lmagan bayt ketma-ketligi ham domen xatosiga aylanadi."""
    with pytest.raises(ValidationError):
        load_json(b"\xff\xfe")


def test_dump_load_aylanma() -> None:
    """`dump_json` -> `load_json` mazmunni saqlaydi."""
    value = {"n": 1, "s": "x", "list": [1, 2], "none": None, "bool": True}
    assert load_json(dump_json(value)) == value


# ---------------------------------------------------------------------------
# Payload
# ---------------------------------------------------------------------------


def test_serialize_payload_none_null_matn() -> None:
    """`None` -> `"null"` (deserializatsiya bilan simmetrik)."""
    assert serialize_payload(None) == "null"
    assert deserialize_payload("null") is None


def test_serialize_payload_lugat_bolmasa_xato() -> None:
    """Payload faqat JSON obyekt (lug'at) bo'lishi mumkin."""
    with pytest.raises(ValidationError):
        serialize_payload([1, 2])  # type: ignore[arg-type]


def test_deserialize_payload_lugat_bolmasa_xato() -> None:
    """JSON massiv payload sifatida qabul qilinmaydi."""
    with pytest.raises(ValidationError):
        deserialize_payload("[1,2]")


def test_serialize_deserialize_aylanma() -> None:
    """Payload aylanmasi mazmunni saqlaydi."""
    payload = {"name": "test", "count": 3}
    assert deserialize_payload(serialize_payload(payload)) == payload


# ---------------------------------------------------------------------------
# Kesish
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    [
        (None, 10, ("", False)),
        ("", 10, ("", False)),
        ("abc", 10, ("abc", False)),
        ("abc", 3, ("abc", False)),
        ("abcdef", 3, ("abc", True)),
        ("abc", 0, ("", True)),
        ("abc", -1, ("", True)),
    ],
)
def test_truncate_belgilar_boyicha(
    text: str | None, limit: int, expected: tuple[str, bool]
) -> None:
    """`truncate` BELGI bo'yicha kesadi va kesilganini bildiradi."""
    assert truncate(text, limit) == expected


def test_truncate_bytes_utf8_belgisini_yarmidan_bolmaydi() -> None:
    """Ko'p baytli belgi yarmidan kesilmaydi — natija yaroqli UTF-8 qoladi."""
    text = "ёёё"  # har biri 2 bayt => jami 6 bayt
    cut, truncated = truncate_bytes(text, 3)
    assert truncated is True
    assert cut == "ё"  # yarim bayt tashlandi
    cut.encode("utf-8")  # yaroqli matn — kodlash xato bermaydi


def test_truncate_bytes_chegarada_kesmaydi() -> None:
    """Hajm aynan chegaraga teng bo'lsa kesilmaydi."""
    text = "ёёё"
    assert truncate_bytes(text, 6) == (text, False)


def test_truncate_bytes_bir_baytli_matn() -> None:
    """ASCII matn uchun bayt va belgi chegarasi mos tushadi."""
    assert truncate_bytes("abcdef", 4) == ("abcd", True)


def test_truncate_output_sozlamadan_chegarani_oladi(monkeypatch: pytest.MonkeyPatch) -> None:
    """`truncate_output` chegarani `settings.MAX_OUTPUT_BYTES` dan oladi."""
    from app.config import settings

    monkeypatch.setattr(settings, "MAX_OUTPUT_BYTES", 4)
    assert truncate_output("abcdefgh") == ("abcd", True)
    assert truncate_output("ab") == ("ab", False)


def test_truncate_output_utf8_buzilmaydi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chegara ko'p baytli belgi o'rtasiga tushsa ham matn yaroqli qoladi."""
    from app.config import settings

    monkeypatch.setattr(settings, "MAX_OUTPUT_BYTES", 5)
    cut, truncated = truncate_output("ёёё")
    assert truncated is True
    assert cut == "ёё"


# ---------------------------------------------------------------------------
# Barmoq izi (fingerprint)
# ---------------------------------------------------------------------------


def test_fingerprint_uzunligi_va_hex() -> None:
    """Iz — 64 belgili SHA-256 hex."""
    value = fingerprint({"a": 1})
    assert len(value) == 64
    int(value, 16)  # hex ekanini tasdiqlaydi


def test_fingerprint_kalit_tartibiga_boglanmaydi() -> None:
    """KRITIK: kalitlar tartibi o'zgarsa ham iz AYNI qoladi."""
    first = fingerprint({"code": "x", "runtime": "python", "timeout_seconds": 5})
    second = fingerprint({"timeout_seconds": 5, "runtime": "python", "code": "x"})
    assert first == second


def test_fingerprint_ichki_lugat_tartibiga_ham_boglanmaydi() -> None:
    """Ichma-ich lug'atlarda ham tartib ahamiyatsiz."""
    first = fingerprint({"payload": {"b": 2, "a": 1}})
    second = fingerprint({"payload": {"a": 1, "b": 2}})
    assert first == second


def test_fingerprint_qiymat_ozgarsa_ozgaradi() -> None:
    """Mazmun o'zgarsa iz ham o'zgaradi (konflikt aniqlanishi uchun)."""
    assert fingerprint({"code": "x"}) != fingerprint({"code": "y"})


def test_fingerprint_royxat_tartibi_ahamiyatli() -> None:
    """Ro'yxat TARTIBI mazmunning bir qismi — iz o'zgarishi kerak."""
    assert fingerprint({"tags": ["a", "b"]}) != fingerprint({"tags": ["b", "a"]})


def test_fingerprint_lugat_bolmasa_xato() -> None:
    """Iz faqat lug'at uchun hisoblanadi."""
    with pytest.raises(ValidationError):
        fingerprint([1, 2])  # type: ignore[arg-type]


def test_fingerprint_enum_va_uuid_bilan_ishlaydi() -> None:
    """Enum/UUID qiymatlari ham izga kiradi (encoder orqali)."""
    identifier = uuid.uuid4()
    first = fingerprint({"runtime": Runtime.PYTHON, "id": identifier})
    second = fingerprint({"id": identifier, "runtime": Runtime.PYTHON})
    assert first == second


# ---------------------------------------------------------------------------
# job_event_payload
# ---------------------------------------------------------------------------


def test_job_event_payload_maydonlari() -> None:
    """Hodisa shaklida frontend va SDK kutadigan barcha kalitlar bor."""
    job = make_job(status=JobStatus.SUCCESS, exit_code=0, duration_ms=120)
    payload = job_event_payload(job)
    assert set(payload) == {
        "job_id",
        "user_id",
        "status",
        "runtime",
        "priority",
        "created_at",
        "started_at",
        "finished_at",
        "duration_ms",
        "exit_code",
        "retry_count",
        "failure_reason",
        "error",
        "correlation_id",
    }
    assert payload["status"] == "success"
    assert payload["runtime"] == "python"
    assert payload["duration_ms"] == 120
    assert payload["retry_count"] == 0


def test_job_event_payload_xatoni_kesadi() -> None:
    """Juda uzun `error` matni hodisa tanasini to'ldirib yubormaydi."""
    job = make_job(error="x" * (MAX_EVENT_ERROR_CHARS + 500))
    payload = job_event_payload(job)
    assert payload["error"] is not None
    assert len(payload["error"]) == MAX_EVENT_ERROR_CHARS


def test_job_event_payload_bosh_xato_none() -> None:
    """`error` bo'sh bo'lsa `None` chiqadi (bo'sh matn emas)."""
    assert job_event_payload(make_job())["error"] is None


def test_job_event_payload_failure_reason_qiymati() -> None:
    """`failure_reason` enum qiymati matn ko'rinishida chiqadi."""
    job = make_job(failure_reason=FailureReason.TIMEOUT)
    assert job_event_payload(job)["failure_reason"] == "timeout"


async def test_job_event_payload_lazy_raise_munosabatga_tegmaydi(
    db_session: AsyncSession, user: User
) -> None:
    """KRITIK: saqlangan job uchun ham hodisa yasash munosabatni O'QIMAYDI.

    `Job.user` `lazy="raise"` bilan, ya'ni unga murojaat qilish
    `InvalidRequestError` tashlardi. Test haqiqiy (persistent) obyekt bilan
    ishlaydi — transient obyektda bu himoya ishlamaydi.
    """
    job = make_job(user_id=user.id, status=JobStatus.QUEUED)
    db_session.add(job)
    await db_session.commit()
    await db_session.refresh(job)

    payload = job_event_payload(job)

    assert payload["job_id"] == str(job.id)
    assert payload["user_id"] == str(user.id)
    assert payload["status"] == "queued"
    # Munosabat hamon yuklanmagan — ya'ni funksiya unga tegmadi.
    assert "user" not in job.__dict__


def test_job_result_payload_qoshimcha_maydonlar() -> None:
    """Natija shakli hodisa shakliga stdout/stderr/result qo'shadi."""
    job = make_job(id=uuid.uuid4(), stdout="salom\n", stderr="", result={"value": 7})
    payload = job_result_payload(job)
    assert payload["stdout"] == "salom\n"
    assert payload["stderr"] == ""
    assert payload["stdout_truncated"] is False
    assert payload["stderr_truncated"] is False
    assert payload["result"] == {"value": 7}
    # Hodisa shaklidagi kalitlar ham saqlanadi
    assert payload["job_id"] == str(job.id)


def test_job_result_payload_kesilganini_bildiradi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chiqish kesilsa `stdout_truncated=True` bo'ladi."""
    from app.config import settings

    monkeypatch.setattr(settings, "MAX_OUTPUT_BYTES", 3)
    payload = job_result_payload(make_job(stdout="abcdef"))
    assert payload["stdout"] == "abc"
    assert payload["stdout_truncated"] is True
