"""Durabl — `app/utils/validators.py` birlik testlari.

Modul ikki mustaqil mas'uliyatni bajaradi, shuning uchun test ham ikki
bo'limga ajralgan:

1. **Mijoz kodining statik tahlili.** Bu xavfsizlikning IKKINCHI qatlami
   (asosiysi — gVisor sandbox), shuning uchun standart rejimda topilmalar
   faqat OGOHLANTIRISH. Sintaksis xatosi esa har doim xato — mijozga
   30 soniya kutib "SyntaxError" olishdan ko'ra darhol aytish yaxshi.
2. **SSRF himoyasi** (`validate_webhook_url`). Mijoz `http://169.254.169.254/`
   bergan bo'lsa, serverimiz o'z cloud metadata'siga so'rov yuborib,
   javobni mijozga qaytarib yuborardi — ya'ni IAM kaliti o'g'irlanardi.

DNS: barcha bloklangan manzillar IP literal yoki nomi bo'yicha ro'yxatda,
shuning uchun tarmoq kerak bo'lmaydi. Faqat "halol URL o'tadi" testida
resolver `monkeypatch` bilan almashtiriladi — CI tarmoqsiz bo'lsa ham
natija AYNI bo'lishi uchun.
"""

from __future__ import annotations

import socket
from typing import Any

import pytest
from app.config import settings
from app.constants import (
    MAX_ENV_VALUE_LENGTH,
    MAX_ENV_VARS,
    MAX_TAG_LENGTH,
    MAX_TAGS,
    Runtime,
)
from app.exceptions import (
    CodeSyntaxError,
    CodeValidationError,
    PayloadTooLargeError,
    UnsupportedRuntimeError,
    ValidationError,
    WebhookUrlNotAllowedError,
)
from app.utils.validators import (
    assert_code_safe,
    inspect_code,
    next_cron_time,
    validate_code,
    validate_code_size,
    validate_cron,
    validate_env_vars,
    validate_payload_size,
    validate_retries,
    validate_runtime,
    validate_tags,
    validate_timeout,
    validate_webhook_url,
)

pytestmark = pytest.mark.unit

SAFE_PYTHON = "def main(payload):\n    total = sum(payload.get('items', []))\n    return total\n"
SAFE_NODE = "export default function main(payload) {\n  return payload.a + payload.b;\n}\n"


@pytest.fixture
def public_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """DNS resolverni almashtiradi: har qanday nom ommaviy IP'ga yechiladi.

    Tarmoqqa chiqmasdan "halol URL o'tadi" holatini tekshirish uchun.
    """

    def fake_getaddrinfo(host: str, port: Any, **_kwargs: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port or 443))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)


# ---------------------------------------------------------------------------
# validate_runtime
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("python", Runtime.PYTHON),
        ("PYTHON", Runtime.PYTHON),
        ("  node  ", Runtime.NODE),
        (Runtime.NODE, Runtime.NODE),
    ],
)
def test_validate_runtime_qabul_qiladi(value: str | Runtime, expected: Runtime) -> None:
    """Matn registri va bo'sh joy ahamiyatsiz."""
    assert validate_runtime(value) is expected


@pytest.mark.parametrize("value", ["ruby", "", "py"])
def test_validate_runtime_notanish_muhit(value: str) -> None:
    """Noma'lum runtime `UnsupportedRuntimeError` beradi."""
    with pytest.raises(UnsupportedRuntimeError):
        validate_runtime(value)


# ---------------------------------------------------------------------------
# Python kodi — xavfsiz namunalar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        SAFE_PYTHON,
        "import json\n\ndef main(payload):\n    return json.dumps(payload)\n",
        "import math, datetime\n\ndef main(p):\n    return math.pi\n",
        "from collections import Counter\n\ndef main(p):\n    return dict(Counter(p))\n",
        "def main(p):\n    with open('/tmp/x.txt') as handle:\n        return handle.read()\n",
    ],
)
def test_python_xavfsiz_kod_toza(code: str) -> None:
    """Halol kod bejiz bloklanmaydi (false positive bo'lmaydi)."""
    assert validate_code(code, Runtime.PYTHON) == []


