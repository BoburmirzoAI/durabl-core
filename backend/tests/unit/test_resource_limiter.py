"""Durabl — `app/execution/resource_limiter.py` birlik testlari.

Modul HISOBLAMAYDI, balki KONVERTATSIYA qiladi: `ResourceLimits` ni Docker
parametrlariga, low-level host config'ga va POSIX `rlimit` juftliklariga
aylantiradi. Shuning uchun test har bir "tarjima" ning kalitlarini aniq
tekshiradi — bitta kalit nomi o'zgarsa konteyner cheklovsiz ishga tushadi
(masalan `mem_limit` o'rniga `memory` yozilsa Docker SDK uni JIM e'tiborsiz
qoldiradi va xotira limiti YO'Q bo'lib qoladi).

Shuningdek reja bo'yicha qisqartirish (`resolve_for_job`) tekshiriladi:
FREE rejadagi mijoz 4 GB so'rasa ham 256 MB oladi — xato tashlanmaydi,
qiymat jim kesiladi ("silent clamp").
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest
from app.config import settings
from app.constants import PlanType, Runtime, plan_limits
from app.exceptions import SandboxError
from app.execution import resource_limiter
from app.execution.resource_limiter import (
    BYTES_PER_MB,
    CAP_DROP_ALL,
    HARD_CAPS,
    LABEL_ATTEMPT,
    LABEL_JOB_ID,
    LABEL_MANAGED,
    LABEL_MANAGED_VALUE,
    LABEL_RUNTIME,
    NETWORK_MODE_BRIDGE,
    NOFILE_PER_DISK_MB,
    PLAN_SANDBOX_PROFILES,
    RLIMIT_AS_SUPPORTED,
    SECURITY_OPT_NO_NEW_PRIVILEGES,
    TMPFS_MOUNT,
    _read_seccomp_profile,
    apply_rlimits,
    container_labels,
    fsize_limit_bytes,
    limits_summary,
    network_mode,
    nofile_limit,
    nproc_limit,
    resolve_for_job,
    resolve_limits,
    tmpfs_mounts,
    to_docker_host_config,
    to_docker_kwargs,
    to_rlimits,
    to_sandbox_env,
)
from app.execution.runtime_python import PythonRuntime
from app.execution.types import ResourceLimits

from tests.factories import make_limits

pytestmark = pytest.mark.unit

RUNTIME = PythonRuntime()


# ---------------------------------------------------------------------------
# ResourceLimits.resolve — reja bo'yicha qisqartirish
# ---------------------------------------------------------------------------


def test_resolve_reja_chegarasiga_qisqartiradi() -> None:
    """FREE reja: 4 GB so'rov 256 MB ga, 4 CPU 0.5 ga kesiladi."""
    limits = ResourceLimits.resolve(
        requested_memory_mb=4096,
        requested_cpus=4.0,
        requested_timeout=600,
        plan=plan_limits(PlanType.FREE),
    )
    assert limits.memory_mb == 256
    assert limits.cpus == 0.5
    assert limits.timeout_seconds == 30
    assert limits.allow_network is False


def test_resolve_kichik_sorovni_oshirmaydi() -> None:
    """Rejadan KAM so'ralgan qiymat o'z holida qoladi."""
    limits = ResourceLimits.resolve(
        requested_memory_mb=128,
        requested_cpus=0.2,
        requested_timeout=10,
        plan=plan_limits(PlanType.PRO),
    )
    assert limits.memory_mb == 128
    assert limits.cpus == 0.2
    assert limits.timeout_seconds == 10


def test_resolve_sorov_berilmasa_reja_qiymati() -> None:
    """So'rov bo'sh bo'lsa rejaning maksimal xotirasi/CPU'si olinadi."""
    limits = ResourceLimits.resolve(plan=plan_limits(PlanType.STARTER))
    assert limits.memory_mb == 512
    assert limits.cpus == 1.0
    assert limits.timeout_seconds == settings.DEFAULT_TIMEOUT_SECONDS


