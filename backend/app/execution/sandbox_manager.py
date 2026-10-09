"""Durabl — gVisor/Docker sandbox runner (production).

`SandboxRunner` protokolining konteyner asosidagi amalga oshirilishi. Mijoz
kodi bir martalik konteynerda, gVisor (`runsc`) runtime'i ostida bajariladi:

    tempfile.mkdtemp()                 host katalogi (kod + payload + natija)
        |  bind-mount -> /sandbox
        v
    docker run --runtime=runsc --network=none --read-only ...
        |  entrypoint (/opt/durabl/entrypoint.py|js)
        v
    stdout/stderr -> konteyner logi -> `on_log(stream, chunk)`
    natija        -> /sandbox/result.json -> `RunnerPayload`

**Nega `asyncio.to_thread` hamma joyda:** `docker` (docker-py) SDK sinxron
`requests` ustiga qurilgan va HAR BIR chaqiruv event loop'ni bloklaydi. Bitta
`container.wait()` 900 soniyaga cho'zilishi mumkin — u loop'ni to'xtatib
qo'ysa, worker'ning heartbeat'i ham to'xtaydi va lease yo'qoladi. Shuning
uchun istisnosiz hamma blokiruvchi chaqiruv alohida thread'da bajariladi.

**Loglar:** `container.logs(stream=True, follow=True)` — blokiruvchi generator.
U alohida thread'da aylanadi va chunk'larni `asyncio.Queue` ga uzatadi; asosiy
koroutina navbatdan olib `on_log` ni chaqiradi. Navbat CHEGARALANGAN: mijoz
kodi gigabayt chiqarsa ham xotira o'smaydi, thread navbat bo'shashini kutadi
(backpressure).

**Xatolar siyosati:**

* image yo'q / `runsc` sozlanmagan -> `SandboxStartupError` (tushunarli xabar,
  nima qilish kerakligi bilan: `make sandbox-build`);
* Docker demoni javob bermaydi -> `available()` `False`, `run()` esa
  `SandboxUnavailableError`;
* qolgan Docker xatolari -> `RunnerOutcome(infra_error=...)`, ya'ni xato
  TASHLANMAYDI — `ResultCollector` uni `SANDBOX_ERROR` deb tasniflaydi va
  `ReliabilityService` qayta urinishni hal qiladi.
"""

from __future__ import annotations

import asyncio
import codecs
import contextlib
import os
import shutil
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Final

from app.config import settings
from app.constants import SANDBOX_WORKDIR, LogStream
from app.exceptions import SandboxError, SandboxStartupError, SandboxUnavailableError
from app.execution.resource_limiter import (
    LABEL_MANAGED,
    LABEL_MANAGED_VALUE,
    limits_summary,
    to_docker_kwargs,
    to_sandbox_env,
)
from app.execution.runtime_base import BaseRuntime, LogSink
from app.execution.types import RunnerOutcome, RunnerPayload, SandboxSpec
from app.logging_config import get_logger
from app.metrics import observe_sandbox_create

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Docker SDK — ixtiyoriy bog'liqlik
# ---------------------------------------------------------------------------
#
# `docker` paketi o'rnatilmagan muhitda ham (masalan faqat API protsessi)
# bu modul import bo'lishi kerak: `available()` `False` qaytaradi, `run()`
# esa tushunarli `SandboxUnavailableError` tashlaydi.

try:  # pragma: no cover - paket mavjudligiga bog'liq
    from docker.errors import APIError, DockerException, ImageNotFound, NotFound

    import docker
except ImportError:  # pragma: no cover - `docker` o'rnatilmagan
    docker = None  # type: ignore[assignment]

    class DockerException(Exception):  # type: ignore[no-redef]
        """`docker` paketi yo'q bo'lganda ishlatiladigan o'rinbosar."""

    class APIError(DockerException):  # type: ignore[no-redef]
        """`docker` paketi yo'q bo'lganda ishlatiladigan o'rinbosar."""

    class ImageNotFound(DockerException):  # type: ignore[no-redef]
        """`docker` paketi yo'q bo'lganda ishlatiladigan o'rinbosar."""

    class NotFound(DockerException):  # type: ignore[no-redef]
        """`docker` paketi yo'q bo'lganda ishlatiladigan o'rinbosar."""


try:  # pragma: no cover - `requests` docker bilan birga keladi
    from requests.exceptions import RequestException
except ImportError:  # pragma: no cover

    class RequestException(Exception):  # type: ignore[no-redef]
        """`requests` yo'q bo'lganda ishlatiladigan o'rinbosar."""


#: `except` bloklarida takrorlanadigan Docker/tarmoq xatolari.
DOCKER_ERRORS: Final[tuple[type[BaseException], ...]] = (
    DockerException,
    RequestException,
    OSError,
)

#: `DOCKER_ERRORS` + `SandboxError` — "klient yasalmadi YOKI Docker javob
#: bermadi" holatlari. Tayyor konstanta sifatida e'lon qilinadi, chunki
#: `except (SandboxError, *DOCKER_ERRORS)` ko'rinishidagi yoyishni tur
#: tekshiruvchi tanimaydi (ish vaqtida esa farq yo'q).
SANDBOX_OR_DOCKER_ERRORS: Final[tuple[type[BaseException], ...]] = (
    SandboxError,
    *DOCKER_ERRORS,
)

#: `container.attach()` qo'llab-quvvatlanmaganda `TypeError` ham chiqadi.
ATTACH_ERRORS: Final[tuple[type[BaseException], ...]] = (TypeError, *DOCKER_ERRORS)