# ---------------------------------------------------------------------------
# Python kodi — xavfli namunalar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("code", "kalit_soz"),
    [
        ("import subprocess\n", "subprocess"),
        ("import ctypes\n", "ctypes"),
        ("import multiprocessing as mp\n", "multiprocessing"),
        ("from subprocess import run\n", "subprocess"),
        ("import subprocess.run\n", "subprocess"),
        ("eval('1+1')\n", "eval"),
        ("exec('x = 1')\n", "exec"),
        ("compile('x', '<s>', 'exec')\n", "compile"),
        ("__import__('os')\n", "__import__"),
        ("import importlib\nimportlib.import_module('os')\n", "import_module"),
        ("import os\nos.system('ls')\n", "os.system"),
        ("open('/etc/passwd', 'w')\n", "open"),
        ("open('/tmp/x', mode='a')\n", "open"),
    ],
)
def test_python_xavfli_kod_topiladi(code: str, kalit_soz: str) -> None:
    """Taqiqlangan import/chaqiruv buzilishlar ro'yxatiga tushadi."""
    violations = validate_code(code, Runtime.PYTHON)
    assert violations, f"buzilish topilmadi: {code!r}"
    assert any(kalit_soz in message for message in violations)


def test_python_buzilish_qator_raqami_bilan() -> None:
    """Xabar qator raqamini ko'rsatadi — mijoz tez topadi."""
    code = "x = 1\ny = 2\nimport subprocess\n"
    assert validate_code(code, Runtime.PYTHON)[0].startswith("3-qator:")


def test_python_takroriy_buzilish_bir_marta() -> None:
    """Ayni qatordagi ayni buzilish ro'yxatda takrorlanmaydi."""
    code = "import subprocess\nimport subprocess\n"
    assert len(validate_code(code, Runtime.PYTHON)) == 2  # ikki TURLI qator


# ---------------------------------------------------------------------------
# Sintaksis xatosi
# ---------------------------------------------------------------------------


def test_python_sintaksis_xatosi_aniqlanadi() -> None:
    """Sintaksis xatosi `CodeInspection.syntax_error` ga tushadi."""
    inspection = inspect_code("def main(:\n", Runtime.PYTHON)
    assert inspection.has_syntax_error is True
    assert inspection.is_clean is False
    assert "sintaksis xatosi" in (inspection.syntax_error or "")


def test_python_sintaksis_xatosi_har_doim_xato() -> None:
    """STRICT o'chirilgan bo'lsa ham sintaksis xatosi so'rovni rad etadi."""
    assert settings.CODE_VALIDATION_STRICT is False
    with pytest.raises(CodeSyntaxError):
        assert_code_safe("def main(\n", Runtime.PYTHON)


def test_python_sintaksis_xatosi_messages_birinchi_orinda() -> None:
    """`messages` ro'yxatida sintaksis xatosi birinchi turadi."""
    messages = validate_code("import subprocess\ndef main(:\n", Runtime.PYTHON)
    assert "sintaksis" in messages[0]


# ---------------------------------------------------------------------------
# STRICT rejimi
# ---------------------------------------------------------------------------


def test_strict_ochirilganda_xato_tashlanmaydi() -> None:
    """Standart rejim: buzilish faqat ogohlantirish, job qabul qilinadi."""
    assert_code_safe("import subprocess\n", Runtime.PYTHON)


def test_strict_yoqilganda_xato_tashlanadi(monkeypatch: pytest.MonkeyPatch) -> None:
    """`CODE_VALIDATION_STRICT=True` — buzilish job'ni rad etadi."""
    monkeypatch.setattr(settings, "CODE_VALIDATION_STRICT", True)
    with pytest.raises(CodeValidationError) as info:
        assert_code_safe("import ctypes\n", Runtime.PYTHON)
    assert info.value.details is not None


