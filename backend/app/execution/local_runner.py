"""Durabl — lokal subprocess runner (FAQAT development/test).

`SandboxRunner` protokolining Docker'siz amalga oshirilishi: mijoz kodi ayni
shu mashinada, oddiy bola jarayon sifatida bajariladi. Interfeys
`SandboxManager` bilan BIR XIL, shu tufayli `Executor` farqni sezmaydi.

**OGOHLANTIRISH — bu runner izolyatsiya BERMAYDI.** Kod host fayl tizimini
o'qiy oladi, tarmoqqa chiqa oladi va faqat `rlimit` bilan cheklangan. Yagona
himoya qatlamlari:

* `preexec_fn` -> `resource.setrlimit` (CPU, fd, fayl hajmi, Linux'da xotira)
* alohida protsess guruhi (`start_new_session=True`) — `kill()` butun
  daraxtni o'ldiradi, bola jarayonlar "zombi" bo'lib qolmaydi
* vaqtinchalik ish katalogi — kod va natija faqat shu yerda
* `settings.is_production` bo'lsa runner O'CHIRILADI (`available() -> False`,
  `run()` -> `SandboxUnavailableError`) — tasodifan production'da ishlab
  ketmasligi uchun

Nega umuman kerak: Docker va gVisor'ni har bir ishlab chiquvchi mashinasida
(ayniqsa macOS'da) talab qilish rivojlanishni sekinlashtiradi. Lokal runner
sandbox entrypoint'ining AYNI o'zini ishga tushiradi (`runtime.local_command`),
shuning uchun shartnoma bir xil: lokal sinovdan o'tgan kod konteynerda ham
ayni natijani beradi.
"""

from __future__ import annotations

import asyncio
import codecs
import contextlib
import os
import shutil
import signal
import tempfile
from pathlib import Path
from typing import Any, Final

from app.config import settings
from app.constants import LogStream
from app.exceptions import SandboxUnavailableError, UnsupportedRuntimeError
from app.execution.resource_limiter import apply_rlimits, limits_summary, to_sandbox_env
from app.execution.runtime_base import (
    BaseRuntime,
    LogSink,
    available_runtimes,
    get_runtime,
)
from app.execution.types import RunnerOutcome, RunnerPayload, SandboxSpec
from app.logging_config import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Konstantalar
# ---------------------------------------------------------------------------

#: Vaqtinchalik ish katalogi nomining boshlanishi (qo'lda tozalashda qulay).
TEMP_DIR_PREFIX: Final[str] = "durabl-local-"

#: `sandbox_id` sifatida yoziladigan prefiks — konteyner id'sidan ajratish uchun.
SANDBOX_ID_PREFIX: Final[str] = "local-"

#: Bola jarayonga UZATILADIGAN host muhit o'zgaruvchilari.
#:
#: `os.environ` loyihada sozlama uchun ishlatilmaydi (sozlama FAQAT
#: `settings` dan keladi). Bu yerdagi murojaat sozlama emas: `PATH` bo'lmasa
#: `node` interpretatori topilmaydi, `LANG` bo'lmasa chiqish kodlashi buziladi.
#: Ro'yxat ataylab qisqa — qolgan hamma narsa bola jarayonga TUSHMAYDI
#: (host sirlari, `AWS_*`, `DATABASE_URL` va h.k. sandbox'ga o'tmaydi).
INHERITED_ENV_VARS: Final[tuple[str, ...]] = ("PATH", "LANG", "LC_ALL", "LC_CTYPE")

#: Chiqish oqimlaridan bir marta o'qiladigan hajm.
READ_CHUNK_BYTES: Final[int] = max(4096, settings.MAX_LOG_CHUNK_BYTES)

#: `StreamReader` ichki buferi — chunk'dan katta bo'lishi shart.
STREAM_LIMIT_BYTES: Final[int] = max(65_536, READ_CHUNK_BYTES * 4)

