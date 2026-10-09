"""Durabl — kirish ma'lumotlari va mijoz kodining validatsiyasi.

**Eng muhim tushuncha:** bu modul xavfsizlikning *ikkinchi* qatlami. Asosiy
himoya — gVisor sandbox (`--network=none`, read-only FS, seccomp, resurs
limitlari). Statik tahlil mijoz kodini hech qachon to'liq "xavfsiz" deb
kafolatlay olmaydi (`getattr(__builtins__, "ev" + "al")` kabi usullar bor),
shuning uchun:

* `CODE_VALIDATION_STRICT=False` (standart) — topilgan importlar/chaqiruvlar
  faqat **ogohlantirish**: ular qaytariladi, log qilinadi, lekin job rad
  etilmaydi. Shu tufayli halol kod bejiz bloklanmaydi.
* `CODE_VALIDATION_STRICT=True` — har qanday buzilish **xato** (`CodeValidationError`).
* **Sintaksis xatosi har doim xato** — bu xavfsizlik emas, mijozga tezkor
  qaytarma: kodni sandbox'ga yuborib 30 soniya kutishdan ko'ra darhol
  aytish yaxshi.
* `CODE_VALIDATION_ENABLED=False` — tekshiruv butunlay o'chadi.

Ikkinchi yirik mas'uliyat — **SSRF himoyasi** (`validate_webhook_url`): mijoz
webhook URL sifatida `http://169.254.169.254/...` (cloud metadata) yoki
`http://localhost:6379` (bizning Redis) berib, serverimizni o'zi uchun
so'rov yuborishga majburlay olmasligi kerak. Shu sababli DNS nomi IP'ga
yechiladi va hosil bo'lgan IP ham tekshiriladi (DNS rebinding).
"""

from __future__ import annotations

import ast
import asyncio
import ipaddress
import re
import socket
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from ipaddress import IPv4Address, IPv6Address
from typing import Any, Final
from urllib.parse import urlsplit

from croniter import CroniterError, croniter

from app.config import settings
from app.constants import (
    ENV_NAME_PATTERN,
    MAX_ENV_VALUE_LENGTH,
    NODE_FORBIDDEN_MODULES,
    PYTHON_FORBIDDEN_IMPORTS,
    Runtime,
)
from app.constants import MAX_ENV_VARS as _MAX_ENV_VARS
from app.constants import MAX_TAG_LENGTH as _MAX_TAG_LENGTH
from app.constants import MAX_TAGS as _MAX_TAGS
from app.exceptions import (
    CodeSyntaxError,
    CodeValidationError,
    PayloadTooLargeError,
    UnsupportedRuntimeError,
    ValidationError,
    WebhookUrlNotAllowedError,
)
from app.utils.serializers import serialize_payload
from app.utils.time_utils import ensure_utc, utcnow

# ---------------------------------------------------------------------------
# Konstantalar
# ---------------------------------------------------------------------------

#: Python'da to'g'ridan-to'g'ri chaqirilishi xavfli nomlar (dinamik kod bajarish).
PYTHON_FORBIDDEN_CALLS: frozenset[str] = frozenset({"eval", "exec", "compile", "__import__"})

#: Nuqtali ko'rinishda xavfli chaqiruvlar (`os.system(...)` kabi).
PYTHON_FORBIDDEN_ATTRIBUTE_CALLS: frozenset[str] = frozenset(
    {
        "builtins.eval",
        "builtins.exec",
        "builtins.compile",
        "builtins.__import__",
        "importlib.import_module",
        "os.execl",
        "os.execv",
        "os.execve",
        "os.execvp",
        "os.fork",
        "os.forkpty",
        "os.kill",
        "os.popen",
        "os.spawnl",
        "os.spawnv",
        "os.system",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "subprocess.getoutput",
        "subprocess.run",
    }
)

#: `open(..., mode)` ichida yozishni bildiruvchi belgilar.
WRITE_FILE_MODE_CHARS: Final = ("w", "a", "x", "+")

#: Tag cheklovlari (`Job.tags`).
MAX_TAGS: Final = _MAX_TAGS
MAX_TAG_LENGTH: Final = _MAX_TAG_LENGTH

#: Muhit o'zgaruvchilari cheklovlari (`Job.env_vars`).
MAX_ENV_VARS: Final = _MAX_ENV_VARS
# `MAX_ENV_VALUE_LENGTH` va `MAX_ENV_NAME_LENGTH` `app.constants` dan import
# qilinadi (yuqoriga qarang) — bu yerda qayta e'lon qilinmaydi.

