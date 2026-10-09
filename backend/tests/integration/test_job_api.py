"""Durabl — `/jobs/*` endpointlarining integratsiya testlari.

Bu platformaning markaziy yo'llari, shuning uchun qamrov keng: yuborish,
filtrlash, sahifalash, tartiblash, bitta job'ning barcha ko'rinishlari
(`/status`, `/logs`, `/result`, `/timeline`), amallar (`cancel`, `resubmit`)
va chegaraviy holatlar (begona job, yaroqsiz UUID, kvota, idempotency).

## Nega ko'p joyda `job_factory`, lekin ba'zi joyda `POST /jobs`

`job_factory` DB'ga BEVOSITA yozadi va navbatga tegmaydi — filtr/sahifalash
testlari uchun tez va aniq (holatni xohlagancha qo'yish mumkin).
Yuborish zanjirini (kvota, idempotency, `Location`, navbat) tekshiradigan
testlar esa HTTP orqali boradi, chunki aynan shu zanjir sinovdan o'tishi kerak.

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

## Idempotency barmoq izi — nozik joy

Barmoq izi so'rov maydonlari REJAGA MOSLANGANDAN KEYIN hisoblanadi
(`JobService._fingerprint_source`). Ya'ni FREE rejada `timeout_seconds=99`
yuborilsa, u reja chegarasiga (30) QISQARTIRILADI va barmoq izi
o'zgarmaydi — bunday so'rov konflikt BERMAYDI. Haqiqiy konflikt uchun
qisqartirilmaydigan maydon (`code`) o'zgartiriladi.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest
from app.config import settings
from app.constants import FailureReason, JobStatus, Priority, Runtime
from app.utils.time_utils import month_key, utcnow

from tests.factories import make_usage

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from collections.abc import Awaitable, Callable

    import httpx
    from app.models.job import Job
    from app.models.user import User
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

#: `LocalRunner` da muvaffaqiyatli bajariladigan kod.
SAFE_CODE = "def main(payload):\n    return {'ok': True}\n"

#: `PYTHON_FORBIDDEN_IMPORTS` ro'yxatidagi modulni import qiladigan kod.
#: DIQQAT: `settings.CODE_VALIDATION_STRICT` standart holatda `False`, ya'ni
#: bunday kod QABUL QILINADI (buzilishlar faqat qayd etiladi) — sandbox
#: baribir tarmoqni va fayl tizimini bloklaydi. Shuning uchun qat'iy rejim
#: testda ATAYLAB yoqiladi.
UNSAFE_CODE = "import subprocess\n\ndef main(payload):\n    return subprocess.getoutput('ls')\n"

#: Sintaksis xatosi — `CODE_VALIDATION_STRICT` dan QAT'I NAZAR rad etiladi.
BROKEN_CODE = "def main(payload)\n    return 1\n"

#: FREE rejadagi oylik job limiti (`PLAN_LIMITS[FREE].monthly_jobs`).
FREE_MONTHLY_JOBS = 1000


def iso_offset(moment: datetime, offset_seconds: int) -> str:
    """`moment` dan `offset_seconds` siljigan ISO-8601 matn (query uchun)."""
    return (moment + timedelta(seconds=offset_seconds)).isoformat()


def submit_body(**overrides: Any) -> dict[str, Any]:
    """`POST /jobs` uchun minimal tana."""
    body: dict[str, Any] = {"code": SAFE_CODE, "runtime": Runtime.PYTHON.value}
    body.update(overrides)
    return body


async def test_submit_returns_location_header(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Yangi job 201 va `Location` header'i bilan qaytadi."""
    response = await client.post(f"{api_prefix}/jobs", headers=auth_headers, json=submit_body())

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == JobStatus.QUEUED.value
    assert body["code"].startswith("def main")
    assert response.headers["Location"] == f"{api_prefix}/jobs/{body['id']}"