#: `kill()` da SIGTERM va SIGKILL orasidagi kutish (soniya).
KILL_GRACE_SECONDS: Final[float] = max(0.1, settings.SANDBOX_KILL_GRACE_SECONDS)


def _killpg(pgid: int, sig: signal.Signals) -> bool:
    """Protsess guruhiga signal yuboradi; muvaffaqiyatli bo'lsa `True`.

    Xato TASHLAMAYDI: guruhning yo'qligi (jarayon o'z-o'zidan tugagan) odatiy
    holat, to'xtatish oqimini buzmasligi kerak.
    """
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError, OSError):
        return False
    return True


def _inherited_env() -> dict[str, str]:
    """Hostdan bola jarayonga o'tadigan o'zgaruvchilar (qat'iy allowlist)."""
    inherited: dict[str, str] = {}
    for name in INHERITED_ENV_VARS:
        value = os.environ.get(name)
        if value:
            inherited[name] = value
    # `PATH` hech qanday holatda bo'sh qolmasligi kerak.
    inherited.setdefault("PATH", os.defpath)
    return inherited


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class LocalRunner:
    """Kodni lokal subprocess sifatida bajaradigan runner.

    Bitta nusxa bir vaqtda BITTA bajarishni olib boradi (`Executor` har job
    uchun o'z nusxasini yaratadi) — shu tufayli joriy jarayon oddiy maydonda
    saqlanadi va `kill()` uni topa oladi.
    """

    __slots__ = ("_killed", "_pgid", "_process")

    def __init__(self) -> None:
        self._process: asyncio.subprocess.Process | None = None
        #: Protsess guruhi identifikatori — `os.killpg` uchun.
        self._pgid: int | None = None
        #: `kill()` chaqirilganmi — `RunnerOutcome.timed_out` shundan kelib chiqadi.
        self._killed: bool = False

    # --- Tayyorlik ---------------------------------------------------------

    async def available(self) -> bool:
        """Lokal runner ishlashga tayyormi.

        Production'da HAR DOIM `False`: izolyatsiyasiz bajarish faqat
        development va test uchun. Qolgan holatda ro'yxatdan o'tgan barcha
        runtime'larning lokal entrypoint fayllari mavjudligi tekshiriladi.
        """
        if settings.is_production:
            logger.warning(
                "lokal runner production'da o'chirilgan",
                env=settings.ENV,
                hint="SANDBOX_ENABLED=True qo'ying",
            )
            return False
        return self._entrypoints_ready()

    @staticmethod
    def _entrypoints_ready() -> bool:
        """Barcha runtime'larning lokal entrypoint fayllari joyidami."""
        runtimes = available_runtimes()
        if not runtimes:
            return False
        for runtime_enum in runtimes:
            try:
                instance = get_runtime(runtime_enum)
            except UnsupportedRuntimeError:  # pragma: no cover - reestr buzilgan holat
                return False
            entrypoint = getattr(instance, "local_entrypoint", None)
            if entrypoint is not None and not Path(entrypoint).is_file():
                logger.error(
                    "lokal entrypoint topilmadi",
                    runtime=runtime_enum.value,
                    entrypoint=str(entrypoint),
                )
                return False
        return True

    # --- Bajarish ---------------------------------------------------------

    async def run(
        self,
        spec: SandboxSpec,
        runtime: BaseRuntime,
        on_log: LogSink | None = None,
    ) -> RunnerOutcome:
        """Kodni lokal subprocess sifatida bajaradi.

        Oqim: vaqtinchalik katalog -> `prepare_files` -> `create_subprocess_exec`
        -> stdout/stderr'ni PARALLEL o'qish -> `wait()` -> `result.json`.

        Vaqt limitini o'zi nazorat QILMAYDI: `TimeoutGuard` tashqaridan
        `kill()` ni chaqiradi (shartnoma `SandboxRunner` da shunday).

        Raises:
            SandboxUnavailableError: Production muhiti yoki entrypoint yo'q.
        """
        if settings.is_production:
            raise SandboxUnavailableError(
                "Lokal runner production'da ishlatilmaydi: mijoz kodi izolyatsiyasiz "
                "bajarilgan bo'lardi. `SANDBOX_ENABLED=True` qo'ying va sandbox "
                "image'larini `make sandbox-build` bilan yasang.",
                details={"env": settings.ENV},
            )

        self._killed = False
        self._process = None
        self._pgid = None

        logger.warning(
            "lokal runner: kod IZOLYATSIYASIZ bajariladi",
            job_id=spec.job_id,
            runtime=runtime.runtime.value,
            attempt=spec.attempt_number,
            limits=limits_summary(spec.limits),
            hint="production'da SANDBOX_ENABLED=True bo'lishi SHART",
        )

        workdir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix=TEMP_DIR_PREFIX))
        try:
            return await self._execute(spec, runtime, workdir, on_log)
        finally:
            # Tozalash ATAYLAB `await` ishlatmaydi: `TimeoutGuard` `run()` ni
            # bekor qilgan paytda (`CancelledError`) har qanday `await` darhol
            # uziladi va katalog/jarayon qolib ketardi.
            self._cleanup(workdir)

    async def _execute(
        self,
        spec: SandboxSpec,
        runtime: BaseRuntime,
        workdir: Path,
        on_log: LogSink | None,
    ) -> RunnerOutcome:
        """`run()` ning asosiy qismi (tozalash chaqiruvchida)."""
        await asyncio.to_thread(runtime.prepare_files, spec, workdir)

        command = runtime.local_command(spec, workdir)
        environment = self._build_env(spec, runtime, workdir)

        process = await self._spawn(command, workdir, environment, spec)
        if process is None:
            return RunnerOutcome(
                infra_error=f"lokal jarayon ishga tushmadi: {' '.join(command)}",
            )

        logger.info(
            "lokal jarayon ishga tushdi",
            job_id=spec.job_id,
            pid=process.pid,
            runtime=runtime.runtime.value,
        )

        # stdout va stderr PARALLEL o'qiladi: aks holda bitta quvur to'lib
        # qolsa jarayon yozishda muzlab qoladi (klassik deadlock).
        await asyncio.gather(
            self._pump(process.stdout, LogStream.STDOUT, on_log),
            self._pump(process.stderr, LogStream.STDERR, on_log),
        )
        exit_code = await process.wait()

        payload: RunnerPayload = await asyncio.to_thread(runtime.read_result_file, workdir)

        logger.info(
            "lokal jarayon tugadi",
            job_id=spec.job_id,
            pid=process.pid,
            exit_code=exit_code,
            killed=self._killed,
            result_ok=payload.ok,
        )

        return RunnerOutcome(
            exit_code=exit_code,
            runner_payload=payload,
            sandbox_id=f"{SANDBOX_ID_PREFIX}{process.pid}",
            # Lokal rejimda OOM'ni ishonchli aniqlash imkoni yo'q (cgroup yo'q);
            # `runtime.classify_failure()` buni stderr belgilaridan topadi.
            oom_killed=False,
            timed_out=self._killed,
            memory_peak_mb=None,
        )

    async def _spawn(
        self,
        command: list[str],
        workdir: Path,
        environment: dict[str, str],
        spec: SandboxSpec,
    ) -> asyncio.subprocess.Process | None:
        """Bola jarayonni yaratadi; muvaffaqiyatsiz bo'lsa `None` qaytaradi."""
        kwargs: dict[str, Any] = {}
        if os.name == "posix":
            # Yangi sessiya = yangi protsess guruhi. `kill()` `os.killpg` bilan
            # butun daraxtni o'ldiradi — mijoz kodi `subprocess` ishlatgan
            # bo'lsa ham zombi qolmaydi.
            kwargs["start_new_session"] = True
            # `fork()` dan keyin, `exec()` dan oldin rlimit qo'yiladi.
            kwargs["preexec_fn"] = apply_rlimits(spec.limits)

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(workdir),
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=STREAM_LIMIT_BYTES,
                **kwargs,
            )
        except (OSError, ValueError) as exc:
            logger.error(
                "lokal jarayonni yaratish muvaffaqiyatsiz",
                job_id=spec.job_id,
                command=command,
                error=str(exc),
            )
            return None

        self._process = process
        self._pgid = self._resolve_pgid(process.pid)
        if self._killed:
            # `kill()` jarayon yaratilishidan OLDIN chaqirilgan — darhol o'ldiramiz.
            await self._terminate(process)
        return process

    @staticmethod
    def _resolve_pgid(pid: int) -> int | None:
        """Jarayonning protsess guruhini aniqlaydi (POSIX bo'lmasa `None`)."""
        if os.name != "posix":  # pragma: no cover - Windows
            return None
        try:
            return os.getpgid(pid)
        except (OSError, ProcessLookupError):  # pragma: no cover - jarayon tez o'lgan
            # `start_new_session=True` bilan guruh id'si pid'ga teng bo'ladi.
            return pid

    # --- Chiqish oqimlari -------------------------------------------------

    @staticmethod
    async def _pump(
        reader: asyncio.StreamReader | None,
        stream: LogStream,
        on_log: LogSink | None,
    ) -> None:
        """Oqimni chunk'lab o'qib `on_log` ga uzatadi.

        Xotira O'SMAYDI: matn hech qayerda yig'ilmaydi, har chunk darhol
        chaqiruvchiga (`ResultCollector`) beriladi. `on_log` berilmagan
        bo'lsa ham oqim baribir o'qiladi — aks holda quvur to'lib jarayon
        muzlab qolardi.

        Satrlar `read()` bilan emas, `readline()` bilan o'qilmaydi: juda uzun
        satr (bufer limitidan katta) `LimitOverrunError` berardi, chunk esa
        har qanday chiqish bilan ishlaydi.
        """
        if reader is None:  # pragma: no cover - PIPE har doim beriladi
            return
        # UTF-8 belgisi ikki chunk orasida bo'linib qolishi mumkin — shuning
        # uchun oqim bo'yicha holatini saqlaydigan dekoder ishlatiladi.
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        while True:
            try:
                chunk = await reader.read(READ_CHUNK_BYTES)
            except (asyncio.IncompleteReadError, ConnectionResetError):  # pragma: no cover
                break
            if not chunk:
                break
            text = decoder.decode(chunk)
            if text and on_log is not None:
                on_log(stream, text)
        tail = decoder.decode(b"", final=True)
        if tail and on_log is not None:
            on_log(stream, tail)

    # --- Muhit o'zgaruvchilari --------------------------------------------

    def _build_env(
        self,
        spec: SandboxSpec,
        runtime: BaseRuntime,
        workdir: Path,
    ) -> dict[str, str]:
        """Bola jarayon uchun muhit o'zgaruvchilarini yig'adi.

        Tartib MUHIM (keyingisi oldingisini bosadi):

        1. hostdan meros (`PATH`, `LANG`) — interpretator ishlashi uchun;
        2. tilga xos qiymatlar (`runtime.runtime_env`) — Dockerfile bilan bir xil;
        3. `HOME`/`TMPDIR` — vaqtinchalik katalogga yo'naltiriladi, kod host
           uy katalogiga yozmasligi uchun;
        4. `spec.safe_env()` — `DURABL_JOB_ID` va mijozning `env_vars` i;
        5. sandbox shartnomasi (`to_sandbox_env`) — OXIRIDA, chunki mijoz
           `DURABL_SANDBOX_RESULT_FILENAME` ni almashtirib natija yozilishini
           buza olmasligi kerak.
        """
        environment = _inherited_env()

        runtime_env = getattr(runtime, "runtime_env", None)
        if callable(runtime_env):
            environment.update(runtime_env(spec))

        environment["HOME"] = str(workdir)
        environment["TMPDIR"] = str(workdir)

        environment.update(spec.safe_env())
        environment.update(to_sandbox_env(spec.limits, runtime=runtime, workdir=workdir))
        return environment

    # --- To'xtatish -------------------------------------------------------

    async def kill(self) -> None:
        """Joriy bajarishni majburan to'xtatadi (timeout yoki bekor qilish).

        Butun protsess GURUHIga signal yuboriladi: SIGTERM -> grace -> SIGKILL.
        Shu tufayli mijoz kodi yaratgan bola jarayonlar ham o'ladi.
        Jarayon allaqachon tugagan bo'lsa jim o'tadi.
        """
        self._killed = True
        process = self._process
        if process is None or process.returncode is not None:
            return
        await self._terminate(process)

    async def _terminate(self, process: asyncio.subprocess.Process) -> None:
        """SIGTERM -> grace -> SIGKILL ketma-ketligi (`_killed` ga tegmaydi)."""
        self._signal_group(process, signal.SIGTERM)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=KILL_GRACE_SECONDS)
            return

        logger.warning(
            "lokal jarayon SIGTERM'ga javob bermadi — SIGKILL",
            pid=process.pid,
            grace_seconds=KILL_GRACE_SECONDS,
        )
        self._signal_group(process, signal.SIGKILL)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(process.wait(), timeout=KILL_GRACE_SECONDS)

    def _signal_group(
        self,
        process: asyncio.subprocess.Process,
        sig: signal.Signals,
    ) -> None:
        """Signalni butun protsess GURUHIga yuboradi.

        Guruh bo'yicha yuborish MUHIM: mijoz kodi `subprocess` ishlatgan
        bo'lsa, faqat asosiy jarayonni o'ldirish bola jarayonlarni yetim
        qoldirardi. Guruhga yuborish imkonsiz bo'lsa (guruh allaqachon
        yo'q yoki ruxsat yetmaydi) bitta jarayonga qaytamiz.
        """
        pgid = self._pgid
        if pgid is not None and _killpg(pgid, sig):
            return
        with contextlib.suppress(ProcessLookupError, OSError):
            process.send_signal(sig)

    # --- Tozalash ---------------------------------------------------------

    def _cleanup(self, workdir: Path) -> None:
        """Qolib ketgan jarayonni o'ldiradi va vaqtinchalik katalogni o'chiradi.

        To'liq SINXRON: `run()` bekor qilingan paytda ham oxirigacha bajarilishi
        kerak. `shutil.rmtree` bu yerda kichik katalog ustida ishlaydi
        (bir nechta kichik fayl), shuning uchun event loop'ni sezilarli
        bloklamaydi. Katalog natija fayli O'QILGANDAN KEYIN o'chiriladi.
        """
        process = self._process
        if process is not None and process.returncode is None:
            # Oxirgi chora: `await` qilish imkoni yo'q, shuning uchun darhol
            # SIGKILL — jarayon "zombi" bo'lib qolmasligi kerak.
            self._signal_group(process, signal.SIGKILL)

        self._process = None
        self._pgid = None
        shutil.rmtree(workdir, ignore_errors=True)

    async def cleanup_orphans(self) -> int:
        """Lokal rejimda qolib ketgan narsa bo'lmaydi — har doim `0`.

        Jarayon o'z protsess guruhida ishga tushadi va `_cleanup()` uni
        SIGKILL bilan yopadi; vaqtinchalik katalog ham ayni joyda o'chadi.
        Tizimda qolib ketgan `durabl-local-*` kataloglarini OS o'zi
        (`/tmp` tozalash siyosati bilan) yo'q qiladi.
        """
        return 0


__all__ = [
    "INHERITED_ENV_VARS",
    "KILL_GRACE_SECONDS",
    "READ_CHUNK_BYTES",
    "SANDBOX_ID_PREFIX",
    "STREAM_LIMIT_BYTES",
    "TEMP_DIR_PREFIX",
    "LocalRunner",
]