def test_validatsiya_ochirilganda_tahlil_yoq(monkeypatch: pytest.MonkeyPatch) -> None:
    """`CODE_VALIDATION_ENABLED=False` — hatto sintaksis ham tekshirilmaydi."""
    monkeypatch.setattr(settings, "CODE_VALIDATION_ENABLED", False)
    assert validate_code("import subprocess\ndef main(:\n", Runtime.PYTHON) == []
    assert_code_safe("def main(:\n", Runtime.PYTHON)


# ---------------------------------------------------------------------------
# Node kodi
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    [
        SAFE_NODE,
        "import fs from 'node:fs';\nexport default (p) => fs.readFileSync('/tmp/a');\n",
        "const path = require('path');\nmodule.exports = () => path.join('a', 'b');\n",
    ],
)
def test_node_xavfsiz_kod_toza(code: str) -> None:
    """Halol Node kodi toza o'tadi (o'qish va `path` ruxsat etilgan)."""
    assert validate_code(code, Runtime.NODE) == []


@pytest.mark.parametrize(
    ("code", "kalit_soz"),
    [
        ("const cp = require('child_process');\n", "child_process"),
        ("import cp from 'node:child_process';\n", "child_process"),
        ("const { Worker } = require('worker_threads');\n", "worker_threads"),
        ("await import('vm');\n", "vm"),
        ("require('cluster');\n", "cluster"),
        ("eval('1+1');\n", "eval"),
        ("const f = new Function('return 1');\n", "new Function"),
        ("process.binding('fs');\n", "process.binding"),
        ("const r = createRequire(import.meta.url);\n", "createRequire"),
        ("fs.writeFileSync('/etc/x', 'y');\n", "faylga yozish"),
        ("fs.promises.unlink('/tmp/x');\n", "faylga yozish"),
    ],
)
def test_node_xavfli_kod_topiladi(code: str, kalit_soz: str) -> None:
    """Taqiqlangan modul va dinamik kod bajarish aniqlanadi."""
    violations = validate_code(code, Runtime.NODE)
    assert violations, f"buzilish topilmadi: {code!r}"
    assert any(kalit_soz in message for message in violations)


def test_node_sintaksisi_tekshirilmaydi() -> None:
    """Node uchun JS parser yo'q — buzilgan sintaksis `syntax_error` bermaydi."""
    inspection = inspect_code("function main( {", Runtime.NODE)
    assert inspection.has_syntax_error is False


# ---------------------------------------------------------------------------
# Kod hajmi
# ---------------------------------------------------------------------------


def test_validate_code_size_chegarada_otadi() -> None:
    """Chegaraga teng hajm qabul qilinadi."""
    validate_code_size("a" * settings.MAX_CODE_SIZE_BYTES)


def test_validate_code_size_oshsa_xato() -> None:
    """Chegaradan katta kod `PayloadTooLargeError` beradi."""
    with pytest.raises(PayloadTooLargeError):
        validate_code_size("a" * (settings.MAX_CODE_SIZE_BYTES + 1))


