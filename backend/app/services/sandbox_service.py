"""Durabl — `app/execution/` qatlami ustidagi yupqa fasad (facade).

Bu servis bajarish YADROSINI biznes qatlamidan ajratib turadi:

    Job (DB modeli) ──▶ SandboxService.build_spec() ──▶ SandboxSpec
                                                           │
                        SandboxService.run() ──▶ Executor ─┘
                                                           ▼
                                                     ExecutionResult

Nega alohida servis kerak?

* `ExecutionService` DB bilan ishlaydi va `Executor` ning ichki tuzilishini
  bilishi shart emas — u faqat shu fasadga qaraydi. Natijada bajarish
  yadrosini soxta (fake) nusxa bilan almashtirib, DB mantig'ini Docker'siz
  test qilish mumkin.
* `/ready` tekshiruvi va `cleanup_orphans` kabi operatsion amallar API va
  worker qatlamlarida AYNI shu nom bilan chaqiriladi.

**Bu servis DB'ga TEGMAYDI va `AsyncSession` olmaydi** — shuning uchun
`commit()` ham qilmaydi (tranzaksiya egasi har doim chaqiruvchi servis).
`build_spec()` esa toza konvertatsiya: faqat `Job` obyektining allaqachon
yuklangan ustunlarini o'qiydi (`lazy="raise"` bog'lanishlarga tegmaydi).

Qatlam qoidasi: `fastapi` import QILINMAYDI, `HTTPException` tashlanmaydi —
ayni shu kod worker protsesslarida ham ishlaydi.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.constants import PlanLimits, Runtime
from app.execution.executor import Executor, default_executor
from app.execution.runtime_base import LogSink
from app.execution.types import ExecutionResult, ResourceLimits, SandboxSpec
from app.logging_config import get_logger
from app.models.job import Job

logger = get_logger(__name__)


class SandboxService:
    """Kod bajarish muhiti bilan ishlashning yagona kirish nuqtasi.

    Args:
        executor: Bajarish koordinatori. `None` bo'lsa sozlamaga mos standart
            nusxa olinadi (`default_executor()`). Ochiq berish testlar uchun:
            soxta runner bilan yasalgan `Executor` uzatiladi.
    """

    __slots__ = ("executor",)

    def __init__(self, executor: Executor | None = None) -> None:
        self.executor = executor or default_executor()

    # ------------------------------------------------------------------
    # Bajarish
    # ------------------------------------------------------------------

    async def run(
        self,
        spec: SandboxSpec,
        *,
        on_log: LogSink | None = None,
    ) -> ExecutionResult:
        """Kodni bajaradi va to'liq natijani qaytaradi.

        `Executor.execute()` shartnomasi SAQLANADI — ya'ni bu metod bajarish
        xatolarini TASHLAMAYDI, har doim `ExecutionResult` qaytaradi. Ikki
        istisno chaqiruvchiga o'tadi:

        * `asyncio.CancelledError` — strukturaviy bekor qilish signali;
        * `UnsupportedRuntimeError` — validatsiya xatosi (bajarish hatto
          boshlanmaydi).

        Args:
            spec: Bajarish topshirig'i (`build_spec()` yasaydi).
            on_log: Real vaqtdagi log callback'i `on_log(stream, chunk)`.
                Xato tashlasa bajarish buzilmaydi (executor yutib yuboradi).
        """
        return await self.executor.execute(spec, on_log=on_log)

    # ------------------------------------------------------------------
    # Operatsion amallar
    # ------------------------------------------------------------------

    async def available(self) -> bool:
        """Bajarish muhiti ishlashga tayyormi (`/ready` tekshiruvi uchun).

        Xato tashlamaydi: tekshiruvning o'zi qulasa `False` qaytadi.
        """
        return await self.executor.available()

    async def cleanup_orphans(self) -> int:
        """Qolib ketgan konteyner/jarayonlarni tozalaydi; sonini qaytaradi.

        Worker ishga tushganda va davriy ravishda chaqiriladi: oldingi
        protsess qulab qolgan sandbox'lar resursni band qilib turmasligi
        uchun. Xato tashlamaydi — tozalanmagan bo'lsa `0` qaytadi.
        """
        return await self.executor.cleanup_orphans()

    # ------------------------------------------------------------------
    # Job -> SandboxSpec konvertatsiyasi
    # ------------------------------------------------------------------

    def build_spec(
        self,
        job: Job,
        *,
        attempt_number: int,
        plan: PlanLimits | None = None,
    ) -> SandboxSpec:
        """`Job` modelidan `SandboxSpec` yasaydi (DB'ga TEGMAYDI).

        Resurs cheklovlari uch manbadan eng QAT'IYsi tanlanadi
        (`ResourceLimits.resolve()`): job so'rovi -> foydalanuvchi rejasi ->
        global sozlama. Mijoz rejasidan ko'proq so'rasa xato tashlanmaydi —
        qiymat jimgina reja chegarasiga qisqartiriladi ("silent clamp"),
        chunki mijoz kodi baribir ishlashi kerak.

        Args:
            job: Bajarilishi kerak bo'lgan job (ustunlari yuklangan bo'lishi
                shart; bog'lanishlar o'qilmaydi).
            attempt_number: Nechanchi urinish (1 — birinchi). Sandbox ichida
                `DURABL_ATTEMPT` muhit o'zgaruvchisi bo'lib ko'rinadi.
            plan: Foydalanuvchi rejasi limitlari. `None` bo'lsa global
                sozlama chegaralari qo'llanadi (eng qat'iy variant).

        Returns:
            Bajarishga tayyor `SandboxSpec`.
        """
        limits = ResourceLimits.resolve(
            requested_memory_mb=job.memory_mb,
            requested_cpus=job.cpus,
            requested_timeout=job.timeout_seconds,
            plan=plan,
        )

        spec = SandboxSpec(
            job_id=str(job.id),
            code=job.code,
            runtime=Runtime(job.runtime),
            limits=limits,
            payload=self._normalize_payload(job.payload),
            env_vars=self._normalize_env(job.env_vars),
            correlation_id=job.correlation_id or "",
            attempt_number=max(1, int(attempt_number)),
        )

        logger.debug(
            "sandbox.spec_built",
            job_id=spec.job_id,
            runtime=spec.runtime.value,
            attempt=spec.attempt_number,
            memory_mb=limits.memory_mb,
            cpus=limits.cpus,
            timeout_seconds=limits.timeout_seconds,
            allow_network=limits.allow_network,
            plan=plan.plan.value if plan is not None else None,
        )
        return spec

    # ------------------------------------------------------------------
    # Ichki yordamchilar
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_payload(payload: Any) -> dict[str, Any] | None:
        """`jobs.payload` ustunini sandbox shartnomasidagi lug'atga keltiradi.

        Ustun `JSONType` bo'lgani uchun nazariy jihatdan ro'yxat yoki skalyar
        ham tushishi mumkin (migratsiya, qo'lda yozilgan yozuv). Sandbox
        entrypoint'i esa `payload.json` da LUG'AT kutadi, shuning uchun
        lug'at bo'lmagan qiymat `{"value": ...}` ichiga o'raladi — ma'lumot
        yo'qolmaydi va entrypoint shartnomasi buzilmaydi.
        """
        if payload is None:
            return None
        if isinstance(payload, Mapping):
            return {str(key): value for key, value in payload.items()}
        return {"value": payload}

    @staticmethod
    def _normalize_env(env_vars: Any) -> dict[str, str] | None:
        """`jobs.env_vars` ustunini `dict[str, str]` ga keltiradi.

        Docker ham, lokal `subprocess` ham muhit o'zgaruvchilarida FAQAT
        matn qabul qiladi — son yoki `None` uzatilsa `TypeError` beradi.
        `None` qiymatli kalitlar butunlay tashlab yuboriladi (o'zgaruvchi
        "bo'sh matn" bo'lib qolishi mijozni chalg'itadi).
        """
        if not isinstance(env_vars, Mapping):
            return None
        normalized = {
            str(key): str(value) for key, value in env_vars.items() if value is not None
        }
        return normalized or None

    def __repr__(self) -> str:  # pragma: no cover - debug yordamchisi
        return f"<SandboxService executor={self.executor!r}>"


__all__ = ["SandboxService"]
