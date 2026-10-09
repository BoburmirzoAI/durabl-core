"""Durabl — haqiqiy Docker talab qiladigan testlar uchun fixture'lar.

## Nega alohida papka

Qolgan testlar SQLite xotira bazasi va `fakeredis` bilan ishlaydi — ular
tashqi hech narsaga bog'liq emas va millisekundlarda o'tadi. Bu yerdagi
testlar esa HAQIQIY konteyner ishga tushiradi: Docker demoni, yig'ilgan
`durabl/runner-*` image'lari va bir necha soniya vaqt kerak.

Ikkalasini aralashtirish ikki tomonga ham zarar: tez testlar sekinlashadi,
sekin testlar esa "Docker yo'q" sababli CI'da yiqilib, hammani bezovta
qiladi. Shuning uchun ular `@pytest.mark.docker` bilan ajratilgan va
`pyproject.toml` dagi `addopts` ularni STANDART ishga tushirishdan
chiqarib tashlaydi.

## DIQQAT: bitta testni yakka ishga tushirish

`addopts` da `-m "not docker"` turgani uchun yo'l bo'yicha chaqirish
JIM ravishda hech narsa ishlatmaydi::

    pytest tests/docker/test_sandbox_execution.py::test_x   # 1 deselected

Markerni ochiq bekor qilish kerak::

    pytest tests/docker/test_sandbox_execution.py::test_x -m docker

Butun to'plam uchun: `make test-sandbox`.

## Nega bu testlar KERAK edi

Sandbox yo'lini qoplaydigan test YO'Q edi (marker `pyproject.toml` da
e'lon qilingan, lekin hech qayerda ishlatilmagan). Oqibati real bo'ldi:
natija bazaga yozilmayapti deb noto'g'ri tashxis qo'yildi, aslida sabab
butunlay boshqa joyda edi (payload'siz job'da kirish funksiyasi
chaqirilmaydi). Bitta test shu xatoni oldini olardi.
"""

from __future__ import annotations

import pathlib
from collections.abc import AsyncIterator
from typing import Any

import pytest
from app.constants import Runtime
from app.execution.executor import Executor
from app.execution.sandbox_manager import SandboxManager
from app.execution.types import ResourceLimits, SandboxSpec

#: Testlarda ishlatiladigan image'lar — yo'q bo'lsa butun modul o'tkaziladi.
REQUIRED_IMAGES = {
    Runtime.PYTHON: "durabl/runner-python:latest",
    Runtime.NODE: "durabl/runner-node:latest",
}


def _docker_state() -> tuple[bool, str]:
    """`(tayyormi, sabab)` — Docker va image'lar holatini tekshiradi."""
    try:
        import docker
    except ImportError:  # pragma: no cover - docker SDK har doim o'rnatilgan
        return False, "docker SDK o'rnatilmagan"

    try:
        client = docker.from_env()
        client.ping()
    except Exception as exc:
        return False, f"Docker demoniga ulanib bo'lmadi: {type(exc).__name__}"

    missing = []
    for image in REQUIRED_IMAGES.values():
        try:
            client.images.get(image)
        except Exception:
            missing.append(image)
    if missing:
        return False, f"image yo'q ({', '.join(missing)}) — `make sandbox-build` qiling"
    return True, ""


_READY, _SKIP_REASON = _docker_state()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Shu papkadagi HAR BIR testga `docker` markerini qo'yadi.

    Nega hook, nega `pytestmark` emas: `conftest.py` dagi `pytestmark`
    test modullariga TARQALMAYDI — u faqat o'sha fayl ichidagi testlarga
    ta'sir qiladi. Natijada `pytest -m docker` hech narsa topmasdi va
    `make test-sandbox` jimgina "0 ta test o'tdi" deb muvaffaqiyat
    qaytarardi. Aynan shunday jim muvaffaqiyat bu testlar yozilishiga
    sabab bo'lgan muammoning o'zi.

    Hook esa papkaga yangi fayl qo'shilganda ham ishlaydi — markerni
    yozishni unutib bo'lmaydi.
    """
    skip = pytest.mark.skipif(not _READY, reason=_SKIP_REASON or "Docker tayyor emas")
    here = pathlib.Path(__file__).parent
    for item in items:
        if here in pathlib.Path(str(item.fspath)).parents:
            item.add_marker(pytest.mark.docker)
            item.add_marker(skip)


@pytest.fixture
def limits() -> ResourceLimits:
    """Testlar uchun qisqa timeout — yiqilgan test 30 soniya kutmasin."""
    return ResourceLimits(timeout_seconds=20, memory_mb=256, allow_network=False)


@pytest.fixture
async def executor() -> AsyncIterator[Executor]:
    """Haqiqiy sandbox bilan ishlaydigan `Executor`.

    `runner` ATAYLAB ochiq beriladi: `Executor.default_runner()` sozlamaga
    (`SANDBOX_ENABLED`) qaraydi, bu testlar esa sozlamadan qat'i nazar
    HAQIQIY konteynerni tekshirishi kerak.
    """
    manager = SandboxManager()
    try:
        yield Executor(runner=manager)
    finally:
        await manager.close()


def make_spec(
    code: str,
    *,
    limits: ResourceLimits,
    runtime: Runtime = Runtime.PYTHON,
    payload: dict[str, Any] | None = None,
    job_id: str = "test-job",
) -> SandboxSpec:
    """Qisqa yordamchi — har bir testda bir xil shablonni takrorlamaslik uchun."""
    return SandboxSpec(
        job_id=job_id,
        code=code,
        runtime=runtime,
        limits=limits,
        payload=payload,
        correlation_id="test-correlation",
    )