def test_validate_code_size_baytlar_boyicha_hisoblanadi() -> None:
    """Hajm BELGI emas, BAYT bo'yicha (ko'p baytli matn uchun muhim)."""
    big = "ё" * (settings.MAX_CODE_SIZE_BYTES // 2 + 1)  # har biri 2 bayt
    with pytest.raises(PayloadTooLargeError):
        validate_code_size(big)


def test_validate_code_size_bosh_kod() -> None:
    """Bo'sh kod hajm bo'yicha o'tadi (mazmuni boshqa joyda tekshiriladi)."""
    validate_code_size("")


# ---------------------------------------------------------------------------
# Payload hajmi
# ---------------------------------------------------------------------------


def test_validate_payload_size_none_otadi() -> None:
    """Payload yo'q bo'lsa tekshiruv o'tkazilmaydi."""
    validate_payload_size(None)


def test_validate_payload_size_kichik_payload() -> None:
    """Oddiy payload chegaraga sig'adi."""
    validate_payload_size({"items": list(range(100))})


def test_validate_payload_size_oshsa_xato() -> None:
    """Chegaradan katta payload rad etiladi."""
    with pytest.raises(PayloadTooLargeError):
        validate_payload_size({"blob": "a" * (settings.MAX_PAYLOAD_SIZE_BYTES + 10)})


def test_validate_payload_size_xato_tafsilotlari() -> None:
    """Xato hajm va chegarani ko'rsatadi (mijoz nima qilishni biladi)."""
    with pytest.raises(PayloadTooLargeError) as info:
        validate_payload_size({"blob": "a" * (settings.MAX_PAYLOAD_SIZE_BYTES + 10)})
    details = info.value.details or {}
    assert details.get("limit_bytes") == settings.MAX_PAYLOAD_SIZE_BYTES
    assert details.get("size_bytes", 0) > settings.MAX_PAYLOAD_SIZE_BYTES


# ---------------------------------------------------------------------------
# SSRF — bloklangan manzillar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/hook",
        "http://localhost:6379/hook",  # bizning Redis
        "http://127.0.0.1/hook",
        "http://127.0.0.1:5432/hook",  # bizning PostgreSQL
        "http://[::1]/hook",
        "http://169.254.169.254/latest/meta-data/",  # AWS metadata
        "http://metadata.google.internal/computeMetadata/v1/",
        "http://metadata/",
        "http://instance-data/",
        "http://10.0.0.5/hook",
        "http://192.168.1.10/hook",
        "http://172.16.0.1/hook",
        "http://0.0.0.0/hook",
        "http://db.internal/hook",
        "http://api.local/hook",
        "http://service.localhost/hook",
    ],
)
def test_webhook_url_ichki_manzil_bloklanadi(url: str) -> None:
    """Ichki/mahalliy/metadata manzillari rad etiladi."""
    with pytest.raises(WebhookUrlNotAllowedError):
        validate_webhook_url(url)


def test_webhook_url_nuqta_bilan_tugagan_host_ham_bloklanadi() -> None:
    """`localhost.` (absolyut DNS nomi) ham bloklanadi."""
    with pytest.raises(WebhookUrlNotAllowedError):
        validate_webhook_url("http://localhost./hook")


def test_webhook_url_registr_ahamiyatsiz() -> None:
    """Host nomi katta harf bilan yozilsa ham bloklanadi."""
    with pytest.raises(WebhookUrlNotAllowedError):
        validate_webhook_url("http://LocalHost/hook")


@pytest.mark.parametrize("url", ["ftp://example.com/x", "file:///etc/passwd", "gopher://x/1"])
def test_webhook_url_notogri_sxema(url: str) -> None:
    """Faqat `http`/`https` ruxsat etilgan."""
    with pytest.raises(WebhookUrlNotAllowedError):
        validate_webhook_url(url)


def test_webhook_url_login_parol_bilan_bloklanadi(public_dns: None) -> None:
    """URL'da kredensial bo'lishi mumkin emas (log'ga tushib ketadi)."""
    with pytest.raises(WebhookUrlNotAllowedError):
        validate_webhook_url("https://user:pass@example.com/hook")


@pytest.mark.parametrize("url", ["", "   ", "https://", "not-a-url"])
def test_webhook_url_yaroqsiz_shakl(url: str) -> None:
    """Bo'sh yoki hostsiz URL `ValidationError` beradi."""
    with pytest.raises(ValidationError):
        validate_webhook_url(url)


def test_webhook_url_juda_uzun() -> None:
    """2048 belgidan uzun URL rad etiladi (DB ustuni ham shu hajmda)."""
    with pytest.raises(ValidationError):
        validate_webhook_url("https://example.com/" + "a" * 2100)


