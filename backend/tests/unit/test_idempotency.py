"""Durabl — `app/services/idempotency_service.py` birlik testlari.

Idempotentlik buzilsa mijoz bitta job uchun ikki marta to'lov qiladi yoki
bitta xat ikki marta ketadi. Shuning uchun quyidagi invariantlar tekshiriladi:

* **Atomar band qilish.** `SET NX` tufayli bir vaqtda kelgan N so'rovdan
  faqat BITTASI `None` (ya'ni "yangi job yarat") oladi.
* **Barmoq izi.** Ayni kalit BOSHQA tana bilan kelsa — `409 Conflict`,
  eski job'ni qaytarish XATO bo'lardi (mijoz boshqa kod yuborgan).
* **Foydalanuvchi izolyatsiyasi.** Kalit `user_id` bilan birga yasaladi,
  shuning uchun ikki mijozning bir xil kaliti to'qnashmaydi.
* **Fail-closed.** Redis javob bermasa so'rov RAD ETILADI (503) — aks holda
  Redis uzilgan paytda har bir takroriy so'rov yangi job yaratib ketardi.
* **TTL saqlanishi.** `commit()` TTL'ni YANGILAMAYDI (`KEEPTTL`), aks holda
  kalit abadiy yashab ketishi mumkin edi.

`fake_redis` fixture'i global klientni almashtiradi, shuning uchun servis
argumentsiz ham ayni shu klientni oladi.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any

import pytest
from app.config import settings
from app.constants import RedisKeys
from app.exceptions import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    InfrastructureError,
)
from app.services.idempotency_service import (
    STATE_COMPLETED,
    STATE_IN_PROGRESS,
    IdempotencyRecord,
    IdempotencyService,
)
from redis.exceptions import RedisError

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from redis.asyncio import Redis

pytestmark = pytest.mark.unit

KEY = "idem-key-0001"
BODY = {"code": "print(1)", "runtime": "python"}


class _BrokenRedis:
    """Har qanday amalda `RedisError` tashlaydigan klient (fail-closed testi)."""

    async def get(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RedisError("ulanish uzildi")

    async def set(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RedisError("ulanish uzildi")

    async def delete(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RedisError("ulanish uzildi")


# ---------------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------------


def test_fingerprint_kalit_tartibiga_boglanmaydi() -> None:
    """KRITIK: maydonlar tartibi o'zgarsa ham iz AYNI qoladi."""
    first = IdempotencyService.fingerprint({"a": 1, "b": 2})
    second = IdempotencyService.fingerprint({"b": 2, "a": 1})
    assert first == second
    assert len(first) == 64


def test_fingerprint_mazmun_ozgarsa_ozgaradi() -> None:
    """Tana o'zgarsa iz ham o'zgaradi — konflikt aniqlanadi."""
    assert IdempotencyService.fingerprint({"a": 1}) != IdempotencyService.fingerprint({"a": 2})


# ---------------------------------------------------------------------------
# IdempotencyRecord
# ---------------------------------------------------------------------------


def test_record_parse_yaroqli_yozuv() -> None:
    """To'g'ri JSON'dan yozuv tiklanadi."""
    record = IdempotencyRecord.parse('{"state":"completed","job_id":"j1","fingerprint":"f"}')
    assert record is not None
    assert record.state == STATE_COMPLETED
    assert record.job_id == "j1"
    assert record.is_completed is True


@pytest.mark.parametrize(
    "raw",
    [None, "", "{buzilgan", "[1,2]", '{"state":"yoq_holat"}', '"matn"'],
)
def test_record_parse_yaroqsiz_yozuv_none(raw: str | None) -> None:
    """Yaroqsiz yozuv ilovani yiqitmaydi — `None` qaytadi."""
    assert IdempotencyRecord.parse(raw) is None


def test_record_parse_in_progress_job_id_siz() -> None:
    """`in_progress` yozuvda `job_id` bo'lmaydi."""
    record = IdempotencyRecord.parse('{"state":"in_progress","job_id":null,"fingerprint":"f"}')
    assert record is not None
    assert record.job_id is None
    assert record.is_completed is False


def test_record_to_dict_aylanmasi() -> None:
    """`to_dict()` -> `parse()` yozuvni to'liq tiklaydi."""
    from app.utils.serializers import dump_json

    original = IdempotencyRecord(state=STATE_IN_PROGRESS, job_id=None, fingerprint="abc")
    assert IdempotencyRecord.parse(dump_json(original.to_dict())) == original


