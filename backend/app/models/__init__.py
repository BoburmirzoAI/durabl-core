"""Durabl modellari — Alembic `--autogenerate` uchun hammasi shu yerda import qilinadi.

DIQQAT: yangi model qo'shilganda shu faylga import qo'shish SHART, aks holda
Alembic uni ko'rmaydi va migratsiya yaratilmaydi.

Jadvallar va ularning bog'lanishlari:

    users ──┬── api_keys
            ├── webhooks ──── webhook_deliveries
            ├── subscriptions
            ├── usage_records
            ├── dlq_entries
            ├── user_sessions
            ├── recovery_codes
            ├── notifications
            ├── schedules ──── schedule_runs ──── jobs (job_id, SET NULL)
            └── jobs ──┬── executions ──── execution_logs
                       ├── execution_logs   (denormalizatsiya: job_id)
                       ├── webhook_deliveries
                       └── dlq_entries
    audit_logs ──── users (admin_id, SET NULL)
    login_events ──── users (user_id, SET NULL — jurnal saqlanadi)
"""

from __future__ import annotations

from app.models.api_key import ApiKey
from app.models.audit_log import AuditLog
from app.models.base import (
    Base,
    DateTimeTZ,
    JSONType,
    SoftDeleteMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
    UUIDType,
    enum_column,
)
from app.models.dlq_entry import DlqEntry
from app.models.execution import Execution
from app.models.execution_log import ExecutionLog
from app.models.job import Job
from app.models.login_event import LoginEvent
from app.models.notification import Notification
from app.models.recovery_code import RecoveryCode
from app.models.schedule import Schedule
from app.models.schedule_run import ScheduleRun
from app.models.subscription import Subscription
from app.models.usage_record import UsageRecord
from app.models.user import User
from app.models.user_session import UserSession
from app.models.webhook import Webhook
from app.models.webhook_delivery import WebhookDelivery

__all__ = [
    "ApiKey",
    "AuditLog",
    "Base",
    "DateTimeTZ",
    "DlqEntry",
    "Execution",
    "ExecutionLog",
    "JSONType",
    "Job",
    "LoginEvent",
    "Notification",
    "RecoveryCode",
    "Schedule",
    "ScheduleRun",
    "SoftDeleteMixin",
    "Subscription",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "UUIDType",
    "UsageRecord",
    "User",
    "UserSession",
    "Webhook",
    "WebhookDelivery",
    "enum_column",
]
