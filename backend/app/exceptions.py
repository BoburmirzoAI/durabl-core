"""Durabl — barcha maxsus (custom) xato klasslari.

Qoida: service va repository qatlamlari HTTPException tashlamaydi — faqat shu
yerdagi domen xatolarini tashlaydi. `main.py`dagi exception handler ularni
HTTP javobiga aylantiradi. Shu tufayli biznes logika FastAPI'ga bog'liq emas
va worker protsesslarida ham ayni shu xatolar ishlaydi.
"""

from __future__ import annotations

from typing import Any

from app.constants import FailureReason, JobStatus

# ---------------------------------------------------------------------------
# Bazaviy xato
# ---------------------------------------------------------------------------


class DurablError(Exception):
    """Barcha Durabl xatolarining ildizi.

    Attributes:
        message: Inson o'qiy oladigan xabar.
        code: Mijoz kodida tekshirish uchun barqaror mashina kodi (SCREAMING_SNAKE).
        status_code: Mos HTTP status.
        details: Qo'shimcha kontekst (javobda `details` sifatida qaytadi).
    """

    message: str = "Ichki xato yuz berdi"
    code: str = "INTERNAL_ERROR"
    status_code: int = 500

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.__class__.message
        self.code = code or self.__class__.code
        self.status_code = status_code or self.__class__.status_code
        self.details: dict[str, Any] = details or {}
        super().__init__(self.message)

    def to_dict(self) -> dict[str, Any]:
        """ErrorResponse schema'siga mos lug'at."""
        payload: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.details:
            payload["details"] = self.details
        return payload

    def __repr__(self) -> str:  # pragma: no cover - debug yordamchisi
        return f"{type(self).__name__}(code={self.code!r}, message={self.message!r})"


# ---------------------------------------------------------------------------
# 4xx — mijoz xatolari
# ---------------------------------------------------------------------------


class ValidationError(DurablError):
    """So'rov ma'lumotlari biznes qoidalariga mos emas."""

    message = "Yuborilgan ma'lumot noto'g'ri"
    code = "VALIDATION_ERROR"
    status_code = 422


class BadRequestError(DurablError):
    message = "So'rov noto'g'ri shakllantirilgan"
    code = "BAD_REQUEST"
    status_code = 400


class AuthenticationError(DurablError):
    """Kim ekanligi aniqlanmadi (token yo'q/yaroqsiz)."""

    message = "Autentifikatsiya talab qilinadi"
    code = "AUTHENTICATION_REQUIRED"
    status_code = 401


class InvalidCredentialsError(AuthenticationError):
    message = "Email yoki parol noto'g'ri"
    code = "INVALID_CREDENTIALS"


class TokenExpiredError(AuthenticationError):
    message = "Token muddati tugagan"
    code = "TOKEN_EXPIRED"


class InvalidTokenError(AuthenticationError):
    message = "Token yaroqsiz"
    code = "INVALID_TOKEN"


class InvalidApiKeyError(AuthenticationError):
    message = "API kalit yaroqsiz yoki bekor qilingan"
    code = "INVALID_API_KEY"


class PermissionDeniedError(DurablError):
    """Kim ekani ma'lum, lekin huquqi yetmaydi."""

    message = "Bu amalni bajarishga ruxsatingiz yo'q"
    code = "PERMISSION_DENIED"
    status_code = 403


class AdminRequiredError(PermissionDeniedError):
    message = "Bu endpoint faqat administratorlar uchun"
    code = "ADMIN_REQUIRED"


class InactiveUserError(PermissionDeniedError):
    message = "Hisob faolsizlantirilgan"
    code = "INACTIVE_USER"


class NotFoundError(DurablError):
    """Resurs topilmadi (yoki boshqa foydalanuvchiga tegishli)."""

    message = "Resurs topilmadi"
    code = "NOT_FOUND"
    status_code = 404

    def __init__(
        self,
        resource: str = "Resurs",
        identifier: Any = None,
        **kwargs: Any,
    ) -> None:
        msg = (
            f"{resource} topilmadi" if identifier is None else f"{resource} topilmadi: {identifier}"
        )
        details = kwargs.pop("details", {}) or {}
        details.setdefault("resource", resource)
        if identifier is not None:
            details.setdefault("identifier", str(identifier))
        super().__init__(msg, details=details, **kwargs)


