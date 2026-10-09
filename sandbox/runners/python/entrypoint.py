#!/usr/bin/env python3
"""Durabl — Python runner'ning kirish nuqtasi (entrypoint).

Bu skript sandbox konteyneri ichida yagona protsess sifatida ishga tushadi,
mijoz kodini bajaradi va natijani fayl orqali backend'ga qaytaradi.

Backend (`app/execution/`) bilan tuzilgan shartnoma:

* ish katalogi   — `/sandbox`             (`constants.SANDBOX_WORKDIR`)
* mijoz kodi     — `/sandbox/main.py`     (`constants.SANDBOX_CODE_FILENAME`)
* argumentlar    — `/sandbox/payload.json` (bo'lishi shart emas)
* natija         — `/sandbox/result.json` (`constants.SANDBOX_RESULT_FILENAME`)
* stdout/stderr  — konteyner loglari orqali real vaqtda yig'iladi

`result.json` shakli — `result_collector` AYNAN shu kalitlarni o'qiydi::

    {
      "ok": true,
      "exit_code": 0,
      "result": <mijoz kodi qaytargan qiymat yoki null>,
      "error": null,
      "error_type": null,
      "traceback": null,
      "duration_ms": 123,
      "stdout_bytes": 456,
      "stderr_bytes": 0,
      "truncated": false
    }

Mijoz kodidan natija olishning uchta yo'li (shu tartibda tekshiriladi):

1. `main(...)` yoki `handler(...)` funksiyasi mavjud bo'lsa VA `payload.json`
   berilgan bo'lsa — funksiya `main(*args, **kwargs)` ko'rinishida chaqiriladi,
   qaytgan qiymat `result` bo'ladi.
2. Kod stdout'ga `print(json.dumps({"__durabl_result__": ...}))` chiqarsa —
   oxirgi shunday qator `result` deb olinadi (Python SDK dekoratori shu usulda
   ishlaydi).
3. Aks holda `result` — `null`.

Faqat standart kutubxona ishlatiladi: image minimal bo'lishi shart.
"""

from __future__ import annotations

import builtins
import contextlib
import io
import json
import os
import signal
import sys
import time
import traceback
import types
from pathlib import Path
from typing import Any, Final

try:  # pragma: no cover - `resource` moduli faqat POSIX tizimlarda bor
    import resource
except ImportError:  # pragma: no cover
    resource = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Shartnoma konstantalari (backend `app/constants.py` bilan bir xil)
# ---------------------------------------------------------------------------

#: Konteyner ichidagi standart ish katalogi.
DEFAULT_WORKDIR: Final[str] = "/sandbox"
#: Mijoz kodi joylashgan fayl nomi.
CODE_FILENAME: Final[str] = "main.py"
#: Argumentlar fayli (bo'lmasa — funksiya chaqirilmaydi).
PAYLOAD_FILENAME: Final[str] = "payload.json"
#: Natija fayli — backend shuni o'qiydi.
RESULT_FILENAME: Final[str] = "result.json"

#: SDK dekoratori stdout orqali natija uzatishda ishlatadigan kalit.
RESULT_MARKER: Final[str] = "__durabl_result__"
#: Natija sifatida chaqiriladigan funksiya nomlari (tartib muhim).
ENTRY_FUNCTION_NAMES: Final[tuple[str, ...]] = ("main", "handler")

#: Yig'iladigan chiqish hajmi chegarasi (1 MB) — `settings.MAX_OUTPUT_BYTES`.
DEFAULT_MAX_OUTPUT_BYTES: Final[int] = 1_048_576
#: Marker qatorini qidirishda nechta nomzodni tahlil qilishga ruxsat beriladi.
MAX_MARKER_ATTEMPTS: Final[int] = 50

#: Chiqish kodlari.
EXIT_OK: Final[int] = 0
EXIT_ERROR: Final[int] = 1
EXIT_TIMEOUT: Final[int] = 124      # `timeout(1)` an'anasi bo'yicha
EXIT_TERMINATED: Final[int] = 143   # 128 + SIGTERM(15)


