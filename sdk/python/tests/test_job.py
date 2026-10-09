"""`JobStatus`, `Job`, `JobResult`, `JobHandle` va sahifalash testlari."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import respx

from durabl import (
    RESULT_MARKER,
    DurablClient,
    Job,
    JobHandle,
    JobPage,
    JobResult,
    JobStatus,
    Pagination,
    ValidationError,
)
from durabl.job import extract_marker_value, parse_datetime

from .conftest import BASE_URL, error_payload, job_payload, result_payload

JOB_ID = "11111111-1111-1111-1111-111111111111"
JOB_URL = f"/api/v1/jobs/{JOB_ID}"


# ---------------------------------------------------------------------------
# JobStatus
# ---------------------------------------------------------------------------


def test_job_status_qiymatlari_backend_bilan_bir_xil() -> None:
    """Holat qiymatlari shartnomadagi matnlar bilan bir xil bo'lishi shart."""
    assert [status.value for status in JobStatus] == [
        "pending",
        "queued",
        "running",
        "success",
        "failed",
        "retrying",
        "cancelled",
        "dead_letter",
    ]
    # `str` dan voris bo'lgani uchun matn sifatida ishlatish mumkin.
    assert f"{JobStatus.SUCCESS}" == "success"
    assert JobStatus.SUCCESS == "success"


def test_job_status_xossalari() -> None:
    """`is_terminal`, `is_finished`, `is_active` ta'riflari."""
    assert JobStatus.SUCCESS.is_terminal
    assert JobStatus.CANCELLED.is_terminal
    assert JobStatus.DEAD_LETTER.is_terminal
    # `failed` dan `dead_letter`ga o'tish mumkin — shuning uchun yakuniy emas,
    # lekin natija mavjud, shuning uchun "tugagan" hisoblanadi.
    assert not JobStatus.FAILED.is_terminal
    assert JobStatus.FAILED.is_finished
    assert JobStatus.RUNNING.is_active
    assert not JobStatus.RUNNING.is_finished
    assert JobStatus.SUCCESS.is_success


def test_job_status_parse_va_notogri_qiymat() -> None:
    """Matn enumga o'giriladi, noma'lum qiymat esa xato beradi."""
    assert JobStatus.parse("QUEUED") is JobStatus.QUEUED
    assert JobStatus.parse(JobStatus.FAILED) is JobStatus.FAILED
    with pytest.raises(ValidationError) as excinfo:
        JobStatus.parse("zombi")
    assert "zombi" in str(excinfo.value)


# ---------------------------------------------------------------------------
# parse_datetime
# ---------------------------------------------------------------------------


def test_parse_datetime_barcha_shakllar() -> None:
    """`Z`, `+00:00`, naive matn, timestamp va noto'g'ri qiymat."""
    assert parse_datetime("2026-10-04T10:00:00Z") == datetime(
        2026, 10, 4, 10, 0, tzinfo=timezone.utc
    )
    assert parse_datetime("2026-10-04T10:00:00+00:00").tzinfo is not None
    # Naive matn UTC deb qabul qilinadi.
    assert parse_datetime("2026-10-04T10:00:00").tzinfo is timezone.utc
    assert parse_datetime(0) == datetime(1970, 1, 1, tzinfo=timezone.utc)
    assert parse_datetime(None) is None
    assert parse_datetime("") is None
    assert parse_datetime("kecha") is None


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


def test_job_from_dict_notanish_maydonlarni_saqlaydi() -> None:
    """SDK bilmagan maydonlar `raw` ichida saqlanadi."""
    job = Job.from_dict(job_payload(status="running", memory_mb=512, tags=["etl"]))

    assert job.id == JOB_ID
    assert job.status is JobStatus.RUNNING
    assert job.tags == ["etl"]
    assert job.raw["memory_mb"] == 512
    assert str(job) == f"Job({JOB_ID}, running)"