class UserNotFoundError(NotFoundError):
    code = "USER_NOT_FOUND"

    def __init__(self, identifier: Any = None, **kwargs: Any) -> None:
        super().__init__("Foydalanuvchi", identifier, **kwargs)


class JobNotFoundError(NotFoundError):
    code = "JOB_NOT_FOUND"

    def __init__(self, identifier: Any = None, **kwargs: Any) -> None:
        super().__init__("Job", identifier, **kwargs)


class ExecutionNotFoundError(NotFoundError):
    code = "EXECUTION_NOT_FOUND"

    def __init__(self, identifier: Any = None, **kwargs: Any) -> None:
        super().__init__("Bajarish", identifier, **kwargs)


class WebhookNotFoundError(NotFoundError):
    code = "WEBHOOK_NOT_FOUND"

    def __init__(self, identifier: Any = None, **kwargs: Any) -> None:
        super().__init__("Webhook", identifier, **kwargs)


class ApiKeyNotFoundError(NotFoundError):
    code = "API_KEY_NOT_FOUND"

    def __init__(self, identifier: Any = None, **kwargs: Any) -> None:
        super().__init__("API kalit", identifier, **kwargs)


class DlqEntryNotFoundError(NotFoundError):
    code = "DLQ_ENTRY_NOT_FOUND"

    def __init__(self, identifier: Any = None, **kwargs: Any) -> None:
        super().__init__("DLQ yozuvi", identifier, **kwargs)


class ConflictError(DurablError):
    """Resurs holati amalga qarshi (409)."""

    message = "Resurs holati bu amalga mos emas"
    code = "CONFLICT"
    status_code = 409


class DuplicateEmailError(ConflictError):
    message = "Bu email allaqachon ro'yxatdan o'tgan"
    code = "DUPLICATE_EMAIL"


class IdempotencyConflictError(ConflictError):
    """Bir xil Idempotency-Key, lekin so'rov tanasi boshqa."""

    message = (
        "Bu Idempotency-Key boshqa so'rov tanasi bilan ishlatilgan. "
        "Yangi kalit yuboring yoki avvalgi so'rovni aynan takrorlang."
    )
    code = "IDEMPOTENCY_CONFLICT"

    def __init__(self, key: str | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}) or {}
        if key:
            details.setdefault("idempotency_key", key)
        super().__init__(details=details, **kwargs)


class IdempotencyInProgressError(ConflictError):
    """Ayni shu kalit bilan so'rov hozir qayta ishlanmoqda."""

    message = (
        "Bu Idempotency-Key bilan so'rov hozir bajarilmoqda, birozdan keyin qayta urinib ko'ring"
    )
    code = "IDEMPOTENCY_IN_PROGRESS"


class InvalidStateTransitionError(ConflictError):
    """Job holatini ruxsat etilmagan holatga o'tkazishga urinish."""

    code = "INVALID_STATE_TRANSITION"

    def __init__(
        self,
        current: JobStatus | str,
        target: JobStatus | str,
        **kwargs: Any,
    ) -> None:
        details = kwargs.pop("details", {}) or {}
        details.setdefault("current_status", str(current))
        details.setdefault("target_status", str(target))
        super().__init__(
            f"Job holatini '{current}' dan '{target}' ga o'tkazish mumkin emas",
            details=details,
            **kwargs,
        )


class JobNotCancellableError(ConflictError):
    code = "JOB_NOT_CANCELLABLE"

    def __init__(self, status: JobStatus | str, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}) or {}
        details.setdefault("status", str(status))
        super().__init__(
            f"Job '{status}' holatida — bekor qilish mumkin emas",
            details=details,
            **kwargs,
        )


class ApiKeyScopeError(PermissionDeniedError):
    """API kalitning ruxsat doirasi yetarli emas (403).

    `AdminRequiredError` dan farqi: u FOYDALANUVCHINING roli haqida,
    bu esa KALITNING huquqlari haqida. Mijoz admin bo'lishi mumkin,
    lekin kaliti tor doira bilan yaratilgan bo'lsa ham rad etiladi —
    aynan shu scope'ning maqsadi.
    """

    code = "API_KEY_SCOPE_REQUIRED"

    def __init__(self, *, required: str, granted: list[str], **kwargs: Any) -> None:
        details = kwargs.pop("details", {}) or {}
        details.setdefault("required_scope", required)
        details.setdefault("granted_scopes", granted)
        super().__init__(
            f"Bu amal uchun kalitga '{required}' ruxsati kerak",
            details=details,
            **kwargs,
        )


