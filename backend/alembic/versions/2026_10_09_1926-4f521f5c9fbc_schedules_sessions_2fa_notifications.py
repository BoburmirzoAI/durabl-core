"""Jadvallar, sessiyalar, 2FA va bildirishnomalar — ikkinchi migratsiya.

Nima yaratiladi (yaratish tartibi foreign key bog'liqligi bo'yicha):

* **6 yangi jadval**: `login_events`, `notifications`, `recovery_codes`,
  `user_sessions`, `schedules` -> `schedule_runs`.
* **`users` ga 2 ustun**: `totp_secret`, `two_factor_enabled_at` (2FA).
* **31 indeks**, shundan 2 tasi `unique` (jadval nomi foydalanuvchi
  ichida yakka; tiklash kodi hashi takrorlanmasin) va 1 tasi ikkilangan
  ishga tushishni DB darajasida to'xtatadi
  (`uq_schedule_runs_schedule_id_scheduled_for`).

DIQQAT — `--autogenerate` shovqini haqida. Bu migratsiya autogenerate
bilan boshlangan, lekin **SQLite'ga qarshi** chaqirilgan (PostgreSQL
emas). Shu sababli Alembic mavjud 10 jadvalning `created_at` /
`updated_at` / boolean ustunlari uchun `alter_column(server_default=...)`
taklif qildi: SQLite `now()` ni `CURRENT_TIMESTAMP` deb o'qiydi, ya'ni
qiymat bir xil, matn boshqa. Bu DRIFT EMAS — barcha shunday qatorlar
QO'LDA O'CHIRILGAN. Kelgusida autogenerate ishlatilsa, xuddi shu
taklifni ko'rib, yana o'chirish kerak (yoki PostgreSQL'ga qarshi
chaqirish kerak).

`batch_alter_table` ham ATAYLAB ishlatilmaydi: bu migratsiyada faqat
`CREATE TABLE`, `CREATE INDEX` va `ADD COLUMN` bor — uchalasi ham
SQLite'da to'g'ridan-to'g'ri ishlaydi, jadvalni qayta yasash shart emas.

Revision ID: 4f521f5c9fbc
Revises: 8fb11e62b45f
Yaratilgan: 2026-10-09 19:26:06.773427+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Alembic identifikatorlari
revision: str = "4f521f5c9fbc"
down_revision: str | None = "8fb11e62b45f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: `app.models.base.JSONType` ning DDL'dagi aynan o'zi: PostgreSQL'da
#: `JSONB`, qolgan dialektlarda `JSON`.
_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")

#: `TimestampMixin` ning server tomonidagi standarti
_NOW = sa.text("now()")


def upgrade() -> None:
    """Sxemani oldinga siljitadi."""
    # ------------------------------------------------------------------
    # 1. login_events — kirish urinishlari jurnali
    #    `user_id` SET NULL: foydalanuvchi o'chirilsa ham jurnal qoladi.
    #    `TimestampMixin` YO'Q — jurnal yozuvi o'zgarmaydi, vaqt
    #    `occurred_at` da.
    # ------------------------------------------------------------------
    op.create_table(
        "login_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "result",
            sa.Enum(
                "success",
                "failed_password",
                "failed_2fa",
                "blocked",
                name="loginresult",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "method",
            sa.Enum(
                "password",
                "password+2fa",
                "api_key",
                name="loginmethod",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("detail", sa.String(length=255), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("location", sa.String(length=128), nullable=True),
        sa.Column("browser", sa.String(length=64), nullable=True),
        sa.Column("os", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_login_events_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_login_events")),
    )
    op.create_index(op.f("ix_login_events_email"), "login_events", ["email"])
    op.create_index(op.f("ix_login_events_occurred_at"), "login_events", ["occurred_at"])
    op.create_index(op.f("ix_login_events_result"), "login_events", ["result"])
    op.create_index(op.f("ix_login_events_user_id"), "login_events", ["user_id"])
    #: "Mening kirish tarixim" — eng yangi birinchi
    op.create_index(
        "ix_login_events_user_id_occurred_at",
        "login_events",
        ["user_id", "occurred_at"],
    )
    #: Brute-force aniqlash: bitta IP'dan oxirgi urinishlar
    op.create_index(
        "ix_login_events_ip_address_occurred_at",
        "login_events",
        ["ip_address", "occurred_at"],
    )

    # ------------------------------------------------------------------
    # 2. notifications — ilova ichidagi bildirishnomalar
    #    `source_type` / `source_id` ga foreign key ATAYLAB qo'yilmaydi:
    #    turli jadvallarga ishora qiladi va manba o'chirilganda
    #    bildirishnoma yo'qolmasligi kerak.
    # ------------------------------------------------------------------
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "job_failed",
                "job_succeeded",
                "dlq_entry",
                "webhook_failed",
                "worker_down",
                "quota_warning",
                "api_key_created",
                "system",
                name="notificationkind",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.Enum(
                "info",
                "warning",
                "critical",
                name="notificationseverity",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.String(length=2048), nullable=False),
        sa.Column("href", sa.String(length=512), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
    )
    op.create_index(op.f("ix_notifications_created_at"), "notifications", ["created_at"])
    op.create_index(op.f("ix_notifications_kind"), "notifications", ["kind"])
    op.create_index(op.f("ix_notifications_severity"), "notifications", ["severity"])
    op.create_index(op.f("ix_notifications_user_id"), "notifications", ["user_id"])
    #: Asosiy so'rov: mening bildirishnomalarim, eng yangi birinchi
    op.create_index(
        "ix_notifications_user_id_created_at",
        "notifications",
        ["user_id", "created_at"],
    )
    #: Qo'ng'iroqdagi o'qilmaganlar soni
    op.create_index("ix_notifications_user_id_read_at", "notifications", ["user_id", "read_at"])

    # ------------------------------------------------------------------
    # 3. recovery_codes — 2FA uchun bir martalik tiklash kodlari
    #    Faqat hash saqlanadi; ishlatilgan kod o'chirilmaydi, `used_at`
    #    bilan belgilanadi.
    # ------------------------------------------------------------------
    op.create_table(
        "recovery_codes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("used_from_ip", sa.String(length=45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_recovery_codes_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recovery_codes")),
    )
    op.create_index(op.f("ix_recovery_codes_created_at"), "recovery_codes", ["created_at"])
    op.create_index(op.f("ix_recovery_codes_user_id"), "recovery_codes", ["user_id"])
    #: "Qolgan kodlar soni" so'rovi
    op.create_index("ix_recovery_codes_user_id_used_at", "recovery_codes", ["user_id", "used_at"])
    #: Generator tasodifiy takrorlasa, ikkinchisi yozilmaydi
    op.create_index(
        "uq_recovery_codes_user_id_code_hash",
        "recovery_codes",
        ["user_id", "code_hash"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # 4. user_sessions — faol sessiyalar (JWT ni bekor qilish uchun)
    #    `token_hash` unique: bitta refresh token bitta sessiyaga tegishli.
    # ------------------------------------------------------------------
    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("browser", sa.String(length=64), nullable=True),
        sa.Column("os", sa.String(length=64), nullable=True),
        sa.Column(
            "device_type",
            sa.Enum(
                "desktop",
                "mobile",
                "tablet",
                "api",
                name="devicetype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("location", sa.String(length=128), nullable=True),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_sessions")),
    )
    op.create_index(op.f("ix_user_sessions_created_at"), "user_sessions", ["created_at"])
    op.create_index(op.f("ix_user_sessions_expires_at"), "user_sessions", ["expires_at"])
    op.create_index(
        op.f("ix_user_sessions_token_hash"), "user_sessions", ["token_hash"], unique=True
    )
    op.create_index(op.f("ix_user_sessions_user_id"), "user_sessions", ["user_id"])
    #: "Faol sessiyalarim" so'rovi
    op.create_index(
        "ix_user_sessions_user_id_revoked_at",
        "user_sessions",
        ["user_id", "revoked_at"],
    )

    # ------------------------------------------------------------------
    # 5. schedules — cron bo'yicha takroriy job retsepti
    #    `schedule_runs` dan OLDIN yaratilishi shart (foreign key).
    # ------------------------------------------------------------------
    op.create_table(
        "schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("cron", sa.String(length=128), nullable=False),
        sa.Column(
            "timezone",
            sa.String(length=64),
            server_default=sa.text("'UTC'"),
            nullable=False,
        ),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "allow_overlap",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "runtime",
            sa.Enum("python", "node", name="runtime", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("payload", _JSON, nullable=True),
        sa.Column("env_vars", _JSON, nullable=True),
        sa.Column(
            "priority",
            sa.Enum("high", "normal", "low", name="priority", native_enum=False, length=32),
            server_default=sa.text("'normal'"),
            nullable=False,
        ),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("memory_mb", sa.Integer(), nullable=False),
        sa.Column("max_retries", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "active",
                "paused",
                "errored",
                name="schedulestatus",
                native_enum=False,
                length=32,
            ),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_status", sa.String(length=32), nullable=True),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("total_runs", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failed_runs", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_schedules_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedules")),
    )
    op.create_index(op.f("ix_schedules_created_at"), "schedules", ["created_at"])
    op.create_index(op.f("ix_schedules_deleted_at"), "schedules", ["deleted_at"])
    op.create_index(op.f("ix_schedules_status"), "schedules", ["status"])
    op.create_index(op.f("ix_schedules_user_id"), "schedules", ["user_id"])
    #: Scheduler'ning asosiy so'rovi: faol va vaqti kelgan jadvallar
    op.create_index("ix_schedules_status_next_run_at", "schedules", ["status", "next_run_at"])
    #: Bir foydalanuvchida bir xil nomli ikki jadval bo'lmasin
    op.create_index("uq_schedules_user_id_name", "schedules", ["user_id", "name"], unique=True)

    # ------------------------------------------------------------------
    # 6. schedule_runs — har bir ishga tushish tarixi
    #    `job_id` SET NULL: job tozalangandan keyin ham yozuv qoladi.
    # ------------------------------------------------------------------
    op.create_table(
        "schedule_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("schedule_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "succeeded",
                "failed",
                "cancelled",
                "skipped",
                name="schedulerunstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("skip_reason", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.String(length=2048), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_NOW, nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["jobs.id"],
            name=op.f("fk_schedule_runs_job_id_jobs"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["schedule_id"],
            ["schedules.id"],
            name=op.f("fk_schedule_runs_schedule_id_schedules"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_schedule_runs")),
    )
    op.create_index(op.f("ix_schedule_runs_created_at"), "schedule_runs", ["created_at"])
    op.create_index(op.f("ix_schedule_runs_job_id"), "schedule_runs", ["job_id"])
    op.create_index(op.f("ix_schedule_runs_schedule_id"), "schedule_runs", ["schedule_id"])
    op.create_index(op.f("ix_schedule_runs_status"), "schedule_runs", ["status"])
    #: Jadval sahifasidagi "oxirgi ishga tushishlar" ro'yxati
    op.create_index(
        "ix_schedule_runs_schedule_id_scheduled_for",
        "schedule_runs",
        ["schedule_id", "scheduled_for"],
    )
    #: Bir xil daqiqa uchun ikki marta job yaratilmasligining kafolati —
    #: deploy paytida qisqa vaqt ikki scheduler ishlasa ham to'xtatadi
    op.create_index(
        "uq_schedule_runs_schedule_id_scheduled_for",
        "schedule_runs",
        ["schedule_id", "scheduled_for"],
        unique=True,
    )

    # ------------------------------------------------------------------
    # 7. users — 2FA ustunlari
    #    Ikkisi ham nullable: mavjud foydalanuvchilarda 2FA yo'q.
    #    `totp_secret` to'ldirilgan, lekin `two_factor_enabled_at` bo'sh
    #    bo'lishi MUMKIN — sozlash boshlangan, tasdiqlanmagan holat.
    # ------------------------------------------------------------------
    op.add_column("users", sa.Column("totp_secret", sa.String(length=64), nullable=True))
    op.add_column(
        "users",
        sa.Column("two_factor_enabled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    """O'zgarishni orqaga qaytaradi (yaratishning teskari tartibida)."""
    # 7. users — 2FA ustunlari
    op.drop_column("users", "two_factor_enabled_at")
    op.drop_column("users", "totp_secret")

    # 6. schedule_runs (schedules dan OLDIN — foreign key)
    op.drop_index("uq_schedule_runs_schedule_id_scheduled_for", table_name="schedule_runs")
    op.drop_index("ix_schedule_runs_schedule_id_scheduled_for", table_name="schedule_runs")
    op.drop_index(op.f("ix_schedule_runs_status"), table_name="schedule_runs")
    op.drop_index(op.f("ix_schedule_runs_schedule_id"), table_name="schedule_runs")
    op.drop_index(op.f("ix_schedule_runs_job_id"), table_name="schedule_runs")
    op.drop_index(op.f("ix_schedule_runs_created_at"), table_name="schedule_runs")
    op.drop_table("schedule_runs")

    # 5. schedules
    op.drop_index("uq_schedules_user_id_name", table_name="schedules")
    op.drop_index("ix_schedules_status_next_run_at", table_name="schedules")
    op.drop_index(op.f("ix_schedules_user_id"), table_name="schedules")
    op.drop_index(op.f("ix_schedules_status"), table_name="schedules")
    op.drop_index(op.f("ix_schedules_deleted_at"), table_name="schedules")
    op.drop_index(op.f("ix_schedules_created_at"), table_name="schedules")
    op.drop_table("schedules")

    # 4. user_sessions
    op.drop_index("ix_user_sessions_user_id_revoked_at", table_name="user_sessions")
    op.drop_index(op.f("ix_user_sessions_user_id"), table_name="user_sessions")
    op.drop_index(op.f("ix_user_sessions_token_hash"), table_name="user_sessions")
    op.drop_index(op.f("ix_user_sessions_expires_at"), table_name="user_sessions")
    op.drop_index(op.f("ix_user_sessions_created_at"), table_name="user_sessions")
    op.drop_table("user_sessions")

    # 3. recovery_codes
    op.drop_index("uq_recovery_codes_user_id_code_hash", table_name="recovery_codes")
    op.drop_index("ix_recovery_codes_user_id_used_at", table_name="recovery_codes")
    op.drop_index(op.f("ix_recovery_codes_user_id"), table_name="recovery_codes")
    op.drop_index(op.f("ix_recovery_codes_created_at"), table_name="recovery_codes")
    op.drop_table("recovery_codes")

    # 2. notifications
    op.drop_index("ix_notifications_user_id_read_at", table_name="notifications")
    op.drop_index("ix_notifications_user_id_created_at", table_name="notifications")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_severity"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_kind"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_created_at"), table_name="notifications")
    op.drop_table("notifications")

    # 1. login_events
    op.drop_index("ix_login_events_ip_address_occurred_at", table_name="login_events")
    op.drop_index("ix_login_events_user_id_occurred_at", table_name="login_events")
    op.drop_index(op.f("ix_login_events_user_id"), table_name="login_events")
    op.drop_index(op.f("ix_login_events_result"), table_name="login_events")
    op.drop_index(op.f("ix_login_events_occurred_at"), table_name="login_events")
    op.drop_index(op.f("ix_login_events_email"), table_name="login_events")
    op.drop_table("login_events")


__all__ = [
    "branch_labels",
    "depends_on",
    "down_revision",
    "downgrade",
    "revision",
    "upgrade",
]
