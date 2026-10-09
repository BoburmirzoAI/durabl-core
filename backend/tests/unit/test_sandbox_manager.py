"""Durabl — `SandboxManager` ning Docker bilan ishlash mantig'i (mock bilan).

Haqiqiy konteyner ishga tushirish `@pytest.mark.docker` testlarida (`make
test-docker`). Bu fayl esa Docker DEMONISIZ tekshiradigan, lekin production'da
eng qimmatga tushadigan xatti-harakatlarni qamraydi:

* `start()` yiqilganda YARATILGAN konteyner o'chiriladimi (resurs oqishi);
* Docker API osilib qolsa vaqt chegarasi ishlaydimi;
* `close()` fon'dagi tozalashni kutadimi.

Nega bu muhim: `docker-py` ning `containers.run()` ichida `create()` dan keyin
`start()` chaqiriladi, lekin `start()` yiqilsa konteyner O'CHIRILMAYDI. Noto'g'ri
seccomp profili yoki ro'yxatdan o'tmagan runtime bilan har bir retry `Created`
holatidagi o'lik konteyner qoldiradi — bir necha ming retry diskni to'ldiradi.
Shuning uchun `SandboxManager` `create()` va `start()` ni ALOHIDA chaqiradi.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from app.config import settings
from app.constants import Runtime
from app.exceptions import SandboxStartupError
from app.execution.runtime_python import PythonRuntime
from app.execution.sandbox_manager import SandboxManager
from app.execution.types import ResourceLimits, SandboxSpec
from docker.errors import APIError, ImageNotFound

pytestmark = pytest.mark.unit

RUNTIME = PythonRuntime()


def make_spec(**overrides: Any) -> SandboxSpec:
    """Sinov uchun minimal `SandboxSpec`."""
    params: dict[str, Any] = {
        "job_id": "test-job",
        "code": "print(1)",
        "runtime": Runtime.PYTHON,
        "limits": ResourceLimits(timeout_seconds=10),
    }
    params.update(overrides)
    return SandboxSpec(**params)


class FakeContainer:
    """Minimal `docker` konteyner dubli — faqat sinovga kerakli metodlar."""

    def __init__(self, *, start_error: Exception | None = None, start_hangs: bool = False) -> None:
        self.id = "c0ffee123456"
        self.attrs: dict[str, Any] = {"State": {"OOMKilled": False}}
        self._start_error = start_error
        self._start_hangs = start_hangs
        self.removed = False
        self.remove_forced = False
        self.start_calls = 0

    def start(self) -> None:
        self.start_calls += 1
        if self._start_hangs:
            # Docker demoni javob bermayotgan holat (thread bloklanadi)
            import time

            # Qisqa kutish yetarli: vaqt chegarasi testda 0.2s qilib qo'yiladi.
            # Uzoq kutish butun to'plamni sekinlashtiradi (thread bekor
            # qilinmaydi, pytest chiqishda uni kutadi).
            time.sleep(1.5)
        if self._start_error is not None:
            raise self._start_error

    def remove(self, *, force: bool = False) -> None:
        self.removed = True
        self.remove_forced = force


class FakeContainers:
    """`client.containers` dubli."""

    def __init__(self, container: FakeContainer, *, create_error: Exception | None = None) -> None:
        self._container = container
        self._create_error = create_error
        self.create_kwargs: dict[str, Any] | None = None

    def create(self, image: str, command: Any, **kwargs: Any) -> FakeContainer:
        if self._create_error is not None:
            raise self._create_error
        self.create_kwargs = {"image": image, "command": command, **kwargs}
        return self._container

    def list(self, **_kwargs: Any) -> list[FakeContainer]:
        return []


class FakeClient:
    """`docker.DockerClient` dubli."""

    def __init__(self, containers: FakeContainers) -> None:
        self.containers = containers
        self.closed = False

    def ping(self) -> bool:
        return True

    def close(self) -> None:
        self.closed = True


async def _start(
    manager: SandboxManager,
    client: FakeClient,
    spec: SandboxSpec,
    tmp_path: Any,
) -> Any:
    """`_start_container` ni to'g'ridan-to'g'ri chaqiradi (xususiy, lekin shartnoma)."""
    return await manager._start_container(client, spec, RUNTIME, tmp_path)


# ---------------------------------------------------------------------------
# Resurs oqishi — eng muhim regressiya
# ---------------------------------------------------------------------------


async def test_start_yiqilsa_konteyner_ochiriladi(tmp_path: Any) -> None:
    """KRITIK: `start()` xatosi YARATILGAN konteynerni qoldirmasligi SHART."""
    container = FakeContainer(start_error=APIError("seccomp profili rad etildi"))
    client = FakeClient(FakeContainers(container))
    manager = SandboxManager()

    with pytest.raises(SandboxStartupError):
        await _start(manager, client, make_spec(), tmp_path)

    assert container.removed is True, "konteyner o'chirilmadi — resurs oqishi!"
    assert container.remove_forced is True, "`force=True` ishlatilmadi"


async def test_create_yiqilsa_ochirish_kerak_emas(tmp_path: Any) -> None:
    """`create()` yiqilsa konteyner yaratilmagan — o'chirish urinilmaydi."""
    container = FakeContainer()
    client = FakeClient(FakeContainers(container, create_error=APIError("yaroqsiz runtime")))
    manager = SandboxManager()

    with pytest.raises(SandboxStartupError, match="ishga tushmadi"):
        await _start(manager, client, make_spec(), tmp_path)

    assert container.removed is False


