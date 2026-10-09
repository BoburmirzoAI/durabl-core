"""Durabl — bajarish muhiti (runtime) va runner interfeyslari.

Bu modul SHARTNOMA: `executor.py` faqat shu abstraksiyalarga qaraydi, konkret
Python/Node mantig'i va Docker/lokal farqi undan yashirilgan.

Ikki abstraksiya:

* `BaseRuntime` — TIL bo'yicha farq (qanday fayl yozish, qaysi image, qaysi buyruq).
* `SandboxRunner` — MUHIT bo'yicha farq (gVisor konteyner yoki lokal subprocess).

Shu ikkisi kesishib to'rt kombinatsiya beradi (python/node × sandbox/lokal),
lekin kod faqat 2 + 2 ta sinfda yoziladi.
"""

from __future__ import annotations

import importlib
import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.constants import (
    SANDBOX_CODE_FILENAME,
    SANDBOX_PAYLOAD_FILENAME,
    SANDBOX_RESULT_FILENAME,
    FailureReason,
    LogStream,
    Runtime,
)
from app.exceptions import UnsupportedRuntimeError
from app.execution.types import RunnerOutcome, RunnerPayload, SandboxSpec

#: Log oqimiga chunk uzatish uchun callback turi.
#: `ResultCollector.feed` ayni shu imzoga mos keladi.
LogSink = Callable[[LogStream, str], None]


# ---------------------------------------------------------------------------
# Runtime (til) abstraksiyasi
# ---------------------------------------------------------------------------