# ---------------------------------------------------------------------------
# reserve
# ---------------------------------------------------------------------------


async def test_reserve_birinchi_sorov_band_qiladi(fake_redis: Redis) -> None:
    """Birinchi so'rov `None` oladi — ya'ni yangi job yaratish mumkin."""
    service = IdempotencyService(fake_redis)
    assert await service.reserve(uuid.uuid4(), KEY, "fp-1") is None


async def test_reserve_ikkinchi_sorov_in_progress(fake_redis: Redis) -> None:
    """Birinchi so'rov hali `commit` qilmagan — ikkinchisi 409 oladi."""
    service = IdempotencyService(fake_redis)
    user_id = uuid.uuid4()
    await service.reserve(user_id, KEY, "fp-1")

    with pytest.raises(IdempotencyInProgressError):
        await service.reserve(user_id, KEY, "fp-1")


async def test_reserve_commitdan_keyin_mavjud_yozuv(fake_redis: Redis) -> None:
    """`commit` dan keyin takroriy so'rov MAVJUD job'ni oladi."""
    service = IdempotencyService(fake_redis)
    user_id = uuid.uuid4()
    job_id = str(uuid.uuid4())

    await service.reserve(user_id, KEY, "fp-1")
    await service.commit(user_id, KEY, job_id)

    record = await service.reserve(user_id, KEY, "fp-1")
    assert record is not None
    assert record.is_completed is True
    assert record.job_id == job_id


async def test_reserve_boshqa_barmoq_izi_konflikt(fake_redis: Redis) -> None:
    """KRITIK: ayni kalit boshqa tana bilan kelsa `IdempotencyConflictError`."""
    service = IdempotencyService(fake_redis)
    user_id = uuid.uuid4()
    await service.reserve(user_id, KEY, "fp-1")

    with pytest.raises(IdempotencyConflictError):
        await service.reserve(user_id, KEY, "fp-BOSHQA")


async def test_reserve_commitdan_keyin_ham_konflikt(fake_redis: Redis) -> None:
    """Yakunlangan kalit boshqa tana bilan kelsa ham konflikt."""
    service = IdempotencyService(fake_redis)
    user_id = uuid.uuid4()
    await service.reserve(user_id, KEY, "fp-1")
    await service.commit(user_id, KEY, uuid.uuid4())

    with pytest.raises(IdempotencyConflictError):
        await service.reserve(user_id, KEY, "fp-BOSHQA")


async def test_reserve_turli_foydalanuvchilarda_ayni_kalit(fake_redis: Redis) -> None:
    """KRITIK: ikki mijozning bir xil kaliti to'qnashmaydi."""
    service = IdempotencyService(fake_redis)
    first_user, second_user = uuid.uuid4(), uuid.uuid4()

    assert await service.reserve(first_user, KEY, "fp-1") is None
    assert await service.reserve(second_user, KEY, "fp-2") is None  # boshqa tana ham mumkin


async def test_reserve_turli_kalitlar_mustaqil(fake_redis: Redis) -> None:
    """Bitta foydalanuvchining turli kalitlari bir-biriga ta'sir qilmaydi."""
    service = IdempotencyService(fake_redis)
    user_id = uuid.uuid4()
    assert await service.reserve(user_id, "key-a", "fp") is None
    assert await service.reserve(user_id, "key-b", "fp") is None


async def test_reserve_bir_vaqtda_faqat_bittasi_otadi(fake_redis: Redis) -> None:
    """Atomarlik: 10 parallel so'rovdan AYNAN bittasi band qiladi."""
    service = IdempotencyService(fake_redis)
    user_id = uuid.uuid4()

    results = await asyncio.gather(
        *(service.reserve(user_id, KEY, "fp-1") for _ in range(10)),
        return_exceptions=True,
    )

    reserved = [item for item in results if item is None]
    rejected = [item for item in results if isinstance(item, IdempotencyInProgressError)]
    assert len(reserved) == 1
    assert len(rejected) == 9


async def test_reserve_global_klientni_oladi(fake_redis: Redis) -> None:
    """Argumentsiz yasalgan servis global (test) klientini ishlatadi."""
    user_id = uuid.uuid4()
    assert await IdempotencyService().reserve(user_id, KEY, "fp") is None
    assert await fake_redis.get(RedisKeys.idempotency(user_id, KEY)) is not None


