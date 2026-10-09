"""Durabl — `app/services/job_state.py` birlik testlari.

Holat mashinasi — Durabl'ning eng muhim invarianti: `SUCCESS` bo'lgan job
qayta `RUNNING` ga o'ta olmaydi, `RETRYING` dan to'g'ridan-to'g'ri `RUNNING` ga
sakrash mumkin emas (shartnoma QO'SHIMCHA 4 §A ayni shu poyga haqida).

Shuning uchun BARCHA (holat, holat) juftligi parametrlangan test bilan
tekshiriladi: 8 holat x 8 holat = 64 juftlik. Grafikda yangi yo'nalish
qo'shilsa yoki o'chirilsa, test darhol ko'rsatadi.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime

import pytest
from app.constants import JOB_STATUS_TRANSITIONS, FailureReason, JobStatus
from app.exceptions import InvalidStateTransitionError
from app.services.job_state import (
    allowed_targets,
    apply_transition,
    assert_transition,
    can_transition,
    is_cancellable,
    is_retryable_status,
    terminal_status_for,
    transition_fields,
)

from tests.factories import make_job

pytestmark = pytest.mark.unit

#: Barcha (joriy, maqsad) juftliklari — parametrlangan test uchun.
ALL_PAIRS = list(itertools.product(list(JobStatus), repeat=2))

#: Test uchun qat'iy lahza — vaqt ustunlari aynan shu qiymat bilan to'ldiriladi.
NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)


def _is_allowed(current: JobStatus, target: JobStatus) -> bool:
    """Shartnoma grafigi bo'yicha o'tish ruxsat etilganmi (testning etaloni)."""
    if current is target:
        return True  # idempotent qayta yozish har doim mumkin
    return target in JOB_STATUS_TRANSITIONS.get(current, frozenset())


# ---------------------------------------------------------------------------
# can_transition / assert_transition — to'liq matritsa
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("current", "target"), ALL_PAIRS)
def test_can_transition_matritsasi(current: JobStatus, target: JobStatus) -> None:
    """64 juftlikning har biri grafik bilan AYNAN mos bo'lishi kerak."""
    assert can_transition(current, target) is _is_allowed(current, target)


@pytest.mark.parametrize(("current", "target"), ALL_PAIRS)
def test_assert_transition_matritsasi(current: JobStatus, target: JobStatus) -> None:
    """Ruxsat etilmagan o'tish `InvalidStateTransitionError` beradi."""
    if _is_allowed(current, target):
        assert_transition(current, target)  # xato tashlamasligi kerak
    else:
        with pytest.raises(InvalidStateTransitionError):
            assert_transition(current, target)


@pytest.mark.parametrize("status", list(JobStatus))
def test_bir_xil_holatga_otish_har_doim_mumkin(status: JobStatus) -> None:
    """Idempotentlik: takroriy hodisa kelsa holatni qayta yozish mumkin."""
    assert can_transition(status, status) is True


def test_can_transition_matn_qiymat_bilan_ishlaydi() -> None:
    """Enum o'rniga matn kelsa ham ishlaydi (Redis/JSON'dan o'qilgan qiymat)."""
    assert can_transition("pending", "queued") is True
    assert can_transition("success", "running") is False


def test_can_transition_notogri_qiymat_valueerror() -> None:
    """Noma'lum holat nomi `ValueError` beradi (jim `False` emas)."""
    with pytest.raises(ValueError, match="yoq_holat"):
        can_transition("yoq_holat", JobStatus.QUEUED)


# ---------------------------------------------------------------------------
# Muhim yo'nalishlar — ochiq yozilgan tekshiruvlar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobStatus.PENDING, JobStatus.QUEUED),
        (JobStatus.QUEUED, JobStatus.RUNNING),
        (JobStatus.RUNNING, JobStatus.SUCCESS),
        (JobStatus.RUNNING, JobStatus.FAILED),
        (JobStatus.RUNNING, JobStatus.RETRYING),
        (JobStatus.RUNNING, JobStatus.QUEUED),  # lease yo'qoldi
        (JobStatus.RETRYING, JobStatus.QUEUED),  # scheduler promote qildi
        (JobStatus.FAILED, JobStatus.DEAD_LETTER),
        (JobStatus.DEAD_LETTER, JobStatus.QUEUED),  # DLQ'dan qo'lda retry
    ],
)
def test_ruxsat_etilgan_muhim_yonalishlar(current: JobStatus, target: JobStatus) -> None:
    """Zanjirning asosiy bo'g'inlari ishlashi SHART."""
    assert can_transition(current, target) is True


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (JobStatus.RETRYING, JobStatus.RUNNING),  # QO'SHIMCHA 4 §A sababi
        (JobStatus.PENDING, JobStatus.RUNNING),
        (JobStatus.SUCCESS, JobStatus.RUNNING),
        (JobStatus.SUCCESS, JobStatus.FAILED),
        (JobStatus.CANCELLED, JobStatus.QUEUED),
        (JobStatus.QUEUED, JobStatus.SUCCESS),
        (JobStatus.DEAD_LETTER, JobStatus.RUNNING),
    ],
)
def test_taqiqlangan_muhim_yonalishlar(current: JobStatus, target: JobStatus) -> None:
    """Sakrashlar taqiqlangan — aks holda hisobot va metrikalar yolg'on bo'lardi."""
    assert can_transition(current, target) is False


