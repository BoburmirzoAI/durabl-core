"""Durabl — Faza 1B da qo'shilgan billing endpointlari.

| Metod | Yo'l | Nima beradi |
|---|---|---|
| `GET` | `/billing/invoices` | oylik hisob-kitoblar |
| `GET` | `/billing/projection` | oy oxirigacha prognoz |
| `GET` | `/billing/runtime-costs` | runtime bo'yicha xarajat |
| `GET` | `/billing/usage/{key}` | kvota o'lchagichi tafsiloti |
| `POST` | `/billing/estimate` | narx kalkulyatori |
| `GET` | `/billing/plans/{plan}/preview` | reja almashtirish oqibati |

## Nega "yo'q ma'lumot" alohida tekshiriladi

Loyihada to'lov tizimi YO'Q: `stripe`/`paddle` integratsiyasi,
`invoices` jadvali va PDF generatsiyasi mavjud emas. Shuning uchun
`status` va `pdf_url` `null` qaytadi.

Testlar shuni QOTIRADI: kimdir "bo'sh ko'rinmasin" deb `status: "paid"`
qo'ysa, test yiqiladi. Mijozga to'lov o'tgani haqida yolg'on xabar
berish — eng yomon turdagi xato.

## Overage har doim nol

Durabl kvotaga yetganda job'ni RAD ETADI (`check_quota` ->
`QuotaExceededError`), qo'shimcha hisob yozmaydi. Ya'ni "limitdan
oshib ishlatish" texnik jihatdan mavjud emas.

Shu sababli `overage_usd` har doim 0 va `will_exceed` "qo'shimcha pul
to'laysiz" emas, "job'lar rad etila boshlaydi" degani. Testlar bu
ma'noni ham qotiradi.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from app.constants import PLAN_LIMITS, PlanType, Runtime
from app.models.usage_record import UsageRecord
from app.services.billing_service import QUOTA_COMPUTE_SECONDS, QUOTA_MONTHLY_JOBS
from app.utils.time_utils import month_key, utcnow

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from collections.abc import Awaitable, Callable

    import httpx
    from app.models.job import Job
    from app.models.user import User
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def seed_usage(
    session: AsyncSession,
    user: User,
    *,
    jobs: int = 100,
    seconds: float = 250.0,
    period: str | None = None,
) -> None:
    """Joriy (yoki berilgan) davr uchun foydalanish yozuvi yasaydi."""
    session.add(
        UsageRecord(
            user_id=user.id,
            period=period or month_key(),
            job_count=jobs,
            success_count=jobs,
            failed_count=0,
            execution_seconds=seconds,
            recorded_at=utcnow(),
        )
    )
    await session.commit()


# ---------------------------------------------------------------------------
# GET /billing/invoices
# ---------------------------------------------------------------------------


async def test_hisob_kitob_haqiqiy_foydalanishdan_hisoblanadi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    user: User,
) -> None:
    """Summa reja narxidan, foydalanish esa `usage_records` dan keladi."""
    await seed_usage(db_session, user, jobs=42, seconds=120.5)

    response = await client.get(f"{api_prefix}/billing/invoices", headers=auth_headers)

    assert response.status_code == 200, response.text
    rows = response.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["job_count"] == 42
    assert row["execution_seconds"] == pytest.approx(120.5)
    # FREE rejada narx 0 — bu haqiqiy qiymat, to'qilgan emas.
    assert row["amount_usd"] == PLAN_LIMITS[PlanType.FREE].price_usd_month
    assert row["period"] == month_key()


async def test_tolov_holati_TOQIB_CHIQARILMAYDI(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    user: User,
) -> None:
    """`status` va `pdf_url` `null` — to'lov tizimi ulanmagan.

    "paid" deb qaytarish mijozga to'lov o'tgani haqida YOLG'ON xabar
    berardi. `payments_enabled=False` sababini ochiq aytadi.
    """
    await seed_usage(db_session, user)

    row = (await client.get(f"{api_prefix}/billing/invoices", headers=auth_headers)).json()[0]

    assert row["status"] is None
    assert row["pdf_url"] is None
    assert row["payments_enabled"] is False
    # O'tgan davrlarning rejasi ham saqlanmaydi — bu ham ochiq aytiladi.
    assert row["plan_history_tracked"] is False


async def test_overage_har_doim_nol(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    user: User,
) -> None:
    """Limitdan oshish narxi yo'q — Durabl kvotada BLOKLAYDI."""
    # FREE chegarasi 1000; 5000 job — ya'ni "oshib ketgan" holat.
    await seed_usage(db_session, user, jobs=5_000)

    row = (await client.get(f"{api_prefix}/billing/invoices", headers=auth_headers)).json()[0]

    assert row["overage_usd"] == 0.0


