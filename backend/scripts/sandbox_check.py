"""Durabl — sandbox orqali sinov job'ini bajaradi va natijani ko'rsatadi.

## Nega kerak

`make sandbox-test` bu skriptni WORKER muhitida ishga tushiradi va to'rt
narsani ko'rsatadi:

1. Kod chindan bajariladimi (natija qaytadimi);
2. Tarmoq bloklanganmi (`--network=none` ishlayaptimi);
3. Fayl tizimi read-only'mi;
4. Jarayon non-root sifatida ishlayaptimi.

Bu DB'ga tegmaydi va API'ni talab qilmaydi — faqat bajarish qatlamini
tekshiradi. Shuning uchun "sandbox ishlayaptimi?" degan savolga eng tez
javob shu.

## Qaysi runtime

`SANDBOX_RUNTIME` nimaga o'rnatilgan bo'lsa, o'sha ishlatiladi:
`runc` (macOS/dev) yoki `runsc` (Linux + gVisor). Skript qaysi biri
ishlatilganini chiqarishda ko'rsatadi — natija chalg'itmasligi uchun.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.execution.local_runner import LocalRunner
from app.execution.runtime_base import get_runtime
from app.execution.sandbox_manager import SandboxManager
from app.execution.types import ResourceLimits, SandboxSpec
from app.logging_config import setup_logging

#: Har bir tekshiruv: nom, runtime, kod, kutilgan natija izohi.
CHECKS: list[tuple[str, str, str, str]] = [
    (
        "kod bajariladi",
        "python",
        "def main():\n    return {'answer': 6 * 7}\n",
        "result={'answer': 42}",
    ),
    (
        "node runtime",
        "node",
        "module.exports = async function main() { return { answer: 6 * 7 }; };\n",
        "result={'answer': 42}",
    ),
    (
        "tarmoq bloklangan",
        "python",
        (
            "import urllib.request\n"
            "def main():\n"
            "    urllib.request.urlopen('http://example.com', timeout=3)\n"
            "    return 'TARMOQ OCHIQ — XAVF!'\n"
        ),
        "xato (tarmoq yopiq bo'lishi kerak)",
    ),
    (
        "fayl tizimi read-only",
        "python",
        "def main():\n    open('/etc/durabl-test', 'w').write('x')\n    return 'YOZILDI — XAVF!'\n",
        "xato (yozib bo'lmasligi kerak)",
    ),
    (
        "non-root foydalanuvchi",
        "python",
        "import os\ndef main():\n    return {'uid': os.getuid(), 'gid': os.getgid()}\n",
        "uid != 0",
    ),
]


def _emit(line: str = "") -> None:
    print(line, flush=True)


async def _run_one(label: str, runtime_name: str, code: str, expectation: str) -> bool:
    """Bitta tekshiruvni bajaradi. Har safar YANGI manager (konteyner bir martalik)."""
    spec = SandboxSpec(
        job_id=f"sandbox_check_{label.replace(' ', '_')[:20]}",
        code=code,
        runtime=runtime_name,
        limits=ResourceLimits(timeout_seconds=25, memory_mb=256, cpus=0.5),
        payload={"args": [], "kwargs": {}},
    )

    manager: SandboxManager | LocalRunner = (
        SandboxManager() if settings.SANDBOX_ENABLED else LocalRunner()
    )
    try:
        outcome = await asyncio.wait_for(manager.run(spec, get_runtime(runtime_name)), timeout=120)
    except Exception as exc:
        _emit(f"  XATO  {label:<24} {type(exc).__name__}: {str(exc)[:90]}")
        return False
    finally:
        close = getattr(manager, "close", None)
        if close is not None:
            await close()

    payload = outcome.runner_payload
    result = getattr(payload, "result", None)
    error = getattr(payload, "error", None)

    # "Xato kutilgan" tekshiruvlar (tarmoq, read-only) uchun exit != 0 — bu YAXSHI
    wants_failure = "xato" in expectation
    ok = (outcome.exit_code != 0) if wants_failure else (outcome.exit_code == 0)

    detail = (
        f"result={result}"
        if result is not None
        else f"error={str(error)[:60]}"
        if error
        else f"exit={outcome.exit_code}"
    )
    _emit(f"  {'OK   ' if ok else 'XATO '}{label:<24} {detail}")
    return ok


async def main() -> int:
    setup_logging()

    mode = "sandbox (Docker)" if settings.SANDBOX_ENABLED else "LocalRunner (IZOLYATSIYASIZ)"
    _emit("\n  Durabl — sandbox tekshiruvi")
    _emit("  " + "-" * 44)
    _emit(f"  Rejim    {mode}")
    _emit(f"  Runtime  {settings.SANDBOX_RUNTIME}")
    if settings.SANDBOX_ENABLED and settings.SANDBOX_RUNTIME != "runsc":
        _emit("  Eslatma  gVisor EMAS. Linux'da: make gvisor-install")
    _emit()

    results = [await _run_one(*check) for check in CHECKS]
    passed = sum(results)

    _emit()
    _emit(f"  {passed}/{len(results)} tekshiruv o'tdi")
    if passed == len(results):
        _emit("  Sandbox ishlayapti.\n")
        return 0
    _emit("  Muammo bor — loglarni ko'ring: make logs-worker\n")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