def test_resolve_xotira_pastki_chegarasi() -> None:
    """64 MB dan kam xotira berilmaydi (interpretator ishga tushmaydi)."""
    limits = ResourceLimits.resolve(requested_memory_mb=1, plan=plan_limits(PlanType.FREE))
    assert limits.memory_mb == 64


def test_resolve_cpu_pastki_chegarasi() -> None:
    """CPU 0.1 dan kam bo'lmaydi."""
    limits = ResourceLimits.resolve(requested_cpus=0.001, plan=plan_limits(PlanType.FREE))
    assert limits.cpus == 0.1


def test_resolve_tarmoq_rejadan_keladi() -> None:
    """Tarmoq ruxsati REJADAN keladi, so'rovdan emas."""
    assert ResourceLimits.resolve(plan=plan_limits(PlanType.FREE)).allow_network is False
    assert ResourceLimits.resolve(plan=plan_limits(PlanType.PRO)).allow_network is True


def test_resolve_global_timeout_chegarasi() -> None:
    """ENTERPRISE rejada ham global `MAX_TIMEOUT_SECONDS` ustun turadi."""
    limits = ResourceLimits.resolve(
        requested_timeout=100_000, plan=plan_limits(PlanType.ENTERPRISE)
    )
    assert limits.timeout_seconds == min(900, settings.MAX_TIMEOUT_SECONDS)


# ---------------------------------------------------------------------------
# resolve_for_job — reja profili + hard caps
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("plan", list(PlanType))
def test_resolve_for_job_reja_profilini_qollaydi(plan: PlanType) -> None:
    """`pids_limit`/`disk_mb`/`tmpfs_mb` reja profilidan olinadi."""
    profile = PLAN_SANDBOX_PROFILES[plan]
    limits = resolve_for_job(plan=plan)
    assert limits.pids_limit == min(profile.pids_limit, HARD_CAPS.pids_limit)
    assert limits.disk_mb == profile.disk_mb
    assert limits.tmpfs_mb == profile.tmpfs_mb


def test_resolve_for_job_hard_caps_bilan_kesiladi() -> None:
    """Hech bir qiymat mutlaq chegaradan oshmaydi."""
    limits = resolve_for_job(
        job_memory_mb=1_000_000,
        job_cpus=1_000.0,
        job_timeout=1_000_000,
        plan=PlanType.ENTERPRISE,
    )
    assert limits.memory_mb <= HARD_CAPS.memory_mb
    assert limits.cpus <= HARD_CAPS.cpus
    assert limits.timeout_seconds <= HARD_CAPS.timeout_seconds
    assert limits.max_output_bytes <= HARD_CAPS.output_bytes


def test_resolve_for_job_reja_matn_sifatida() -> None:
    """Reja matn ko'rinishida ham qabul qilinadi (`"free"`)."""
    assert resolve_for_job(plan="free").memory_mb == resolve_for_job(plan=PlanType.FREE).memory_mb


def test_resolve_for_job_reja_berilmasa_sozlamadan() -> None:
    """Reja yo'q bo'lsa sandbox sozlamalari ishlatiladi."""
    limits = resolve_for_job()
    assert limits.pids_limit == min(settings.SANDBOX_PIDS_LIMIT, HARD_CAPS.pids_limit)
    assert limits.disk_mb == settings.SANDBOX_DISK_MB


def test_resolve_limits_aliasi_ayni_funksiya() -> None:
    """Shartnomadagi `resolve_limits` nomi `resolve_for_job` bilan AYNI."""
    assert resolve_limits is resolve_for_job


# ---------------------------------------------------------------------------
# to_docker_kwargs
# ---------------------------------------------------------------------------


def test_to_docker_kwargs_majburiy_kalitlar() -> None:
    """Barcha xavfsizlik kalitlari mavjud bo'lishi SHART."""
    kwargs = to_docker_kwargs(make_limits(), runtime=RUNTIME)
    for key in (
        "mem_limit",
        "memswap_limit",
        "nano_cpus",
        "pids_limit",
        "read_only",
        "cap_drop",
        "security_opt",
        "network_mode",
        "tmpfs",
        "labels",
        "ulimits",
        "user",
        "working_dir",
        "runtime",
    ):
        assert key in kwargs, f"kalit yo'qolgan: {key}"


