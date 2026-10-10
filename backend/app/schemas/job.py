"""Durabl — job (ish) schema'lari: yuborish, o'qish, filtrlash, natija.

`JobCreate` — platformaning asosiy kirish nuqtasi. Uning chegaralari
`settings`dan olinadi (`MAX_CODE_SIZE_BYTES`, `MIN/MAX_TIMEOUT_SECONDS`,
`MAX_ALLOWED_RETRIES`), shuning uchun .env o'zgarsa OpenAPI hujjati ham
avtomatik mos keladi.

Schema qatlamida faqat **shaklga xos** tekshiruvlar bajariladi (tur, chegara,
o'zaro mos kelish). Reja (plan) limitlari, kod xavfsizligi va cron'ning to'liq
semantikasi service qatlamida (`job_service`, `utils.validators`) tekshiriladi.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, computed_field, field_validator, model_validator

from app.config import settings
from app.constants import (
    MAX_ENV_NAME_LENGTH,
    MAX_ENV_VALUE_LENGTH,
    MAX_ENV_VARS,
    MAX_TAG_LENGTH,
    MAX_TAGS,
    FailureReason,
    HttpMethod,
    JobKind,
    JobStatus,
    Priority,
    Runtime,
)
from app.exceptions import DurablError
from app.schemas.base import DurablSchema, ORMSchema
from app.schemas.execution import ExecutionLogRead, ExecutionSummary
from app.utils.time_utils import ensure_utc, utcnow
from app.utils.validators import validate_webhook_url

#: Rejalashtirilgan vaqt uchun ruxsat etilgan "orqaga" chetlanish (soniya).
#: Mijoz va server soatlari to'liq sinxron bo'lmasligi mumkin.
SCHEDULE_CLOCK_SKEW_SECONDS = 5.0

#: Teg va muhit o'zgaruvchisi chegaralari `app.constants` dan keladi — ular
#: `app/utils/validators.py` bilan BIR XIL bo'lishi shart (aks holda 422'dan
#: o'tgan so'rov service qatlamida yiqiladi). Shu yerda faqat re-eksport.
MAX_ENV_KEY_LENGTH = MAX_ENV_NAME_LENGTH

#: Resurs chegaralari (yakuniy qiymat reja limitiga qarab kesiladi).
MIN_MEMORY_MB = 64
MAX_MEMORY_MB = 8_192
MIN_CPUS = 0.1
MAX_CPUS = 8.0

#: `JobFilter` da ruxsat etilgan tartiblash ustunlari.
JOB_SORT_FIELDS: frozenset[str] = frozenset(
    {"created_at", "updated_at", "scheduled_at", "started_at", "finished_at", "duration_ms"}
)

#: Cron ifodasidagi maydonlar soni (5 — klassik, 6 — soniyali variant).
_CRON_FIELD_COUNTS: frozenset[int] = frozenset({5, 6})

#: `kind=HTTP` uchun chegaralar.
MAX_TARGET_URL_LENGTH = 2_048
MAX_HTTP_HEADERS = 32
MAX_HTTP_HEADER_NAME_LENGTH = 128
MAX_HTTP_HEADER_VALUE_LENGTH = 2_048

#: Durabl o'zi qo'yadigan header prefiksi. Mijoz shu prefiksli header
#: bersa, so'rov REJECT qilinadi — jim ustidan yozish o'rniga. Sababi:
#: `HttpRunner` ularni baribir bosib o'tadi, ya'ni mijoz "men
#: `X-Durabl-Attempt` ni o'zgartirdim" deb o'ylab, aslida hech narsa
#: qilmagan bo'lardi. Aniq xato tushunarliroq.
RESERVED_HEADER_PREFIX = "x-durabl-"


# ---------------------------------------------------------------------------
# So'rovlar
# ---------------------------------------------------------------------------


class JobCreate(DurablSchema):
    """`POST /jobs` — yangi job yuborish (ikki rejim).

    ## Ikki rejim bitta endpointda

    * `kind="code"` (standart) — `code` va `runtime` beriladi, kod
      sandboxda bajariladi.
    * `kind="http"` — `target_url` beriladi, Durabl mijozning
      endpointini chaqiradi.

    Alohida endpoint (`POST /jobs/http`) ATAYLAB yasalmadi: ikkisi ayni
    jadvalda yashaydi, ayni hayot siklidan o'tadi va ayni ro'yxat /
    filtr / DLQ sahifalarida ko'rinadi. Ikki endpoint bo'lsa, bu
    umumiylik API darajasida yashirilib qolardi.

    `kind` standart qiymati `code` — mavjud mijozlar `kind` yubormasa
    ham xulq o'zgarmaydi.

    ## Nega mos kelmaydigan maydon JIM O'TKAZILMAYDI

    `kind=http` bilan `code` yuborilsa, so'rov RAD ETILADI. Jim
    e'tiborsiz qoldirish yomonroq: mijoz kodini yuborib, u hech qachon
    bajarilmaganini bilmay qolardi.
    """

    kind: JobKind = Field(
        default=JobKind.CODE,
        description=(
            "Job turi: `code` — kod sandboxda bajariladi; "
            "`http` — ko'rsatilgan endpoint chaqiriladi."
        ),
        examples=[JobKind.CODE.value],
    )
    code: Annotated[str, Field(min_length=1, max_length=settings.MAX_CODE_SIZE_BYTES)] | None = (
        Field(
            default=None,
            description=(
                "Bajarilishi kerak bo'lgan manba kod — `kind=code` uchun SHART. "
                f"Maksimal hajm: {settings.MAX_CODE_SIZE_BYTES} bayt (UTF-8)."
            ),
            examples=["print('Salom dunyo')"],
        )
    )
    runtime: Runtime | None = Field(
        default=None,
        description=(
            "Bajarish muhiti: `python` yoki `node`. `kind=code` uchun SHART, "
            "`kind=http` uchun ma'nosiz (berilmaydi)."
        ),
        examples=[Runtime.PYTHON.value],
    )
    target_url: Annotated[str, Field(min_length=1, max_length=MAX_TARGET_URL_LENGTH)] | None = (
        Field(
            default=None,
            description=(
                "Chaqiriladigan endpoint — `kind=http` uchun SHART. "
                "SSRF tekshiruvidan o'tadi: ichki va mahalliy manzillar taqiqlangan."
            ),
            examples=["https://api.example.com/durabl/nightly-report"],
        )
    )
    http_method: HttpMethod | None = Field(
        default=None,
        description="HTTP metodi (`kind=http`). Berilmasa `POST`.",
        examples=[HttpMethod.POST.value],
    )
    http_headers: dict[str, str] | None = Field(
        default=None,
        description=(
            f"Qo'shimcha so'rov header'lari (maksimal {MAX_HTTP_HEADERS} ta). "
            "`X-Durabl-*` prefiksi band — Durabl o'z header'larini qo'yadi."
        ),
        examples=[{"Authorization": "Bearer ..."}],
    )
    priority: Priority = Field(
        default=Priority.NORMAL,
        description="Navbat ustuvorligi: `high`, `normal` yoki `low`",
    )
    payload: dict[str, Any] | None = Field(
        default=None,
        description="Kodga uzatiladigan argumentlar (JSON obyekt)",
        examples=[{"url": "https://example.com/img.jpg"}],
    )
    env_vars: dict[str, str] | None = Field(
        default=None,
        description="Sandbox ichidagi muhit o'zgaruvchilari (nomlar `A-Z0-9_`)",
        examples=[{"API_MODE": "fast"}],
    )
    timeout_seconds: Annotated[
        int,
        Field(ge=settings.MIN_TIMEOUT_SECONDS, le=settings.MAX_TIMEOUT_SECONDS),
    ] = Field(
        default=settings.DEFAULT_TIMEOUT_SECONDS,
        description=(
            "Bajarish uchun vaqt limiti (soniya). "
            f"Oraliq: {settings.MIN_TIMEOUT_SECONDS}–{settings.MAX_TIMEOUT_SECONDS}."
        ),
    )
    max_retries: Annotated[int, Field(ge=0, le=settings.MAX_ALLOWED_RETRIES)] = Field(
        default=settings.DEFAULT_MAX_RETRIES,
        description=(
            "Muvaffaqiyatsizlikda qayta urinishlar soni (0 — urinmaslik). "
            f"Maksimal: {settings.MAX_ALLOWED_RETRIES}."
        ),
    )
    scheduled_at: datetime | None = Field(
        default=None,
        description="Job shu vaqtda bajariladi (ISO-8601, UTC). O'tmishda bo'lishi mumkin emas.",
    )
    cron_expression: Annotated[str, Field(min_length=9, max_length=100)] | None = Field(
        default=None,
        description="Takrorlanuvchi job uchun cron ifodasi (5 yoki 6 maydon)",
        examples=["*/5 * * * *"],
    )
    tags: list[Annotated[str, Field(min_length=1, max_length=MAX_TAG_LENGTH)]] | None = Field(
        default=None,
        description=f"Guruhlash uchun teglar (maksimal {MAX_TAGS} ta, takrorlanmaydi)",
        examples=[["etl", "nightly"]],
    )
    memory_mb: Annotated[int, Field(ge=MIN_MEMORY_MB, le=MAX_MEMORY_MB)] | None = Field(
        default=None,
        description="Sandbox xotira limiti (MB). Berilmasa reja standartidan olinadi.",
    )
    cpus: Annotated[float, Field(ge=MIN_CPUS, le=MAX_CPUS)] | None = Field(
        default=None,
        description="Sandbox CPU limiti (yadro ulushi). Berilmasa reja standartidan olinadi.",
    )
    idempotency_key: Annotated[str, Field(min_length=1, max_length=255)] | None = Field(
        default=None,
        description=(
            "Takrorlanmaslik kaliti. `Idempotency-Key` header berilsa, header qiymati ustun turadi."
        ),
    )

    @field_validator("code")
    @classmethod
    def _check_code_size(cls, value: str | None) -> str | None:
        """Kod hajmini baytda tekshiradi (`max_length` belgi sonini sanaydi)."""
        if value is None:
            return None
        size = len(value.encode("utf-8"))
        if size > settings.MAX_CODE_SIZE_BYTES:
            raise ValueError(f"Kod hajmi {size} bayt — limit {settings.MAX_CODE_SIZE_BYTES} bayt")
        return value

    @field_validator("http_headers")
    @classmethod
    def _check_http_headers(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        """Header'lar sonini, nomini va uzunligini tekshiradi.

        `X-Durabl-*` prefiksli header RAD ETILADI — `HttpRunner` ularni
        baribir bosib o'tadi, ya'ni jim qabul qilish mijozni chalg'itadi.
        """
        if value is None:
            return None
        if len(value) > MAX_HTTP_HEADERS:
            raise ValueError(f"Header'lar soni {MAX_HTTP_HEADERS} dan oshmasligi kerak")
        for key, item in value.items():
            if not key.strip():
                raise ValueError("Header nomi bo'sh bo'lishi mumkin emas")
            if len(key) > MAX_HTTP_HEADER_NAME_LENGTH:
                raise ValueError(f"'{key}' nomi {MAX_HTTP_HEADER_NAME_LENGTH} belgidan uzun")
            if key.lower().startswith(RESERVED_HEADER_PREFIX):
                raise ValueError(f"'{key}' band: `X-Durabl-*` header'larini Durabl o'zi qo'yadi")
            if len(item) > MAX_HTTP_HEADER_VALUE_LENGTH:
                raise ValueError(f"'{key}' qiymati {MAX_HTTP_HEADER_VALUE_LENGTH} belgidan uzun")
        return value

    @field_validator("env_vars")
    @classmethod
    def _check_env_vars(cls, value: dict[str, str] | None) -> dict[str, str] | None:
        """Muhit o'zgaruvchilari nomi va hajmini tekshiradi."""
        if value is None:
            return None
        if len(value) > MAX_ENV_VARS:
            raise ValueError(f"Muhit o'zgaruvchilari soni {MAX_ENV_VARS} dan oshmasligi kerak")
        for key, item in value.items():
            if not key or len(key) > MAX_ENV_KEY_LENGTH:
                raise ValueError(f"'{key}' nomi bo'sh yoki {MAX_ENV_KEY_LENGTH} belgidan uzun")
            if not (key[0].isalpha() or key[0] == "_"):
                raise ValueError(f"'{key}' harf yoki '_' bilan boshlanishi kerak")
            if not all(char.isalnum() or char == "_" for char in key):
                raise ValueError(f"'{key}' faqat harf, raqam va '_' dan tashkil topishi kerak")
            if len(item) > MAX_ENV_VALUE_LENGTH:
                raise ValueError(f"'{key}' qiymati {MAX_ENV_VALUE_LENGTH} belgidan uzun")
        return value

    @field_validator("tags")
    @classmethod
    def _check_tags(cls, value: list[str] | None) -> list[str] | None:
        """Teglar sonini tekshiradi va takrorlanishni olib tashlaydi (tartib saqlanadi)."""
        if value is None:
            return None
        unique: list[str] = []
        for tag in value:
            if tag not in unique:
                unique.append(tag)
        if len(unique) > MAX_TAGS:
            raise ValueError(f"Teglar soni {MAX_TAGS} dan oshmasligi kerak")
        return unique

    @field_validator("cron_expression")
    @classmethod
    def _check_cron_shape(cls, value: str | None) -> str | None:
        """Cron ifodasining maydon sonini tekshiradi.

        To'liq semantik tekshiruv (croniter) `utils.validators.validate_cron`da —
        bu yerda faqat shakl nazorat qilinadi.
        """
        if value is None:
            return None
        fields = value.split()
        if len(fields) not in _CRON_FIELD_COUNTS:
            raise ValueError(
                "Cron ifodasi 5 yoki 6 maydondan tashkil topishi kerak (masalan `*/5 * * * *`)"
            )
        return " ".join(fields)

    @model_validator(mode="after")
    def _check_kind_fields(self) -> JobCreate:
        """Rejimga mos maydonlar berilganini tekshiradi.

        Qoida sodda: har rejim o'z maydonlarini TALAB qiladi va
        boshqasining maydonlarini RAD ETADI. Jim e'tiborsiz qoldirish
        yo'q — mijoz nimani noto'g'ri yuborganini darhol biladi.

        SSRF tekshiruvi ham shu yerda: mijoz 422 ni DARHOL oladi,
        job yaratilib keyin bajarilish paytida yiqilishini kutmaydi.
        Bajarishdan oldin `HttpRunner` tekshiruvni QAYTA o'tkazadi —
        DNS yozuvi oradan o'zgarishi mumkin.
        """
        if self.kind is JobKind.HTTP:
            if self.target_url is None:
                raise ValueError("`kind=http` uchun `target_url` berilishi shart")
            if self.code is not None:
                raise ValueError(
                    "`kind=http` bilan `code` berilmaydi — HTTP job kod bajarmaydi, "
                    "mijozning endpointini chaqiradi"
                )
            if self.env_vars is not None:
                raise ValueError(
                    "`kind=http` bilan `env_vars` berilmaydi — ular sandbox muhiti "
                    "uchun; HTTP so'rovga `http_headers` ishlatiladi"
                )
            try:
                validate_webhook_url(self.target_url)
            except DurablError as exc:
                raise ValueError(f"`target_url` yaroqsiz: {exc.message}") from exc
            return self

        # kind == CODE
        if self.code is None:
            raise ValueError("`kind=code` uchun `code` berilishi shart")
        if self.runtime is None:
            raise ValueError("`kind=code` uchun `runtime` berilishi shart (`python` yoki `node`)")
        http_only = {
            "target_url": self.target_url,
            "http_method": self.http_method,
            "http_headers": self.http_headers,
        }
        extra = sorted(name for name, value in http_only.items() if value is not None)
        if extra:
            raise ValueError(
                f"{extra} faqat `kind=http` uchun — kod rejimida e'tiborsiz qolmasligi "
                "uchun rad etiladi"
            )
        return self

    @model_validator(mode="after")
    def _check_scheduling(self) -> JobCreate:
        """Rejalashtirish maydonlarining o'zaro mosligini tekshiradi."""
        if self.scheduled_at is not None and self.cron_expression is not None:
            raise ValueError(
                "`scheduled_at` va `cron_expression` birgalikda berilmaydi — "
                "bir martalik yoki takrorlanuvchi job'dan bittasini tanlang"
            )
        if self.scheduled_at is not None:
            moment = ensure_utc(self.scheduled_at)
            assert moment is not None  # ensure_utc faqat None uchun None qaytaradi
            if (utcnow() - moment).total_seconds() > SCHEDULE_CLOCK_SKEW_SECONDS:
                raise ValueError("`scheduled_at` o'tmishda bo'lishi mumkin emas")
        return self


