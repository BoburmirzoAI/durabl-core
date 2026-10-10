"""Durabl — resurs cheklovlarini platforma qiymatlariga aylantirish.

Bu modul **hisoblash emas, KONVERTATSIYA** qiladi: `ResourceLimits` dataclass'i
allaqachon `app/execution/types.py` da yozilgan va yakuniy qiymatlarni o'zi
hal qiladi. Shu fayl esa ayni cheklovlarni uch xil "tilga" tarjima qiladi:

* `to_docker_kwargs()`      -> Docker SDK `containers.run(**kwargs)` parametrlari
* `to_docker_host_config()` -> low-level API (`create_host_config`) lug'ati
* `to_rlimits()` / `apply_rlimits()` -> POSIX `resource.setrlimit` juftliklari
  (lokal subprocess runner uchun, `SANDBOX_ENABLED=False` rejimi)

Qo'shimcha ikki funksiya:

* `resolve_for_job()` — job so'rovi + reja limitidan `ResourceLimits` yasaydi va
  `sandbox/policies/resource-limits.json` dagi `hard_caps` bilan kesadi.
* `limits_summary()`  — log va API javobi uchun yassi (flat) lug'at.

Himoya qatlamlari (`resource-limits.json`, `enforcement_layers`) ataylab
takrorlanadi: bitta qatlam ishlamay qolsa, keyingisi ushlab qoladi.

    1. API validatsiyasi  (JobCreate schema)
    2. Docker/cgroup      (mem_limit, nano_cpus, pids_limit, tmpfs)
    3. gVisor             (syscall qatlami)
    4. entrypoint rlimit  (sandbox ichida)
    5. preexec rlimit     (shu fayl — lokal runner uchun)
    6. timeout_guard      (tashqaridan o'ldirish)
"""

from __future__ import annotations

import dataclasses
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from app.config import settings
from app.constants import (
    SANDBOX_RESULT_FILENAME,
    SANDBOX_WORKDIR,
    PlanLimits,
    PlanType,
    Runtime,
    plan_limits,
)
from app.exceptions import SandboxError
from app.execution.types import ResourceLimits

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshirgich uchun
    from app.execution.runtime_base import BaseRuntime

try:  # pragma: no cover - `resource` moduli faqat POSIX tizimlarda bor
    import resource
except ImportError:  # pragma: no cover - Windows
    resource = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Konstantalar
# ---------------------------------------------------------------------------

#: Orphan (qolib ketgan) konteynerlarni topish uchun yorliq nomi.
#: `app.constants` da yo'q, chunki bu faqat Docker qatlamiga tegishli —
#: shu tufayli yagona manba ayni shu modul (`sandbox_manager` shundan oladi).
LABEL_MANAGED: Final[str] = "durabl.managed"
LABEL_JOB_ID: Final[str] = "durabl.job_id"
LABEL_RUNTIME: Final[str] = "durabl.runtime"
LABEL_ATTEMPT: Final[str] = "durabl.attempt"
#: `LABEL_MANAGED` yorlig'ining qiymati (filtrda ham ayni shu matn ishlatiladi).
LABEL_MANAGED_VALUE: Final[str] = "true"

#: Tarmoq ruxsat etilganda ishlatiladigan Docker tarmoq rejimi.
#: Taqiqlanganda `settings.SANDBOX_NETWORK_MODE` (standart — `none`).
NETWORK_MODE_BRIDGE: Final[str] = "bridge"

#: Konteyner ichida yozishga ruxsat etilgan yagona joy (tmpfs).
TMPFS_MOUNT: Final[str] = "/tmp"
#: tmpfs bayroqlari: yozish mumkin, lekin kod bajarish va setuid TAQIQLANGAN.
TMPFS_FLAGS: Final[str] = "rw,noexec,nosuid"

#: Barcha Linux imkoniyatlari (capability) olib tashlanadi.
CAP_DROP_ALL: Final[tuple[str, ...]] = ("ALL",)
#: Protsess qo'shimcha imtiyoz ola olmasligi uchun.
SECURITY_OPT_NO_NEW_PRIVILEGES: Final[str] = "no-new-privileges"