# ---------------------------------------------------------------------------
# GET /billing/projection
# ---------------------------------------------------------------------------


async def test_prognoz_joriy_tezlikdan_hisoblanadi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    user: User,
) -> None:
    """Prognoz kunlik tezlikni oy oxirigacha davom ettiradi."""
    await seed_usage(db_session, user, jobs=300)

    body = (await client.get(f"{api_prefix}/billing/projection", headers=auth_headers)).json()

    assert body["current_jobs"] == 300
    assert body["monthly_limit"] == PLAN_LIMITS[PlanType.FREE].monthly_jobs
    assert body["days_total"] >= 28
    assert body["jobs_per_day"] > 0
    # Prognoz joriy qiymatdan kam bo'lishi mumkin emas.
    assert body["projected_jobs"] >= body["current_jobs"]


async def test_will_exceed_limitga_yetishni_bildiradi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    user: User,
) -> None:
    """`will_exceed` — "job'lar rad etila boshlaydi", pul emas.

    FREE chegarasi 1000. 2000 job allaqachon yuborilgan bo'lsa,
    prognoz albatta oshadi — lekin `overage_usd` baribir 0, chunki
    qo'shimcha hisob yozilmaydi.
    """
    await seed_usage(db_session, user, jobs=2_000)

    body = (await client.get(f"{api_prefix}/billing/projection", headers=auth_headers)).json()

    assert body["will_exceed"] is True
    assert body["overage_usd"] == 0.0


# ---------------------------------------------------------------------------
# GET /billing/runtime-costs
# ---------------------------------------------------------------------------


async def test_xarajat_bajarish_soniyalari_nisbatida_taqsimlanadi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Ulushlar soniyalar nisbatiga mos va jami 100% ga yaqin."""
    await job_factory(runtime=Runtime.PYTHON, duration_ms=3_000)
    await job_factory(runtime=Runtime.PYTHON, duration_ms=1_000)
    await job_factory(runtime=Runtime.NODE, duration_ms=4_000)

    rows = (await client.get(f"{api_prefix}/billing/runtime-costs", headers=auth_headers)).json()

    by_runtime = {row["runtime"]: row for row in rows}
    assert by_runtime[Runtime.PYTHON.value]["jobs"] == 2
    assert by_runtime[Runtime.NODE.value]["jobs"] == 1
    # Python 4s, Node 4s -> 50/50.
    assert by_runtime[Runtime.PYTHON.value]["percent"] == pytest.approx(50.0, abs=0.5)
    assert sum(row["percent"] for row in rows) == pytest.approx(100.0, abs=0.5)


async def test_job_bolmasa_taqsim_bosh(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
) -> None:
    """Job yo'q — bo'sh ro'yxat (teng bo'lib berish noto'g'ri xulosa berardi)."""
    response = await client.get(f"{api_prefix}/billing/runtime-costs", headers=auth_headers)

    assert response.status_code == 200
    assert response.json() == []


# ---------------------------------------------------------------------------
# GET /billing/usage/{key}
# ---------------------------------------------------------------------------


async def test_kvota_tafsiloti_uch_savolga_javob_beradi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    user: User,
) -> None:
    """NIMA hisoblanadi, KIM sarflayapti, limitda NIMA bo'ladi."""
    await seed_usage(db_session, user, jobs=820)

    body = (
        await client.get(f"{api_prefix}/billing/usage/{QUOTA_MONTHLY_JOBS}", headers=auth_headers)
    ).json()

    assert body["key"] == QUOTA_MONTHLY_JOBS
    assert body["current"] == 820
    assert body["limit"] == PLAN_LIMITS[PlanType.FREE].monthly_jobs
    assert body["percent"] == pytest.approx(82.0, abs=0.1)
    # Uch savolga javob bo'sh BO'LMASLIGI kerak.
    assert body["counted"]
    assert body["at_limit"]
    assert len(body["tips"]) >= 2
    assert body["resets_at"] is not None


