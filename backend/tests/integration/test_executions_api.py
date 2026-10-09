"""Durabl — `/executions/*` endpointlarining integratsiya testlari.

Urinish yozuvlari bu yerda fabrika bilan yaratiladi (`make_execution`,
`make_log`): bajarish zanjirining O'ZI `test_execution.py` da tekshiriladi,
bu fayl esa SO'ROV qatlamiga — filtr, sahifalash, egalik va log kursoriga —
qaratilgan. Fabrika yo'li tezroq va holatlarni (masalan `TIMEOUT`) xohlagancha
qo'yish imkonini beradi.

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

## Egalik `jobs` bilan `JOIN` orqali tekshiriladi

`ExecutionRepository.search()` `user_id` ni `executions -> jobs` bog'lanishi
orqali qo'llaydi, ya'ni begona urinish natijaga TUSHMAYDI va bitta yozuvni
o'qish 404 beradi. `executions` jadvalida `user_id` ustuni YO'Q, shuning
uchun bu test izolyatsiyaning yagona kafolati.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from app.constants import ExecutionStatus, FailureReason, JobStatus, LogStream

from tests.factories import make_execution, make_log

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from collections.abc import Awaitable, Callable

    import httpx
    from app.models.execution import Execution
    from app.models.job import Job
    from app.models.user import User
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def add_execution(
    session: AsyncSession, job: Job, **overrides: object
) -> Execution:
    """Urinish yozuvini DB'ga yozadi va commit qiladi."""
    execution = make_execution(job_id=job.id, **overrides)  # type: ignore[arg-type]
    session.add(execution)
    await session.flush()
    await session.commit()
    return execution


async def test_list_returns_user_executions(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Ro'yxat foydalanuvchining urinishlarini sahifalangan holda beradi."""
    job = await job_factory(status=JobStatus.SUCCESS)
    execution = await add_execution(
        db_session, job, status=ExecutionStatus.SUCCESS, exit_code=0, duration_ms=120
    )

    response = await client.get(f"{api_prefix}/executions", headers=auth_headers)

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["id"] for item in items] == [str(execution.id)]
    assert items[0]["job_id"] == str(job.id)
    assert items[0]["attempt_number"] == 1
    assert items[0]["duration_ms"] == 120