#: `RLIMIT_NOFILE` — ochiq fayl deskriptorlari soni.
#: `sandbox/policies/resource-limits.json` dagi reja qiymatlari `disk_mb * 4`
#: ga AYNAN mos keladi (free 64->256, starter 128->512, pro 256->1024,
#: enterprise 1024->4096), shuning uchun koeffitsient sifatida saqlanadi.
NOFILE_PER_DISK_MB: Final[int] = 4
#: `RLIMIT_NPROC` uchun eng kichik ma'noli qiymat (interpretator ishga tushishi uchun).
#:
#: ## DIQQAT — bu limit FAQAT konteyner ichida ma'noga ega
#:
#: `RLIMIT_NPROC` — PROTSESS bo'yicha emas, **UID bo'yicha** limit:
#: o'sha foydalanuvchining BARCHA vazifalari (protsesslar VA thread'lar)
#: hisoblanadi. Shu sababli:
#:
#: * **Konteyner ichida** (`_ulimits` -> `to_docker_kwargs`) u TO'G'RI
#:   ishlaydi — uid 10001
#:   faqat shu job'ning protsesslarini ishlatadi, ya'ni limit haqiqatan
#:   "bu job nechta vazifa yaratishi mumkin" degani. Fork bombaga
#:   qarshi himoya aynan shu yerda.
#: * **Hostda** (`to_rlimits`, lokal runner) u BUZUQ — uid dasturchining
#:   yoki CI foydalanuvchisining boshqa hamma ishi bilan baham
#:   ko'riladi. O'sha uid'da allaqachon 100+ vazifa bo'lsa, limit 50
#:   bo'lgani uchun HAR QANDAY `fork()` yoki `pthread_create()` darhol
#:   `EAGAIN` bilan yiqiladi.
#:
#: Ikkinchi holat haqiqatda ro'y berdi. CI'da (GitHub runner) Node job'i
#: shunday yiqilardi::
#:
#:     exit=-6  non_zero_exit
#:     node::WorkerThreadsTaskRunner::DelayedTaskScheduler::Start()
#:     Assertion failed: (0) == (uv_thread_create(...))
#:
#: Node (libuv) ishga tushishida bir nechta thread yaratadi, Python esa
#: bitta — shu sababli xato faqat Node'da chiqdi. Tinch konteynerda
#: takrorlanmaydi (o'sha uid'da bir necha vazifa bor), shuning uchun
#: lokal sinovlar yolg'on "o'tdi" berardi.
#:
#: Xulosa: hostda `RLIMIT_NPROC` "job chegarasi" ni IFODALAY OLMAYDI —
#: har qanday qiymat xato bo'ladi (kichik bo'lsa buziladi, katta bo'lsa
#: himoya bermaydi). To'g'ri mexanizm — cgroup `pids` nazoratchisi
#: (`--pids-limit`), u `SandboxManager` da allaqachon qo'yiladi.
MIN_NPROC: Final[int] = 32

#: Bir megabayt — baytga aylantirish uchun.
BYTES_PER_MB: Final[int] = 1024 * 1024

#: `RLIMIT_AS` (virtual manzil maydoni) FAQAT Linux'da qo'llanadi.
#: macOS/BSD'da u yo tashlab yuboriladi, yo CPython/Node ishga tushishiga
#: yetmaydigan darajada qattiq bo'lib qoladi (interpretator o'zi uchun
#: limitdan ko'p virtual manzil band qiladi) — natijada mijoz kodi
#: bajarilmasdan o'ladi. Xotira cheklovi baribir cgroup darajasida bor.
RLIMIT_AS_SUPPORTED: Final[bool] = sys.platform.startswith("linux")

#: `RLIMIT_AS` QAYSI runtime'larga QO'YILMAYDI.
#:
#: V8 (Node) ishga tushishida katta virtual manzil diapazonini oldindan
#: zahiralaydi — bu HAQIQIY xotira sarfi emas, faqat manzil maydoni.
#: `RLIMIT_AS` esa aynan manzil maydonini cheklaydi, ya'ni V8 uchun u
#: xotira nazorati emas, oddiy to'siq bo'lib qoladi.
#:
#: Linux'da o'lchangan (`node v20`, `console.log("salom")`):
#:
#:     RLIMIT_AS yo'q    -> exit 0
#:     RLIMIT_AS 256 MB  -> SIGTRAP: "Failed to reserve virtual memory
#:                          for CodeRange"
#:     RLIMIT_AS 512 MB  -> exit 0
#:
#: Ya'ni standart `SANDBOX_MEMORY_MB=256` bilan Linux'da HAR QANDAY Node
#: job'i mijoz kodiga yetib bormasdan o'lardi (FREE rejada xotira
#: chegarasi ham aynan 256 MB). macOS'da `RLIMIT_AS` qo'yilmagani uchun
#: bu ko'rinmasdi — xato faqat Linux'da chiqardi.
#:
#: CPython 256 MB'ga sig'adi (o'lchangan), shuning uchun Python uchun
#: limit SAQLANADI. Node uchun xotira nazorati konteyner darajasida
#: (`--memory`, cgroup) ishlaydi va u haqiqiy RSS ni cheklaydi.
RLIMIT_AS_EXCLUDED_RUNTIMES: Final[frozenset[Runtime]] = frozenset({Runtime.NODE})