# ---------------------------------------------------------------------------
# Muhit o'zgaruvchilari bilan ishlash yordamchilari
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    """Muhit o'zgaruvchisidan butun son o'qiydi; xato bo'lsa — standart qiymat."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_flag(name: str, default: bool) -> bool:
    """Muhit o'zgaruvchisini mantiqiy qiymatga aylantiradi."""
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def resolve_workdir() -> Path:
    """Ish katalogini aniqlaydi.

    Tartib: `DURABL_SANDBOX_WORKDIR` → `/sandbox` (agar kod fayli shunda bo'lsa)
    → joriy katalog. Oxirgi variant lokal sinovlar uchun kerak (macOS'da
    `/sandbox` mavjud emas).
    """
    override = os.environ.get("DURABL_SANDBOX_WORKDIR", "").strip()
    if override:
        return Path(override)
    default = Path(DEFAULT_WORKDIR)
    if (default / _code_filename()).is_file():
        return default
    return Path.cwd()


def _code_filename() -> str:
    """Kod fayli nomi (backend boshqa nom bersa ham ishlaydi)."""
    return os.environ.get("DURABL_SANDBOX_CODE_FILENAME", "").strip() or CODE_FILENAME


# ---------------------------------------------------------------------------
# Chiqishni ikki joyga yozuvchi oqim ("tee")
# ---------------------------------------------------------------------------


def _cut_to_bytes(text: str, limit: int) -> str:
    """Matnni UTF-8 baytlari bo'yicha kesadi (yarim belgi qolmasligi uchun)."""
    if limit <= 0:
        return ""
    return text.encode("utf-8", "replace")[:limit].decode("utf-8", "ignore")


class TeeStream(io.TextIOBase):
    """Yozilgan matnni xotirada yig'adi VA haqiqiy oqimga ham uzatadi.

    Ikki vazifani bir vaqtda hal qiladi:

    * backend konteyner loglarini real vaqtda o'qiydi — shuning uchun matn
      haqiqiy `stdout`/`stderr`ga darhol yoziladi;
    * `result.json` uchun natija markerini topish kerak — shuning uchun matn
      xotirada ham saqlanadi (chegaradan oshgani kesiladi).
    """

    def __init__(self, real: Any, limit: int) -> None:
        super().__init__()
        self._real = real
        self._limit = max(0, limit)
        self._chunks: list[str] = []
        self._captured_bytes = 0
        self._total_bytes = 0
        self.truncated = False

    # -- yozish --------------------------------------------------------
    def write(self, data: Any) -> int:  # type: ignore[override]
        if data is None:
            return 0
        if not isinstance(data, str):
            data = str(data)
        if not data:
            return 0

        size = len(data.encode("utf-8", "replace"))
        self._total_bytes += size

        room = self._limit - self._captured_bytes
        if room <= 0:
            # Chegara allaqachon to'ldi — faqat belgi qo'yamiz.
            self.truncated = True
        elif size <= room:
            self._chunks.append(data)
            self._captured_bytes += size
        else:
            self._chunks.append(_cut_to_bytes(data, room))
            self._captured_bytes = self._limit
            self.truncated = True

        # Haqiqiy oqimga uzatish. Bu yerdagi xato (masalan quvur uzilishi)
        # mijoz kodini to'xtatmasligi kerak — natija baribir faylga yoziladi.
        with contextlib.suppress(Exception):  # pragma: no cover
            self._real.write(data)
            self._real.flush()
        return len(data)

    def writelines(self, lines: Any) -> None:  # type: ignore[override]
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        with contextlib.suppress(Exception):  # pragma: no cover
            self._real.flush()

    def close(self) -> None:
        """Mijoz kodi `sys.stdout.close()` chaqirsa ham oqim yopilmaydi."""
        self.flush()

    # -- mijoz kodi so'rashi mumkin bo'lgan xossalar --------------------
    def writable(self) -> bool:
        return True

    def readable(self) -> bool:
        return False

    def seekable(self) -> bool:
        return False

    def isatty(self) -> bool:
        return False

    def fileno(self) -> int:
        return self._real.fileno()

    @property
    def encoding(self) -> str:  # type: ignore[override]
        return getattr(self._real, "encoding", "utf-8") or "utf-8"

    @property
    def errors(self) -> str:  # type: ignore[override]
        return getattr(self._real, "errors", "replace") or "replace"

    @property
    def buffer(self) -> Any:
        """Ikkilik yozuv (`sys.stdout.buffer`) to'g'ridan-to'g'ri o'tadi.

        Bunday yozuv konteyner logiga tushadi, lekin marker qidiruvida
        hisobga olinmaydi — SDK har doim matnli `print` ishlatadi.
        """
        return getattr(self._real, "buffer", None)

    # -- natija yig'ish ------------------------------------------------
    @property
    def text(self) -> str:
        """Ushlab olingan (kesilgan bo'lishi mumkin) matn."""
        return "".join(self._chunks)

    @property
    def total_bytes(self) -> int:
        """Kod chiqargan umumiy hajm — kesishdan OLDINGI qiymat."""
        return self._total_bytes