#: Webhook URL va cron ifodasi uzunligi (DB ustunlari bilan mos).
MAX_WEBHOOK_URL_LENGTH: Final = 2_048
MAX_CRON_LENGTH: Final = 100

#: Sandbox muhitini buzishi mumkin bo'lgan muhit o'zgaruvchilari.
FORBIDDEN_ENV_NAMES: frozenset[str] = frozenset(
    {
        "BASH_ENV",
        "ENV",
        "GCONV_PATH",
        "HOME",
        "HOSTALIASES",
        "IFS",
        "LOCPATH",
        "NLSPATH",
        "NODE_OPTIONS",
        "NODE_PATH",
        "NODE_REPL_EXTERNAL_MODULE",
        "NPM_CONFIG_PREFIX",
        "PATH",
        "PERL5LIB",
        "PS4",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "RUBYOPT",
        "SHELL",
    }
)

#: Shu prefiksli o'zgaruvchilar ham taqiqlangan (dinamik kutubxona yuklash va
#: Durabl'ning o'z ichki o'zgaruvchilari).
FORBIDDEN_ENV_PREFIXES: Final = ("LD_", "DYLD_", "DURABL_")

#: Nomi bo'yicha bloklanadigan hostlar (SSRF — cloud metadata va mahalliy xizmatlar).
BLOCKED_HOSTNAMES: frozenset[str] = frozenset(
    {
        "169.254.169.254",
        "instance-data",
        "ip6-localhost",
        "ip6-loopback",
        "localhost",
        "localhost.localdomain",
        "metadata",
        "metadata.goog",
        "metadata.google.internal",
    }
)

#: Shu bilan tugaydigan hostlar ham bloklanadi (ichki tarmoq zonalari).
BLOCKED_HOST_SUFFIXES: Final = (".internal", ".local", ".localdomain", ".localhost", ".home.arpa")

#: croniter qo'llab-quvvatlaydigan taxalluslar.
CRON_ALIASES: frozenset[str] = frozenset(
    {"@annually", "@daily", "@hourly", "@midnight", "@monthly", "@weekly", "@yearly"}
)

_TAG_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
_ENV_NAME_RE: Final = re.compile(ENV_NAME_PATTERN)

# Node uchun regex'lar — JS parser'imiz yo'q, shuning uchun matn bo'yicha tekshiramiz.
_NODE_REQUIRE_RE: Final = re.compile(r"""require\s*\(\s*['"]([^'"]+)['"]\s*\)""")
_NODE_IMPORT_FROM_RE: Final = re.compile(
    r"""\bimport\s+(?:[\w*\s{},$]+\s+from\s+)?['"]([^'"]+)['"]"""
)
_NODE_DYNAMIC_IMPORT_RE: Final = re.compile(r"""\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)""")
_NODE_CREATE_REQUIRE_RE: Final = re.compile(r"""createRequire\s*\(""")
_NODE_EVAL_RE: Final = re.compile(r"\beval\s*\(")
_NODE_FUNCTION_CTOR_RE: Final = re.compile(r"\bnew\s+Function\s*\(")
_NODE_PROCESS_RE: Final = re.compile(r"\bprocess\s*\.\s*(binding|dlopen|_linkedBinding)\b")
_NODE_FS_WRITE_RE: Final = re.compile(
    r"\bfs\s*(?:\.\s*promises\s*)?\.\s*"
    r"(appendFile|appendFileSync|createWriteStream|rm|rmSync|rmdir|rmdirSync|"
    r"truncate|truncateSync|unlink|unlinkSync|write|writeFile|writeFileSync|writeSync)\s*\("
)


# ---------------------------------------------------------------------------
# Kod tekshiruvi natijasi
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CodeInspection:
    """Mijoz kodi statik tahlili natijasi.

    Attributes:
        runtime: Qaysi muhit uchun tekshirildi.
        syntax_error: Sintaksis xatosi matni (bo'lmasa `None`).
        violations: Topilgan buzilishlar — `"12-qator: ..."` ko'rinishida,
            qator raqami bo'yicha tartiblangan.
    """

    runtime: Runtime
    syntax_error: str | None = None
    violations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_syntax_error(self) -> bool:
        """Kodda sintaksis xatosi bormi?"""
        return self.syntax_error is not None

    @property
    def is_clean(self) -> bool:
        """Hech qanday muammo topilmadimi?"""
        return self.syntax_error is None and not self.violations

    @property
    def messages(self) -> list[str]:
        """Barcha xabarlar — sintaksis xatosi birinchi o'rinda."""
        result = list(self.violations)
        if self.syntax_error is not None:
            result.insert(0, self.syntax_error)
        return result


