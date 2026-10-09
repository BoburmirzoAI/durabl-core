"""Durabl — qayta urinish (retry) siyosati: eksponensial backoff + jitter.

Formula:

    delay = min(base * multiplier ** (attempt - 1), max_delay)
    jitter qo'shilsa: delay *= (1 ± jitter_ratio * random)

`attempt` 1'dan boshlanadi (birinchi qayta urinish).
Jitter "thundering herd" muammosini oldini oladi: 1000 job bir vaqtda
fail bo'lsa, ular bir vaqtda qayta urinmaydi.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime

from app.config import settings
from app.constants import FailureReason
from app.utils.time_utils import seconds_from_now

#: Qayta urinish befoyda bo'lgan sabablar — darhol DLQ'ga.
NON_RETRYABLE_REASONS: frozenset[FailureReason] = frozenset(
    {
        FailureReason.VALIDATION_ERROR,
        FailureReason.OOM,
        FailureReason.OUTPUT_TOO_LARGE,
        FailureReason.MAX_RETRIES_EXCEEDED,
    }
)


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Qayta urinish parametrlari to'plami."""

    max_retries: int = settings.DEFAULT_MAX_RETRIES
    base_delay: float = settings.RETRY_BASE_DELAY_SECONDS
    multiplier: float = settings.RETRY_MULTIPLIER
    max_delay: float = settings.RETRY_MAX_DELAY_SECONDS
    jitter: bool = settings.RETRY_JITTER
    jitter_ratio: float = settings.RETRY_JITTER_RATIO

    @classmethod
    def default(cls) -> RetryPolicy:
        """Sozlamalardan standart siyosat."""
        return cls()

    @classmethod
    def for_job(cls, max_retries: int | None) -> RetryPolicy:
        """Job'ning o'z `max_retries` qiymati bilan siyosat."""
        if max_retries is None:
            return cls.default()
        bounded = max(0, min(int(max_retries), settings.MAX_ALLOWED_RETRIES))
        return cls(max_retries=bounded)

    # ------------------------------------------------------------------

    def should_retry(
        self,
        attempt: int,
        *,
        failure_reason: FailureReason | None = None,
        retryable: bool = True,
    ) -> bool:
        """Yana urinish kerakmi?

        Args:
            attempt: Shu paytgacha bo'lib o'tgan urinishlar soni (1 = birinchi bajarish).
            failure_reason: Nega fail bo'ldi.
            retryable: Xato o'zi qayta urinishga yaroqlimi (ExecutionError.retryable).
        """
        if not retryable:
            return False
        if failure_reason is not None and failure_reason in NON_RETRYABLE_REASONS:
            return False
        return attempt <= self.max_retries

    def compute_delay(self, attempt: int) -> float:
        """`attempt`-urinishdan keyin qancha kutish kerak (soniya).

        attempt=1 -> base, attempt=2 -> base*m, attempt=3 -> base*m^2 ...
        """
        if attempt < 1:
            attempt = 1
        raw = self.base_delay * (self.multiplier ** (attempt - 1))
        delay = min(raw, self.max_delay)
        if self.jitter and self.jitter_ratio > 0:
            spread = delay * self.jitter_ratio
            delay = delay + random.uniform(-spread, spread)
        return max(0.0, round(delay, 3))

    def next_retry_at(self, attempt: int) -> datetime:
        """Keyingi urinish vaqti (UTC) — scheduler ZSET'iga score sifatida yoziladi."""
        return seconds_from_now(self.compute_delay(attempt))

    def schedule(self, attempt: int) -> tuple[float, datetime]:
        """`(delay_seconds, next_retry_at)` juftligi."""
        delay = self.compute_delay(attempt)
        return delay, seconds_from_now(delay)

    def attempts_remaining(self, attempt: int) -> int:
        """Yana nechta urinish qolgan."""
        return max(0, self.max_retries - attempt + 1)


def compute_backoff(
    attempt: int,
    *,
    base_delay: float | None = None,
    multiplier: float | None = None,
    max_delay: float | None = None,
    jitter: bool | None = None,
) -> float:
    """Tez chaqiruv uchun qisqa funksiya (webhook sender ham ishlatadi)."""
    policy = RetryPolicy(
        base_delay=base_delay if base_delay is not None else settings.RETRY_BASE_DELAY_SECONDS,
        multiplier=multiplier if multiplier is not None else settings.RETRY_MULTIPLIER,
        max_delay=max_delay if max_delay is not None else settings.RETRY_MAX_DELAY_SECONDS,
        jitter=jitter if jitter is not None else settings.RETRY_JITTER,
    )
    return policy.compute_delay(attempt)


def webhook_policy() -> RetryPolicy:
    """Webhook yuborish uchun alohida (uzoqroq) siyosat."""
    return RetryPolicy(
        max_retries=settings.WEBHOOK_MAX_RETRIES,
        base_delay=settings.WEBHOOK_BASE_DELAY_SECONDS,
        multiplier=settings.RETRY_MULTIPLIER,
        max_delay=settings.WEBHOOK_MAX_DELAY_SECONDS,
        jitter=settings.RETRY_JITTER,
    )


__all__ = [
    "NON_RETRYABLE_REASONS",
    "RetryPolicy",
    "compute_backoff",
    "webhook_policy",
]
