"""Durabl — `app/utils/retry_policy.py` birlik testlari.

Backoff formulasi ikki xususiyatga ega bo'lishi kerak:

* **Aniq** — jitter o'chirilganda qiymatlar 1, 2, 4, 8, 16 ... ketma-ketligi
  bo'yicha o'sadi va `max_delay` da to'xtaydi. Aks holda retry "cheksiz
  kutish" ga aylanadi.
* **Tarqoq** — jitter yoqilganda `±jitter_ratio` oralig'ida chetga chiqadi,
  shu tufayli bir vaqtda yiqilgan ming job bir vaqtda qayta urinmaydi
  ("thundering herd").

`should_retry()` esa qayta urinish BEFOYDA bo'lgan holatlarni (sintaksis
xatosi, OOM, chiqish hajmi) darhol rad etishi kerak — ular har urinishda
AYNI natijani beradi.
"""

from __future__ import annotations

import pytest
from app.config import settings
from app.constants import FailureReason
from app.utils.retry_policy import (
    NON_RETRYABLE_REASONS,
    RetryPolicy,
    compute_backoff,
    webhook_policy,
)
from app.utils.time_utils import utcnow

pytestmark = pytest.mark.unit

#: Jitter'siz, aniq qiymatli siyosat — hisob-kitobni tekshirish uchun.
EXACT = RetryPolicy(max_retries=5, base_delay=1.0, multiplier=2.0, max_delay=300.0, jitter=False)


# ---------------------------------------------------------------------------
# compute_delay — aniq qiymatlar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [(1, 1.0), (2, 2.0), (3, 4.0), (4, 8.0), (5, 16.0), (6, 32.0)],
)
def test_compute_delay_eksponensial_ketma_ketlik(attempt: int, expected: float) -> None:
    """Jitter'siz: 1, 2, 4, 8, 16, 32 — har qadamda ikki barobar."""
    assert EXACT.compute_delay(attempt) == expected


def test_compute_delay_max_delay_bilan_cheklanadi() -> None:
    """Katta `attempt` da kutish `max_delay` dan oshmaydi."""
    policy = RetryPolicy(base_delay=1.0, multiplier=2.0, max_delay=10.0, jitter=False)
    assert policy.compute_delay(10) == 10.0
    assert policy.compute_delay(100) == 10.0


@pytest.mark.parametrize("attempt", [0, -1, -100])
def test_compute_delay_notogri_attempt_birga_tenglashtiriladi(attempt: int) -> None:
    """`attempt < 1` kelsa `1` deb olinadi (manfiy kutish bo'lmaydi)."""
    assert EXACT.compute_delay(attempt) == EXACT.compute_delay(1)


def test_compute_delay_boshqa_multiplier() -> None:
    """Ko'paytiruvchi sozlanadi (webhook uchun boshqa egri chiziq)."""
    policy = RetryPolicy(base_delay=2.0, multiplier=3.0, max_delay=1000.0, jitter=False)
    assert policy.compute_delay(1) == 2.0
    assert policy.compute_delay(2) == 6.0
    assert policy.compute_delay(3) == 18.0


# ---------------------------------------------------------------------------
# Jitter
# ---------------------------------------------------------------------------


def test_jitter_diapazondan_chiqmaydi() -> None:
    """Jitter qiymatni `±25%` oralig'ida ushlab turadi."""
    policy = RetryPolicy(base_delay=10.0, multiplier=1.0, jitter=True, jitter_ratio=0.25)
    values = [policy.compute_delay(1) for _ in range(200)]
    assert all(7.5 <= value <= 12.5 for value in values)


def test_jitter_qiymatlarni_tarqatadi() -> None:
    """200 chaqiruvda kamida bir nechta TURLI qiymat chiqishi kerak."""
    policy = RetryPolicy(base_delay=10.0, multiplier=1.0, jitter=True, jitter_ratio=0.25)
    assert len({policy.compute_delay(1) for _ in range(200)}) > 10


def test_jitter_ochirilganda_qiymat_barqaror() -> None:
    """`jitter=False` — har chaqiruvda AYNI qiymat (test qilish mumkin)."""
    assert len({EXACT.compute_delay(3) for _ in range(50)}) == 1