# ---------------------------------------------------------------------------
# Signal bilan uzilish (timeout va SIGTERM)
# ---------------------------------------------------------------------------


class SandboxInterrupt(BaseException):
    """Signal keldi: natijani yozib, nazorat ostida chiqish kerak.

    `Exception`dan emas, `BaseException`dan voris — mijoz kodidagi
    `except Exception` bloklari bu uzilishni yutib ketmasligi uchun.
    """

    def __init__(self, message: str, error_type: str, exit_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.error_type = error_type
        self.exit_code = exit_code


def _signal_raiser(message: str, error_type: str, exit_code: int):
    """Signal uchun ishlovchi yasaydi — u `SandboxInterrupt` tashlaydi."""

    def _handler(signum: int, frame: types.FrameType | None) -> None:
        raise SandboxInterrupt(message, error_type, exit_code)

    return _handler


def install_signal_handlers(timeout_seconds: int) -> None:
    """SIGTERM/SIGINT va (timeout berilgan bo'lsa) SIGALRM ni ulaydi.

    Timeout uchun `setitimer` ishlatiladi: birinchi signal 1 soniyalik
    takrorlanish bilan beriladi. Agar mijoz kodi uzilishni `except:` bilan
    yutib ketsa — signal qayta kelib, protsess baribir to'xtaydi.
    """
    terminate = _signal_raiser(
        "Bajarish tashqaridan to'xtatildi (SIGTERM)",
        "SandboxTerminated",
        EXIT_TERMINATED,
    )
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, terminate)
        except (ValueError, OSError):  # pragma: no cover
            continue

    if timeout_seconds > 0 and hasattr(signal, "SIGALRM"):
        with contextlib.suppress(ValueError, OSError):  # pragma: no cover
            signal.signal(
                signal.SIGALRM,
                _signal_raiser(
                    f"Bajarish vaqti limiti oshdi ({timeout_seconds}s)",
                    "SandboxTimeout",
                    EXIT_TIMEOUT,
                ),
            )
            signal.setitimer(signal.ITIMER_REAL, float(timeout_seconds), 1.0)


def disarm_signals() -> None:
    """Natijani yozish oldidan barcha signallarni o'chiradi.

    Aks holda `result.json` yozilayotgan payt kelgan signal faylni yarim
    yozilgan holda qoldirishi mumkin edi.
    """
    if hasattr(signal, "ITIMER_REAL"):
        with contextlib.suppress(ValueError, OSError):  # pragma: no cover
            signal.setitimer(signal.ITIMER_REAL, 0.0, 0.0)
    for name in ("SIGTERM", "SIGINT", "SIGALRM"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, signal.SIG_IGN)
        except (ValueError, OSError):  # pragma: no cover
            continue


# ---------------------------------------------------------------------------
# Qo'shimcha himoya: rlimit
# ---------------------------------------------------------------------------