# ---------------------------------------------------------------------------
# SSRF — ruxsat etilgan manzillar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/hook",
        "http://example.com/durabl/webhook?x=1",
        "https://hooks.example.com:8443/path",
    ],
)
def test_webhook_url_ommaviy_manzil_otadi(url: str, public_dns: None) -> None:
    """Halol ommaviy URL qabul qilinadi."""
    validate_webhook_url(url)


def test_webhook_url_ommaviy_ip_otadi() -> None:
    """Ommaviy IP literal ham qabul qilinadi (DNS kerak emas)."""
    validate_webhook_url("https://93.184.216.34/hook")


def test_webhook_url_himoya_ochirilganda_ichki_manzil_otadi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`WEBHOOK_BLOCK_PRIVATE_IPS=False` — lokal ishlab chiqish rejimi."""
    monkeypatch.setattr(settings, "WEBHOOK_BLOCK_PRIVATE_IPS", False)
    validate_webhook_url("http://localhost:3000/hook")


def test_webhook_url_require_resolution_yechilmasa_xato(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Qat'iy rejimda DNS yechilmasa URL rad etiladi (fail-closed)."""

    def failing_getaddrinfo(*_args: Any, **_kwargs: Any) -> list[Any]:
        raise OSError("DNS javob bermadi")

    monkeypatch.setattr(socket, "getaddrinfo", failing_getaddrinfo)
    with pytest.raises(WebhookUrlNotAllowedError):
        validate_webhook_url("https://example.com/hook", require_resolution=True)


def test_webhook_url_dns_ichki_ipga_yechilsa_bloklanadi(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """KRITIK: DNS rebinding — nom halol, lekin IP ichki."""

    def internal_getaddrinfo(host: str, port: Any, **_kwargs: Any) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", port or 80))]

    monkeypatch.setattr(socket, "getaddrinfo", internal_getaddrinfo)
    with pytest.raises(WebhookUrlNotAllowedError):
        validate_webhook_url("https://evil.example.com/hook")


# ---------------------------------------------------------------------------
# Cron
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "expression",
    ["* * * * *", "0 0 * * *", "*/5 * * * *", "0 9 1 * 1", "0 0 0 * * *", "@daily", "@HOURLY"],
)
def test_validate_cron_togri_ifodalar(expression: str) -> None:
    """5/6 maydonli ifodalar va taxalluslar qabul qilinadi."""
    validate_cron(expression)


@pytest.mark.parametrize(
    "expression",
    ["", "   ", "* * *", "* * * * * * *", "@har-kuni", "99 * * * *", "salom"],
)
def test_validate_cron_notogri_ifodalar(expression: str) -> None:
    """Maydon soni, taxallus yoki qiymat noto'g'ri bo'lsa xato."""
    with pytest.raises(ValidationError):
        validate_cron(expression)


def test_validate_cron_juda_uzun() -> None:
    """100 belgidan uzun ifoda rad etiladi (DB ustuni chegarasi)."""
    with pytest.raises(ValidationError):
        validate_cron("*" + " *" * 200)


def test_next_cron_time_kelajakdagi_vaqt() -> None:
    """Keyingi bajarish vaqti berilgan bazadan KEYIN va UTC."""
    from datetime import UTC, datetime

    base = datetime(2026, 10, 4, 12, 30, 0, tzinfo=UTC)
    upcoming = next_cron_time("0 * * * *", base)
    assert upcoming == datetime(2026, 10, 4, 13, 0, 0, tzinfo=UTC)
    assert upcoming.tzinfo is not None


def test_next_cron_time_yaroqsiz_ifoda() -> None:
    """Yaroqsiz ifoda uchun vaqt hisoblanmaydi."""
    with pytest.raises(ValidationError):
        next_cron_time("notogri")


# ---------------------------------------------------------------------------
# Teglar
# ---------------------------------------------------------------------------


def test_validate_tags_none_bosh_royxat() -> None:
    """`None` -> bo'sh ro'yxat."""
    assert validate_tags(None) == []


