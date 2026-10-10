"""Durabl — cache servisi (Redis ustida, "fail-open" tamoyili bilan).

Cache nima uchun kerak. `GET /api/v1/analytics/overview` kabi so'rovlar
og'ir agregat SQL bajaradi (`COUNT`, `percentile_cont`, oylik yig'indilar).
Dashboard har 10 soniyada yangilanadi, ma'lumot esa 30 soniyada bir marta
o'zgarsa ham yetarli — shuning uchun natija `settings.STATS_CACHE_TTL_SECONDS`
davomida Redis'da saqlanadi.

**Fail-open — eng muhim qoida.** Cache tezlashtirish vositasi, haqiqat
manbai EMAS. Redis qulasa ilova ISHLASHDA DAVOM ETISHI kerak: `get()`
`None` qaytaradi (ya'ni "cache'da yo'q"), `set()`/`delete()` jim o'tadi,
`get_or_set()` esa `factory` natijasini — to'g'ridan-to'g'ri DB'dan — beradi.
Hech bir metod `RedisError` ni tashqariga chiqarmaydi. Bu `idempotency_service`
ning teskarisi: u fail-CLOSED (Redis yo'q bo'lsa so'rov rad etiladi), chunki
u to'g'rilik kafolati beradi, cache esa faqat tezlik.

**`invalidate()` va `SCAN`.** Kalitlarni naqsh bo'yicha topish uchun `KEYS`
ISHLATILMAYDI: u bitta buyruqda butun keyspace'ni aylanib chiqadi va Redis'ni
(bir oqimli server) millionlab kalitda soniyalar davomida BLOKLAYDI — bu
butun platforma uchun uzilish degani. `SCAN` kursor bilan qadamba-qadam
yuradi va boshqa buyruqlarga yo'l beradi.

**"Cache stampede" himoyasi.** Mashhur kalitning TTL'i tugagan lahzada 200 ta
parallel so'rov keladi — himoya bo'lmasa HAMMASI bir vaqtda ayni og'ir SQL'ni
bajaradi va DB yiqiladi ("thundering herd"). `get_or_set()` qisqa muddatli
lock oladi: faqat BITTA chaqiruvchi hisoblaydi, qolganlari 50 ms kutib
cache'ni qayta o'qiydi. Lock ololmagan va cache'da hamon qiymat topmagan
chaqiruvchi o'zi hisoblaydi — to'g'ri javob kechikishdan muhimroq.
"""

from __future__ import annotations

import asyncio
import hashlib
from enum import Enum
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from redis.exceptions import RedisError

from app.config import settings
from app.constants import RedisKeys
from app.exceptions import ValidationError
from app.logging_config import get_logger
from app.redis_client import get_redis
from app.utils.serializers import dump_json, load_json

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from redis.asyncio import Redis

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Konstantalar
# ---------------------------------------------------------------------------

#: Stampede lock'i qancha yashaydi. Qisqa bo'lishi SHART: lock egasi qulasa
#: boshqalar shu muddatdan keyin baribir hisoblay oladi.
STAMPEDE_LOCK_TTL_SECONDS: Final = 5

#: Lock ololmagan chaqiruvchi cache'ni qayta o'qishdan oldin qancha kutadi.
STAMPEDE_WAIT_SECONDS: Final = 0.05

#: `invalidate()` dagi `SCAN` qadami (bitta murojaatda ko'riladigan kalit).
SCAN_COUNT: Final = 200

#: `invalidate()` nechta kalitni bitta `DEL` bilan o'chiradi. Juda katta
#: partiya Redis'ni bloklaydi, juda kichik esa murojaatlarni ko'paytiradi.
DELETE_BATCH_SIZE: Final = 500

#: Lug'at/ro'yxat kalitidan yasaladigan hash uzunligi (kalit o'qishli qolishi
#: uchun to'liq SHA-256 emas, 16 belgi — to'qnashuv ehtimoli amalda nol).
KEY_HASH_LENGTH: Final = 16