async def test_kvota_oshirib_bolmasligi_korsatiladi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    user: User,
) -> None:
    """`overage_label` `null` — shartnoma "oshirib bo'lmaydi" deb ta'riflaydi."""
    await seed_usage(db_session, user)

    body = (
        await client.get(f"{api_prefix}/billing/usage/{QUOTA_MONTHLY_JOBS}", headers=auth_headers)
    ).json()

    assert body["overage_label"] is None


async def test_saqlanmagan_kesimlar_TOQIB_CHIQARILMAYDI(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    user: User,
) -> None:
    """`daily` va `by_api_key` bo'sh, sababi ochiq aytiladi.

    * `daily` — `usage_records` OYLIK agregat, kunlik kesim yo'q;
    * `by_api_key` — `api_key_usage` jadvali hali yozilmagan.

    Taxminiy qiymat qo'yish mijozni chalg'itardi.
    """
    await seed_usage(db_session, user)

    body = (
        await client.get(f"{api_prefix}/billing/usage/{QUOTA_MONTHLY_JOBS}", headers=auth_headers)
    ).json()

    assert body["daily"] == []
    assert body["daily_tracked"] is False
    assert body["by_api_key"] == []
    assert body["by_api_key_tracked"] is False


async def test_compute_seconds_olchagichi_ham_ishlaydi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    user: User,
) -> None:
    """Ikkinchi qo'llanadigan kalit — bajarish soniyalari."""
    await seed_usage(db_session, user, seconds=500.0)

    body = (
        await client.get(
            f"{api_prefix}/billing/usage/{QUOTA_COMPUTE_SECONDS}", headers=auth_headers
        )
    ).json()

    assert body["key"] == QUOTA_COMPUTE_SECONDS
    assert body["current"] == pytest.approx(500.0)
    assert "nazariy" in body["limit_label"]


@pytest.mark.parametrize("key", ["max_concurrent_jobs", "requests_per_minute", "nomalum"])
async def test_qollanmaydigan_olchagich_422(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    key: str,
) -> None:
    """Tarixi saqlanmaydigan o'lchagich uchun 422, jim bo'sh javob EMAS.

    `max_concurrent_jobs` va `requests_per_minute` Redis'da lahzalik
    qiymat sifatida yashaydi — "kunlar bo'yicha" tahlil yasash uchun
    ma'lumot yo'q. Bo'sh javob qaytarish mijozni chalg'itardi.
    """
    response = await client.get(f"{api_prefix}/billing/usage/{key}", headers=auth_headers)

    assert response.status_code == 422, response.text
    assert "allowed" in response.text


# ---------------------------------------------------------------------------
# POST /billing/estimate
# ---------------------------------------------------------------------------


async def test_kalkulyator_har_reja_uchun_narx_beradi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
) -> None:
    """To'rtta reja uchun narx va sig'ishlik qaytadi."""
    response = await client.post(
        f"{api_prefix}/billing/estimate",
        headers=auth_headers,
        json={"monthly_jobs": 30_000, "avg_duration_ms": 2_000},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["plans"]) == len(PLAN_LIMITS)
    assert body["compute_seconds"] == pytest.approx(60_000.0)
    # 30 000 job: FREE (1 000) sig'maydi, STARTER (50 000) sig'adi.
    plans = {item["plan"]: item for item in body["plans"]}
    assert plans[PlanType.FREE.value]["fits"] is False
    assert plans[PlanType.STARTER.value]["fits"] is True


async def test_tavsiya_FAQAT_sigadigan_rejalardan_tanlanadi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
) -> None:
    """Arzon, lekin sig'maydigan reja TAVSIYA QILINMAYDI.

    Durabl kvotada bloklaydi, ya'ni sig'maydigan reja arzon bo'lsa ham
    mijozga yaramaydi — ish shunchaki bajarilmaydi.
    """
    body = (
        await client.post(
            f"{api_prefix}/billing/estimate",
            headers=auth_headers,
            json={"monthly_jobs": 30_000, "avg_duration_ms": 1_000},
        )
    ).json()

    # FREE eng arzon (0$), lekin 30 000 job unga sig'maydi.
    assert body["recommended"] == PlanType.STARTER.value


