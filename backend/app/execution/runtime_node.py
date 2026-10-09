"""Durabl — Node.js bajarish muhiti (runtime).

`BaseRuntime` ning JavaScript uchun konkret amalga oshirilishi. Python
variantidan farqlari faqat uchta: image, buyruq va tilga xos xato belgilari —
qolgan hamma narsa (fayl tayyorlash, `result.json` o'qish) bazaviy klassda.

Shartnoma (`sandbox/runners/node/`):

* konteynerdagi entrypoint — `/opt/durabl/entrypoint.js`
* lokal entrypoint        — `<loyiha>/sandbox/runners/node/entrypoint.js`
* mijoz kodi              — `<workdir>/main.js`
* natija                  — `<workdir>/result.json`

`vm` moduli ATAYLAB ishlatilmaydi (izolyatsiya bermaydi va
`NODE_FORBIDDEN_MODULES` ro'yxatida) — haqiqiy izolyatsiya gVisor darajasida.
"""

from __future__ import annotations

import shutil
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

#: Loyiha ildizi: `backend/app/execution/runtime_node.py` -> parents[3].
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]

#: Lokal (Docker'siz) rejimda ishga tushiriladigan entrypoint.
LOCAL_ENTRYPOINT: Final[Path] = PROJECT_ROOT / "sandbox" / "runners" / "node" / "entrypoint.js"

#: Konteyner ichidagi entrypoint yo'li (`sandbox/runners/node/Dockerfile`).
CONTAINER_ENTRYPOINT: Final[str] = "/opt/durabl/entrypoint.js"

#: Lokal rejimda qidiriladigan interpretator nomi.
NODE_EXECUTABLE: Final[str] = "node"

#: Konteyner xotira limitining V8 "old space" ga beriladigan ulushi.
#: `sandbox/runners/node/Dockerfile` da 256 MB konteyner uchun 192 MB
#: (`--max-old-space-size=192`) qo'yilgan — ayni shu nisbat saqlanadi.
V8_HEAP_RATIO: Final[float] = 0.75
#: V8 uchun eng kichik ma'noli heap hajmi (MB).
MIN_V8_HEAP_MB: Final[int] = 64


# ---------------------------------------------------------------------------
# Xato belgilari
# ---------------------------------------------------------------------------

#: V8 xotira tugaganida chiqaradigan matnlar.
#: Tipik ko'rinishi:
#:   FATAL ERROR: Reached heap limit Allocation failed -
#:   JavaScript heap out of memory
OOM_MARKERS: Final[tuple[str, ...]] = (
    "JavaScript heap out of memory",
    "Allocation failed",
    "Reached heap limit",
    "ERR_WORKER_OUT_OF_MEMORY",
    "Cannot allocate memory",
    "Killed",
)

#: Kod sintaktik jihatdan yaroqsiz — retry befoyda.
VALIDATION_MARKERS: Final[tuple[str, ...]] = (
    "SyntaxError",
    "ERR_MODULE_NOT_FOUND",
)

#: OOM killer SIGKILL yuborganda ko'rinadigan chiqish kodlari.
OOM_EXIT_CODES: Final[tuple[int, ...]] = (137, -9)


def _contains_any(haystack: str, markers: tuple[str, ...]) -> bool:
    """Matnda berilgan belgilardan birortasi bormi."""
    return any(marker in haystack for marker in markers)


def _failure_text(outcome: RunnerOutcome, stderr: str) -> str:
    """Tasniflash uchun qidiriladigan barcha matnni bitta satrga yig'adi."""
    payload = outcome.runner_payload
    parts = (stderr, payload.error_type or "", payload.error or "", payload.traceback or "")
    return "\n".join(part for part in parts if part)


# ---------------------------------------------------------------------------
# Runtime
# ---------------------------------------------------------------------------