class BaseRuntime(ABC):
    """Bitta bajarish muhiti (Python yoki Node) uchun bazaviy interfeys."""

    #: Voris klass shu atributni belgilaydi
    runtime: Runtime

    # --- Identifikatsiya ---------------------------------------------------

    @property
    @abstractmethod
    def image(self) -> str:
        """Sandbox uchun Docker image nomi (`settings`dan)."""

    @property
    def code_filename(self) -> str:
        """Sandbox ichidagi kod fayli nomi (`main.py` / `main.js`)."""
        return SANDBOX_CODE_FILENAME[self.runtime]

    @property
    @abstractmethod
    def entrypoint_path(self) -> str:
        """Konteyner ichidagi entrypoint yo'li (`/opt/durabl/entrypoint.py`)."""

    # --- Fayllarni tayyorlash ---------------------------------------------

    def prepare_files(self, spec: SandboxSpec, workdir: Path) -> None:
        """Ish katalogiga kod va payload fayllarini yozadi.

        Ikki runner ham (sandbox va lokal) ayni shu tayyorgarlikdan foydalanadi,
        shuning uchun mantiq bazaviy klassda.
        """
        workdir.mkdir(parents=True, exist_ok=True)
        (workdir / self.code_filename).write_text(spec.code, encoding="utf-8")
        if spec.payload is not None:
            (workdir / SANDBOX_PAYLOAD_FILENAME).write_text(
                json.dumps(spec.payload, ensure_ascii=False, default=str),
                encoding="utf-8",
            )

    def read_result_file(self, workdir: Path) -> RunnerPayload:
        """Entrypoint yozgan `result.json` ni o'qiydi (yo'q bo'lsa bo'sh payload)."""
        path = workdir / SANDBOX_RESULT_FILENAME
        if not path.is_file():
            return RunnerPayload()
        try:
            return RunnerPayload.parse(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return RunnerPayload()

    # --- Bajarish buyruqlari ----------------------------------------------

    @abstractmethod
    def container_command(self, spec: SandboxSpec) -> list[str]:
        """Konteyner ichida bajarilishi kerak bo'lgan buyruq."""

    @abstractmethod
    def local_command(self, spec: SandboxSpec, workdir: Path) -> list[str]:
        """Lokal subprocess uchun buyruq (`SANDBOX_ENABLED=False` rejimi).

        Interpretator loyihadagi `sandbox/runners/<til>/entrypoint.*` faylini
        ishga tushiradi — sandbox bilan AYNI shartnoma ishlaydi.
        """

    # --- Xatoni tasniflash -------------------------------------------------

    def classify_failure(
        self,
        outcome: RunnerOutcome,
        *,
        stderr: str = "",
    ) -> FailureReason:
        """Jarayon natijasidan xato sababini aniqlaydi.

        Voris klasslar tilga xos belgilarni qo'shishi mumkin
        (masalan Python `MemoryError`, Node `heap out of memory`).
        """
        if outcome.timed_out:
            return FailureReason.TIMEOUT
        if outcome.oom_killed:
            return FailureReason.OOM
        if outcome.infra_error:
            return FailureReason.SANDBOX_ERROR
        return FailureReason.NON_ZERO_EXIT

    def __repr__(self) -> str:  # pragma: no cover - debug yordamchisi
        return f"<{type(self).__name__} runtime={self.runtime.value}>"


# ---------------------------------------------------------------------------
# Runtime reestri
# ---------------------------------------------------------------------------

_RUNTIMES: dict[Runtime, BaseRuntime] = {}

#: Konkret runtime modullari — import bo'lganda o'zini reestrga qo'shadi.
_RUNTIME_MODULES: tuple[str, ...] = (
    "app.execution.runtime_python",
    "app.execution.runtime_node",
)

#: Lazy yuklash BIR MARTA bajarilganini bildiradi.
#:
#: Bayroq `_RUNTIMES` ning bo'sh-to'laligidan AJRATILGAN. Avval shart
#: `if _RUNTIMES: return` edi va bu jim yo'qotishga olib kelardi: biror
#: modul `app.execution.runtime_python` ni BEVOSITA import qilsa (dekorator
#: o'zini reestrga qo'shadi), reestr "bo'sh emas" bo'lib qolardi va
#: `runtime_node` HECH QACHON import qilinmasdi. Natijada `node` job'lari
#: butun protsess umri davomida `UnsupportedRuntimeError` -> `validation_error`
#: -> DARHOL `DEAD_LETTER` (qayta urinishga yaroqsiz) bo'lib ketardi.
_runtimes_loaded: bool = False


def _ensure_runtimes_loaded() -> None:
    """Konkret runtime modullarini bir marta import qiladi (lazy ro'yxat).

    Modul mavjud bo'lmasa jim o'tadi — natijada `get_runtime()` tushunarli
    `UnsupportedRuntimeError` beradi, xom `ImportError` emas.

    Bayroq halqadan OLDIN qo'yiladi: import qilinayotgan modul (yoki uning
    bog'liqligi) `get_runtime()` ni chaqirsa, cheksiz rekursiya bo'lmaydi.
    """
    global _runtimes_loaded

    if _runtimes_loaded:
        return
    _runtimes_loaded = True
    for module_name in _RUNTIME_MODULES:
        try:
            importlib.import_module(module_name)
        except ImportError:  # pragma: no cover - modul hali yozilmagan holat
            continue


def register_runtime(instance: BaseRuntime) -> BaseRuntime:
    """Runtime nusxasini reestrga qo'shadi (modul import bo'lganda chaqiriladi)."""
    _RUNTIMES[instance.runtime] = instance
    return instance


def get_runtime(runtime: Runtime | str) -> BaseRuntime:
    """Enum bo'yicha runtime nusxasini qaytaradi.

    Raises:
        UnsupportedRuntimeError: Qo'llab-quvvatlanmagan muhit.
    """
    _ensure_runtimes_loaded()

    try:
        key = Runtime(runtime)
    except ValueError as exc:
        raise UnsupportedRuntimeError(str(runtime)) from exc

    instance = _RUNTIMES.get(key)
    if instance is None:
        raise UnsupportedRuntimeError(key.value)
    return instance


def available_runtimes() -> list[Runtime]:
    """Ro'yxatdan o'tgan muhitlar."""
    _ensure_runtimes_loaded()
    return sorted(_RUNTIMES, key=lambda item: item.value)


# ---------------------------------------------------------------------------
# Runner (muhit) abstraksiyasi
# ---------------------------------------------------------------------------


@runtime_checkable
class SandboxRunner(Protocol):
    """Kodni bajaradigan muhit interfeysi.

    Ikki amalga oshirish bor:

    * `SandboxManager` — gVisor/Docker konteyner (production).
    * `LocalRunner` — lokal subprocess (`SANDBOX_ENABLED=False`, development/test).

    `Executor` faqat shu protokolga qaraydi.
    """

    async def available(self) -> bool:
        """Muhit ishlashga tayyormi (Docker demoni javob beradimi va h.k.)."""
        ...

    async def run(
        self,
        spec: SandboxSpec,
        runtime: BaseRuntime,
        on_log: LogSink | None = None,
    ) -> RunnerOutcome:
        """Kodni bajaradi.

        Chiqish oqimlari kelgani sari `on_log(stream, chunk)` chaqiriladi
        (real-time log uchun). Qaytadigan `RunnerOutcome` xom natija —
        uni `ExecutionResult`ga aylantirish `ResultCollector` vazifasi.

        Bu metod VAQT LIMITINI o'zi nazorat qilmaydi — `TimeoutGuard`
        tashqaridan `kill()` ni chaqiradi.
        """
        ...

    async def kill(self) -> None:
        """Joriy bajarishni majburan to'xtatadi (timeout yoki bekor qilish)."""
        ...

    async def cleanup_orphans(self) -> int:
        """Qolib ketgan konteyner/jarayonlarni tozalaydi; sonini qaytaradi."""
        ...


__all__ = [
    "BaseRuntime",
    "LogSink",
    "SandboxRunner",
    "available_runtimes",
    "get_runtime",
    "register_runtime",
]
