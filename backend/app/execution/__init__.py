"""Durabl — bajarish (execution) qatlami.

Bu paket mijoz kodini xavfsiz bajarishning TO'LIQ zanjirini o'z ichiga oladi:

    types.py            umumiy ma'lumot tuzilmalari (shartnoma)
    runtime_base.py     `BaseRuntime` (til) va `SandboxRunner` (muhit) interfeyslari
    runtime_python.py   Python muhiti
    runtime_node.py     Node muhiti
    resource_limiter.py resurs cheklovlarini Docker/rlimit shakliga o'girish
    sandbox_manager.py  gVisor/Docker konteyner runner'i (production)
    local_runner.py     lokal subprocess runner'i (development/test)
    timeout_guard.py    vaqt limiti nazorati
    result_collector.py oqimlarni yig'ish va natijani tasniflash
    executor.py         hammasini bir-biriga ulaydigan koordinator

Tashqi qatlamlar (`services/`, `workers/`) odatda faqat ikki narsani oladi:

    from app.execution import Executor, SandboxSpec

**Dangasa (lazy) import:** konkret runner va runtime modullari faqat
nomiga murojaat qilinganda yuklanadi. Shu tufayli `docker` SDK yoki
`resource` moduli kerak bo'lmagan muhitda ham (masalan API protsessi)
`app.execution` ni import qilish arzon va xavfsiz bo'lib qoladi.
"""

from __future__ import annotations

import importlib
from typing import Any

from app.execution.executor import Executor, default_executor
from app.execution.result_collector import ResultCollector
from app.execution.runtime_base import (
    BaseRuntime,
    LogSink,
    SandboxRunner,
    available_runtimes,
    get_runtime,
    register_runtime,
)
from app.execution.timeout_guard import TimeoutCallback, TimeoutGuard, with_timeout
from app.execution.types import (
    ExecutionResult,
    LogEntry,
    ResourceLimits,
    RunnerOutcome,
    RunnerPayload,
    SandboxSpec,
)

#: Dangasa yuklanadigan nomlar: nom -> modul.
#: Shartnomada (`docs/CONTRACTS.md` §7) kelishilgan nomlar.
_LAZY_EXPORTS: dict[str, str] = {
    "SandboxManager": "app.execution.sandbox_manager",
    "LocalRunner": "app.execution.local_runner",
    "PythonRuntime": "app.execution.runtime_python",
    "NodeRuntime": "app.execution.runtime_node",
    "resolve_limits": "app.execution.resource_limiter",
    "to_docker_kwargs": "app.execution.resource_limiter",
    "to_rlimits": "app.execution.resource_limiter",
}


def __getattr__(name: str) -> Any:
    """Dangasa eksportlarni ilk murojaatda yuklaydi (PEP 562)."""
    module_name = _LAZY_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"`{__name__}` modulida `{name}` nomi yo'q")

    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:  # pragma: no cover - modul yo'q/buzilgan holat
        raise AttributeError(f"`{name}` uchun `{module_name}` moduli yuklanmadi: {exc}") from exc

    try:
        value = getattr(module, name)
    except AttributeError as exc:  # pragma: no cover - shartnoma buzilgan holat
        raise AttributeError(
            f"`{module_name}` modulida `{name}` nomi yo'q (shartnomaga mos emasmi?)"
        ) from exc

    globals()[name] = value  # keyingi murojaatlar uchun keshlanadi
    return value


def __dir__() -> list[str]:
    """`dir(app.execution)` dangasa nomlarni ham ko'rsatadi."""
    return sorted(set(__all__) | set(globals()))


__all__ = [
    "BaseRuntime",
    "ExecutionResult",
    "Executor",
    "LocalRunner",
    "LogEntry",
    "LogSink",
    "NodeRuntime",
    "PythonRuntime",
    "ResourceLimits",
    "ResultCollector",
    "RunnerOutcome",
    "RunnerPayload",
    "SandboxManager",
    "SandboxRunner",
    "SandboxSpec",
    "TimeoutCallback",
    "TimeoutGuard",
    "available_runtimes",
    "default_executor",
    "get_runtime",
    "register_runtime",
    "resolve_limits",
    "to_docker_kwargs",
    "to_rlimits",
    "with_timeout",
]
