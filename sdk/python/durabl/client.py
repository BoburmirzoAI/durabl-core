"""Durabl HTTP mijozlari: `DurablClient` (sinxron) va `AsyncDurablClient` (asinxron).

Ikkala mijoz bir xil imzolarga ega — farqi faqat `await` da. Umumiy mantiq
(so'rov tanasini yasash, xatoni tanib olish, backoff hisoblash) `_BaseClient`da
yozilgan, shuning uchun qoidalar bir joyda saqlanadi.

Ishonchlilik xususiyatlari:

* `X-API-Key` sarlavhasi har so'rovda yuboriladi;
* `Idempotency-Key` berilsa — tarmoq uzilib qayta yuborilsa ham job bir marta
  yaratiladi (backend `idempotency_service` shu kalitga tayanadi);
* 429 va 5xx javoblarda eksponensial backoff bilan avtomatik qayta urinish,
  `Retry-After` sarlavhasi hisobga olinadi;
* `wait_for_result()` da polling intervali asta oshadi: 1s -> 2s -> 4s -> 5s.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from enum import Enum
from typing import Any

import httpx

from .config import HEADER_IDEMPOTENCY_KEY, HEADER_REQUEST_ID, DurablConfig
from .exceptions import (
    DurablAPIError,
    DurablConnectionError,
    DurablTimeoutError,
    JobFailedError,
    ResultNotReadyError,
    ValidationError,
    error_from_response,
)
from .job import AsyncJobHandle, Job, JobHandle, JobPage, JobResult, JobStatus, Pagination

#: Shu statuslarda so'rov qayta yuboriladi (vaqtincha nosozliklar).
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})

#: `wait_for_result` da polling intervali shu qiymatdan oshmaydi (soniya).
MAX_POLL_INTERVAL = 5.0
#: Har pollingdan keyin interval shu koeffitsientga ko'paytiriladi.
POLL_INTERVAL_FACTOR = 2.0
#: Eng kichik ruxsat etilgan polling intervali (serverni bosmaslik uchun).
MIN_POLL_INTERVAL = 0.05


def _value_of(value: Any) -> Any:
    """Enum bo'lsa uning qiymatini, aks holda o'zini qaytaradi."""
    return value.value if isinstance(value, Enum) else value


def _as_float(value: Any) -> float | None:
    """Qiymatni `float`ga aylantiradi; bo'lmasa `None`."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(value: datetime | str) -> str:
    """`datetime`ni ISO-8601 UTC matnga aylantiradi (naive vaqt UTC deb olinadi)."""
    if isinstance(value, str):
        return value
    moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat()


