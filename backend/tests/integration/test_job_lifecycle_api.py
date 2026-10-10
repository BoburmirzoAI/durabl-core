"""Durabl — Faza 1B da qo'shilgan job endpointlari.

Qoplanadigan to'rtta yo'l:

| Metod | Yo'l | Nima beradi |
|---|---|---|
| `POST` | `/jobs/{id}/retry` | AYNI job'ni navbatga qaytaradi |
| `DELETE` | `/jobs/{id}` | yozuvni butunlay o'chiradi |
| `GET` | `/jobs/{id}/lease-history` | lease egallash/yo'qotish vaqt o'qi |
| `GET` | `/jobs/{id}/idempotency` | kalit, barmoq izi, muddat |

## Nega `retry` va `resubmit` farqi alohida tekshiriladi

Ikkisi tashqi ko'rinishda o'xshash, lekin ma'nosi boshqa:

* `retry` — ayni job (`id` o'zgarmaydi), tarix ustiga qo'shiladi;
* `resubmit` — yangi job, eskisi tegilmaydi.

Frontend mock'ida `retryJob()` `resubmitJob()` ni chaqiradi, ya'ni
shartnoma noaniq qolgan. `docs/TASKS.md` esa "AYNI job" deb yozadi va
bulk `retryJobs()` ham shunday ishlaydi. Shu testlar tanlangan ma'noni
QOTIRADI — aks holda keyinchalik kimdir ikkisini birlashtirib
qo'yishi mumkin.

## Nega `lease-history` va `idempotency` da "yo'q" ma'lumot tekshiriladi

Ikki endpoint frontend shartnomasida mavjud bo'lgan, lekin backend
SAQLAMAYDIGAN maydonlarga ega (`renewed` hodisalari, so'rovlar
jurnali). Ular to'qib chiqarilmaydi — `renewals_persisted=False` va
`requests_persisted=False` ochiq qaytariladi.

Testlar aynan shuni qotiradi: kimdir "bo'sh ko'rinmasin" deb taxminiy
qiymat qo'ysa, test yiqiladi. Ishonchlilikni sotayotgan mahsulot o'z
ma'lumotini to'qishi eng yomon xato bo'lardi.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from app.constants import FailureReason, JobStatus, LeaseEventKind
from app.models.execution import Execution
from app.utils.time_utils import seconds_from_now, utcnow

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    from collections.abc import Awaitable, Callable

    import httpx
    from app.models.job import Job
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# POST /jobs/{id}/retry
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("from_status", [JobStatus.FAILED, JobStatus.DEAD_LETTER])
async def test_retry_ayni_jobni_navbatga_qaytaradi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
    from_status: JobStatus,
) -> None:
    """`failed` va `dead_letter` dan qayta urinish mumkin — AYNI job."""
    job = await job_factory(
        status=from_status,
        exit_code=1,
        error="eski xato",
        failure_reason=FailureReason.NON_ZERO_EXIT,
        retry_count=2,
        finished_at=utcnow(),
    )

    response = await client.post(f"{api_prefix}/jobs/{job.id}/retry", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    # AYNI job — `id` o'zgarmaydi. Bu `resubmit` dan asosiy farq.
    assert body["id"] == str(job.id)
    assert body["status"] == JobStatus.QUEUED.value
    # Oldingi urinish natijasi tozalangan: mijoz yangi urinish
    # ketayotganda eski xatoni ko'rib turmasligi kerak.
    assert body["exit_code"] is None
    assert body["error"] is None
    assert body["failure_reason"] is None
    # `retry_count` esa SAQLANADI — u job'ning haqiqiy tarixi.
    assert body["retry_count"] == 2


@pytest.mark.parametrize("from_status", [JobStatus.SUCCESS, JobStatus.CANCELLED])
async def test_retry_tugagan_jobda_409(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
    from_status: JobStatus,
) -> None:
    """`success` va `cancelled` dan qayta urinish YO'Q.

    Qoida holat mashinasidan keladi (`JOB_STATUS_TRANSITIONS`), ya'ni
    ikki joyda yozilmaydi. Javobda `resubmit` taklif qilinadi.
    """
    job = await job_factory(status=from_status, finished_at=utcnow())

    response = await client.post(f"{api_prefix}/jobs/{job.id}/retry", headers=auth_headers)

    assert response.status_code == 409, response.text
    assert "resubmit" in response.text


async def test_retry_boshqa_foydalanuvchining_jobida_404(
    client: httpx.AsyncClient,
    api_prefix: str,
    other_user_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Begona job uchun 404 (403 EMAS) — resurs borligi oshkor qilinmaydi."""
    job = await job_factory(status=JobStatus.FAILED, finished_at=utcnow())

    response = await client.post(f"{api_prefix}/jobs/{job.id}/retry", headers=other_user_headers)

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /jobs/{id}
# ---------------------------------------------------------------------------