def test_to_docker_kwargs_qiymatlari() -> None:
    """Qiymatlar cheklovlardan to'g'ri hisoblanadi."""
    limits = make_limits(memory_mb=512, cpus=1.5, pids_limit=100)
    kwargs = to_docker_kwargs(limits, runtime=RUNTIME)
    assert kwargs["mem_limit"] == "512m"
    assert kwargs["nano_cpus"] == int(1.5 * 1e9)
    assert kwargs["pids_limit"] == 100
    assert kwargs["read_only"] is True
    assert kwargs["cap_drop"] == list(CAP_DROP_ALL)
    assert SECURITY_OPT_NO_NEW_PRIVILEGES in kwargs["security_opt"]


def test_to_docker_kwargs_swap_ochirilgan() -> None:
    """KRITIK: `memswap_limit == mem_limit` — swap ishlatilmaydi."""
    kwargs = to_docker_kwargs(make_limits(memory_mb=256), runtime=RUNTIME)
    assert kwargs["memswap_limit"] == kwargs["mem_limit"]


def test_to_docker_kwargs_tmpfs_noexec() -> None:
    """`/tmp` yozish mumkin, lekin `noexec,nosuid` bilan."""
    kwargs = to_docker_kwargs(make_limits(tmpfs_mb=64), runtime=RUNTIME)
    mount = kwargs["tmpfs"][TMPFS_MOUNT]
    assert "noexec" in mount
    assert "nosuid" in mount
    assert "size=64m" in mount


def test_to_docker_kwargs_auto_remove_ochirilgan() -> None:
    """Konteyner o'zi o'chmaydi — avval loglar va `result.json` o'qiladi."""
    kwargs = to_docker_kwargs(make_limits(), runtime=RUNTIME)
    assert kwargs["auto_remove"] is False
    assert kwargs["detach"] is True
    assert kwargs["tty"] is False  # stdout/stderr ALOHIDA oqimda


def test_to_docker_kwargs_yorliqlari() -> None:
    """Yorliqlar orphan tozalash uchun to'liq bo'ladi."""
    kwargs = to_docker_kwargs(make_limits(), runtime=RUNTIME, job_id="job-1", attempt_number=2)
    labels = kwargs["labels"]
    assert labels[LABEL_MANAGED] == LABEL_MANAGED_VALUE
    assert labels[LABEL_JOB_ID] == "job-1"
    assert labels[LABEL_RUNTIME] == Runtime.PYTHON.value
    assert labels[LABEL_ATTEMPT] == "2"


def test_to_docker_kwargs_ulimits_shakli() -> None:
    """`ulimits` — `docker` paketiga bog'liq bo'lmagan oddiy lug'atlar."""
    limits = make_limits(disk_mb=64, pids_limit=50, timeout_seconds=10)
    ulimits = to_docker_kwargs(limits, runtime=RUNTIME)["ulimits"]
    names = {item["name"] for item in ulimits}
    assert names == {"nofile", "nproc", "fsize"}
    for item in ulimits:
        assert item["soft"] == item["hard"]  # bola limitni yumshata olmaydi


@pytest.mark.parametrize(
    ("allow_network", "expected"),
    [(True, NETWORK_MODE_BRIDGE), (False, settings.SANDBOX_NETWORK_MODE)],
)
def test_network_mode_tarmoq_ruxsatiga_qarab(allow_network: bool, expected: str) -> None:
    """Tarmoq taqiqlangan bo'lsa `none`, ruxsat etilsa `bridge`."""
    assert network_mode(make_limits(allow_network=allow_network)) == expected


