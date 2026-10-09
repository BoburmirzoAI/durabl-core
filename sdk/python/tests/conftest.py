"""Umumiy test sozlamalari va fixture'lar.

`durabl` paketi `pip install` qilinmagan bo'lishi mumkin, shuning uchun SDK
ildizi (`sdk/python`) `sys.path`ga qo'shiladi.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

#: `sdk/python` papkasi — `durabl` paketi shu yerda.
SDK_ROOT = Path(__file__).resolve().parent.parent
if str(SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_ROOT))

import pytest  # noqa: E402 - sys.path sozlangandan keyin import qilinadi

from durabl import AsyncDurablClient, DurablClient  # noqa: E402

#: Testlarda ishlatiladigan API kalit (haqiqiy emas).
API_KEY = "durabl_test_0000000000000000000000000000"
#: Testlarda ishlatiladigan server manzili (hech qachon chaqirilmaydi — mock).
BASE_URL = "https://api.test.durabl.dev"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Muhit o'zgaruvchilari testlar natijasiga ta'sir qilmasligi uchun tozalanadi."""
    for name in (
        "DURABL_API_KEY",
        "DURABL_BASE_URL",
        "DURABL_TIMEOUT",
        "DURABL_MAX_RETRIES",
        "DURABL_RETRY_BACKOFF",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def api_key() -> str:
    """Test API kaliti."""
    return API_KEY


@pytest.fixture
def base_url() -> str:
    """Test server manzili."""
    return BASE_URL


@pytest.fixture
def sleeps() -> list[float]:
    """Mijoz "kutgan" soniyalar ro'yxati (backoff tekshiruvi uchun)."""
    return []


@pytest.fixture
def client(sleeps: list[float]) -> Iterator[DurablClient]:
    """Sinxron mijoz — haqiqiy kutish o'rniga `sleeps` ro'yxatiga yozadi."""
    instance = DurablClient(
        api_key=API_KEY,
        base_url=BASE_URL,
        timeout=5.0,
        max_retries=2,
        retry_backoff=1.0,
        retry_max_delay=10.0,
    )
    # Testlar tez ishlashi uchun haqiqiy `time.sleep` almashtiriladi.
    instance._sleep = sleeps.append  # type: ignore[method-assign]
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture
async def async_client(sleeps: list[float]) -> Any:
    """Asinxron mijoz — kutish `sleeps` ro'yxatiga yoziladi."""
    instance = AsyncDurablClient(
        api_key=API_KEY,
        base_url=BASE_URL,
        timeout=5.0,
        max_retries=2,
        retry_backoff=1.0,
        retry_max_delay=10.0,
    )

    async def record(seconds: float) -> None:
        sleeps.append(seconds)

    instance._sleep = record  # type: ignore[method-assign]
    try:
        yield instance
    finally:
        await instance.aclose()


def job_payload(
    job_id: str = "11111111-1111-1111-1111-111111111111",
    status: str = "pending",
    **overrides: Any,
) -> dict[str, Any]:
    """`JobRead` shaklidagi mock javob yasaydi."""
    payload: dict[str, Any] = {
        "id": job_id,
        "status": status,
        "runtime": "python",
        "priority": "normal",
        "created_at": "2026-10-04T10:00:00Z",
        "started_at": None,
        "finished_at": None,
        "duration_ms": None,
        "retry_count": 0,
        "exit_code": None,
        "error": None,
        "tags": [],
    }
    payload.update(overrides)
    return payload


def result_payload(
    job_id: str = "11111111-1111-1111-1111-111111111111",
    status: str = "success",
    **overrides: Any,
) -> dict[str, Any]:
    """`JobResultResponse` shaklidagi mock javob yasaydi."""
    payload: dict[str, Any] = {
        "job_id": job_id,
        "status": status,
        "stdout": "Salom dunyo\n",
        "stderr": "",
        "result": None,
        "exit_code": 0,
        "duration_ms": 1234,
    }
    payload.update(overrides)
    return payload


def error_payload(
    code: str,
    message: str = "Xato",
    details: dict[str, Any] | None = None,
    request_id: str = "req_test_1",
) -> dict[str, Any]:
    """Backend xato javobi shakli: `{error: {code, message, details?}, request_id}`."""
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error, "request_id": request_id}


def page_payload(
    items: list[dict[str, Any]],
    *,
    page: int = 1,
    page_size: int = 20,
    total: int | None = None,
    has_next: bool = False,
) -> dict[str, Any]:
    """Ro'yxat javobi shakli: `{items, pagination}`."""
    count = len(items) if total is None else total
    total_pages = max(1, (count + page_size - 1) // page_size) if count else 0
    return {
        "items": items,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total": count,
            "total_pages": total_pages,
            "has_next": has_next,
            "has_prev": page > 1,
        },
    }