def test_job_from_dict_id_bolmasa_xato() -> None:
    """`id` yo'q javob — shartnoma buzilgan, darhol xato."""
    with pytest.raises(ValidationError):
        Job.from_dict({"status": "pending"})
    with pytest.raises(ValidationError):
        Job.from_dict([])  # type: ignore[arg-type]


def test_job_xossalari() -> None:
    """`is_terminal`, `is_success`, `duration_seconds`."""
    success = Job.from_dict(job_payload(status="success", duration_ms=1500, exit_code=0))
    failed = Job.from_dict(job_payload(status="failed", exit_code=1, error="xato"))

    assert success.is_success and success.is_terminal and success.is_finished
    assert success.duration_seconds == 1.5
    assert not failed.is_success
    assert not failed.is_terminal
    assert failed.is_finished
    assert failed.duration_seconds is None


# ---------------------------------------------------------------------------
# JobResult
# ---------------------------------------------------------------------------


def test_job_result_ok_shartlari() -> None:
    """`ok` faqat `success` va `exit_code` 0 (yoki yo'q) bo'lganda rost."""
    assert JobResult(status=JobStatus.SUCCESS, exit_code=0).ok
    assert JobResult(status=JobStatus.SUCCESS).ok
    assert not JobResult(status=JobStatus.SUCCESS, exit_code=2).ok
    assert not JobResult(status=JobStatus.FAILED, exit_code=0).ok
    assert JobResult(status=JobStatus.FAILED).failed


def test_job_result_from_dict_va_maydon_tartibi() -> None:
    """Shartnoma tartibi: stdout, stderr, result, exit_code, duration_ms, status."""
    positional = JobResult("chiqish", "xato", {"a": 1}, 0, 10, JobStatus.SUCCESS)
    assert positional.stdout == "chiqish"
    assert positional.stderr == "xato"
    assert positional.result == {"a": 1}
    assert positional.ok

    parsed = JobResult.from_dict(result_payload(result={"x": 2}))
    assert parsed.job_id == JOB_ID
    assert parsed.result == {"x": 2}
    assert "JobResult(success" in str(parsed)

    with pytest.raises(ValidationError):
        JobResult.from_dict("matn")  # type: ignore[arg-type]


def test_job_result_from_job_surati() -> None:
    """Natija bo'lmaganda job suratidan yasash."""
    job = Job.from_dict(
        job_payload(status="failed", exit_code=137, error="OOM", stdout="a\n", stderr="b\n")
    )
    result = JobResult.from_job(job)

    assert result.status is JobStatus.FAILED
    assert result.exit_code == 137
    assert result.stdout == "a\n"
    assert result.stderr == "b\n"
    assert result.error == "OOM"
    assert not result.ok


def test_job_result_value_markerdan_oladi() -> None:
    """Dekorator qaytargan qiymat stdout'dagi belgidan olinadi."""
    stdout = f'foydalanuvchi chiqishi\n{{"{RESULT_MARKER}": {{"soni": 3}}}}\n'
    result = JobResult(stdout=stdout, status=JobStatus.SUCCESS, exit_code=0)

    assert result.value() == {"soni": 3}
    # Belgi bo'lmasa — `result` maydoni, u ham bo'lmasa `default`.
    assert JobResult(status=JobStatus.SUCCESS, result=42).value() == 42
    assert JobResult(status=JobStatus.SUCCESS).value(default="yo'q") == "yo'q"


def test_extract_marker_value_oxirgi_mos_qatorni_oladi() -> None:
    """Kod o'zi ham JSON chiqarsa, oxirgi mos qator olinadi."""
    stdout = "\n".join(
        [
            '{"boshqa": 1}',
            f'{{"{RESULT_MARKER}": "birinchi"}}',
            "oddiy matn",
            f'{{"{RESULT_MARKER}": "oxirgi"}}',
        ]
    )
    assert extract_marker_value(stdout) == "oxirgi"
    # Topilmasa — ichki "yo'q" belgisi (None emas).
    assert extract_marker_value("hech narsa") is not None
    assert repr(extract_marker_value("")) == "<MISSING>"


