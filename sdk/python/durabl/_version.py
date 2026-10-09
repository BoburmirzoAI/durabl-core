"""Durabl Python SDK versiyasi.

Versiya FAQAT shu faylda saqlanadi — `pyproject.toml` ham uni shu yerdan o'qiydi
(`[tool.hatch.version] path = "durabl/_version.py"`). Shu sababli versiyani
o'zgartirish uchun yagona joy mavjud.
"""

from __future__ import annotations

#: Paket versiyasi (semantik versiyalash: MAJOR.MINOR.PATCH).
__version__ = "1.0.0"

#: Versiyaning sonli ko'rinishi — taqqoslash uchun qulay: `VERSION >= (1, 0, 0)`.
VERSION: tuple[int, int, int] = (1, 0, 0)

#: Har bir HTTP so'rovda yuboriladigan `User-Agent` qiymati.
#: Server tomonida qaysi SDK versiyasi ishlatilayotganini bilish uchun kerak.
USER_AGENT = f"durabl-python/{__version__}"

__all__ = ["USER_AGENT", "VERSION", "__version__"]