class JobFilter(DurablSchema):
    """`GET /jobs` query parametrlari."""

    status: JobStatus | None = Field(default=None, description="Holat bo'yicha filtr")
    kind: JobKind | None = Field(default=None, description="Job turi bo'yicha filtr")
    runtime: Runtime | None = Field(default=None, description="Bajarish muhiti bo'yicha filtr")
    priority: Priority | None = Field(default=None, description="Ustuvorlik bo'yicha filtr")
    failure_reason: FailureReason | None = Field(
        default=None, description="Muvaffaqiyatsizlik sababi bo'yicha filtr"
    )
    tag: Annotated[str, Field(min_length=1, max_length=MAX_TAG_LENGTH)] | None = Field(
        default=None, description="Shu teg qo'yilgan job'lar"
    )
    search: Annotated[str, Field(min_length=1, max_length=255)] | None = Field(
        default=None, description="Kod va teglar bo'yicha matnli qidiruv"
    )
    start: datetime | None = Field(default=None, description="Oraliq boshlanishi (ISO-8601, UTC)")
    end: datetime | None = Field(default=None, description="Oraliq tugashi (ISO-8601, UTC)")
    sort_by: str = Field(default="created_at", description="Tartiblash ustuni")
    sort_order: Literal["asc", "desc"] = Field(default="desc", description="Tartiblash yo'nalishi")

    @model_validator(mode="after")
    def _check_filter(self) -> JobFilter:
        """Oraliq mantiqan to'g'ri va tartiblash ustuni ruxsat etilganmi."""
        if self.start is not None and self.end is not None and self.start > self.end:
            raise ValueError("`start` qiymati `end`dan keyin bo'lishi mumkin emas")
        if self.sort_by not in JOB_SORT_FIELDS:
            raise ValueError(
                "`sort_by` noto'g'ri; ruxsat etilgan: " + ", ".join(sorted(JOB_SORT_FIELDS))
            )
        return self