async def test_filter_by_job_id(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`?job_id` faqat shu job'ning urinishlarini qoldiradi."""
    first = await job_factory()
    second = await job_factory()
    wanted = await add_execution(db_session, first)
    await add_execution(db_session, second)

    response = await client.get(
        f"{api_prefix}/executions?job_id={first.id}", headers=auth_headers
    )

    assert response.status_code == 200, response.text
    assert [item["id"] for item in response.json()["items"]] == [str(wanted.id)]


async def test_filter_by_status_and_reason(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`?status` va `?failure_reason` filtrlari ALOHIDA ishlaydi."""
    job = await job_factory()
    timed_out = await add_execution(
        db_session,
        job,
        attempt_number=1,
        status=ExecutionStatus.TIMEOUT,
        failure_reason=FailureReason.TIMEOUT,
    )
    await add_execution(db_session, job, attempt_number=2, status=ExecutionStatus.SUCCESS)

    by_status = await client.get(
        f"{api_prefix}/executions?status={ExecutionStatus.TIMEOUT.value}",
        headers=auth_headers,
    )
    assert [item["id"] for item in by_status.json()["items"]] == [str(timed_out.id)]

    by_reason = await client.get(
        f"{api_prefix}/executions?failure_reason={FailureReason.TIMEOUT.value}",
        headers=auth_headers,
    )
    assert [item["id"] for item in by_reason.json()["items"]] == [str(timed_out.id)]


async def test_filter_by_worker_id(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`?worker_id` diagnostika uchun kerak: qaysi worker nimani bajardi."""
    job = await job_factory()
    mine = await add_execution(db_session, job, attempt_number=1, worker_id="worker-a")
    await add_execution(db_session, job, attempt_number=2, worker_id="worker-b")

    response = await client.get(
        f"{api_prefix}/executions?worker_id=worker-a", headers=auth_headers
    )

    assert [item["id"] for item in response.json()["items"]] == [str(mine.id)]


async def test_sorting_and_pagination(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`sort_by=attempt_number` va sahifalash meta'si to'g'ri ishlaydi."""
    job = await job_factory()
    for attempt in (1, 2, 3):
        await add_execution(db_session, job, attempt_number=attempt)

    ascending = await client.get(
        f"{api_prefix}/executions?sort_by=attempt_number&sort_order=asc",
        headers=auth_headers,
    )
    assert ascending.status_code == 200, ascending.text
    assert [item["attempt_number"] for item in ascending.json()["items"]] == [1, 2, 3]

    paged = await client.get(
        f"{api_prefix}/executions?sort_by=attempt_number&sort_order=asc&page=2&page_size=2",
        headers=auth_headers,
    )
    assert [item["attempt_number"] for item in paged.json()["items"]] == [3]
    assert paged.json()["pagination"]["total_pages"] == 2


async def test_get_single_execution(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Bitta urinishning to'liq tafsiloti."""
    job = await job_factory()
    execution = await add_execution(
        db_session, job, status=ExecutionStatus.FAILED, error_message="xato matni"
    )

    response = await client.get(
        f"{api_prefix}/executions/{execution.id}", headers=auth_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(execution.id)
    assert body["error_message"] == "xato matni"
    # CONTRACTS "QO'SHIMCHA 4 §E": ishonchli manba yo'q, HAR DOIM `None`.
    assert body["memory_peak_mb"] is None


async def test_execution_logs_with_cursor(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`/executions/{id}/logs` kursor va oqim filtrini qo'llaydi."""
    job = await job_factory()
    execution = await add_execution(db_session, job)
    db_session.add_all(
        [
            make_log(
                execution_id=execution.id,
                job_id=job.id,
                stream=LogStream.STDOUT,
                content="birinchi",
                sequence=0,
            ),
            make_log(
                execution_id=execution.id,
                job_id=job.id,
                stream=LogStream.STDERR,
                content="ikkinchi",
                sequence=1,
            ),
        ]
    )
    await db_session.commit()

    everything = await client.get(
        f"{api_prefix}/executions/{execution.id}/logs", headers=auth_headers
    )
    assert everything.status_code == 200, everything.text
    body = everything.json()
    assert [entry["content"] for entry in body["entries"]] == ["birinchi", "ikkinchi"]
    assert body["execution_id"] == str(execution.id)
    assert body["job_id"] == str(job.id)

    after = await client.get(
        f"{api_prefix}/executions/{execution.id}/logs?after_sequence=0", headers=auth_headers
    )
    assert [entry["content"] for entry in after.json()["entries"]] == ["ikkinchi"]

    only_stderr = await client.get(
        f"{api_prefix}/executions/{execution.id}/logs?stream={LogStream.STDERR.value}",
        headers=auth_headers,
    )
    assert [entry["content"] for entry in only_stderr.json()["entries"]] == ["ikkinchi"]


async def test_other_users_execution_not_found(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    other_user: User,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Begona urinish ro'yxatda ko'rinmaydi va 404 beradi (modul docstring'iga qara)."""
    foreign_job = await job_factory(owner=other_user)
    foreign_id = str((await add_execution(db_session, foreign_job)).id)

    listed = await client.get(f"{api_prefix}/executions", headers=auth_headers)
    assert listed.json()["pagination"]["total"] == 0

    single = await client.get(
        f"{api_prefix}/executions/{foreign_id}", headers=auth_headers
    )
    assert single.status_code == 404, single.text
    assert single.json()["error"]["code"] == "EXECUTION_NOT_FOUND"

    logs = await client.get(
        f"{api_prefix}/executions/{foreign_id}/logs", headers=auth_headers
    )
    assert logs.status_code == 404, logs.text


async def test_unknown_execution_not_found(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Mavjud bo'lmagan urinish 404 beradi."""
    response = await client.get(
        f"{api_prefix}/executions/{uuid.uuid4()}", headers=auth_headers
    )

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "EXECUTION_NOT_FOUND"


async def test_invalid_sort_field_unprocessable(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Ruxsat etilmagan `sort_by` 422 beradi (500 EMAS)."""
    response = await client.get(f"{api_prefix}/executions?sort_by=yoq", headers=auth_headers)

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_requires_authentication(client: httpx.AsyncClient, api_prefix: str) -> None:
    """Tokensiz so'rov 401 beradi."""
    response = await client.get(f"{api_prefix}/executions")

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


__all__ = ["add_execution"]