def _clean_params(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """So'rov parametrlarini tozalaydi: `None` tashlanadi, enum/sana matnga o'tadi."""
    if not params:
        return None
    clean: dict[str, Any] = {}
    for key, raw in params.items():
        if raw is None:
            continue
        if isinstance(raw, datetime):
            clean[key] = _iso(raw)
        elif isinstance(raw, bool):
            clean[key] = "true" if raw else "false"
        elif isinstance(raw, (list, tuple, set, frozenset)):
            values = [_value_of(item) for item in raw]
            if values:
                clean[key] = values
        else:
            clean[key] = _value_of(raw)
    return clean or None


class _BaseClient:
    """Sinxron va asinxron mijozlar uchun umumiy mantiq (HTTP'siz qism)."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
        retry_backoff: float | None = None,
        retry_max_delay: float | None = None,
        verify_ssl: bool | None = None,
        headers: Mapping[str, str] | None = None,
        config: DurablConfig | None = None,
    ) -> None:
        # Faqat berilgan (None bo'lmagan) qiymatlar standartlarni almashtiradi.
        overrides: dict[str, Any] = {
            "api_key": api_key,
            "base_url": base_url,
            "timeout": timeout,
            "max_retries": max_retries,
            "retry_backoff": retry_backoff,
            "retry_max_delay": retry_max_delay,
            "verify_ssl": verify_ssl,
        }
        overrides = {key: val for key, val in overrides.items() if val is not None}
        self.config = config.merge(**overrides) if config is not None else DurablConfig(**overrides)
        if headers:
            self.config.extra_headers.update(dict(headers))
        # API kalit bo'lmasa darhol tushunarli xato berish (so'rovni kutmasdan).
        self.config.require_api_key()
        #: Oxirgi o'qilgan job suratlari — `JobHandle` keshini yangilash uchun.
        self._last_jobs: dict[str, Job] = {}

    # ------------------------------------------------------------------
    # Yordamchilar
    # ------------------------------------------------------------------

    def last_job(self, job_id: str) -> Job | None:
        """Shu mijoz oxirgi marta o'qigan job suratini qaytaradi (keshdan)."""
        return self._last_jobs.get(str(job_id))

    def _remember(self, job: Job) -> Job:
        """Job suratini keshga yozadi va o'zini qaytaradi."""
        self._last_jobs[job.id] = job
        return job

    def _path(self, *parts: Any) -> str:
        """API yo'li: `_path("jobs", job_id)` -> `/api/v1/jobs/<id>`."""
        return self.config.path(*parts)

    def _request_headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        """So'rov sarlavhalari (kerak bo'lsa `Idempotency-Key` bilan)."""
        headers = self.config.headers()
        if idempotency_key:
            headers[HEADER_IDEMPOTENCY_KEY] = str(idempotency_key)
        return headers

    def _submit_body(
        self,
        code: str,
        runtime: Any,
        *,
        payload: Mapping[str, Any] | None,
        env_vars: Mapping[str, str] | None,
        timeout: int | None,
        max_retries: int | None,
        priority: Any,
        scheduled_at: datetime | str | None,
        cron: str | None,
        tags: Iterable[str] | None,
        memory_mb: int | None,
        cpus: float | None,
        idempotency_key: str | None,
    ) -> dict[str, Any]:
        """`POST /jobs` uchun tanani yasaydi (`JobCreate` schema shakli).

        Faqat berilgan maydonlar yuboriladi, chunki backend schema'si
        `extra="forbid"` bilan ishlaydi va `None` qiymatlarni ortiqcha
        yuborish kerak emas.
        """
        if not isinstance(code, str) or not code.strip():
            raise ValidationError(message="`code` bo'sh bo'lishi mumkin emas")
        if timeout is not None and int(timeout) <= 0:
            raise ValidationError(message="`timeout` noldan katta bo'lishi kerak")
        if max_retries is not None and int(max_retries) < 0:
            raise ValidationError(message="`max_retries` manfiy bo'lishi mumkin emas")

        body: dict[str, Any] = {"code": code, "runtime": str(_value_of(runtime))}
        if priority is not None:
            body["priority"] = str(_value_of(priority))
        if timeout is not None:
            body["timeout_seconds"] = int(timeout)
        if max_retries is not None:
            body["max_retries"] = int(max_retries)
        if payload is not None:
            body["payload"] = dict(payload)
        if env_vars is not None:
            body["env_vars"] = {str(key): str(val) for key, val in dict(env_vars).items()}
        if scheduled_at is not None:
            body["scheduled_at"] = _iso(scheduled_at)
        if cron is not None:
            body["cron_expression"] = cron
        if tags is not None:
            body["tags"] = [str(tag) for tag in tags]
        if memory_mb is not None:
            body["memory_mb"] = int(memory_mb)
        if cpus is not None:
            body["cpus"] = float(cpus)
        if idempotency_key is not None:
            # Header ustun turadi, lekin tanada ham yuborish shartnomada ruxsat etilgan.
            body["idempotency_key"] = str(idempotency_key)
        return body

    # ------------------------------------------------------------------
    # Javob va xato bilan ishlash
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_body(response: httpx.Response) -> Any:
        """Javob tanasini JSON sifatida o'qiydi (bo'sh tana -> `None`)."""
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            snippet = response.text[:200]
            raise DurablAPIError(
                status_code=response.status_code,
                code="INVALID_RESPONSE",
                message=f"Server JSON bo'lmagan javob qaytardi: {snippet!r}",
                request_id=response.headers.get(HEADER_REQUEST_ID),
            ) from exc

    @staticmethod
    def _parse_retry_after(headers: Mapping[str, str]) -> float | None:
        """`Retry-After` sarlavhasini soniyaga aylantiradi.

        Ikki shakl qo'llanadi: soniya soni (`"5"`) va HTTP-sana
        (`"Wed, 21 Oct 2026 07:28:00 GMT"`).
        """
        raw = headers.get("Retry-After") or headers.get("retry-after")
        if not raw:
            return None
        # Birinchi shakl: soniya soni.
        seconds = _as_float(raw)
        if seconds is not None:
            return max(0.0, seconds)
        # Ikkinchi shakl: HTTP-sana.
        try:
            when = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return None
        if when is None:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0.0, (when - datetime.now(timezone.utc)).total_seconds())

    def _error_for(self, response: httpx.Response) -> DurablAPIError:
        """Xato javobidan mos SDK xato obyektini yasaydi."""
        try:
            payload: Any = response.json() if response.content else None
        except ValueError:
            payload = response.text
        return error_from_response(
            response.status_code,
            payload,
            retry_after=self._parse_retry_after(response.headers),
            request_id=response.headers.get(HEADER_REQUEST_ID),
        )

    def _is_retryable(self, status_code: int) -> bool:
        """Shu status kodda qayta urinish ma'noga egami?"""
        return status_code in RETRYABLE_STATUS_CODES

    def _compute_retry_delay(self, attempt: int, retry_after: float | None = None) -> float:
        """Qayta urinishdan oldin qancha kutishni hisoblaydi.

        `Retry-After` berilgan bo'lsa u ustun turadi, aks holda eksponensial
        backoff: `retry_backoff * 2**attempt`. Natija `retry_max_delay` bilan
        cheklanadi. `attempt` 0'dan boshlanadi.
        """
        if retry_after is not None and retry_after >= 0:
            return min(float(retry_after), self.config.retry_max_delay)
        delay = self.config.retry_backoff * (POLL_INTERVAL_FACTOR ** max(0, attempt))
        return min(delay, self.config.retry_max_delay)

    @staticmethod
    def _next_poll_interval(interval: float) -> float:
        """Keyingi polling intervali: ikki barobar, lekin maksimumdan oshmaydi."""
        return min(interval * POLL_INTERVAL_FACTOR, MAX_POLL_INTERVAL)

    @staticmethod
    def _extract_items(payload: Any, *extra_keys: str) -> list[Any]:
        """Ro'yxat javobidan elementlarni ajratadi.

        Shartnoma bo'yicha shakl `{items, pagination}`, lekin ba'zi endpointlar
        boshqa kalit ishlatadi: `/jobs/{id}/logs` -> `JobLogsResponse.entries`.
        To'g'ridan-to'g'ri ro'yxat ham qabul qilinadi — hammasi
        qo'llab-quvvatlanadi.
        """
        if payload is None:
            return []
        if isinstance(payload, list):
            return list(payload)
        if isinstance(payload, dict):
            for key in ("items", *extra_keys, "data", "results"):
                value = payload.get(key)
                if isinstance(value, list):
                    return list(value)
        return []

    def _job_page(self, payload: Any) -> JobPage:
        """Ro'yxat javobini `JobPage`ga aylantiradi."""
        items = [
            self._remember(Job.from_dict(item))
            for item in self._extract_items(payload, "jobs")
        ]
        pagination = (
            Pagination.from_dict(payload.get("pagination"))
            if isinstance(payload, dict)
            else Pagination()
        )
        if not pagination.total:
            pagination.total = len(items)
        return JobPage(items=items, pagination=pagination)

    def _result_or_snapshot(self, payload: Any, job: Job | None) -> JobResult:
        """Natija javobini `JobResult`ga aylantiradi (bo'lmasa job suratidan)."""
        if isinstance(payload, dict) and payload:
            result = JobResult.from_dict(payload)
            if result.job_id is None and job is not None:
                result.job_id = job.id
            return result
        if job is not None:
            return JobResult.from_job(job)
        raise DurablAPIError(
            status_code=200, code="INVALID_RESPONSE", message="Natija javobi bo'sh"
        )

    @staticmethod
    def _check_failure(result: JobResult, job: Job | None, raise_on_failure: bool) -> JobResult:
        """`raise_on_failure=True` bo'lsa muvaffaqiyatsiz natijada xato beradi."""
        if raise_on_failure and not result.ok:
            raise JobFailedError(job if job is not None else result, result=result)
        return result

    def _timeout_error(self, job_id: str, timeout: float, job: Job | None) -> DurablTimeoutError:
        """`wait_for_result` uchun tushunarli timeout xatosi yasaydi."""
        status = job.status if job is not None else "?"
        return DurablTimeoutError(
            f"Job {job_id} {timeout:g} soniya ichida tugamadi (oxirgi holat: {status})"
        )