async def test_delete_tugagan_jobni_ochiradi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Tugagan job o'chiriladi va keyin 404 bo'ladi."""
    job = await job_factory(status=JobStatus.SUCCESS, finished_at=utcnow())

    deleted = await client.delete(f"{api_prefix}/jobs/{job.id}", headers=auth_headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json() == {"deleted": True}

    gone = await client.get(f"{api_prefix}/jobs/{job.id}", headers=auth_headers)
    assert gone.status_code == 404


@pytest.mark.parametrize(
    "from_status",
    [JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.RETRYING],
)
async def test_delete_tugamagan_jobda_409(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
    from_status: JobStatus,
) -> None:
    """Tugamagan job o'chirilmaydi — worker egasiz job ustida qolardi."""
    job = await job_factory(status=from_status)

    response = await client.delete(f"{api_prefix}/jobs/{job.id}", headers=auth_headers)

    assert response.status_code == 409, response.text
    assert "cancel" in response.text


async def test_delete_urinishlarni_ham_ochiradi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Bog'liq `executions` cascade bilan ketadi (DB darajasida)."""
    job = await job_factory(status=JobStatus.SUCCESS, finished_at=utcnow())
    db_session.add(
        Execution(job_id=job.id, attempt_number=1, status="success", started_at=utcnow())
    )
    await db_session.commit()
    job_id = job.id

    response = await client.delete(f"{api_prefix}/jobs/{job_id}", headers=auth_headers)
    assert response.status_code == 200

    db_session.expire_all()
    left = await client.get(f"{api_prefix}/executions?job_id={job_id}", headers=auth_headers)
    assert left.status_code == 200
    assert left.json()["items"] == []


# ---------------------------------------------------------------------------
# GET /jobs/{id}/lease-history
# ---------------------------------------------------------------------------


async def test_lease_history_egallash_va_bosatishni_korsatadi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Muvaffaqiyatli urinish -> `acquired` + `released`."""
    job = await job_factory(status=JobStatus.SUCCESS, finished_at=utcnow())
    started = utcnow()
    db_session.add(
        Execution(
            job_id=job.id,
            attempt_number=1,
            status="success",
            worker_id="worker-1",
            started_at=started,
            finished_at=started,
            lease_expires_at=seconds_from_now(15),
        )
    )
    await db_session.commit()

    response = await client.get(f"{api_prefix}/jobs/{job.id}/lease-history", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    kinds = [event["kind"] for event in body["events"]]
    assert kinds == [LeaseEventKind.ACQUIRED.value, LeaseEventKind.RELEASED.value]
    assert body["events"][0]["worker_id"] == "worker-1"
    assert body["events"][0]["attempt_number"] == 1
    # TTL va heartbeat sozlamadan keladi — to'qib chiqarilmaydi.
    assert body["ttl_seconds"] >= 1
    assert body["heartbeat_interval_seconds"] >= 1
    assert body["reassignments"] == 0


async def test_lease_history_yoqolgan_leaseni_sanaydi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`LEASE_LOST` -> `lost` hodisasi va `reassignments` oshadi.

    Bu Durabl'ning asosiy va'dasini ko'rinadigan qiladi: worker qulasa
    job boshqa worker'ga o'tadi va bu KO'RINADI.
    """
    job = await job_factory(status=JobStatus.SUCCESS, finished_at=utcnow())
    moment = utcnow()
    db_session.add_all(
        [
            Execution(
                job_id=job.id,
                attempt_number=1,
                status="failed",
                worker_id="worker-oldi-oldi",
                started_at=moment,
                finished_at=moment,
                failure_reason=FailureReason.LEASE_LOST,
            ),
            Execution(
                job_id=job.id,
                attempt_number=2,
                status="success",
                worker_id="worker-2",
                started_at=moment,
                finished_at=moment,
            ),
        ]
    )
    await db_session.commit()

    body = (
        await client.get(f"{api_prefix}/jobs/{job.id}/lease-history", headers=auth_headers)
    ).json()

    kinds = [event["kind"] for event in body["events"]]
    assert LeaseEventKind.LOST.value in kinds
    assert body["reassignments"] == 1


