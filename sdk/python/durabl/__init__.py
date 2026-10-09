"""Durabl — ishonchli background job va kod bajarish platformasi uchun Python SDK.

Durabl kodingizni gVisor sandbox ichida xavfsiz bajaradi: job yo'qolmaydi
(durability), ikki marta bajarilmaydi (idempotency), worker qulasa boshqasiga
o'tadi (lease + heartbeat), barcha urinishlar tugasa DLQ'ga tushadi.

Tez boshlash:

    from durabl import DurablClient

    client = DurablClient(api_key="durabl_xxx")
    job = client.submit(code="print('Salom dunyo')", runtime="python", timeout=30)
    result = client.wait_for_result(job.id, timeout=60)
    print(result.stdout)

Dekorator usuli:

    from durabl import durabl

    durabl.configure(api_key="durabl_xxx")

    @durabl.task(runtime="python", timeout=30, retries=3)
    def process(url):
        return len(url)

    handle = process.delay("https://example.com")
    print(handle.wait().value())

Asinxron:

    from durabl import AsyncDurablClient

    async with AsyncDurablClient(api_key="durabl_xxx") as client:
        handle = await client.submit(code="print(1)")
        result = await handle.wait()
"""

from __future__ import annotations

from ._version import USER_AGENT, VERSION, __version__
from .client import RETRYABLE_STATUS_CODES, AsyncDurablClient, DurablClient
from .config import DEFAULT_BASE_URL, DurablConfig
from .decorators import (
    AsyncDurablTask,
    Durabl,
    DurablTask,
    build_task_code,
    configure,
    durabl,
    task,
)
from .exceptions import (
    AuthenticationError,
    ConflictError,
    ConnectionError,
    DurablAPIError,
    DurablConfigError,
    DurablConnectionError,
    DurablError,
    DurablTimeoutError,
    JobFailedError,
    NotFoundError,
    PermissionDeniedError,
    QuotaExceededError,
    RateLimitError,
    ResultNotReadyError,
    ServerError,
    TimeoutError,
    ValidationError,
    error_from_response,
)
from .job import (
    RESULT_MARKER,
    AsyncJobHandle,
    Job,
    JobHandle,
    JobPage,
    JobResult,
    JobStatus,
    Pagination,
)

__all__ = [
    "DEFAULT_BASE_URL",
    "RESULT_MARKER",
    "RETRYABLE_STATUS_CODES",
    "USER_AGENT",
    "VERSION",
    # Mijozlar
    "AsyncDurablClient",
    "DurablClient",
    "DurablConfig",
    # Dekorator va global obyekt
    "AsyncDurablTask",
    "Durabl",
    "DurablTask",
    "build_task_code",
    "configure",
    "durabl",
    "task",
    # Ma'lumot tuzilmalari
    "AsyncJobHandle",
    "Job",
    "JobHandle",
    "JobPage",
    "JobResult",
    "JobStatus",
    "Pagination",
    # Xatolar
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
    "__version__",
]