class ApiKeyRevokedError(ConflictError):
    code = "API_KEY_REVOKED"
    message = "Kalit bekor qilingan — huquq, muddat va rotatsiya amallari qo'llanmaydi"


class JobNotRetryableError(ConflictError):
    code = "JOB_NOT_RETRYABLE"
    message = "Bu job'ni qayta urinib ko'rish mumkin emas"


class DlqEntryAlreadyResolvedError(ConflictError):
    code = "DLQ_ALREADY_RESOLVED"
    message = "Bu DLQ yozuvi allaqachon hal qilingan"


class ResultNotReadyError(DurablError):
    """Job hali tugamagan — natija yo'q."""

    code = "RESULT_NOT_READY"
    status_code = 409

    def __init__(self, status: JobStatus | str, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}) or {}
        details.setdefault("status", str(status))
        super().__init__(
            f"Job hali tugamagan (holat: {status}) — natija mavjud emas",
            details=details,
            **kwargs,
        )


class RateLimitExceededError(DurablError):
    """So'rov chastotasi limiti oshdi (429)."""

    message = "So'rov limiti oshdi"
    code = "RATE_LIMIT_EXCEEDED"
    status_code = 429

    def __init__(
        self,
        limit: int | None = None,
        retry_after: int | None = None,
        **kwargs: Any,
    ) -> None:
        details = kwargs.pop("details", {}) or {}
        if limit is not None:
            details.setdefault("limit", limit)
        if retry_after is not None:
            details.setdefault("retry_after_seconds", retry_after)
        self.retry_after = retry_after
        super().__init__(details=details, **kwargs)


class QuotaExceededError(DurablError):
    """Oylik reja kvotasi tugadi (402 — to'lov talab qilinadi)."""

    message = "Rejangiz kvotasi tugadi"
    code = "QUOTA_EXCEEDED"
    status_code = 402

    def __init__(
        self,
        used: int | None = None,
        limit: int | None = None,
        plan: str | None = None,
        **kwargs: Any,
    ) -> None:
        details = kwargs.pop("details", {}) or {}
        for key, value in (("used", used), ("limit", limit), ("plan", plan)):
            if value is not None:
                details.setdefault(key, value)
        super().__init__(details=details, **kwargs)


class ConcurrencyLimitError(DurablError):
    """Bir vaqtda bajarilayotgan job'lar soni limiti."""

    message = "Bir vaqtda bajarilayotgan job'lar limiti oshdi"
    code = "CONCURRENCY_LIMIT_EXCEEDED"
    status_code = 429


class PayloadTooLargeError(DurablError):
    message = "Yuborilgan ma'lumot juda katta"
    code = "PAYLOAD_TOO_LARGE"
    status_code = 413

    def __init__(self, size: int | None = None, limit: int | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}) or {}
        if size is not None:
            details.setdefault("size_bytes", size)
        if limit is not None:
            details.setdefault("limit_bytes", limit)
        super().__init__(details=details, **kwargs)


# ---------------------------------------------------------------------------
# Kod validatsiyasi va xavfsizlik
# ---------------------------------------------------------------------------


class CodeValidationError(ValidationError):
    """Mijoz kodi statik tekshiruvdan o'tmadi."""

    message = "Kod xavfsizlik tekshiruvidan o'tmadi"
    code = "CODE_VALIDATION_FAILED"

    def __init__(
        self,
        reason: str | None = None,
        violations: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        details = kwargs.pop("details", {}) or {}
        if violations:
            details.setdefault("violations", violations)
        super().__init__(reason or self.__class__.message, details=details, **kwargs)


class CodeSyntaxError(CodeValidationError):
    message = "Kodda sintaksis xatosi bor"
    code = "CODE_SYNTAX_ERROR"


class UnsupportedRuntimeError(ValidationError):
    code = "UNSUPPORTED_RUNTIME"

    def __init__(self, runtime: str, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}) or {}
        details.setdefault("runtime", runtime)
        super().__init__(f"'{runtime}' muhiti qo'llab-quvvatlanmaydi", details=details, **kwargs)