# ---------------------------------------------------------------------------
# Python AST tahlili
# ---------------------------------------------------------------------------


def _dotted_name(node: ast.expr) -> str | None:
    """`os.path.join` kabi nuqtali nomni matn sifatida yig'adi."""
    parts: list[str] = []
    current: ast.expr = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
        return ".".join(reversed(parts))
    return None


def _open_mode(node: ast.Call) -> str | None:
    """`open(...)` chaqiruvidan `mode` qiymatini (matn bo'lsa) ajratadi."""
    if len(node.args) > 1:
        candidate = node.args[1]
        if isinstance(candidate, ast.Constant) and isinstance(candidate.value, str):
            return candidate.value
    for keyword in node.keywords:
        if keyword.arg == "mode":
            value = keyword.value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                return value.value
    return None


class _PythonInspector(ast.NodeVisitor):
    """AST'ni kezib taqiqlangan import va chaqiruvlarni yig'adi."""

    def __init__(self) -> None:
        self.findings: list[tuple[int, str]] = []

    # ast.NodeVisitor metod nomlari CamelCase bo'lishi SHART (N802 shu yerda o'rinli emas)

    def visit_Import(self, node: ast.Import) -> None:
        """`import x, y` — har bir alias tekshiriladi."""
        for alias in node.names:
            self._check_module(node, alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """`from x import y` — modul nomi tekshiriladi."""
        if node.module:
            self._check_module(node, node.module)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Chaqiruvlar: dinamik kod bajarish va faylga yozish."""
        name = _dotted_name(node.func)
        if name is not None:
            if name in PYTHON_FORBIDDEN_CALLS or name in PYTHON_FORBIDDEN_ATTRIBUTE_CALLS:
                self._add(node, f"xavfli chaqiruv: `{name}()` — dinamik kod bajarish/protsess")
            elif name == "open":
                mode = _open_mode(node)
                if mode and any(char in mode for char in WRITE_FILE_MODE_CHARS):
                    self._add(
                        node,
                        f"faylga yozish urinishi: `open(..., {mode!r})` — sandbox fayl tizimi "
                        "faqat o'qish uchun",
                    )
        self.generic_visit(node)

    def _check_module(self, node: ast.stmt, module: str) -> None:
        """Modulning ildiz nomini taqiqlanganlar ro'yxati bilan solishtiradi."""
        root = module.split(".", 1)[0]
        if root in PYTHON_FORBIDDEN_IMPORTS:
            self._add(node, f"taqiqlangan modul import qilingan: `{module}`")

    def _add(self, node: ast.AST, message: str) -> None:
        """Topilmani qator raqami bilan saqlaydi."""
        self.findings.append((int(getattr(node, "lineno", 0) or 0), message))


def _format_findings(findings: Sequence[tuple[int, str]]) -> tuple[str, ...]:
    """Topilmalarni qator bo'yicha tartiblab, takrorlarini olib tashlaydi."""
    seen: set[str] = set()
    result: list[str] = []
    for line, message in sorted(findings, key=lambda item: (item[0], item[1])):
        text = f"{line}-qator: {message}"
        if text not in seen:
            seen.add(text)
            result.append(text)
    return tuple(result)


def _inspect_python(code: str, runtime: Runtime) -> CodeInspection:
    """Python kodini `ast` bilan tekshiradi."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        line = exc.lineno or 0
        reason = exc.msg or "sintaksis xatosi"
        return CodeInspection(
            runtime=runtime,
            syntax_error=f"{line}-qator: sintaksis xatosi — {reason}",
        )
    except (ValueError, MemoryError, RecursionError) as exc:
        # Juda chuqur yoki buzilgan kod — parser ko'tara olmadi
        return CodeInspection(
            runtime=runtime,
            syntax_error=f"kodni tahlil qilib bo'lmadi: {exc}",
        )

    inspector = _PythonInspector()
    inspector.visit(tree)
    return CodeInspection(runtime=runtime, violations=_format_findings(inspector.findings))


# ---------------------------------------------------------------------------
# Node (JavaScript) tahlili
# ---------------------------------------------------------------------------


def _line_at(code: str, index: int) -> int:
    """Belgining indeksi bo'yicha qator raqamini hisoblaydi (1'dan)."""
    return code.count("\n", 0, index) + 1


def _normalize_node_module(raw: str) -> str:
    """`node:child_process/foo` -> `child_process` ko'rinishiga keltiradi."""
    module = raw.strip().lower()
    if module.startswith("node:"):
        module = module[5:]
    if module.startswith("@"):
        # Scoped npm paketi: `@scope/name` — ikki segment saqlanadi
        segments = module.split("/")
        return "/".join(segments[:2])
    return module.split("/", 1)[0]


