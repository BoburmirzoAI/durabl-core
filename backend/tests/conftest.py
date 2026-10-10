"""Durabl — testlar uchun umumiy fixture'lar (CONTRACTS §11).

## Nega muhit o'zgaruvchilari modul BOSHIDA qo'yiladi

`app/config.py` dagi `settings` obyekti IMPORT paytida yasaladi va qolgan
modullar uni `from app.config import settings` bilan O'ZI ga bog'lab oladi.
Shuning uchun `reload_settings()` ni keyin chaqirish foydasiz — eski obyekt
boshqa modullarda qolib ketadi. Yechim: `os.environ` ni `app.*` dan BIRINCHI
import bo'lishidan OLDIN to'ldirish. Pytest `conftest.py` ni test
modullaridan oldin import qiladi, ya'ni bu yer yagona to'g'ri joy
(CONTRACTS §11 shuni ochiq ruxsat beradi).

## Nega `RATE_LIMIT_ENABLED=false`

Anonim limit daqiqada 20 so'rov, FREE reja 30. Bitta integratsiya testi
o'nlab so'rov yuboradi, ya'ni limit yoqilgan holda testlar bir-birini 429
bilan yiqitardi. Limiterning O'ZI `test_middleware.py` da `monkeypatch`
bilan yoqib tekshiriladi.

## Sessiya va ilova chegarasi

SQLite xotira bazasi `StaticPool` bilan BITTA ulanishda yashaydi, ya'ni
`db_session` va HTTP so'rovining sessiyasi AYNI ulanishni baham ko'radi.
Shuning uchun `db_session` ga yozgandan keyin `commit()` qilish SHART —
aks holda tranzaksiya ochiq qolib, HTTP so'rovi kutib qoladi.

## Nega `test_engine` SESSIYA emas, FUNKSIYA darajasida

Shartnomada sessiya darajasidagi engine + har test uchun nested savepoint
ko'zda tutilgan edi. Amalda bu yo'l BU loyihada ishlamaydi: `StaticPool`
bitta DBAPI ulanishini qaytaradi, ya'ni `db_session` ning tashqi
tranzaksiyasi AYNI ulanishda ochiq turganda ilovaning o'z sessiyasi
(`get_db` -> `get_sessionmaker()`) shu ulanishni band holatda topadi va
HTTP so'rovi kutib qoladi.

Shuning uchun har test O'Z xotira bazasini oladi: `create_engine()` +
`init_db(create_all=True)` — SQLite'da bu millisekundlar (795 birlik test
~2 soniyada o'tadi), izolyatsiya esa savepoint'dan ham KUCHLIROQ, chunki
testlar orasida umuman umumiy holat qolmaydi.

## Fixture'lar xaritasi

Infratuzilma: `test_engine`, `db_session`, `fake_redis`, `app`, `client`.
Foydalanuvchilar: `user`, `admin_user`, `other_user`.
Kirish: `auth_headers`, `admin_headers`, `other_user_headers`,
`api_key` (-> `(ApiKey, xom_kalit)`), `api_key_headers`.
Ma'lumot: `job_factory` (chaqirilishi mumkin), `api_prefix`, `frozen_time`.

`anyio_backend` QO'SHILMAGAN: `pyproject.toml` da `asyncio_mode = "auto"`,
ya'ni `async def test_*` funksiyalari marker'siz ishlaydi.
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

# --- Muhit: `app.*` importidan OLDIN -------------------------------------
os.environ.update(
    ENV="test",
    DATABASE_URL="sqlite+aiosqlite:///:memory:",
    REDIS_FAKE="true",
    BCRYPT_ROUNDS="4",
    SANDBOX_ENABLED="false",
    SECRET_KEY="test-secret-key-at-least-32-chars-long",
    RATE_LIMIT_ENABLED="false",
    METRICS_ENABLED="true",
    NOTIFICATIONS_ENABLED="false",
    BOOTSTRAP_ADMIN_EMAIL="",
    BOOTSTRAP_ADMIN_PASSWORD="",
)

import fakeredis.aioredis
import httpx
import pytest
from app.config import settings
from app.constants import HEADER_API_KEY, Runtime
from app.database import (
    close_db,
    create_engine,
    get_db,
    get_sessionmaker,
    init_db,
    set_engine,
)
from app.main import create_app
from app.models.job import Job
from app.models.user import User
from app.redis_client import close_redis, set_redis
from app.repositories.subscription_repo import SubscriptionRepository
from app.schemas.api_key import ApiKeyCreate
from app.services.auth_service import AuthService
from app.utils.security import create_access_token, hash_password
from app.utils.time_utils import utcnow
from freezegun import freeze_time
from sqlalchemy import func, select

from tests.factories import make_job, make_user

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
    from pathlib import Path

    from app.models.api_key import ApiKey
    from fastapi import FastAPI
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

#: `user`/`admin_user`/`other_user` fixture'lari uchun yagona parol.
#: Parol siyosatini qanoatlantiradi (8+ belgi, harf va raqam).
TEST_PASSWORD = "Parol12345"

#: Testlarda yuborilgan standart kod — `LocalRunner` da haqiqatan bajariladi.
TEST_CODE = "def main(payload):\n    return {'ok': True}\n"

#: `frozen_time` fixture'i vaqtni ayni shu lahzaga muzlatadi.
#: Qiymat ataylab qat'iy: `day_key()`/`month_key()` kabi funksiyalar natijasi
#: testda hisoblanmasdan, ko'z bilan tekshiriladigan matn bo'lib qoladi.
FROZEN_INSTANT = datetime(2026, 10, 4, 12, 30, 45, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Infratuzilma
# ---------------------------------------------------------------------------


@pytest.fixture
async def test_engine() -> AsyncIterator[Any]:
    """Har test uchun toza SQLite xotira bazasi.

    `create_engine()` ataylab ishlatiladi (`create_async_engine` emas):
    u `PRAGMA foreign_keys=ON` tinglovchisini ham ulaydi, ya'ni
    `ON DELETE CASCADE` testda ham ishlaydi.
    """
    engine = create_engine()
    set_engine(engine)
    await init_db(create_all=True)
    try:
        yield engine
    finally:
        await close_db()
        set_engine(None)


@pytest.fixture
async def fake_redis() -> AsyncIterator[Redis]:
    """`fakeredis` klienti — `app.redis_client` global nusxasi sifatida.

    `fakeredis[lua]` o'rnatilgani uchun `queue_service`/`reliability_service`
    ning Lua skriptlari HAQIQATAN bajariladi (zaxira yo'lga tushmaydi).
    """
    client: Any = fakeredis.aioredis.FakeRedis(decode_responses=True)
    set_redis(client)
    try:
        yield client
    finally:
        await client.flushall()
        await close_redis()
        set_redis(None)


@pytest.fixture
async def db_session(test_engine: Any) -> AsyncIterator[AsyncSession]:
    """Test uchun DB sessiyasi (ilova sessiyasi bilan AYNI engine)."""
    factory = get_sessionmaker()
    async with factory() as session:
        yield session


@pytest.fixture
def app(test_engine: Any, fake_redis: Redis) -> FastAPI:
    """Har test uchun YANGI ilova nusxasi.

    `app.main.app` global nusxasi import paytida yasalgani uchun eski
    sozlamalarni ushlab qolishi mumkin — shu sababli `create_app()`
    qaytadan chaqiriladi.
    """
    return create_app()


@pytest.fixture
async def client(app: FastAPI, db_session: AsyncSession) -> AsyncIterator[httpx.AsyncClient]:
    """HTTP mijoz — ASGI transport orqali, tarmoqqa chiqmasdan.

    `raise_app_exceptions=False` SHART: aks holda tutilmagan istisno
    testga qaytib keladi va 500 handler'ini tekshirish imkonsiz bo'ladi.
    ASGI lifespan ISHGA TUSHMAYDI — sxemani `test_engine` yaratadi.

    `get_db` dependency `db_session` ga bog'lanadi, ya'ni test va so'rov
    AYNI sessiyani baham ko'radi. Buning ikki foydasi bor:

    * fixture'da yozilgan yozuv so'rovga DARHOL ko'rinadi (`StaticPool`
      bitta ulanishni qaytargani uchun ikki alohida sessiya bir-birini
      bloklab qo'yishi mumkin edi);
    * so'rov yaratgan yozuvni test `db_session` orqali tekshira oladi.

    Xato bo'lsa `get_db` ning o'zidagi kabi `rollback()` qilinadi — aks
    holda sessiya buzilgan tranzaksiyada qolib, keyingi so'rov yiqilardi.
    """

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        """`get_db` ning test varianti — mavjud sessiyani qaytaradi."""
        try:
            yield db_session
        except Exception:
            await db_session.rollback()
            raise

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
            yield http_client
    finally:
        app.dependency_overrides.clear()


@dataclass(frozen=True, slots=True)
class ParallelEnv:
    """`parallel_client` fixture'i qaytaradigan to'plam."""

    #: HTTP mijoz — har so'rov O'Z DB sessiyasini oladi.
    client: httpx.AsyncClient
    #: So'rovlar egasi (FREE reja).
    user: User
    #: `user` uchun JWT header'i.
    headers: dict[str, str]
    #: `jobs` jadvalidagi qatorlarni sanaydi (ixtiyoriy ravishda egasi bo'yicha).
    count_jobs: Callable[..., Awaitable[int]]


@pytest.fixture
async def parallel_client(
    tmp_path: Path,
    fake_redis: Redis,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[ParallelEnv]:
    """HAQIQIY parallel HTTP so'rovlar uchun muhit.

    Standart `client` fixture'i `get_db` ni BITTA `db_session` ga bog'laydi —
    bu testlarning ko'pchiligi uchun qulay, lekin `asyncio.gather()` bilan
    bir vaqtda yuborilgan so'rovlar uchun YARAMAYDI: bitta `AsyncSession` ni
    parallel ishlatish SQLAlchemy'da taqiqlangan va `MissingGreenlet` beradi.
    Ya'ni bu ilova xatosi emas, test infratuzilmasining chegarasi.

    Shuning uchun bu fixture ikki narsani boshqacha qiladi:

    * `:memory:` o'rniga FAYL bazasini ishlatadi. `create_engine()` fayl
      bazasiga `NullPool` beradi, ya'ni har sessiya O'Z ulanishini oladi;
      `:memory:` da esa `StaticPool` BITTA ulanishni qaytarardi va parallel
      kursorlar yana bir-birini buzardi.
    * `get_db` ni OVERRIDE QILMAYDI — ilova haqiqiy dependency bilan, aynan
      production'dagi kabi, har so'rov uchun alohida sessiya bilan ishlaydi.

    `monkeypatch` `settings.DATABASE_URL` ni test oxirida o'zi tiklaydi.
    """
    monkeypatch.setattr(
        settings, "DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'durabl-parallel.db'}"
    )
    engine = create_engine()
    set_engine(engine)
    await init_db(create_all=True)

    factory = get_sessionmaker()
    async with factory() as session:
        owner = await _persist_user(
            session, email="parallel@durabl.test", full_name="Parallel User"
        )

    async def count_jobs(user_id: Any = None) -> int:
        """Qatorlarni QISQA umrli sessiyada sanaydi (ilovaning holatidan mustaqil)."""
        stmt = select(func.count()).select_from(Job)
        if user_id is not None:
            stmt = stmt.where(
                Job.user_id
                == (user_id if isinstance(user_id, uuid.UUID) else uuid.UUID(str(user_id)))
            )
        async with get_sessionmaker()() as counting_session:
            return int(await counting_session.scalar(stmt) or 0)

    transport = httpx.ASGITransport(app=create_app(), raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http_client:
            yield ParallelEnv(
                client=http_client,
                user=owner,
                headers={"Authorization": f"Bearer {create_access_token(owner.id)}"},
                count_jobs=count_jobs,
            )
    finally:
        await close_db()
        set_engine(None)


# ---------------------------------------------------------------------------
# Foydalanuvchilar
# ---------------------------------------------------------------------------


async def _persist_user(session: AsyncSession, **overrides: Any) -> User:
    """Foydalanuvchini FREE obunasi bilan yaratadi va commit qiladi."""
    user = make_user(hashed_password=hash_password(TEST_PASSWORD), **overrides)
    session.add(user)
    await session.flush()
    await SubscriptionRepository(session).ensure_for_user(user.id)
    await session.commit()
    return user


@pytest.fixture
async def user(db_session: AsyncSession) -> User:
    """Oddiy faol foydalanuvchi (FREE reja)."""
    return await _persist_user(db_session, email="user@durabl.test", full_name="Test User")


@pytest.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """Administrator huquqli foydalanuvchi."""
    return await _persist_user(
        db_session, email="admin@durabl.test", full_name="Test Admin", is_admin=True
    )


@pytest.fixture
async def other_user(db_session: AsyncSession) -> User:
    """Begona foydalanuvchi — izolyatsiya (404) testlari uchun."""
    return await _persist_user(db_session, email="other@durabl.test", full_name="Other User")


# ---------------------------------------------------------------------------
# Autentifikatsiya header'lari
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_headers(user: User) -> dict[str, str]:
    """`user` uchun JWT header'i."""
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture
def admin_headers(admin_user: User) -> dict[str, str]:
    """`admin_user` uchun JWT header'i."""
    return {"Authorization": f"Bearer {create_access_token(admin_user.id)}"}


@pytest.fixture
def other_user_headers(other_user: User) -> dict[str, str]:
    """`other_user` uchun JWT header'i — begona foydalanuvchi so'rovlari uchun."""
    return {"Authorization": f"Bearer {create_access_token(other_user.id)}"}


@pytest.fixture
async def api_key(db_session: AsyncSession, user: User) -> tuple[ApiKey, str]:
    """`user` uchun API kalit — `(model, xom_kalit)` juftligi.

    Xom kalit DB'da SAQLANMAYDI (faqat SHA-256 hash), shuning uchun uni
    `AuthService.create_api_key()` qaytargan lahzada ushlab qolish kerak —
    keyin tiklash imkonsiz.
    """
    created, raw = await AuthService(db_session).create_api_key(
        user, ApiKeyCreate(name="test-kalit")
    )
    await db_session.commit()
    return created, raw


@pytest.fixture
def api_key_headers(api_key: tuple[ApiKey, str]) -> dict[str, str]:
    """`user` uchun `X-API-Key` header'i."""
    return {HEADER_API_KEY: api_key[1]}


# ---------------------------------------------------------------------------
# Job fabrikasi
# ---------------------------------------------------------------------------


@pytest.fixture
async def job_factory(db_session: AsyncSession, user: User) -> Callable[..., Awaitable[Job]]:
    """DB'ga bevosita job yozadigan fabrika (navbatga TEGMAYDI).

    Navbat va holat o'tishlari kerak bo'lsa `POST /jobs` yoki
    `JobService.submit()` ishlatiladi; bu fabrika esa ro'yxat, filtr va
    sahifalash testlari uchun tez yo'l.

    Chaqirish shakli: `await job_factory(owner=user, status=..., **fields)`.
    `owner` berilmasa `user` fixture'i egasi bo'ladi.
    """

    async def factory(owner: User | None = None, **fields: Any) -> Job:
        job = make_job(user_id=(owner or user).id, **fields)
        db_session.add(job)
        await db_session.flush()
        await db_session.commit()
        return job

    return factory


# ---------------------------------------------------------------------------
# Umumiy yordamchilar (test modullari import qilishi mumkin)
# ---------------------------------------------------------------------------


@pytest.fixture
def api_prefix() -> str:
    """`settings.API_V1_PREFIX` ning qisqartmasi."""
    return settings.API_V1_PREFIX


@pytest.fixture
def frozen_time() -> Iterator[Any]:
    """Vaqtni `FROZEN_INSTANT` lahzasida muzlatadi (`freezegun`).

    Qaytgan obyekt — `freezegun` ning `FrozenDateTimeFactory` si:
    `frozen_time.tick(seconds)` yoki `frozen_time.move_to(...)` bilan vaqtni
    qo'lda surish mumkin.

    **DIQQAT:** `freezegun` `time.monotonic()` ni ham almashtiradi, ya'ni
    muzlatilgan vaqtda `asyncio.sleep()` HECH QACHON tugamaydi. Shu sababli
    bu fixture faqat vaqt hisob-kitobini (`day_key`, `is_expired`, JWT
    muddati) tekshiradigan testlarda ishlatiladi — kutish talab qiladigan
    testlarda emas.
    """
    with freeze_time(FROZEN_INSTANT) as frozen:
        yield frozen


__all__ = [
    "FROZEN_INSTANT",
    "TEST_CODE",
    "TEST_PASSWORD",
    "ParallelEnv",
    "Runtime",
    "admin_headers",
    "admin_user",
    "api_key",
    "api_key_headers",
    "api_prefix",
    "app",
    "auth_headers",
    "client",
    "db_session",
    "fake_redis",
    "frozen_time",
    "job_factory",
    "other_user",
    "other_user_headers",
    "parallel_client",
    "test_engine",
    "user",
    "utcnow",
    "uuid",
]