class NodeRuntime(BaseRuntime):
    """Node.js kodini bajaradigan muhit."""

    runtime = Runtime.NODE

    # --- Identifikatsiya ---------------------------------------------------

    @property
    def image(self) -> str:
        """Sandbox Docker image nomi (`make sandbox-build` yasaydi)."""
        return settings.SANDBOX_IMAGE_NODE

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

        Node stdout'ni quvurga yozganda ham satr-satr tozalaydi, shuning uchun
        Python'dagi `-u` kabi bayroq kerak emas.
        """
        del spec  # Buyruq spec'ga bog'liq emas — shartnoma faylda belgilangan.
        return ["node", CONTAINER_ENTRYPOINT]

    def local_command(self, spec: SandboxSpec, workdir: Path) -> list[str]:
        """Lokal subprocess buyrug'i — tizimdagi `node` bilan.

        Raises:
            SandboxUnavailableError: Entrypoint fayli yoki `node` topilmadi.
        """
        del spec, workdir
        self._require_local_entrypoint()
        return [self._require_node(), str(LOCAL_ENTRYPOINT)]

    def _require_local_entrypoint(self) -> None:
        """Lokal entrypoint mavjudligini tekshiradi.

        Raises:
            SandboxUnavailableError: Fayl yo'q — `sandbox/` katalogi
                deploy'ga qo'shilmagan yoki loyiha ildizi noto'g'ri aniqlangan.
        """
        if LOCAL_ENTRYPOINT.is_file():
            return
        raise SandboxUnavailableError(
            "Node runner entrypoint fayli topilmadi: "
            f"{LOCAL_ENTRYPOINT}. Lokal rejim (`SANDBOX_ENABLED=False`) loyihadagi "
            "`sandbox/runners/node/entrypoint.js` faylini talab qiladi — "
            "repozitoriy to'liq klonlanganini tekshiring.",
            details={"entrypoint": str(LOCAL_ENTRYPOINT), "runtime": self.runtime.value},
        )

    def _require_node(self) -> str:
        """`node` interpretatorining to'liq yo'lini qaytaradi.

        Raises:
            SandboxUnavailableError: Interpretator tizimda o'rnatilmagan.
        """
        found = shutil.which(NODE_EXECUTABLE)
        if found:
            return found
        raise SandboxUnavailableError(
            "Node interpretatori topilmadi (`node`). Lokal rejimda JavaScript "
            "job'larini bajarish uchun Node.js o'rnatilishi kerak; production'da "
            "esa `SANDBOX_ENABLED=True` bo'lib, kod konteyner ichida bajariladi.",
            details={"executable": NODE_EXECUTABLE, "runtime": self.runtime.value},
        )

    # --- Xatoni tasniflash -------------------------------------------------

    def classify_failure(
        self,
        outcome: RunnerOutcome,
        *,
        stderr: str = "",
    ) -> FailureReason:
        """Node'ga xos belgilar bilan xato sababini aniqlaydi.

        * `JavaScript heap out of memory`, `FATAL ERROR: ... Allocation failed`
          -> `OOM` (V8 o'zi yiqiladi, konteyner `OOMKilled` bermasligi mumkin);
        * `SyntaxError` -> `VALIDATION_ERROR` (kod yaroqsiz, retry befoyda).
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
        """Lokal rejim uchun Node'ga xos muhit o'zgaruvchilari.

        `NODE_OPTIONS=--max-old-space-size=...` — V8 ichki heap chegarasi
        konteyner/cgroup limitidan PAST turadi. Shu tufayli xotira tugaganda
        kernel OOM killer emas, V8 o'zi tushunarli xabar bilan yiqiladi
        (`JavaScript heap out of memory`) — `classify_failure` uni OOM deb
        belgilaydi.
        """
        heap_mb = max(MIN_V8_HEAP_MB, int(spec.limits.memory_mb * V8_HEAP_RATIO))
        return {
            "NODE_ENV": "production",
            "NODE_OPTIONS": f"--max-old-space-size={heap_mb}",
            "NO_UPDATE_NOTIFIER": "1",
        }


#: Reestrga qo'shilgan yagona nusxa (`get_runtime(Runtime.NODE)` shuni beradi).
NODE_RUNTIME: Final[BaseRuntime] = register_runtime(NodeRuntime())


__all__ = [
    "CONTAINER_ENTRYPOINT",
    "LOCAL_ENTRYPOINT",
    "MIN_V8_HEAP_MB",
    "NODE_EXECUTABLE",
    "NODE_RUNTIME",
    "OOM_EXIT_CODES",
    "OOM_MARKERS",
    "PROJECT_ROOT",
    "V8_HEAP_RATIO",
    "VALIDATION_MARKERS",
    "NodeRuntime",
]
