"""Durabl — development uchun namuna ma'lumot generatori (`make seed`).

Nima yaratadi:

* 2 foydalanuvchi: admin (`admin@durabl.dev`) va oddiy (`demo@durabl.dev`),
  ikkisiga ham API kalit — **xom kalit ekranga chiqariladi**, chunki u DB'da
  faqat SHA-256 hash ko'rinishida saqlanadi va boshqa hech qachon ko'rinmaydi.
* turli rejadagi obunalar (`ENTERPRISE` va `PRO`) + joriy va o'tgan
  davrlar uchun `usage_records`.
* 30 job: muvaffaqiyatli, xato, DLQ'da, bajarilayotgan, navbatda,
  kechiktirilgan va bekor qilingan; har xil runtime, ustuvorlik va teg bilan.
  `created_at` oxirgi 7 kun ichida tarqatilgan — dashboard grafiklari
  bo'sh ko'rinmasligi uchun.
* har job uchun 1-3 `execution` + har biriga stdout/stderr loglari.
* 2 webhook (biri faol, biri ketma-ket xatolar tufayli avtomatik o'chirilgan)
  va ularning yuborish tarixi.
* bir nechta `audit_log` yozuvi (admin harakatlari).

Xususiyatlari:

* **Idempotent** — ikki marta ishlatilsa ma'lumot TAKRORLANMAYDI: avval
  `admin@durabl.dev` emaili bo'yicha tekshiriladi, mavjud bo'lsa skript
  hech narsa yozmasdan chiqadi (`--reset` berilmagan bo'lsa).
* `--reset` — avval seed foydalanuvchilarini o'chiradi. Ularga tegishli
  hamma narsa DB darajasidagi `ON DELETE CASCADE` bilan ketadi, shuning
  uchun alohida tozalash kerak emas.
* **Deterministik** — `random.Random(SEED)` fiksirlangan urug' bilan, ya'ni
  har ishga tushirishda bir xil ma'lumot chiqadi (testlarni takrorlash uchun).

Ishlatish:

    cd backend
    python -m scripts.seed              # yaratish (mavjud bo'lsa — hech narsa)
    python -m scripts.seed --reset      # avval tozalab, qaytadan yaratish
    python -m scripts.seed --jobs 60    # ko'proq job

DIQQAT: skript jadvallar ALLAQACHON mavjud deb hisoblaydi — avval
`alembic upgrade head` bajarilishi kerak.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from random import Random
from typing import Any

from sqlalchemy import delete, func, select

# Skript `python scripts/seed.py` ko'rinishida ham ishlashi uchun
# `backend/` katalogini `sys.path`ga qo'shamiz (`python -m scripts.seed` da shart emas).
# `app.*` importlari ATAYLAB shundan KEYIN turadi, shuning uchun ularda E402
# o'chirilgan (ayni usul `alembic/env.py` da ham ishlatilgan).
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.constants import (  # noqa: E402
    AuditAction,
    DeliveryStatus,
    ExecutionStatus,
    FailureReason,
    JobStatus,
    LogStream,
    PlanType,
    Priority,
    Runtime,
    WebhookEvent,
)
from app.database import close_db, session_scope  # noqa: E402
from app.logging_config import get_logger, setup_logging  # noqa: E402
from app.models import (  # noqa: E402
    ApiKey,
    AuditLog,
    DlqEntry,
    Execution,
    ExecutionLog,
    Job,
    Subscription,
    UsageRecord,
    User,
    Webhook,
    WebhookDelivery,
)
from app.utils.security import (  # noqa: E402
    generate_api_key,
    generate_correlation_id,
    generate_webhook_secret,
    hash_password,
)
from app.utils.time_utils import month_key, start_of_month, utcnow  # noqa: E402

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Sozlamalar
# ---------------------------------------------------------------------------

#: Deterministik natija uchun fiksirlangan urug'
SEED = 20261004

#: Standart job soni
DEFAULT_JOB_COUNT = 30

#: Ma'lumot shu kun oralig'ida tarqatiladi (dashboard grafiklari uchun)
SPREAD_DAYS = 7

#: Seed foydalanuvchilari — `--reset` shu emaillar bo'yicha tozalaydi
ADMIN_EMAIL = "admin@durabl.dev"
ADMIN_PASSWORD = "Admin12345"  # development uchun ataylab ochiq
DEMO_EMAIL = "demo@durabl.dev"
DEMO_PASSWORD = "Demo12345"  # development uchun ataylab ochiq
SEED_EMAILS = (ADMIN_EMAIL, DEMO_EMAIL)

#: Job'larga tasodifiy tarqatiladigan teglar
TAG_POOL = ("nightly", "etl", "report", "image", "ci", "adhoc", "billing")

#: Namuna kodlar — `runtime` bo'yicha
CODE_SAMPLES: dict[Runtime, tuple[str, ...]] = {
    Runtime.PYTHON: (
        "def main(payload):\n"
        "    total = sum(payload.get('values', [1, 2, 3]))\n"
        "    print(f'yigindi={total}')\n"
        "    return {'total': total}\n",
        "import json\n\n\n"
        "def main(payload):\n"
        "    rows = payload.get('rows', [])\n"
        "    print(json.dumps({'qatorlar': len(rows)}))\n"
        "    return {'processed': len(rows)}\n",
        "def main(payload):\n    name = payload.get('name', 'dunyo')\n    return {'salom': name}\n",
    ),
    Runtime.NODE: (
        "module.exports = async function main(payload) {\n"
        "  const values = payload.values || [1, 2, 3];\n"
        "  const total = values.reduce((a, b) => a + b, 0);\n"
        "  console.log(`yigindi=${total}`);\n"
        "  return { total };\n"
        "};\n",
        "module.exports = async function main(payload) {\n"
        "  const rows = payload.rows || [];\n"
        "  console.log(JSON.stringify({ qatorlar: rows.length }));\n"
        "  return { processed: rows.length };\n"
        "};\n",
    ),
}

#: Xato job'lar uchun namuna xato matnlari (sabab -> (xato, stderr))
ERROR_SAMPLES: dict[FailureReason, tuple[str, str]] = {
    FailureReason.NON_ZERO_EXIT: (
        "KeyError: 'customer_id'",
        "Traceback (most recent call last):\n  File \"main.py\", line 4\nKeyError: 'customer_id'\n",
    ),
    FailureReason.TIMEOUT: (
        "Bajarish vaqti limitidan oshdi",
        "durabl: timeout — jarayon majburan to'xtatildi\n",
    ),
    FailureReason.OOM: (
        "Xotira limiti oshdi (konteyner o'ldirildi)",
        "durabl: out of memory — konteyner 137 kodi bilan tugadi\n",
    ),
    FailureReason.SANDBOX_ERROR: (
        "Sandbox konteyneri yaratilmadi",
        "durabl: sandbox unavailable\n",
    ),
}

#: Job holatlari taqsimoti: (holat, nechta)
STATUS_MIX: tuple[tuple[JobStatus, int], ...] = (
    (JobStatus.SUCCESS, 13),
    (JobStatus.FAILED, 4),
    (JobStatus.DEAD_LETTER, 4),
    (JobStatus.RUNNING, 3),
    (JobStatus.QUEUED, 2),
    (JobStatus.PENDING, 3),  # kechiktirilgan (`scheduled_at` kelajakda)
    (JobStatus.CANCELLED, 1),
)


# ---------------------------------------------------------------------------
# Chiqish (CLI hisoboti)
# ---------------------------------------------------------------------------


def _emit(line: str = "") -> None:
    """Foydalanuvchiga ko'rsatiladigan hisobot qatorini chiqaradi.

    `print()` ATAYLAB ishlatilmaydi (loyiha qoidasi), lekin bu matn log
    emas — bu skriptning asosiy NATIJASI (jadval va kirish ma'lumotlari),
    shuning uchun structlog orqali emas, bevosita `stdout`ga yoziladi.
    Diagnostika xabarlari esa `logger` orqali ketadi.
    """
    sys.stdout.write(f"{line}\n")


def _table(rows: list[tuple[str, str]], *, title: str, unit: str = "soni") -> None:
    """Ikki ustunli oddiy jadval chiqaradi (ustun kengligi sarlavhani ham hisobga oladi)."""
    width_left = max([len(left) for left, _ in rows] + [len(title)])
    width_right = max([len(right) for _, right in rows] + [len(unit)])
    border = f"+-{'-' * width_left}-+-{'-' * width_right}-+"
    _emit(border)
    _emit(f"| {title.ljust(width_left)} | {unit.rjust(width_right)} |")
    _emit(border)
    for left, right in rows:
        _emit(f"| {left.ljust(width_left)} | {right.rjust(width_right)} |")
    _emit(border)


# ---------------------------------------------------------------------------
# Hisoblagich
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class SeedReport:
    """Yaratilgan yozuvlar soni va ko'rsatiladigan kirish ma'lumotlari."""

    counts: dict[str, int] = field(default_factory=dict)
    credentials: list[tuple[str, str, str]] = field(default_factory=list)
    """`(email, parol, xom API kalit)` uchliklari."""

    def add(self, table: str, amount: int = 1) -> None:
        """Jadval hisoblagichini oshiradi."""
        self.counts[table] = self.counts.get(table, 0) + amount

    @property
    def total(self) -> int:
        """Jami yozuvlar soni."""
        return sum(self.counts.values())


# ---------------------------------------------------------------------------
# Yaratuvchi
# ---------------------------------------------------------------------------


class Seeder:
    """Namuna ma'lumot yaratuvchi (bitta tranzaksiya ichida ishlaydi)."""

    def __init__(self, session: Any, *, job_count: int, rng: Random) -> None:
        self.session = session
        self.job_count = job_count
        self.rng = rng
        self.now = utcnow()
        self.report = SeedReport()

    # ------------------------------------------------------------------
    # Yordamchilar
    # ------------------------------------------------------------------

    def _moment(self, *, max_days: float = SPREAD_DAYS) -> datetime:
        """Oxirgi `max_days` kun ichidagi tasodifiy vaqt."""
        seconds = self.rng.uniform(0, max_days * 24 * 3600)
        return self.now - timedelta(seconds=seconds)

    def _add(self, obj: Any, table: str) -> Any:
        """Obyektni sessiyaga qo'shadi va hisoblagichni oshiradi."""
        self.session.add(obj)
        self.report.add(table)
        return obj

    # ------------------------------------------------------------------
    # Foydalanuvchilar
    # ------------------------------------------------------------------

    def create_user(
        self,
        *,
        email: str,
        password: str,
        full_name: str,
        is_admin: bool,
        plan: PlanType,
    ) -> User:
        """Foydalanuvchi + obuna + API kalit yaratadi."""
        user = User(
            id=uuid.uuid4(),
            email=email,
            hashed_password=hash_password(password),
            full_name=full_name,
            is_active=True,
            is_admin=is_admin,
            last_login_at=self._moment(max_days=1),
            created_at=self.now - timedelta(days=SPREAD_DAYS + 3),
            updated_at=self.now,
        )
        self._add(user, "users")

        self._add(
            Subscription(
                id=uuid.uuid4(),
                user_id=user.id,
                plan=plan,
                started_at=self.now - timedelta(days=SPREAD_DAYS + 3),
                expires_at=None,
                is_active=True,
                external_customer_id=f"cus_seed_{plan.value}",
            ),
            "subscriptions",
        )

        # Xom kalit faqat shu yerda ma'lum — DB'ga hash yoziladi
        generated = generate_api_key()
        self._add(
            ApiKey(
                id=uuid.uuid4(),
                user_id=user.id,
                key_hash=generated.key_hash,
                key_prefix=generated.key_prefix,
                last_four=generated.last_four,
                name="Seed kaliti",
                scopes=[],
                last_used_at=self._moment(max_days=2),
                expires_at=None,
                revoked_at=None,
            ),
            "api_keys",
        )
        self.report.credentials.append((email, password, generated.raw))
        return user

    def create_usage_history(self, user: User, *, months: int = 4) -> None:
        """Joriy va o'tgan davrlar uchun `usage_records` yozadi."""
        period_start = start_of_month(self.now)
        for offset in range(months):
            # Oldingi oylarga qadam-baqadam orqaga siljiymiz
            moment = period_start
            for _ in range(offset):
                moment = start_of_month(moment - timedelta(days=1))
            jobs = self.rng.randint(40, 400) if offset else self.job_count
            failed = self.rng.randint(1, max(2, jobs // 8))
            self._add(
                UsageRecord(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    period=month_key(moment),
                    job_count=jobs,
                    success_count=jobs - failed,
                    failed_count=failed,
                    execution_seconds=round(jobs * self.rng.uniform(0.8, 4.5), 2),
                    recorded_at=moment,
                ),
                "usage_records",
            )

    # ------------------------------------------------------------------
    # Job'lar
    # ------------------------------------------------------------------

    def _status_plan(self) -> list[JobStatus]:
        """`STATUS_MIX` ni `job_count` ga moslab holatlar ro'yxatini qaytaradi.

        Ikki kafolat beradi:

        1. **Har holatdan kamida bittasi** bo'ladi — hatto `--jobs 8` da ham.
           Shuning uchun ro'yxat `STATUS_MIX` ning har bir holatidan bittasi
           bilan boshlanadi (dashboard'ning hamma paneli bo'sh qolmasligi uchun:
           DLQ, bajarilayotganlar, kechiktirilganlar...).
        2. **Qolgan joy nisbatga qarab** to'ldiriladi — avval aralashtirilgan
           hovuzdan olinadi, ya'ni `--jobs 100` da ham taqsimot saqlanadi.

        `--jobs` `STATUS_MIX` dagi holatlar sonidan (7) kichik bo'lsa ro'yxat
        qirqiladi — bunda birinchi holatlar (`SUCCESS`, `FAILED`, ...) qoladi.
        """
        pool = [status for status, count in STATUS_MIX for _ in range(count)]
        self.rng.shuffle(pool)

        # Har holatdan kamida bittasi
        statuses = [status for status, _ in STATUS_MIX]
        # Qolganini nisbatga qarab to'ldiramiz (hovuz aylanadi, shuning uchun
        # `--jobs` hovuz hajmidan katta bo'lsa ham taqsimot buzilmaydi)
        shortfall = max(0, self.job_count - len(statuses))
        statuses.extend(pool[index % len(pool)] for index in range(shortfall))
        del statuses[self.job_count :]

        self.rng.shuffle(statuses)
        return statuses

    def create_jobs(self, users: list[User]) -> None:
        """Job'lar, ularning urinishlari, loglari va DLQ yozuvlarini yaratadi."""
        for status in self._status_plan():
            owner = self.rng.choice(users)
            self._create_job(owner, status)

    def _create_job(self, owner: User, status: JobStatus) -> Job:
        """Bitta job'ni to'liq hayot sikli bilan yaratadi."""
        runtime = self.rng.choice(tuple(Runtime))
        created_at = self._moment()
        timeout_seconds = self.rng.choice((15, 30, 60, 120))
        max_retries = self.rng.choice((0, 2, 3, 5))

        payload: dict[str, Any] = {"values": [self.rng.randint(1, 50) for _ in range(3)]}

        job = Job(
            id=uuid.uuid4(),
            user_id=owner.id,
            idempotency_key=None,
            code=self.rng.choice(CODE_SAMPLES[runtime]),
            runtime=runtime,
            priority=self.rng.choice(tuple(Priority)),
            status=status,
            payload=payload,
            env_vars={"DURABL_ENV": "seed"},
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            retry_count=0,
            memory_mb=self.rng.choice((128, 256, 512)),
            cpus=self.rng.choice((0.5, 1.0, 2.0)),
            tags=self.rng.sample(TAG_POOL, k=self.rng.randint(1, 3)),
            correlation_id=generate_correlation_id(),
            created_at=created_at,
            updated_at=created_at,
        )

        # Holatga qarab vaqt ustunlarini to'ldiramiz
        # (`app/services/job_state.py` dagi `transition_fields` bilan bir xil mantiq).
        # `queued_at` lokal o'zgaruvchida saqlanadi va pastdagi yordamchilarga
        # ARGUMENT sifatida uzatiladi — modeldan qayta o'qilmaydi, chunki ustun
        # turi `datetime | None` va har safar `None` tekshiruvi kerak bo'lardi.
        queued_at: datetime | None = None
        if status is JobStatus.PENDING:
            # Kechiktirilgan job: hali navbatga tushmagan, vaqti kelajakda
            job.scheduled_at = self.now + timedelta(minutes=self.rng.randint(5, 720))
        else:
            queued_at = created_at + timedelta(seconds=self.rng.uniform(0.1, 3))
            job.queued_at = queued_at

        if status is JobStatus.CANCELLED and queued_at is not None:
            job.cancelled_at = queued_at + timedelta(seconds=self.rng.uniform(1, 30))

        self._add(job, "jobs")

        if queued_at is None or status in (JobStatus.QUEUED, JobStatus.CANCELLED):
            # Bu holatlarda hali bajarish urinishi bo'lmagan
            return job

        if status is JobStatus.SUCCESS:
            self._finish_success(job, queued_at=queued_at, payload=payload)
        elif status is JobStatus.RUNNING:
            self._start_running(job)
        else:  # FAILED yoki DEAD_LETTER
            self._finish_failure(
                job, queued_at=queued_at, dead_letter=status is JobStatus.DEAD_LETTER
            )
        return job

    def _finish_success(self, job: Job, *, queued_at: datetime, payload: dict[str, Any]) -> None:
        """Muvaffaqiyatli job: 1-2 urinish, oxirgisi muvaffaqiyatli."""
        attempts = self.rng.choice((1, 1, 1, 2))  # ko'pincha birinchi urinishda
        job.retry_count = attempts - 1
        started = queued_at + timedelta(seconds=self.rng.uniform(0.2, 5))

        for attempt in range(1, attempts):
            # Oxirgidan oldingi urinishlar xato bilan tugagan
            started = self._execution(
                job,
                attempt_number=attempt,
                status=ExecutionStatus.FAILED,
                started_at=started,
                failure_reason=FailureReason.NON_ZERO_EXIT,
            )

        duration_ms = self.rng.randint(120, 9_000)
        finished = started + timedelta(milliseconds=duration_ms)
        total = sum(payload["values"])
        stdout = f"yigindi={total}\n"

        self._execution(
            job,
            attempt_number=attempts,
            status=ExecutionStatus.SUCCESS,
            started_at=started,
            duration_ms=duration_ms,
            exit_code=0,
            result={"total": total},
            stdout=stdout,
        )

        job.started_at = started
        job.finished_at = finished
        job.duration_ms = duration_ms
        job.exit_code = 0
        job.result = {"total": total}
        job.stdout = stdout
        job.updated_at = finished

    def _start_running(self, job: Job) -> None:
        """Hozir bajarilayotgan job: lease faol, urinish `RUNNING` holatida."""
        started = self.now - timedelta(seconds=self.rng.uniform(1, 45))
        job.started_at = started
        job.updated_at = started

        progress = "ishlov berilmoqda...\n"
        execution = self._add(
            Execution(
                id=uuid.uuid4(),
                job_id=job.id,
                attempt_number=1,
                worker_id=f"worker-{self.rng.randint(1, 3)}",
                lease_expires_at=self.now + timedelta(seconds=30),
                status=ExecutionStatus.RUNNING,
                started_at=started,
                stdout_bytes=len(progress.encode()),
                stderr_bytes=0,
                created_at=started,
                updated_at=started,
            ),
            "executions",
        )
        # Bajarilayotgan job'da ham log bo'ladi — UI "jonli loglar" panelini
        # ko'rsatishi uchun bir nechta qator yozamiz
        self._log(execution, job, LogStream.SYSTEM, "urinish #1 boshlandi", 0, started)
        self._log(execution, job, LogStream.STDOUT, progress.strip(), 1, started)

    def _finish_failure(self, job: Job, *, queued_at: datetime, dead_letter: bool) -> None:
        """Xato job: barcha urinishlar yiqilgan; DLQ bo'lsa yozuv ham qo'shiladi."""
        reason = self.rng.choice(tuple(ERROR_SAMPLES))
        error_text, stderr = ERROR_SAMPLES[reason]
        # DLQ'ga tushgan job barcha urinishlarni sarflagan bo'ladi
        attempts = (job.max_retries + 1) if dead_letter else self.rng.randint(1, 2)
        attempts = max(1, min(attempts, 3))
        job.retry_count = attempts - 1

        started = queued_at + timedelta(seconds=self.rng.uniform(0.2, 5))
        duration_ms = self.rng.randint(80, 6_000)
        for attempt in range(1, attempts + 1):
            started = self._execution(
                job,
                attempt_number=attempt,
                status=(
                    ExecutionStatus.TIMEOUT
                    if reason is FailureReason.TIMEOUT
                    else ExecutionStatus.FAILED
                ),
                started_at=started,
                duration_ms=duration_ms,
                exit_code=None if reason is FailureReason.TIMEOUT else 1,
                failure_reason=reason,
                stderr=stderr,
                error_message=error_text,
            )

        finished = started
        job.started_at = queued_at + timedelta(seconds=self.rng.uniform(0.2, 5))
        job.finished_at = finished
        job.duration_ms = duration_ms
        job.exit_code = None if reason is FailureReason.TIMEOUT else 1
        job.stderr = stderr
        job.error = error_text
        job.failure_reason = FailureReason.MAX_RETRIES_EXCEEDED if dead_letter else reason
        job.updated_at = finished

        if not dead_letter:
            return

        # DLQ yozuvi: qismi hal qilingan, qismi ochiq (UI ikkisini ham ko'rsatadi)
        resolved = self.rng.random() < 0.25
        self._add(
            DlqEntry(
                id=uuid.uuid4(),
                job_id=job.id,
                user_id=job.user_id,
                failure_reason=reason,
                last_error=error_text,
                failed_at=finished,
                retry_count=job.retry_count,
                resolved=resolved,
                resolved_at=finished + timedelta(hours=1) if resolved else None,
                resolved_by_id=None,
                notes="Seed ma'lumoti: qo'lda ko'rib chiqildi" if resolved else None,
                manual_retry_count=1 if resolved else 0,
                created_at=finished,
                updated_at=finished,
            ),
            "dlq_entries",
        )

    def _execution(
        self,
        job: Job,
        *,
        attempt_number: int,
        status: ExecutionStatus,
        started_at: datetime,
        duration_ms: int | None = None,
        exit_code: int | None = None,
        failure_reason: FailureReason | None = None,
        result: dict[str, Any] | None = None,
        stdout: str = "",
        stderr: str = "",
        error_message: str | None = None,
    ) -> datetime:
        """Bitta urinish + uning loglarini yozadi; keyingi urinish vaqtini qaytaradi."""
        millis = duration_ms if duration_ms is not None else self.rng.randint(100, 4_000)
        finished_at = started_at + timedelta(milliseconds=millis)

        execution = self._add(
            Execution(
                id=uuid.uuid4(),
                job_id=job.id,
                attempt_number=attempt_number,
                worker_id=f"worker-{self.rng.randint(1, 3)}",
                lease_expires_at=None,
                status=status,
                started_at=started_at,
                finished_at=finished_at,
                exit_code=exit_code,
                duration_ms=millis,
                error_message=error_message,
                failure_reason=failure_reason,
                stdout_bytes=len(stdout.encode()),
                stderr_bytes=len(stderr.encode()),
                result=result,
                sandbox_id=f"sbx_{uuid.uuid4().hex[:12]}",
                # `memory_peak_mb` ATAYLAB None — ishonchli manba yo'q
                memory_peak_mb=None,
                created_at=started_at,
                updated_at=finished_at,
            ),
            "executions",
        )

        sequence = 0
        self._log(
            execution,
            job,
            LogStream.SYSTEM,
            f"urinish #{attempt_number} boshlandi",
            sequence,
            started_at,
        )
        for chunk, stream in ((stdout, LogStream.STDOUT), (stderr, LogStream.STDERR)):
            for raw_line in chunk.splitlines():
                sequence += 1
                self._log(execution, job, stream, raw_line, sequence, started_at)
        sequence += 1
        self._log(
            execution,
            job,
            LogStream.SYSTEM,
            f"urinish #{attempt_number} tugadi: {status.value}",
            sequence,
            finished_at,
        )

        # Keyingi urinish qayta urinish kechikishidan keyin boshlanadi
        return finished_at + timedelta(seconds=self.rng.uniform(1, 20))

    def _log(
        self,
        execution: Execution,
        job: Job,
        stream: LogStream,
        content: str,
        sequence: int,
        timestamp: datetime,
    ) -> None:
        """Bitta log qatorini yozadi (`job_id` denormalizatsiya qilingan)."""
        self._add(
            ExecutionLog(
                id=uuid.uuid4(),
                execution_id=execution.id,
                job_id=job.id,
                stream=stream,
                content=content,
                sequence=sequence,
                timestamp=timestamp,
            ),
            "execution_logs",
        )

    # ------------------------------------------------------------------
    # Webhook'lar
    # ------------------------------------------------------------------

    def create_webhooks(self, owner: User) -> None:
        """2 webhook: biri faol, biri ketma-ket xatolar tufayli o'chirilgan."""
        active = self._add(
            Webhook(
                id=uuid.uuid4(),
                user_id=owner.id,
                url="https://hooks.example.com/durabl/success",
                secret=generate_webhook_secret(),
                events=[WebhookEvent.JOB_SUCCEEDED.value, WebhookEvent.JOB_FAILED.value],
                description="Job tugaganda Slack kanaliga xabar",
                is_active=True,
                last_triggered_at=self._moment(max_days=1),
                consecutive_failures=0,
                disabled_at=None,
            ),
            "webhooks",
        )
        broken_at = self._moment(max_days=2)
        broken = self._add(
            Webhook(
                id=uuid.uuid4(),
                user_id=owner.id,
                url="https://broken.example.com/durabl",
                secret=generate_webhook_secret(),
                events=[WebhookEvent.JOB_DEAD_LETTERED.value],
                description="Ketma-ket xatolar tufayli avtomatik o'chirilgan",
                is_active=False,
                last_triggered_at=broken_at,
                consecutive_failures=12,
                disabled_at=broken_at,
            ),
            "webhooks",
        )
        self._create_deliveries(active, success_ratio=0.8)
        self._create_deliveries(broken, success_ratio=0.0)

    def _create_deliveries(self, webhook: Webhook, *, success_ratio: float) -> None:
        """Webhook uchun yuborish tarixini yozadi.

        Oxirgi yozuv ataylab chegaraviy holatda qoldiriladi: muvaffaqiyatli
        webhook uchun `SUCCESS`, buzilgan webhook uchun `EXHAUSTED` — shunda
        UI'da `DeliveryStatus` ning barcha asosiy qiymatlari ko'rinadi.
        """
        total = self.rng.randint(3, 5)
        for index in range(total):
            created = self._moment(max_days=3)
            is_last = index == total - 1
            succeeded = self.rng.random() < success_ratio
            duration_ms = self.rng.randint(40, 1_500)
            if is_last:
                succeeded = success_ratio > 0
            attempt = 1 if succeeded else (5 if is_last else self.rng.randint(2, 4))
            if succeeded:
                status = DeliveryStatus.SUCCESS
            elif attempt >= 5:
                status = DeliveryStatus.EXHAUSTED
            else:
                status = DeliveryStatus.RETRYING
            self._add(
                WebhookDelivery(
                    id=uuid.uuid4(),
                    webhook_id=webhook.id,
                    job_id=None,
                    event=WebhookEvent(self.rng.choice(webhook.events)),
                    status=status,
                    attempt=attempt,
                    next_retry_at=(
                        None
                        if status is not DeliveryStatus.RETRYING
                        else self.now + timedelta(minutes=self.rng.randint(1, 30))
                    ),
                    delivered_at=(
                        created + timedelta(milliseconds=duration_ms) if succeeded else None
                    ),
                    payload={"event": "seed", "job": {"status": "success"}},
                    response_code=200 if succeeded else self.rng.choice((500, 502, 503)),
                    response_body='{"ok":true}' if succeeded else "Bad Gateway",
                    error_message=None if succeeded else "HTTP 502 — manzil javob bermadi",
                    duration_ms=duration_ms,
                    created_at=created,
                    updated_at=created,
                ),
                "webhook_deliveries",
            )

    # ------------------------------------------------------------------
    # Audit jurnali
    # ------------------------------------------------------------------

    def create_audit_logs(self, admin: User, demo: User) -> None:
        """Admin panelda ko'rinadigan bir nechta audit yozuvi."""
        entries: tuple[tuple[AuditAction, str, str, dict[str, Any]], ...] = (
            (AuditAction.USER_CREATED, "user", str(demo.id), {"email": demo.email}),
            (AuditAction.PLAN_CHANGED, "user", str(demo.id), {"from": "free", "to": "pro"}),
            (AuditAction.USER_PROMOTED, "user", str(admin.id), {"is_admin": True}),
            (AuditAction.DLQ_PURGED, "dlq", "hammasi", {"removed": 3}),
            (AuditAction.API_KEY_REVOKED, "api_key", str(uuid.uuid4()), {"reason": "rotation"}),
        )
        for action, target_type, target_id, details in entries:
            created = self._moment()
            self._add(
                AuditLog(
                    id=uuid.uuid4(),
                    admin_id=admin.id,
                    action=action,
                    target_type=target_type,
                    target_id=target_id,
                    details=details,
                    ip_address="127.0.0.1",
                    user_agent="durabl-seed/1.0",
                    created_at=created,
                    updated_at=created,
                ),
                "audit_logs",
            )

    # ------------------------------------------------------------------
    # Asosiy oqim
    # ------------------------------------------------------------------

    def run(self) -> SeedReport:
        """Hamma narsani yaratadi (commit chaqiruvchining mas'uliyatida)."""
        admin = self.create_user(
            email=ADMIN_EMAIL,
            password=ADMIN_PASSWORD,
            full_name="Durabl Admin",
            is_admin=True,
            plan=PlanType.ENTERPRISE,
        )
        demo = self.create_user(
            email=DEMO_EMAIL,
            password=DEMO_PASSWORD,
            full_name="Demo Foydalanuvchi",
            is_admin=False,
            plan=PlanType.PRO,
        )
        for user in (admin, demo):
            self.create_usage_history(user)
        self.create_jobs([admin, demo])
        self.create_webhooks(demo)
        self.create_audit_logs(admin, demo)
        return self.report


# ---------------------------------------------------------------------------
# Tozalash va tekshiruvlar
# ---------------------------------------------------------------------------


async def _tables_exist(session: Any) -> bool:
    """`users` jadvali bormi — ya'ni migratsiya qo'llanganmi?

    Xato bo'lsa `rollback()` SHART: PostgreSQL'da yiqilgan so'rov butun
    tranzaksiyani "aborted" holatiga o'tkazadi va `session_scope()` ning
    chiqishdagi `commit()` i ham yiqilib, asl xato xabari yashirinib qolardi.
    """
    try:
        await session.execute(select(func.count()).select_from(User))
    except Exception as exc:
        logger.error("DB sxemasi topilmadi", error=str(exc))
        await session.rollback()
        return False
    return True


async def _existing_emails(session: Any) -> list[str]:
    """Seed foydalanuvchilaridan qaysilari allaqachon bor."""
    result = await session.execute(select(User.email).where(User.email.in_(SEED_EMAILS)))
    return sorted(result.scalars().all())


async def _reset(session: Any) -> int:
    """Seed foydalanuvchilarini va ularga tegishli hamma narsani o'chiradi.

    `audit_logs.admin_id` `ON DELETE SET NULL` bo'lgani uchun audit yozuvlari
    foydalanuvchi bilan ketmaydi — ularni alohida o'chiramiz. Qolgan jadvallar
    (`jobs`, `executions`, `execution_logs`, `api_keys`, `webhooks`,
    `webhook_deliveries`, `subscriptions`, `usage_records`, `dlq_entries`)
    DB darajasidagi `ON DELETE CASCADE` bilan avtomatik tozalanadi.
    """
    ids = (await session.execute(select(User.id).where(User.email.in_(SEED_EMAILS)))).scalars()
    user_ids = list(ids)
    if not user_ids:
        return 0
    await session.execute(delete(AuditLog).where(AuditLog.admin_id.in_(user_ids)))
    result = await session.execute(delete(User).where(User.id.in_(user_ids)))
    return int(result.rowcount or 0)


# ---------------------------------------------------------------------------
# Hisobot
# ---------------------------------------------------------------------------


def _print_report(report: SeedReport, *, job_count: int) -> None:
    """Yaratilganlarni jadval ko'rinishida va kirish ma'lumotlarini chiqaradi."""
    _emit()
    _emit("Durabl — namuna ma'lumot yaratildi")
    _emit()
    rows = [(name, str(count)) for name, count in sorted(report.counts.items())]
    rows.append(("JAMI", str(report.total)))
    _table(rows, title="jadval")

    _emit()
    _emit("Kirish ma'lumotlari (development uchun):")
    _emit()
    for email, password, raw_key in report.credentials:
        _emit(f"  email    : {email}")
        _emit(f"  parol    : {password}")
        _emit(f"  API kalit: {raw_key}")
        _emit()
    _emit("  DIQQAT: API kalit DB'da faqat SHA-256 hash sifatida saqlanadi —")
    _emit("  shu yerdan nusxa olib qo'ying, boshqa marta ko'rsatilmaydi.")
    _emit()
    _emit(f"  Job'lar: {job_count} ta, oxirgi {SPREAD_DAYS} kunga tarqatilgan.")
    _emit()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """CLI argumentlarini tavsiflaydi."""
    parser = argparse.ArgumentParser(
        prog="python -m scripts.seed",
        description="Durabl uchun development namuna ma'lumotini yaratadi.",
        epilog="Avval `alembic upgrade head` bajarilgan bo'lishi kerak.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="avval seed foydalanuvchilarini (va ularga tegishli hamma narsani) o'chiradi",
    )
    parser.add_argument(
        "--jobs",
        type=int,
        default=DEFAULT_JOB_COUNT,
        metavar="N",
        help=f"yaratiladigan job soni (standart: {DEFAULT_JOB_COUNT})",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=SEED,
        metavar="N",
        help=f"tasodifiy urug' — bir xil urug' bir xil ma'lumot beradi (standart: {SEED})",
    )
    return parser


async def main() -> int:
    """Skriptning kirish nuqtasi; chiqish kodini qaytaradi."""
    args = build_parser().parse_args()
    setup_logging()

    if args.jobs < 1:
        logger.error("--jobs kamida 1 bo'lishi kerak", jobs=args.jobs)
        return 2

    try:
        async with session_scope() as session:
            if not await _tables_exist(session):
                _emit("XATO: DB sxemasi yo'q. Avval migratsiyani qo'llang:")
                _emit("  cd backend && alembic upgrade head")
                return 1

            if args.reset:
                removed = await _reset(session)
                logger.info("seed ma'lumoti tozalandi", users_removed=removed)
            elif existing := await _existing_emails(session):
                # Idempotentlik: email bo'yicha tekshirib, takrorlamaymiz
                _emit("Namuna ma'lumot allaqachon mavjud — hech narsa yaratilmadi.")
                _emit(f"  mavjud foydalanuvchilar: {', '.join(existing)}")
                _emit("  qaytadan yaratish uchun: python -m scripts.seed --reset")
                return 0

            seeder = Seeder(session, job_count=args.jobs, rng=Random(args.seed))
            report = seeder.run()
            # `session_scope()` kontekstdan chiqishda commit qiladi
    finally:
        await close_db()

    _print_report(report, job_count=args.jobs)
    logger.info("seed tugadi", records=report.total, jobs=args.jobs)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))


__all__ = [
    "ADMIN_EMAIL",
    "DEMO_EMAIL",
    "SeedReport",
    "Seeder",
    "build_parser",
    "main",
]