# ---------------------------------------------------------------------------
# Reja bo'yicha sandbox profili
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanSandboxProfile:
    """Rejaga xos, lekin `PlanLimits` da yo'q sandbox qiymatlari.

    `PLAN_LIMITS` (`app/constants.py`) faqat biznes limitlarini saqlaydi
    (xotira, CPU, timeout). Konteyner darajasidagi `pids_limit`, `disk_mb`,
    `tmpfs_mb` esa `sandbox/policies/resource-limits.json` dagi `plans.*.sandbox`
    bo'limidan keladi — shu dataclass ayni qiymatlarning Python ko'rinishi.
    """

    pids_limit: int
    disk_mb: int
    tmpfs_mb: int


#: Reja -> sandbox profili. `resource-limits.json` bilan AYNAN bir xil.
PLAN_SANDBOX_PROFILES: Final[dict[PlanType, PlanSandboxProfile]] = {
    PlanType.FREE: PlanSandboxProfile(pids_limit=50, disk_mb=64, tmpfs_mb=32),
    PlanType.STARTER: PlanSandboxProfile(pids_limit=100, disk_mb=128, tmpfs_mb=64),
    PlanType.PRO: PlanSandboxProfile(pids_limit=200, disk_mb=256, tmpfs_mb=128),
    PlanType.ENTERPRISE: PlanSandboxProfile(pids_limit=512, disk_mb=1024, tmpfs_mb=256),
}


@dataclass(frozen=True, slots=True)
class HardCaps:
    """Hech bir reja va hech bir so'rov oshib keta olmaydigan mutlaq chegara.

    Sozlama xatosi (masalan `.env` da `SANDBOX_MEMORY_MB=1000000`) hostni
    yiqitmasligi uchun oxirgi himoya — `resource-limits.json`, `hard_caps`.
    """

    memory_mb: int = 8192
    cpus: float = 8.0
    pids_limit: int = 1024
    timeout_seconds: int = 900
    output_bytes: int = 10_485_760


#: Mutlaq chegaralar (`resource-limits.json` -> `hard_caps`).
HARD_CAPS: Final[HardCaps] = HardCaps()


# ---------------------------------------------------------------------------
# Yordamchi hisoblashlar
# ---------------------------------------------------------------------------


def _profile_for(plan: PlanLimits | PlanType | str | None) -> PlanSandboxProfile:
    """Reja bo'yicha sandbox profilini qaytaradi (noma'lum reja -> FREE)."""
    if plan is None:
        return PlanSandboxProfile(
            pids_limit=settings.SANDBOX_PIDS_LIMIT,
            disk_mb=settings.SANDBOX_DISK_MB,
            tmpfs_mb=settings.SANDBOX_TMPFS_SIZE_MB,
        )
    plan_type = plan.plan if isinstance(plan, PlanLimits) else PlanType(plan)
    return PLAN_SANDBOX_PROFILES.get(plan_type, PLAN_SANDBOX_PROFILES[PlanType.FREE])


def _as_plan_limits(plan: PlanLimits | PlanType | str | None) -> PlanLimits | None:
    """Reja turini `PlanLimits` ga keltiradi (`None` bo'lsa — `None`)."""
    if plan is None or isinstance(plan, PlanLimits):
        return plan
    return plan_limits(plan)


def nofile_limit(limits: ResourceLimits) -> int:
    """`RLIMIT_NOFILE` — disk kvotasidan kelib chiqib hisoblangan fd soni."""
    return max(64, limits.disk_mb * NOFILE_PER_DISK_MB)


def nproc_limit(limits: ResourceLimits) -> int:
    """`RLIMIT_NPROC` — fork bombasiga qarshi protsesslar soni."""
    return max(MIN_NPROC, limits.pids_limit)


def fsize_limit_bytes(limits: ResourceLimits) -> int:
    """`RLIMIT_FSIZE` — yoziladigan eng katta fayl hajmi (bayt)."""
    return max(1, limits.disk_mb) * BYTES_PER_MB