def _inspect_node(code: str, runtime: Runtime) -> CodeInspection:
    """Node kodini regex bilan tekshiradi (JS parser'i yo'q)."""
    findings: list[tuple[int, str]] = []

    module_patterns = (
        (_NODE_REQUIRE_RE, "require()"),
        (_NODE_IMPORT_FROM_RE, "import"),
        (_NODE_DYNAMIC_IMPORT_RE, "import()"),
    )
    for pattern, label in module_patterns:
        for match in pattern.finditer(code):
            module = _normalize_node_module(match.group(1))
            if module in NODE_FORBIDDEN_MODULES:
                findings.append(
                    (
                        _line_at(code, match.start()),
                        f"taqiqlangan modul {label} orqali ulangan: `{match.group(1)}`",
                    )
                )

    simple_patterns = (
        (_NODE_EVAL_RE, "xavfli chaqiruv: `eval()` — dinamik kod bajarish"),
        (_NODE_FUNCTION_CTOR_RE, "xavfli chaqiruv: `new Function()` — dinamik kod bajarish"),
        (_NODE_PROCESS_RE, "xavfli chaqiruv: `process.binding`/`process.dlopen` — native kod"),
        (_NODE_CREATE_REQUIRE_RE, "`createRequire()` — modul cheklovini chetlab o'tish urinishi"),
        (_NODE_FS_WRITE_RE, "faylga yozish urinishi: sandbox fayl tizimi faqat o'qish uchun"),
    )
    for pattern, message in simple_patterns:
        for match in pattern.finditer(code):
            findings.append((_line_at(code, match.start()), message))

    return CodeInspection(runtime=runtime, violations=_format_findings(findings))


# ---------------------------------------------------------------------------
# Kod validatsiyasining ommaviy API'si
# ---------------------------------------------------------------------------


def validate_runtime(value: Runtime | str) -> Runtime:
    """Matn yoki enumni `Runtime`ga aylantiradi.

    Raises:
        UnsupportedRuntimeError: Noma'lum muhit.
    """
    if isinstance(value, Runtime):
        return value
    try:
        return Runtime(str(value).strip().lower())
    except ValueError as exc:
        raise UnsupportedRuntimeError(str(value)) from exc


def inspect_code(code: str, runtime: Runtime | str) -> CodeInspection:
    """Kodni tekshiradi va to'liq natijani (`CodeInspection`) qaytaradi.

    `CODE_VALIDATION_ENABLED=False` bo'lsa tekshiruv o'tkazilmaydi va bo'sh
    natija qaytadi.
    """
    target = validate_runtime(runtime)
    if not settings.CODE_VALIDATION_ENABLED:
        return CodeInspection(runtime=target)
    if target is Runtime.PYTHON:
        return _inspect_python(code or "", target)
    return _inspect_node(code or "", target)


def validate_code(code: str, runtime: Runtime | str) -> list[str]:
    """Kodni tekshiradi va buzilishlar ro'yxatini qaytaradi (bo'sh = muammo yo'q).

    Xato TASHLAMAYDI — qaror `assert_code_safe()` yoki chaqiruvchida qabul
    qilinadi (`CODE_VALIDATION_STRICT` qiymatiga qarab).
    """
    return inspect_code(code, runtime).messages


def assert_code_safe(code: str, runtime: Runtime | str) -> None:
    """Kod yaroqli va (qat'iy rejimda) xavfsiz ekanini talab qiladi.

    Raises:
        CodeSyntaxError: Sintaksis xatosi (har doim, `STRICT`dan qat'i nazar).
        CodeValidationError: `CODE_VALIDATION_STRICT=True` bo'lganda buzilish topildi.
    """
    inspection = inspect_code(code, runtime)
    if inspection.syntax_error is not None:
        raise CodeSyntaxError(
            f"Kodda sintaksis xatosi bor: {inspection.syntax_error}",
            violations=list(inspection.violations) or None,
        )
    if inspection.violations and settings.CODE_VALIDATION_STRICT:
        raise CodeValidationError(
            "Kod xavfsizlik tekshiruvidan o'tmadi: " + "; ".join(inspection.violations),
            violations=list(inspection.violations),
        )


