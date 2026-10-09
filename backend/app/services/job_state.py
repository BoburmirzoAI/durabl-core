"""Durabl — job holat mashinasi (toza funksiyalar, bog'liqliksiz).

Nega alohida modul? `job_service` va `reliability_service` IKKISI ham job
holatini o'zgartiradi. Agar biri ikkinchisini import qilsa aylanma bog'liqlik
yuzaga keladi. Shuning uchun holat o'tishi mantig'i shu neytral modulda:
ikki service ham shuni chaqiradi.

Holat grafigi `app.constants.JOB_STATUS_TRANSITIONS` da ta'riflangan.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.constants import JOB_STATUS_TRANSITIONS, FailureReason, JobStatus
from app.exceptions import InvalidStateTransitionError
from app.utils.time_utils import utcnow

if TYPE_CHECKING:
    from app.models.job import Job


def can_transition(current: JobStatus | str, target: JobStatus | str) -> bool:
    """`current` holatidan `target` holatiga o'tish ruxsat etilganmi?

    Bir xil holatga o'tish (idempotent qayta yozish) har doim ruxsat etiladi —
    bu takroriy xabar yoki qayta ishlangan hodisada muammo bo'lmasligi uchun.
    """
    current_status = JobStatus(current)
    target_status = JobStatus(target)
    if current_status is target_status:
        return True
    return target_status in JOB_STATUS_TRANSITIONS.get(current_status, frozenset())


def assert_transition(current: JobStatus | str, target: JobStatus | str) -> None:
    """O'tish ruxsat etilmagan bo'lsa `InvalidStateTransitionError` tashlaydi."""
    if not can_transition(current, target):
        raise InvalidStateTransitionError(JobStatus(current), JobStatus(target))


def allowed_targets(current: JobStatus | str) -> frozenset[JobStatus]:
    """Berilgan holatdan o'tish mumkin bo'lgan holatlar."""
    return JOB_STATUS_TRANSITIONS.get(JobStatus(current), frozenset())


# ---------------------------------------------------------------------------
# Holat o'zgarishida avtomatik to'ldiriladigan vaqt maydonlari
# ---------------------------------------------------------------------------

#: Qaysi holatga o'tganda qaysi vaqt ustuni to'ldiriladi.
_TIMESTAMP_FIELD: dict[JobStatus, str] = {
    JobStatus.QUEUED: "queued_at",
    JobStatus.RUNNING: "started_at",
    JobStatus.SUCCESS: "finished_at",
    JobStatus.FAILED: "finished_at",
    JobStatus.CANCELLED: "cancelled_at",
    JobStatus.DEAD_LETTER: "finished_at",
}


def transition_fields(
    target: JobStatus | str,
    *,
    now: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    """Holat o'zgarishi uchun yangilanadigan maydonlar lug'atini yasaydi.

    Vaqt ustuni avtomatik qo'shiladi (`queued_at`, `started_at`, ...), lekin
    `extra` da ochiq berilgan qiymat ustun turadi.

    Misol:
        fields = transition_fields(JobStatus.RUNNING)
        # {"status": JobStatus.RUNNING, "started_at": datetime(...)}
    """
    target_status = JobStatus(target)
    timestamp = now or utcnow()
    fields: dict[str, Any] = {"status": target_status}

    field_name = _TIMESTAMP_FIELD.get(target_status)
    if field_name is not None:
        fields[field_name] = timestamp

    fields.update(extra)
    return fields


def apply_transition(
    job: Job,
    target: JobStatus | str,
    *,
    validate: bool = True,
    now: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    """Job obyektiga holat o'zgarishini qo'llaydi (DB'ga yozmaydi).

    Faqat Python obyektini o'zgartiradi — `flush`/`commit` chaqiruvchi
    service'ning mas'uliyatida. Qo'llanilgan maydonlar lug'ati qaytariladi
    (log va hodisa uchun qulay).

    Args:
        job: `Job` modeli.
        target: Yangi holat.
        validate: `False` bo'lsa holat grafigini tekshirmaydi (DLQ'dan
            majburiy tiklash kabi admin amallari uchun).
        now: Vaqtni ochiq berish (testlar uchun).
        **extra: Qo'shimcha maydonlar (`error`, `failure_reason`, ...).
    """
    if validate:
        assert_transition(job.status, target)

    fields = transition_fields(target, now=now, **extra)
    for key, value in fields.items():
        if hasattr(job, key):
            setattr(job, key, value)
    return fields


# ---------------------------------------------------------------------------
# Yordamchi predikatlar
# ---------------------------------------------------------------------------


def is_cancellable(status: JobStatus | str) -> bool:
    """Job'ni bekor qilish mumkinmi?"""
    return can_transition(status, JobStatus.CANCELLED)


def is_retryable_status(status: JobStatus | str) -> bool:
    """Shu holatdan qayta urinishga o'tish mumkinmi?"""
    targets = allowed_targets(JobStatus(status))
    return JobStatus.QUEUED in targets or JobStatus.RETRYING in targets


def terminal_status_for(failure_reason: FailureReason | None, *, retries_left: bool) -> JobStatus:
    """Xato sababiga qarab keyingi holatni tanlaydi.

    `retries_left=True` -> `RETRYING` (backoff kutiladi),
    aks holda -> `DEAD_LETTER` (DLQ'ga tushadi).

    `failure_reason` hozircha qarorга ta'sir qilmaydi, lekin imzoda
    saqlanadi: `reliability_service` kelajakda sabab bo'yicha boshqa
    siyosat qo'llashi mumkin (masalan OOM uchun darhol DLQ).
    """
    return JobStatus.RETRYING if retries_left else JobStatus.DEAD_LETTER


__all__ = [
    "allowed_targets",
    "apply_transition",
    "assert_transition",
    "can_transition",
    "is_cancellable",
    "is_retryable_status",
    "terminal_status_for",
    "transition_fields",
]