async def test_image_topilmasa_tushunarli_xato(tmp_path: Any) -> None:
    """Image yo'q bo'lsa xabar `make sandbox-build` ni aytadi."""
    client = FakeClient(
        FakeContainers(FakeContainer(), create_error=ImageNotFound("yo'q"))
    )
    manager = SandboxManager()

    with pytest.raises(SandboxStartupError, match="make sandbox-build"):
        await _start(manager, client, make_spec(), tmp_path)


# ---------------------------------------------------------------------------
# Docker API osilib qolishi
# ---------------------------------------------------------------------------


async def test_start_osilsa_vaqt_chegarasi_ishlaydi(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Demon javob bermasa worker job vaqtini kutib o'tirmaydi.

    `SANDBOX_STARTUP_TIMEOUT_SECONDS` job'ning o'z timeout'idan ALOHIDA
    chegara: nosoz demon butun worker hovuzini qulflab qo'ymasligi uchun.
    """
    monkeypatch.setattr(settings, "SANDBOX_STARTUP_TIMEOUT_SECONDS", 0.2)
    container = FakeContainer(start_hangs=True)
    client = FakeClient(FakeContainers(container))
    manager = SandboxManager()

    with pytest.raises(SandboxStartupError, match="javob bermadi"):
        await _start(manager, client, make_spec(), tmp_path)

    # Tozalash FON'da rejalashtirilgan (thread bekor qilinmaydi, lekin
    # worker darhol bo'shaydi)
    assert manager._cleanup_tasks, "tozalash vazifasi rejalashtirilmadi"


async def test_close_fondagi_tozalashni_kutadi(monkeypatch: pytest.MonkeyPatch) -> None:
    """`close()` fon'dagi o'chirish vazifalarini kutadi."""
    monkeypatch.setattr(settings, "SANDBOX_STARTUP_TIMEOUT_SECONDS", 1.0)
    container = FakeContainer()
    manager = SandboxManager()
    manager._schedule_remove(container)
    assert len(manager._cleanup_tasks) == 1

    await manager.close()

    assert container.removed is True
    assert not manager._cleanup_tasks, "vazifalar to'plami bo'shatilmadi"


async def test_close_tiqilib_qolgan_tozalashni_bekor_qiladi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tozalash ham osilsa `close()` abadiy kutmaydi (vazifa bekor qilinadi)."""
    monkeypatch.setattr(settings, "SANDBOX_STARTUP_TIMEOUT_SECONDS", 0.2)

    class StuckContainer(FakeContainer):
        def remove(self, *, force: bool = False) -> None:
            import time

            # Qisqa kutish yetarli: vaqt chegarasi testda 0.2s qilib qo'yiladi.
            # Uzoq kutish butun to'plamni sekinlashtiradi (thread bekor
            # qilinmaydi, pytest chiqishda uni kutadi).
            time.sleep(1.5)

    manager = SandboxManager()
    manager._schedule_remove(StuckContainer())

    await asyncio.wait_for(manager.close(), timeout=5.0)


# ---------------------------------------------------------------------------
# Xavfsizlik parametrlari konteynerga yetib boradimi
# ---------------------------------------------------------------------------


async def test_xavfsizlik_parametrlari_uzatiladi(tmp_path: Any) -> None:
    """Yaratishda barcha izolyatsiya parametrlari berilishi SHART."""
    container = FakeContainer()
    containers = FakeContainers(container)
    client = FakeClient(containers)
    manager = SandboxManager()

    await _start(manager, client, make_spec(), tmp_path)

    kwargs = containers.create_kwargs
    assert kwargs is not None
    assert kwargs["read_only"] is True
    assert kwargs["network_mode"] == settings.SANDBOX_NETWORK_MODE
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["user"] == settings.SANDBOX_USER
    assert kwargs["mem_limit"].endswith("m")
    assert kwargs["memswap_limit"] == kwargs["mem_limit"], "swap o'chirilmagan!"
    assert kwargs["labels"]["durabl.managed"] == "true", "orphan tozalash uchun yorliq yo'q"
    # Kod va natija shu bind-mount orqali almashinadi
    assert str(tmp_path) in kwargs["volumes"]