@lru_cache(maxsize=4)
def _read_seccomp_profile(path: str) -> str:
    """Seccomp profilini o'qib JSON MATNINI qaytaradi (keshlangan).

    **Nega mazmun, yo'l emas.** `docker run --security-opt seccomp=/yo'l.json`
    da faylni Docker CLI o'zi o'qib, mazmunini API'ga yuboradi. Biz esa
    docker-py orqali TO'G'RIDAN-TO'G'RI API bilan gaplashamiz, API esa yo'lni
    tushunmaydi — u `security_opt` qiymatini JSON deb parse qiladi va
    `Decoding seccomp profile failed: invalid character '/' looking for
    beginning of value` xatosi bilan konteynerni ishga tushirmaydi.

    Shuning uchun faylni o'zimiz o'qiymiz. Profil har bir job uchun
    o'qilmasligi uchun `lru_cache` ishlatiladi (fayl deploy paytida
    o'zgaradi, ish vaqtida emas).

    Raises:
        SandboxError: Fayl yo'q yoki yaroqsiz JSON — bu konfiguratsiya
            xatosi, jim o'tkazib yuborish xavfsizlik qatlamini
            bildirmasdan o'chirib qo'ygan bo'lardi.
    """
    profile_path = Path(path)
    try:
        raw = profile_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SandboxError(
            f"Seccomp profili o'qilmadi: {profile_path} ({exc.strerror}). "
            "`SANDBOX_SECCOMP_PROFILE` sozlamasini tekshiring yoki bo'sh qoldiring."
        ) from exc
    try:
        json.loads(raw)
    except ValueError as exc:
        raise SandboxError(f"Seccomp profili yaroqli JSON emas: {profile_path} ({exc})") from exc
    # Docker API bo'shliqlarga e'tibor bermaydi, lekin tanani kichraytiramiz
    return json.dumps(json.loads(raw), separators=(",", ":"))


def _security_opt() -> list[str]:
    """Docker `security_opt` ro'yxati (seccomp profili sozlangan bo'lsa qo'shiladi).

    Profil MAZMUNI uzatiladi — tushuntirish `_read_seccomp_profile()` da.
    """
    options = [SECURITY_OPT_NO_NEW_PRIVILEGES]
    profile = settings.SANDBOX_SECCOMP_PROFILE
    if profile:
        options.append(f"seccomp={_read_seccomp_profile(profile)}")
    return options


def _ulimits(limits: ResourceLimits) -> list[dict[str, Any]]:
    """Docker SDK uchun `ulimits` ro'yxati (kichik harfli kalitlar bilan).

    `docker.types.Ulimit` obyekti shart emas: `create_host_config` oddiy
    lug'atni ham qabul qiladi va o'zi `Ulimit(**item)` ga aylantiradi.
    Shu tufayli bu modul `docker` paketiga BOG'LIQ EMAS — lokal runner
    Docker o'rnatilmagan mashinada ham ishlaydi.
    """
    nofile = nofile_limit(limits)
    nproc = nproc_limit(limits)
    fsize = fsize_limit_bytes(limits)
    return [
        {"name": "nofile", "soft": nofile, "hard": nofile},
        {"name": "nproc", "soft": nproc, "hard": nproc},
        {"name": "fsize", "soft": fsize, "hard": fsize},
    ]


def tmpfs_mounts(limits: ResourceLimits) -> dict[str, str]:
    """`--tmpfs` moslamalari: `/tmp` yozish mumkin, lekin `noexec`."""
    return {TMPFS_MOUNT: f"{TMPFS_FLAGS},size={max(1, limits.tmpfs_mb)}m"}


def network_mode(limits: ResourceLimits) -> str:
    """Tarmoq rejimi: ruxsat berilgan bo'lsa `bridge`, aks holda sozlamadagi (`none`)."""
    return NETWORK_MODE_BRIDGE if limits.allow_network else settings.SANDBOX_NETWORK_MODE


def container_labels(
    *,
    job_id: str = "",
    runtime: BaseRuntime | None = None,
    attempt_number: int | None = None,
) -> dict[str, str]:
    """Konteyner yorliqlari — orphan tozalash va kuzatuv uchun.

    `durabl.managed=true` MAJBURIY: `cleanup_orphans()` ayni shu filtr bilan
    qolib ketgan konteynerlarni topadi va boshqa birovning konteyneriga
    tegmaydi.
    """
    labels = {LABEL_MANAGED: LABEL_MANAGED_VALUE, LABEL_JOB_ID: job_id}
    if runtime is not None:
        labels[LABEL_RUNTIME] = runtime.runtime.value
    if attempt_number is not None:
        labels[LABEL_ATTEMPT] = str(attempt_number)
    return labels