# ---------------------------------------------------------------------------
# commit
# ---------------------------------------------------------------------------


async def test_commit_holatni_ozgartiradi(fake_redis: Redis) -> None:
    """`commit` yozuvni `completed` holatiga o'tkazadi va `job_id` yozadi."""
    service = IdempotencyService(fake_redis)
    user_id = uuid.uuid4()
    job_id = uuid.uuid4()

    await service.reserve(user_id, KEY, "fp-1")
    await service.commit(user_id, KEY, job_id)

    record = await service.lookup(user_id, KEY)
    assert record is not None
    assert record.state == STATE_COMPLETED
    assert record.job_id == str(job_id)
    assert record.fingerprint == "fp-1"  # iz saqlanadi


async def test_commit_ttl_ni_saqlaydi(fake_redis: Redis) -> None:
    """KRITIK: `commit` TTL'ni YANGILAMAYDI — kalit abadiy yashab ketmaydi."""
    service = IdempotencyService(fake_redis)
    user_id = uuid.uuid4()
    redis_key = RedisKeys.idempotency(user_id, KEY)

    await service.reserve(user_id, KEY, "fp-1")
    await fake_redis.expire(redis_key, 120)  # TTL'ni sun'iy qisqartiramiz
    await service.commit(user_id, KEY, uuid.uuid4())

    ttl = await fake_redis.ttl(redis_key)
    assert 0 < ttl <= 120


async def test_commit_yozuv_yoq_bolsa_yangisini_yozadi(fake_redis: Redis) -> None:
    """TTL tugab ketgan bo'lsa ham takroriy so'rov TO'G'RI job'ni oladi."""
    service = IdempotencyService(fake_redis)
    user_id = uuid.uuid4()
    job_id = uuid.uuid4()

    await service.commit(user_id, KEY, job_id)  # `reserve` qilinmagan

    record = await service.lookup(user_id, KEY)
    assert record is not None
    assert record.job_id == str(job_id)
    ttl = await fake_redis.ttl(RedisKeys.idempotency(user_id, KEY))
    assert ttl > 0


async def test_reserve_ttl_sozlamadan_olinadi(fake_redis: Redis) -> None:
    """Band qilish TTL'i `settings.IDEMPOTENCY_TTL_SECONDS` ga teng."""
    service = IdempotencyService(fake_redis)
    user_id = uuid.uuid4()
    await service.reserve(user_id, KEY, "fp-1")

    ttl = await fake_redis.ttl(RedisKeys.idempotency(user_id, KEY))
    assert 0 < ttl <= settings.IDEMPOTENCY_TTL_SECONDS


# ---------------------------------------------------------------------------
# release
# ---------------------------------------------------------------------------


async def test_release_kalitni_boshatadi(fake_redis: Redis) -> None:
    """Job yaratish yiqilsa kalit bo'shatiladi va qayta ishlatilishi mumkin."""
    service = IdempotencyService(fake_redis)
    user_id = uuid.uuid4()

    await service.reserve(user_id, KEY, "fp-1")
    await service.release(user_id, KEY)

    assert await service.lookup(user_id, KEY) is None
    assert await service.reserve(user_id, KEY, "fp-1") is None  # qayta band qilish mumkin


async def test_release_mavjud_bolmagan_kalit_xato_bermaydi(fake_redis: Redis) -> None:
    """Yo'q kalitni bo'shatish xato tashlamaydi (idempotent amal)."""
    await IdempotencyService(fake_redis).release(uuid.uuid4(), "yoq-kalit")


async def test_release_boshqa_foydalanuvchiga_tegmaydi(fake_redis: Redis) -> None:
    """Bir mijozning `release` i boshqasining kalitini o'chirmaydi."""
    service = IdempotencyService(fake_redis)
    first_user, second_user = uuid.uuid4(), uuid.uuid4()
    await service.reserve(first_user, KEY, "fp")
    await service.reserve(second_user, KEY, "fp")

    await service.release(first_user, KEY)

    assert await service.lookup(first_user, KEY) is None
    assert await service.lookup(second_user, KEY) is not None


# ---------------------------------------------------------------------------
# lookup
# ---------------------------------------------------------------------------