# ---------------------------------------------------------------------------
# Bajarish (execution) xatolari — bular retry/DLQ qaroriga ta'sir qiladi
# ---------------------------------------------------------------------------


class ExecutionError(DurablError):
    """Bajarish davomida yuzaga kelgan xato.

    `failure_reason` DLQ'da tasniflash uchun, `retryable` esa qayta urinish
    kerakligini bildiradi.
    """

    message = "Job bajarilishida xato"
    code = "EXECUTION_ERROR"
    status_code = 500
    failure_reason: FailureReason = FailureReason.INTERNAL_ERROR
    retryable: bool = True

    def __init__(
        self,
        message: str | None = None,
        *,
        failure_reason: FailureReason | None = None,
        retryable: bool | None = None,
        exit_code: int | None = None,
        **kwargs: Any,
    ) -> None:
        self.failure_reason = failure_reason or self.__class__.failure_reason
        self.retryable = self.__class__.retryable if retryable is None else retryable
        self.exit_code = exit_code
        details = kwargs.pop("details", {}) or {}
        details.setdefault("failure_reason", self.failure_reason.value)
        details.setdefault("retryable", self.retryable)
        if exit_code is not None:
            details.setdefault("exit_code", exit_code)
        super().__init__(message, details=details, **kwargs)


class ExecutionTimeoutError(ExecutionError):
    message = "Job vaqt limitidan oshdi"
    code = "EXECUTION_TIMEOUT"
    failure_reason = FailureReason.TIMEOUT
    retryable = True

    def __init__(self, timeout_seconds: float | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}) or {}
        if timeout_seconds is not None:
            details.setdefault("timeout_seconds", timeout_seconds)
        msg = (
            f"Job {timeout_seconds} soniyalik vaqt limitidan oshdi"
            if timeout_seconds is not None
            else None
        )
        super().__init__(msg, details=details, **kwargs)


class ExecutionFailedError(ExecutionError):
    """Mijoz kodi nolga teng bo'lmagan exit kod bilan tugadi."""

    message = "Kod xato bilan tugadi"
    code = "EXECUTION_FAILED"
    failure_reason = FailureReason.NON_ZERO_EXIT
    retryable = True


class OutOfMemoryError(ExecutionError):
    message = "Job xotira limitidan oshdi"
    code = "OUT_OF_MEMORY"
    failure_reason = FailureReason.OOM
    retryable = False  # Qayta urinish ham ayni natijani beradi


class OutputTooLargeError(ExecutionError):
    message = "Job chiqishi (stdout/stderr) juda katta"
    code = "OUTPUT_TOO_LARGE"
    failure_reason = FailureReason.OUTPUT_TOO_LARGE
    retryable = False


class SandboxError(ExecutionError):
    """Sandbox infratuzilmasi xatosi (mijoz kodi aybdor emas)."""

    message = "Sandbox yaratishda xato"
    code = "SANDBOX_ERROR"
    failure_reason = FailureReason.SANDBOX_ERROR
    retryable = True


class SandboxUnavailableError(SandboxError):
    message = "Sandbox muhiti mavjud emas (Docker/gVisor ishlamayapti)"
    code = "SANDBOX_UNAVAILABLE"
    status_code = 503


class SandboxStartupError(SandboxError):
    message = "Sandbox konteyneri ishga tushmadi"
    code = "SANDBOX_STARTUP_FAILED"


class LeaseLostError(ExecutionError):
    """Worker lease'ni yo'qotdi — job boshqa worker'ga o'tkaziladi."""

    message = "Job lease'i yo'qoldi (worker javob bermadi)"
    code = "LEASE_LOST"
    failure_reason = FailureReason.LEASE_LOST
    retryable = True


class LeaseNotAcquiredError(ConflictError):
    """Job'ni boshqa worker allaqachon olgan."""

    message = "Job lease'ini olish imkonsiz — boshqa worker ishlab turibdi"
    code = "LEASE_NOT_ACQUIRED"