# ---------------------------------------------------------------------------
# Docker SDK (yuqori darajali API)
# ---------------------------------------------------------------------------


def to_docker_kwargs(
    limits: ResourceLimits,
    *,
    runtime: BaseRuntime,
    job_id: str = "",
    attempt_number: int | None = None,
) -> dict[str, Any]:
    """`client.containers.run(image, command, **kwargs)` uchun parametrlar.

    `volumes` va `environment` BU YERDA qo'shilmaydi — ular bitta bajarishga
    xos (vaqtinchalik katalog, `spec.safe_env()`), shuning uchun
    `SandboxManager.run()` ularni o'zi qo'shadi.

    Args:
        limits: Hisoblangan resurs cheklovlari.
        runtime: Til runtime'i — yorliqqa (`durabl.runtime`) yoziladi.
        job_id: `durabl.job_id` yorlig'i (orphan tozalashda job'ni topish uchun).
        attempt_number: Urinish raqami (`durabl.attempt` yorlig'i), ixtiyoriy.

    Qaytgan lug'atdagi muhim qarorlar:

    * `memswap_limit == mem_limit` — swap BUTUNLAY o'chirilgan, aks holda kod
      limitdan oshib swap hisobiga ishlaydi va host sekinlashadi.
    * `auto_remove=False` — konteynerni o'zimiz o'chiramiz, chunki undan OLDIN
      loglarni va `result.json` ni o'qib olish kerak.
    * `read_only=True` + `tmpfs /tmp` — kod faqat tmpfs'ga yoza oladi.
    """
    memory = f"{limits.memory_mb}m"
    return {
        # gVisor (`runsc`) — ikkinchi kernel devori.
        "runtime": settings.SANDBOX_RUNTIME,
        "network_mode": network_mode(limits),
        "mem_limit": memory,
        # Swap xotira limitiga TENG => swap ishlatilmaydi.
        "memswap_limit": memory,
        "nano_cpus": int(limits.cpus * 1e9),
        "pids_limit": limits.pids_limit,
        "read_only": limits.read_only_rootfs,
        "tmpfs": tmpfs_mounts(limits),
        "cap_drop": list(CAP_DROP_ALL),
        "security_opt": _security_opt(),
        "user": settings.SANDBOX_USER,
        "working_dir": SANDBOX_WORKDIR,
        "ulimits": _ulimits(limits),
        "detach": True,
        "stdin_open": False,
        # `tty=False` — stdout va stderr ALOHIDA oqimlarda keladi (`demux=True`).
        "tty": False,
        "auto_remove": False,
        "labels": container_labels(
            job_id=job_id,
            runtime=runtime,
            attempt_number=attempt_number,
        ),
    }


def to_docker_host_config(limits: ResourceLimits) -> dict[str, Any]:
    """Low-level API (`APIClient.create_host_config`) uchun lug'at.

    Yuqori darajali SDK yetarli bo'lmagan holatlar uchun (masalan konteynerni
    oldin `create` qilib, keyin `start` qilish kerak bo'lsa). Kalitlar
    Docker Engine API nomlari bilan — `Memory`, `NanoCpus`, `Ulimits`...
    """
    memory_bytes = limits.memory_mb * BYTES_PER_MB
    return {
        "Runtime": settings.SANDBOX_RUNTIME,
        "NetworkMode": network_mode(limits),
        "Memory": memory_bytes,
        "MemorySwap": memory_bytes,
        "NanoCpus": int(limits.cpus * 1e9),
        "PidsLimit": limits.pids_limit,
        "ReadonlyRootfs": limits.read_only_rootfs,
        "Tmpfs": tmpfs_mounts(limits),
        "CapDrop": list(CAP_DROP_ALL),
        "SecurityOpt": _security_opt(),
        "AutoRemove": False,
        "Ulimits": [
            {"Name": item["name"], "Soft": item["soft"], "Hard": item["hard"]}
            for item in _ulimits(limits)
        ],
    }


# ---------------------------------------------------------------------------
# POSIX rlimit (lokal subprocess runner)
# ---------------------------------------------------------------------------