# ---------------------------------------------------------------------------
# Konstantalar
# ---------------------------------------------------------------------------

#: Vaqtinchalik ish katalogi nomining boshlanishi.
TEMP_DIR_PREFIX: Final[str] = "durabl-sandbox-"

#: `sandbox_id` sifatida saqlanadigan konteyner id'si uzunligi (Docker uslubi).
SANDBOX_ID_LENGTH: Final[int] = 12

#: Konteyner SIGKILL bilan o'ldirilganda Docker qaytaradigan chiqish kodi.
DOCKER_SIGKILL_EXIT_CODE: Final[int] = 137

#: Log navbatining maksimal uzunligi. Chegara MAJBURIY: aks holda juda
#: "gapdon" kod event loop'dan tez yozib, xotirani to'ldirib qo'yardi.
LOG_QUEUE_MAXSIZE: Final[int] = 256

#: Thread navbatga chunk qo'yishni qancha kutadi (soniya). Oshsa chunk
#: tashlab yuboriladi — log yo'qolishi bajarishni to'xtatishdan afzal.
LOG_QUEUE_PUT_TIMEOUT_SECONDS: Final[float] = 30.0

#: Konteyner tugagandan keyin qolgan loglarni yig'ib olishga berilgan vaqt.
LOG_DRAIN_TIMEOUT_SECONDS: Final[float] = 10.0

#: Konteynerni ishga tushirishdan oldin log oqimiga ulanishni qancha kutamiz.
#:
#: Ulanish `asyncio.to_thread` ichida bo'ladi va thread havzasi band bo'lsa
#: navbat kutadi. Cheksiz kutish job'ni bloklab qo'yardi, shuning uchun
#: chegara bor: oshsa loglarsiz davom etamiz (ish natijasi loglardan
#: muhimroq), lekin buni ochiq ogohlantirish bilan yozamiz.
LOG_ATTACH_TIMEOUT_SECONDS: Final[float] = 5.0

#: HTTP klient timeout'i: eng uzun job + zaxira. `container.wait()` ayni shu
#: timeout bilan cheklangani uchun u MAX_TIMEOUT_SECONDS dan katta bo'lishi shart.
CLIENT_TIMEOUT_MARGIN_SECONDS: Final[int] = 120

#: `kill()` da SIGKILL va `remove()` orasidagi kutish.
KILL_GRACE_SECONDS: Final[float] = max(0.1, settings.SANDBOX_KILL_GRACE_SECONDS)

#: Hali tirik bo'lgan konteyner holatlari — orphan tozalashda TEGILMAYDI.
LIVE_CONTAINER_STATUSES: Final[frozenset[str]] = frozenset(
    {"running", "restarting", "paused", "removing"}
)

#: Bind-mount qilingan katalog huquqlari.
#: Konteyner imtiyozsiz foydalanuvchi (`settings.SANDBOX_USER`, 10001) ostida
#: ishlaydi va `result.json` ni SHU katalogga yozishi kerak, host katalogi esa
#: `mkdtemp` tufayli 0700 (faqat backend foydalanuvchisi) bo'ladi. Katalog
#: bir martalik va ichida sir yo'q, shuning uchun hammaga yozishga ruxsat
#: beriladi — aks holda natija fayli umuman yozilmaydi.
WORKDIR_MODE: Final[int] = 0o777