async def test_lease_history_renewed_TOQIB_CHIQARILMAYDI(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Heartbeat yangilanishlari saqlanmaydi — bu OCHIQ aytiladi.

    Uzoq ishlagan job uchun ham `total_renewals` 0 bo'ladi, chunki
    heartbeat ataylab DB'ga tegmaydi (`app/workers/heartbeat.py`).
    Davomiylikdan "hisoblab chiqarish" mumkin edi, lekin bu o'lchov
    emas, taxmin bo'lardi.

    `renewals_persisted=False` maydoni UI'ga "qayd etilmagan" deb
    ko'rsatish imkonini beradi — "0 marta yangilandi" degan YOLG'ON
    xabar o'rniga.
    """
    job = await job_factory(status=JobStatus.SUCCESS, finished_at=utcnow())
    moment = utcnow()
    db_session.add(
        Execution(
            job_id=job.id,
            attempt_number=1,
            status="success",
            worker_id="worker-1",
            started_at=moment,
            finished_at=moment,
            duration_ms=600_000,  # 10 daqiqa — ~120 heartbeat bo'lgan
        )
    )
    await db_session.commit()

    body = (
        await client.get(f"{api_prefix}/jobs/{job.id}/lease-history", headers=auth_headers)
    ).json()

    assert body["total_renewals"] == 0
    assert body["renewals_persisted"] is False
    assert LeaseEventKind.RENEWED.value not in [e["kind"] for e in body["events"]]


# ---------------------------------------------------------------------------
# GET /jobs/{id}/idempotency
# ---------------------------------------------------------------------------


async def test_idempotency_kalitsiz_job(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Kalit berilmagan — har so'rov yangi job yaratgan."""
    job = await job_factory(status=JobStatus.SUCCESS, finished_at=utcnow())

    body = (
        await client.get(f"{api_prefix}/jobs/{job.id}/idempotency", headers=auth_headers)
    ).json()

    assert body["key"] is None
    assert body["fingerprint"] is None
    assert body["was_deduplicated"] is False
    assert body["expires_at"] is None


async def test_idempotency_kalit_bilan_yuborilgan_job(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
) -> None:
    """Haqiqiy oqim: kalit bilan yuborilgan job uchun to'liq ma'lumot.

    Job HTTP orqali yuboriladi — ya'ni Redis yozuvi haqiqatan
    yaratiladi va `expires_at` TTL'dan hisoblanadi.
    """
    submitted = await client.post(
        f"{api_prefix}/jobs",
        headers={**auth_headers, "Idempotency-Key": "kalit-1-uzun"},
        json={"code": "print('salom')", "runtime": "python"},
    )
    assert submitted.status_code == 201, submitted.text
    job_id = submitted.json()["id"]

    body = (
        await client.get(f"{api_prefix}/jobs/{job_id}/idempotency", headers=auth_headers)
    ).json()

    assert body["key"] == "kalit-1-uzun"
    # Barmoq izi — SHA-256 hex.
    assert body["fingerprint"] is not None
    assert len(body["fingerprint"]) == 64
    # Redis yozuvi hamon shu job'ga ishora qiladi: takroriy so'rov
    # yangi job yaratmasdan shu job'ni oladi.
    assert body["was_deduplicated"] is True
    assert body["expires_at"] is not None


async def test_idempotency_sorovlar_tarixi_TOQIB_CHIQARILMAYDI(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
) -> None:
    """So'rovlar jurnali saqlanmaydi — bo'sh ro'yxat va ochiq belgi.

    Redis'da faqat JORIY yozuv bor (`state`, `job_id`, `fingerprint`),
    tarix emas. Ikki marta so'rov yuborilsa ham `requests` bo'sh
    qoladi — va `requests_persisted=False` buning sababini aytadi.
    """
    headers = {**auth_headers, "Idempotency-Key": "kalit-2-uzun"}
    body_json = {"code": "print('salom')", "runtime": "python"}

    first = await client.post(f"{api_prefix}/jobs", headers=headers, json=body_json)
    second = await client.post(f"{api_prefix}/jobs", headers=headers, json=body_json)
    assert first.status_code == 201
    # Takroriy so'rov — 200 va ayni job.
    assert second.status_code == 200

    body = (
        await client.get(
            f"{api_prefix}/jobs/{first.json()['id']}/idempotency", headers=auth_headers
        )
    ).json()

    assert body["requests"] == []
    assert body["requests_persisted"] is False


async def test_idempotency_boshqa_foydalanuvchida_404(
    client: httpx.AsyncClient,
    api_prefix: str,
    other_user_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Begona job uchun 404 — IDOR himoyasi barcha yangi yo'llarda ham."""
    job = await job_factory(status=JobStatus.SUCCESS, finished_at=utcnow())
    # ID ni OLDIN olib qo'yamiz: `client` ilovaning so'rovlari AYNI
    # `db_session` ni ishlatadi va commit'dan keyin obyekt eskiradi —
    # `job.id` ga qayta murojaat sinxron refresh'ni qo'zg'atib
    # `MissingGreenlet` beradi.
    job_id = job.id

    for path in ("idempotency", "lease-history"):
        response = await client.get(
            f"{api_prefix}/jobs/{job_id}/{path}", headers=other_user_headers
        )
        assert response.status_code == 404, path