class MaxRetriesExceededError(ExecutionError):
    message = "Barcha qayta urinishlar tugadi"
    code = "MAX_RETRIES_EXCEEDED"
    failure_reason = FailureReason.MAX_RETRIES_EXCEEDED
    retryable = False

    def __init__(self, attempts: int | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", {}) or {}
        if attempts is not None:
            details.setdefault("attempts", attempts)
        super().__init__(details=details, **kwargs)


class JobCancelledError(ExecutionError):
    message = "Job bekor qilindi"
    code = "JOB_CANCELLED"
    retryable = False


# ---------------------------------------------------------------------------
# Infratuzilma xatolari (5xx)
# ---------------------------------------------------------------------------


class InfrastructureError(DurablError):
    message = "Tashqi servis bilan aloqa xatosi"
    code = "INFRASTRUCTURE_ERROR"
    status_code = 503


class DatabaseError(InfrastructureError):
    message = "Ma'lumotlar bazasi xatosi"
    code = "DATABASE_ERROR"


class QueueError(InfrastructureError):
    message = "Navbat (Redis) xatosi"
    code = "QUEUE_ERROR"


class CacheError(InfrastructureError):
    message = "Cache xatosi"
    code = "CACHE_ERROR"


class WebhookDeliveryError(InfrastructureError):
    """Webhook yuborib bo'lmadi."""

    message = "Webhook yuborilmadi"
    code = "WEBHOOK_DELIVERY_FAILED"

    def __init__(
        self,
        url: str | None = None,
        status_code_received: int | None = None,
        **kwargs: Any,
    ) -> None:
        details = kwargs.pop("details", {}) or {}
        if url:
            details.setdefault("url", url)
        if status_code_received is not None:
            details.setdefault("response_code", status_code_received)
        super().__init__(details=details, **kwargs)


class WebhookUrlNotAllowedError(ValidationError):
    """SSRF himoyasi — mahalliy/ichki manzil."""

    message = "Bu webhook URL ruxsat etilmagan (ichki manzillar bloklangan)"
    code = "WEBHOOK_URL_NOT_ALLOWED"


class ServiceUnavailableError(InfrastructureError):
    message = "Servis vaqtincha mavjud emas"
    code = "SERVICE_UNAVAILABLE"


class NotImplementedFeatureError(DurablError):
    message = "Bu funksiya hali amalga oshirilmagan"
    code = "NOT_IMPLEMENTED"
    status_code = 501


__all__ = [
    "AdminRequiredError",
    "ApiKeyNotFoundError",
    "ApiKeyRevokedError",
    "ApiKeyScopeError",
    "AuthenticationError",
    "BadRequestError",
    "CacheError",
    "CodeSyntaxError",
    "CodeValidationError",
    "ConcurrencyLimitError",
    "ConflictError",
    "DatabaseError",
    "DlqEntryAlreadyResolvedError",
    "DlqEntryNotFoundError",
    "DuplicateEmailError",
    "DurablError",
    "ExecutionError",
    "ExecutionFailedError",
    "ExecutionNotFoundError",
    "ExecutionTimeoutError",
    "IdempotencyConflictError",
    "IdempotencyInProgressError",
    "InactiveUserError",
    "InfrastructureError",
    "InvalidApiKeyError",
    "InvalidCredentialsError",
    "InvalidStateTransitionError",
    "InvalidTokenError",
    "JobCancelledError",
    "JobNotCancellableError",
    "JobNotFoundError",
    "JobNotRetryableError",
    "LeaseLostError",
    "LeaseNotAcquiredError",
    "MaxRetriesExceededError",
    "NotFoundError",
    "NotImplementedFeatureError",
    "OutOfMemoryError",
    "OutputTooLargeError",
    "PayloadTooLargeError",
    "PermissionDeniedError",
    "QueueError",
    "QuotaExceededError",
    "RateLimitExceededError",
    "ResultNotReadyError",
    "SandboxError",
    "SandboxStartupError",
    "SandboxUnavailableError",
    "ServiceUnavailableError",
    "TokenExpiredError",
    "UnsupportedRuntimeError",
    "UserNotFoundError",
    "ValidationError",
    "WebhookDeliveryError",
    "WebhookNotFoundError",
    "WebhookUrlNotAllowedError",
]
