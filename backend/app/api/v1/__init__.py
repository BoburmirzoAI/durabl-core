"""Durabl — API v1 router modullari.

Bu paket faqat **modul darajasidagi** re-eksport qiladi, ya'ni
`from app.api.v1 import jobs` ko'rinishida. Routerlarning o'zini
(`jobs.router`) shu yerda `router` nomi bilan birlashtirish ATAYLAB
qilinmaydi: har bir modulda nomi AYNI (`router`) bo'lgani uchun
birlashtirilgan nom chalkashtiradi. Ularni ulash — `app/api/router.py`
ning vazifasi.

**`websocket` moduli ham shu yerda**, lekin u `api_router` ga
KIRMAYDI: `WS /ws/jobs` yo'li `settings.API_V1_PREFIX` ostida emas,
ildizda joylashadi (shartnoma "QO'SHIMCHA 2" — WEBSOCKET bo'limi), shuning
uchun uni `app/main.py` alohida `prefix="/ws"` bilan ulaydi.
"""

from __future__ import annotations

from app.api.v1 import (
    admin,
    analytics,
    api_keys,
    auth,
    billing,
    dlq,
    executions,
    jobs,
    webhooks,
    websocket,
)

__all__ = [
    "admin",
    "analytics",
    "api_keys",
    "auth",
    "billing",
    "dlq",
    "executions",
    "jobs",
    "webhooks",
    "websocket",
]