def validate_code_size(code: str) -> None:
    """Kod hajmi `MAX_CODE_SIZE_BYTES` chegarasiga sig'adimi.

    Raises:
        PayloadTooLargeError: Kod juda katta.
    """
    size = len((code or "").encode("utf-8"))
    if size > settings.MAX_CODE_SIZE_BYTES:
        raise PayloadTooLargeError(
            size=size,
            limit=settings.MAX_CODE_SIZE_BYTES,
            message="Kod hajmi ruxsat etilgan chegaradan katta",
        )


# ---------------------------------------------------------------------------
# Webhook URL (SSRF himoyasi)
# ---------------------------------------------------------------------------


def _is_blocked_address(address: IPv4Address | IPv6Address) -> bool:
    """IP manzil ichki/xizmat manzilimi? (loopback, private, link-local, reserved)"""
    candidates: list[IPv4Address | IPv6Address] = [address]
    for attribute in ("ipv4_mapped", "sixtofour"):
        mapped = getattr(address, attribute, None)
        if mapped is not None:
            candidates.append(mapped)
    return any(
        candidate.is_loopback
        or candidate.is_private
        or candidate.is_link_local
        or candidate.is_reserved
        or candidate.is_multicast
        or candidate.is_unspecified
        for candidate in candidates
    )


def _resolve_addresses(
    host: str,
    port: int | None,
    *,
    require_resolution: bool,
) -> list[IPv4Address | IPv6Address]:
    """Host nomini IP manzillarga yechadi (DNS rebinding'ga qarshi).

    Host o'zi IP bo'lsa — DNS so'rovi qilinmaydi.

    DNS yechilmasa nima bo'ladi? Standart holatda (`require_resolution=False`)
    bo'sh ro'yxat qaytadi, ya'ni URL rad etilmaydi. Buning sababi:
    yechilmaydigan nomga HTTP so'rov ham ketmaydi (`httpx` ayni resolverdan
    foydalanadi), shuning uchun bu teshik ochmaydi — lekin DNS vaqtincha
    ishlamay qolganda yoki tarmoqsiz CI'da halol webhook'lar bejiz
    bloklanishini oldini oladi. Nomi bo'yicha bloklash (`BLOCKED_HOSTNAMES`)
    baribir ishlaydi. Qat'iy "fail-closed" kerak bo'lsa —
    `require_resolution=True`.
    """
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, port or None, proto=socket.IPPROTO_TCP)
    except (OSError, UnicodeError, ValueError) as exc:
        if require_resolution:
            raise WebhookUrlNotAllowedError(
                f"'{host}' nomini IP manzilga aylantirib bo'lmadi",
                details={"host": host},
            ) from exc
        return []

    addresses: list[IPv4Address | IPv6Address] = []
    for info in infos:
        sockaddr = info[4]
        try:
            addresses.append(ipaddress.ip_address(str(sockaddr[0])))
        except (ValueError, IndexError):
            continue
    if not addresses and require_resolution:
        raise WebhookUrlNotAllowedError(
            f"'{host}' uchun IP manzil topilmadi",
            details={"host": host},
        )
    return addresses