# ---------------------------------------------------------------------------
# Sahifalash
# ---------------------------------------------------------------------------


def test_pagination_va_job_page() -> None:
    """`{page, page_size, total, total_pages, has_next, has_prev}` shakli."""
    pagination = Pagination.from_dict(
        {
            "page": 2,
            "page_size": 10,
            "total": 25,
            "total_pages": 3,
            "has_next": True,
            "has_prev": True,
        }
    )
    assert (pagination.page, pagination.total_pages) == (2, 3)
    assert pagination.has_next and pagination.has_prev

    # Noto'g'ri yoki yo'q `pagination` — standart qiymatlar.
    assert Pagination.from_dict(None).page == 1

    page = JobPage(items=[Job.from_dict(job_payload())], pagination=pagination)
    assert len(page) == 1
    assert [job.id for job in page] == [JOB_ID]


# ---------------------------------------------------------------------------
# JobHandle
# ---------------------------------------------------------------------------


def test_job_handle_argumentsiz_yaratilmaydi(client: DurablClient) -> None:
    """`job` yoki `job_id` berilishi shart."""
    with pytest.raises(ValidationError):
        JobHandle(client)


def test_job_handle_status_result_logs(client: DurablClient) -> None:
    """Handle metodlari mijozga to'g'ri yo'naltiradi."""
    log_entry = {"stream": "stdout", "content": "qator", "sequence": 1}
    with respx.mock(base_url=BASE_URL) as router:
        router.get(JOB_URL).mock(
            return_value=httpx.Response(200, json=job_payload(status="success"))
        )
        router.get(f"{JOB_URL}/result").mock(
            return_value=httpx.Response(200, json=result_payload())
        )
        router.get(f"{JOB_URL}/logs").mock(
            return_value=httpx.Response(200, json={"items": [log_entry]})
        )

        handle = JobHandle(client, job_id=JOB_ID)
        assert handle.job is None
        assert handle.status() is JobStatus.SUCCESS
        assert handle.job is not None  # refresh keshga yozdi
        assert handle.result().ok
        assert handle.logs() == [log_entry]
        assert handle.client is client
        assert "success" in repr(handle)


def test_job_handle_wait_va_cancel(client: DurablClient) -> None:
    """`wait()` natijani qaytaradi, `cancel()` holatni yangilaydi."""
    with respx.mock(base_url=BASE_URL) as router:
        router.get(JOB_URL).mock(
            side_effect=[
                httpx.Response(200, json=job_payload(status="queued")),
                httpx.Response(200, json=job_payload(status="success", exit_code=0)),
            ]
        )
        router.get(f"{JOB_URL}/result").mock(
            return_value=httpx.Response(200, json=result_payload())
        )
        router.post(f"{JOB_URL}/cancel").mock(
            return_value=httpx.Response(200, json=job_payload(status="cancelled"))
        )

        handle = JobHandle(client, Job.from_dict(job_payload(status="queued")))
        result = handle.wait(timeout=30, poll_interval=1.0)
        assert result.ok
        assert handle.job is not None and handle.job.status is JobStatus.SUCCESS

        cancelled = handle.cancel()
        assert cancelled.status is JobStatus.CANCELLED


def test_job_handle_natija_tayyor_emas(client: DurablClient) -> None:
    """Tugamagan job'dan natija so'ralsa xato ko'tariladi."""
    with respx.mock(base_url=BASE_URL) as router:
        router.get(f"{JOB_URL}/result").mock(
            return_value=httpx.Response(409, json=error_payload("RESULT_NOT_READY"))
        )
        handle = JobHandle(client, job_id=JOB_ID)
        with pytest.raises(Exception) as excinfo:
            handle.result()

    assert excinfo.value.code == "RESULT_NOT_READY"