# ---------------------------------------------------------------------------
# Javoblar
# ---------------------------------------------------------------------------


class JobSummary(ORMSchema):
    """Ro'yxat uchun yengil ko'rinish — `code` QAYTARILMAYDI."""

    id: uuid.UUID = Field(description="Job identifikatori")
    user_id: uuid.UUID = Field(description="Egasi — foydalanuvchi identifikatori")
    status: JobStatus = Field(description="Joriy holat")
    kind: JobKind = Field(
        default=JobKind.CODE,
        description="Job turi: `code` (sandboxda kod) yoki `http` (endpoint chaqiruvi)",
    )
    #: `kind=http` da bu maydon to'ldirilgan bo'ladi, lekin MA'NOSIZ —
    #: HTTP job kod bajarmaydi. Ustun `nullable=False` bo'lgani uchun
    #: neytral `python` yoziladi (`job_service.submit` ga qarang).
    runtime: Runtime = Field(description="Bajarish muhiti (`kind=code` uchun)")
    priority: Priority = Field(description="Navbat ustuvorligi")
    retry_count: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Bajarilgan qayta urinishlar soni"
    )
    max_retries: Annotated[int, Field(ge=0)] = Field(
        description="Ruxsat etilgan qayta urinishlar soni"
    )
    timeout_seconds: Annotated[int, Field(ge=1)] = Field(description="Vaqt limiti (soniya)")
    scheduled_at: datetime | None = Field(
        default=None, description="Rejalashtirilgan bajarish vaqti (UTC)"
    )
    cron_expression: str | None = Field(default=None, description="Cron ifodasi (bo'lsa)")
    queued_at: datetime | None = Field(default=None, description="Navbatga qo'yilgan vaqt (UTC)")
    started_at: datetime | None = Field(default=None, description="Bajarish boshlangan vaqt (UTC)")
    finished_at: datetime | None = Field(default=None, description="Tugagan vaqt (UTC)")
    cancelled_at: datetime | None = Field(default=None, description="Bekor qilingan vaqt (UTC)")
    exit_code: int | None = Field(default=None, description="Chiqish kodi")
    duration_ms: int | None = Field(default=None, description="Bajarish davomiyligi (ms)")
    failure_reason: FailureReason | None = Field(
        default=None, description="Muvaffaqiyatsizlik sababi"
    )
    correlation_id: str = Field(description="Butun zanjirni kuzatish identifikatori")
    tags: list[str] | None = Field(default=None, description="Teglar")
    created_at: datetime = Field(description="Job qabul qilingan vaqt (UTC)")
    updated_at: datetime | None = Field(default=None, description="Oxirgi o'zgartirish vaqti (UTC)")

    @computed_field(description="Holat yakuniymi (bundan keyin avtomatik o'zgarmaydi)")  # type: ignore[prop-decorator]
    @property
    def is_terminal(self) -> bool:
        """`JobStatus.is_terminal` ustidagi qobiq."""
        return self.status.is_terminal

    @computed_field(description="Jami sarflangan urinishlar soni (birinchi urinish ham hisobda)")  # type: ignore[prop-decorator]
    @property
    def attempts_used(self) -> int:
        """`retry_count + 1`."""
        return self.retry_count + 1