async def test_lookup_yoq_kalit_none(fake_redis: Redis) -> None:
    """Band qilinmagan kalit uchun `None`."""
    assert await IdempotencyService(fake_redis).lookup(uuid.uuid4(), "yoq") is None


async def test_lookup_barmoq_izini_solishtirmaydi(fake_redis: Redis) -> None:
    """`lookup` konflikt tekshirmaydi — faqat holatni o'qiydi."""
    service = IdempotencyService(fake_redis)
    user_id = uuid.uuid4()
    await service.reserve(user_id, KEY, "fp-1")

    record = await service.lookup(user_id, KEY)  # xato tashlanmaydi
    assert record is not None
    assert record.state == STATE_IN_PROGRESS


async def test_lookup_yaroqsiz_yozuv_none(fake_redis: Redis) -> None:
    """Qo'lda buzilgan yozuv `None` deb o'qiladi (kalit bo'sh hisoblanadi)."""
    user_id = uuid.uuid4()
    await fake_redis.set(RedisKeys.idempotency(user_id, KEY), "{buzilgan")
    assert await IdempotencyService(fake_redis).lookup(user_id, KEY) is None


# ---------------------------------------------------------------------------
# Fail-closed (Redis javob bermaydi)
# ---------------------------------------------------------------------------


async def test_reserve_redis_yiqilsa_infrastructure_error() -> None:
    """KRITIK: Redis javob bermasa so'rov RAD ETILADI (yangi job yaratilmaydi)."""
    service = IdempotencyService(_BrokenRedis())  # type: ignore[arg-type]
    with pytest.raises(InfrastructureError):
        await service.reserve(uuid.uuid4(), KEY, "fp")


async def test_commit_redis_yiqilsa_infrastructure_error() -> None:
    """`commit` ham jim o'tib ketmaydi."""
    service = IdempotencyService(_BrokenRedis())  # type: ignore[arg-type]
    with pytest.raises(InfrastructureError):
        await service.commit(uuid.uuid4(), KEY, uuid.uuid4())


async def test_release_redis_yiqilsa_infrastructure_error() -> None:
    """`release` xatosi ham ko'rinadi (kalit qulflanib qolgani bilinadi)."""
    service = IdempotencyService(_BrokenRedis())  # type: ignore[arg-type]
    with pytest.raises(InfrastructureError):
        await service.release(uuid.uuid4(), KEY)


async def test_lookup_redis_yiqilsa_infrastructure_error() -> None:
    """`lookup` ham fail-closed (middleware noto'g'ri qaror qabul qilmaydi)."""
    service = IdempotencyService(_BrokenRedis())  # type: ignore[arg-type]
    with pytest.raises(InfrastructureError):
        await service.lookup(uuid.uuid4(), KEY)


# ---------------------------------------------------------------------------
# To'liq zanjir
# ---------------------------------------------------------------------------


async def test_toliq_zanjir_takroriy_sorov_ayni_jobni_oladi(fake_redis: Redis) -> None:
    """Haqiqiy oqim: band qilish -> commit -> takroriy so'rov -> AYNI job."""
    service = IdempotencyService(fake_redis)
    user_id = uuid.uuid4()
    fingerprint = service.fingerprint(BODY)
    job_id = str(uuid.uuid4())

    assert await service.reserve(user_id, KEY, fingerprint) is None
    await service.commit(user_id, KEY, job_id)

    # Mijoz javobni olmadi va so'rovni (maydonlar tartibi boshqa) qayta yubordi
    repeated_fingerprint = service.fingerprint({"runtime": "python", "code": "print(1)"})
    record = await service.reserve(user_id, KEY, repeated_fingerprint)

    assert record is not None
    assert record.job_id == job_id


async def test_toliq_zanjir_xato_bolsa_kalit_boshatiladi(fake_redis: Redis) -> None:
    """Job yaratish yiqilsa `release` kalitni 24 soat qulflab qoldirmaydi."""
    service = IdempotencyService(fake_redis)
    user_id = uuid.uuid4()
    fingerprint = service.fingerprint(BODY)

    await service.reserve(user_id, KEY, fingerprint)
    try:
        raise RuntimeError("DB yiqildi")
    except RuntimeError:
        await service.release(user_id, KEY)

    assert await service.reserve(user_id, KEY, fingerprint) is None