# ---------------------------------------------------------------------------
# Sinxron mijoz
# ---------------------------------------------------------------------------


class DurablClient(_BaseClient):
    """Durabl API bilan ishlash uchun sinxron mijoz.

    Misol:

        from durabl import DurablClient

        with DurablClient(api_key="durabl_xxx") as client:
            job = client.submit(code="print('salom')", runtime="python")
            result = client.wait_for_result(job.id, timeout=60)
            print(result.stdout)
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
        retry_backoff: float | None = None,
        retry_max_delay: float | None = None,
        verify_ssl: bool | None = None,
        headers: Mapping[str, str] | None = None,
        config: DurablConfig | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            retry_backoff=retry_backoff,
            retry_max_delay=retry_max_delay,
            verify_ssl=verify_ssl,
            headers=headers,
            config=config,
        )
        #: Tashqi `httpx.Client` berilsa, uni yopish mas'uliyati egasida qoladi.
        self._owns_http = http_client is None
        self._http = http_client or httpx.Client(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            verify=self.config.verify_ssl,
            follow_redirects=True,
        )

    # ------------------------------------------------------------------
    # Hayot sikli
    # ------------------------------------------------------------------

    def close(self) -> None:
        """HTTP ulanishlarini yopadi."""
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> DurablClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def _sleep(self, seconds: float) -> None:
        """Kutish (testlarda almashtirib qo'yish mumkin)."""
        if seconds > 0:
            time.sleep(seconds)

    # ------------------------------------------------------------------
    # Quyi qatlam: so'rov yuborish
    # ------------------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        idempotency_key: str | None = None,
    ) -> Any:
        """So'rov yuboradi, kerak bo'lsa qayta urinadi, javob tanasini qaytaradi."""
        headers = self._request_headers(idempotency_key)
        query = _clean_params(params)
        attempt = 0
        while True:
            try:
                response = self._http.request(
                    method, path, params=query, json=json_body, headers=headers
                )
            except httpx.TimeoutException as exc:
                if attempt < self.config.max_retries:
                    self._sleep(self._compute_retry_delay(attempt))
                    attempt += 1
                    continue
                raise DurablTimeoutError(
                    f"{method} {path} so'rovi {self.config.timeout:g} soniyada javob bermadi"
                ) from exc
            except httpx.HTTPError as exc:
                if attempt < self.config.max_retries:
                    self._sleep(self._compute_retry_delay(attempt))
                    attempt += 1
                    continue
                raise DurablConnectionError(
                    f"{self.config.base_url} manziliga ulanib bo'lmadi: {exc}"
                ) from exc

            if response.status_code >= 400:
                if self._is_retryable(response.status_code) and attempt < self.config.max_retries:
                    delay = self._compute_retry_delay(
                        attempt, self._parse_retry_after(response.headers)
                    )
                    self._sleep(delay)
                    attempt += 1
                    continue
                raise self._error_for(response)
            return self._parse_body(response)

    # ------------------------------------------------------------------
    # Job'lar
    # ------------------------------------------------------------------

    def submit(
        self,
        code: str,
        runtime: str = "python",
        *,
        payload: Mapping[str, Any] | None = None,
        env_vars: Mapping[str, str] | None = None,
        timeout: int = 30,
        max_retries: int = 3,
        priority: str = "normal",
        scheduled_at: datetime | str | None = None,
        cron: str | None = None,
        tags: Iterable[str] | None = None,
        memory_mb: int | None = None,
        cpus: float | None = None,
        idempotency_key: str | None = None,
    ) -> JobHandle:
        """Kodni bajarishga yuboradi va `JobHandle` qaytaradi.

        Argumentlar:
            code: Bajariladigan manba kod.
            runtime: `python` yoki `node`.
            payload: Kodga uzatiladigan ma'lumot (sandbox'da `payload.json`).
            env_vars: Sandbox muhit o'zgaruvchilari.
            timeout: Bajarish vaqti limiti (soniya).
            max_retries: Server tomonda necha marta qayta urinish.
            priority: `high` | `normal` | `low`.
            scheduled_at: Kechiktirilgan ishga tushirish vaqti.
            cron: Takrorlanuvchi job uchun cron ifodasi.
            tags: Qidiruv uchun teglar.
            memory_mb: Xotira limiti (reja ruxsat etgan chegarada).
            cpus: CPU limiti.
            idempotency_key: Takrorlanmaslik kaliti — bir xil kalit bilan
                ikkinchi so'rov yangi job yaratmaydi, mavjudini qaytaradi.
        """
        body = self._submit_body(
            code,
            runtime,
            payload=payload,
            env_vars=env_vars,
            timeout=timeout,
            max_retries=max_retries,
            priority=priority,
            scheduled_at=scheduled_at,
            cron=cron,
            tags=tags,
            memory_mb=memory_mb,
            cpus=cpus,
            idempotency_key=idempotency_key,
        )
        data = self._request(
            "POST", self._path("jobs"), json_body=body, idempotency_key=idempotency_key
        )
        job = self._remember(Job.from_dict(data))
        return JobHandle(self, job)

    def get_job(self, job_id: str) -> Job:
        """Bitta job'ning to'liq holatini o'qiydi."""
        data = self._request("GET", self._path("jobs", job_id))
        return self._remember(Job.from_dict(data))

    def get_status(self, job_id: str) -> JobStatus:
        """Job holatini qaytaradi (`JobStatus` enum)."""
        return self.get_job(job_id).status

    def get_result(self, job_id: str) -> JobResult:
        """Job natijasini oladi.

        Job hali tugamagan bo'lsa server 409 beradi va SDK
        `ResultNotReadyError` tashlaydi.
        """
        data = self._request("GET", self._path("jobs", job_id, "result"))
        return self._result_or_snapshot(data, self.last_job(job_id))

    def wait_for_result(
        self,
        job_id: str,
        timeout: float = 60.0,
        poll_interval: float = 1.0,
        *,
        raise_on_failure: bool = False,
    ) -> JobResult:
        """Job tugashini kutadi va natijani qaytaradi.

        Polling intervali asta oshadi: `poll_interval` -> 2x -> 4x -> ...
        maksimum 5 soniya. Umumiy kutish `timeout`dan oshsa
        `TimeoutError` (SDK xatosi) tashlanadi.

        `raise_on_failure=True` bo'lsa, muvaffaqiyatsiz natijada
        `JobFailedError` beradi.
        """
        deadline = time.monotonic() + max(0.0, float(timeout))
        interval = max(MIN_POLL_INTERVAL, float(poll_interval))
        job: Job | None = None
        while True:
            job = self.get_job(job_id)
            if job.status.is_finished:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise self._timeout_error(job_id, timeout, job)
            self._sleep(min(interval, remaining))
            interval = self._next_poll_interval(interval)

        try:
            result = self.get_result(job_id)
        except ResultNotReadyError:
            # Bekor qilingan yoki DLQ'ga tushgan job'da natija bo'lmasligi mumkin.
            result = JobResult.from_job(job)
        return self._check_failure(result, job, raise_on_failure)

    def cancel(self, job_id: str) -> Job:
        """Job'ni bekor qiladi (navbatda yoki bajarilayotgan bo'lsa)."""
        data = self._request("POST", self._path("jobs", job_id, "cancel"))
        if isinstance(data, dict) and not (data.get("id") or data.get("job_id")):
            # `JobCancelResponse` qisqa shakl qaytarsa — to'liq holatni o'qiymiz.
            return self.get_job(job_id)
        return self._remember(Job.from_dict(data))

    def list_jobs_page(self, *, page: int = 1, page_size: int = 20, **filters: Any) -> JobPage:
        """Bitta sahifadagi job'larni sahifalash ma'lumoti bilan qaytaradi."""
        params = {"page": page, "page_size": page_size, **filters}
        data = self._request("GET", self._path("jobs"), params=params)
        return self._job_page(data)

    def list_jobs(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        all_pages: bool = False,
        limit: int | None = None,
        **filters: Any,
    ) -> list[Job]:
        """Job'lar ro'yxatini qaytaradi.

        `all_pages=True` bo'lsa, `pagination.has_next` bo'yicha barcha
        sahifalar aylanib o'qiladi. `limit` berilsa, shu sondan ko'p job
        qaytarilmaydi. Filtrlar serverga to'g'ridan-to'g'ri uzatiladi
        (`status`, `runtime`, `priority`, `search`, `tags`, ...).
        """
        collected: list[Job] = []
        current = max(1, int(page))
        while True:
            result_page = self.list_jobs_page(page=current, page_size=page_size, **filters)
            collected.extend(result_page.items)
            if limit is not None and len(collected) >= limit:
                return collected[:limit]
            if not all_pages or not result_page.items or not result_page.pagination.has_next:
                break
            current += 1
        return collected

    def get_logs(
        self,
        job_id: str,
        *,
        after_sequence: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Job loglarini (stdout/stderr yozuvlari) qaytaradi."""
        params = {"after_sequence": after_sequence, "limit": limit}
        data = self._request("GET", self._path("jobs", job_id, "logs"), params=params)
        entries = self._extract_items(data, "entries", "logs")
        return [item for item in entries if isinstance(item, dict)]

    # ------------------------------------------------------------------
    # DLQ (o'lik xatlar navbati)
    # ------------------------------------------------------------------

    def list_dlq(
        self, *, page: int = 1, page_size: int = 20, **filters: Any
    ) -> list[dict[str, Any]]:
        """DLQ yozuvlarini qaytaradi (muvaffaqiyatsiz tugagan job'lar)."""
        params = {"page": page, "page_size": page_size, **filters}
        data = self._request("GET", self._path("dlq"), params=params)
        return [item for item in self._extract_items(data, "entries") if isinstance(item, dict)]

    def retry_dlq(self, entry_id: str) -> dict[str, Any]:
        """DLQ yozuvini qayta urinishga yuboradi."""
        data = self._request("POST", self._path("dlq", entry_id, "retry"))
        return data if isinstance(data, dict) else {}

    def delete_dlq(self, entry_id: str) -> None:
        """DLQ yozuvini o'chiradi (hal qilindi deb belgilaydi)."""
        self._request("DELETE", self._path("dlq", entry_id))

    # ------------------------------------------------------------------
    # Webhook'lar
    # ------------------------------------------------------------------

    def create_webhook(
        self,
        url: str,
        events: Iterable[str],
        *,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Webhook yaratadi.

        `events` — `job.queued`, `job.succeeded`, `job.failed` kabi hodisalar
        ro'yxati. Javobda `secret` qaytadi — imzoni tekshirish uchun saqlang.
        """
        if not url:
            raise ValidationError(message="webhook `url` bo'sh bo'lishi mumkin emas")
        event_list = [str(_value_of(event)) for event in events]
        if not event_list:
            raise ValidationError(message="kamida bitta hodisa (`events`) ko'rsatilishi kerak")
        body: dict[str, Any] = {"url": url, "events": event_list}
        if description is not None:
            body["description"] = description
        data = self._request("POST", self._path("webhooks"), json_body=body)
        return data if isinstance(data, dict) else {}

    def list_webhooks(self) -> list[dict[str, Any]]:
        """Webhook'lar ro'yxatini qaytaradi."""
        data = self._request("GET", self._path("webhooks"))
        return [item for item in self._extract_items(data, "webhooks") if isinstance(item, dict)]

    def delete_webhook(self, webhook_id: str) -> None:
        """Webhook'ni o'chiradi."""
        self._request("DELETE", self._path("webhooks", webhook_id))

    # ------------------------------------------------------------------
    # Billing va salomatlik
    # ------------------------------------------------------------------

    def usage(self) -> dict[str, Any]:
        """Joriy davr uchun foydalanish statistikasini qaytaradi."""
        data = self._request("GET", self._path("billing", "usage"))
        return data if isinstance(data, dict) else {}

    def ping(self) -> bool:
        """Server javob berayotganini tekshiradi (`/health`).

        Xato bo'lsa istisno tashlamaydi — `False` qaytaradi, shuning uchun
        monitoring kodida qulay.
        """
        try:
            self._request("GET", "/health")
        except (DurablAPIError, DurablConnectionError, DurablTimeoutError):
            return False
        return True


# ---------------------------------------------------------------------------
# Asinxron mijoz
# ---------------------------------------------------------------------------


class AsyncDurablClient(_BaseClient):
    """Durabl API bilan ishlash uchun asinxron mijoz.

    Misol:

        async with AsyncDurablClient(api_key="durabl_xxx") as client:
            job = await client.submit(code="print('salom')")
            result = await job.wait(timeout=60)
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        *,
        timeout: float | None = None,
        max_retries: int | None = None,
        retry_backoff: float | None = None,
        retry_max_delay: float | None = None,
        verify_ssl: bool | None = None,
        headers: Mapping[str, str] | None = None,
        config: DurablConfig | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            retry_backoff=retry_backoff,
            retry_max_delay=retry_max_delay,
            verify_ssl=verify_ssl,
            headers=headers,
            config=config,
        )
        self._owns_http = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            verify=self.config.verify_ssl,
            follow_redirects=True,
        )

    # ------------------------------------------------------------------
    # Hayot sikli
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """HTTP ulanishlarini yopadi."""
        if self._owns_http:
            await self._http.aclose()

    #: `close()` nomi ham qulaylik uchun qoldirilgan (aclose bilan bir xil).
    close = aclose

    async def __aenter__(self) -> AsyncDurablClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def _sleep(self, seconds: float) -> None:
        """Kutish (testlarda almashtirib qo'yish mumkin)."""
        if seconds > 0:
            await asyncio.sleep(seconds)

    # ------------------------------------------------------------------
    # Quyi qatlam
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any = None,
        idempotency_key: str | None = None,
    ) -> Any:
        """So'rov yuboradi, kerak bo'lsa qayta urinadi, javob tanasini qaytaradi."""
        headers = self._request_headers(idempotency_key)
        query = _clean_params(params)
        attempt = 0
        while True:
            try:
                response = await self._http.request(
                    method, path, params=query, json=json_body, headers=headers
                )
            except httpx.TimeoutException as exc:
                if attempt < self.config.max_retries:
                    await self._sleep(self._compute_retry_delay(attempt))
                    attempt += 1
                    continue
                raise DurablTimeoutError(
                    f"{method} {path} so'rovi {self.config.timeout:g} soniyada javob bermadi"
                ) from exc
            except httpx.HTTPError as exc:
                if attempt < self.config.max_retries:
                    await self._sleep(self._compute_retry_delay(attempt))
                    attempt += 1
                    continue
                raise DurablConnectionError(
                    f"{self.config.base_url} manziliga ulanib bo'lmadi: {exc}"
                ) from exc

            if response.status_code >= 400:
                if self._is_retryable(response.status_code) and attempt < self.config.max_retries:
                    delay = self._compute_retry_delay(
                        attempt, self._parse_retry_after(response.headers)
                    )
                    await self._sleep(delay)
                    attempt += 1
                    continue
                raise self._error_for(response)
            return self._parse_body(response)

    # ------------------------------------------------------------------
    # Job'lar
    # ------------------------------------------------------------------

    async def submit(
        self,
        code: str,
        runtime: str = "python",
        *,
        payload: Mapping[str, Any] | None = None,
        env_vars: Mapping[str, str] | None = None,
        timeout: int = 30,
        max_retries: int = 3,
        priority: str = "normal",
        scheduled_at: datetime | str | None = None,
        cron: str | None = None,
        tags: Iterable[str] | None = None,
        memory_mb: int | None = None,
        cpus: float | None = None,
        idempotency_key: str | None = None,
    ) -> AsyncJobHandle:
        """Kodni bajarishga yuboradi (sinxron variant bilan bir xil imzo)."""
        body = self._submit_body(
            code,
            runtime,
            payload=payload,
            env_vars=env_vars,
            timeout=timeout,
            max_retries=max_retries,
            priority=priority,
            scheduled_at=scheduled_at,
            cron=cron,
            tags=tags,
            memory_mb=memory_mb,
            cpus=cpus,
            idempotency_key=idempotency_key,
        )
        data = await self._request(
            "POST", self._path("jobs"), json_body=body, idempotency_key=idempotency_key
        )
        job = self._remember(Job.from_dict(data))
        return AsyncJobHandle(self, job)

    async def get_job(self, job_id: str) -> Job:
        """Bitta job'ning to'liq holatini o'qiydi."""
        data = await self._request("GET", self._path("jobs", job_id))
        return self._remember(Job.from_dict(data))

    async def get_status(self, job_id: str) -> JobStatus:
        """Job holatini qaytaradi."""
        job = await self.get_job(job_id)
        return job.status

    async def get_result(self, job_id: str) -> JobResult:
        """Job natijasini oladi."""
        data = await self._request("GET", self._path("jobs", job_id, "result"))
        return self._result_or_snapshot(data, self.last_job(job_id))

    async def wait_for_result(
        self,
        job_id: str,
        timeout: float = 60.0,
        poll_interval: float = 1.0,
        *,
        raise_on_failure: bool = False,
    ) -> JobResult:
        """Job tugashini kutadi (polling intervali asta oshadi)."""
        deadline = time.monotonic() + max(0.0, float(timeout))
        interval = max(MIN_POLL_INTERVAL, float(poll_interval))
        job: Job | None = None
        while True:
            job = await self.get_job(job_id)
            if job.status.is_finished:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise self._timeout_error(job_id, timeout, job)
            await self._sleep(min(interval, remaining))
            interval = self._next_poll_interval(interval)

        try:
            result = await self.get_result(job_id)
        except ResultNotReadyError:
            result = JobResult.from_job(job)
        return self._check_failure(result, job, raise_on_failure)

    async def cancel(self, job_id: str) -> Job:
        """Job'ni bekor qiladi."""
        data = await self._request("POST", self._path("jobs", job_id, "cancel"))
        if isinstance(data, dict) and not (data.get("id") or data.get("job_id")):
            return await self.get_job(job_id)
        return self._remember(Job.from_dict(data))

    async def list_jobs_page(
        self, *, page: int = 1, page_size: int = 20, **filters: Any
    ) -> JobPage:
        """Bitta sahifadagi job'larni qaytaradi."""
        params = {"page": page, "page_size": page_size, **filters}
        data = await self._request("GET", self._path("jobs"), params=params)
        return self._job_page(data)

    async def list_jobs(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        all_pages: bool = False,
        limit: int | None = None,
        **filters: Any,
    ) -> list[Job]:
        """Job'lar ro'yxatini qaytaradi (`all_pages=True` — barcha sahifalar)."""
        collected: list[Job] = []
        current = max(1, int(page))
        while True:
            result_page = await self.list_jobs_page(page=current, page_size=page_size, **filters)
            collected.extend(result_page.items)
            if limit is not None and len(collected) >= limit:
                return collected[:limit]
            if not all_pages or not result_page.items or not result_page.pagination.has_next:
                break
            current += 1
        return collected

    async def get_logs(
        self,
        job_id: str,
        *,
        after_sequence: int | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Job loglarini qaytaradi."""
        params = {"after_sequence": after_sequence, "limit": limit}
        data = await self._request("GET", self._path("jobs", job_id, "logs"), params=params)
        entries = self._extract_items(data, "entries", "logs")
        return [item for item in entries if isinstance(item, dict)]

    # ------------------------------------------------------------------
    # DLQ
    # ------------------------------------------------------------------

    async def list_dlq(
        self, *, page: int = 1, page_size: int = 20, **filters: Any
    ) -> list[dict[str, Any]]:
        """DLQ yozuvlarini qaytaradi."""
        params = {"page": page, "page_size": page_size, **filters}
        data = await self._request("GET", self._path("dlq"), params=params)
        return [item for item in self._extract_items(data, "entries") if isinstance(item, dict)]

    async def retry_dlq(self, entry_id: str) -> dict[str, Any]:
        """DLQ yozuvini qayta urinishga yuboradi."""
        data = await self._request("POST", self._path("dlq", entry_id, "retry"))
        return data if isinstance(data, dict) else {}

    async def delete_dlq(self, entry_id: str) -> None:
        """DLQ yozuvini o'chiradi."""
        await self._request("DELETE", self._path("dlq", entry_id))

    # ------------------------------------------------------------------
    # Webhook'lar
    # ------------------------------------------------------------------

    async def create_webhook(
        self,
        url: str,
        events: Iterable[str],
        *,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Webhook yaratadi."""
        if not url:
            raise ValidationError(message="webhook `url` bo'sh bo'lishi mumkin emas")
        event_list = [str(_value_of(event)) for event in events]
        if not event_list:
            raise ValidationError(message="kamida bitta hodisa (`events`) ko'rsatilishi kerak")
        body: dict[str, Any] = {"url": url, "events": event_list}
        if description is not None:
            body["description"] = description
        data = await self._request("POST", self._path("webhooks"), json_body=body)
        return data if isinstance(data, dict) else {}

    async def list_webhooks(self) -> list[dict[str, Any]]:
        """Webhook'lar ro'yxatini qaytaradi."""
        data = await self._request("GET", self._path("webhooks"))
        return [item for item in self._extract_items(data, "webhooks") if isinstance(item, dict)]

    async def delete_webhook(self, webhook_id: str) -> None:
        """Webhook'ni o'chiradi."""
        await self._request("DELETE", self._path("webhooks", webhook_id))

    # ------------------------------------------------------------------
    # Billing va salomatlik
    # ------------------------------------------------------------------

    async def usage(self) -> dict[str, Any]:
        """Foydalanish statistikasini qaytaradi."""
        data = await self._request("GET", self._path("billing", "usage"))
        return data if isinstance(data, dict) else {}

    async def ping(self) -> bool:
        """Server javob berayotganini tekshiradi."""
        try:
            await self._request("GET", "/health")
        except (DurablAPIError, DurablConnectionError, DurablTimeoutError):
            return False
        return True


__all__ = [
    "MAX_POLL_INTERVAL",
    "RETRYABLE_STATUS_CODES",
    "AsyncDurablClient",
    "DurablClient",
]
