"""Durabl — test obyektlari fabrikasi (oddiy funksiyalar, kutubxonasiz).

Nega tashqi kutubxona (`factory_boy`, `polyfactory`) ishlatilmaydi? Bizning
modellarimizda `lazy="raise"` munosabatlar va `enum_column()` ustunlari bor —
avtomatik fabrikalar ularni to'ldirishga urinib `MissingGreenlet` yoki
noto'g'ri turdagi qiymat beradi. Oddiy funksiya esa aniq nimani yasayotganini
ko'rsatadi va hech qanday yashirin xatti-harakatga ega emas.

**Muhim shartnoma:** har bir `make_*()` funksiyasi FAQAT Python obyektini
qaytaradi — sessiyaga `add()` QILMAYDI va `flush()`/`commit()` chaqirmaydi.
Yozish chaqiruvchining mas'uliyatida:

    user = make_user(email="a@b.com")
    db_session.add(user)
    await db_session.flush()

Bu ataylab: ba'zi birlik testlari DB'ga umuman tegmasdan model obyekti bilan
ishlaydi (masalan `job_event_payload()` tekshiruvi), shuning uchun fabrika
sessiyaga bog'lanib qolmasligi kerak.

Foreign key maydonlari `None` bo'lsa yangi `uuid4()` yasaladi — DB'siz
testlarda qulay, lekin DB'ga yozishdan oldin HAQIQIY ota yozuvning
identifikatorini uzatish SHART (aks holda FK cheklovi buziladi).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.config import settings
from app.constants import (
    AuditAction,
    DeliveryStatus,
    ExecutionStatus,
    FailureReason,
    JobStatus,
    LogStream,
    PlanType,
    Priority,
    Runtime,
    WebhookEvent,
)
from app.execution.types import ExecutionResult, LogEntry, ResourceLimits, SandboxSpec
from app.models import (
    ApiKey,
    AuditLog,
    DlqEntry,
    Execution,
    ExecutionLog,
    Job,
    Subscription,
    UsageRecord,
    User,
    Webhook,
    WebhookDelivery,
)
from app.utils.security import (
    GeneratedApiKey,
    generate_api_key,
    generate_webhook_secret,
    hash_api_key,
    hash_password,
)
from app.utils.time_utils import month_key, utcnow

# ---------------------------------------------------------------------------
# Umumiy standart qiymatlar
# ---------------------------------------------------------------------------

#: Testlardagi standart parol — `validate_password_strength()` dan o'tadi
#: (kamida 8 belgi, harf va raqam bor).
DEFAULT_PASSWORD: str = "TestParol123"

#: Standart Python kodi — `validators.inspect_code()` tekshiruvidan toza o'tadi.
DEFAULT_CODE: str = "def main(payload):\n    return {'ok': True}\n"

#: Takrorlanmas email yasash uchun hisoblagich (har chaqiruvda oshadi).
_counter: int = 0


def _next_index() -> int:
    """Modul darajasidagi hisoblagichni oshirib qaytaradi.

    Takrorlanmas `email`/`name` qiymatlari uchun: `uuid4()` ham ishlardi,
    lekin ketma-ket raqam test xatolarini o'qishni osonlashtiradi
    (`user-3@durabl.test` degan email qaysi obyekt ekanini ko'rsatadi).
    """
    global _counter
    _counter += 1
    return _counter


def unique_email(prefix: str = "user") -> str:
    """Takrorlanmas test emaili (`user-1@durabl.test`)."""
    return f"{prefix}-{_next_index()}@durabl.test"


# ---------------------------------------------------------------------------
# Foydalanuvchi va kirish
# ---------------------------------------------------------------------------


def make_user(
    *,
    id: uuid.UUID | None = None,
    email: str | None = None,
    password: str | None = DEFAULT_PASSWORD,
    hashed_password: str | None = None,
    full_name: str | None = "Test Foydalanuvchi",
    is_active: bool = True,
    is_admin: bool = False,
    last_login_at: datetime | None = None,
) -> User:
    """`User` obyektini yasaydi (sessiyaga qo'shmaydi).

    Args:
        id: Birlamchi kalit; berilmasa modelning `uuid4` standarti ishlaydi.
        email: Pochta; berilmasa takrorlanmas qiymat yasaladi.
        password: Xom parol — `hashed_password` berilmagan bo'lsa hash qilinadi.
        hashed_password: Tayyor hash (parolni hash qilish vaqtini tejash uchun).
        full_name: To'liq ism.
        is_active: Hisob faolmi.
        is_admin: Administrator huquqi.
        last_login_at: Oxirgi kirish vaqti.
    """
    if hashed_password is None:
        hashed_password = hash_password(password or DEFAULT_PASSWORD)
    user = User(
        email=email or unique_email(),
        hashed_password=hashed_password,
        full_name=full_name,
        is_active=is_active,
        is_admin=is_admin,
        last_login_at=last_login_at,
    )
    if id is not None:
        user.id = id
    return user


def make_api_key(
    *,
    user_id: uuid.UUID | None = None,
    name: str | None = None,
    raw_key: str | None = None,
    scopes: list[str] | None = None,
    expires_at: datetime | None = None,
    revoked_at: datetime | None = None,
    last_used_at: datetime | None = None,
) -> tuple[ApiKey, str]:
    """`ApiKey` obyektini va uning XOM kalitini qaytaradi.

    Xom kalit ikkinchi element sifatida qaytariladi, chunki DB'da faqat
    SHA-256 hash saqlanadi va keyin uni tiklash IMKONSIZ — testlarda
    `X-API-Key` header'i uchun aynan shu qiymat kerak bo'ladi.

    Args:
        user_id: Egasi; berilmasa yangi `uuid4`.
        name: Kalit nomi.
        raw_key: Tayyor xom kalit (berilmasa `generate_api_key()` yasaydi).
        scopes: Ruxsatlar ro'yxati.
        expires_at: Muddat tugash vaqti.
        revoked_at: Bekor qilingan vaqt.
        last_used_at: Oxirgi ishlatilgan vaqt.
    """
    if raw_key is None:
        generated = generate_api_key()
    else:
        prefix_length = len(settings.API_KEY_PREFIX) + 8
        generated = GeneratedApiKey(
            raw=raw_key,
            key_hash=hash_api_key(raw_key),
            key_prefix=raw_key[:prefix_length],
            last_four=raw_key[-4:],
        )

    api_key = ApiKey(
        user_id=user_id or uuid.uuid4(),
        key_hash=generated.key_hash,
        key_prefix=generated.key_prefix,
        last_four=generated.last_four,
        name=name or f"test-kalit-{_next_index()}",
        scopes=scopes if scopes is not None else [],
        expires_at=expires_at,
        revoked_at=revoked_at,
        last_used_at=last_used_at,
    )
    return api_key, generated.raw


def make_subscription(
    *,
    user_id: uuid.UUID | None = None,
    plan: PlanType = PlanType.FREE,
    started_at: datetime | None = None,
    expires_at: datetime | None = None,
    is_active: bool = True,
    cancelled_at: datetime | None = None,
    external_customer_id: str | None = None,
) -> Subscription:
    """`Subscription` obyektini yasaydi (standart — faol FREE reja)."""
    return Subscription(
        user_id=user_id or uuid.uuid4(),
        plan=plan,
        started_at=started_at or utcnow(),
        expires_at=expires_at,
        is_active=is_active,
        cancelled_at=cancelled_at,
        external_customer_id=external_customer_id,
    )


# ---------------------------------------------------------------------------
# Job va bajarish
# ---------------------------------------------------------------------------


def make_job(
    *,
    id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    code: str = DEFAULT_CODE,
    runtime: Runtime = Runtime.PYTHON,
    priority: Priority = Priority.NORMAL,
    status: JobStatus = JobStatus.PENDING,
    payload: dict[str, Any] | None = None,
    env_vars: dict[str, str] | None = None,
    timeout_seconds: int | None = None,
    max_retries: int | None = None,
    retry_count: int = 0,
    memory_mb: int | None = None,
    cpus: float | None = None,
    scheduled_at: datetime | None = None,
    cron_expression: str | None = None,
    idempotency_key: str | None = None,
    correlation_id: str | None = None,
    tags: list[str] | None = None,
    queued_at: datetime | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    cancelled_at: datetime | None = None,
    result: dict[str, Any] | None = None,
    stdout: str | None = None,
    stderr: str | None = None,
    exit_code: int | None = None,
    duration_ms: int | None = None,
    error: str | None = None,
    failure_reason: FailureReason | None = None,
) -> Job:
    """`Job` obyektini yasaydi (sessiyaga qo'shmaydi).

    `timeout_seconds`, `max_retries` va `correlation_id` — modelda
    `nullable=False`, shuning uchun berilmasa sozlamadan/`uuid4`dan
    to'ldiriladi (aks holda `flush()` da `IntegrityError` chiqardi).
    """
    job = Job(
        user_id=user_id or uuid.uuid4(),
        code=code,
        runtime=runtime,
        priority=priority,
        status=status,
        payload=payload,
        env_vars=env_vars,
        timeout_seconds=(
            settings.DEFAULT_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds
        ),
        max_retries=settings.DEFAULT_MAX_RETRIES if max_retries is None else max_retries,
        retry_count=retry_count,
        memory_mb=memory_mb,
        cpus=cpus,
        scheduled_at=scheduled_at,
        cron_expression=cron_expression,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id or uuid.uuid4().hex,
        tags=tags,
        queued_at=queued_at,
        started_at=started_at,
        finished_at=finished_at,
        cancelled_at=cancelled_at,
        result=result,
        stdout=stdout,
        stderr=stderr,
        exit_code=exit_code,
        duration_ms=duration_ms,
        error=error,
        failure_reason=failure_reason,
    )
    if id is not None:
        job.id = id
    return job


def make_execution(
    *,
    id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    attempt_number: int = 1,
    worker_id: str | None = "test-worker",
    status: ExecutionStatus = ExecutionStatus.PENDING,
    lease_expires_at: datetime | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    exit_code: int | None = None,
    duration_ms: int | None = None,
    error_message: str | None = None,
    failure_reason: FailureReason | None = None,
    stdout_bytes: int = 0,
    stderr_bytes: int = 0,
    result: dict[str, Any] | None = None,
    sandbox_id: str | None = None,
    memory_peak_mb: int | None = None,
) -> Execution:
    """`Execution` obyektini yasaydi (bitta urinish yozuvi)."""
    execution = Execution(
        job_id=job_id or uuid.uuid4(),
        attempt_number=attempt_number,
        worker_id=worker_id,
        status=status,
        lease_expires_at=lease_expires_at,
        started_at=started_at,
        finished_at=finished_at,
        exit_code=exit_code,
        duration_ms=duration_ms,
        error_message=error_message,
        failure_reason=failure_reason,
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
        result=result,
        sandbox_id=sandbox_id,
        memory_peak_mb=memory_peak_mb,
    )
    if id is not None:
        execution.id = id
    return execution


def make_log(
    *,
    execution_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    stream: LogStream = LogStream.STDOUT,
    content: str = "salom",
    sequence: int = 0,
    timestamp: datetime | None = None,
) -> ExecutionLog:
    """`ExecutionLog` obyektini yasaydi (bitta log qatori)."""
    return ExecutionLog(
        execution_id=execution_id or uuid.uuid4(),
        job_id=job_id or uuid.uuid4(),
        stream=stream,
        content=content,
        sequence=sequence,
        timestamp=timestamp or utcnow(),
    )


# ---------------------------------------------------------------------------
# Webhook
# ---------------------------------------------------------------------------


def make_webhook(
    *,
    id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    url: str = "https://example.com/durabl-hook",
    secret: str | None = None,
    events: list[str] | None = None,
    description: str | None = "Test webhook",
    is_active: bool = True,
    last_triggered_at: datetime | None = None,
    consecutive_failures: int = 0,
    disabled_at: datetime | None = None,
) -> Webhook:
    """`Webhook` obyektini yasaydi (standart — barcha hodisalarga obuna)."""
    webhook = Webhook(
        user_id=user_id or uuid.uuid4(),
        url=url,
        secret=secret or generate_webhook_secret(),
        events=events if events is not None else WebhookEvent.all(),
        description=description,
        is_active=is_active,
        last_triggered_at=last_triggered_at,
        consecutive_failures=consecutive_failures,
        disabled_at=disabled_at,
    )
    if id is not None:
        webhook.id = id
    return webhook


def make_delivery(
    *,
    webhook_id: uuid.UUID | None = None,
    job_id: uuid.UUID | None = None,
    event: WebhookEvent = WebhookEvent.JOB_SUCCEEDED,
    status: DeliveryStatus = DeliveryStatus.PENDING,
    attempt: int = 1,
    payload: dict[str, Any] | None = None,
    response_code: int | None = None,
    response_body: str | None = None,
    error_message: str | None = None,
    next_retry_at: datetime | None = None,
    delivered_at: datetime | None = None,
    duration_ms: int | None = None,
) -> WebhookDelivery:
    """`WebhookDelivery` obyektini yasaydi (bitta yuborish urinishi)."""
    return WebhookDelivery(
        webhook_id=webhook_id or uuid.uuid4(),
        job_id=job_id,
        event=event,
        status=status,
        attempt=attempt,
        payload=payload if payload is not None else {"job_id": str(job_id or uuid.uuid4())},
        response_code=response_code,
        response_body=response_body,
        error_message=error_message,
        next_retry_at=next_retry_at,
        delivered_at=delivered_at,
        duration_ms=duration_ms,
    )


# ---------------------------------------------------------------------------
# DLQ, hisob va audit
# ---------------------------------------------------------------------------


def make_dlq_entry(
    *,
    job_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    failure_reason: FailureReason = FailureReason.NON_ZERO_EXIT,
    last_error: str | None = "Kod 1 chiqish kodi bilan tugadi",
    failed_at: datetime | None = None,
    retry_count: int = 0,
    resolved: bool = False,
    resolved_at: datetime | None = None,
    resolved_by_id: uuid.UUID | None = None,
    notes: str | None = None,
    manual_retry_count: int = 0,
) -> DlqEntry:
    """`DlqEntry` obyektini yasaydi (standart — hal qilinmagan yozuv)."""
    return DlqEntry(
        job_id=job_id or uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        failure_reason=failure_reason,
        last_error=last_error,
        failed_at=failed_at or utcnow(),
        retry_count=retry_count,
        resolved=resolved,
        resolved_at=resolved_at,
        resolved_by_id=resolved_by_id,
        notes=notes,
        manual_retry_count=manual_retry_count,
    )


def make_usage(
    *,
    user_id: uuid.UUID | None = None,
    period: str | None = None,
    job_count: int = 0,
    success_count: int = 0,
    failed_count: int = 0,
    execution_seconds: float = 0.0,
    recorded_at: datetime | None = None,
) -> UsageRecord:
    """`UsageRecord` obyektini yasaydi (standart davr — joriy oy)."""
    return UsageRecord(
        user_id=user_id or uuid.uuid4(),
        period=period or month_key(),
        job_count=job_count,
        success_count=success_count,
        failed_count=failed_count,
        execution_seconds=execution_seconds,
        recorded_at=recorded_at or utcnow(),
    )


def make_audit(
    *,
    admin_id: uuid.UUID | None = None,
    action: AuditAction = AuditAction.USER_UPDATED,
    target_type: str | None = "user",
    target_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = "127.0.0.1",
    user_agent: str | None = "pytest",
) -> AuditLog:
    """`AuditLog` obyektini yasaydi (admin harakati yozuvi)."""
    return AuditLog(
        admin_id=admin_id,
        action=action,
        target_type=target_type,
        target_id=target_id or uuid.uuid4().hex,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent,
    )


# ---------------------------------------------------------------------------
# Bajarish qatlamining tuzilmalari (DB'ga tegmaydi)
# ---------------------------------------------------------------------------


def make_limits(
    *,
    memory_mb: int = 256,
    cpus: float = 0.5,
    pids_limit: int = 50,
    disk_mb: int = 64,
    tmpfs_mb: int = 32,
    timeout_seconds: int = 5,
    max_output_bytes: int = 1024,
    allow_network: bool = False,
    read_only_rootfs: bool = True,
) -> ResourceLimits:
    """`ResourceLimits` yasaydi — `ResultCollector` va limiter testlari uchun.

    `max_output_bytes` ataylab kichik (1 KB): kesish (truncation) mantig'ini
    1 MB matn yasamasdan sinash mumkin bo'lsin.
    """
    return ResourceLimits(
        memory_mb=memory_mb,
        cpus=cpus,
        pids_limit=pids_limit,
        disk_mb=disk_mb,
        tmpfs_mb=tmpfs_mb,
        timeout_seconds=timeout_seconds,
        max_output_bytes=max_output_bytes,
        allow_network=allow_network,
        read_only_rootfs=read_only_rootfs,
    )


def make_sandbox_spec(
    *,
    job_id: str | None = None,
    code: str = DEFAULT_CODE,
    runtime: Runtime = Runtime.PYTHON,
    limits: ResourceLimits | None = None,
    payload: dict[str, Any] | None = None,
    env_vars: dict[str, str] | None = None,
    correlation_id: str = "",
    attempt_number: int = 1,
) -> SandboxSpec:
    """`SandboxSpec` yasaydi — executor/runner testlari uchun topshiriq."""
    return SandboxSpec(
        job_id=job_id or str(uuid.uuid4()),
        code=code,
        runtime=runtime,
        limits=limits or make_limits(),
        payload=payload,
        env_vars=env_vars,
        correlation_id=correlation_id,
        attempt_number=attempt_number,
    )


def make_execution_result(
    *,
    status: ExecutionStatus = ExecutionStatus.SUCCESS,
    exit_code: int | None = 0,
    stdout: str = "",
    stderr: str = "",
    result: Any | None = None,
    duration_ms: int = 42,
    logs: list[LogEntry] | None = None,
    failure_reason: FailureReason | None = None,
    error_message: str | None = None,
    traceback: str | None = None,
    memory_peak_mb: int | None = None,
    truncated: bool = False,
    sandbox_id: str | None = None,
) -> ExecutionResult:
    """`ExecutionResult` yasaydi — service qatlami testlari uchun natija."""
    return ExecutionResult(
        status=status,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        result=result,
        duration_ms=duration_ms,
        logs=logs if logs is not None else [],
        failure_reason=failure_reason,
        error_message=error_message,
        traceback=traceback,
        memory_peak_mb=memory_peak_mb,
        truncated=truncated,
        sandbox_id=sandbox_id,
    )


def make_log_entry(
    *,
    stream: LogStream = LogStream.STDOUT,
    content: str = "salom",
    sequence: int = 0,
    timestamp: datetime | None = None,
) -> LogEntry:
    """`LogEntry` (bajarish qatlamining dataclass'i) yasaydi."""
    return LogEntry(
        stream=stream,
        content=content,
        sequence=sequence,
        timestamp=timestamp or utcnow(),
    )


__all__ = [
    "DEFAULT_CODE",
    "DEFAULT_PASSWORD",
    "make_api_key",
    "make_audit",
    "make_delivery",
    "make_dlq_entry",
    "make_execution",
    "make_execution_result",
    "make_job",
    "make_limits",
    "make_log",
    "make_log_entry",
    "make_sandbox_spec",
    "make_subscription",
    "make_usage",
    "make_user",
    "make_webhook",
    "unique_email",
]
