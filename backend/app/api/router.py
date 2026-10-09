"""Durabl — v1 routerlarini bitta `api_router` ga birlashtirish.

`app/main.py` faqat shu obyektni biladi:

```python
app.include_router(api_router, prefix=settings.API_V1_PREFIX)
```

Shuning uchun prefiks (`/api/v1`) FAQAT bir joyda beriladi: routerlarning
o'zida `/auth`, `/jobs`, `/dlq` kabi domen prefiksi bo'ladi, versiya
prefiksi esa ulash paytida qo'shiladi. Bu `/api/v2` ni kelajakda
qo'shishni arzon qiladi va `Location` header'ini yasayotgan endpointlar
(`POST /jobs`) `settings.API_V1_PREFIX` dan foydalanganda yo'l aynan mos
tushadi.

## Ulash tartibi

FastAPI yo'llarni e'lon qilingan TARTIBDA tekshiradi, lekin bu yerda
tartib ahamiyatsiz: har bir router prefiksi boshqasidan farq qiladi
(`/auth`, `/api-keys`, `/jobs`, ...), ya'ni ular bir-birini yopa olmaydi.
Tartib faqat `/docs` da bo'limlar ketma-ketligini belgilaydi, shuning
uchun u foydalanuvchi yo'li bo'yicha mantiqiy tanlangan: kirish ->
kalitlar -> job'lar -> bajarish -> integratsiya -> ishonchlilik ->
hisobotlar -> to'lov -> administratsiya.

**Bitta router ichidagi tartib esa MUHIM** (masalan `/dlq/stats` ni
`/dlq/{id}` dan oldin e'lon qilish) — bu har bir router faylining o'z
mas'uliyatida.

## WebSocket bu yerda YO'Q

`app/api/v1/websocket.py` dagi router `api_router` ga ULANMAYDI:
shartnoma bo'yicha `WS /ws/jobs` ildizda (`API_V1_PREFIX` ostida emas),
chunki brauzer mijozlari va frontend `DurablSocket` aynan shu yo'lni
kutadi. Uni `app/main.py` `prefix="/ws"` bilan alohida ulaydi.
"""

from __future__ import annotations

from fastapi import APIRouter

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
)

#: Barcha v1 endpointlari. Prefiksni `main.py` beradi.
api_router = APIRouter()

# --- Kirish va hisob ------------------------------------------------------
api_router.include_router(auth.router)
api_router.include_router(api_keys.router)

# --- Job'lar va ularning bajarilishi --------------------------------------
api_router.include_router(jobs.router)
api_router.include_router(executions.router)

# --- Integratsiya va ishonchlilik -----------------------------------------
api_router.include_router(webhooks.router)
api_router.include_router(dlq.router)

# --- Hisobotlar, to'lov va administratsiya --------------------------------
api_router.include_router(analytics.router)
api_router.include_router(billing.router)
api_router.include_router(admin.router)

__all__ = ["api_router"]
