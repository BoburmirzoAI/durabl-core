"""Durabl — idempotentlik: "ikki marta to'lamaslik" kafolati.

`Idempotency-Key` Durabl'da ikki qatlamda himoyalangan va ikkisi ham shu
faylda tekshiriladi:

1. **Redis (`IdempotencyService`)** — `SET NX` bilan atomar band qilish.
   Parallel so'rovlardan faqat BITTASI kalitni band qiladi, qolganlari
   `IDEMPOTENCY_IN_PROGRESS` (409) oladi.
2. **DB (`uq_jobs_user_idempotency`)** — `(user_id, idempotency_key)`
   bo'yicha UNIQUE cheklov. Redis qulasa ham ikkinchi job yaratilmaydi;
   `JobService.submit()` cheklov buzilishini ushlab g'olibning job'ini
   qaytaradi.

## Nega har testda `count_jobs()` bor

Javob kodi (201 / 200 / 409) — mijozga qulaylik, lekin ASOSIY kafolat
jadvalda: kod qanday bo'lsa ham `jobs` da KUTILGAN SONDA qator bo'lishi
kerak. Shuning uchun har test javoblardan tashqari bevosita SQL hisobini
ham tekshiradi.

## Barmoq izi (fingerprint) chegarasi

Kalit so'rov TANASIGA bog'langan: `IdempotencyService.fingerprint()`
kod, runtime, payload, limitlar va teglardan SHA-256 yasaydi. Shu tufayli
bir xil kalitni BOSHQA tana bilan ishlatish 409 `IDEMPOTENCY_CONFLICT`
beradi — mijozning kalitni qayta ishlatib yuborgani jim o'tib ketmaydi.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest
from app.constants import HEADER_IDEMPOTENCY_KEY, JobStatus, RedisKeys, Runtime
from app.utils.security import create_access_token

from tests.conftest import ParallelEnv

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from collections.abc import Awaitable, Callable

    import httpx
    from app.models.execution import Execution
    from app.models.job import Job
    from app.models.user import User
    from redis.asyncio import Redis

pytestmark = pytest.mark.e2e

#: Parallel so'rovlar soni (vazifa shartiga ko'ra beshta).
PARALLEL_REQUESTS = 5

#: Testlarda ishlatiladigan kod — har doim muvaffaqiyatli bajariladi.
IDEMPOTENT_CODE = "print('bitta marta')\n"

#: `IdempotencyMiddleware` kalit uzunligini 8..255 belgida cheklaydi va
#: faqat `[A-Za-z0-9_.:-]` ga ruxsat beradi.
KEY_PARALLEL = "e2e-parallel-0001"
KEY_AFTER_FINISH = "e2e-tugagandan-keyin"
KEY_SHARED = "e2e-umumiy-kalit"

#: `POST /jobs` ning idempotent takroriy so'rovi uchun kutilgan kodlar.
#: `201` — yangi job; `200` — tayyor job qaytarildi; `409` — birinchi
#: so'rov hali `commit` qilmagan (`IDEMPOTENCY_IN_PROGRESS`). Uchtasi ham
#: TO'G'RI javob, chunki hech birida ikkinchi job YARATILMAYDI.
ACCEPTED_CODES = frozenset({200, 201, 409})


def _body(code: str = IDEMPOTENT_CODE) -> dict[str, object]:
    """Standart `JobCreate` tanasi."""
    return {"code": code, "runtime": Runtime.PYTHON.value}


def _with_key(headers: dict[str, str], key: str) -> dict[str, str]:
    """Header'larga `Idempotency-Key` qo'shadi."""
    return {**headers, HEADER_IDEMPOTENCY_KEY: key}


# ---------------------------------------------------------------------------
# 1. Parallel so'rovlar
# ---------------------------------------------------------------------------


async def test_parallel_requests_with_same_key_create_one_job(
    parallel_client: ParallelEnv,
    api_prefix: str,
    fake_redis: Redis,
) -> None:
    """AYNI kalit bilan 5 parallel `POST /jobs` -> BITTA job.

    Bu test standart `client` fixture'ini ISHLATMAYDI: u `get_db` ni bitta
    `db_session` ga bog'laydi, bitta `AsyncSession` ni esa parallel
    ishlatish mumkin emas (`MissingGreenlet`) — ya'ni o'lchanayotgan narsa
    ilova emas, test infratuzilmasi bo'lib qolardi. `parallel_client` fayl
    bazasi + haqiqiy `get_db` beradi, demak har so'rov O'Z sessiyasi va
    O'Z ulanishida ketadi — aynan production'dagi kabi.
    """
    client = parallel_client.client
    user = parallel_client.user
    count_jobs = parallel_client.count_jobs
    headers = _with_key(parallel_client.headers, KEY_PARALLEL)
    responses = await asyncio.gather(
        *(
            client.post(f"{api_prefix}/jobs", headers=headers, json=_body())
            for _ in range(PARALLEL_REQUESTS)
        )
    )

    codes = [response.status_code for response in responses]
    assert set(codes) <= ACCEPTED_CODES, codes
    # Aniq BITTA so'rov job YARATDI.
    assert codes.count(201) == 1, codes

    created = next(response for response in responses if response.status_code == 201)
    job_id = created.json()["id"]
    assert created.json()["idempotency_key"] == KEY_PARALLEL

    # Muvaffaqiyatli javoblarning hammasi AYNI job'ni ko'rsatadi.
    for response in responses:
        if response.status_code in (200, 201):
            assert response.json()["id"] == job_id
        else:
            assert response.json()["error"]["code"] == "IDEMPOTENCY_IN_PROGRESS"

    # --- ASOSIY KAFOLAT ---------------------------------------------
    assert await count_jobs(user.id) == 1
    assert await count_jobs() == 1

    # Navbatda ham BITTA yozuv — kod bir marta bajariladi.
    assert await fake_redis.lrange(RedisKeys.queue("normal"), 0, -1) == [f"normal:{job_id}"]


# ---------------------------------------------------------------------------
# 2. Tugagan job'dan keyin ayni kalit
# ---------------------------------------------------------------------------


async def test_same_key_after_completion_returns_finished_job(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    user: User,
    run_until: Callable[..., Awaitable[Job]],
    count_jobs: Callable[..., Awaitable[int]],
    fetch_executions: Callable[..., Awaitable[list[Execution]]],
    fake_redis: Redis,
) -> None:
    """Kod BAJARILGANDAN keyin ayni kalit -> AYNI job, QAYTA bajarilmaydi.

    Bu idempotentlikning eng qimmat holati: mijoz tarmoq uzilgani uchun
    so'rovni takrorlaydi, lekin job allaqachon bajarilib bo'lgan. Yangi
    job yaratish mijozning kodini IKKI MARTA bajarish bo'lardi.
    """
    headers = _with_key(auth_headers, KEY_AFTER_FINISH)

    first = await client.post(f"{api_prefix}/jobs", headers=headers, json=_body())
    assert first.status_code == 201, first.text
    job_id = first.json()["id"]

    finished = await run_until(job_id, JobStatus.SUCCESS)
    assert finished.stdout == "bitta marta\n"

    # --- Takroriy so'rov --------------------------------------------
    second = await client.post(f"{api_prefix}/jobs", headers=headers, json=_body())
    assert second.status_code == 200, second.text
    assert second.json()["id"] == job_id
    # Tayyor natija BIRGA qaytadi — mijoz qayta polling qilishi shart emas.
    assert second.json()["status"] == JobStatus.SUCCESS.value
    assert second.json()["stdout"] == "bitta marta"
    assert second.headers["Location"] == f"{api_prefix}/jobs/{job_id}"

    # --- QAYTA BAJARILMADI ------------------------------------------
    assert await count_jobs(user.id) == 1
    assert len(await fetch_executions(job_id)) == 1
    assert await fake_redis.lrange(RedisKeys.queue("normal"), 0, -1) == []


# ---------------------------------------------------------------------------
# 3. Boshqa tana + ayni kalit
# ---------------------------------------------------------------------------


async def test_same_key_with_different_body_conflicts(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    user: User,
    count_jobs: Callable[..., Awaitable[int]],
) -> None:
    """Ayni kalit, BOSHQA tana -> 409 `IDEMPOTENCY_CONFLICT`."""
    # `conftest.override_get_db` xato javobdan keyin `rollback()` qiladi va
    # baham ko'rilgan `db_session` dagi BARCHA ORM obyektlari "expired"
    # bo'ladi. Shundan keyin `user.id` ga murojaat sinxron kontekstda lazy
    # yuklanishni boshlab `MissingGreenlet` berardi — shuning uchun
    # identifikator so'rovlardan OLDIN oddiy qiymatga ko'chiriladi.
    user_id = user.id
    headers = _with_key(auth_headers, KEY_SHARED)

    first = await client.post(f"{api_prefix}/jobs", headers=headers, json=_body())
    assert first.status_code == 201, first.text

    conflict = await client.post(
        f"{api_prefix}/jobs",
        headers=headers,
        json=_body("print('butunlay boshqa kod')\n"),
    )
    assert conflict.status_code == 409, conflict.text
    error = conflict.json()["error"]
    assert error["code"] == "IDEMPOTENCY_CONFLICT"
    assert error["details"]["idempotency_key"] == KEY_SHARED

    # Konflikt ikkinchi job YARATMAYDI.
    assert await count_jobs(user_id) == 1

    # To'g'ri tana bilan takrorlash BARIBIR ishlaydi — konflikt kalitni
    # "o'lik" qilib qo'ymaydi.
    repeated = await client.post(f"{api_prefix}/jobs", headers=headers, json=_body())
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["id"] == first.json()["id"]
    assert await count_jobs(user_id) == 1


# ---------------------------------------------------------------------------
# 4. Turli foydalanuvchilar, ayni kalit
# ---------------------------------------------------------------------------


async def test_same_key_for_different_users_is_independent(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    user: User,
    other_user: User,
    count_jobs: Callable[..., Awaitable[int]],
) -> None:
    """Kalit foydalanuvchi bo'yicha ajratilgan -> IKKI alohida job.

    `RedisKeys.idempotency(user_id, key)` va `uq_jobs_user_idempotency`
    ikkisi ham `user_id` ni o'z ichiga oladi. Aks holda bir mijozning
    kaliti boshqasining job'ini qaytarib yuborardi — ma'lumot oqishi.
    """
    other_headers = {"Authorization": f"Bearer {create_access_token(other_user.id)}"}

    mine = await client.post(
        f"{api_prefix}/jobs", headers=_with_key(auth_headers, KEY_SHARED), json=_body()
    )
    theirs = await client.post(
        f"{api_prefix}/jobs", headers=_with_key(other_headers, KEY_SHARED), json=_body()
    )

    assert mine.status_code == 201, mine.text
    assert theirs.status_code == 201, theirs.text
    assert mine.json()["id"] != theirs.json()["id"]
    assert mine.json()["user_id"] == str(user.id)
    assert theirs.json()["user_id"] == str(other_user.id)

    assert await count_jobs(user.id) == 1
    assert await count_jobs(other_user.id) == 1
    assert await count_jobs() == 2

    # Begona job ko'rinmaydi (IDOR himoyasi) — kalit bir xil bo'lsa ham.
    foreign = await client.get(
        f"{api_prefix}/jobs/{theirs.json()['id']}", headers=auth_headers
    )
    assert foreign.status_code == 404


# ---------------------------------------------------------------------------
# 5. Kalitsiz so'rovlar
# ---------------------------------------------------------------------------


async def test_requests_without_key_create_separate_jobs(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    user: User,
    count_jobs: Callable[..., Awaitable[int]],
    fake_redis: Redis,
) -> None:
    """Kalitsiz ikki BIR XIL so'rov -> IKKI job (kutilgan xatti-harakat).

    Idempotentlik IXTIYORIY: kalitsiz `POST /jobs` har safar yangi job
    yaratadi. Bu ataylab — bir xil kodni ikki marta bajarish mijozning
    qonuniy ehtiyoji (masalan ayni hisobotni qayta yuborish). Takrorlanishdan
    himoya kerak bo'lsa mijoz kalit yuborishi kerak (SDK'lar buni avtomatik
    qiladi).
    """
    first = await client.post(f"{api_prefix}/jobs", headers=auth_headers, json=_body())
    second = await client.post(f"{api_prefix}/jobs", headers=auth_headers, json=_body())

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert first.json()["id"] != second.json()["id"]
    assert first.json()["idempotency_key"] is None
    assert second.json()["idempotency_key"] is None

    assert await count_jobs(user.id) == 2
    queued = await fake_redis.lrange(RedisKeys.queue("normal"), 0, -1)
    assert sorted(queued) == sorted(
        [f"normal:{first.json()['id']}", f"normal:{second.json()['id']}"]
    )


# ---------------------------------------------------------------------------
# 6. Yaroqsiz kalit — middleware darajasida
# ---------------------------------------------------------------------------


async def test_malformed_key_is_rejected_before_database(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    count_jobs: Callable[..., Awaitable[int]],
) -> None:
    """Qisqa yoki noto'g'ri belgili kalit -> 400, DB'ga TEGILMAYDI.

    `IdempotencyMiddleware` kalitni DB sessiyasi ochilishidan OLDIN
    tekshiradi: kalit log'ga va Redis kalitiga tushadi, shuning uchun
    bo'shliq va boshqaruv belgilari o'tmasligi kerak.
    """
    too_short = await client.post(
        f"{api_prefix}/jobs", headers=_with_key(auth_headers, "qisqa"), json=_body()
    )
    assert too_short.status_code == 400, too_short.text
    assert too_short.json()["error"]["details"]["header"] == HEADER_IDEMPOTENCY_KEY

    bad_chars = await client.post(
        f"{api_prefix}/jobs",
        headers=_with_key(auth_headers, "yaroqsiz kalit*"),
        json=_body(),
    )
    assert bad_chars.status_code == 400, bad_chars.text
    assert bad_chars.json()["error"]["details"]["header"] == HEADER_IDEMPOTENCY_KEY

    assert await count_jobs() == 0


__all__ = [
    "ACCEPTED_CODES",
    "IDEMPOTENT_CODE",
    "KEY_AFTER_FINISH",
    "KEY_PARALLEL",
    "KEY_SHARED",
    "PARALLEL_REQUESTS",
    "test_malformed_key_is_rejected_before_database",
    "test_parallel_requests_with_same_key_create_one_job",
    "test_requests_without_key_create_separate_jobs",
    "test_same_key_after_completion_returns_finished_job",
    "test_same_key_for_different_users_is_independent",
    "test_same_key_with_different_body_conflicts",
]