def apply_rlimits() -> list[str]:
    """`resource.setrlimit` bilan protsess darajasidagi cheklovlar.

    Bu Docker/gVisor limitlarining o'rnini bosmaydi — ular ustiga qo'shiladi
    (fork bombasi, fayl deskriptorlari tugashi, disk to'lib ketishiga qarshi).
    Limit faqat QATTIQLASHTIRILADI: mavjud yumshoq limit allaqachon kichik
    bo'lsa, u o'zgartirilmaydi.
    """
    if resource is None or not _env_flag("DURABL_RLIMITS_ENABLED", True):
        return []

    desired: tuple[tuple[str, int], ...] = (
        # Ochiq fayl deskriptorlari soni.
        ("RLIMIT_NOFILE", _env_int("DURABL_RLIMIT_NOFILE", 256)),
        # Bir foydalanuvchi yarata oladigan protsesslar soni (fork bombasi).
        ("RLIMIT_NPROC", _env_int("DURABL_RLIMIT_NPROC", 64)),
        # Yoziladigan fayl hajmi (disk to'lishiga qarshi).
        ("RLIMIT_FSIZE", _env_int("DURABL_RLIMIT_FSIZE_MB", 64) * 1024 * 1024),
    )

    applied: list[str] = []
    for name, value in desired:
        limit_id = getattr(resource, name, None)
        if limit_id is None or value <= 0:
            continue
        try:
            soft, hard = resource.getrlimit(limit_id)
            target = value if hard == resource.RLIM_INFINITY else min(value, hard)
            if soft != resource.RLIM_INFINITY and soft <= target:
                continue  # mavjud limit allaqachon qattiqroq
            resource.setrlimit(limit_id, (target, hard))
            applied.append(f"{name}={target}")
        except (ValueError, OSError):  # pragma: no cover - platformaga bog'liq
            continue
    return applied


# ---------------------------------------------------------------------------
# Payload va natija bilan ishlash
# ---------------------------------------------------------------------------


class PayloadError(Exception):
    """`payload.json` o'qilmadi yoki JSON emas."""


def load_payload(path: Path) -> dict[str, Any] | None:
    """`payload.json` ni o'qiydi; fayl bo'lmasa `None` qaytaradi.

    Fayl ichida lug'at bo'lmasa (masalan ro'yxat yoki son), u yagona
    pozitsion argument sifatida o'raladi.
    """
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise PayloadError(f"payload.json o'qilmadi: {exc}") from exc
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except ValueError as exc:
        raise PayloadError(f"payload.json yaroqli JSON emas: {exc}") from exc
    if isinstance(parsed, dict):
        return parsed
    return {"args": [parsed], "kwargs": {}}


def split_payload(payload: dict[str, Any]) -> tuple[list[Any], dict[str, Any]]:
    """Payload'dan `args` va `kwargs` ni ajratadi (noto'g'ri turlarni to'g'rilaydi)."""
    args = payload.get("args", [])
    kwargs = payload.get("kwargs", {})
    if args is None:
        args = []
    elif isinstance(args, tuple):
        args = list(args)
    elif not isinstance(args, list):
        args = [args]
    if not isinstance(kwargs, dict):
        kwargs = {}
    # Kalitlar faqat matn bo'lishi kerak — aks holda `**kwargs` ishlamaydi.
    kwargs = {str(key): value for key, value in kwargs.items()}
    return args, kwargs


def _json_default(value: Any) -> Any:
    """JSON'ga tushmaydigan obyektlarni matnga aylantiradi (oxirgi chora)."""
    for attr in ("isoformat", "__str__"):
        method = getattr(value, attr, None)
        if callable(method):
            try:
                return method()
            except Exception:  # pragma: no cover
                continue
    return repr(value)  # pragma: no cover


def normalize_result(value: Any) -> tuple[Any, str | None]:
    """Natijani JSON'ga tushadigan ko'rinishga keltiradi.

    `(normallashtirilgan_qiymat, ogohlantirish)` qaytaradi. Serializatsiya
    umuman imkonsiz bo'lsa (masalan tsiklik havola) — `(None, xabar)`.
    """
    if value is None:
        return None, None
    try:
        return json.loads(json.dumps(value, default=_json_default)), None
    except (TypeError, ValueError) as exc:
        return None, f"natija JSON'ga aylantirilmadi: {exc}"


def extract_marker_result(stdout_text: str) -> tuple[Any, bool]:
    """stdout'dan `{"__durabl_result__": ...}` qatorini topadi.

    Oxiridan boshlab tekshiriladi — eng oxirgi marker ustun turadi.
    `(qiymat, topildimi)` qaytaradi.
    """
    if RESULT_MARKER not in stdout_text:
        return None, False
    attempts = 0
    for line in reversed(stdout_text.splitlines()):
        if RESULT_MARKER not in line:
            continue
        attempts += 1
        if attempts > MAX_MARKER_ATTEMPTS:
            break
        try:
            parsed = json.loads(line.strip())
        except ValueError:
            continue
        if isinstance(parsed, dict) and RESULT_MARKER in parsed:
            return parsed[RESULT_MARKER], True
    return None, False