def test_jitter_ratio_nol_bolsa_jitter_qollanmaydi() -> None:
    """`jitter_ratio=0` jitter yoqilgan bo'lsa ham qiymatni o'zgartirmaydi."""
    policy = RetryPolicy(base_delay=5.0, multiplier=1.0, jitter=True, jitter_ratio=0.0)
    assert policy.compute_delay(1) == 5.0


def test_jitter_manfiy_qiymat_bermaydi() -> None:
    """Keng jitter ham manfiy kutish bermaydi (`max(0.0, ...)`)."""
    policy = RetryPolicy(base_delay=1.0, multiplier=1.0, jitter=True, jitter_ratio=5.0)
    assert all(policy.compute_delay(1) >= 0.0 for _ in range(100))


# ---------------------------------------------------------------------------
# should_retry — barcha tarmoqlar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("attempt", [1, 2, 3])
def test_should_retry_limit_ichida_true(attempt: int) -> None:
    """Urinish soni `max_retries` dan oshmaganda qayta urinish mumkin."""
    policy = RetryPolicy(max_retries=3)
    assert policy.should_retry(attempt) is True


@pytest.mark.parametrize("attempt", [4, 5, 100])
def test_should_retry_limit_oshsa_false(attempt: int) -> None:
    """Urinishlar tugaganda retry yo'q — job DLQ'ga ketadi."""
    policy = RetryPolicy(max_retries=3)
    assert policy.should_retry(attempt) is False


def test_should_retry_retryable_false_ustun_turadi() -> None:
    """`retryable=False` (xato o'zi takrorlanmaydigan) — limitdan ham ustun."""
    assert RetryPolicy(max_retries=10).should_retry(1, retryable=False) is False


@pytest.mark.parametrize("reason", sorted(NON_RETRYABLE_REASONS))
def test_should_retry_qayta_urilmaydigan_sabablar(reason: FailureReason) -> None:
    """Validatsiya/OOM/chiqish hajmi/urinishlar tugashi — darhol DLQ."""
    assert RetryPolicy(max_retries=10).should_retry(1, failure_reason=reason) is False


@pytest.mark.parametrize(
    "reason",
    [
        FailureReason.NON_ZERO_EXIT,
        FailureReason.TIMEOUT,
        FailureReason.SANDBOX_ERROR,
        FailureReason.LEASE_LOST,
        FailureReason.INTERNAL_ERROR,
    ],
)
def test_should_retry_qayta_urinishga_yaroqli_sabablar(reason: FailureReason) -> None:
    """Vaqtinchalik xatolar (timeout, sandbox, lease) qayta urinishga yaroqli."""
    assert RetryPolicy(max_retries=3).should_retry(1, failure_reason=reason) is True


def test_should_retry_max_retries_nol() -> None:
    """`max_retries=0` — birinchi xatodan keyin darhol DLQ."""
    assert RetryPolicy(max_retries=0).should_retry(1) is False


def test_non_retryable_reasons_tarkibi() -> None:
    """To'plam shartnomadagi to'rt sababdan iborat."""
    assert NON_RETRYABLE_REASONS == frozenset(
        {
            FailureReason.VALIDATION_ERROR,
            FailureReason.OOM,
            FailureReason.OUTPUT_TOO_LARGE,
            FailureReason.MAX_RETRIES_EXCEEDED,
        }
    )


# ---------------------------------------------------------------------------
# default / for_job
# ---------------------------------------------------------------------------


def test_default_sozlamadan_oladi() -> None:
    """`default()` sozlama qiymatlarini oladi."""
    policy = RetryPolicy.default()
    assert policy.max_retries == settings.DEFAULT_MAX_RETRIES
    assert policy.base_delay == settings.RETRY_BASE_DELAY_SECONDS
    assert policy.multiplier == settings.RETRY_MULTIPLIER


def test_for_job_none_default_bilan_ayni() -> None:
    """Job'da qiymat bo'lmasa standart siyosat ishlatiladi."""
    assert RetryPolicy.for_job(None) == RetryPolicy.default()


@pytest.mark.parametrize("value", [0, 1, 5, 10])
def test_for_job_chegara_ichidagi_qiymat_saqlanadi(value: int) -> None:
    """Chegara ichidagi qiymat o'zgarmaydi."""
    assert RetryPolicy.for_job(value).max_retries == value