def test_validate_tags_tozalaydi_va_takrorni_olib_tashlaydi() -> None:
    """Bo'sh joy kesiladi, bo'sh teg tashlanadi, takror birlashtiriladi."""
    assert validate_tags([" alpha ", "beta", "alpha", "", "   "]) == ["alpha", "beta"]


@pytest.mark.parametrize("tag", ["a", "A1", "job.daily", "team_core", "env:prod", "x-y"])
def test_validate_tags_ruxsat_etilgan_belgilar(tag: str) -> None:
    """Harf/raqam bilan boshlanadigan va `. _ : -` saqlagan teg o'tadi."""
    assert validate_tags([tag]) == [tag]


@pytest.mark.parametrize("tag", ["-boshlanish", ".nuqta", "bo'sh joy", "teg!", "#hash", ":a"])
def test_validate_tags_notogri_shakl(tag: str) -> None:
    """Shabloniga mos kelmagan teg rad etiladi."""
    with pytest.raises(ValidationError):
        validate_tags([tag])


def test_validate_tags_juda_uzun_teg() -> None:
    """Teg uzunligi `MAX_TAG_LENGTH` dan oshmasligi kerak."""
    with pytest.raises(ValidationError):
        validate_tags(["a" * (MAX_TAG_LENGTH + 1)])


def test_validate_tags_chegaradagi_uzunlik_otadi() -> None:
    """Aynan chegaraga teng uzunlik qabul qilinadi."""
    tag = "a" * MAX_TAG_LENGTH
    assert validate_tags([tag]) == [tag]


def test_validate_tags_soni_cheklanadi() -> None:
    """Teglar soni `MAX_TAGS` dan oshmasligi kerak."""
    with pytest.raises(ValidationError):
        validate_tags([f"tag{index}" for index in range(MAX_TAGS + 1)])


def test_validate_tags_matn_royxat_emas() -> None:
    """Matn uzatilsa xato (aks holda har bir HARF teg bo'lib ketardi)."""
    with pytest.raises(ValidationError):
        validate_tags("alpha")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Muhit o'zgaruvchilari
# ---------------------------------------------------------------------------


def test_validate_env_vars_bosh_qiymat() -> None:
    """`None` va bo'sh lug'at -> bo'sh lug'at."""
    assert validate_env_vars(None) == {}
    assert validate_env_vars({}) == {}


def test_validate_env_vars_oddiy_qiymatlar() -> None:
    """Halol nomlar o'tadi, qiymatlar matnga aylanadi."""
    assert validate_env_vars({"API_URL": "https://x", "RETRIES": 3}) == {
        "API_URL": "https://x",
        "RETRIES": "3",
    }


def test_validate_env_vars_none_qiymat_bosh_matn() -> None:
    """`None` qiymat bo'sh matnga aylanadi (o'zgaruvchi baribir mavjud)."""
    assert validate_env_vars({"FLAG": None}) == {"FLAG": ""}


@pytest.mark.parametrize("name", ["1BAD", "bo'sh joy", "A-B", "", "A.B", "A$"])
def test_validate_env_vars_notogri_nom(name: str) -> None:
    """Nom `[A-Za-z_][A-Za-z0-9_]*` shabloniga mos bo'lishi kerak."""
    with pytest.raises(ValidationError):
        validate_env_vars({name: "x"})


@pytest.mark.parametrize(
    "name",
    ["PATH", "path", "Path", "LD_PRELOAD", "ld_preload", "PYTHONPATH", "NODE_OPTIONS", "HOME"],
)
def test_validate_env_vars_taqiqlangan_nom_registrsiz(name: str) -> None:
    """KRITIK: taqiqlangan nom REGISTRDAN QAT'I NAZAR bloklanadi."""
    with pytest.raises(ValidationError):
        validate_env_vars({name: "/evil"})


@pytest.mark.parametrize("name", ["DURABL_JOB_ID", "durabl_x", "DYLD_INSERT_LIBRARIES"])
def test_validate_env_vars_taqiqlangan_prefiks(name: str) -> None:
    """`LD_`, `DYLD_`, `DURABL_` prefikslari ham bloklanadi."""
    with pytest.raises(ValidationError):
        validate_env_vars({name: "x"})