def validate_webhook_url(url: str, *, require_resolution: bool = False) -> None:
    """Webhook URL ruxsat etilganmi (SSRF himoyasi).

    Tekshiruvlar:
        1. Sxema `WEBHOOK_ALLOWED_SCHEMES` ro'yxatida.
        2. URL'da login/parol yo'q, host bor, uzunlik chegarada.
        3. `WEBHOOK_BLOCK_PRIVATE_IPS=True` bo'lsa: host nomi bloklanganlar
           ro'yxatida emas, DNS yechilgan BARCHA IP'lar ommaviy (loopback,
           private, link-local, reserved, multicast emas).

    DIQQAT: DNS yechish bloklovchi chaqiruv. Async kontekstda
    `validate_webhook_url_async()` ishlatiladi.

    DNS rebinding to'liq yopilishi uchun tekshiruv faqat webhook yaratilganda
    emas, **yuborish oldidan ham** chaqirilishi kerak (`webhook_service.deliver`).

    Args:
        url: Tekshirilayotgan URL.
        require_resolution: `True` bo'lsa DNS yechilmasa ham xato beradi
            (qat'iy "fail-closed" rejim).

    Raises:
        ValidationError: URL shakli noto'g'ri.
        WebhookUrlNotAllowedError: URL ruxsat etilmagan manzilga ishora qiladi.
    """
    candidate = (url or "").strip()
    if not candidate:
        raise ValidationError("Webhook URL bo'sh bo'lishi mumkin emas")
    if len(candidate) > MAX_WEBHOOK_URL_LENGTH:
        raise ValidationError(
            f"Webhook URL juda uzun (maksimum {MAX_WEBHOOK_URL_LENGTH} belgi)",
            details={"length": len(candidate), "limit": MAX_WEBHOOK_URL_LENGTH},
        )

    try:
        parts = urlsplit(candidate)
        host = parts.hostname
        port = parts.port
        username = parts.username
        password = parts.password
    except ValueError as exc:
        raise ValidationError(f"Webhook URL shakli noto'g'ri: {exc}") from exc

    scheme = parts.scheme.lower()
    allowed_schemes = {item.strip().lower() for item in settings.WEBHOOK_ALLOWED_SCHEMES}
    if scheme not in allowed_schemes:
        raise WebhookUrlNotAllowedError(
            f"'{scheme or '-'}' sxemasi ruxsat etilmagan",
            details={"scheme": scheme, "allowed_schemes": sorted(allowed_schemes)},
        )
    if not host:
        raise ValidationError("Webhook URL'da host ko'rsatilmagan")
    if username or password:
        raise WebhookUrlNotAllowedError(
            "Webhook URL'da login/parol bo'lishi mumkin emas",
            details={"host": host},
        )

    if not settings.WEBHOOK_BLOCK_PRIVATE_IPS:
        return

    normalized = host.lower().rstrip(".")
    if normalized in BLOCKED_HOSTNAMES or normalized.endswith(BLOCKED_HOST_SUFFIXES):
        raise WebhookUrlNotAllowedError(
            f"'{normalized}' hosti bloklangan (mahalliy/ichki manzil)",
            details={"host": normalized},
        )

    resolved = _resolve_addresses(normalized, port, require_resolution=require_resolution)
    for address in resolved:
        if _is_blocked_address(address):
            raise WebhookUrlNotAllowedError(
                f"'{normalized}' ichki IP manzilga ishora qiladi ({address})",
                details={"host": normalized, "resolved_ip": str(address)},
            )


async def validate_webhook_url_async(url: str, *, require_resolution: bool = False) -> None:
    """`validate_webhook_url()`ning async varianti — DNS alohida ipda yechiladi.

    Service qatlami (async) shu funksiyadan foydalanadi, aks holda bloklovchi
    DNS so'rovi butun event loop'ni to'xtatib qo'yadi.
    """
    await asyncio.to_thread(validate_webhook_url, url, require_resolution=require_resolution)


# ---------------------------------------------------------------------------
# Cron
# ---------------------------------------------------------------------------


def validate_cron(expression: str) -> None:
    """Cron ifodasi yaroqlimi (5 yoki 6 maydon, yoki `@daily` kabi taxallus).

    Raises:
        ValidationError: Ifoda yaroqsiz.
    """
    candidate = (expression or "").strip()
    if not candidate:
        raise ValidationError("Cron ifodasi bo'sh bo'lishi mumkin emas")
    if len(candidate) > MAX_CRON_LENGTH:
        raise ValidationError(
            f"Cron ifodasi juda uzun (maksimum {MAX_CRON_LENGTH} belgi)",
            details={"limit": MAX_CRON_LENGTH},
        )

    if candidate.startswith("@"):
        if candidate.lower() not in CRON_ALIASES:
            raise ValidationError(
                f"'{candidate}' taxallusi qo'llab-quvvatlanmaydi",
                details={"allowed": sorted(CRON_ALIASES)},
            )
    elif len(candidate.split()) not in (5, 6):
        raise ValidationError(
            "Cron ifodasi 5 maydon (`m h dom mon dow`) yoki 6 maydon "
            "(soniya bilan) bo'lishi kerak",
            details={"expression": candidate},
        )

    try:
        valid = croniter.is_valid(candidate)
    except (CroniterError, ValueError):
        valid = False
    if not valid:
        raise ValidationError(
            f"Cron ifodasi yaroqsiz: '{candidate}'",
            details={"expression": candidate},
        )


