"""Durabl SDK xatolari.

Ierarxiya:

    DurablError                     — barcha SDK xatolarining ildizi
    ├── DurablConfigError           — noto'g'ri sozlama (lokal xato, server emas)
    ├── DurablConnectionError       — tarmoq ulanmadi (`ConnectionError` taxallusi)
    ├── DurablTimeoutError          — kutish vaqti tugadi (`TimeoutError` taxallusi)
    ├── JobFailedError              — job muvaffaqiyatsiz tugadi
    └── DurablAPIError              — server xato javob qaytardi (4xx/5xx)
        ├── ValidationError         — 400/413/422
        ├── AuthenticationError     — 401
        ├── PermissionDeniedError   — 403
        ├── NotFoundError           — 404
        ├── ConflictError           — 409
        │   └── ResultNotReadyError — job hali tugamagan (409 RESULT_NOT_READY)
        ├── QuotaExceededError      — 402 (oylik limit tugadi)
        ├── RateLimitError          — 429 (daqiqadagi limit)
        └── ServerError             — 5xx

Backend `{"error": {"code", "message", "details"}, "request_id"}` shaklida javob
beradi (CONTRACTS.md 12-bo'lim). `error_from_response()` shu `code` qiymatiga
qarab mos xato klassini tanlaydi — shuning uchun mijoz kodida `except
NotFoundError` kabi aniq tekshiruvlar yozish mumkin.

Diqqat: `TimeoutError` va `ConnectionError` nomlari Python'ning o'rnatilgan
xatolari bilan bir xil. Ular shu modul ichida ataylab shunday nomlangan (SDK
shartnomasi talabi), lekin ichki kodda chalkashmaslik uchun `DurablTimeoutError`
va `DurablConnectionError` taxalluslaridan foydalaniladi.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Ildiz xato
# ---------------------------------------------------------------------------


class DurablError(Exception):
    """Barcha Durabl SDK xatolarining ildizi.

    Mijoz butun SDK xatolarini bitta `except DurablError` bilan ushlashi mumkin.
    """

    #: Xato uchun standart xabar (voris klasslar almashtiradi).
    message = "Durabl SDK xatosi"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or type(self).message
        super().__init__(self.message)

    def __str__(self) -> str:
        return self.message


class DurablConfigError(DurablError):
    """Sozlama noto'g'ri yoki to'liq emas (masalan, API kalit berilmagan)."""

    message = "Durabl sozlamasi noto'g'ri"


class ConnectionError(DurablError):  # noqa: A001 - shartnoma bo'yicha shu nom talab qilinadi
    """Serverga ulanib bo'lmadi (DNS, TCP, TLS yoki tarmoq uzilishi)."""

    message = "Durabl serveriga ulanib bo'lmadi"


class TimeoutError(DurablError):  # noqa: A001 - shartnoma bo'yicha shu nom talab qilinadi
    """Kutish vaqti tugadi.

    Ikki holatda uchraydi:
      1. HTTP so'rov `config.timeout` ichida javob bermadi;
      2. `wait_for_result()` berilgan vaqt ichida job tugashini kutib ulgurmadi.
    """

    message = "Durabl so'rovi uchun kutish vaqti tugadi"


#: Ichki kodda ishlatish uchun xavfsiz taxalluslar (o'rnatilgan xatolar bilan
#: chalkashmaslik uchun).
DurablConnectionError = ConnectionError
DurablTimeoutError = TimeoutError


# ---------------------------------------------------------------------------
# Server qaytargan xatolar
# ---------------------------------------------------------------------------


class DurablAPIError(DurablError):
    """Server 4xx yoki 5xx javob qaytardi.

    Argumentlar:
        status_code: HTTP status kodi (berilmasa klass qiymati olinadi).
        code: Backend bergan barqaror mashina kodi, masalan `JOB_NOT_FOUND`.
        message: O'qishga qulay xabar.
        details: Qo'shimcha tafsilotlar (validatsiya xatolari ro'yxati va h.k.).
        request_id: Javobdagi `request_id` — qo'llab-quvvatlashga murojaat uchun.
    """

    message = "Durabl API xatosi"
    #: Voris klass uchun standart HTTP status.
    default_status_code = 500
    #: Voris klass uchun standart mashina kodi.
    default_code = "API_ERROR"

    def __init__(
        self,
        status_code: int | None = None,
        code: str | None = None,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        self.status_code = (
            int(status_code) if status_code is not None else type(self).default_status_code
        )
        self.code = code or type(self).default_code
        self.details: dict[str, Any] = details or {}
        self.request_id = request_id
        super().__init__(message or type(self).message)

    def __str__(self) -> str:
        parts = [f"[{self.status_code} {self.code}] {self.message}"]
        if self.request_id:
            parts.append(f"(request_id={self.request_id})")
        return " ".join(parts)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}(status_code={self.status_code!r}, code={self.code!r}, "
            f"message={self.message!r}, request_id={self.request_id!r})"
        )


