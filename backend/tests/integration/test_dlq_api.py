"""Durabl — `/dlq/*` endpointlarining integratsiya testlari.

## Nega yozuvlar `ReliabilityService.move_to_dlq()` bilan yaratiladi

`make_dlq_entry()` fabrikasi ham ishlardi, lekin u job'ning holatini
`DEAD_LETTER` ga O'TKAZMAYDI. `POST /dlq/{id}/retry` esa job holatini
tekshiradi, shuning uchun yozuv HAQIQIY yo'l bilan — servis orqali —
yaratiladi. Shu tufayli test "DLQ'ga tushish -> qayta urinish" zanjirini
butun holda tekshiradi.

## `/dlq/stats` yo'l tartibi — alohida test sababi

FastAPI yo'llarni E'LON TARTIBIDA solishtiradi. Agar `/dlq/{entry_id}`
`/dlq/stats` dan OLDIN e'lon qilinsa, `stats` matni `entry_id` deb o'qiladi
va UUID validatsiyasi 422 beradi. Shuning uchun `test_stats_route_wins`
ataylab alohida test: regressiya darhol ko'rinadi.

## Xato javobidan KEYIN ORM obyektiga murojaat qilmaslik

`get_db()` dependency'si istisno chiqqanda `session.rollback()` qiladi.
SQLite xotira bazasi `StaticPool` bilan BITTA ulanishda yashagani uchun bu
rollback `db_session` dagi obyektlarni ham "eskirgan" (expired) qilib
qo'yadi. Shundan keyin `job.id` kabi oddiy murojaat DB'ga SO'ROV yuborishga
urinadi va sinxron kontekstda `MissingGreenlet` beradi.

Shuning uchun qoida: 4xx/5xx qaytaradigan so'rovdan OLDIN kerakli
qiymatlar (`str(obj.id)`) oddiy o'zgaruvchiga ko'chiriladi. Kerak bo'lsa
`await db_session.refresh(obj)` ham ishlaydi, lekin identifikatorni
oldindan olish — ancha sodda.

## `DELETE /dlq/{id}` — "o'chirish" emas, "hal qilish"

Yozuv fizik o'chirilmaydi (`job_id` unique, aks holda job yana yiqilganda
tarix yo'qolardi) — `resolved=True` qo'yiladi va chuqurlikdan chiqadi.
Takroriy `DELETE` xato BERMAYDI (idempotent).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from app.constants import FailureReason, JobStatus
from app.services.reliability_service import ReliabilityService

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from collections.abc import Awaitable, Callable

    import httpx
    from app.models.dlq_entry import DlqEntry
    from app.models.job import Job
    from app.models.user import User
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def push_to_dlq(
    session: AsyncSession,
    job: Job,
    *,
    failure_reason: FailureReason = FailureReason.NON_ZERO_EXIT,
    error_text: str = "Kod 1 chiqish kodi bilan tugadi",
) -> DlqEntry:
    """Job'ni DLQ'ga tushiradi va yozuvni qaytaradi."""
    entry = await ReliabilityService(session).move_to_dlq(
        job, failure_reason=failure_reason, error_text=error_text
    )
    await session.commit()
    return entry


async def test_list_returns_entries(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Ro'yxat foydalanuvchining yozuvlarini sahifalangan holda beradi."""
    job = await job_factory(status=JobStatus.FAILED, retry_count=3)
    entry = await push_to_dlq(db_session, job)

    response = await client.get(f"{api_prefix}/dlq", headers=auth_headers)

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["id"] for item in items] == [str(entry.id)]
    assert items[0]["job_id"] == str(job.id)
    assert items[0]["resolved"] is False
    assert items[0]["failure_reason"] == FailureReason.NON_ZERO_EXIT.value
    # `DlqEntryRead.job` ichma-ich qo'shiladi (frontend ro'yxatda kod/holatni
    # ko'rsatadi) — `selectinload` ishlayotganining dalili.
    assert items[0]["job"]["id"] == str(job.id)


