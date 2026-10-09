"""Durabl — egasiz sandbox konteynerlarini tozalash (HAQIQIY Docker bilan).

Oddiy ishda qoldiq qolmaydi: `SandboxManager.run()` konteynerni `finally`
da o'chiradi. Qoldiq faqat jarayon O'RTADA o'lganda paydo bo'ladi (SIGKILL,
OOM, deploy) — unda Python'ning `finally` bloki umuman ishlamaydi.

Shu holat testda jarayonni o'ldirmasdan takrorlanadi: konteyner to'g'ridan-
to'g'ri Docker SDK bilan yasaladi, ya'ni uni tozalaydigan `SandboxManager`
umuman mavjud emas — xuddi egasi o'lgandek.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from app.config import settings
from app.execution.executor import Executor
from app.execution.resource_limiter import LABEL_JOB_ID, LABEL_MANAGED, LABEL_MANAGED_VALUE
from app.execution.sandbox_manager import ORPHAN_AGE_FACTOR

import docker

PYTHON_IMAGE = "durabl/runner-python:latest"


def _spawn(client: Any, *, labelled: bool, sleep_seconds: int) -> Any:
    """Yorliqli yoki yorliqsiz, uzoq yashaydigan konteyner yasaydi."""
    labels = {LABEL_MANAGED: LABEL_MANAGED_VALUE, LABEL_JOB_ID: "orphan-test"} if labelled else {}
    return client.containers.run(
        PYTHON_IMAGE,
        ["python", "-u", "-c", f"import time; time.sleep({sleep_seconds})"],
        entrypoint=[""],
        user="10001:10001",
        network_disabled=True,
        labels=labels,
        detach=True,
    )


@pytest.fixture
def docker_client() -> Any:
    return docker.from_env()


async def test_toxtagan_qoldiq_ochiriladi(executor: Executor, docker_client: Any) -> None:
    """Tugagan, yorliqli konteyner tozalanadi."""
    container = _spawn(docker_client, labelled=True, sleep_seconds=0)
    try:
        await asyncio.to_thread(container.wait, timeout=20)
        removed = await executor.cleanup_orphans()
        assert removed >= 1
        with pytest.raises(docker.errors.NotFound):
            container.reload()
    finally:
        try:
            container.remove(force=True)
        except docker.errors.NotFound:
            pass


async def test_yorliqsiz_konteynerga_TEGILMAYDI(executor: Executor, docker_client: Any) -> None:
    """Begona konteyner o'chirilmasligi SHART.

    `cleanup_orphans()` host'da ishlaydi va u yerda Durabl'ga aloqasi
    bo'lmagan konteynerlar bo'lishi mumkin. Yorliq bo'yicha filtrlash —
    yagona himoya; u buzilsa tozalash begona ishlarni o'ldiradi.
    """
    container = _spawn(docker_client, labelled=False, sleep_seconds=30)
    try:
        await executor.cleanup_orphans()
        container.reload()
        assert container.status == "running", "yorliqsiz konteynerga tegildi"
    finally:
        container.remove(force=True)


async def test_tirik_lekin_YOSH_konteynerga_tegilmaydi(
    executor: Executor, docker_client: Any
) -> None:
    """Hali ishlayotgan va yosh job o'ldirilmasligi kerak.

    Boshqa worker uni bajarayotgan bo'lishi mumkin.
    """
    container = _spawn(docker_client, labelled=True, sleep_seconds=30)
    try:
        await executor.cleanup_orphans()
        container.reload()
        assert container.status == "running", "ishlayotgan yosh job o'ldirildi"
    finally:
        container.remove(force=True)


async def test_tirik_lekin_ESKI_konteyner_oldiriladi(
    executor: Executor, docker_client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Egasiz, lekin hamon ishlayotgan konteyner o'ldiriladi.

    ENG MUHIM TEST. Ilgari `cleanup_orphans()` tirik konteynerlarni
    BUTUNLAY chetlab o'tardi — natijada egasi o'lgan konteyner abadiy
    qolib, xotira va CPU yeyaverardi.

    Yosh ishonchli belgi: har bir sandbox'ning qat'iy vaqt chegarasi bor,
    shuning uchun `MAX_TIMEOUT_SECONDS × ORPHAN_AGE_FACTOR` dan uzoq
    yashagan konteyner normal holatda mavjud bo'la olmaydi.

    Testda kutish o'rniga CHEGARA pasaytiriladi — aks holda test
    `900 × 2` soniya kutishi kerak bo'lardi.
    """
    monkeypatch.setattr(settings, "MAX_TIMEOUT_SECONDS", 2)
    threshold = 2 * ORPHAN_AGE_FACTOR

    container = _spawn(docker_client, labelled=True, sleep_seconds=120)
    try:
        # Hali chegaradan o'tmagan — tegilmasligi kerak
        assert await executor.cleanup_orphans() == 0
        container.reload()
        assert container.status == "running"

        await asyncio.sleep(threshold + 2)

        assert await executor.cleanup_orphans() >= 1
        with pytest.raises(docker.errors.NotFound):
            container.reload()
    finally:
        try:
            container.remove(force=True)
        except docker.errors.NotFound:
            pass
