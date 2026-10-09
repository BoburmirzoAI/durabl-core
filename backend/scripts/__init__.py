"""Durabl — ishga tushirish va xizmat ko'rsatish skriptlari.

Bu paketdagi skriptlar ilovaning bir qismi EMAS: ular qo'lda yoki `make`
orqali ishga tushiriladi va `app/` paketini oddiy mijoz sifatida ishlatadi.

Mavjud skriptlar:

* `seed.py` — development uchun namuna ma'lumot (`make seed`).
  Ishlatish: `python -m scripts.seed --reset`

Paket `backend/` katalogidan ishga tushirilishi kerak (`app` importi uchun).
"""

from __future__ import annotations

__all__: list[str] = []
