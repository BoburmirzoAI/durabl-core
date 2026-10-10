"""Durabl — `JobKind.HTTP` uchun runner: mijozning endpointini chaqiradi.

## Nega bu runner bor

Durabl ikki ish rejimini qo'llaydi:

* `JobKind.CODE` — mijoz KODINI yuboradi, u sandboxda bajariladi. Kod
  mijozning serveriga va DB'siga tega olmaydi (tarmoq o'chirilgan,
  paket yo'q), ya'ni tipik "fonda hisobot yasash" ishi uchun yaramaydi.
* `JobKind.HTTP` — mijoz o'z ENDPOINTINI ko'rsatadi. Kod mijozning
  serverida qoladi, demak o'z ORM'i, DB'si va kutubxonalari bilan erkin
  ishlaydi. Durabl faqat "qachon chaqirish va yiqilsa nima qilish" ni
  boshqaradi.

Ikkinchi rejim Celery'dan charchagan oddiy dasturchiga mo'ljallangan:
u Redis ko'tarmaydi, worker boqmaydi, lekin job yo'qolmasligi, ikki
marta bajarilmasligi va yiqilsa DLQ'da KO'RINISHI kafolatini oladi.

## Nega alohida zanjir qurilmadi

`HttpRunner` `SandboxRunner` protokolining uchinchi amalga oshirishi
(`SandboxManager` va `LocalRunner` yonida). Shu tufayli HTTP job
butun ishonchlilik mashinasidan O'ZGARMAGAN holda o'tadi: navbat,
lease, heartbeat, `TimeoutGuard`, eksponensial backoff, DLQ, webhook,
real-time log. Bitta satr ham takrorlanmaydi.

## Xatolar qanday tasniflanadi

| Natija | Sabab | Qayta urinadimi |
|---|---|---|
| 2xx | — | muvaffaqiyat |
| 4xx | `HTTP_CLIENT_ERROR` | **YO'Q** — ayni so'rov ayni javobni oladi |
| 5xx | `HTTP_SERVER_ERROR` | ha — vaqtinchalik nosozlik |
| ulanmadi (DNS/TLS/refused) | `HTTP_CONNECT_ERROR` | ha |
| vaqt limiti | `TIMEOUT` | ha |

4xx ni qayta urinmaslik qarori ataylab: yo'q endpoint yoki noto'g'ri
token uch marta urinishdan tuzalmaydi, faqat mijozning kvotasi yeyiladi
va DLQ'ga tushish kechikadi.

## Xavfsizlik: SSRF

URL `validate_webhook_url_async()` bilan tekshiriladi — webhook'lar
bilan AYNI chaqiruv va AYNI qoida, toki ikki joyda ikki xil himoya
bo'lmasin. Tekshiruv job yuborilganda ham, BAJARILGANDA ham
o'tkaziladi: DNS yozuvi oradan o'zgarib ichki manzilga ishora qilishi
mumkin (DNS rebinding).

Redirect ATAYLAB kuzatilmaydi (`follow_redirects=False`): 302 javob
tekshiruvdan o'tgan URL'ni chetlab o'tishning eng oson yo'li.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Final

import httpx

from app.config import settings
from app.constants import FailureReason, HttpMethod, LogStream, Runtime
from app.exceptions import SandboxError
from app.execution.runtime_base import BaseRuntime, LogSink
from app.execution.types import RunnerOutcome, RunnerPayload, SandboxSpec
from app.logging_config import get_logger
from app.utils.validators import validate_webhook_url_async

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Konstantalar
# ---------------------------------------------------------------------------

#: Durabl qo'yadigan header'lar — mijozning `http_headers` i bu nomlarni
#: BOSIB O'TA OLMAYDI (pastdagi `_build_headers` ga qarang). Shunda
#: qabul qiluvchi tomon so'rov haqiqatan Durabl'dan kelganini va
#: nechanchi urinish ekanini ishonchli biladi.
HEADER_JOB_ID: Final[str] = "X-Durabl-Job-Id"
HEADER_ATTEMPT: Final[str] = "X-Durabl-Attempt"
HEADER_KIND: Final[str] = "X-Durabl-Kind"

#: Javob tanasining saqlanadigan maksimal hajmi. `max_output_bytes` dan
#: oshgan qism tashlanadi va `truncated` belgisi qo'yiladi — mijozning
#: 100 MB javobi DB'ni to'ldirmasligi uchun.
#: (`ResultCollector` chiqish hajmini alohida ham nazorat qiladi.)
MAX_RESPONSE_PREVIEW_BYTES: Final[int] = 64 * 1024

#: HTTP status chegaralari.
STATUS_CLIENT_ERROR_FLOOR: Final[int] = 400
STATUS_SERVER_ERROR_FLOOR: Final[int] = 500

#: `User-Agent` — qabul qiluvchi loglarida kim chaqirganini ko'rsatadi.
USER_AGENT: Final[str] = f"{settings.APP_NAME}/{settings.APP_VERSION} (+durabl-http-job)"


# ---------------------------------------------------------------------------
# Runtime (xatoni tasniflash uchun)
# ---------------------------------------------------------------------------


class HttpRuntime(BaseRuntime):
    """HTTP job uchun "runtime" — faqat xatoni tasniflaydi.

    ## Nega `BaseRuntime` dan voris olinadi

    `Executor` va `ResultCollector` natijani tasniflash uchun
    `runtime.classify_failure()` ni chaqiradi. Agar HTTP uchun alohida
    yo'l qilinsa, `Executor` ning butun mantig'i (TimeoutGuard,
    CancelledError, log fanout, `_finish`) ikki martalab yozilishi
    kerak bo'lardi.

    Shu sababli `BaseRuntime` ning tasniflash qismi QAYTA ISHLATILADI,
    konteyner qismi esa ATAYLAB xato tashlaydi: HTTP job hech qachon
    konteynerga joylashtirilmaydi. Bu nuqsonni yashirmaslik uchun
    xabarlar aniq yozilgan — chaqirilsa, bu dasturchi xatosi.

    `runtime` atributi `PYTHON` qilib qo'yilgan: u faqat log maydoni
    sifatida ishlatiladi va `Runtime` enum'iga `HTTP` qiymatini qo'shish
    "til" tushunchasini "ish rejimi" bilan aralashtirardi. Loglarda
    chalkashlik bo'lmasligi uchun `Executor` `kind` ni alohida yozadi.
    """

    runtime: Runtime = Runtime.PYTHON

    @property
    def image(self) -> str:
        """HTTP job konteynerda bajarilmaydi."""
        raise SandboxError(
            "HTTP rejimidagi job konteynerda bajarilmaydi — image kerak emas.",
            details={"kind": "http"},
        )

    @property
    def entrypoint_path(self) -> str:
        """HTTP job konteynerda bajarilmaydi."""
        raise SandboxError(
            "HTTP rejimidagi job konteynerda bajarilmaydi — entrypoint kerak emas.",
            details={"kind": "http"},
        )

    def container_command(self, spec: SandboxSpec) -> list[str]:
        """HTTP job konteynerda bajarilmaydi."""
        raise SandboxError(
            "HTTP rejimidagi job konteynerda bajarilmaydi.",
            details={"kind": "http", "job_id": spec.job_id},
        )

    def local_command(self, spec: SandboxSpec, workdir: Path) -> list[str]:
        """HTTP job subprocess'da ham bajarilmaydi."""
        raise SandboxError(
            "HTTP rejimidagi job subprocess'da bajarilmaydi.",
            details={"kind": "http", "job_id": spec.job_id},
        )

    def classify_failure(
        self,
        outcome: RunnerOutcome,
        *,
        stderr: str = "",
    ) -> FailureReason:
        """Natijadan HTTP xatosining sababini aniqlaydi.

        Tartib muhim: `timed_out` birinchi tekshiriladi, chunki vaqt
        limiti `TimeoutGuard` tomonidan tashqaridan qo'yiladi va u
        status kodidan ustun turadi (javob kelmagan).
        """
        if outcome.timed_out:
            return FailureReason.TIMEOUT
        status = outcome.exit_code
        if status is None:
            # Status yo'q — ulanish o'rnatilmagan (DNS, TLS, refused).
            return FailureReason.HTTP_CONNECT_ERROR
        if status >= STATUS_SERVER_ERROR_FLOOR:
            return FailureReason.HTTP_SERVER_ERROR
        if status >= STATUS_CLIENT_ERROR_FLOOR:
            return FailureReason.HTTP_CLIENT_ERROR
        return FailureReason.INTERNAL_ERROR


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class HttpRunner:
    """Mijozning HTTP endpointini chaqiradigan runner.

    `SandboxRunner` protokoliga mos (`available` / `run` / `kill`).

    Nusxa HAR BAJARISH uchun yangi yasaladi (`Executor` kabi), shuning
    uchun `_task` maydoni bitta so'rovga tegishli va `kill()` aynan
    o'shani bekor qiladi.
    """

    __slots__ = ("_task",)

    def __init__(self) -> None:
        self._task: asyncio.Task[httpx.Response] | None = None

    # ------------------------------------------------------------------
    # Protokol
    # ------------------------------------------------------------------

    async def available(self) -> bool:
        """HTTP runner har doim tayyor — tashqi demon talab qilmaydi.

        `SandboxManager` uchun bu Docker demoniga ulanishni bildiradi;
        bu yerda esa `httpx` ilovaning o'z bog'liqligi, ya'ni
        tekshiradigan narsa yo'q.
        """
        return True

    async def kill(self) -> None:
        """Ketayotgan so'rovni bekor qiladi (`TimeoutGuard` chaqiradi)."""
        task = self._task
        if task is not None and not task.done():
            task.cancel()

    async def cleanup_orphans(self) -> int:
        """HTTP rejimida tozalanadigan qoldiq YO'Q — har doim 0.

        `SandboxManager` uchun bu metod qolib ketgan konteynerlarni
        o'ldiradi, `LocalRunner` uchun esa zombi jarayonlarni. HTTP
        so'rov esa jarayon ham, konteyner ham yaratmaydi: protsess
        o'lsa, ulanish o'zi uziladi va hostda hech narsa qolmaydi.

        Metod protokolni to'liq bajarish uchun bor (`SandboxRunner`),
        shuning uchun `Executor.cleanup_orphans()` HTTP runner bilan ham
        xato bermasdan ishlaydi.
        """
        return 0

    async def run(
        self,
        spec: SandboxSpec,
        runtime: BaseRuntime,
        on_log: LogSink | None = None,
    ) -> RunnerOutcome:
        """Mijozning endpointini chaqiradi va xom natijani qaytaradi.

        `runtime` argumenti protokol uchun qabul qilinadi, lekin
        ISHLATILMAYDI: HTTP job'da "til" tushunchasi yo'q.

        Vaqt limitini bu metod O'ZI nazorat qilmaydi — `Executor`
        `TimeoutGuard` bilan tashqaridan `kill()` chaqiradi. Shunga
        qaramay `httpx` ga ham timeout berilади: `TimeoutGuard` faqat
        umumiy chegara, `httpx` esa ulanish/o'qish bosqichlarini
        alohida uzadi va aniqroq xato beradi.
        """
        if spec.target_url is None or spec.http_method is None:
            raise SandboxError(
                "HTTP job uchun `target_url` va `http_method` to'ldirilishi shart.",
                details={"job_id": spec.job_id, "target_url": spec.target_url},
            )

        # SSRF: yuborilganda tekshirilgan, lekin DNS oradan o'zgargan
        # bo'lishi mumkin (DNS rebinding) — bajarishdan oldin QAYTA
        # tekshiriladi.
        #
        # `require_resolution` ATAYLAB berilmaydi (standart `False`) —
        # `webhook_service` bilan AYNI yondashuv. Sababi validatorning
        # `_resolve_addresses` docstring'ida: yechilmaydigan nomga HTTP
        # so'rov ham ketmaydi (`httpx` ayni resolverdan foydalanadi),
        # ya'ni teshik ochilmaydi; qat'iy rejim esa DNS vaqtincha
        # ishlamaganda yoki tarmoqsiz muhitda halol URL'larni bejiz
        # bloklardi.
        await validate_webhook_url_async(spec.target_url)

        method = spec.http_method
        headers = self._build_headers(spec)
        body = self._build_body(spec, method)

        self._emit(
            on_log,
            f"{method.value} {spec.target_url} (urinish {spec.attempt_number})",
        )

        timeout = httpx.Timeout(float(spec.timeout_seconds))
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                # Redirect KUZATILMAYDI: 302 — tekshirilgan URL'ni
                # chetlab o'tishning eng oson yo'li (SSRF).
                follow_redirects=False,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                self._task = asyncio.create_task(
                    client.request(
                        method.value,
                        spec.target_url,
                        headers=headers,
                        content=body,
                    )
                )
                response = await self._task
        except asyncio.CancelledError:
            # `kill()` yoki tashqi bekor qilish — `Executor` hal qiladi.
            raise
        except httpx.TimeoutException as exc:
            self._emit(on_log, f"Vaqt limiti: {exc}", stream=LogStream.STDERR)
            return RunnerOutcome(timed_out=True)
        except httpx.HTTPError as exc:
            # Ulanish o'rnatilmadi: DNS, TLS, refused, proxy.
            self._emit(on_log, f"Ulanish xatosi: {exc}", stream=LogStream.STDERR)
            return RunnerOutcome(
                runner_payload=RunnerPayload(
                    ok=False,
                    error=str(exc),
                    error_type=type(exc).__name__,
                ),
            )
        finally:
            self._task = None

        return self._outcome_from_response(response, spec, on_log)

    # ------------------------------------------------------------------
    # Yordamchilar
    # ------------------------------------------------------------------

    @staticmethod
    def _build_headers(spec: SandboxSpec) -> dict[str, str]:
        """So'rov header'larini yasaydi.

        Mijozning header'lari BIRINCHI qo'yiladi, Durabl'ning o'z
        header'lari esa USTIDAN yoziladi — mijoz `X-Durabl-Attempt` ni
        o'zgartirib qabul qiluvchini chalg'itib yubormasligi uchun.
        """
        headers: dict[str, str] = dict(spec.http_headers or {})
        headers[HEADER_JOB_ID] = spec.job_id
        headers[HEADER_ATTEMPT] = str(spec.attempt_number)
        headers[HEADER_KIND] = "http"
        if spec.correlation_id:
            headers["X-Correlation-ID"] = spec.correlation_id
        return headers

    @staticmethod
    def _build_body(spec: SandboxSpec, method: HttpMethod) -> bytes | None:
        """So'rov tanasini yasaydi (`payload` -> JSON).

        `GET` va `DELETE` uchun tana YUBORILMAYDI: ko'p server va proxy
        ularni e'tiborsiz qoldiradi yoki rad etadi
        (`HttpMethod.allows_body`).
        """
        if spec.payload is None or not method.allows_body:
            return None
        return json.dumps(spec.payload, ensure_ascii=False, default=str).encode("utf-8")

    def _outcome_from_response(
        self,
        response: httpx.Response,
        spec: SandboxSpec,
        on_log: LogSink | None,
    ) -> RunnerOutcome:
        """`httpx.Response` ni `RunnerOutcome` ga aylantiradi.

        `exit_code` ga HTTP STATUS KODI yoziladi. Bu ataylab: shunda
        `ResultCollector` ning "nol bo'lmagan chiqish -> xato" mantig'i
        o'zgarmasdan ishlaydi, mijoz esa job natijasida haqiqiy status
        kodini ko'radi (`404`, `503`).
        """
        raw = response.content[:MAX_RESPONSE_PREVIEW_BYTES]
        truncated = len(response.content) > len(raw)
        text = raw.decode("utf-8", errors="replace")
        ok = response.is_success

        self._emit(
            on_log,
            f"-> {response.status_code} ({len(response.content)} bayt)",
            stream=LogStream.STDOUT if ok else LogStream.STDERR,
        )
        if text:
            self._emit(on_log, text, stream=LogStream.STDOUT if ok else LogStream.STDERR)

        logger.info(
            "http_job.response",
            job_id=spec.job_id,
            status=response.status_code,
            attempt=spec.attempt_number,
            bytes=len(response.content),
            truncated=truncated,
            # URL ataylab TO'LIQ yozilmaydi: query ichida token bo'lishi
            # mumkin. Faqat host qoladi.
            host=response.request.url.host,
        )

        return RunnerOutcome(
            # Muvaffaqiyatda 0: `ResultCollector` nolni "muvaffaqiyat"
            # deb o'qiydi. Xatoda esa haqiqiy status kodi.
            exit_code=0 if ok else response.status_code,
            runner_payload=RunnerPayload(
                ok=ok,
                exit_code=0 if ok else response.status_code,
                result=self._parse_result(response, text),
                error=None if ok else f"HTTP {response.status_code}",
                error_type=None if ok else "HTTPStatusError",
            ),
            sandbox_id=f"http-{spec.job_id}-{spec.attempt_number}",
            # Haqiqiy status kodi: muvaffaqiyatda `exit_code` 0 bo'lishi
            # SHART (`ResultCollector` shunday talab qiladi), shuning
            # uchun 200/201/204 farqi faqat shu maydonda saqlanadi.
            response_status=response.status_code,
        )

    @staticmethod
    def _parse_result(response: httpx.Response, text: str) -> Any:
        """Javob tanasini job natijasiga aylantiradi.

        JSON bo'lsa — tahlil qilingan obyekt (mijoz `result["x"]` bilan
        ishlashi uchun), aks holda xom matn. Tahlil xatosi YUTILADI:
        javob tanasi JSON bo'lishi SHART emas.
        """
        content_type = response.headers.get("content-type", "")
        if "json" in content_type.lower():
            try:
                return json.loads(text) if text else None
            except ValueError:
                return text
        return text or None

    @staticmethod
    def _emit(
        on_log: LogSink | None,
        message: str,
        *,
        stream: LogStream = LogStream.SYSTEM,
    ) -> None:
        """Log callback'ini xavfsiz chaqiradi (xatoni yutadi).

        Log yozish bajarishni BUZMASLIGI kerak — `Executor` ham ayni
        shu qoidaga amal qiladi.
        """
        if on_log is None:
            return
        try:
            on_log(stream, message if message.endswith("\n") else f"{message}\n")
        except Exception:  # log yozish bajarishni BUZMASLIGI kerak
            logger.warning("http_job.log_callback_failed", exc_info=True)


__all__ = [
    "HEADER_ATTEMPT",
    "HEADER_JOB_ID",
    "HEADER_KIND",
    "MAX_RESPONSE_PREVIEW_BYTES",
    "STATUS_CLIENT_ERROR_FLOOR",
    "STATUS_SERVER_ERROR_FLOOR",
    "HttpRunner",
    "HttpRuntime",
]