def next_cron_time(expression: str, base: datetime | None = None) -> datetime:
    """Cron ifodasi bo'yicha keyingi bajarish vaqti (timezone-aware UTC).

    `scheduler` shu funksiya natijasini `delayed` ZSET'iga score sifatida yozadi.

    Raises:
        ValidationError: Ifoda yaroqsiz yoki keyingi vaqt hisoblanmadi.
    """
    validate_cron(expression)
    start = ensure_utc(base) if base is not None else utcnow()
    if start is None:
        start = utcnow()
    try:
        upcoming = croniter(expression.strip(), start).get_next(datetime)
    except (CroniterError, ValueError, OverflowError, TypeError) as exc:
        raise ValidationError(
            f"Cron ifodasidan keyingi vaqtni hisoblab bo'lmadi: {exc}",
            details={"expression": expression},
        ) from exc

    result = ensure_utc(upcoming if isinstance(upcoming, datetime) else None)
    if result is None:
        raise ValidationError(
            "Cron ifodasidan keyingi vaqt aniqlanmadi",
            details={"expression": expression},
        )
    return result


# ---------------------------------------------------------------------------
# Job maydonlari
# ---------------------------------------------------------------------------


def validate_timeout(value: int | float | None, *, max_allowed: int | None = None) -> int:
    """Timeout (soniya) chegaralarda ekanini tekshiradi va butun son qaytaradi.

    Args:
        value: Mijoz yuborgan qiymat; `None` bo'lsa standart qiymat olinadi.
        max_allowed: Reja (plan) cheklovi — global chegaradan past bo'lishi mumkin.

    Raises:
        ValidationError: Qiymat son emas yoki chegaradan tashqarida.
    """
    if value is None:
        return settings.DEFAULT_TIMEOUT_SECONDS
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValidationError("timeout_seconds butun son bo'lishi kerak")
    seconds = int(value)

    upper = settings.MAX_TIMEOUT_SECONDS
    if max_allowed is not None:
        upper = min(upper, int(max_allowed))
    lower = min(settings.MIN_TIMEOUT_SECONDS, upper)

    if seconds < lower or seconds > upper:
        raise ValidationError(
            f"timeout_seconds {lower}..{upper} oralig'ida bo'lishi kerak",
            details={"value": seconds, "min": lower, "max": upper},
        )
    return seconds


def validate_retries(value: int | None, *, max_allowed: int | None = None) -> int:
    """`max_retries` chegaralarda ekanini tekshiradi.

    Raises:
        ValidationError: Qiymat son emas yoki chegaradan tashqarida.
    """
    if value is None:
        return settings.DEFAULT_MAX_RETRIES
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError("max_retries butun son bo'lishi kerak")

    upper = settings.MAX_ALLOWED_RETRIES
    if max_allowed is not None:
        upper = min(upper, int(max_allowed))
    if value < 0 or value > upper:
        raise ValidationError(
            f"max_retries 0..{upper} oralig'ida bo'lishi kerak",
            details={"value": value, "max": upper},
        )
    return value


def validate_tags(tags: Sequence[str] | None) -> list[str]:
    """Teglarni tozalaydi va tekshiradi.

    Qoidalar: maksimum `MAX_TAGS` ta teg, har biri `MAX_TAG_LENGTH`
    belgidan oshmaydi (chegaralar `app.constants` dan olinadi), faqat
    harf/raqam/`.`/`_`/`:`/`-` belgilaridan iborat. Bo'sh teglar tashlanadi,
    takrorlar birlashtiriladi (tartib saqlanadi).

    Raises:
        ValidationError: Teglar soni/uzunligi/shakli qoidaga mos emas.
    """
    if tags is None:
        return []
    if isinstance(tags, str):
        raise ValidationError("tags ro'yxat bo'lishi kerak, matn emas")

    cleaned: list[str] = []
    for raw in tags:
        tag = str(raw).strip()
        if not tag:
            continue
        if len(tag) > MAX_TAG_LENGTH:
            raise ValidationError(
                f"Teg juda uzun (maksimum {MAX_TAG_LENGTH} belgi): '{tag[:MAX_TAG_LENGTH]}...'",
                details={"limit": MAX_TAG_LENGTH},
            )
        if _TAG_RE.match(tag) is None:
            raise ValidationError(
                f"Teg shakli noto'g'ri: '{tag}' (harf/raqam bilan boshlanadi, "
                "ichida faqat harf, raqam va . _ : - bo'ladi)",
                details={"tag": tag},
            )
        if tag not in cleaned:
            cleaned.append(tag)

    if len(cleaned) > MAX_TAGS:
        raise ValidationError(
            f"Teglar soni {MAX_TAGS} dan oshmasligi kerak",
            details={"count": len(cleaned), "limit": MAX_TAGS},
        )
    return cleaned


