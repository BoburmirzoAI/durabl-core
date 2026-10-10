"""Boshlang'ich sxema — Durabl ma'lumotlar bazasining birinchi migratsiyasi.

Nima yaratiladi:

* **11 jadval** (yaratish tartibi — foreign key bog'liqligi bo'yicha):
  `users` -> `api_keys` -> `subscriptions` -> `usage_records` -> `jobs` ->
  `executions` -> `execution_logs` -> `webhooks` -> `webhook_deliveries` ->
  `dlq_entries` -> `audit_logs`.
* **149 ustun**, **11 birlamchi kalit**, **14 foreign key** (`CASCADE` yoki
  `SET NULL`), **3 `UniqueConstraint`** va **42 indeks** — hammasi
  `Base.metadata` bilan skript orqali solishtirib tasdiqlangan.
* **2 qo'shimcha PostgreSQL optimizatsiyasi** (`jobs.tags` uchun GIN indeks va
  DLQ sahifasi uchun qisman indeks). Ular ATAYLAB `Base.metadata` da yo'q:
  GIN SQLite'da mavjud emas, qisman indeks esa SQLite'da foyda bermaydi,
  shuning uchun modelga qo'shilsa SQLite testlari yiqilardi. Bu yerda dialekt
  tekshiruvi bilan faqat PostgreSQL'da yaratiladi.

DIQQAT (`--autogenerate` haqida): yuqoridagi ikki indeks `Base.metadata` da
yo'q, shuning uchun PostgreSQL'ga qarshi `alembic revision --autogenerate`
chaqirilsa Alembic ularni "Detected removed index" deb belgilaydi va
`op.drop_index` taklif qiladi. Bu DRIFT EMAS — jadval, ustun, cheklov va
qolgan 42 indeks to'liq mos (tekshirilgan). Shunday taklif chiqsa, yangi
migratsiyadan bu ikki `drop_index` qatorini O'CHIRIB tashlash kerak.
Doimiy yechim: `alembic/env.py` dagi `include_object()` ga shu ikki nomni
qo'shish (aniq kod `alembic/README.md` da).

Tur tanlovlari (`app/models/base.py` dagi qarorlarning DDL'dagi aksi):

* `sa.Uuid()` — PostgreSQL'da tabiiy `uuid`, SQLite'da `CHAR(32)`.
* `sa.JSON().with_variant(postgresql.JSONB(...), "postgresql")` — PostgreSQL'da
  `JSONB` (indekslanadi va `?` operatorini qo'llab-quvvatlaydi), SQLite'da `JSON`.
* `sa.DateTime(timezone=True)` — barcha vaqt ustunlari timezone-aware
  (`TIMESTAMP WITH TIME ZONE`).
* Enum ustunlar `native_enum=False` bilan — ya'ni `VARCHAR(n)`. PostgreSQL
  `ENUM` turi YARATILMAYDI, shuning uchun yangi holat qo'shish uchun
  `ALTER TYPE` migratsiyasi kerak bo'lmaydi.

SQLite'da ham sinovdan o'tgan: `alembic/env.py` `render_as_batch` ni
`settings.is_sqlite` bo'yicha yoqadi, bu migratsiyada esa `ALTER TABLE`
yo'q (faqat `CREATE TABLE`), shuning uchun batch rejimi shart emas.

Revision ID: 8fb11e62b45f
Revises: yo'q (birinchi migratsiya)
Yaratilgan: 2026-10-04 01:23:07.251385+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Alembic identifikatorlari
revision: str = "8fb11e62b45f"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# ---------------------------------------------------------------------------
# Takrorlanadigan ustun turlari (`app/models/base.py` bilan AYNAN mos)
# ---------------------------------------------------------------------------

#: JSON ustun: PostgreSQL -> JSONB, qolgan dialektlarda -> JSON
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def _enum(*values: str, name: str, length: int = 32) -> sa.Enum:
    """`enum_column()` yasagan turning DDL ko'rinishi: `VARCHAR(length)`.

    `native_enum=False` tufayli PostgreSQL'da alohida `ENUM` turi
    yaratilmaydi — faqat matn ustuni. `name` baribir beriladi, chunki
    `--autogenerate` solishtirishda shu nomga tayanadi.
    """
    return sa.Enum(*values, name=name, native_enum=False, length=length)


#: `app.constants.JobStatus`
JOB_STATUS = _enum(
    "pending",
    "queued",
    "running",
    "success",
    "failed",
    "retrying",
    "cancelled",
    "dead_letter",
    name="jobstatus",
)
#: `app.constants.Runtime`
RUNTIME = _enum("python", "node", name="runtime")
#: `app.constants.Priority`
PRIORITY = _enum("high", "normal", "low", name="priority")
#: `app.constants.ExecutionStatus`
EXECUTION_STATUS = _enum(
    "pending",
    "running",
    "success",
    "failed",
    "timeout",
    "cancelled",
    "lost",
    name="executionstatus",
)
#: `app.constants.LogStream`
LOG_STREAM = _enum("stdout", "stderr", "system", name="logstream")
#: `app.constants.WebhookEvent`
WEBHOOK_EVENT = _enum(
    "job.queued",
    "job.started",
    "job.succeeded",
    "job.failed",
    "job.cancelled",
    "job.dead_lettered",
    name="webhookevent",
)
#: `app.constants.DeliveryStatus`
DELIVERY_STATUS = _enum(
    "pending",
    "success",
    "failed",
    "retrying",
    "exhausted",
    name="deliverystatus",
)
#: `app.constants.PlanType`
PLAN_TYPE = _enum("free", "starter", "pro", "enterprise", name="plantype")
#: `app.constants.AuditAction` — qiymatlar uzun, shuning uchun `length=48`
AUDIT_ACTION = _enum(
    "user.created",
    "user.updated",
    "user.deactivated",
    "user.activated",
    "user.promoted",
    "job.cancelled",
    "job.force_retried",
    "dlq.purged",
    "api_key.revoked",
    "plan.changed",
    name="auditaction",
    length=48,
)


def _failure_reason() -> sa.Enum:
    """`app.constants.FailureReason` — uch jadvalda ishlatiladi.

    Har chaqiruvda yangi nusxa qaytaradi: bitta `sa.Enum` obyektini bir
    nechta `Table` ga ulash SQLAlchemy'da ogohlantirishga olib keladi.
    """
    return _enum(
        "non_zero_exit",
        "timeout",
        "out_of_memory",
        "sandbox_error",
        "validation_error",
        "lease_lost",
        "max_retries_exceeded",
        "internal_error",
        "output_too_large",
        name="failurereason",
    )


# ---------------------------------------------------------------------------
# Qo'shimcha PostgreSQL indekslari (`Base.metadata` da yo'q)
# ---------------------------------------------------------------------------

#: `(indeks nomi, jadval nomi, CREATE INDEX matni)` uchligi.
#:
#: Bu indekslar ataylab modellarda e'lon qilinmagan: GIN SQLite'da mavjud
#: emas, qisman indeks (DESC + WHERE) esa SQLite'da foyda bermaydi — ya'ni
#: `Index()` ni modelga qo'shish SQLite testlarini buzardi. Bu yerda esa
#: dialekt tekshiruvi bilan faqat PostgreSQL'da yaratiladi.
_POSTGRES_INDEXES: tuple[tuple[str, str, str], ...] = (
    (
        "ix_jobs_tags_gin",
        "jobs",
        # `JobRepository.search(tag=...)` PostgreSQL'da JSONB `?` operatorini
        # ishlatadi (`tags ? 'nightly'`). GIN indeksi busiz har so'rov `jobs`
        # jadvalini to'liq skan qilardi — teglar bo'yicha filtr tez ishlashi
        # uchun `jsonb_ops` opklassi kerak (u `?`, `?|`, `?&`, `@>` ni qo'llaydi).
        "CREATE INDEX ix_jobs_tags_gin ON jobs USING gin (tags)",
    ),
    (
        "ix_dlq_unresolved",
        "dlq_entries",
        # DLQ sahifasi FAQAT hal qilinmagan yozuvlarni ko'rsatadi
        # (`DlqRepository.list_for_user(resolved=False)` va `depth()`),
        # tartib esa `failed_at DESC`. Qisman indeks hal qilingan yozuvlarni
        # butunlay tashlab yuboradi — vaqt o'tishi bilan indeks hajmi
        # jadvaldan ancha kichik qoladi.
        "CREATE INDEX ix_dlq_unresolved ON dlq_entries (user_id, failed_at DESC)"
        " WHERE resolved = false",
    ),
)


def _is_postgresql() -> bool:
    """Joriy ulanish PostgreSQL'mi?

    `app/repositories/` dagi `_is_sqlite()` namunasining teskarisi: dialekt
    sozlamadan emas, HAQIQIY bind'dan olinadi (migratsiya `DATABASE_URL`
    sozlamasidan boshqa manzilga ham qo'llanishi mumkin).
    """
    return op.get_bind().dialect.name == "postgresql"


# ---------------------------------------------------------------------------
# Oldinga
# ---------------------------------------------------------------------------


def upgrade() -> None:
    """Sxemani noldan yaratadi (11 jadval, 42 indeks + 2 PostgreSQL indeksi)."""
    # -----------------------------------------------------------------
    # 1. users — barcha resurslarning egasi
    # -----------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=128), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("is_admin", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
    )
    op.create_index(op.f("ix_users_created_at"), "users", ["created_at"], unique=False)
    # Login identifikatori — unique indeks (`AuthService.register` shu bo'yicha tekshiradi)
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    # -----------------------------------------------------------------
    # 2. api_keys — `X-API-Key` autentifikatsiyasi
    # -----------------------------------------------------------------
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("key_prefix", sa.String(length=32), nullable=False),
        sa.Column("last_four", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("scopes", JSON_TYPE, nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_api_keys_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_keys")),
    )
    op.create_index(op.f("ix_api_keys_created_at"), "api_keys", ["created_at"], unique=False)
    # Autentifikatsiyada SHA-256 hash bo'yicha qidiriladi —
    # unique va butun tizimda eng tez-tez ishlatiladigan indeks
    op.create_index(op.f("ix_api_keys_key_hash"), "api_keys", ["key_hash"], unique=True)
    op.create_index(op.f("ix_api_keys_user_id"), "api_keys", ["user_id"], unique=False)

    # -----------------------------------------------------------------
    # 3. subscriptions — foydalanuvchi rejasi (bitta foydalanuvchi = bitta obuna)
    # -----------------------------------------------------------------
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("plan", PLAN_TYPE, server_default="free", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("external_customer_id", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_subscriptions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_subscriptions")),
    )
    op.create_index(
        op.f("ix_subscriptions_created_at"), "subscriptions", ["created_at"], unique=False
    )
    # `uselist=False` relationship'ni DB darajasida kafolatlaydi
    op.create_index(op.f("ix_subscriptions_user_id"), "subscriptions", ["user_id"], unique=True)

    # -----------------------------------------------------------------
    # 4. usage_records — oylik hisob (`"2026-10"` davri bo'yicha)
    # -----------------------------------------------------------------
    op.create_table(
        "usage_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("job_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("success_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failed_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("execution_seconds", sa.Float(), server_default=sa.text("0"), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_usage_records_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage_records")),
        # `UsageRepository.get_or_create(user_id, period)` shu cheklovga tayanadi
        sa.UniqueConstraint("user_id", "period", name=op.f("uq_usage_records_user_id_period")),
    )
    op.create_index(
        op.f("ix_usage_records_created_at"), "usage_records", ["created_at"], unique=False
    )
    op.create_index(op.f("ix_usage_records_period"), "usage_records", ["period"], unique=False)
    op.create_index(op.f("ix_usage_records_user_id"), "usage_records", ["user_id"], unique=False)

    # -----------------------------------------------------------------
    # 5. jobs — platformaning markaziy jadvali
    # -----------------------------------------------------------------
    op.create_table(
        "jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        # --- bajarish uchun kirish ma'lumotlari ---
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("runtime", RUNTIME, nullable=False),
        sa.Column("priority", PRIORITY, server_default="normal", nullable=False),
        sa.Column("status", JOB_STATUS, server_default="pending", nullable=False),
        sa.Column("payload", JSON_TYPE, nullable=True),
        sa.Column("env_vars", JSON_TYPE, nullable=True),
        # --- cheklovlar va qayta urinish ---
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("memory_mb", sa.Integer(), nullable=True),
        sa.Column("cpus", sa.Float(), nullable=True),
        # --- rejalashtirish ---
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cron_expression", sa.String(length=100), nullable=True),
        # --- hayot siklining vaqt belgilari (`job_state.transition_fields`) ---
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        # --- natija ---
        sa.Column("result", JSON_TYPE, nullable=True),
        sa.Column("stdout", sa.Text(), nullable=True),
        sa.Column("stderr", sa.Text(), nullable=True),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("failure_reason", _failure_reason(), nullable=True),
        # --- kuzatuv ---
        sa.Column("correlation_id", sa.String(length=64), nullable=False),
        sa.Column("tags", JSON_TYPE, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_jobs_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        # Idempotency: bitta foydalanuvchi uchun kalit takrorlanmasin.
        # `idempotency_key` NULL bo'lsa cheklov ishlamaydi (SQL standarti) —
        # ya'ni kalitsiz job'lar cheksiz yuborilishi mumkin, bu to'g'ri xatti-harakat.
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_jobs_user_idempotency"),
    )
    op.create_index(op.f("ix_jobs_correlation_id"), "jobs", ["correlation_id"], unique=False)
    op.create_index(op.f("ix_jobs_created_at"), "jobs", ["created_at"], unique=False)
    op.create_index(op.f("ix_jobs_scheduled_at"), "jobs", ["scheduled_at"], unique=False)
    op.create_index(op.f("ix_jobs_status"), "jobs", ["status"], unique=False)
    # Scheduler: `due_scheduled(now, limit)` — holat + vaqt bo'yicha
    op.create_index("ix_jobs_status_scheduled", "jobs", ["status", "scheduled_at"], unique=False)
    op.create_index(op.f("ix_jobs_user_id"), "jobs", ["user_id"], unique=False)
    # `JobRepository.search()` ning asosiy indeksi: egasi + holat + tartib
    op.create_index(
        "ix_jobs_user_status_created", "jobs", ["user_id", "status", "created_at"], unique=False
    )

    # -----------------------------------------------------------------
    # 6. executions — job'ning har bir urinishi
    # -----------------------------------------------------------------
    op.create_table(
        "executions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        # --- lease (worker egaligi) ---
        sa.Column("worker_id", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", EXECUTION_STATUS, server_default="pending", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        # --- natija ---
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("failure_reason", _failure_reason(), nullable=True),
        sa.Column("stdout_bytes", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("stderr_bytes", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("result", JSON_TYPE, nullable=True),
        sa.Column("sandbox_id", sa.String(length=128), nullable=True),
        # DIQQAT: bu ustun HAR DOIM NULL qoladi — ishonchli manba yo'q
        # (konteyner `stats` tugagandan keyin o'qiladi, `ru_maxrss` kumulyativ).
        sa.Column("memory_peak_mb", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_executions_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_executions")),
        # Bir urinish raqami bir job uchun faqat bir marta — ikki worker
        # bir vaqtda bir xil urinish yozishining oldini oladi
        sa.UniqueConstraint(
            "job_id", "attempt_number", name=op.f("uq_executions_job_id_attempt_number")
        ),
    )
    op.create_index(op.f("ix_executions_created_at"), "executions", ["created_at"], unique=False)
    op.create_index(op.f("ix_executions_job_id"), "executions", ["job_id"], unique=False)
    # `ReliabilityService.reap_expired_leases()` — muddati o'tgan lease'larni topish
    op.create_index(
        op.f("ix_executions_lease_expires_at"), "executions", ["lease_expires_at"], unique=False
    )
    op.create_index(op.f("ix_executions_status"), "executions", ["status"], unique=False)
    op.create_index(op.f("ix_executions_worker_id"), "executions", ["worker_id"], unique=False)

    # -----------------------------------------------------------------
    # 7. execution_logs — stdout/stderr qatorlari (eng tez o'sadigan jadval)
    # -----------------------------------------------------------------
    # DIQQAT: `TimestampMixin` ATAYLAB ishlatilmagan — `created_at`/`updated_at`
    # o'rniga bitta `timestamp` ustuni (hajm va indeks tejaladi).
    op.create_table(
        "execution_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("execution_id", sa.Uuid(), nullable=False),
        # Denormalizatsiya: "job'ning barcha loglari" so'rovi JOIN qilmasdan bajariladi
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("stream", LOG_STREAM, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["execution_id"],
            ["executions.id"],
            name=op.f("fk_execution_logs_execution_id_executions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_execution_logs_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_logs")),
    )
    # Kompozit indeks: loglarni tartib bilan va kursor (`after_sequence`) orqali o'qish
    op.create_index(
        "ix_execution_logs_exec_seq", "execution_logs", ["execution_id", "sequence"], unique=False
    )
    op.create_index(
        op.f("ix_execution_logs_execution_id"), "execution_logs", ["execution_id"], unique=False
    )
    op.create_index(op.f("ix_execution_logs_job_id"), "execution_logs", ["job_id"], unique=False)
    # `delete_older_than(cutoff)` — reja `log_retention_days` bo'yicha tozalash
    op.create_index(
        op.f("ix_execution_logs_timestamp"), "execution_logs", ["timestamp"], unique=False
    )

    # -----------------------------------------------------------------
    # 8. webhooks — mijozning hodisa manzillari
    # -----------------------------------------------------------------
    op.create_table(
        "webhooks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        # HMAC imzo kaliti (`sign_webhook`) — javobda faqat yaratishda qaytadi
        sa.Column("secret", sa.String(length=128), nullable=False),
        sa.Column("events", JSON_TYPE, nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
        # Ketma-ket xatolar soni chegaradan oshsa webhook avtomatik o'chiriladi
        sa.Column(
            "consecutive_failures", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_webhooks_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhooks")),
    )
    op.create_index(op.f("ix_webhooks_created_at"), "webhooks", ["created_at"], unique=False)
    op.create_index(op.f("ix_webhooks_user_id"), "webhooks", ["user_id"], unique=False)

    # -----------------------------------------------------------------
    # 9. webhook_deliveries — har bir yuborish urinishi
    # -----------------------------------------------------------------
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("webhook_id", sa.Uuid(), nullable=False),
        # Job o'chirilsa delivery ham o'chadi; hodisa job'siz ham bo'lishi mumkin (NULL)
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("event", WEBHOOK_EVENT, nullable=False),
        sa.Column("status", DELIVERY_STATUS, server_default="pending", nullable=False),
        sa.Column("attempt", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", JSON_TYPE, nullable=False),
        sa.Column("response_code", sa.Integer(), nullable=True),
        # Javob tanasi 4KB'ga kesiladi (`truncate()`)
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_webhook_deliveries_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["webhook_id"],
            ["webhooks.id"],
            name=op.f("fk_webhook_deliveries_webhook_id_webhooks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_deliveries")),
    )
    op.create_index(
        op.f("ix_webhook_deliveries_created_at"), "webhook_deliveries", ["created_at"], unique=False
    )
    op.create_index(
        op.f("ix_webhook_deliveries_job_id"), "webhook_deliveries", ["job_id"], unique=False
    )
    # `WebhookDeliveryRepository.pending_retries(now, limit)` — `webhook_sender` worker'i
    op.create_index(
        op.f("ix_webhook_deliveries_next_retry_at"),
        "webhook_deliveries",
        ["next_retry_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_webhook_deliveries_status"), "webhook_deliveries", ["status"], unique=False
    )
    op.create_index(
        op.f("ix_webhook_deliveries_webhook_id"), "webhook_deliveries", ["webhook_id"], unique=False
    )

    # -----------------------------------------------------------------
    # 10. dlq_entries — o'lik xatlar navbati
    # -----------------------------------------------------------------
    op.create_table(
        "dlq_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        # Egasi (`resolved_by_id` dan farqli — shuning uchun modelda `foreign_keys=` ochiq)
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("failure_reason", _failure_reason(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("resolved", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        # Admin hisobi o'chirilsa ham DLQ tarixi qolishi kerak -> SET NULL
        sa.Column("resolved_by_id", sa.Uuid(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("manual_retry_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_dlq_entries_job_id_jobs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by_id"],
            ["users.id"],
            name=op.f("fk_dlq_entries_resolved_by_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_dlq_entries_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dlq_entries")),
    )
    op.create_index(op.f("ix_dlq_entries_created_at"), "dlq_entries", ["created_at"], unique=False)
    op.create_index(op.f("ix_dlq_entries_failed_at"), "dlq_entries", ["failed_at"], unique=False)
    op.create_index(
        op.f("ix_dlq_entries_failure_reason"), "dlq_entries", ["failure_reason"], unique=False
    )
    # Bitta job DLQ'ga faqat bir marta tushadi -> unique indeks (`get_by_job`)
    op.create_index(op.f("ix_dlq_entries_job_id"), "dlq_entries", ["job_id"], unique=True)
    op.create_index(op.f("ix_dlq_entries_resolved"), "dlq_entries", ["resolved"], unique=False)
    op.create_index(op.f("ix_dlq_entries_user_id"), "dlq_entries", ["user_id"], unique=False)

    # -----------------------------------------------------------------
    # 11. audit_logs — admin harakatlari tarixi
    # -----------------------------------------------------------------
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        # Tizim bajargan harakatda NULL; admin o'chirilsa ham yozuv qoladi -> SET NULL
        sa.Column("admin_id", sa.Uuid(), nullable=True),
        sa.Column("action", AUDIT_ACTION, nullable=False),
        sa.Column("target_type", sa.String(length=50), nullable=True),
        sa.Column("target_id", sa.String(length=64), nullable=True),
        sa.Column("details", JSON_TYPE, nullable=True),
        # IPv6 ham sig'adi (45 belgi)
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["admin_id"],
            ["users.id"],
            name=op.f("fk_audit_logs_admin_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_logs")),
    )
    op.create_index(op.f("ix_audit_logs_action"), "audit_logs", ["action"], unique=False)
    op.create_index(op.f("ix_audit_logs_admin_id"), "audit_logs", ["admin_id"], unique=False)
    op.create_index(op.f("ix_audit_logs_created_at"), "audit_logs", ["created_at"], unique=False)

    # -----------------------------------------------------------------
    # 12. Qo'shimcha PostgreSQL indekslari (GIN va qisman indeks)
    # -----------------------------------------------------------------
    if _is_postgresql():
        for _name, _table, _sql in _POSTGRES_INDEXES:
            op.execute(_sql)


# ---------------------------------------------------------------------------
# Orqaga
# ---------------------------------------------------------------------------


def downgrade() -> None:
    """Barcha jadvalni TESKARI tartibda o'chiradi (foreign key buzilmasligi uchun).

    Tartib: `audit_logs` -> `dlq_entries` -> `webhook_deliveries` -> `webhooks` ->
    `execution_logs` -> `executions` -> `jobs` -> `usage_records` ->
    `subscriptions` -> `api_keys` -> `users`.

    DIQQAT: bu BARCHA ma'lumotni yo'q qiladi. Production'da `downgrade base`
    ishlatilmaydi — `alembic/README.md` dagi "Orqaga qaytarish xavfi" bo'limini o'qing.
    """
    # Qo'shimcha PostgreSQL indekslari — jadval o'chirilishidan OLDIN
    # (`DROP TABLE` ularni baribir olib tashlaydi, lekin ochiq o'chirish
    # migratsiyani qayta qo'llashda idempotent bo'lishini kafolatlaydi)
    if _is_postgresql():
        for _name, _table, _sql in reversed(_POSTGRES_INDEXES):
            op.drop_index(_name, table_name=_table)

    # 11. audit_logs
    op.drop_index(op.f("ix_audit_logs_created_at"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_admin_id"), table_name="audit_logs")
    op.drop_index(op.f("ix_audit_logs_action"), table_name="audit_logs")
    op.drop_table("audit_logs")

    # 10. dlq_entries
    op.drop_index(op.f("ix_dlq_entries_user_id"), table_name="dlq_entries")
    op.drop_index(op.f("ix_dlq_entries_resolved"), table_name="dlq_entries")
    op.drop_index(op.f("ix_dlq_entries_job_id"), table_name="dlq_entries")
    op.drop_index(op.f("ix_dlq_entries_failure_reason"), table_name="dlq_entries")
    op.drop_index(op.f("ix_dlq_entries_failed_at"), table_name="dlq_entries")
    op.drop_index(op.f("ix_dlq_entries_created_at"), table_name="dlq_entries")
    op.drop_table("dlq_entries")

    # 9. webhook_deliveries
    op.drop_index(op.f("ix_webhook_deliveries_webhook_id"), table_name="webhook_deliveries")
    op.drop_index(op.f("ix_webhook_deliveries_status"), table_name="webhook_deliveries")
    op.drop_index(op.f("ix_webhook_deliveries_next_retry_at"), table_name="webhook_deliveries")
    op.drop_index(op.f("ix_webhook_deliveries_job_id"), table_name="webhook_deliveries")
    op.drop_index(op.f("ix_webhook_deliveries_created_at"), table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")

    # 8. webhooks
    op.drop_index(op.f("ix_webhooks_user_id"), table_name="webhooks")
    op.drop_index(op.f("ix_webhooks_created_at"), table_name="webhooks")
    op.drop_table("webhooks")

    # 7. execution_logs
    op.drop_index(op.f("ix_execution_logs_timestamp"), table_name="execution_logs")
    op.drop_index(op.f("ix_execution_logs_job_id"), table_name="execution_logs")
    op.drop_index(op.f("ix_execution_logs_execution_id"), table_name="execution_logs")
    op.drop_index("ix_execution_logs_exec_seq", table_name="execution_logs")
    op.drop_table("execution_logs")

    # 6. executions
    op.drop_index(op.f("ix_executions_worker_id"), table_name="executions")
    op.drop_index(op.f("ix_executions_status"), table_name="executions")
    op.drop_index(op.f("ix_executions_lease_expires_at"), table_name="executions")
    op.drop_index(op.f("ix_executions_job_id"), table_name="executions")
    op.drop_index(op.f("ix_executions_created_at"), table_name="executions")
    op.drop_table("executions")

    # 5. jobs
    op.drop_index("ix_jobs_user_status_created", table_name="jobs")
    op.drop_index(op.f("ix_jobs_user_id"), table_name="jobs")
    op.drop_index("ix_jobs_status_scheduled", table_name="jobs")
    op.drop_index(op.f("ix_jobs_status"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_scheduled_at"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_created_at"), table_name="jobs")
    op.drop_index(op.f("ix_jobs_correlation_id"), table_name="jobs")
    op.drop_table("jobs")

    # 4. usage_records
    op.drop_index(op.f("ix_usage_records_user_id"), table_name="usage_records")
    op.drop_index(op.f("ix_usage_records_period"), table_name="usage_records")
    op.drop_index(op.f("ix_usage_records_created_at"), table_name="usage_records")
    op.drop_table("usage_records")

    # 3. subscriptions
    op.drop_index(op.f("ix_subscriptions_user_id"), table_name="subscriptions")
    op.drop_index(op.f("ix_subscriptions_created_at"), table_name="subscriptions")
    op.drop_table("subscriptions")

    # 2. api_keys
    op.drop_index(op.f("ix_api_keys_user_id"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_key_hash"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_created_at"), table_name="api_keys")
    op.drop_table("api_keys")

    # 1. users
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_index(op.f("ix_users_created_at"), table_name="users")
    op.drop_table("users")


__all__ = [
    "branch_labels",
    "depends_on",
    "down_revision",
    "downgrade",
    "revision",
    "upgrade",
]