async def test_hech_bir_rejaga_sigmasa_eng_kattasi_tavsiya_qilinadi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
) -> None:
    """Hajm hamma rejadan oshsa — ENTERPRISE (eng katta chegara)."""
    body = (
        await client.post(
            f"{api_prefix}/billing/estimate",
            headers=auth_headers,
            json={"monthly_jobs": 50_000_000, "avg_duration_ms": 100},
        )
    ).json()

    assert body["recommended"] == PlanType.ENTERPRISE.value
    assert all(item["fits"] is False for item in body["plans"])
    # `over_by` necha barobar oshganini aytadi.
    assert body["plans"][0]["over_by"] > 1


@pytest.mark.parametrize(
    "payload",
    [
        {"monthly_jobs": -1, "avg_duration_ms": 100},
        {"monthly_jobs": 10, "avg_duration_ms": -5},
        {"monthly_jobs": 10**12, "avg_duration_ms": 100},
    ],
)
async def test_chegaradan_tashqari_qiymat_422(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    payload: dict[str, Any],
) -> None:
    """Chegara SHART: cheksiz qiymat `compute_seconds` ni ma'nosiz qiladi."""
    response = await client.post(
        f"{api_prefix}/billing/estimate", headers=auth_headers, json=payload
    )

    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# GET /billing/plans/{plan}/preview
# ---------------------------------------------------------------------------


async def test_reja_oshirish_yonalishi_va_farqi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
) -> None:
    """FREE -> PRO: `upgrade`, narx farqi musbat, solishtiruv jadvali bor."""
    body = (
        await client.get(
            f"{api_prefix}/billing/plans/{PlanType.PRO.value}/preview", headers=auth_headers
        )
    ).json()

    assert body["from"] == PlanType.FREE.value
    assert body["to"] == PlanType.PRO.value
    assert body["direction"] == "upgrade"
    assert body["price_delta_usd"] == pytest.approx(PLAN_LIMITS[PlanType.PRO].price_usd_month)
    assert len(body["rows"]) >= 5
    # Oylik job chegarasi oshadi -> mijoz uchun `better`.
    jobs_row = next(row for row in body["rows"] if "job" in row["label"].lower())
    assert jobs_row["direction"] == "better"


async def test_ayni_reja_same_yonalishi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
) -> None:
    """Ayni rejaga o'tish — `same`, farq nol."""
    body = (
        await client.get(
            f"{api_prefix}/billing/plans/{PlanType.FREE.value}/preview", headers=auth_headers
        )
    ).json()

    assert body["direction"] == "same"
    assert body["price_delta_usd"] == 0.0
    assert body["blockers"] == []


async def test_pastga_tushishda_TOSIQ_ogohlantiradi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    user: User,
) -> None:
    """Joriy sarf yangi rejadan oshsa — `blockers` oldindan ogohlantiradi.

    Bu endpointning asosiy qiymati: busiz mijoz rejani pasaytirib,
    keyin "nega hamma narsa buzildi?" degan savolda qolardi.
    """
    # FREE chegarasi 1000; 5000 job yuborilgan.
    await seed_usage(db_session, user, jobs=5_000)

    body = (
        await client.get(
            f"{api_prefix}/billing/plans/{PlanType.FREE.value}/preview", headers=auth_headers
        )
    ).json()

    assert len(body["blockers"]) == 1
    assert "5,000" in body["blockers"][0]
    assert "rad etiladi" in body["blockers"][0]


async def test_qayta_hisob_nol_va_sababi_aytiladi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
) -> None:
    """`prorated_usd` 0 — to'lov tizimi yo'q, ya'ni qayta hisob ham yo'q."""
    body = (
        await client.get(
            f"{api_prefix}/billing/plans/{PlanType.STARTER.value}/preview",
            headers=auth_headers,
        )
    ).json()

    assert body["prorated_usd"] == 0.0
    assert body["payments_enabled"] is False


async def test_nomalum_reja_422(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
) -> None:
    """Noma'lum reja nomi — 422 (enum tekshiruvi)."""
    response = await client.get(f"{api_prefix}/billing/plans/nomalum/preview", headers=auth_headers)

    assert response.status_code == 422