#: Kalit sifatida bevosita matnga aylantiriladigan turlar.
_SCALAR_KEY_TYPES: Final = (str, int, UUID, Enum)


class CacheService:
    """Namespace'larga ajratilgan Redis cache.

    Kalit `RedisKeys.cache(namespace, key)` — ya'ni
    `durabl:cache:{namespace}:{key}`. Namespace bo'yicha ajratish
    `invalidate(namespace)` ni mumkin qiladi: masalan foydalanuvchi yangi
    job yuborganda uning butun `stats` namespace'i bir amalda tozalanadi.

    Qiymatlar JSON (`dump_json`/`load_json`) sifatida saqlanadi — `datetime`,
    `UUID`, `Enum` va Pydantic modellari avtomatik aylanadi, shuning uchun
    chaqiruvchi serializatsiya haqida o'ylamaydi.

    Servis DB'ga tegmaydi va `commit()` qilmaydi.
    """

    def __init__(self, redis: Redis | None = None) -> None:
        self.redis: Redis = redis or get_redis()

    # ------------------------------------------------------------------
    # Kalit yasash
    # ------------------------------------------------------------------

    @staticmethod
    def _key_part(key: Any) -> str:
        """Kalitning o'qishli va BARQAROR matn ko'rinishi.

        Skalyar kalitlar (`str`, `int`, `UUID`, `Enum`) shundayligicha
        ishlatiladi — kalit Redis'da o'qishli qoladi va diagnostika oson.
        Murakkab kalit (lug'at, ro'yxat, filtr to'plami) esa tartiblangan
        JSON'ning SHA-256 izi orqali qisqartiriladi: shu tufayli maydonlar
        tartibi o'zgarsa ham AYNI kalit chiqadi.
        """
        if isinstance(key, Enum):
            return str(key.value)
        if isinstance(key, _SCALAR_KEY_TYPES):
            return str(key)
        if key is None:
            return "none"
        canonical = dump_json(key, sort_keys=True)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return digest[:KEY_HASH_LENGTH]

    def _key(self, namespace: str, key: Any) -> str:
        """To'liq Redis kaliti (`RedisKeys.cache` orqali)."""
        return RedisKeys.cache(namespace, self._key_part(key))

    @staticmethod
    def _ttl(ttl: int | None) -> int:
        """Berilgan TTL yoki standart (`STATS_CACHE_TTL_SECONDS`).

        Nol va manfiy qiymat ham standartga aylantiriladi: TTL'siz yozuv
        Redis xotirasida abadiy qolib ketardi.
        """
        if ttl is None or ttl <= 0:
            return settings.STATS_CACHE_TTL_SECONDS
        return ttl

    # ------------------------------------------------------------------
    # Asosiy amallar
    # ------------------------------------------------------------------

    async def get(self, namespace: str, key: Any) -> Any | None:
        """Cache'dan qiymat o'qiydi; yo'q bo'lsa yoki Redis qulasa `None`.

        `None` ikki ma'noni bildiradi: "cache'da yo'q" va "cache ishlamadi".
        Chaqiruvchi uchun ikkisi ham bir xil — qiymatni qaytadan hisoblash
        kerak, shuning uchun farqlash shart emas.
        """
        try:
            raw = await self.redis.get(self._key(namespace, key))
        except RedisError as exc:
            logger.warning("Cache o'qilmadi", namespace=namespace, error=str(exc))
            return None
        if raw is None:
            return None
        try:
            return load_json(raw)
        except ValidationError as exc:
            # Buzuq yozuv (qo'lda o'zgartirilgan, eski format) ilovani buzmaydi.
            logger.warning("Cache yozuvi yaroqsiz JSON", namespace=namespace, error=str(exc))
            return None

    async def set(self, namespace: str, key: Any, value: Any, *, ttl: int | None = None) -> None:
        """Qiymatni cache'ga yozadi (standart TTL — `STATS_CACHE_TTL_SECONDS`).

        Redis qulasa jim o'tadi: yozilmagan cache ilovaning ishini
        to'xtatmaydi, faqat keyingi so'rov sekinroq bo'ladi.
        """
        try:
            payload = dump_json(value)
        except ValidationError as exc:
            logger.warning("Cache qiymati JSON'ga aylanmadi", namespace=namespace, error=str(exc))
            return
        try:
            await self.redis.set(self._key(namespace, key), payload, ex=self._ttl(ttl))
        except RedisError as exc:
            logger.warning("Cache yozilmadi", namespace=namespace, error=str(exc))

    async def delete(self, namespace: str, key: Any) -> None:
        """Bitta kalitni o'chiradi (ma'lumot o'zgarganda chaqiriladi)."""
        try:
            await self.redis.delete(self._key(namespace, key))
        except RedisError as exc:
            logger.warning("Cache o'chirilmadi", namespace=namespace, error=str(exc))

    async def invalidate(self, namespace: str) -> int:
        """Butun namespace'ni tozalaydi — `SCAN` bilan, `KEYS` ISHLATMAYDI.

        `KEYS durabl:cache:stats:*` bitta buyruqda butun keyspace'ni
        aylanadi va Redis'ni bloklaydi. `SCAN` esa kursor bilan yuradi:
        har qadamda `SCAN_COUNT` ta kalit ko'riladi va server boshqa
        buyruqlarga javob berishda davom etadi. Topilganlar
        `DELETE_BATCH_SIZE` lik to'plamlarda o'chiriladi.

        Returns:
            O'chirilgan kalitlar soni (Redis qulasa — shu paytgacha
            o'chirilganlar soni).
        """
        pattern = RedisKeys.cache(namespace, "*")
        removed = 0
        batch: list[str] = []

        try:
            async for raw_key in self.redis.scan_iter(match=pattern, count=SCAN_COUNT):
                batch.append(str(raw_key))
                if len(batch) >= DELETE_BATCH_SIZE:
                    removed += int(await self.redis.delete(*batch) or 0)
                    batch.clear()
            if batch:
                removed += int(await self.redis.delete(*batch) or 0)
        except RedisError as exc:
            logger.warning(
                "Cache namespace to'liq tozalanmadi",
                namespace=namespace,
                removed=removed,
                error=str(exc),
            )
            return removed

        if removed:
            logger.debug("Cache namespace tozalandi", namespace=namespace, removed=removed)
        return removed

    async def get_or_set(
        self,
        namespace: str,
        key: Any,
        factory: Callable[[], Awaitable[Any]],
        *,
        ttl: int | None = None,
    ) -> Any:
        """Cache'dan o'qiydi, bo'lmasa `factory()` bilan hisoblab yozadi.

        Stampede himoyasi bilan:

        1. cache'da bor — darhol qaytariladi;
        2. yo'q bo'lsa qisqa lock olinadi (`SET NX EX 5`). Lock EGASI
           `factory()` ni bajaradi, natijani yozadi va lock'ni bo'shatadi;
        3. lock ololmagan chaqiruvchi `STAMPEDE_WAIT_SECONDS` kutib cache'ni
           QAYTA o'qiydi — odatda shu paytda qiymat paydo bo'ladi;
        4. hamon yo'q bo'lsa (lock egasi sekin yoki xato bergan) chaqiruvchi
           o'zi hisoblaydi va YOZMAYDI — yozishni lock egasiga qoldiradi.

        `factory` ichidagi xato YASHIRILMAYDI: u ma'lumot manbai (DB)
        ishlamaganini bildiradi va chaqiruvchi bilishi kerak. Faqat Redis
        xatolari yashiriladi.

        Args:
            namespace: Cache namespace'i.
            key: Cache kaliti.
            factory: Qiymatni hisoblaydigan async funksiya (argumentsiz).
            ttl: Yashash muddati (`None` — standart).
        """
        cached = await self.get(namespace, key)
        if cached is not None:
            return cached

        lock_key = RedisKeys.lock(f"cache:{namespace}:{self._key_part(key)}")
        if await self._acquire_lock(lock_key):
            try:
                value = await factory()
                await self.set(namespace, key, value, ttl=ttl)
                return value
            finally:
                await self._release_lock(lock_key)

        # Lock boshqa chaqiruvchida — biroz kutib cache'ni qayta o'qiymiz.
        await asyncio.sleep(STAMPEDE_WAIT_SECONDS)
        cached = await self.get(namespace, key)
        if cached is not None:
            return cached

        logger.debug(
            "Cache stampede: lock olinmadi, qiymat o'zimiz hisoblanadi",
            namespace=namespace,
        )
        return await factory()

    async def incr(
        self,
        namespace: str,
        key: Any,
        *,
        amount: int = 1,
        ttl: int | None = None,
    ) -> int:
        """Hisoblagichni oshiradi va yangi qiymatni qaytaradi.

        Kalit YANGI yaratilganda (natija `amount` ga teng) TTL qo'yiladi —
        shu tufayli hisoblagich ham cheksiz yashab qolmaydi.

        Returns:
            Oshirilgandan keyingi qiymat; Redis qulasa `0`. Nol "hisoblab
            bo'lmadi" degan signal: shu bilan hisoblagichga tayangan
            tekshiruvlar (masalan yumshoq limitlar) Redis uzilganda
            so'rovni rad etmaydi, ya'ni fail-open xatti-harakati saqlanadi.
        """
        redis_key = self._key(namespace, key)
        try:
            current = int(await self.redis.incrby(redis_key, amount) or 0)
            if current == amount:
                await self.redis.expire(redis_key, self._ttl(ttl))
            return current
        except RedisError as exc:
            logger.warning("Cache hisoblagichi oshirilmadi", namespace=namespace, error=str(exc))
            return 0

    async def ttl(self, namespace: str, key: Any) -> int:
        """Kalitning qolgan yashash muddati (soniya).

        Redis semantikasi saqlanadi: `-1` — kalit bor, lekin muddati yo'q;
        `-2` — kalit yo'q. Redis qulasa ham `-2` qaytadi ("yo'q deb
        hisoblang").
        """
        try:
            return int(await self.redis.ttl(self._key(namespace, key)))
        except RedisError as exc:
            logger.warning("Cache TTL o'qilmadi", namespace=namespace, error=str(exc))
            return -2

    # ------------------------------------------------------------------
    # Stampede lock'i
    # ------------------------------------------------------------------

    async def _acquire_lock(self, lock_key: str) -> bool:
        """Qisqa muddatli lock oladi. Redis qulasa `False`.

        `False` — "lock yo'q" degani emas, "ishonchli lock olinmadi"
        degani. Bunda chaqiruvchi qiymatni o'zi hisoblaydi: himoyasiz,
        lekin ishlaydigan yo'l.
        """
        try:
            return bool(await self.redis.set(lock_key, "1", nx=True, ex=STAMPEDE_LOCK_TTL_SECONDS))
        except RedisError as exc:
            logger.warning("Cache lock olinmadi", lock=lock_key, error=str(exc))
            return False

    async def _release_lock(self, lock_key: str) -> None:
        """Lock'ni bo'shatadi (xato yashiriladi — TTL baribir tozalaydi)."""
        try:
            await self.redis.delete(lock_key)
        except RedisError as exc:
            logger.warning("Cache lock bo'shatilmadi", lock=lock_key, error=str(exc))


__all__ = [
    "DELETE_BATCH_SIZE",
    "KEY_HASH_LENGTH",
    "SCAN_COUNT",
    "STAMPEDE_LOCK_TTL_SECONDS",
    "STAMPEDE_WAIT_SECONDS",
    "CacheService",
]