async def test_list_filters(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Holat, muhit, ustuvorlik, teg va sabab filtrlari ALOHIDA ishlaydi."""
    target = await job_factory(
        status=JobStatus.FAILED,
        runtime=Runtime.NODE,
        priority=Priority.HIGH,
        failure_reason=FailureReason.TIMEOUT,
        tags=["muhim", "hisobot"],
    )
    await job_factory(status=JobStatus.SUCCESS, runtime=Runtime.PYTHON, tags=["boshqa"])

    for query in (
        f"status={JobStatus.FAILED.value}",
        f"runtime={Runtime.NODE.value}",
        f"priority={Priority.HIGH.value}",
        f"failure_reason={FailureReason.TIMEOUT.value}",
        "tag=muhim",
    ):
        response = await client.get(f"{api_prefix}/jobs?{query}", headers=auth_headers)
        assert response.status_code == 200, f"{query}: {response.text}"
        items = response.json()["items"]
        assert [item["id"] for item in items] == [str(target.id)], query


async def test_list_search_and_time_range(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Matnli qidiruv va vaqt oralig'i filtrlari."""
    await job_factory(code="def main(payload):\n    return 'alohida_belgi'\n")
    await job_factory(code=SAFE_CODE)

    found = await client.get(f"{api_prefix}/jobs?search=alohida_belgi", headers=auth_headers)
    assert found.status_code == 200, found.text
    assert found.json()["pagination"]["total"] == 1

    # Hozirgi vaqtni o'rab turgan oraliq — ikkisi ham topiladi.
    now = utcnow()
    window = await client.get(
        f"{api_prefix}/jobs",
        headers=auth_headers,
        params={"start": iso_offset(now, -3600), "end": iso_offset(now, 3600)},
    )
    assert window.json()["pagination"]["total"] == 2

    # Kelajakdagi oraliq — hech narsa topilmaydi.
    future = await client.get(
        f"{api_prefix}/jobs",
        headers=auth_headers,
        params={"start": iso_offset(now, 3600), "end": iso_offset(now, 7200)},
    )
    assert future.json()["pagination"]["total"] == 0


async def test_list_pagination_meta(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`pagination` meta'si (`total_pages`, `has_next`, `has_prev`) to'g'ri."""
    for _ in range(5):
        await job_factory()

    first = await client.get(f"{api_prefix}/jobs?page=1&page_size=2", headers=auth_headers)
    assert first.status_code == 200, first.text
    meta = first.json()["pagination"]
    assert meta == {
        "page": 1,
        "page_size": 2,
        "total": 5,
        "total_pages": 3,
        "has_next": True,
        "has_prev": False,
    }
    assert len(first.json()["items"]) == 2

    last = await client.get(f"{api_prefix}/jobs?page=3&page_size=2", headers=auth_headers)
    last_meta = last.json()["pagination"]
    assert last_meta["has_next"] is False
    assert last_meta["has_prev"] is True
    assert len(last.json()["items"]) == 1


async def test_list_sorting(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`sort_by`/`sort_order` tartibni o'zgartiradi, noma'lum ustun 422 beradi."""
    slow = await job_factory(status=JobStatus.SUCCESS, duration_ms=5000)
    fast = await job_factory(status=JobStatus.SUCCESS, duration_ms=10)

    ascending = await client.get(
        f"{api_prefix}/jobs?sort_by=duration_ms&sort_order=asc", headers=auth_headers
    )
    assert ascending.status_code == 200, ascending.text
    assert [item["id"] for item in ascending.json()["items"]] == [str(fast.id), str(slow.id)]

    descending = await client.get(
        f"{api_prefix}/jobs?sort_by=duration_ms&sort_order=desc", headers=auth_headers
    )
    assert [item["id"] for item in descending.json()["items"]] == [str(slow.id), str(fast.id)]

    rejected = await client.get(f"{api_prefix}/jobs?sort_by=yoq", headers=auth_headers)
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_get_job_and_status(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`GET /jobs/{id}` to'liq, `/status` esa YENGIL javob beradi."""
    job = await job_factory(status=JobStatus.SUCCESS, exit_code=0, duration_ms=42)

    full = await client.get(f"{api_prefix}/jobs/{job.id}", headers=auth_headers)
    assert full.status_code == 200, full.text
    assert "code" in full.json()

    light = await client.get(f"{api_prefix}/jobs/{job.id}/status", headers=auth_headers)
    assert light.status_code == 200, light.text
    body = light.json()
    assert body["status"] == JobStatus.SUCCESS.value
    assert body["is_terminal"] is True
    # Yengil javobda og'ir maydonlar YO'Q.
    assert "code" not in body
    assert "stdout" not in body
    assert light.headers["Cache-Control"] == "no-store"


async def test_logs_empty_for_fresh_job(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Hali bajarilmagan job'ning loglari bo'sh, lekin javob shakli to'g'ri."""
    job = await job_factory()

    response = await client.get(f"{api_prefix}/jobs/{job.id}/logs", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["job_id"] == str(job.id)
    assert body["entries"] == []
    assert body["has_more"] is False
    assert body["next_sequence"] is None


async def test_result_conflicts_until_finished(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Tugamagan job'da `/result` 409 `RESULT_NOT_READY` beradi."""
    # IKKI job 409 dan OLDIN yaratiladi (modul docstring'idagi qoida).
    pending_id = str((await job_factory(status=JobStatus.QUEUED)).id)
    done_id = str(
        (
            await job_factory(
                status=JobStatus.SUCCESS,
                result={"value": 7},
                exit_code=0,
                finished_at=utcnow(),
            )
        ).id
    )

    response = await client.get(f"{api_prefix}/jobs/{pending_id}/result", headers=auth_headers)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "RESULT_NOT_READY"

    ready = await client.get(f"{api_prefix}/jobs/{done_id}/result", headers=auth_headers)
    assert ready.status_code == 200, ready.text
    assert ready.json()["result"] == {"value": 7}


async def test_timeline_shape(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`/timeline` barcha bosqich maydonlarini va `executions` ro'yxatini beradi."""
    job = await job_factory(status=JobStatus.QUEUED, queued_at=utcnow())

    response = await client.get(f"{api_prefix}/jobs/{job.id}/timeline", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    for field in ("job_id", "status", "created_at", "queued_at", "attempts", "executions"):
        assert field in body, field
    assert body["executions"] == []


async def test_cancel_then_terminal_conflict(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Navbatdagi job bekor qilinadi; YAKUNIY holatdagi job 409 beradi."""
    job_id = str((await job_factory(status=JobStatus.QUEUED, queued_at=utcnow())).id)
    finished_id = str((await job_factory(status=JobStatus.SUCCESS, finished_at=utcnow())).id)

    cancelled = await client.post(f"{api_prefix}/jobs/{job_id}/cancel", headers=auth_headers)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == JobStatus.CANCELLED.value
    assert cancelled.json()["cancelled_at"] is not None

    conflict = await client.post(f"{api_prefix}/jobs/{finished_id}/cancel", headers=auth_headers)
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "JOB_NOT_CANCELLABLE"


async def test_resubmit_creates_new_job(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """`/resubmit` YANGI job yaratadi, eskisi o'zgarmaydi."""
    source = await job_factory(status=JobStatus.FAILED, tags=["qayta"])

    response = await client.post(f"{api_prefix}/jobs/{source.id}/resubmit", headers=auth_headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] != str(source.id)
    # `JobCreate` kodni `strip()` qiladi, shuning uchun solishtirish ham shunday.
    assert body["code"].strip() == source.code.strip()
    assert body["tags"] == ["qayta"]
    assert body["status"] == JobStatus.QUEUED.value
    assert response.headers["Location"] == f"{api_prefix}/jobs/{body['id']}"

    original = await client.get(f"{api_prefix}/jobs/{source.id}", headers=auth_headers)
    assert original.json()["status"] == JobStatus.FAILED.value


async def test_other_users_job_is_not_found(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    other_user: User,
    job_factory: Callable[..., Awaitable[Job]],
) -> None:
    """Begona job HAR DOIM 404 (IDOR himoyasi — mavjudligi oshkor qilinmaydi)."""
    foreign_id = str((await job_factory(owner=other_user)).id)

    for path in ("", "/status", "/logs", "/result", "/timeline"):
        response = await client.get(
            f"{api_prefix}/jobs/{foreign_id}{path}", headers=auth_headers
        )
        assert response.status_code == 404, f"{path}: {response.text}"
        assert response.json()["error"]["code"] == "JOB_NOT_FOUND"

    listed = await client.get(f"{api_prefix}/jobs", headers=auth_headers)
    assert listed.json()["pagination"]["total"] == 0


async def test_invalid_uuid_is_unprocessable(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Yo'l parametri UUID bo'lmasa 422 qaytadi (404 emas)."""
    response = await client.get(f"{api_prefix}/jobs/mutlaqo-uuid-emas", headers=auth_headers)

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_broken_code_rejected(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Sintaksis xatosi har qanday sozlamada 422 `CODE_SYNTAX_ERROR` beradi."""
    response = await client.post(
        f"{api_prefix}/jobs", headers=auth_headers, json=submit_body(code=BROKEN_CODE)
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "CODE_SYNTAX_ERROR"


async def test_unsafe_code_rejected_in_strict_mode(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qat'iy rejimda taqiqlangan import 422 `CODE_VALIDATION_FAILED` beradi."""
    monkeypatch.setattr(settings, "CODE_VALIDATION_STRICT", True)

    response = await client.post(
        f"{api_prefix}/jobs", headers=auth_headers, json=submit_body(code=UNSAFE_CODE)
    )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "CODE_VALIDATION_FAILED"
    assert error["details"]["violations"]


async def test_unsafe_code_accepted_when_not_strict(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Standart (qat'iy bo'lmagan) rejimda ayni kod QABUL QILINADI.

    Bu qoida ataylab: statik tekshiruv — qulaylik, haqiqiy chegara esa
    sandbox (tarmoq yo'q, `read_only_rootfs`, rlimit). Test shu qarorni
    muzlatib qo'yadi, aks holda `CODE_VALIDATION_STRICT` ni tasodifan
    o'zgartirish sezilmay ketardi.
    """
    response = await client.post(
        f"{api_prefix}/jobs", headers=auth_headers, json=submit_body(code=UNSAFE_CODE)
    )

    assert response.status_code == 201, response.text


async def test_quota_exceeded_payment_required(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    user: User,
) -> None:
    """Oylik kvota tugaganda `POST /jobs` 402 `QUOTA_EXCEEDED` beradi."""
    db_session.add(
        make_usage(user_id=user.id, period=month_key(), job_count=FREE_MONTHLY_JOBS)
    )
    await db_session.commit()

    response = await client.post(f"{api_prefix}/jobs", headers=auth_headers, json=submit_body())

    assert response.status_code == 402, response.text
    assert response.json()["error"]["code"] == "QUOTA_EXCEEDED"


async def test_idempotent_submit_returns_same_job(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Ayni kalit bilan ikkinchi so'rov 200 va AYNI job'ni qaytaradi."""
    headers = {**auth_headers, "Idempotency-Key": "buyruq-2026-10-04-0001"}
    body = submit_body(payload={"args": [1]})

    first = await client.post(f"{api_prefix}/jobs", headers=headers, json=body)
    second = await client.post(f"{api_prefix}/jobs", headers=headers, json=body)

    assert first.status_code == 201, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]

    listed = await client.get(f"{api_prefix}/jobs", headers=auth_headers)
    assert listed.json()["pagination"]["total"] == 1


async def test_idempotency_key_with_other_body_conflicts(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Ayni kalit BOSHQA tana bilan 409 `IDEMPOTENCY_CONFLICT` beradi."""
    headers = {**auth_headers, "Idempotency-Key": "buyruq-2026-10-04-0002"}

    first = await client.post(f"{api_prefix}/jobs", headers=headers, json=submit_body())
    assert first.status_code == 201, first.text

    # `code` reja chegarasiga QISQARTIRILMAYDI, shuning uchun barmoq izi
    # kafolatlangan ravishda o'zgaradi (modul docstring'iga qara).
    conflict = await client.post(
        f"{api_prefix}/jobs",
        headers=headers,
        json=submit_body(code="def main(payload):\n    return {'ok': False}\n"),
    )

    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


async def test_submit_requires_authentication(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    """Tokensiz yuborish 401 beradi va job yaratilmaydi."""
    response = await client.post(f"{api_prefix}/jobs", json=submit_body())

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


async def test_submit_with_api_key_allowed(
    client: httpx.AsyncClient, api_prefix: str, api_key_headers: dict[str, str]
) -> None:
    """`X-API-Key` bilan job yuborish ishlaydi (server-server integratsiya)."""
    response = await client.post(
        f"{api_prefix}/jobs", headers=api_key_headers, json=submit_body()
    )

    assert response.status_code == 201, response.text
    assert uuid.UUID(response.json()["id"])


__all__ = [
    "BROKEN_CODE",
    "FREE_MONTHLY_JOBS",
    "SAFE_CODE",
    "UNSAFE_CODE",
    "iso_offset",
    "submit_body",
]