def test_validate_env_vars_soni_cheklanadi() -> None:
    """O'zgaruvchilar soni `MAX_ENV_VARS` dan oshmaydi."""
    env = {f"VAR_{index}": "x" for index in range(MAX_ENV_VARS + 1)}
    with pytest.raises(ValidationError):
        validate_env_vars(env)


def test_validate_env_vars_qiymat_uzunligi() -> None:
    """Qiymat `MAX_ENV_VALUE_LENGTH` dan uzun bo'lmasligi kerak."""
    with pytest.raises(ValidationError):
        validate_env_vars({"BIG": "a" * (MAX_ENV_VALUE_LENGTH + 1)})


def test_validate_env_vars_nul_bayt_taqiqlangan() -> None:
    """NUL bayt `execve()` ni buzadi — qiymatda bo'lishi mumkin emas."""
    with pytest.raises(ValidationError):
        validate_env_vars({"EVIL": "a\x00b"})


def test_validate_env_vars_lugat_bolmasa_xato() -> None:
    """Lug'at bo'lmagan qiymat rad etiladi."""
    with pytest.raises(ValidationError):
        validate_env_vars([("A", "1")])  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Timeout va retry
# ---------------------------------------------------------------------------


def test_validate_timeout_none_standart_qiymat() -> None:
    """`None` -> sozlamadagi standart timeout."""
    assert validate_timeout(None) == settings.DEFAULT_TIMEOUT_SECONDS


@pytest.mark.parametrize("value", [1, 30, 100, 900])
def test_validate_timeout_chegara_ichida(value: int) -> None:
    """Chegara ichidagi qiymat o'zgarmaydi."""
    assert validate_timeout(value) == value


@pytest.mark.parametrize("value", [0, -5, 901, 10_000])
def test_validate_timeout_chegaradan_tashqari(value: int) -> None:
    """Chegaradan tashqari qiymat `ValidationError` beradi."""
    with pytest.raises(ValidationError):
        validate_timeout(value)


def test_validate_timeout_reja_chegarasi() -> None:
    """Reja chegarasi global chegaradan ustun turadi (FREE: 30 soniya)."""
    assert validate_timeout(30, max_allowed=30) == 30
    with pytest.raises(ValidationError):
        validate_timeout(60, max_allowed=30)


def test_validate_timeout_float_butun_songa_keltiriladi() -> None:
    """Float qiymat butun songa aylanadi."""
    assert validate_timeout(10.7) == 10


def test_validate_timeout_bool_qabul_qilinmaydi() -> None:
    """`True` Python'da `1` ga teng, lekin timeout emas."""
    with pytest.raises(ValidationError):
        validate_timeout(True)


def test_validate_retries_none_standart() -> None:
    """`None` -> sozlamadagi standart urinishlar soni."""
    assert validate_retries(None) == settings.DEFAULT_MAX_RETRIES


@pytest.mark.parametrize("value", [0, 1, 5, 10])
def test_validate_retries_chegara_ichida(value: int) -> None:
    """0..`MAX_ALLOWED_RETRIES` oralig'i qabul qilinadi."""
    assert validate_retries(value) == value


@pytest.mark.parametrize("value", [-1, 11, 1000])
def test_validate_retries_chegaradan_tashqari(value: int) -> None:
    """Manfiy yoki juda katta qiymat rad etiladi."""
    with pytest.raises(ValidationError):
        validate_retries(value)


def test_validate_retries_reja_chegarasi() -> None:
    """`max_allowed` orqali rejaga xos chegara qo'llanadi."""
    assert validate_retries(2, max_allowed=2) == 2
    with pytest.raises(ValidationError):
        validate_retries(5, max_allowed=2)


def test_validate_retries_bool_qabul_qilinmaydi() -> None:
    """`True` butun son emas — rad etiladi."""
    with pytest.raises(ValidationError):
        validate_retries(True)
