"""Durabl service qatlami — barcha biznes logika shu yerdan olinadi.

API va worker qatlamlari service'larni modul yo'li bo'yicha emas, shu
paketdan import qiladi:

    from app.services import JobService, QueueService, BillingService

**Qatlam qoidalari** (shartnoma §2):

* Service `fastapi` ni import QILMAYDI va `HTTPException` TASHLAMAYDI —
  faqat `app.exceptions` domen xatolarini. Shu tufayli ayni kod worker
  protsessida ham ishlaydi.
* Repozitoriy `commit()` qilmaydi; tranzaksiyani service'ning PUBLIC
  metodi yopadi. Boshqa service chaqiradigan ICHKI metodlar commit
  QILMAYDI (har bir metodning docstring'ida ko'rsatilgan).
* Modellardagi barcha `relationship()` lar `lazy="raise"`, shuning uchun
  bog'liq ma'lumot `selectinload()` bilan OCHIQ so'raladi.

**Holat mashinasi alohida modulda.** `job_state` ning toza funksiyalari
`JobService` va `ReliabilityService` IKKISI uchun umumiy — ular bir-birini
import qilmasligi (aylanma bog'liqlik) uchun shunday ajratilgan. Shuning
uchun bu paket service klasslaridan tashqari o'sha funksiyalarni ham
re-eksport qiladi.

Modul darajasidagi konstantalar (`CACHE_NAMESPACE`, `PLAN_ORDER`,
`DEFAULT_LOG_LIMIT` va h.k.) re-eksport QILINMAYDI — ba'zilari bir xil
nomga ega, shuning uchun o'z modulidan olinadi
(`from app.services.analytics_service import CACHE_NAMESPACE`).
"""

from __future__ import annotations

from app.services.admin_service import AdminService
from app.services.analytics_service import AnalyticsService
from app.services.audit_service import AuditService
from app.services.auth_service import AuthService
from app.services.billing_service import BillingService
from app.services.cache_service import CacheService
from app.services.execution_service import ExecutionService
from app.services.idempotency_service import IdempotencyRecord, IdempotencyService
from app.services.job_service import JobService
from app.services.job_state import (
    allowed_targets,
    apply_transition,
    assert_transition,
    can_transition,
    is_cancellable,
    is_retryable_status,
    terminal_status_for,
    transition_fields,
)
from app.services.notification_service import NotificationService
from app.services.queue_service import QueueService
from app.services.reliability_service import ReliabilityService
from app.services.sandbox_service import SandboxService
from app.services.webhook_service import WebhookService

__all__ = [
    "AdminService",
    "AnalyticsService",
    "AuditService",
    "AuthService",
    "BillingService",
    "CacheService",
    "ExecutionService",
    "IdempotencyRecord",
    "IdempotencyService",
    "JobService",
    "NotificationService",
    "QueueService",
    "ReliabilityService",
    "SandboxService",
    "WebhookService",
    "allowed_targets",
    "apply_transition",
    "assert_transition",
    "can_transition",
    "is_cancellable",
    "is_retryable_status",
    "terminal_status_for",
    "transition_fields",
]