class ValidationError(DurablAPIError):
    """So'rov ma'lumotlari serverning validatsiyasidan o'tmadi (400/413/422).

    Lokal tekshiruvlarda ham ishlatiladi (masalan, bo'sh kod yuborilganda) —
    bunda `status_code=422` va `code="VALIDATION_ERROR"` bo'ladi.
    """

    message = "So'rov ma'lumotlari noto'g'ri"
    default_status_code = 422
    default_code = "VALIDATION_ERROR"


class AuthenticationError(DurablAPIError):
    """API kalit yo'q, yaroqsiz yoki bekor qilingan (401)."""

    message = "Autentifikatsiya muvaffaqiyatsiz: API kalitni tekshiring"
    default_status_code = 401
    default_code = "AUTHENTICATION_REQUIRED"


class PermissionDeniedError(DurablAPIError):
    """Kalitda bu amal uchun ruxsat yo'q (403)."""

    message = "Bu amal uchun ruxsat yo'q"
    default_status_code = 403
    default_code = "PERMISSION_DENIED"


class NotFoundError(DurablAPIError):
    """So'ralgan resurs topilmadi (404)."""

    message = "Resurs topilmadi"
    default_status_code = 404
    default_code = "NOT_FOUND"


class ConflictError(DurablAPIError):
    """Resursning joriy holati bu amalga yo'l bermaydi (409)."""

    message = "Amal joriy holatda bajarilmaydi"
    default_status_code = 409
    default_code = "CONFLICT"


class ResultNotReadyError(ConflictError):
    """Job hali tugamagan — natija mavjud emas.

    `wait_for_result()` bu xatoni ichida ushlab, pollingni davom ettiradi.
    """

    message = "Job hali tugamadi, natija tayyor emas"
    default_code = "RESULT_NOT_READY"


class QuotaExceededError(DurablAPIError):
    """Rejadagi oylik job limiti tugadi (402)."""

    message = "Reja limiti tugadi: obunani yangilang"
    default_status_code = 402
    default_code = "QUOTA_EXCEEDED"