class JobRead(JobSummary):
    """Bitta job'ning to'liq tafsiloti — `code` va natija bilan."""

    code: str | None = Field(default=None, description="Yuborilgan manba kod (`kind=code` uchun)")
    target_url: str | None = Field(
        default=None, description="Chaqirilgan endpoint (`kind=http` uchun)"
    )
    http_method: HttpMethod | None = Field(
        default=None, description="HTTP metodi (`kind=http` uchun)"
    )
    #: Mijoz bergan header'lar. `Authorization` kabi maxfiy qiymatlar
    #: shu yerda QAYTADI — mijoz o'zi yuborgan, o'zi ko'radi. Boshqa
    #: foydalanuvchiga chiqmaydi: `JobService.get()` egalik tekshiradi.
    http_headers: dict[str, str] | None = Field(
        default=None, description="So'rov header'lari (`kind=http` uchun)"
    )
    response_status: int | None = Field(
        default=None, description="Javobning HTTP status kodi (`kind=http`, oxirgi urinish)"
    )
    payload: dict[str, Any] | None = Field(
        default=None, description="Kodga uzatilgan argumentlar yoki so'rov tanasi"
    )
    env_vars: dict[str, str] | None = Field(
        default=None, description="Sandbox muhit o'zgaruvchilari"
    )
    memory_mb: int | None = Field(default=None, description="Xotira limiti (MB)")
    cpus: float | None = Field(default=None, description="CPU limiti (yadro ulushi)")
    idempotency_key: str | None = Field(default=None, description="Takrorlanmaslik kaliti")
    result: Any | None = Field(default=None, description="Kod qaytargan qiymat (JSON)")
    stdout: str | None = Field(default=None, description="Standart chiqish oqimi")
    stderr: str | None = Field(default=None, description="Xato oqimi")
    error: str | None = Field(default=None, description="Durabl aniqlagan xato matni")