def format_user_traceback(exc: BaseException) -> str:
    """Izma-izni (traceback) mijoz nuqtai nazaridan shakllantiradi.

    Boshidagi entrypoint kadrlari tashlab yuboriladi — mijozga faqat o'z
    kodidagi qatorlar ko'rinishi kerak.
    """
    tb = exc.__traceback__
    entry_file = os.path.abspath(__file__)
    while tb is not None:
        frame_file = os.path.abspath(tb.tb_frame.f_code.co_filename)
        if frame_file != entry_file:
            break
        tb = tb.tb_next
    if tb is None:
        return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    return "".join(traceback.format_exception(type(exc), exc, tb))


def write_result(path: Path, document: dict[str, Any]) -> None:
    """`result.json` ni atomik yozadi (vaqtinchalik fayl + `os.replace`).

    Yarim yozilgan faylni backend o'qib qolmasligi uchun atomik almashtirish
    ishlatiladi.
    """
    raw = json.dumps(document, ensure_ascii=False, default=_json_default)
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        with open(tmp_path, "w", encoding="utf-8") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
    except OSError:
        # Atomik yozuv imkonsiz bo'lsa (masalan `os.replace` ruxsat bermasa) —
        # to'g'ridan-to'g'ri yozamiz: natija backend uchun hayotiy muhim.
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(raw)


# ---------------------------------------------------------------------------
# Mijoz kodini bajarish
# ---------------------------------------------------------------------------


def build_user_globals(code_path: Path, payload: dict[str, Any] | None) -> dict[str, Any]:
    """Mijoz kodi uchun izolyatsiyalangan `globals` yasaydi.

    Kod o'zini asosiy skript deb hisoblashi kerak (`if __name__ == "__main__"`
    bloklari ishlashi uchun), shuning uchun yangi `__main__` moduli yaratiladi
    va `sys.modules`ga qo'yiladi — `dataclasses`, `pickle` kabi modullar
    `__main__`ga murojaat qiladi.
    """
    module = types.ModuleType("__main__")
    namespace = module.__dict__
    namespace["__name__"] = "__main__"
    namespace["__file__"] = str(code_path)
    namespace["__builtins__"] = builtins
    namespace["__package__"] = None
    namespace["__spec__"] = None
    namespace["__loader__"] = None
    namespace["__doc__"] = None
    # Payload'ni kodga ham ko'rsatamiz — funksiya yozmagan mijoz uchun qulay.
    namespace["__durabl_payload__"] = payload
    sys.modules["__main__"] = module
    return namespace


def run_user_code(
    code_path: Path,
    payload: dict[str, Any] | None,
    namespace: dict[str, Any],
) -> tuple[Any, bool]:
    """Kodni bajaradi va kerak bo'lsa kirish funksiyasini chaqiradi.

    `(qaytgan_qiymat, funksiya_chaqirildimi)` qaytaradi.
    """
    source = code_path.read_text(encoding="utf-8", errors="replace")
    compiled = compile(source, str(code_path), "exec")
    exec(compiled, namespace)  # noqa: S102 - sandbox ichida ataylab exec

    # Funksiya faqat payload berilganda chaqiriladi (shartnoma shunday).
    if payload is None:
        return None, False
    args, kwargs = split_payload(payload)
    for name in ENTRY_FUNCTION_NAMES:
        candidate = namespace.get(name)
        if callable(candidate):
            return candidate(*args, **kwargs), True
    return None, False


# ---------------------------------------------------------------------------
# Asosiy oqim
# ---------------------------------------------------------------------------