def test_for_job_manfiy_qiymat_nolga_qisqaradi() -> None:
    """Manfiy qiymat `0` ga keltiriladi (manfiy urinish bo'lmaydi)."""
    assert RetryPolicy.for_job(-5).max_retries == 0


def test_for_job_juda_katta_qiymat_cheklanadi() -> None:
    """Juda katta qiymat `MAX_ALLOWED_RETRIES` ga qisqartiriladi."""
    assert RetryPolicy.for_job(10_000).max_retries == settings.MAX_ALLOWED_RETRIES


# ---------------------------------------------------------------------------
# next_retry_at / schedule / attempts_remaining
# ---------------------------------------------------------------------------


def test_next_retry_at_kelajakda_va_aware() -> None:
    """Keyingi urinish vaqti — timezone-aware va kelajakda."""
    moment = EXACT.next_retry_at(1)
    assert moment.tzinfo is not None
    assert moment > utcnow()


def test_schedule_juftlik_mos_keladi() -> None:
    """`schedule()` qaytargan kechikish va vaqt bir-biriga mos."""
    delay, moment = EXACT.schedule(3)
    assert delay == 4.0
    assert 3.0 <= (moment - utcnow()).total_seconds() <= 4.5


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [(1, 3), (2, 2), (3, 1), (4, 0), (10, 0)],
)
def test_attempts_remaining(attempt: int, expected: int) -> None:
    """Qolgan urinishlar soni nolga kelib to'xtaydi (manfiy bo'lmaydi)."""
    assert RetryPolicy(max_retries=3).attempts_remaining(attempt) == expected


# ---------------------------------------------------------------------------
# compute_backoff
# ---------------------------------------------------------------------------


def test_compute_backoff_sozlamalarni_qabul_qiladi() -> None:
    """Qisqa funksiya siyosat yasamasdan ayni formulani beradi."""
    assert compute_backoff(3, base_delay=1.0, multiplier=2.0, jitter=False) == 4.0


def test_compute_backoff_max_delay_bilan_cheklanadi() -> None:
    """`max_delay` qisqa funksiyada ham ishlaydi."""
    assert compute_backoff(10, base_delay=1.0, max_delay=5.0, jitter=False) == 5.0


def test_compute_backoff_siyosat_bilan_ayni_natija() -> None:
    """`compute_backoff` va `RetryPolicy.compute_delay` bir xil hisoblaydi."""
    for attempt in range(1, 7):
        assert compute_backoff(attempt, jitter=False) == RetryPolicy(jitter=False).compute_delay(
            attempt
        )


# ---------------------------------------------------------------------------
# webhook_policy
# ---------------------------------------------------------------------------


def test_webhook_policy_sozlamalardan_oladi() -> None:
    """Webhook siyosati o'z sozlamalaridan yasaladi (uzoqroq kutish)."""
    policy = webhook_policy()
    assert policy.max_retries == settings.WEBHOOK_MAX_RETRIES
    assert policy.base_delay == settings.WEBHOOK_BASE_DELAY_SECONDS
    assert policy.max_delay == settings.WEBHOOK_MAX_DELAY_SECONDS


def test_webhook_policy_job_siyosatidan_uzoqroq_kutadi() -> None:
    """Webhook qabul qiluvchisi tiklanishi uchun chegara job'dan kattaroq."""
    assert webhook_policy().max_delay > RetryPolicy.default().max_delay


def test_webhook_policy_jitterisiz_qiymatlari() -> None:
    """Jitter'siz webhook egri chizig'i: 2, 4, 8, 16 ..."""
    policy = RetryPolicy(
        max_retries=settings.WEBHOOK_MAX_RETRIES,
        base_delay=settings.WEBHOOK_BASE_DELAY_SECONDS,
        multiplier=settings.RETRY_MULTIPLIER,
        max_delay=settings.WEBHOOK_MAX_DELAY_SECONDS,
        jitter=False,
    )
    assert [policy.compute_delay(attempt) for attempt in range(1, 5)] == [2.0, 4.0, 8.0, 16.0]


# ---------------------------------------------------------------------------
# Dataclass xususiyatlari
# ---------------------------------------------------------------------------


def test_siyosat_ozgarmas() -> None:
    """`frozen=True` — siyosatni tasodifan o'zgartirib bo'lmaydi."""
    policy = RetryPolicy.default()
    with pytest.raises(AttributeError):
        policy.max_retries = 99  # type: ignore[misc]