class JobStatusResponse(ORMSchema):
    """`GET /jobs/{id}` — yengil holat tekshiruvi (polling uchun arzon)."""

    id: uuid.UUID = Field(description="Job identifikatori")
    status: JobStatus = Field(description="Joriy holat")
    retry_count: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Bajarilgan qayta urinishlar soni"
    )
    max_retries: Annotated[int, Field(ge=0)] = Field(
        description="Ruxsat etilgan qayta urinishlar soni"
    )
    queued_at: datetime | None = Field(default=None, description="Navbatga qo'yilgan vaqt (UTC)")
    started_at: datetime | None = Field(default=None, description="Boshlangan vaqt (UTC)")
    finished_at: datetime | None = Field(default=None, description="Tugagan vaqt (UTC)")
    duration_ms: int | None = Field(default=None, description="Davomiylik (ms)")
    failure_reason: FailureReason | None = Field(
        default=None, description="Muvaffaqiyatsizlik sababi"
    )
    updated_at: datetime | None = Field(default=None, description="Oxirgi o'zgarish vaqti (UTC)")

    @computed_field(description="Natija olishga tayyormi")  # type: ignore[prop-decorator]
    @property
    def is_terminal(self) -> bool:
        """Holat yakuniymi."""
        return self.status.is_terminal


