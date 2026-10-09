"""Durabl — HTTP (API) qatlami.

Tuzilma:

* `app/api/v1/` — versiyalangan endpoint modullari (`auth`, `jobs`, ...);
* `app/api/router.py` — ularni bitta `api_router` ga birlashtiradi.

Qatlam qoidasi (CONTRACTS §2): bu paket biznes logika yozmaydi, `select()`
chaqirmaydi va modellarga bevosita tegmaydi. Har bir endpoint faqat uch
ishni bajaradi: schema bilan validatsiya -> `app/services/` dagi servisni
chaqirish -> javob schema'sini qaytarish.
"""

from __future__ import annotations

from app.api.router import api_router

__all__ = ["api_router"]