def validate_env_vars(env: Mapping[str, Any] | None) -> dict[str, str]:
    """Sandbox'ga uzatiladigan muhit o'zgaruvchilarini tekshiradi.

    Qoidalar: maksimum `MAX_ENV_VARS` ta, nom `ENV_NAME_PATTERN` ga mos,
    `PATH`/`LD_PRELOAD`/`PYTHONPATH`/`NODE_OPTIONS` kabi sandbox muhitini
    buzadigan nomlar taqiqlangan, qiymat 4096 belgidan oshmaydi va NUL
    bayt saqlamaydi.

    Raises:
        ValidationError: Nom yoki qiymat qoidaga mos emas.
    """
    if not env:
        return {}
    if not isinstance(env, Mapping):
        raise ValidationError("env_vars lug'at (obyekt) bo'lishi kerak")
    if len(env) > MAX_ENV_VARS:
        raise ValidationError(
            f"Muhit o'zgaruvchilari soni {MAX_ENV_VARS} dan oshmasligi kerak",
            details={"count": len(env), "limit": MAX_ENV_VARS},
        )

    cleaned: dict[str, str] = {}
    for raw_name, raw_value in env.items():
        name = str(raw_name).strip()
        if _ENV_NAME_RE.match(name) is None:
            raise ValidationError(
                f"Muhit o'zgaruvchisi nomi noto'g'ri: '{name}' "
                "(harf, raqam va pastki chiziq; harf yoki `_` bilan boshlanadi)",
                details={"name": name},
            )
        # Taqiqlangan nomlar REGISTRDAN QAT'I NAZAR tekshiriladi: `PATH`, `Path`
        # va `path` — uchlasi ham bloklanadi. Sababi: nom shabloni kichik harfga
        # ruxsat beradi (schema bilan bir xil bo'lishi uchun), lekin ba'zi
        # muhitlar va kutubxonalar o'zgaruvchi nomini registrsiz izlaydi,
        # shuning uchun `path=/evil` ni o'tkazib yuborish xavfli bo'lardi.
        upper_name = name.upper()
        if upper_name in FORBIDDEN_ENV_NAMES or upper_name.startswith(FORBIDDEN_ENV_PREFIXES):
            raise ValidationError(
                f"'{name}' muhit o'zgaruvchisini o'zgartirish taqiqlangan",
                details={"name": name},
            )
        value = "" if raw_value is None else str(raw_value)
        if len(value) > MAX_ENV_VALUE_LENGTH:
            raise ValidationError(
                f"'{name}' qiymati juda uzun (maksimum {MAX_ENV_VALUE_LENGTH} belgi)",
                details={"name": name, "limit": MAX_ENV_VALUE_LENGTH},
            )
        if "\x00" in value:
            raise ValidationError(
                f"'{name}' qiymatida NUL bayt bo'lishi mumkin emas",
                details={"name": name},
            )
        cleaned[name] = value
    return cleaned


def validate_payload_size(payload: Mapping[str, Any] | None) -> None:
    """Payload JSON ko'rinishida `MAX_PAYLOAD_SIZE_BYTES` chegarasiga sig'adimi.

    Raises:
        PayloadTooLargeError: Payload juda katta.
        ValidationError: Payload JSON'ga aylanmaydi.
    """
    if payload is None:
        return
    size = len(serialize_payload(payload).encode("utf-8"))
    if size > settings.MAX_PAYLOAD_SIZE_BYTES:
        raise PayloadTooLargeError(
            size=size,
            limit=settings.MAX_PAYLOAD_SIZE_BYTES,
            message="Job payload'i ruxsat etilgan chegaradan katta",
        )


__all__ = [
    "BLOCKED_HOSTNAMES",
    "BLOCKED_HOST_SUFFIXES",
    "CRON_ALIASES",
    "FORBIDDEN_ENV_NAMES",
    "FORBIDDEN_ENV_PREFIXES",
    "MAX_CRON_LENGTH",
    "MAX_ENV_VALUE_LENGTH",
    "MAX_ENV_VARS",
    "MAX_TAGS",
    "MAX_TAG_LENGTH",
    "MAX_WEBHOOK_URL_LENGTH",
    "PYTHON_FORBIDDEN_ATTRIBUTE_CALLS",
    "PYTHON_FORBIDDEN_CALLS",
    "WRITE_FILE_MODE_CHARS",
    "CodeInspection",
    "assert_code_safe",
    "inspect_code",
    "next_cron_time",
    "validate_code",
    "validate_code_size",
    "validate_cron",
    "validate_env_vars",
    "validate_payload_size",
    "validate_retries",
    "validate_runtime",
    "validate_tags",
    "validate_timeout",
    "validate_webhook_url",
    "validate_webhook_url_async",
]
