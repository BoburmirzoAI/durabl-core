"""Durabl repository qatlami — barcha repository'lar shu yerdan olinadi.

Service qatlami repository'larni modul yo'li bo'yicha emas, shu paketdan
import qiladi:

    from app.repositories import JobRepository, ExecutionRepository

**Qatlam qoidalari** (`BaseRepository` docstring'ida batafsil):

* Repository konstruktorga `AsyncSession` oladi: `JobRepository(session)`.
* Repository `commit()` QILMAYDI — faqat `flush()`. Tranzaksiya chegarasini
  service (yoki worker'dagi `session_scope()`) belgilaydi.
* Faqat SQL: biznes qoidalar, holat o'tishi tekshiruvi va domen xatolari
  service qatlamida qoladi.
* Modellardagi barcha `relationship()` lar `lazy="raise"`, shuning uchun
  bog'lanish kerak bo'lganda repository uni ochiq `selectinload()` bilan
  so'raydi (masalan `get_for_user(..., with_executions=True)`).

Faqat repository klasslari re-export qilinadi. Modul darajasidagi
konstantalar (`DEFAULT_LOG_LIMIT`, `JOB_SORT_COLUMNS`, `RETRYABLE_STATUSES`
va h.k.) o'z modulidan olinadi — ba'zilari bir xil nomga ega bo'lishi mumkin.
"""

from __future__ import annotations

from app.repositories.api_key_repo import ApiKeyRepository
from app.repositories.base import BaseRepository, ModelT
from app.repositories.dlq_repo import DlqRepository
from app.repositories.execution_log_repo import ExecutionLogRepository
from app.repositories.execution_repo import ExecutionRepository
from app.repositories.job_repo import JobRepository
from app.repositories.subscription_repo import SubscriptionRepository
from app.repositories.usage_repo import UsageRepository
from app.repositories.user_repo import UserRepository
from app.repositories.webhook_delivery_repo import WebhookDeliveryRepository
from app.repositories.webhook_repo import WebhookRepository

__all__ = [
    "ApiKeyRepository",
    "BaseRepository",
    "DlqRepository",
    "ExecutionLogRepository",
    "ExecutionRepository",
    "JobRepository",
    "ModelT",
    "SubscriptionRepository",
    "UsageRepository",
    "UserRepository",
    "WebhookDeliveryRepository",
    "WebhookRepository",
]