class JobResultResponse(ORMSchema):
    """`GET /jobs/{id}/result` — bajarish natijasi."""

    id: uuid.UUID = Field(description="Job identifikatori")
    status: JobStatus = Field(description="Yakuniy holat")
    result: Any | None = Field(default=None, description="Kod qaytargan qiymat (JSON)")
    stdout: str | None = Field(default=None, description="Standart chiqish oqimi")
    stderr: str | None = Field(default=None, description="Xato oqimi")
    exit_code: int | None = Field(default=None, description="Chiqish kodi")
    duration_ms: int | None = Field(default=None, description="Davomiylik (ms)")
    error: str | None = Field(default=None, description="Xato matni (bo'lsa)")
    failure_reason: FailureReason | None = Field(
        default=None, description="Muvaffaqiyatsizlik sababi"
    )
    retry_count: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Qancha marta qayta urinilgan"
    )
    finished_at: datetime | None = Field(default=None, description="Tugagan vaqt (UTC)")

    @computed_field(description="Job muvaffaqiyatli tugadimi")  # type: ignore[prop-decorator]
    @property
    def succeeded(self) -> bool:
        """Holat `success` bo'lsa `True`."""
        return self.status is JobStatus.SUCCESS


class JobCancelResponse(ORMSchema):
    """`POST /jobs/{id}/cancel` javobi."""

    id: uuid.UUID = Field(description="Job identifikatori")
    status: JobStatus = Field(description="Bekor qilingandan keyingi holat")
    cancelled_at: datetime | None = Field(default=None, description="Bekor qilingan vaqt (UTC)")
    message: str = Field(default="Job bekor qilindi", description="Inson o'qiydigan izoh")


