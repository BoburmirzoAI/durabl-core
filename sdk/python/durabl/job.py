"""Job ma'lumot tuzilmalari: `JobStatus`, `Job`, `JobResult`, `JobHandle`.

Bu modul faqat ma'lumotni ifodalaydi va HTTP bilan ishlamaydi — `JobHandle`
chaqiruvlarni o'ziga berilgan mijozga (`DurablClient` / `AsyncDurablClient`)
yo'naltiradi. Shu sababli modul `client.py`ni ishga tushish vaqtida import
qilmaydi (aylanma import bo'lmasligi uchun faqat `TYPE_CHECKING` ostida).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any

from .exceptions import ValidationError

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi uchun
    from .client import AsyncDurablClient, DurablClient

#: Natijani dekorator orqali qaytarish uchun ishlatiladigan belgi.
#: Sandbox ichidagi kod `{"__durabl_result__": <qiymat>}` ni stdout'ga chiqaradi.
RESULT_MARKER = "__durabl_result__"


class JobStatus(str, Enum):
    """Job hayot sikli holatlari.

    Qiymatlar backend `app/constants.py:JobStatus` bilan bir xil (shartnoma):
    `pending | queued | running | success | failed | retrying | cancelled | dead_letter`.
    """

    PENDING = "pending"          # DB'ga yozildi, hali navbatga qo'yilmadi
    QUEUED = "queued"            # Navbatda, worker kutilmoqda
    RUNNING = "running"          # Sandbox'da bajarilmoqda
    SUCCESS = "success"          # Muvaffaqiyatli tugadi
    FAILED = "failed"            # Xato bilan tugadi
    RETRYING = "retrying"        # Backoff kutilmoqda, qayta urinadi
    CANCELLED = "cancelled"      # Mijoz bekor qildi
    DEAD_LETTER = "dead_letter"  # Barcha urinishlar tugadi -> DLQ

    def __str__(self) -> str:
        return str(self.value)

    @classmethod
    def parse(cls, value: Any) -> JobStatus:
        """Matn yoki enum qiymatini `JobStatus`ga aylantiradi.

        Noma'lum qiymat kelsa `ValidationError` beradi — bu SDK va backend
        versiyalari mos emasligini darhol ko'rsatadi.
        """
        if isinstance(value, cls):
            return value
        text = str(value or "").strip().lower()
        try:
            return cls(text)
        except ValueError as exc:
            raise ValidationError(
                message=f"Noma'lum job holati: {value!r}. SDK versiyasini yangilang.",
                details={"status": text},
            ) from exc

    @property
    def is_terminal(self) -> bool:
        """Yakuniy holatmi? (bundan keyin avtomatik o'zgarmaydi)

        Backend bilan bir xil ta'rif: `success`, `cancelled`, `dead_letter`.
        `failed` bu ro'yxatda yo'q, chunki undan `dead_letter` yoki qo'lda
        `queued` holatiga o'tish mumkin.
        """
        return self in _TERMINAL_STATUSES

    @property
    def is_finished(self) -> bool:
        """Bajarilish tugadimi? (polling shu holatda to'xtaydi)

        `is_terminal`dan farqi: `failed` ham tugagan hisoblanadi, chunki
        natija (stdout/stderr/exit_code) allaqachon mavjud.
        """
        return self in _FINISHED_STATUSES

    @property
    def is_active(self) -> bool:
        """Job hali tizimda harakatdami?"""
        return self in _ACTIVE_STATUSES

    @property
    def is_success(self) -> bool:
        """Muvaffaqiyatli tugadimi?"""
        return self is JobStatus.SUCCESS


_TERMINAL_STATUSES = frozenset(
    {JobStatus.SUCCESS, JobStatus.CANCELLED, JobStatus.DEAD_LETTER}
)
_FINISHED_STATUSES = frozenset(
    {JobStatus.SUCCESS, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.DEAD_LETTER}
)
_ACTIVE_STATUSES = frozenset(
    {JobStatus.PENDING, JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.RETRYING}
)


def parse_datetime(value: Any) -> datetime | None:
    """ISO-8601 matnni `datetime`ga aylantiradi (`...Z` ham qo'llanadi).

    Backend barcha sanalarni UTC'da, `Z` qo'shimchasi bilan yuboradi
    (CONTRACTS.md 12-bo'lim). Python 3.9/3.10 `fromisoformat` `Z` ni
    tushunmaydi — shuning uchun qo'lda `+00:00`ga almashtiriladi.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)

    text = str(value).strip()
    if text.endswith(("Z", "z")):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _as_int(value: Any) -> int | None:
    """Qiymatni `int`ga aylantiradi; bo'lmasa `None`."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_str(value: Any) -> str | None:
    """Qiymatni matnga aylantiradi; bo'sh bo'lsa `None`."""
    if value is None:
        return None
    text = value if isinstance(value, str) else str(value)
    return text or None


# ---------------------------------------------------------------------------
# Job
# ---------------------------------------------------------------------------


@dataclass
class Job:
    """Serverdagi bitta job holatining surati (snapshot).

    `raw` maydonida serverning to'liq javobi saqlanadi — SDK bilmagan yangi
    maydonlar yo'qolmaydi (`job.raw["memory_mb"]` kabi murojaat qilish mumkin).
    """

    id: str
    status: JobStatus = JobStatus.PENDING
    runtime: str = "python"
    priority: str = "normal"
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    retry_count: int = 0
    exit_code: int | None = None
    error: str | None = None
    tags: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Job:
        """Server javobidan `Job` yasaydi (`JobRead` schema shakli)."""
        if not isinstance(data, dict):
            raise ValidationError(
                message=f"Job javobi dict bo'lishi kerak, keldi: {type(data).__name__}"
            )

        job_id = data.get("id") or data.get("job_id")
        if not job_id:
            raise ValidationError(message="Job javobida `id` maydoni yo'q", details={"body": data})

        tags = data.get("tags")
        return cls(
            id=str(job_id),
            status=JobStatus.parse(data.get("status", JobStatus.PENDING)),
            runtime=str(data.get("runtime") or "python"),
            priority=str(data.get("priority") or "normal"),
            created_at=parse_datetime(data.get("created_at")),
            started_at=parse_datetime(data.get("started_at")),
            finished_at=parse_datetime(data.get("finished_at")),
            duration_ms=_as_int(data.get("duration_ms")),
            retry_count=_as_int(data.get("retry_count")) or 0,
            exit_code=_as_int(data.get("exit_code")),
            error=_as_str(data.get("error")),
            tags=list(tags) if isinstance(tags, (list, tuple)) else [],
            raw=dict(data),
        )

    @property
    def is_terminal(self) -> bool:
        """Job yakuniy holatdami? (`success`, `cancelled`, `dead_letter`)"""
        return self.status.is_terminal

    @property
    def is_success(self) -> bool:
        """Job muvaffaqiyatli tugadimi?"""
        return self.status is JobStatus.SUCCESS

    @property
    def is_finished(self) -> bool:
        """Bajarilish tugadimi? (`failed` ham shu ro'yxatda)"""
        return self.status.is_finished

    @property
    def duration_seconds(self) -> float | None:
        """Bajarilish davomiyligi soniyada (ma'lum bo'lsa)."""
        return None if self.duration_ms is None else self.duration_ms / 1000.0

    def __str__(self) -> str:
        return f"Job({self.id}, {self.status})"


# ---------------------------------------------------------------------------
# JobResult
# ---------------------------------------------------------------------------


@dataclass
class JobResult:
    """Job bajarilishi natijasi.

    Maydonlar tartibi shartnoma bo'yicha: `stdout`, `stderr`, `result`,
    `exit_code`, `duration_ms`, `status`.
    """

    stdout: str = ""
    stderr: str = ""
    result: Any = None
    exit_code: int | None = None
    duration_ms: int | None = None
    status: JobStatus = JobStatus.PENDING
    job_id: str | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> JobResult:
        """Server javobidan natija yasaydi (`JobResultResponse` schema shakli)."""
        if not isinstance(data, dict):
            raise ValidationError(
                message=f"Natija javobi dict bo'lishi kerak, keldi: {type(data).__name__}"
            )
        return cls(
            stdout=str(data.get("stdout") or ""),
            stderr=str(data.get("stderr") or ""),
            result=data.get("result"),
            exit_code=_as_int(data.get("exit_code")),
            duration_ms=_as_int(data.get("duration_ms")),
            status=JobStatus.parse(data.get("status", JobStatus.SUCCESS)),
            job_id=_as_str(data.get("job_id") or data.get("id")),
            error=_as_str(data.get("error")),
            raw=dict(data),
        )

    @classmethod
    def from_job(cls, job: Job) -> JobResult:
        """`Job` suratidan natija yasaydi.

        `GET /jobs/{id}/result` natija bermagan holatlarda ishlatiladi
        (masalan, job bekor qilingan — natija yo'q, lekin holat ma'lum).
        """
        return cls(
            stdout=str(job.raw.get("stdout") or ""),
            stderr=str(job.raw.get("stderr") or ""),
            result=job.raw.get("result"),
            exit_code=job.exit_code,
            duration_ms=job.duration_ms,
            status=job.status,
            job_id=job.id,
            error=job.error,
            raw=dict(job.raw),
        )

    @property
    def ok(self) -> bool:
        """Natija muvaffaqiyatlimi?

        Shart: holat `success` va `exit_code` 0 (yoki ko'rsatilmagan).
        """
        return self.status is JobStatus.SUCCESS and self.exit_code in (0, None)

    @property
    def failed(self) -> bool:
        """Natija muvaffaqiyatsizmi? (`ok`ning teskarisi)"""
        return not self.ok

    def value(self, default: Any = None) -> Any:
        """Dekorator qaytargan qiymatni oladi.

        `@durabl.task` yasagan kod natijani stdout'ga
        `{"__durabl_result__": <qiymat>}` ko'rinishida chiqaradi. Bu metod shu
        belgini topib qiymatni qaytaradi; topilmasa `result` maydoni, u ham
        bo'lmasa `default` qaytariladi.
        """
        marker_value = extract_marker_value(self.stdout)
        if marker_value is not _MISSING:
            return marker_value
        if isinstance(self.result, dict) and RESULT_MARKER in self.result:
            return self.result[RESULT_MARKER]
        if self.result is not None:
            return self.result
        return default

    def __str__(self) -> str:
        return f"JobResult({self.status}, exit_code={self.exit_code}, ok={self.ok})"


class _Missing:
    """`None`dan farqlash uchun ichki "qiymat yo'q" belgisi."""

    def __repr__(self) -> str:  # pragma: no cover - faqat debug uchun
        return "<MISSING>"


_MISSING = _Missing()


def extract_marker_value(stdout: str) -> Any:
    """stdout ichidan `__durabl_result__` qiymatini ajratib oladi.

    Kod o'zi ham `print()` qilishi mumkin, shuning uchun qatorlar OXIRIDAN
    boshlab tekshiriladi va birinchi mos JSON qator olinadi. Topilmasa ichki
    `_MISSING` belgisi qaytariladi.
    """
    import json  # lokal import — modul yuklanishini tezlashtiradi

    if not stdout:
        return _MISSING
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line or RESULT_MARKER not in line:
            continue
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and RESULT_MARKER in parsed:
            return parsed[RESULT_MARKER]
    return _MISSING


# ---------------------------------------------------------------------------
# Handle'lar
# ---------------------------------------------------------------------------


class JobHandle:
    """Yuborilgan job ustida amal bajarish uchun qulay "dastak" (sinxron).

    `client.submit(...)` shu obyektni qaytaradi:

        job = client.submit(code="print(1)")
        result = job.wait(timeout=60)
        print(result.stdout)
    """

    __slots__ = ("_client", "_job", "id")

    def __init__(
        self,
        client: DurablClient,
        job: Job | None = None,
        *,
        job_id: str | None = None,
    ) -> None:
        if job is None and not job_id:
            raise ValidationError(message="JobHandle uchun `job` yoki `job_id` kerak")
        self._client = client
        self._job = job
        self.id: str = job.id if job is not None else str(job_id)

    @property
    def client(self) -> DurablClient:
        """Shu handle ishlatadigan mijoz."""
        return self._client

    @property
    def job(self) -> Job | None:
        """Oxirgi ma'lum job surati (hali o'qilmagan bo'lsa `None`)."""
        return self._job

    def refresh(self) -> Job:
        """Serverdan yangi suratni oladi va keshlaydi."""
        self._job = self._client.get_job(self.id)
        return self._job

    def status(self) -> JobStatus:
        """Joriy holatni serverdan o'qiydi."""
        return self.refresh().status

    def result(self) -> JobResult:
        """Natijani oladi (job tugamagan bo'lsa `ResultNotReadyError`)."""
        return self._client.get_result(self.id)

    def wait(
        self,
        timeout: float = 60.0,
        poll_interval: float = 1.0,
        *,
        raise_on_failure: bool = False,
    ) -> JobResult:
        """Job tugashini kutadi va natijani qaytaradi.

        Polling intervali asta oshadi (1s -> 2s -> ... maksimum 5s), shuning
        uchun uzoq job'larda serverga keraksiz so'rov yuborilmaydi.
        """
        result = self._client.wait_for_result(
            self.id,
            timeout=timeout,
            poll_interval=poll_interval,
            raise_on_failure=raise_on_failure,
        )
        self._job = self._client.last_job(self.id) or self._job
        return result

    def cancel(self) -> Job:
        """Job'ni bekor qiladi."""
        self._job = self._client.cancel(self.id)
        return self._job

    def logs(self) -> list[dict[str, Any]]:
        """Job loglarini (stdout/stderr yozuvlari) qaytaradi."""
        return self._client.get_logs(self.id)

    def __repr__(self) -> str:
        status = self._job.status if self._job else "?"
        return f"JobHandle(id={self.id!r}, status={status!s})"


class AsyncJobHandle:
    """`JobHandle`ning asinxron varianti (`AsyncDurablClient` uchun)."""

    __slots__ = ("_client", "_job", "id")

    def __init__(
        self,
        client: AsyncDurablClient,
        job: Job | None = None,
        *,
        job_id: str | None = None,
    ) -> None:
        if job is None and not job_id:
            raise ValidationError(message="AsyncJobHandle uchun `job` yoki `job_id` kerak")
        self._client = client
        self._job = job
        self.id: str = job.id if job is not None else str(job_id)

    @property
    def client(self) -> AsyncDurablClient:
        """Shu handle ishlatadigan asinxron mijoz."""
        return self._client

    @property
    def job(self) -> Job | None:
        """Oxirgi ma'lum job surati."""
        return self._job

    async def refresh(self) -> Job:
        """Serverdan yangi suratni oladi."""
        self._job = await self._client.get_job(self.id)
        return self._job

    async def status(self) -> JobStatus:
        """Joriy holatni o'qiydi."""
        job = await self.refresh()
        return job.status

    async def result(self) -> JobResult:
        """Natijani oladi."""
        return await self._client.get_result(self.id)

    async def wait(
        self,
        timeout: float = 60.0,
        poll_interval: float = 1.0,
        *,
        raise_on_failure: bool = False,
    ) -> JobResult:
        """Job tugashini kutadi va natijani qaytaradi."""
        result = await self._client.wait_for_result(
            self.id,
            timeout=timeout,
            poll_interval=poll_interval,
            raise_on_failure=raise_on_failure,
        )
        self._job = self._client.last_job(self.id) or self._job
        return result

    async def cancel(self) -> Job:
        """Job'ni bekor qiladi."""
        self._job = await self._client.cancel(self.id)
        return self._job

    async def logs(self) -> list[dict[str, Any]]:
        """Job loglarini qaytaradi."""
        return await self._client.get_logs(self.id)

    def __repr__(self) -> str:
        status = self._job.status if self._job else "?"
        return f"AsyncJobHandle(id={self.id!r}, status={status!s})"


@dataclass
class Pagination:
    """Ro'yxat javobidagi sahifalash meta-ma'lumoti.

    Shakl CONTRACTS.md 12-bo'limidan:
    `{page, page_size, total, total_pages, has_next, has_prev}`.
    """

    page: int = 1
    page_size: int = 20
    total: int = 0
    total_pages: int = 0
    has_next: bool = False
    has_prev: bool = False

    @classmethod
    def from_dict(cls, data: Any) -> Pagination:
        """Javobdagi `pagination` obyektini o'qiydi (bo'lmasa standart qiymatlar)."""
        if not isinstance(data, dict):
            return cls()
        return cls(
            page=_as_int(data.get("page")) or 1,
            page_size=_as_int(data.get("page_size")) or 20,
            total=_as_int(data.get("total")) or 0,
            total_pages=_as_int(data.get("total_pages")) or 0,
            has_next=bool(data.get("has_next")),
            has_prev=bool(data.get("has_prev")),
        )


@dataclass
class JobPage:
    """Bitta sahifadagi job'lar va sahifalash ma'lumoti."""

    items: list[Job] = field(default_factory=list)
    pagination: Pagination = field(default_factory=Pagination)

    def __iter__(self) -> Any:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)


__all__ = [
    "RESULT_MARKER",
    "AsyncJobHandle",
    "Job",
    "JobHandle",
    "JobPage",
    "JobResult",
    "JobStatus",
    "Pagination",
    "extract_marker_value",
    "parse_datetime",
]