class RateLimitError(DurablAPIError):
    """So'rov tezligi limiti oshdi (429).

    `retry_after` — serverning `Retry-After` sarlavhasi yoki javob
    tafsilotidan olingan, necha soniyadan keyin qayta urinish mumkinligi.
    Chalkashmaslik uchun u faqat nomlangan argument sifatida beriladi:
    `RateLimitError(retry_after=5.0)`.
    """

    message = "So'rov tezligi limiti oshdi"
    default_status_code = 429
    default_code = "RATE_LIMIT_EXCEEDED"

    def __init__(
        self,
        status_code: int | None = None,
        code: str | None = None,
        message: str | None = None,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
        *,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(
            status_code=status_code,
            code=code,
            message=message,
            details=details,
            request_id=request_id,
        )
        if retry_after is None:
            # Server tafsilotda ham yuborishi mumkin: details.retry_after
            raw = self.details.get("retry_after")
            retry_after = _as_float(raw)
        self.retry_after = retry_after


class ServerError(DurablAPIError):
    """Serverning ichki xatosi yoki vaqtincha ishlamasligi (5xx)."""

    message = "Durabl serverida ichki xato"
    default_status_code = 500
    default_code = "INTERNAL_ERROR"


# ---------------------------------------------------------------------------
# Job bilan bog'liq xato
# ---------------------------------------------------------------------------


class JobFailedError(DurablError):
    """Job bajarildi, lekin muvaffaqiyatsiz tugadi (fail / dead_letter / cancelled).

    `job` — `Job` yoki `JobResult` obyekti; `result` — natija (agar bo'lsa).
    Shu sababli xatodan `stderr`, `exit_code` kabi tafsilotlarni olish mumkin.
    """

    message = "Job muvaffaqiyatsiz tugadi"

    def __init__(
        self,
        job: Any = None,
        message: str | None = None,
        *,
        result: Any = None,
    ) -> None:
        self.job = job
        self.result = result if result is not None else job
        super().__init__(message or _describe_failure(job, result))

    @property
    def job_id(self) -> str | None:
        """Muvaffaqiyatsiz job identifikatori (agar aniqlansa)."""
        for candidate in (self.job, self.result):
            job_id = getattr(candidate, "id", None) or getattr(candidate, "job_id", None)
            if job_id:
                return str(job_id)
        return None


# ---------------------------------------------------------------------------
# Xato javobidan klass tanlash
# ---------------------------------------------------------------------------

#: Backend `code` -> SDK xato klassi. Backend `app/exceptions.py`dagi kodlar
#: bilan bir xil yozilgan (CONTRACTS.md: kodlar barqaror shartnoma hisoblanadi).
ERROR_CODE_MAP: dict[str, type[DurablAPIError]] = {
    # 401
    "AUTHENTICATION_REQUIRED": AuthenticationError,
    "INVALID_CREDENTIALS": AuthenticationError,
    "INVALID_TOKEN": AuthenticationError,
    "TOKEN_EXPIRED": AuthenticationError,
    "INVALID_API_KEY": AuthenticationError,
    # 403
    "PERMISSION_DENIED": PermissionDeniedError,
    "ADMIN_REQUIRED": PermissionDeniedError,
    "INACTIVE_USER": PermissionDeniedError,
    # 404
    "NOT_FOUND": NotFoundError,
    "USER_NOT_FOUND": NotFoundError,
    "JOB_NOT_FOUND": NotFoundError,
    "EXECUTION_NOT_FOUND": NotFoundError,
    "WEBHOOK_NOT_FOUND": NotFoundError,
    "API_KEY_NOT_FOUND": NotFoundError,
    "DLQ_ENTRY_NOT_FOUND": NotFoundError,
    # 409
    "CONFLICT": ConflictError,
    "DUPLICATE_EMAIL": ConflictError,
    "IDEMPOTENCY_CONFLICT": ConflictError,
    "IDEMPOTENCY_IN_PROGRESS": ConflictError,
    "INVALID_STATE_TRANSITION": ConflictError,
    "JOB_NOT_CANCELLABLE": ConflictError,
    "JOB_NOT_RETRYABLE": ConflictError,
    "DLQ_ALREADY_RESOLVED": ConflictError,
    "LEASE_NOT_ACQUIRED": ConflictError,
    "RESULT_NOT_READY": ResultNotReadyError,
    # 400 / 413 / 422
    "BAD_REQUEST": ValidationError,
    "VALIDATION_ERROR": ValidationError,
    "CODE_VALIDATION_FAILED": ValidationError,
    "CODE_SYNTAX_ERROR": ValidationError,
    "UNSUPPORTED_RUNTIME": ValidationError,
    "PAYLOAD_TOO_LARGE": ValidationError,
    "WEBHOOK_URL_NOT_ALLOWED": ValidationError,
    # 402
    "QUOTA_EXCEEDED": QuotaExceededError,
    # 429
    "RATE_LIMIT_EXCEEDED": RateLimitError,
    "CONCURRENCY_LIMIT_EXCEEDED": RateLimitError,
    # 5xx
    "INTERNAL_ERROR": ServerError,
    "INFRASTRUCTURE_ERROR": ServerError,
    "DATABASE_ERROR": ServerError,
    "QUEUE_ERROR": ServerError,
    "CACHE_ERROR": ServerError,
    "SERVICE_UNAVAILABLE": ServerError,
    "SANDBOX_UNAVAILABLE": ServerError,
    "EXECUTION_ERROR": ServerError,
    "NOT_IMPLEMENTED": ServerError,
}

#: `code` topilmasa HTTP status bo'yicha tanlanadi.
STATUS_CODE_MAP: dict[int, type[DurablAPIError]] = {
    400: ValidationError,
    401: AuthenticationError,
    402: QuotaExceededError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    413: ValidationError,
    422: ValidationError,
    429: RateLimitError,
}


def error_from_response(
    status_code: int,
    payload: Any = None,
    *,
    retry_after: float | None = None,
    request_id: str | None = None,
) -> DurablAPIError:
    """Server javobidan mos SDK xato obyektini yasaydi.

    Tanlash tartibi:
      1. `payload["error"]["code"]` — `ERROR_CODE_MAP` bo'yicha;
      2. HTTP status — `STATUS_CODE_MAP` bo'yicha;
      3. 5xx bo'lsa `ServerError`, aks holda umumiy `DurablAPIError`.

    Argumentlar:
        status_code: HTTP status kodi.
        payload: JSON javob (`dict` bo'lmasa ham ishlaydi — matn sifatida olinadi).
        retry_after: `Retry-After` sarlavhasidan olingan soniya (429 uchun).
        request_id: Javob sarlavhasidagi `X-Request-ID` (tanada bo'lmasa).

    Qaytaradi:
        Hech qachon `None` emas — har doim `DurablAPIError` yoki uning vorisi.
    """
    code, message, details, body_request_id = _unpack_payload(payload)
    request_id = body_request_id or request_id

    error_class = ERROR_CODE_MAP.get(code or "")
    if error_class is None:
        error_class = STATUS_CODE_MAP.get(status_code)
    if error_class is None:
        error_class = ServerError if status_code >= 500 else DurablAPIError

    if issubclass(error_class, RateLimitError):
        return error_class(
            status_code=status_code,
            code=code,
            message=message,
            details=details,
            request_id=request_id,
            retry_after=retry_after,
        )
    return error_class(
        status_code=status_code,
        code=code,
        message=message,
        details=details,
        request_id=request_id,
    )


def _unpack_payload(
    payload: Any,
) -> tuple[str | None, str | None, dict[str, Any], str | None]:
    """Xato javobini `(code, message, details, request_id)` ko'rinishiga keltiradi.

    Kutilgan shakl (CONTRACTS.md 12-bo'lim):
    `{"error": {"code", "message", "details"}, "request_id"}`.
    Boshqa shakllar (FastAPI'ning `{"detail": ...}` yoki oddiy matn) ham
    yo'qotilmaydi — ular `message` sifatida olinadi.
    """
    if payload is None:
        return None, None, {}, None

    if isinstance(payload, str):
        text = payload.strip()
        return None, text or None, {}, None

    if not isinstance(payload, dict):
        return None, str(payload), {}, None

    request_id = payload.get("request_id")
    error = payload.get("error")

    if isinstance(error, dict):
        details = error.get("details")
        return (
            _as_str(error.get("code")),
            _as_str(error.get("message")),
            details if isinstance(details, dict) else ({"details": details} if details else {}),
            _as_str(request_id),
        )

    if isinstance(error, str):
        return None, error, {}, _as_str(request_id)

    # FastAPI standart shakli yoki noma'lum tana
    detail = payload.get("detail") or payload.get("message")
    return None, _as_str(detail), {}, _as_str(request_id)


def _as_str(value: Any) -> str | None:
    """Qiymatni matnga aylantiradi; bo'sh yoki `None` bo'lsa `None` qaytaradi."""
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    return text or None


def _as_float(value: Any) -> float | None:
    """Qiymatni `float`ga aylantiradi; bo'lmasa `None`."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _describe_failure(job: Any, result: Any) -> str:
    """`JobFailedError` uchun o'qishga qulay xabar yasaydi."""
    job_id = getattr(job, "id", None) or getattr(result, "job_id", None)
    status = getattr(job, "status", None) or getattr(result, "status", None)
    error = getattr(job, "error", None) or getattr(result, "error", None)
    stderr = getattr(result, "stderr", None) or getattr(job, "stderr", None)

    parts = ["Job muvaffaqiyatsiz tugadi"]
    if job_id:
        parts.append(f"(id={job_id})")
    if status:
        parts.append(f"holat={status}")
    last_stderr_line = (
        stderr.strip().splitlines()[-1] if isinstance(stderr, str) and stderr.strip() else None
    )
    reason = error or last_stderr_line
    if reason:
        parts.append(f"— {reason}")
    return " ".join(parts)


__all__ = [
    "ERROR_CODE_MAP",
    "STATUS_CODE_MAP",
    "AuthenticationError",
    "ConflictError",
    "ConnectionError",
    "DurablAPIError",
    "DurablConfigError",
    "DurablConnectionError",
    "DurablError",
    "DurablTimeoutError",
    "JobFailedError",
    "NotFoundError",
    "PermissionDeniedError",
    "QuotaExceededError",
    "RateLimitError",
    "ResultNotReadyError",
    "ServerError",
    "TimeoutError",
    "ValidationError",
    "error_from_response",
]