def to_rlimits(
    limits: ResourceLimits, *, runtime: Runtime | None = None
) -> list[tuple[int, tuple[int, int]]]:
    """`resource.setrlimit` uchun `(limit_id, (soft, hard))` juftliklari.

    Faqat JORIY platformada ma'noga ega bo'lgan cheklovlar qaytadi:
    `resource` moduli bo'lmagan tizimda bo'sh ro'yxat, macOS'da esa
    `RLIMIT_AS` tashlab yuboriladi (`RLIMIT_AS_SUPPORTED` ga qarang).

    `RLIMIT_NPROC` bu ro'yxatga HECH QACHON kirmaydi: u UID bo'yicha
    limit va hostda "job chegarasi" ni ifodalay olmaydi (batafsil
    `MIN_NPROC` izohida). Konteyner ichida esa `_ulimits()` orqali
    qo'yiladi va u yerda to'g'ri ishlaydi.

    Juftlikdagi `hard` qiymati `soft` ga TENG qo'yiladi — bola jarayon
    cheklovni o'zi yumshata olmasligi uchun.

    Args:
        limits: Qo'llanadigan resurs cheklovlari.
        runtime: Qaysi runtime ishga tushadi. `RLIMIT_AS_EXCLUDED_RUNTIMES`
            ichidagi runtime'lar uchun `RLIMIT_AS` QO'YILMAYDI (sababi
            o'sha konstantada). `None` — runtime noma'lum, limit
            qo'llanadi (eng qat'iy variant).
    """
    if resource is None:  # pragma: no cover - Windows
        return []

    desired: list[tuple[str, int]] = []
    if RLIMIT_AS_SUPPORTED and runtime not in RLIMIT_AS_EXCLUDED_RUNTIMES:
        # Virtual manzil maydoni — xotira limitining protsess darajasidagi aksi.
        desired.append(("RLIMIT_AS", limits.memory_mb * BYTES_PER_MB))
    desired.extend(
        [
            # CPU vaqti: `while True: pass` kabi halqa uchun oxirgi to'siq.
            ("RLIMIT_CPU", max(1, limits.timeout_seconds)),
            ("RLIMIT_NOFILE", nofile_limit(limits)),
            # `RLIMIT_NPROC` ATAYLAB YO'Q — sababi pastda.
            ("RLIMIT_FSIZE", fsize_limit_bytes(limits)),
            # Core dump yozilmaydi: diskni to'ldirmasligi va mijoz xotirasi
            # faylga tushib qolmasligi uchun.
            ("RLIMIT_CORE", 0),
        ]
    )

    pairs: list[tuple[int, tuple[int, int]]] = []
    for name, value in desired:
        limit_id = getattr(resource, name, None)
        if limit_id is None or value < 0:
            continue
        pairs.append((int(limit_id), (value, value)))
    return pairs


def apply_rlimits(limits: ResourceLimits, *, runtime: Runtime | None = None) -> Callable[[], None]:
    """`subprocess` ning `preexec_fn` uchun funksiya qaytaradi.

    Qaytgan funksiya `fork()` dan KEYIN, `exec()` dan OLDIN bola jarayonda
    ishlaydi. Shu sababli u:

    * hech narsa log QILMAYDI (fork'dan keyin lock holati xavfli),
    * hech qanday xato TASHLAMAYDI — har bir limit alohida `try` ichida.

    Limit qo'yilmasligi (masalan macOS'da `RLIMIT_AS`, yoki hard limit
    ruxsat bermasligi) bajarishni to'xtatmaydi: resurs nazorati baribir
    bir necha qatlamda takrorlangan.
    """
    pairs = to_rlimits(limits, runtime=runtime)

    def _preexec() -> None:
        """Bola jarayonda cheklovlarni qo'yadi (xatoni jim o'tkazadi)."""
        if resource is None:  # pragma: no cover - Windows
            return
        for limit_id, (soft, hard) in pairs:
            try:
                current_soft, current_hard = resource.getrlimit(limit_id)
                target_hard = hard
                if current_hard != resource.RLIM_INFINITY:
                    # Mavjud hard limitdan oshib keta olmaymiz.
                    target_hard = min(hard, current_hard)
                target_soft = min(soft, target_hard)
                if current_soft != resource.RLIM_INFINITY and current_soft < target_soft:
                    # Mavjud limit allaqachon qattiqroq — yumshatmaymiz.
                    continue
                resource.setrlimit(limit_id, (target_soft, target_hard))
            except (OSError, ValueError, OverflowError):
                # Platforma qo'llab-quvvatlamaydi yoki ruxsat bermaydi — o'tamiz.
                continue

    return _preexec


# ---------------------------------------------------------------------------
# Sandbox entrypoint'i o'qiydigan muhit o'zgaruvchilari
# ---------------------------------------------------------------------------