def test_yakuniy_holatlardan_chiqish_yoq() -> None:
    """`SUCCESS` va `CANCELLED` — chindan ham tupik (`DEAD_LETTER` dan tashqari)."""
    assert allowed_targets(JobStatus.SUCCESS) == frozenset()
    assert allowed_targets(JobStatus.CANCELLED) == frozenset()


# ---------------------------------------------------------------------------
# allowed_targets
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", list(JobStatus))
def test_allowed_targets_grafik_bilan_mos(status: JobStatus) -> None:
    """`allowed_targets` grafikdagi to'plamni AYNAN qaytaradi."""
    assert allowed_targets(status) == JOB_STATUS_TRANSITIONS[status]


def test_allowed_targets_ozini_qaytarmaydi() -> None:
    """To'plamda o'zi yo'q, lekin `can_transition` baribir `True` beradi."""
    assert JobStatus.RUNNING not in allowed_targets(JobStatus.RUNNING)
    assert can_transition(JobStatus.RUNNING, JobStatus.RUNNING) is True


# ---------------------------------------------------------------------------
# transition_fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "field_name"),
    [
        (JobStatus.QUEUED, "queued_at"),
        (JobStatus.RUNNING, "started_at"),
        (JobStatus.SUCCESS, "finished_at"),
        (JobStatus.FAILED, "finished_at"),
        (JobStatus.DEAD_LETTER, "finished_at"),
        (JobStatus.CANCELLED, "cancelled_at"),
    ],
)
def test_transition_fields_vaqt_ustunini_qoshadi(target: JobStatus, field_name: str) -> None:
    """Har bir holat uchun TO'G'RI vaqt ustuni to'ldiriladi."""
    fields = transition_fields(target, now=NOW)
    assert fields["status"] is target
    assert fields[field_name] == NOW


@pytest.mark.parametrize("target", [JobStatus.PENDING, JobStatus.RETRYING])
def test_transition_fields_vaqt_ustuni_yoq_holatlar(target: JobStatus) -> None:
    """`PENDING` va `RETRYING` uchun vaqt ustuni yo'q — faqat `status`."""
    assert transition_fields(target, now=NOW) == {"status": target}


def test_transition_fields_extra_ustun_turadi() -> None:
    """Ochiq berilgan qiymat avtomatik qo'yilganini ALMASHTIRADI."""
    custom = datetime(2020, 1, 1, tzinfo=UTC)
    fields = transition_fields(JobStatus.SUCCESS, now=NOW, finished_at=custom, exit_code=0)
    assert fields["finished_at"] == custom
    assert fields["exit_code"] == 0


def test_transition_fields_now_berilmasa_hozirgi_vaqt() -> None:
    """`now` berilmasa `utcnow()` ishlatiladi (aware qiymat)."""
    fields = transition_fields(JobStatus.RUNNING)
    assert fields["started_at"].tzinfo is not None


# ---------------------------------------------------------------------------
# apply_transition
# ---------------------------------------------------------------------------


def test_apply_transition_obyektni_ozgartiradi() -> None:
    """Holat va vaqt ustuni job obyektiga yoziladi."""
    job = make_job(status=JobStatus.QUEUED)
    applied = apply_transition(job, JobStatus.RUNNING, now=NOW)

    assert job.status is JobStatus.RUNNING
    assert job.started_at == NOW
    assert applied == {"status": JobStatus.RUNNING, "started_at": NOW}