def _create_client() -> Any:
    """Docker klientini yaratadi (BLOKLAYDI — `asyncio.to_thread` ichida chaqiriladi).

    Raises:
        SandboxUnavailableError: `docker` paketi yo'q yoki demon javob bermaydi.
    """
    if docker is None:  # pragma: no cover - `docker` o'rnatilmagan
        raise SandboxUnavailableError(
            "`docker` paketi o'rnatilmagan — sandbox rejimi ishlamaydi. "
            "Backend bog'liqliklarini to'liq o'rnatish kerak yoki development "
            "uchun `SANDBOX_ENABLED=False` qo'yib lokal runner ishlatilsin."
        )

    timeout = settings.MAX_TIMEOUT_SECONDS + CLIENT_TIMEOUT_MARGIN_SECONDS
    try:
        if settings.SANDBOX_DOCKER_HOST:
            return docker.DockerClient(
                base_url=settings.SANDBOX_DOCKER_HOST,
                timeout=timeout,
            )
        return docker.from_env(timeout=timeout)
    except DOCKER_ERRORS as exc:
        raise SandboxUnavailableError(
            "Docker demoniga ulanib bo'lmadi: "
            f"{exc}. `SANDBOX_DOCKER_HOST` sozlamasini va demon ishlayotganini "
            "tekshiring (`docker info`).",
            details={"docker_host": settings.SANDBOX_DOCKER_HOST or "env"},
        ) from exc


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class SandboxManager:
    """Kodni gVisor konteynerida bajaradigan runner.

    Bitta nusxa bir vaqtda BITTA konteynerni boshqaradi (`Executor` har job
    uchun o'z nusxasini yaratadi) — `kill()` ayni shu konteynerni topa oladi.
    Docker klienti esa DANGASA yaratiladi: `SandboxManager()` konstruktori
    tarmoqqa chiqmaydi, shuning uchun uni istalgan joyda yasash xavfsiz.
    """

    __slots__ = ("_cleanup_tasks", "_client", "_client_lock", "_container", "_killed")

    def __init__(self) -> None:
        self._client: Any | None = None
        self._container: Any | None = None
        #: `kill()` chaqirilganmi — `RunnerOutcome.timed_out` shundan kelib chiqadi.
        self._killed: bool = False
        self._client_lock = asyncio.Lock()
        #: Fon'da ketayotgan tozalash vazifalari (`_schedule_remove`).
        #: `close()` ularni kutadi, shunda worker to'xtaganda konteyner
        #: qolib ketmaydi. `set` havolani ushlab turadi — aks holda
        #: `asyncio` vazifani "garbage" deb yo'q qilib yuborishi mumkin.
        self._cleanup_tasks: set[asyncio.Task[None]] = set()

    # --- Klient -----------------------------------------------------------

    async def _ensure_client(self) -> Any:
        """Docker klientini (bir marta) yaratadi va qaytaradi."""
        if self._client is not None:
            return self._client
        async with self._client_lock:
            if self._client is None:
                self._client = await asyncio.to_thread(_create_client)
        return self._client

    async def available(self) -> bool:
        """Docker demoni javob beradimi (`ping`).

        Xato HECH QACHON tashlanmaydi: `Executor` shu metod bilan runner
        tanlashdan oldin tekshiradi, tekshiruvning o'zi yiqilmasligi kerak.
        """
        try:
            client = await self._ensure_client()
            pong = await asyncio.to_thread(client.ping)
        except SANDBOX_OR_DOCKER_ERRORS as exc:
            logger.warning(
                "Docker demoni javob bermadi",
                error=str(exc),
                docker_host=settings.SANDBOX_DOCKER_HOST or "env",
            )
            return False
        return bool(pong)

    async def _ensure_image(self, client: Any, runtime: BaseRuntime) -> None:
        """Sandbox image mavjudligini tekshiradi.

        Image'ni ATAYLAB `pull` QILMAYMIZ: `durabl/runner-*` lokal build,
        registry'da yo'q. `containers.run` esa image topilmasa avtomatik
        pull'ga urinib, tushunarsiz tarmoq xatosi beradi — shuning uchun
        oldindan tekshirib, nima qilish kerakligini aytamiz.

        Raises:
            SandboxStartupError: Image yo'q yoki Docker so'rovga javob bermadi.
        """
        try:
            await asyncio.to_thread(client.images.get, runtime.image)
        except (ImageNotFound, NotFound) as exc:
            raise SandboxStartupError(
                f"Sandbox image topilmadi: `{runtime.image}`. "
                "Uni `make sandbox-build` buyrug'i bilan yasang "
                f"(yoki qo'lda: `docker build -t {runtime.image} "
                f"sandbox/runners/{runtime.runtime.value}`).",
                details={"image": runtime.image, "runtime": runtime.runtime.value},
            ) from exc
        except DOCKER_ERRORS as exc:
            raise SandboxStartupError(
                f"Sandbox image'ini tekshirib bo'lmadi (`{runtime.image}`): {exc}",
                details={"image": runtime.image, "runtime": runtime.runtime.value},
            ) from exc

    # --- Bajarish ---------------------------------------------------------

    async def run(
        self,
        spec: SandboxSpec,
        runtime: BaseRuntime,
        on_log: LogSink | None = None,
    ) -> RunnerOutcome:
        """Kodni gVisor konteynerida bajaradi.

        Vaqt limitini o'zi nazorat QILMAYDI: `TimeoutGuard` tashqaridan
        `kill()` ni chaqiradi (shartnoma `SandboxRunner` da shunday).

        Returns:
            Xom natija. Infratuzilma xatosi `infra_error` maydonida qaytadi.

        Raises:
            SandboxUnavailableError: Docker demoni ishlamayapti.
            SandboxStartupError: Image yo'q yoki konteyner yaratilmadi.
        """
        self._killed = False
        self._container = None

        workdir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix=TEMP_DIR_PREFIX))
        try:
            try:
                return await self._execute(spec, runtime, workdir, on_log)
            except (SandboxUnavailableError, SandboxStartupError):
                # Bu ikkisi ataylab yuqoriga chiqadi: ular sozlama/infratuzilma
                # muammosi va operatorga tushunarli xabar bilan yetishi kerak.
                raise
            except DOCKER_ERRORS as exc:
                logger.error(
                    "sandbox bajarishda Docker xatosi",
                    job_id=spec.job_id,
                    runtime=runtime.runtime.value,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                return RunnerOutcome(infra_error=f"{type(exc).__name__}: {exc}")
        finally:
            await self._cleanup(workdir)

    async def _execute(
        self,
        spec: SandboxSpec,
        runtime: BaseRuntime,
        workdir: Path,
        on_log: LogSink | None,
    ) -> RunnerOutcome:
        """`run()` ning asosiy qismi (tozalash chaqiruvchida)."""
        await asyncio.to_thread(self._prepare_workdir, runtime, spec, workdir)

        client = await self._ensure_client()
        await self._ensure_image(client, runtime)

        queue: asyncio.Queue[tuple[LogStream, str] | None] = asyncio.Queue(
            maxsize=LOG_QUEUE_MAXSIZE
        )
        loop = asyncio.get_running_loop()
        tasks: dict[str, asyncio.Task[Any]] = {}

        async def attach_logs(created: Any) -> None:
            """Log oqimiga ulanadi va ULANGUNCHA kutadi.

            ═══════════════════════════════════════════════════════════════
            NEGA BU KONTEYNER ISHGA TUSHISHIDAN OLDIN BO'LADI
            ═══════════════════════════════════════════════════════════════

            Ilgari ulanish `start()` dan KEYIN bo'lardi va faqat vazifa
            yaratilardi — uning haqiqatan ulanganini hech kim kutmasdi.

            Ulanish `asyncio.to_thread` ichida bajariladi. Bir vaqtda bir
            nechta job ishlaganda thread havzasi band bo'ladi (har bir job
            `prepare_workdir`, `create`, `start`, `wait`, `read_result_file`
            uchun thread oladi), shuning uchun ulanish navbatda kutib
            qolishi mumkin. Shu orada 300 ms yashaydigan konteyner allaqachon
            tugab bo'ladi — va tugagan konteynerga `attach` BO'SH oqim
            qaytaradi.

            Oqibati o'lchangan: 72 ta job'dan 2 tasida (~2.8%) chiqish
            butunlay yo'qolgan. Natija joyida, `status=success`, `stdout`
            esa bo'sh — ya'ni nosozlik jim kechadi.

            Konteyner YARATILGAN, lekin ISHGA TUSHMAGAN holatda ulansak,
            u hali bitta ham bayt chiqarmagan bo'ladi. Shuning uchun bu
            ehtimollikni kamaytirish emas — poygani BUTUNLAY yo'q qilish.
            """
            attached = asyncio.Event()
            tasks["pump"] = asyncio.create_task(
                asyncio.to_thread(_pump_logs, created, queue, loop, attached)
            )
            tasks["drain"] = asyncio.create_task(_drain_logs(queue, on_log))
            try:
                await asyncio.wait_for(attached.wait(), timeout=LOG_ATTACH_TIMEOUT_SECONDS)
            except TimeoutError:
                # Ulanish ulgurmadi. Job'ni bloklamaymiz — natija loglardan
                # muhimroq — lekin bu holat ko'rinmas qolmasligi kerak.
                logger.warning(
                    "log oqimiga ulanish vaqti oshdi — chiqish yo'qolishi mumkin",
                    job_id=spec.job_id,
                    timeout=LOG_ATTACH_TIMEOUT_SECONDS,
                    attempt=spec.attempt_number,
                )

        container = await self._start_container(
            client, spec, runtime, workdir, before_start=attach_logs
        )
        self._container = container
        sandbox_id = str(container.id or "")[:SANDBOX_ID_LENGTH]

        logger.info(
            "sandbox konteyneri ishga tushdi",
            job_id=spec.job_id,
            sandbox_id=sandbox_id,
            runtime=runtime.runtime.value,
            image=runtime.image,
            attempt=spec.attempt_number,
        )

        pump = tasks["pump"]
        drain = tasks["drain"]

        try:
            exit_code, timed_out = await self._wait_for_exit(container, spec)
            oom_killed = await self._read_oom_flag(container)
        finally:
            await _finish_log_tasks(pump, drain)

        payload: RunnerPayload = await asyncio.to_thread(runtime.read_result_file, workdir)

        logger.info(
            "sandbox konteyneri tugadi",
            job_id=spec.job_id,
            sandbox_id=sandbox_id,
            exit_code=exit_code,
            oom_killed=oom_killed,
            timed_out=timed_out,
            result_ok=payload.ok,
        )

        return RunnerOutcome(
            exit_code=exit_code,
            runner_payload=payload,
            sandbox_id=sandbox_id,
            oom_killed=oom_killed,
            timed_out=timed_out,
            memory_peak_mb=None,
        )

    @staticmethod
    def _prepare_workdir(runtime: BaseRuntime, spec: SandboxSpec, workdir: Path) -> None:
        """Kod va payload fayllarini yozadi, huquqlarni konteynerga moslaydi.

        BLOKLAYDI (fayl I/O) — `asyncio.to_thread` ichida chaqiriladi.
        """
        runtime.prepare_files(spec, workdir)
        # Konteyner imtiyozsiz foydalanuvchi ostida ishlaydi va `result.json`
        # ni shu katalogga yozadi — `mkdtemp` ning 0700 huquqi yetmaydi.
        with contextlib.suppress(OSError):
            os.chmod(workdir, WORKDIR_MODE)

    async def _start_container(
        self,
        client: Any,
        spec: SandboxSpec,
        runtime: BaseRuntime,
        workdir: Path,
        before_start: Callable[[Any], Awaitable[None]] | None = None,
    ) -> Any:
        """Konteynerni yaratadi va ishga tushiradi.

        Args:
            before_start: Konteyner YARATILGANDAN keyin, lekin ISHGA
                TUSHIRILISHIDAN oldin chaqiriladi. Log oqimiga ulanish shu
                yerda bo'ladi — sabab quyida.

        Raises:
            SandboxStartupError: Konteyner yaratilmadi (masalan `runsc`
                runtime'i Docker'da ro'yxatdan o'tmagan).
        """
        kwargs = to_docker_kwargs(
            spec.limits,
            runtime=runtime,
            job_id=spec.job_id,
            attempt_number=spec.attempt_number,
        )
        # Kod, payload va natija shu bind-mount orqali almashinadi.
        kwargs["volumes"] = {str(workdir): {"bind": SANDBOX_WORKDIR, "mode": "rw"}}
        kwargs["environment"] = self._container_env(spec, runtime)

        started = time.monotonic()

        # DIQQAT: `containers.run()` ISHLATILMAYDI. Uning ichida `create()` dan
        # keyin `start()` chaqiriladi, lekin `start()` yiqilsa YARATILGAN
        # konteyner O'CHIRILMAYDI (docker-py 7.x xatti-harakati). Natijada har
        # bir muvaffaqiyatsiz urinish `Created` holatidagi o'lik konteyner
        # qoldiradi — noto'g'ri seccomp profili yoki ro'yxatdan o'tmagan
        # runtime bilan retry'lar diskni to'ldirib yuboradi. Shuning uchun
        # `create()` va `start()` ALOHIDA chaqiriladi va `start()` xatosida
        # konteyner darhol olib tashlanadi.
        startup_timeout = settings.SANDBOX_STARTUP_TIMEOUT_SECONDS
        try:
            container = await asyncio.wait_for(
                asyncio.to_thread(
                    client.containers.create,
                    runtime.image,
                    runtime.container_command(spec),
                    **kwargs,
                ),
                timeout=startup_timeout,
            )
        except (ImageNotFound, NotFound) as exc:
            raise SandboxStartupError(
                f"Sandbox image topilmadi: `{runtime.image}`. "
                "Uni `make sandbox-build` bilan yasang.",
                details={"image": runtime.image},
            ) from exc
        except TimeoutError as exc:
            raise self._startup_timeout_error("create", startup_timeout, spec, runtime) from exc
        except APIError as exc:
            raise self._startup_error(exc, spec, runtime) from exc

        # Log oqimiga ulanish KONTEYNER ISHGA TUSHMASDAN oldin bo'lishi shart —
        # batafsil sababi `_execute` dagi izohda.
        if before_start is not None:
            try:
                await before_start(container)
            except Exception:
                # Ulanish yiqilsa job baribir bajarilishi kerak: natija
                # loglardan muhimroq. Konteynerni tozalashni unutmaymiz.
                await self._force_remove(container)
                raise

        try:
            await asyncio.wait_for(asyncio.to_thread(container.start), timeout=startup_timeout)
        except TimeoutError as exc:
            # Konteyner yaratilgan, lekin `start()` javob bermadi — oqishni
            # oldini olish uchun o'chirishga HARAKAT qilamiz (u ham osilishi
            # mumkin, shuning uchun fon vazifasi sifatida).
            self._schedule_remove(container)
            raise self._startup_timeout_error("start", startup_timeout, spec, runtime) from exc
        except APIError as exc:
            # Konteyner yaratilgan, lekin ishga tushmadi — oqishni oldini olamiz
            await self._force_remove(container)
            raise self._startup_error(exc, spec, runtime) from exc

        observe_sandbox_create(time.monotonic() - started)
        return container

    @staticmethod
    def _startup_timeout_error(
        stage: str,
        timeout: float,
        spec: SandboxSpec,
        runtime: BaseRuntime,
    ) -> SandboxStartupError:
        """Docker API javob bermaganda tushunarli xato.

        Bu job'ning o'z `timeout_seconds` idan ALOHIDA chegara: Docker demoni
        osilib qolsa worker job vaqtini kutib o'tirmasligi kerak, aks holda
        bitta nosoz demon butun worker hovuzini bir necha daqiqaga qulflaydi.
        """
        return SandboxStartupError(
            f"Docker API `{stage}` bosqichida {timeout} soniyada javob bermadi. "
            "Demon ortiqcha yuklangan yoki nosoz bo'lishi mumkin "
            "(`docker info`, `docker system df`). "
            "Chegara: `SANDBOX_STARTUP_TIMEOUT_SECONDS`.",
            details={
                "stage": stage,
                "timeout_seconds": timeout,
                "image": runtime.image,
                "job_id": spec.job_id,
            },
        )

    def _schedule_remove(self, container: Any) -> None:
        """Konteynerni FON'da o'chiradi (o'chirish ham osilishi mumkin).

        `asyncio.to_thread` ichidagi thread'ni bekor qilish mumkin emas,
        shuning uchun bu yerda vazifa yaratib kutmasdan davom etamiz:
        worker darhol bo'shaydi, tozalash esa Docker javob berganda bajariladi.
        Vazifa yo'qolib ketmasligi uchun havolasi saqlanadi.
        """
        task = asyncio.create_task(self._force_remove(container))
        self._cleanup_tasks.add(task)
        task.add_done_callback(self._cleanup_tasks.discard)

    @staticmethod
    def _startup_error(
        exc: APIError,
        spec: SandboxSpec,
        runtime: BaseRuntime,
    ) -> SandboxStartupError:
        """Docker API xatosini tushunarli `SandboxStartupError`ga aylantiradi."""
        return SandboxStartupError(
            f"Sandbox konteyneri ishga tushmadi: {exc}. "
            f"Docker'da `{settings.SANDBOX_RUNTIME}` runtime'i ro'yxatdan "
            "o'tganini tekshiring (`docker info | grep Runtimes`) — gVisor "
            "`sandbox/gvisor/install.sh` bilan o'rnatiladi.",
            details={
                "image": runtime.image,
                "sandbox_runtime": settings.SANDBOX_RUNTIME,
                "limits": limits_summary(spec.limits),
            },
        )

    async def _force_remove(self, container: Any) -> None:
        """Konteynerni majburan o'chiradi; xatoni faqat log qiladi.

        Tozalash HECH QACHON asosiy xatoni yashirmasligi kerak, shuning uchun
        bu metod istisno tashlamaydi.
        """
        try:
            await asyncio.to_thread(container.remove, force=True)
        except Exception as exc:  # pragma: no cover - Docker nosozligi
            logger.warning(
                "sandbox.container_remove_failed",
                container_id=getattr(container, "id", None),
                error=str(exc),
            )

    @staticmethod
    def _container_env(spec: SandboxSpec, runtime: BaseRuntime) -> dict[str, str]:
        """Konteynerga uzatiladigan muhit o'zgaruvchilari.

        Host muhitidan HECH NARSA meros qilib olinmaydi (bu lokal runner'dan
        asosiy farq): konteyner o'z image'idagi `ENV` va shu lug'atni ko'radi.
        Shu tufayli `DATABASE_URL`, `AWS_*` kabi sirlar sandbox'ga TUSHMAYDI.

        Tartib: tilga xos qiymatlar -> mijoz `env_vars` -> sandbox shartnomasi
        (oxirgisi mijoz tomonidan bosib o'tilmasligi kerak).
        """
        environment: dict[str, str] = {}

        runtime_env = getattr(runtime, "runtime_env", None)
        if callable(runtime_env):
            environment.update(runtime_env(spec))

        environment.update(spec.safe_env())
        environment.update(to_sandbox_env(spec.limits, runtime=runtime, workdir=SANDBOX_WORKDIR))
        return environment

    async def _wait_for_exit(
        self,
        container: Any,
        spec: SandboxSpec,
    ) -> tuple[int | None, bool]:
        """Konteyner tugashini kutadi.

        Returns:
            `(exit_code, timed_out)`. `exit_code` `None` bo'lsa — kodni
            aniqlash imkoni bo'lmadi (konteyner o'chirilgan).
        """
        # Zaxira chegara: `TimeoutGuard` ishlamay qolsa ham `wait` abadiy
        # osilib qolmasligi kerak.
        wait_timeout = (
            float(spec.timeout_seconds)
            + settings.SANDBOX_STARTUP_TIMEOUT_SECONDS
            + KILL_GRACE_SECONDS
        )
        try:
            status = await asyncio.to_thread(container.wait, timeout=wait_timeout)
        except NotFound:
            # `kill()` konteynerni allaqachon o'chirgan.
            code = DOCKER_SIGKILL_EXIT_CODE if self._killed else None
            return code, self._killed
        except DOCKER_ERRORS as exc:
            logger.warning(
                "konteyner tugashini kutish uzildi",
                job_id=spec.job_id,
                wait_timeout=wait_timeout,
                error=str(exc),
            )
            # Kutish uzildi — konteynerni o'zimiz o'ldiramiz va buni
            # vaqt limiti deb belgilaymiz.
            await self.kill()
            return DOCKER_SIGKILL_EXIT_CODE, True

        exit_code = int(status.get("StatusCode", -1)) if isinstance(status, dict) else -1
        return exit_code, self._killed

    @staticmethod
    async def _read_oom_flag(container: Any) -> bool:
        """`State.OOMKilled` — konteyner xotira limiti tufayli o'ldirilganmi."""
        try:
            await asyncio.to_thread(container.reload)
        except (NotFound, *DOCKER_ERRORS):
            # Konteyner o'chirilgan — OOM holatini bilish imkoni yo'q.
            return False
        state = container.attrs.get("State") or {}
        return bool(state.get("OOMKilled"))

    # --- To'xtatish -------------------------------------------------------

    async def kill(self) -> None:
        """Joriy konteynerni majburan to'xtatadi: `kill` -> grace -> `remove`.

        Konteyner allaqachon yo'q bo'lsa jim o'tadi (`kill()` bir necha marta
        chaqirilishi mumkin: `TimeoutGuard` va keyin bekor qilish).
        """
        self._killed = True
        container = self._container
        if container is None:
            return

        try:
            await asyncio.to_thread(container.kill)
        except (NotFound, APIError) as exc:
            # 409 — konteyner allaqachon to'xtagan; 404 — o'chirilgan.
            logger.debug("konteynerni o'ldirish shart emas", error=str(exc))
        except DOCKER_ERRORS as exc:
            logger.warning("konteynerni o'ldirish muvaffaqiyatsiz", error=str(exc))

        # Loglar va `result.json` o'qib olinishi uchun qisqa pauza.
        await asyncio.sleep(KILL_GRACE_SECONDS)

        try:
            await asyncio.to_thread(container.remove, force=True)
        except (NotFound, *DOCKER_ERRORS) as exc:
            logger.debug("konteyner allaqachon o'chirilgan", error=str(exc))

    async def _cleanup(self, workdir: Path) -> None:
        """Konteynerni o'chiradi va vaqtinchalik katalogni tozalaydi.

        Katalog natija fayli O'QILGANDAN KEYIN o'chiriladi (`_execute`
        `read_result_file` ni qaytishdan oldin chaqiradi).

        Bekor qilish (`CancelledError`) paytida konteyner o'chirilmay qolishi
        mumkin — ayni shuning uchun `cleanup_orphans()` mavjud: u
        `durabl.managed` yorlig'i bo'yicha qolib ketganlarni yopadi.
        """
        container = self._container
        self._container = None
        try:
            if container is not None:
                try:
                    await asyncio.to_thread(container.remove, force=True)
                except (NotFound, *DOCKER_ERRORS) as exc:
                    logger.debug("konteynerni o'chirish shart emas", error=str(exc))
        finally:
            # SINXRON: bekor qilish paytida ham bajarilishi kerak.
            shutil.rmtree(workdir, ignore_errors=True)

    async def cleanup_orphans(self) -> int:
        """Qolib ketgan (to'xtagan) Durabl konteynerlarini o'chiradi.

        Faqat `durabl.managed=true` yorlig'i bo'lganlar ko'riladi — hostdagi
        boshqa konteynerlarga TEGILMAYDI. Tirik konteynerlar ham chetlab
        o'tiladi (boshqa worker ularni bajarayotgan bo'lishi mumkin).

        Returns:
            O'chirilgan konteynerlar soni.
        """
        try:
            client = await self._ensure_client()
            containers = await asyncio.to_thread(
                client.containers.list,
                all=True,
                filters={"label": f"{LABEL_MANAGED}={LABEL_MANAGED_VALUE}"},
            )
        except SANDBOX_OR_DOCKER_ERRORS as exc:
            logger.warning("orphan konteynerlarni ro'yxatlash muvaffaqiyatsiz", error=str(exc))
            return 0

        current_id = getattr(self._container, "id", None)
        removed = 0
        for container in containers:
            if getattr(container, "status", "") in LIVE_CONTAINER_STATUSES:
                continue
            if current_id is not None and container.id == current_id:
                continue
            try:
                await asyncio.to_thread(container.remove, force=True)
            except (NotFound, *DOCKER_ERRORS) as exc:
                logger.debug(
                    "orphan konteyner o'chirilmadi",
                    container_id=str(container.id or "")[:SANDBOX_ID_LENGTH],
                    error=str(exc),
                )
                continue
            removed += 1

        if removed:
            logger.info("orphan konteynerlar o'chirildi", count=removed)
        return removed

    async def close(self) -> None:
        """Docker klientini yopadi (worker to'xtaganda chaqiriladi).

        Avval fon'dagi tozalash vazifalari kutiladi (chegaralangan vaqt bilan),
        shunda worker to'xtaganda `Created` holatidagi konteyner qolib ketmaydi.
        """
        if self._cleanup_tasks:
            pending = list(self._cleanup_tasks)
            done, still_pending = await asyncio.wait(
                pending, timeout=settings.SANDBOX_STARTUP_TIMEOUT_SECONDS
            )
            del done
            for task in still_pending:
                task.cancel()
            if still_pending:
                logger.warning(
                    "sandbox.cleanup_incomplete",
                    pending=len(still_pending),
                    hint="`docker ps -a --filter label=durabl.managed=true` bilan tekshiring",
                )

        client = self._client
        self._client = None
        if client is None:
            return
        with contextlib.suppress(*DOCKER_ERRORS):
            await asyncio.to_thread(client.close)


# ---------------------------------------------------------------------------
# Log oqimi (thread <-> event loop)
# ---------------------------------------------------------------------------


def _offer(
    loop: asyncio.AbstractEventLoop,
    queue: asyncio.Queue[tuple[LogStream, str] | None],
    item: tuple[LogStream, str] | None,
) -> None:
    """Chunk'ni thread'dan event loop navbatiga qo'yadi (backpressure bilan).

    `future.result(timeout=...)` ataylab BLOKLAYDI: navbat to'lgan bo'lsa
    thread kutib turadi va mijoz kodining chiqishi xotirani to'ldirib
    yubormaydi. Kutish oshsa chunk tashlab yuboriladi — log yo'qolishi
    bajarishni to'xtatishdan afzal.
    """
    try:
        future = asyncio.run_coroutine_threadsafe(queue.put(item), loop)
        future.result(timeout=LOG_QUEUE_PUT_TIMEOUT_SECONDS)
    except (TimeoutError, RuntimeError, asyncio.CancelledError):
        # Loop yopilgan, bekor qilingan yoki navbat bo'shamadi.
        return


def _open_log_stream(container: Any) -> tuple[Any, bool]:
    """Konteynerning chiqish oqimini ochadi.

    Returns:
        `(stream, demuxed)`. `demuxed=True` bo'lsa oqim
        `(stdout_chunk, stderr_chunk)` juftliklarini beradi.

    Nega `attach`, `logs` emas: docker-py (7.x) `Container.logs()` da `demux`
    parametri YO'Q — u faqat `attach()` da bor. `logs(stream=True)` esa
    stdout va stderr'ni AJRATMASDAN, bitta bayt oqimi sifatida beradi.
    Durabl'da esa oqimlar ajratilishi SHART: `LogStream.STDERR` yozuvlari
    xatoni tasniflashda (`classify_failure`) va UI'da alohida ko'rsatiladi.

    `attach(logs=True)` — allaqachon yozilgan chiqishni ham qaytaradi
    (konteyner biz ulanishdan oldin yozib qo'ygan bo'lishi mumkin), shuning
    uchun hech narsa yo'qolmaydi. `demux` faqat `tty=False` bilan ishlaydi —
    `to_docker_kwargs` ayni shuni ta'minlaydi.

    Zaxira yo'l: `attach` ishlamasa `logs(stream=True)` ga tushamiz va hamma
    narsani stdout deb hisoblaymiz — loglarni BUTUNLAY yo'qotishdan afzal.
    """
    try:
        stream = container.attach(
            stream=True,
            logs=True,
            stdout=True,
            stderr=True,
            demux=True,
        )
    except ATTACH_ERRORS as exc:
        logger.warning(
            "konteynerga `attach` qilib bo'lmadi — `logs` zaxirasi ishlatiladi "
            "(stdout/stderr ajratilmaydi)",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return container.logs(stream=True, follow=True, stdout=True, stderr=True), False
    return stream, True


def _pump_logs(
    container: Any,
    queue: asyncio.Queue[tuple[LogStream, str] | None],
    loop: asyncio.AbstractEventLoop,
    attached: asyncio.Event | None = None,
) -> None:
    """Konteyner chiqishini blokiruvchi generatordan o'qib navbatga uzatadi.

    ALOHIDA THREAD'da ishlaydi (`asyncio.to_thread`), chunki generator
    blokiruvchi socket ustida aylanadi.

    Oqim tugaganda (konteyner tugadi yoki o'chirildi) navbatga `None`
    sentinel qo'yiladi — iste'molchi shundan tugashini biladi. Sentinel
    `finally` ichida qo'yiladi: har qanday xatoda ham iste'molchi
    abadiy kutib qolmasligi kerak.
    """
    decoders = {
        LogStream.STDOUT: codecs.getincrementaldecoder("utf-8")("replace"),
        LogStream.STDERR: codecs.getincrementaldecoder("utf-8")("replace"),
    }
    stream: Any = None
    try:
        try:
            stream, demuxed = _open_log_stream(container)
        finally:
            # Ulanish muvaffaqiyatli bo'ldimi yoki yo'qmi — chaqiruvchi
            # KUTIB QOLMASLIGI kerak. Aks holda `attach` yiqilganda
            # konteyner hech qachon ishga tushmasdi.
            if attached is not None:
                loop.call_soon_threadsafe(attached.set)
        for frame in stream:
            if demuxed and isinstance(frame, tuple):
                pairs = tuple(zip((LogStream.STDOUT, LogStream.STDERR), frame, strict=False))
            else:
                # Zaxira yo'l yoki kutilmagan shakl — hammasi stdout.
                pairs = ((LogStream.STDOUT, frame),)

            for kind, raw in pairs:
                if not raw:
                    continue
                text = decoders[kind].decode(bytes(raw))
                if text:
                    _offer(loop, queue, (kind, text))

        for kind, decoder in decoders.items():
            tail = decoder.decode(b"", final=True)
            if tail:
                _offer(loop, queue, (kind, tail))
    except (NotFound, *DOCKER_ERRORS) as exc:
        # Konteyner o'chirilgan yoki ulanish uzilgan — kutilgan holat.
        logger.debug("konteyner log oqimi uzildi", error=str(exc))
    except Exception as exc:
        # Bu yerga tushish SHARTNOMA buzilganini bildiradi (masalan SDK
        # imzosi o'zgargan). ATAYLAB `warning` bilan ko'rinadi: ilgari jim
        # yutilgan `TypeError` tufayli loglar butunlay yo'qolgan edi.
        logger.warning(
            "konteyner log oqimini o'qishda kutilmagan xato",
            error=str(exc),
            error_type=type(exc).__name__,
        )
    finally:
        if stream is not None:
            # `CancellableStream` socket'ni ushlab turadi — yopish SHART.
            with contextlib.suppress(Exception):
                stream.close()
        _offer(loop, queue, None)


async def _drain_logs(
    queue: asyncio.Queue[tuple[LogStream, str] | None],
    on_log: LogSink | None,
) -> None:
    """Navbatdan chunk'larni olib `on_log` ga uzatadi.

    `on_log` berilmagan bo'lsa ham navbat BO'SHATILADI — aks holda uzatuvchi
    thread backpressure'da abadiy kutib qolardi.
    """
    while True:
        item = await queue.get()
        if item is None:
            return
        if on_log is None:
            continue
        stream, text = item
        try:
            on_log(stream, text)
        except Exception as exc:
            logger.warning("log sink xato berdi", error=str(exc))


async def _finish_log_tasks(pump: asyncio.Task[Any], drain: asyncio.Task[Any]) -> None:
    """Log vazifalarini yakunlaydi (cheklangan kutish bilan).

    `pump` `asyncio.to_thread` ustida ishlaydi — uni bekor qilish thread'ni
    to'xtatmaydi, lekin konteyner tugagandan keyin log oqimi o'zi yopiladi,
    shuning uchun thread ham tabiiy tugaydi.
    """
    gathered = asyncio.gather(pump, drain, return_exceptions=True)
    try:
        results = await asyncio.wait_for(
            asyncio.shield(gathered), timeout=LOG_DRAIN_TIMEOUT_SECONDS
        )
    except TimeoutError:
        logger.warning("loglarni yig'ish vaqti oshdi", timeout=LOG_DRAIN_TIMEOUT_SECONDS)
        pump.cancel()
        drain.cancel()
        with contextlib.suppress(asyncio.CancelledError, TimeoutError):
            await asyncio.wait_for(gathered, timeout=LOG_DRAIN_TIMEOUT_SECONDS)
        return
    except asyncio.CancelledError:
        pump.cancel()
        drain.cancel()
        raise

    # `return_exceptions=True` xatoni YUTIB yuboradi — shuning uchun uni
    # ochiq log qilamiz. Aks holda log quvuridagi nosozlik "loglar yo'q"
    # ko'rinishida, sababsiz qolib ketardi.
    for name, result in zip(("pump", "drain"), results, strict=False):
        if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
            logger.warning(
                "log vazifasi xato bilan tugadi",
                task=name,
                error=str(result),
                error_type=type(result).__name__,
            )


__all__ = [
    "CLIENT_TIMEOUT_MARGIN_SECONDS",
    "DOCKER_SIGKILL_EXIT_CODE",
    "KILL_GRACE_SECONDS",
    "LIVE_CONTAINER_STATUSES",
    "LOG_DRAIN_TIMEOUT_SECONDS",
    "LOG_QUEUE_MAXSIZE",
    "LOG_QUEUE_PUT_TIMEOUT_SECONDS",
    "SANDBOX_ID_LENGTH",
    "TEMP_DIR_PREFIX",
    "WORKDIR_MODE",
    "SandboxManager",
]