#: Entrypoint ish katalogini shu o'zgaruvchidan oladi.
ENV_WORKDIR: Final[str] = "DURABL_SANDBOX_WORKDIR"
#: Mijoz kodi fayli nomi (`main.py` / `main.js`).
ENV_CODE_FILENAME: Final[str] = "DURABL_SANDBOX_CODE_FILENAME"
#: Natija fayli nomi (`result.json`).
ENV_RESULT_FILENAME: Final[str] = "DURABL_SANDBOX_RESULT_FILENAME"
#: Entrypoint xotirada ushlab qoladigan chiqish hajmi.
ENV_MAX_OUTPUT_BYTES: Final[str] = "DURABL_MAX_OUTPUT_BYTES"
#: Entrypoint o'zini SIGALRM bilan to'xtatadigan vaqt (0 = o'chirilgan).
ENV_TIMEOUT_SECONDS: Final[str] = "DURABL_SANDBOX_TIMEOUT_SECONDS"
#: Entrypoint ichidagi `setrlimit` yoqilganmi.
ENV_RLIMITS_ENABLED: Final[str] = "DURABL_RLIMITS_ENABLED"
ENV_RLIMIT_NOFILE: Final[str] = "DURABL_RLIMIT_NOFILE"
ENV_RLIMIT_NPROC: Final[str] = "DURABL_RLIMIT_NPROC"
ENV_RLIMIT_FSIZE_MB: Final[str] = "DURABL_RLIMIT_FSIZE_MB"


def to_sandbox_env(
    limits: ResourceLimits,
    *,
    runtime: BaseRuntime | None = None,
    workdir: str | Path | None = None,
) -> dict[str, str]:
    """Cheklovlarni sandbox entrypoint'i tushunadigan muhit o'zgaruvchilariga aylantiradi.

    Ikki runner ham (`SandboxManager` va `LocalRunner`) ayni shu funksiyani
    ishlatadi — shu tufayli konteynerda va lokal subprocess'da entrypoint
    BIR XIL shartnomani ko'radi.

    Bu o'zgaruvchilar mijoz `env_vars` idan KEYIN qo'yilishi kerak: aks holda
    mijoz `DURABL_SANDBOX_RESULT_FILENAME` ni almashtirib natija yozilishini
    buzishi mumkin edi.

    Args:
        limits: Hisoblangan resurs cheklovlari.
        runtime: Til runtime'i — kod fayli nomini berish uchun (ixtiyoriy).
        workdir: Entrypoint ishlashi kerak bo'lgan katalog (ixtiyoriy).
    """
    env: dict[str, str] = {
        ENV_MAX_OUTPUT_BYTES: str(limits.max_output_bytes),
        ENV_TIMEOUT_SECONDS: str(limits.timeout_seconds),
        ENV_RLIMITS_ENABLED: "1",
        ENV_RLIMIT_NOFILE: str(nofile_limit(limits)),
        ENV_RLIMIT_NPROC: str(nproc_limit(limits)),
        ENV_RLIMIT_FSIZE_MB: str(max(1, limits.disk_mb)),
        ENV_RESULT_FILENAME: SANDBOX_RESULT_FILENAME,
    }
    if runtime is not None:
        env[ENV_CODE_FILENAME] = runtime.code_filename
    if workdir is not None:
        env[ENV_WORKDIR] = str(workdir)
    return env


# ---------------------------------------------------------------------------
# Reja + so'rovdan yakuniy cheklovlar
# ---------------------------------------------------------------------------