class JobLogsResponse(ORMSchema):
    """`GET /jobs/{id}/logs` — loglar sahifasi (kursor: `sequence`)."""

    job_id: uuid.UUID = Field(description="Job identifikatori")
    execution_id: uuid.UUID | None = Field(
        default=None, description="Joriy (oxirgi) bajarish urinishi identifikatori"
    )
    entries: list[ExecutionLogRead] = Field(
        default_factory=list, description="Log yozuvlari (`sequence` bo'yicha o'sish tartibida)"
    )
    next_sequence: int | None = Field(
        default=None,
        description="Keyingi so'rovda `after_sequence` sifatida yuboriladigan qiymat",
    )
    has_more: bool = Field(default=False, description="Server tomonida yana log qoldimi")

    @computed_field(description="Shu sahifadagi yozuvlar soni")  # type: ignore[prop-decorator]
    @property
    def count(self) -> int:
        """`entries` uzunligi."""
        return len(self.entries)


class JobTimeline(ORMSchema):
    """`GET /jobs/{id}/timeline` — job hayot siklining vaqt o'qi.

    `job_service.timeline()` lug'at qaytaradi, shu schema uni shaklga soladi.
    """

    job_id: uuid.UUID = Field(description="Job identifikatori")
    status: JobStatus = Field(description="Joriy holat")
    created_at: datetime = Field(description="Qabul qilindi (UTC)")
    scheduled_at: datetime | None = Field(default=None, description="Rejalashtirilgan vaqt (UTC)")
    queued_at: datetime | None = Field(default=None, description="Navbatga qo'yildi (UTC)")
    started_at: datetime | None = Field(default=None, description="Bajarish boshlandi (UTC)")
    finished_at: datetime | None = Field(default=None, description="Tugadi (UTC)")
    cancelled_at: datetime | None = Field(default=None, description="Bekor qilindi (UTC)")
    queue_wait_ms: int | None = Field(default=None, description="Navbatda kutilgan vaqt (ms)")
    execution_ms: int | None = Field(default=None, description="Sof bajarish vaqti (ms)")
    total_ms: int | None = Field(
        default=None, description="Qabuldan yakungacha ketgan umumiy vaqt (ms)"
    )
    attempts: Annotated[int, Field(ge=0)] = Field(
        default=0, description="Bajarish urinishlari soni"
    )
    executions: list[ExecutionSummary] = Field(
        default_factory=list,
        description="Har bir bajarish urinishi — vaqt tartibida (retry tarixi)",
    )


__all__ = [
    "JOB_SORT_FIELDS",
    "MAX_CPUS",
    "MAX_ENV_KEY_LENGTH",
    "MAX_ENV_VALUE_LENGTH",
    "MAX_ENV_VARS",
    "MAX_MEMORY_MB",
    "MAX_TAGS",
    "MAX_TAG_LENGTH",
    "MIN_CPUS",
    "MIN_MEMORY_MB",
    "SCHEDULE_CLOCK_SKEW_SECONDS",
    "JobCancelResponse",
    "JobCreate",
    "JobFilter",
    "JobLogsResponse",
    "JobRead",
    "JobResultResponse",
    "JobStatusResponse",
    "JobSummary",
    "JobTimeline",
]