def test_apply_transition_qoshimcha_maydonlarni_yozadi() -> None:
    """`**extra` orqali xato maydonlari ham bir yo'la yoziladi."""
    job = make_job(status=JobStatus.RUNNING)
    apply_transition(
        job,
        JobStatus.FAILED,
        now=NOW,
        error="Kod 1 bilan tugadi",
        failure_reason=FailureReason.NON_ZERO_EXIT,
        exit_code=1,
    )

    assert job.status is JobStatus.FAILED
    assert job.finished_at == NOW
    assert job.error == "Kod 1 bilan tugadi"
    assert job.failure_reason is FailureReason.NON_ZERO_EXIT
    assert job.exit_code == 1


def test_apply_transition_notogri_otishda_xato() -> None:
    """Validatsiya yoqilganda taqiqlangan o'tish obyektni O'ZGARTIRMAYDI."""
    job = make_job(status=JobStatus.SUCCESS)
    with pytest.raises(InvalidStateTransitionError):
        apply_transition(job, JobStatus.RUNNING)
    assert job.status is JobStatus.SUCCESS
    assert job.started_at is None


def test_apply_transition_validate_false_majburan_otkazadi() -> None:
    """`validate=False` — admin amallari uchun grafik chetlab o'tiladi."""
    job = make_job(status=JobStatus.SUCCESS)
    apply_transition(job, JobStatus.QUEUED, validate=False, now=NOW)
    assert job.status is JobStatus.QUEUED
    assert job.queued_at == NOW


def test_apply_transition_notanish_maydonni_tashlab_ketadi() -> None:
    """Modelda yo'q maydon jim o'tkazib yuboriladi (`hasattr` tekshiruvi)."""
    job = make_job(status=JobStatus.PENDING)
    applied = apply_transition(job, JobStatus.QUEUED, now=NOW, yoq_maydon="x")
    assert applied["yoq_maydon"] == "x"
    assert not hasattr(job, "yoq_maydon")


def test_apply_transition_db_ga_yozmaydi() -> None:
    """Faqat Python obyekti o'zgaradi — `flush`/`commit` chaqiruvchida."""
    job = make_job(status=JobStatus.PENDING)
    apply_transition(job, JobStatus.QUEUED, now=NOW)
    # Obyekt hamon transient (sessiyaga qo'shilmagan)
    assert job.id is None


# ---------------------------------------------------------------------------
# Predikatlar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (JobStatus.PENDING, True),
        (JobStatus.QUEUED, True),
        (JobStatus.RUNNING, True),
        (JobStatus.RETRYING, True),
        (JobStatus.SUCCESS, False),
        (JobStatus.FAILED, False),
        (JobStatus.CANCELLED, True),  # bir xil holatga o'tish mumkin
        (JobStatus.DEAD_LETTER, False),
    ],
)
def test_is_cancellable(status: JobStatus, expected: bool) -> None:
    """Bekor qilish `CANCELLED` ga o'tish mumkinligi bilan AYNI narsa."""
    assert is_cancellable(status) is expected


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (JobStatus.PENDING, True),
        (JobStatus.QUEUED, False),  # faqat RUNNING/CANCELLED
        (JobStatus.RUNNING, True),
        (JobStatus.RETRYING, True),
        (JobStatus.FAILED, True),
        (JobStatus.DEAD_LETTER, True),
        (JobStatus.SUCCESS, False),
        (JobStatus.CANCELLED, False),
    ],
)
def test_is_retryable_status(status: JobStatus, expected: bool) -> None:
    """Qayta urinish — `QUEUED` yoki `RETRYING` ga o'tish mumkinligi."""
    assert is_retryable_status(status) is expected


@pytest.mark.parametrize("reason", [None, *list(FailureReason)])
def test_terminal_status_for_retries_left(reason: FailureReason | None) -> None:
    """Urinish qolgan bo'lsa `RETRYING`, qolmasa `DEAD_LETTER`."""
    assert terminal_status_for(reason, retries_left=True) is JobStatus.RETRYING
    assert terminal_status_for(reason, retries_left=False) is JobStatus.DEAD_LETTER


def test_terminal_status_for_natijasi_runningdan_otish_mumkin() -> None:
    """Natija har doim `RUNNING` dan qonuniy o'tish bo'lishi kerak."""
    for retries_left in (True, False):
        target = terminal_status_for(FailureReason.NON_ZERO_EXIT, retries_left=retries_left)
        if target is JobStatus.DEAD_LETTER:
            # `RUNNING -> DEAD_LETTER` grafikda yo'q: avval FAILED bo'ladi
            assert can_transition(JobStatus.FAILED, target) is True
        else:
            assert can_transition(JobStatus.RUNNING, target) is True