def resolve_for_job(
    job_memory_mb: int | None = None,
    job_cpus: float | None = None,
    job_timeout: int | None = None,
    plan: PlanLimits | PlanType | str | None = None,
) -> ResourceLimits:
    """Job so'rovi va foydalanuvchi rejasidan yakuniy cheklovlarni hisoblaydi.

    Uch bosqich:

    1. `ResourceLimits.resolve()` — so'rovni reja chegarasiga qisqartiradi
       ("silent clamp": xato tashlanmaydi, mijoz kodi baribir ishlaydi).
    2. Reja sandbox profili — `pids_limit`, `disk_mb`, `tmpfs_mb` qo'shiladi.
    3. `HARD_CAPS` — mutlaq chegara bilan kesish (sozlama xatosiga qarshi).

    Args:
        job_memory_mb: `Job.memory_mb` (mijoz so'ragan xotira) yoki `None`.
        job_cpus: `Job.cpus` yoki `None`.
        job_timeout: `Job.timeout_seconds` yoki `None`.
        plan: Foydalanuvchi rejasi — `PlanLimits`, `PlanType` yoki matn.

    Returns:
        Bajarishga tayyor, chegaralangan `ResourceLimits`.
    """
    limits = ResourceLimits.resolve(
        requested_memory_mb=job_memory_mb,
        requested_cpus=job_cpus,
        requested_timeout=job_timeout,
        plan=_as_plan_limits(plan),
    )
    profile = _profile_for(plan)

    return dataclasses.replace(
        limits,
        memory_mb=min(limits.memory_mb, HARD_CAPS.memory_mb),
        cpus=min(limits.cpus, HARD_CAPS.cpus),
        timeout_seconds=min(limits.timeout_seconds, HARD_CAPS.timeout_seconds),
        pids_limit=min(profile.pids_limit, HARD_CAPS.pids_limit),
        disk_mb=profile.disk_mb,
        tmpfs_mb=profile.tmpfs_mb,
        max_output_bytes=min(settings.MAX_OUTPUT_BYTES, HARD_CAPS.output_bytes),
    )


#: `docs/CONTRACTS.md` §7 da kelishilgan nom — `resolve_for_job` bilan AYNI
#: funksiya. Ikki nom saqlanadi, chunki shartnomaning §7 bo'limi va keyingi
#: "ma'lumotlar qatlami yakunlandi" qo'shimchasi turli nom ishlatadi;
#: `app/execution/__init__.py` esa `resolve_limits` ni eksport qiladi.
resolve_limits = resolve_for_job


# ---------------------------------------------------------------------------
# Log va API uchun qisqa ko'rinish
# ---------------------------------------------------------------------------


def limits_summary(limits: ResourceLimits) -> dict[str, Any]:
    """Cheklovlarning yassi ko'rinishi — structlog maydonlari va API javobi uchun.

    Hisoblangan (derived) qiymatlar ham qo'shiladi, chunki muammoni tahlil
    qilayotgan odam `rlimit_nofile` qanday chiqqanini bilishi kerak.
    """
    return {
        "memory_mb": limits.memory_mb,
        "cpus": limits.cpus,
        "pids_limit": limits.pids_limit,
        "disk_mb": limits.disk_mb,
        "tmpfs_mb": limits.tmpfs_mb,
        "timeout_seconds": limits.timeout_seconds,
        "max_output_bytes": limits.max_output_bytes,
        "allow_network": limits.allow_network,
        "read_only_rootfs": limits.read_only_rootfs,
        "network_mode": network_mode(limits),
        "rlimit_nofile": nofile_limit(limits),
        "rlimit_nproc": nproc_limit(limits),
        "rlimit_fsize_bytes": fsize_limit_bytes(limits),
        "rlimit_as_applied": RLIMIT_AS_SUPPORTED,
    }


__all__ = [
    "BYTES_PER_MB",
    "CAP_DROP_ALL",
    "ENV_CODE_FILENAME",
    "ENV_MAX_OUTPUT_BYTES",
    "ENV_RESULT_FILENAME",
    "ENV_RLIMITS_ENABLED",
    "ENV_RLIMIT_FSIZE_MB",
    "ENV_RLIMIT_NOFILE",
    "ENV_RLIMIT_NPROC",
    "ENV_TIMEOUT_SECONDS",
    "ENV_WORKDIR",
    "HARD_CAPS",
    "LABEL_ATTEMPT",
    "LABEL_JOB_ID",
    "LABEL_MANAGED",
    "LABEL_MANAGED_VALUE",
    "LABEL_RUNTIME",
    "MIN_NPROC",
    "NETWORK_MODE_BRIDGE",
    "NOFILE_PER_DISK_MB",
    "PLAN_SANDBOX_PROFILES",
    "RLIMIT_AS_EXCLUDED_RUNTIMES",
    "RLIMIT_AS_SUPPORTED",
    "SECURITY_OPT_NO_NEW_PRIVILEGES",
    "TMPFS_FLAGS",
    "TMPFS_MOUNT",
    "HardCaps",
    "PlanSandboxProfile",
    "apply_rlimits",
    "container_labels",
    "fsize_limit_bytes",
    "limits_summary",
    "network_mode",
    "nofile_limit",
    "nproc_limit",
    "resolve_for_job",
    "resolve_limits",
    "tmpfs_mounts",
    "to_docker_host_config",
    "to_docker_kwargs",
    "to_rlimits",
    "to_sandbox_env",
]
