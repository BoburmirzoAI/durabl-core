"""Durabl fon worker'lari — job bajarish va davriy xizmat vazifalari.

Bu paket API'dan BUTUNLAY mustaqil: `app.api` dan hech narsa import
qilinmaydi (shartnoma §2). Shu tufayli worker'lar alohida konteynerda,
alohida masshtabda ishlaydi va API qulasa ham job'lar bajarilishda davom
etadi.

Paket tarkibi:

    runner.py          `PeriodicWorker` — davriy worker'larning bazaviy halqasi
    worker.py          `Worker` — navbatdan job olib bajaradigan asosiy worker
    worker_pool.py     `WorkerPool` — bir protsessda bir nechta `Worker`
    heartbeat.py       `Heartbeat` — bajarish paytida lease'ni uzaytirish
    scheduler.py       `SchedulerWorker` — kechiktirilganlar, reaper, cron, tiklash
    dlq_processor.py   `DlqProcessor` — DLQ nazorati, alert, avtomatik retry
    webhook_sender.py  `WebhookSender` — webhook yetkazish va qayta urinishlar

Har bir worker mustaqil protsess sifatida ishga tushadi:

    python -m app.workers.worker_pool
    python -m app.workers.scheduler
    python -m app.workers.dlq_processor
    python -m app.workers.webhook_sender

Kod ichidan ishga tushirish uchun `run_worker()` va `main_entry()`
yordamchilari ishlatiladi.
"""

from __future__ import annotations

from app.workers.dlq_processor import DlqProcessor
from app.workers.heartbeat import Heartbeat, HeartbeatCallback
from app.workers.runner import (
    ERROR_BACKOFF_THRESHOLD,
    MAX_BACKOFF_INTERVAL,
    PeriodicWorker,
    SupportsRun,
    main_entry,
    run_worker,
)
from app.workers.scheduler import SchedulerWorker
from app.workers.webhook_sender import WebhookSender
from app.workers.worker import Worker
from app.workers.worker_pool import WorkerPool

__all__ = [
    "ERROR_BACKOFF_THRESHOLD",
    "MAX_BACKOFF_INTERVAL",
    "DlqProcessor",
    "Heartbeat",
    "HeartbeatCallback",
    "PeriodicWorker",
    "SchedulerWorker",
    "SupportsRun",
    "WebhookSender",
    "Worker",
    "WorkerPool",
    "main_entry",
    "run_worker",
]