async def test_list_filters(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`resolved`, `failure_reason` va `job_id` filtrlari ishlaydi."""
    timeout_job = await job_factory(status=JobStatus.FAILED, retry_count=3)
    timeout_entry = await push_to_dlq(db_session, timeout_job, failure_reason=FailureReason.TIMEOUT)
    other_job = await job_factory(status=JobStatus.FAILED, retry_count=3)
    await push_to_dlq(db_session, other_job, failure_reason=FailureReason.OOM)

    by_reason = await client.get(
        f"{api_prefix}/dlq?failure_reason={FailureReason.TIMEOUT.value}", headers=auth_headers
    )
    assert by_reason.status_code == 200, by_reason.text
    assert [item["id"] for item in by_reason.json()["items"]] == [str(timeout_entry.id)]

    by_job = await client.get(f"{api_prefix}/dlq?job_id={timeout_job.id}", headers=auth_headers)
    assert [item["id"] for item in by_job.json()["items"]] == [str(timeout_entry.id)]

    unresolved = await client.get(f"{api_prefix}/dlq?resolved=false", headers=auth_headers)
    assert unresolved.json()["pagination"]["total"] == 2

    resolved = await client.get(f"{api_prefix}/dlq?resolved=true", headers=auth_headers)
    assert resolved.json()["pagination"]["total"] == 0


async def test_stats_route_wins(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`GET /dlq/stats` 200 qaytaradi (yo'l `/dlq/{entry_id}` bilan to'qnashmaydi)."""
    job = await job_factory(status=JobStatus.FAILED, retry_count=3)
    await push_to_dlq(db_session, job, failure_reason=FailureReason.TIMEOUT)

    response = await client.get(f"{api_prefix}/dlq/stats", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["depth"] == 1
    assert body["total"] == 1
    assert body["unresolved"] == 1
    assert body["resolved"] == 0
    assert body["added_last_24h"] == 1
    assert body["by_reason"][FailureReason.TIMEOUT.value] == 1
    assert body["oldest_failed_at"] is not None


async def test_get_single_entry(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Bitta yozuvning tafsiloti va `is_retryable` hisoblangan maydoni."""
    job = await job_factory(status=JobStatus.FAILED, retry_count=3)
    entry = await push_to_dlq(db_session, job, error_text="aniq sabab")

    response = await client.get(f"{api_prefix}/dlq/{entry.id}", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(entry.id)
    assert body["last_error"] == "aniq sabab"
    assert body["is_retryable"] is True


async def test_unknown_entry_not_found(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Mavjud bo'lmagan yozuv 404 `DLQ_ENTRY_NOT_FOUND` beradi."""
    response = await client.get(f"{api_prefix}/dlq/{uuid.uuid4()}", headers=auth_headers)

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "DLQ_ENTRY_NOT_FOUND"


async def test_retry_requeues_job(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`POST /dlq/{id}/retry` job'ni `QUEUED` qiladi va `retry_count` ni nollaydi."""
    job = await job_factory(status=JobStatus.FAILED, retry_count=3)
    entry = await push_to_dlq(db_session, job)

    response = await client.post(
        f"{api_prefix}/dlq/{entry.id}/retry",
        headers=auth_headers,
        json={"notes": "kod tuzatildi"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["entry_id"] == str(entry.id)
    assert body["job_id"] == str(job.id)
    assert body["status"] == JobStatus.QUEUED.value
    assert body["requeued"] is True
    assert body["resolved"] is True

    refreshed = await client.get(f"{api_prefix}/jobs/{job.id}", headers=auth_headers)
    assert refreshed.json()["status"] == JobStatus.QUEUED.value
    assert refreshed.json()["retry_count"] == 0

    # Yozuv hal qilingani uchun chuqurlik 0 ga tushadi.
    stats = await client.get(f"{api_prefix}/dlq/stats", headers=auth_headers)
    assert stats.json()["depth"] == 0
    assert stats.json()["resolved"] == 1


async def test_second_retry_conflicts(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Hal qilingan yozuvni qayta urish 409 `DLQ_ALREADY_RESOLVED` beradi."""
    job = await job_factory(status=JobStatus.FAILED, retry_count=3)
    entry_id = str((await push_to_dlq(db_session, job)).id)

    first = await client.post(f"{api_prefix}/dlq/{entry_id}/retry", headers=auth_headers, json={})
    assert first.status_code == 200, first.text

    second = await client.post(f"{api_prefix}/dlq/{entry_id}/retry", headers=auth_headers, json={})
    assert second.status_code == 409, second.text
    assert second.json()["error"]["code"] == "DLQ_ALREADY_RESOLVED"


async def test_delete_marks_resolved_and_is_idempotent(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`DELETE` yozuvni hal qilingan qiladi; takrorlash xato BERMAYDI."""
    job = await job_factory(status=JobStatus.FAILED, retry_count=3)
    entry = await push_to_dlq(db_session, job)

    first = await client.delete(f"{api_prefix}/dlq/{entry.id}", headers=auth_headers)
    assert first.status_code == 200, first.text
    assert first.json()["success"] is True

    second = await client.delete(f"{api_prefix}/dlq/{entry.id}", headers=auth_headers)
    assert second.status_code == 200, second.text

    fetched = await client.get(f"{api_prefix}/dlq/{entry.id}", headers=auth_headers)
    assert fetched.json()["resolved"] is True
    assert fetched.json()["is_retryable"] is False


async def test_other_users_entry_not_found(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    other_user: User,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Begona yozuv ro'yxatda ko'rinmaydi va har qanday amalda 404 beradi."""
    foreign_job = await job_factory(owner=other_user, status=JobStatus.FAILED, retry_count=3)
    foreign_id = str((await push_to_dlq(db_session, foreign_job)).id)

    listed = await client.get(f"{api_prefix}/dlq", headers=auth_headers)
    assert listed.json()["pagination"]["total"] == 0

    for method, path in (
        ("get", f"/dlq/{foreign_id}"),
        ("delete", f"/dlq/{foreign_id}"),
    ):
        response = await getattr(client, method)(api_prefix + path, headers=auth_headers)
        assert response.status_code == 404, f"{method} {path}: {response.text}"

    retried = await client.post(
        f"{api_prefix}/dlq/{foreign_id}/retry", headers=auth_headers, json={}
    )
    assert retried.status_code == 404, retried.text


async def test_invalid_sort_field_unprocessable(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Ruxsat etilmagan `sort_by` 422 beradi (500 EMAS).

    `DlqFilter` `Depends()` bilan ulangan, ya'ni model ichidagi
    `model_validator` xatosi FastAPI'ning `RequestValidationError` iga
    AYLANMAYDI — uni `main.py` dagi XOM `pydantic.ValidationError`
    handler'i ushlaydi. Shu handler bo'lmasa javob 500 bo'lardi.
    """
    response = await client.get(f"{api_prefix}/dlq?sort_by=yoq", headers=auth_headers)

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]["errors"]


async def test_requires_authentication(client: httpx.AsyncClient, api_prefix: str) -> None:
    """Tokensiz so'rov 401 beradi."""
    for path in ("/dlq", "/dlq/stats"):
        response = await client.get(api_prefix + path)
        assert response.status_code == 401, f"{path}: {response.text}"


async def test_api_key_can_read_dlq(
    client: httpx.AsyncClient, api_prefix: str, api_key_headers: dict[str, str]
) -> None:
    """DLQ yo'llari `X-API-Key` ni ham qabul qiladi (shartnomadagi "J/K")."""
    response = await client.get(f"{api_prefix}/dlq/stats", headers=api_key_headers)

    assert response.status_code == 200, response.text
    assert response.json()["depth"] == 0


# ---------------------------------------------------------------------------
# Frontend bilan moslik: `search`, `mark_resolved`, `timeout_seconds`
# ---------------------------------------------------------------------------


async def test_search_filters_by_error_text(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`?search=` xato matni bo'yicha filtrlaydi (registrga sezgir emas).

    Frontend DLQ sahifasidagi qidiruv maydoni aynan shu parametrni
    yuboradi (`frontend/src/types/dlq.ts:DlqFilter.search`). Parametr
    backend'da bo'lmaganda `Depends(DlqFilter)` uni JIMGINA e'tiborsiz
    qoldirardi — ya'ni foydalanuvchi yozgan matn hech narsani filtrlamasdi.
    """
    first = await job_factory(status=JobStatus.FAILED)
    second = await job_factory(status=JobStatus.FAILED)
    await push_to_dlq(db_session, first, error_text="ZeroDivisionError: nolga bo'linish")
    await push_to_dlq(db_session, second, error_text="TimeoutError: vaqt tugadi")

    response = await client.get(f"{api_prefix}/dlq?search=NOLGA", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["pagination"]["total"] == 1
    assert body["items"][0]["job_id"] == str(first.id)

    # Mos kelmaydigan matn bo'sh sahifa beradi (422 EMAS).
    empty = await client.get(f"{api_prefix}/dlq?search=yoq-bunday-xato", headers=auth_headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["pagination"]["total"] == 0


async def test_search_also_matches_operator_notes(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Qidiruv operator izohini (`notes`) ham qamraydi."""
    job = await job_factory(status=JobStatus.FAILED)
    entry = await push_to_dlq(db_session, job, error_text="RuntimeError")
    entry.notes = "mijoz bilan kelishildi"
    await db_session.commit()

    response = await client.get(f"{api_prefix}/dlq?search=kelishildi", headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json()["pagination"]["total"] == 1
    assert response.json()["items"][0]["id"] == str(entry.id)


async def test_retry_accepts_frontend_mark_resolved_field(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`{"mark_resolved": true}` qabul qilinadi (frontend aynan shuni yuboradi).

    `DurablSchema` da `extra="forbid"`, shuning uchun maydon schema'da
    bo'lmaganda dashboard'dagi "qayta urinish" tugmasi 422 olardi.
    """
    job = await job_factory(status=JobStatus.FAILED, retry_count=2)
    entry = await push_to_dlq(db_session, job)

    response = await client.post(
        f"{api_prefix}/dlq/{entry.id}/retry",
        headers=auth_headers,
        json={"mark_resolved": True},
    )

    assert response.status_code == 200, response.text
    assert response.json()["resolved"] is True


async def test_retry_applies_timeout_and_keeps_retry_count(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`timeout_seconds` job'ga qo'llanadi, `reset_retry_count=false` esa saqlaydi."""
    job = await job_factory(status=JobStatus.FAILED, retry_count=2, timeout_seconds=10)
    entry = await push_to_dlq(db_session, job)

    response = await client.post(
        f"{api_prefix}/dlq/{entry.id}/retry",
        headers=auth_headers,
        json={"timeout_seconds": 120, "max_retries": 5, "reset_retry_count": False},
    )

    assert response.status_code == 200, response.text

    refreshed = (await client.get(f"{api_prefix}/jobs/{job.id}", headers=auth_headers)).json()
    assert refreshed["timeout_seconds"] == 120
    assert refreshed["max_retries"] == 5
    # `reset_retry_count=false` -> urinishlar hisobi SAQLANADI.
    assert refreshed["retry_count"] == 2


async def test_retry_without_resolving_keeps_entry_in_queue(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`mark_resolved=false` -> job navbatga qaytadi, yozuv DLQ'da QOLADI.

    Operator natijani kuzatib turmoqchi bo'lgan holat: chuqurlik 1 da
    qoladi, lekin yozuvni KEYIN ham qayta urish mumkin (409 emas).
    """
    job = await job_factory(status=JobStatus.FAILED, retry_count=3)
    entry = await push_to_dlq(db_session, job)

    response = await client.post(
        f"{api_prefix}/dlq/{entry.id}/retry",
        headers=auth_headers,
        json={"mark_resolved": False, "notes": "kuzatuvda"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["resolved"] is False
    assert response.json()["status"] == JobStatus.QUEUED.value

    stats = (await client.get(f"{api_prefix}/dlq/stats", headers=auth_headers)).json()
    assert stats["depth"] == 1
    assert stats["resolved"] == 0

    # Yozuv hal qilinmagani uchun ikkinchi urinish 409 BERMAYDI.
    again = await client.post(
        f"{api_prefix}/dlq/{entry.id}/retry", headers=auth_headers, json={"mark_resolved": False}
    )
    assert again.status_code == 200, again.text


async def test_retry_rejects_contradictory_resolve_flags(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`resolve` va `mark_resolved` zid bo'lsa 422 — jim qolib ketmaydi."""
    job = await job_factory(status=JobStatus.FAILED)
    entry_id = str((await push_to_dlq(db_session, job)).id)

    response = await client.post(
        f"{api_prefix}/dlq/{entry_id}/retry",
        headers=auth_headers,
        json={"resolve": True, "mark_resolved": False},
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


__all__ = ["push_to_dlq"]