def main() -> int:
    """Entrypoint: tayyorlash → bajarish → `result.json` → chiqish kodi."""
    started = time.monotonic()

    workdir = resolve_workdir()
    code_path = workdir / _code_filename()
    payload_path = workdir / PAYLOAD_FILENAME
    result_path = workdir / (
        os.environ.get("DURABL_SANDBOX_RESULT_FILENAME", "").strip() or RESULT_FILENAME
    )

    output_limit = _env_int("DURABL_MAX_OUTPUT_BYTES", DEFAULT_MAX_OUTPUT_BYTES)
    timeout_seconds = _env_int("DURABL_SANDBOX_TIMEOUT_SECONDS", 0)

    real_stdout, real_stderr = sys.stdout, sys.stderr
    tee_out = TeeStream(real_stdout, output_limit)
    tee_err = TeeStream(real_stderr, output_limit)

    ok = True
    exit_code = EXIT_OK
    error: str | None = None
    error_type: str | None = None
    tb_text: str | None = None
    raw_result: Any = None
    returned = False

    try:
        # --- tayyorlash (bu bosqich xatosi mijoz kodining xatosi emas) ---
        if not code_path.is_file():
            raise FileNotFoundError(f"kod fayli topilmadi: {code_path}")
        payload = load_payload(payload_path)

        # Kod o'z katalogidan nisbiy fayllarni ocha olishi va qo'shni
        # modullarni import qila olishi uchun.
        with contextlib.suppress(OSError):
            os.chdir(workdir)
        workdir_str = str(workdir)
        if workdir_str not in sys.path:
            sys.path.insert(0, workdir_str)

        apply_rlimits()
        install_signal_handlers(timeout_seconds)

        namespace = build_user_globals(code_path, payload)

        # --- mijoz kodi ---
        with contextlib.redirect_stdout(tee_out), contextlib.redirect_stderr(tee_err):
            try:
                raw_result, returned = run_user_code(code_path, payload, namespace)
            finally:
                tee_out.flush()
                tee_err.flush()

    except SandboxInterrupt as exc:
        # Timeout yoki SIGTERM — natija baribir yozilishi kerak.
        ok = False
        exit_code = exc.exit_code
        error = exc.message
        error_type = exc.error_type
        tb_text = format_user_traceback(exc)

    except SystemExit as exc:
        # `sys.exit()` — mijoz kodining normal tugash usuli.
        code = exc.code
        if code is None:
            numeric = EXIT_OK
        elif isinstance(code, int):
            numeric = code
        else:
            # `sys.exit("xabar")` — matn stderr'ga chiqadi, kod 1 bo'ladi.
            numeric = EXIT_ERROR
            error = str(code)
        if numeric == EXIT_OK:
            ok = True
            exit_code = EXIT_OK
        else:
            ok = False
            exit_code = max(1, min(255, numeric))
            error = error or f"kod sys.exit({numeric}) bilan tugadi"
            error_type = "SystemExit"
            tb_text = format_user_traceback(exc)

    except PayloadError as exc:
        ok = False
        exit_code = EXIT_ERROR
        error = str(exc)
        error_type = "PayloadError"
        tb_text = format_user_traceback(exc)

    except BaseException as exc:  # noqa: BLE001 - har qanday xato natijaga aylanadi
        ok = False
        exit_code = EXIT_ERROR
        error = str(exc) or exc.__class__.__name__
        error_type = exc.__class__.__name__
        tb_text = format_user_traceback(exc)

    finally:
        # Natija yozilayotganda signal kelmasligi kerak.
        disarm_signals()
        sys.stdout, sys.stderr = real_stdout, real_stderr

    # --- natijani aniqlash ---
    result_value: Any = None
    if ok:
        if returned and raw_result is not None:
            result_value = raw_result
        else:
            marker_value, found = extract_marker_result(tee_out.text)
            if found:
                result_value = marker_value
            elif returned:
                result_value = raw_result  # funksiya ataylab `None` qaytargan

    normalized, warning = normalize_result(result_value)
    if warning is not None:
        # Natija serializatsiya qilinmadi — bu xato emas, ogohlantirish.
        with contextlib.suppress(Exception):
            tee_err.write(f"[durabl] ogohlantirish: {warning}\n")

    duration_ms = int((time.monotonic() - started) * 1000)
    document: dict[str, Any] = {
        "ok": ok,
        "exit_code": exit_code,
        "result": normalized,
        "error": error,
        "error_type": error_type,
        "traceback": tb_text,
        "duration_ms": duration_ms,
        "stdout_bytes": tee_out.total_bytes,
        "stderr_bytes": tee_err.total_bytes,
        "truncated": tee_out.truncated or tee_err.truncated,
    }

    try:
        write_result(result_path, document)
    except OSError as exc:
        # Natija yozilmasa backend buni "sandbox_error" deb hisoblaydi.
        print(f"[durabl] result.json yozilmadi: {exc}", file=real_stderr, flush=True)
        return EXIT_ERROR

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
