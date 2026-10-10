"""Durabl — Python bajarish muhiti (runtime).

`BaseRuntime` ning Python uchun konkret amalga oshirilishi: qaysi image,
konteyner ichida qaysi buyruq, lokal rejimda qaysi interpretator va Python'ga
XOS xato belgilarini qanday tasniflash.

Shartnoma (`sandbox/runners/python/`):

* konteynerdagi entrypoint — `/opt/durabl/entrypoint.py` (Dockerfile `COPY` qiladi)
* lokal entrypoint        — `<loyiha>/sandbox/runners/python/entrypoint.py`
* mijoz kodi              — `<workdir>/main.py`
* natija                  — `<workdir>/result.json`

Lokal rejim (`SANDBOX_ENABLED=False`) ayni shu entrypoint'ni `sys.executable`
bilan ishga tushiradi, ya'ni sandbox bilan BIR XIL shartnoma ishlaydi —
development'da ishlagan kod production'da ham ayni natijani beradi.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from app.config import settings
from app.constants import FailureReason, Runtime
from app.exceptions import SandboxUnavailableError
from app.execution.runtime_base import BaseRuntime, register_runtime
from app.execution.types import RunnerOutcome, SandboxSpec

# ---------------------------------------------------------------------------
# Yo'llar
# ---------------------------------------------------------------------------

#: Loyiha ildizi: `backend/app/execution/runtime_python.py` -> parents[3].
#: `settings` da emas, modul darajasida hisoblanadi — sandbox entrypoint'i
#: repozitoriyning bir qismi, sozlanadigan qiymat emas.
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

#: Lokal (Docker'siz) rejimda ishga tushiriladigan entrypoint.
LOCAL_ENTRYPOINT: Final[Path] = PROJECT_ROOT / "sandbox" / "runners" / "python" / "entrypoint.py"

#: Konteyner ichidagi entrypoint yo'li (`sandbox/runners/python/Dockerfile`).
CONTAINER_ENTRYPOINT: Final[str] = "/opt/durabl/entrypoint.py"


# ---------------------------------------------------------------------------
# Xato belgilari
# ---------------------------------------------------------------------------

#: Xotira tugaganini bildiruvchi belgilar (stderr yoki `result.json` ichida).
#: `Killed` — kernel OOM killer protsessni o'ldirganda qobiq chiqaradigan matn.
OOM_MARKERS: Final[tuple[str, ...]] = (
    "MemoryError",
    "Killed",
    "Cannot allocate memory",
    "out of memory",
)

#: Kod SINTAKTIK jihatdan yaroqsiz — qayta urinish befoyda, retry qilinmaydi.
VALIDATION_MARKERS: Final[tuple[str, ...]] = (
    "SyntaxError",
    "IndentationError",
    "TabError",
)

#: OOM killer SIGKILL yuborganda ko'rinadigan chiqish kodlari
#: (Docker: 128 + 9 = 137, POSIX subprocess: -9).
OOM_EXIT_CODES: Final[tuple[int, ...]] = (137, -9)


def _contains_any(haystack: str, markers: tuple[str, ...]) -> bool:
    """Matnda berilgan belgilardan birortasi bormi."""
    return any(marker in haystack for marker in markers)


def _failure_text(outcome: RunnerOutcome, stderr: str) -> str:
    """Tasniflash uchun qidiriladigan barcha matnni bitta satrga yig'adi.

    Faqat `stderr` yetarli emas: konteyner logi yo'qolgan bo'lsa ham
    `result.json` ichidagi `error_type`/`traceback` saqlanib qoladi.
    """
    payload = outcome.runner_payload
    parts = (stderr, payload.error_type or "", payload.error or "", payload.traceback or "")
    return "\n".join(part for part in parts if part)


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


class PythonRuntime(BaseRuntime):
    """Python 3.12 kodini bajaradigan muhit."""

    runtime = Runtime.PYTHON

    # --- Identifikatsiya ---------------------------------------------------

    @property
    def image(self) -> str:
        """Sandbox Docker image nomi (`make sandbox-build` yasaydi)."""
        return settings.SANDBOX_IMAGE_PYTHON

    @property
    def entrypoint_path(self) -> str:
        """Konteyner ichidagi entrypoint yo'li."""
        return CONTAINER_ENTRYPOINT

    @property
    def local_entrypoint(self) -> Path:
        """Lokal rejimdagi entrypoint fayli (`LocalRunner.available()` tekshiradi)."""
        return LOCAL_ENTRYPOINT

    # --- Bajarish buyruqlari ----------------------------------------------

    def container_command(self, spec: SandboxSpec) -> list[str]:
        """Konteyner ichidagi buyruq.

        `-u` — buferlanmagan chiqish: backend konteyner logini real vaqtda
        o'qiydi, bufer tufayli loglar kechikmasligi kerak.
        """
        del spec  # Buyruq spec'ga bog'liq emas — shartnoma faylda belgilangan.
        return ["python", "-u", CONTAINER_ENTRYPOINT]

    def local_command(self, spec: SandboxSpec, workdir: Path) -> list[str]:
        """Lokal subprocess buyrug'i — joriy virtual muhit interpretatori bilan.

        `workdir` buyruqda ko'rsatilmaydi: entrypoint ish katalogini
        `DURABL_SANDBOX_WORKDIR` muhit o'zgaruvchisidan yoki `cwd` dan oladi
        (`LocalRunner` ikkisini ham to'g'ri qo'yadi).

        Raises:
            SandboxUnavailableError: Entrypoint fayli topilmadi.
        """
        del spec, workdir
        self._require_local_entrypoint()
        return [sys.executable, "-u", str(LOCAL_ENTRYPOINT)]

    def _require_local_entrypoint(self) -> None:
        """Lokal entrypoint mavjudligini tekshiradi.

        Raises:
            SandboxUnavailableError: Fayl yo'q — `sandbox/` katalogi
                deploy'ga qo'shilmagan yoki loyiha ildizi noto'g'ri aniqlangan.
        """
        if LOCAL_ENTRYPOINT.is_file():
            return
        raise SandboxUnavailableError(
            "Python runner entrypoint fayli topilmadi: "
            f"{LOCAL_ENTRYPOINT}. Lokal rejim (`SANDBOX_ENABLED=False`) loyihadagi "
            "`sandbox/runners/python/entrypoint.py` faylini talab qiladi — "
            "repozitoriy to'liq klonlanganini tekshiring.",
            details={"entrypoint": str(LOCAL_ENTRYPOINT), "runtime": self.runtime.value},
        )

    # --- Xatoni tasniflash -------------------------------------------------

    def classify_failure(
        self,
        outcome: RunnerOutcome,
        *,
        stderr: str = "",
    ) -> FailureReason:
        """Python'ga xos belgilar bilan xato sababini aniqlaydi.

        Bazaviy klass allaqachon `timed_out`/`oom_killed`/`infra_error` ni
        hal qiladi; bu yerda faqat "kod xato bilan tugadi" holati aniqlashtiriladi:

        * `MemoryError` / `Killed` / `Cannot allocate memory` -> `OOM`
          (konteyner `OOMKilled` belgisini bermagan holat uchun — masalan
          lokal rejimda yoki `RLIMIT_AS` ishlagan paytda);
        * `SyntaxError` / `IndentationError` / `TabError` -> `VALIDATION_ERROR`
          (kod yaroqsiz, qayta urinish AYNI natijani beradi — retry befoyda).
        """
        reason = super().classify_failure(outcome, stderr=stderr)
        if reason is not FailureReason.NON_ZERO_EXIT:
            return reason

        text = _failure_text(outcome, stderr)
        if outcome.exit_code in OOM_EXIT_CODES or _contains_any(text, OOM_MARKERS):
            return FailureReason.OOM
        if _contains_any(text, VALIDATION_MARKERS):
            return FailureReason.VALIDATION_ERROR
        return reason

    # --- Muhit o'zgaruvchilari --------------------------------------------

    def runtime_env(self, spec: SandboxSpec) -> dict[str, str]:
        """Lokal rejim uchun Python'ga xos muhit o'zgaruvchilari.

        `sandbox/runners/python/Dockerfile` dagi `ENV` qiymatlari bilan bir xil:
        konteynerda ham, lokalda ham interpretator ayni holatda ishlashi kerak.
        """
        del spec
        return {
            "PYTHONUNBUFFERED": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONHASHSEED": "random",
        }


#: Reestrga qo'shilgan yagona nusxa (`get_runtime(Runtime.PYTHON)` shuni beradi).
PYTHON_RUNTIME: Final[BaseRuntime] = register_runtime(PythonRuntime())


__all__ = [
    "CONTAINER_ENTRYPOINT",
    "LOCAL_ENTRYPOINT",
    "OOM_EXIT_CODES",
    "OOM_MARKERS",
    "PROJECT_ROOT",
    "PYTHON_RUNTIME",
    "VALIDATION_MARKERS",
    "PythonRuntime",
]