def test_to_docker_kwargs_network_mode_rejaga_qarab_ozgaradi() -> None:
    """FREE rejada tarmoq yo'q, PRO rejada bor — kwargs ham shunga qarab."""
    free = to_docker_kwargs(resolve_for_job(plan=PlanType.FREE), runtime=RUNTIME)
    pro = to_docker_kwargs(resolve_for_job(plan=PlanType.PRO), runtime=RUNTIME)
    assert free["network_mode"] == settings.SANDBOX_NETWORK_MODE
    assert pro["network_mode"] == NETWORK_MODE_BRIDGE


def test_to_docker_kwargs_seccomp_profil_MAZMUNINI_uzatadi(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Seccomp profili `security_opt` ga MAZMUN sifatida qo'shiladi, yo'l sifatida emas.

    Docker CLI faylni o'zi o'qib mazmunini API'ga yuboradi, biz esa docker-py
    orqali to'g'ridan-to'g'ri API bilan gaplashamiz — API yo'lni JSON deb
    parse qilib `Decoding seccomp profile failed` xatosini beradi va
    konteyner UMUMAN ishga tushmaydi. Shu regressiyani qaytmasligi uchun test.
    """
    profile = tmp_path / "durabl-seccomp.json"
    profile.write_text(
        json.dumps({"defaultAction": "SCMP_ACT_ERRNO", "syscalls": []}),
        encoding="utf-8",
    )
    _read_seccomp_profile.cache_clear()
    monkeypatch.setattr(settings, "SANDBOX_SECCOMP_PROFILE", str(profile))

    options = to_docker_kwargs(make_limits(), runtime=RUNTIME)["security_opt"]
    seccomp = next(o for o in options if o.startswith("seccomp="))
    payload = seccomp.removeprefix("seccomp=")

    assert str(profile) not in seccomp, "yo'l uzatilgan — Docker API buni rad etadi"
    assert json.loads(payload)["defaultAction"] == "SCMP_ACT_ERRNO"
    _read_seccomp_profile.cache_clear()


def test_seccomp_profili_yoq_boslsa_tushunarli_xato(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Profil fayli yo'q bo'lsa jim o'tmaydi — `SandboxError` tashlanadi.

    Jim o'tkazish xavfsizlik qatlamini bildirmasdan o'chirib qo'ygan bo'lardi.
    """
    _read_seccomp_profile.cache_clear()
    monkeypatch.setattr(settings, "SANDBOX_SECCOMP_PROFILE", str(tmp_path / "yoq.json"))
    with pytest.raises(SandboxError, match="o'qilmadi"):
        to_docker_kwargs(make_limits(), runtime=RUNTIME)
    _read_seccomp_profile.cache_clear()


def test_seccomp_profili_yaroqsiz_json_boslsa_xato(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Yaroqsiz JSON ham ishga tushishdan oldin ushlanadi."""
    bad = tmp_path / "buzilgan.json"
    bad.write_text('{"defaultAction": ', encoding="utf-8")
    _read_seccomp_profile.cache_clear()
    monkeypatch.setattr(settings, "SANDBOX_SECCOMP_PROFILE", str(bad))
    with pytest.raises(SandboxError, match="yaroqli JSON emas"):
        to_docker_kwargs(make_limits(), runtime=RUNTIME)
    _read_seccomp_profile.cache_clear()


# ---------------------------------------------------------------------------
# to_docker_host_config
# ---------------------------------------------------------------------------


def test_to_docker_host_config_engine_nomlari() -> None:
    """Low-level API Docker Engine nomlarini kutadi (`Memory`, `NanoCpus`...)."""
    config = to_docker_host_config(make_limits(memory_mb=256, cpus=0.5, pids_limit=50))
    assert config["Memory"] == 256 * BYTES_PER_MB
    assert config["MemorySwap"] == config["Memory"]
    assert config["NanoCpus"] == int(0.5 * 1e9)
    assert config["PidsLimit"] == 50
    assert config["ReadonlyRootfs"] is True
    assert config["CapDrop"] == list(CAP_DROP_ALL)
    assert config["AutoRemove"] is False


def test_to_docker_host_config_ulimits_bosh_harfli() -> None:
    """`Ulimits` elementlari `Name`/`Soft`/`Hard` kalitlari bilan."""
    items = to_docker_host_config(make_limits())["Ulimits"]
    assert all(set(item) == {"Name", "Soft", "Hard"} for item in items)


# ---------------------------------------------------------------------------
# Hisoblangan qiymatlar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("disk_mb", "expected"),
    [(64, 256), (128, 512), (256, 1024), (1024, 4096)],
)
def test_nofile_limit_disk_kvotasidan(disk_mb: int, expected: int) -> None:
    """`nofile` = `disk_mb * 4` (sandbox siyosati bilan AYNAN mos)."""
    assert nofile_limit(make_limits(disk_mb=disk_mb)) == expected
    assert expected == disk_mb * NOFILE_PER_DISK_MB


def test_nofile_limit_pastki_chegarasi() -> None:
    """Juda kichik disk kvotasida ham kamida 64 fd beriladi."""
    assert nofile_limit(make_limits(disk_mb=1)) == 64


def test_nproc_limit_pastki_chegarasi() -> None:
    """`nproc` kamida 32 (interpretator ishga tushishi uchun)."""
    assert nproc_limit(make_limits(pids_limit=1)) == 32
    assert nproc_limit(make_limits(pids_limit=200)) == 200


def test_fsize_limit_baytga_aylantiriladi() -> None:
    """`fsize` megabaytdan baytga aylanadi."""
    assert fsize_limit_bytes(make_limits(disk_mb=64)) == 64 * BYTES_PER_MB


def test_tmpfs_mounts_pastki_chegarasi() -> None:
    """tmpfs hajmi hech qachon `0m` bo'lmaydi."""
    assert "size=1m" in tmpfs_mounts(make_limits(tmpfs_mb=0))[TMPFS_MOUNT]


def test_container_labels_minimal_holat() -> None:
    """Runtime va urinish berilmasa faqat majburiy yorliqlar qoladi."""
    labels = container_labels()
    assert labels == {LABEL_MANAGED: LABEL_MANAGED_VALUE, LABEL_JOB_ID: ""}


# ---------------------------------------------------------------------------
# to_rlimits / apply_rlimits
# ---------------------------------------------------------------------------


def _rlimit_names(limits: ResourceLimits) -> dict[int, tuple[int, int]]:
    """`to_rlimits()` natijasini `{limit_id: (soft, hard)}` ko'rinishiga keltiradi."""
    return dict(to_rlimits(limits))


def test_to_rlimits_majburiy_cheklovlar() -> None:
    """CPU, nofile, nproc, fsize va core dump cheklovlari bo'lishi kerak."""
    import resource as posix_resource

    limits = make_limits(timeout_seconds=7, disk_mb=64, pids_limit=50)
    pairs = _rlimit_names(limits)

    assert pairs[posix_resource.RLIMIT_CPU] == (7, 7)
    assert pairs[posix_resource.RLIMIT_NOFILE] == (256, 256)
    assert pairs[posix_resource.RLIMIT_FSIZE] == (64 * BYTES_PER_MB,) * 2
    assert pairs[posix_resource.RLIMIT_CORE] == (0, 0)


def test_to_rlimits_soft_hard_teng() -> None:
    """Har juftlikda `soft == hard` — bola limitni yumshata olmaydi."""
    assert all(soft == hard for soft, hard in _rlimit_names(make_limits()).values())


def test_to_rlimits_cpu_pastki_chegarasi() -> None:
    """`timeout_seconds=0` bo'lsa ham CPU limiti kamida 1 soniya."""
    import resource as posix_resource

    assert _rlimit_names(make_limits(timeout_seconds=0))[posix_resource.RLIMIT_CPU] == (1, 1)


def test_to_rlimits_as_faqat_linuxda() -> None:
    """`RLIMIT_AS` macOS'da QO'LLANMAYDI (interpretator ishga tushmaydi)."""
    import resource as posix_resource

    pairs = _rlimit_names(make_limits(memory_mb=256))
    if RLIMIT_AS_SUPPORTED:
        assert pairs[posix_resource.RLIMIT_AS] == (256 * BYTES_PER_MB,) * 2
    else:
        assert posix_resource.RLIMIT_AS not in pairs


def test_to_rlimits_node_uchun_as_QOYILMAYDI() -> None:
    """Node uchun `RLIMIT_AS` HECH QACHON qo'yilmaydi — platformadan qat'i nazar.

    ## Nega bu test bor

    Bu HAQIQIY xato bo'lgan va faqat Linux'da chiqqan. V8 ishga
    tushishida katta virtual manzil diapazonini oldindan zahiralaydi
    (bu RSS emas, faqat manzil maydoni), `RLIMIT_AS` esa aynan shu
    maydonni cheklaydi.

    Linux'da o'lchangan (`node v20`, `console.log("salom")`):

        RLIMIT_AS yo'q    -> exit 0
        RLIMIT_AS 256 MB  -> SIGTRAP, "Failed to reserve virtual memory
                             for CodeRange"
        RLIMIT_AS 512 MB  -> exit 0

    Standart `SANDBOX_MEMORY_MB` 256, FREE rejada xotira chegarasi ham
    256 — ya'ni Linux'da HAR QANDAY Node job'i mijoz kodiga yetib
    bormasdan o'lardi. macOS'da `RLIMIT_AS` qo'yilmagani uchun bu
    ko'rinmasdi va `tests/e2e/test_full_flow.py::test_node_runtime_executes`
    faqat CI'da (Linux) yiqilardi.

    Shu sababli tekshiruv platformaga BOG'LIQ EMAS: `None` bo'lsin,
    Linux bo'lsin — Node uchun limit bo'lmasligi SHART.
    """
    import resource as posix_resource

    pairs = dict(to_rlimits(make_limits(memory_mb=256), runtime=Runtime.NODE))
    assert posix_resource.RLIMIT_AS not in pairs
    # Qolgan cheklovlar o'z joyida — faqat `RLIMIT_AS` chiqarib tashlanadi.
    assert posix_resource.RLIMIT_CPU in pairs
    assert posix_resource.RLIMIT_NOFILE in pairs


def test_to_rlimits_python_uchun_as_saqlanadi() -> None:
    """Python uchun `RLIMIT_AS` SAQLANADI (Linux'da).

    CPython 256 MB virtual manzilga sig'adi (o'lchangan), shuning uchun
    Node uchun qo'yilgan istisno Python'ga TARQALMASLIGI kerak — aks
    holda himoya sababsiz yo'qolardi.
    """
    import resource as posix_resource

    pairs = dict(to_rlimits(make_limits(memory_mb=256), runtime=Runtime.PYTHON))
    if RLIMIT_AS_SUPPORTED:
        assert pairs[posix_resource.RLIMIT_AS] == (256 * BYTES_PER_MB,) * 2
    else:
        assert posix_resource.RLIMIT_AS not in pairs


def test_to_rlimits_runtime_berilmasa_eng_qatiy_variant() -> None:
    """`runtime=None` — limit QO'LLANADI (noma'lum holatda qat'iyroq tomon)."""
    import resource as posix_resource

    pairs = dict(to_rlimits(make_limits(memory_mb=256), runtime=None))
    assert (posix_resource.RLIMIT_AS in pairs) is RLIMIT_AS_SUPPORTED


def test_apply_rlimits_funksiya_qaytaradi() -> None:
    """`apply_rlimits` — `preexec_fn` uchun argumentsiz funksiya."""
    preexec = apply_rlimits(make_limits())
    assert callable(preexec)


def test_apply_rlimits_setrlimit_chaqiradi(monkeypatch: pytest.MonkeyPatch) -> None:
    """Qaytgan funksiya har bir juftlik uchun `setrlimit()` chaqiradi."""
    import resource as posix_resource

    calls: list[tuple[int, tuple[int, int]]] = []

    def fake_setrlimit(limit_id: int, values: tuple[int, int]) -> None:
        calls.append((limit_id, values))

    def fake_getrlimit(_limit_id: int) -> tuple[int, int]:
        return (posix_resource.RLIM_INFINITY, posix_resource.RLIM_INFINITY)

    monkeypatch.setattr(posix_resource, "setrlimit", fake_setrlimit)
    monkeypatch.setattr(posix_resource, "getrlimit", fake_getrlimit)

    limits = make_limits()
    apply_rlimits(limits)()

    assert len(calls) == len(to_rlimits(limits))
    assert dict(calls) == _rlimit_names(limits)


def test_apply_rlimits_xatoni_yutadi(monkeypatch: pytest.MonkeyPatch) -> None:
    """`setrlimit` ruxsat bermasa bajarish TO'XTAMAYDI (fork'dan keyin xato xavfli)."""
    import resource as posix_resource

    def failing_setrlimit(*_args: Any) -> None:
        raise OSError("ruxsat yo'q")

    monkeypatch.setattr(posix_resource, "setrlimit", failing_setrlimit)
    apply_rlimits(make_limits())()  # xato tashlanmasligi kerak


def test_apply_rlimits_resource_moduli_yoq(monkeypatch: pytest.MonkeyPatch) -> None:
    """`resource` moduli bo'lmagan tizimda (Windows) bo'sh ro'yxat va jim ishlash."""
    monkeypatch.setattr(resource_limiter, "resource", None)
    assert to_rlimits(make_limits()) == []
    apply_rlimits(make_limits())()


# ---------------------------------------------------------------------------
# to_sandbox_env
# ---------------------------------------------------------------------------


def test_to_sandbox_env_entrypoint_ozgaruvchilari() -> None:
    """Entrypoint o'qiydigan barcha o'zgaruvchilar matn ko'rinishida."""
    env = to_sandbox_env(make_limits(timeout_seconds=9, max_output_bytes=1024))
    assert env["DURABL_SANDBOX_TIMEOUT_SECONDS"] == "9"
    assert env["DURABL_MAX_OUTPUT_BYTES"] == "1024"
    assert env["DURABL_RLIMITS_ENABLED"] == "1"
    assert env["DURABL_SANDBOX_RESULT_FILENAME"] == "result.json"
    assert all(isinstance(value, str) for value in env.values())


def test_to_sandbox_env_runtime_va_workdir_ixtiyoriy() -> None:
    """Runtime/workdir berilsa qo'shimcha o'zgaruvchilar paydo bo'ladi."""
    base = to_sandbox_env(make_limits())
    assert "DURABL_SANDBOX_CODE_FILENAME" not in base
    full = to_sandbox_env(make_limits(), runtime=RUNTIME, workdir="/sandbox")
    assert full["DURABL_SANDBOX_CODE_FILENAME"] == "main.py"
    assert full["DURABL_SANDBOX_WORKDIR"] == "/sandbox"


# ---------------------------------------------------------------------------
# limits_summary
# ---------------------------------------------------------------------------


def test_limits_summary_hisoblangan_qiymatlarni_ham_beradi() -> None:
    """Log va API uchun yassi ko'rinish — `rlimit_*` qiymatlari bilan."""
    summary = limits_summary(make_limits(disk_mb=64))
    assert summary["rlimit_nofile"] == 256
    assert summary["network_mode"] == settings.SANDBOX_NETWORK_MODE
    assert summary["rlimit_as_applied"] is RLIMIT_AS_SUPPORTED
    assert set(summary) >= {"memory_mb", "cpus", "pids_limit", "timeout_seconds"}


def test_limits_summary_json_ga_mos_turlar() -> None:
    """Barcha qiymatlar oddiy turlar (JSON javobiga to'g'ridan-to'g'ri ketadi)."""
    for value in limits_summary(make_limits()).values():
        assert isinstance(value, int | float | str | bool)
