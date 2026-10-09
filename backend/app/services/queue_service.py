"""Durabl — navbat servisi (Redis ustidagi "reliable queue").

Nega "reliable queue"? Oddiy `BRPOP` bilan job navbatdan OLINADI va worker
xotirasiga o'tadi. Agar worker shu lahzada qulasa (SIGKILL, OOM, server
o'chdi), job Redis'da ham yo'q, DB'da esa `queued` holatida muallaq qoladi —
hech kim uni qayta olmaydi. Shuning uchun Durabl `BLMOVE`/`LMOVE` ishlatadi:

    LMOVE durabl:queue:high durabl:processing:{worker_id} LEFT RIGHT

Bu BITTA atomar amal — job navbat boshidan olinadi va AYNI PAYTDA shu
worker'ning `processing` ro'yxatiga qo'shiladi. Worker qulasa, job hamon
`processing` ro'yxatida turadi va `requeue_stale(worker_id)` uni navbatga
qaytaradi. Ya'ni job hech qachon "havoda" qolmaydi.

**A'zo (member) formati.** Navbat, kechiktirilgan ZSET va `processing`
ro'yxatlarida job `f"{priority}:{job_id}"` ko'rinishida saqlanadi. Sabab:
`processing` ro'yxatidan job'ni qaytarganda uning QAYSI ustuvorlik navbatidan
kelganini bilishimiz kerak. Faqat `job_id` saqlansa, barcha stale job'lar
`normal` navbatga tushib, mijozning `high` ustuvorligi yo'qolardi.
`dequeue()` shu a'zoni `split(":", 1)` bilan ajratib FAQAT `job_id` qaytaradi
— chaqiruvchi (worker) format haqida bilmaydi.

**FIFO yo'nalishi.** Yangi job `RPUSH` bilan oxiriga qo'shiladi, worker
`LEFT` tomonidan oladi — eng eski job birinchi bajariladi. `nack()` va
`requeue_stale()` esa `LPUSH` bilan BOSHIGA qaytaradi: ular allaqachon
kutgan job'lar, shuning uchun navbatdagi yangilardan oldinda turishi FIFO
ma'nosiga mos keladi.

**Atomarlik va Lua.** `promote_due()` va `requeue_stale()` ikki qadamdan
iborat (ZSET'dan olish + navbatga qo'yish). Ularni Lua skript bilan bajarish
atomarlikni to'liq kafolatlaydi, shuning uchun skriptlar modul darajasida
yozilgan va lazy ro'yxatdan o'tadi. Lua yo'q muhitda (`fakeredis` lupa'siz)
servis avtomatik ravishda Python zaxira yo'liga o'tadi — bu yo'lda ham job
IKKI MARTA navbatga tushmaydi, chunki `ZREM`/`RPOP` natijasi tekshiriladi:
a'zoni faqat uni haqiqatan olgan chaqiruvchi navbatga qo'yadi.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Final
from uuid import UUID

from redis.exceptions import RedisError, ResponseError

from app import metrics
from app.config import settings
from app.constants import PRIORITY_ORDER, Priority, RedisKeys
from app.exceptions import QueueError
from app.logging_config import get_logger
from app.redis_client import get_redis
from app.utils.serializers import dump_json
from app.utils.time_utils import from_timestamp, isoformat, to_timestamp, utc_timestamp

if TYPE_CHECKING:
    from datetime import datetime

    from redis.asyncio import Redis
    from redis.commands.core import AsyncScript

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Konstantalar
# ---------------------------------------------------------------------------

#: `f"{priority}:{job_id}"` a'zosidagi ajratgich.
MEMBER_SEPARATOR: Final = ":"

#: `promote_due()` bir chaqiruvda ko'chiradigan maksimal job (standart).
DEFAULT_PROMOTE_LIMIT: Final = 100

#: `requeue_stale()` cheksiz halqaga tushmasligi uchun qattiq chegara.
MAX_REQUEUE_BATCH: Final = 10_000

#: `purge()`/`stats()` SCAN qadami.
SCAN_COUNT: Final = 200

#: Lua qo'llab-quvvatlanmaganini bildiruvchi Redis javoblari (fakeredis lupa'siz).
_LUA_UNSUPPORTED_MARKERS: Final = ("unknown command", "not supported", "unsupported")


# ---------------------------------------------------------------------------
# Lua skriptlar — atomarlik kafolati
# ---------------------------------------------------------------------------

#: Vaqti kelgan kechiktirilgan job'larni navbatga ko'chiradi.
#:
#: KEYS[1]     — kechiktirilgan ZSET (`RedisKeys.DELAYED`)
#: KEYS[2..]   — navbat kalitlari, `PRIORITY_ORDER` tartibida
#: ARGV[1]     — hozirgi unix timestamp (score chegarasi)
#: ARGV[2]     — nechta job ko'chirilsin
#: ARGV[3]     — noma'lum ustuvorlik uchun zaxira navbat indeksi (1-asosli)
#: ARGV[4..]   — ustuvorlik nomlari, KEYS[2..] bilan bir tartibda
#:
#: Qaytaradi: ko'chirilgan `job_id` lar ro'yxati.
PROMOTE_DUE_LUA: Final = """
local due = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, ARGV[2])
local fallback = KEYS[1 + tonumber(ARGV[3])]
local promoted = {}
for i = 1, #due do
    local member = due[i]
    -- ZREM 1 qaytarsagina navbatga qo'yamiz: a'zoni boshqa chaqiruvchi
    -- allaqachon olgan bo'lsa 0 qaytadi va job ikki marta tushmaydi.
    if redis.call('ZREM', KEYS[1], member) == 1 then
        local target = fallback
        local job_id = member
        local sep = string.find(member, ':', 1, true)
        if sep then
            local priority = string.sub(member, 1, sep - 1)
            job_id = string.sub(member, sep + 1)
            for j = 4, #ARGV do
                if ARGV[j] == priority then
                    target = KEYS[j - 2]
                    break
                end
            end
        end
        redis.call('RPUSH', target, member)
        promoted[#promoted + 1] = job_id
    end
end
return promoted
"""

#: Worker'ning `processing` ro'yxatidagi barcha job'ni o'z navbatiga qaytaradi.
#:
#: KEYS[1]   — `RedisKeys.processing(worker_id)`
#: KEYS[2..] — navbat kalitlari, `PRIORITY_ORDER` tartibida
#: ARGV[1]   — noma'lum ustuvorlik uchun zaxira navbat indeksi (1-asosli)
#: ARGV[2]   — bir chaqiruvdagi qattiq chegara
#: ARGV[3..] — ustuvorlik nomlari, KEYS[2..] bilan bir tartibda
#:
#: `RPOP` + `LPUSH`: eng YANGI a'zodan boshlab olinadi va boshiga qo'yiladi,
#: shu tufayli navbatda asl tartib (eng eski oldinda) tiklanadi.
#:
#: Qaytaradi: qaytarilgan job'lar soni.
REQUEUE_STALE_LUA: Final = """
local fallback = KEYS[1 + tonumber(ARGV[1])]
local limit = tonumber(ARGV[2])
local moved = 0
while moved < limit do
    local member = redis.call('RPOP', KEYS[1])
    if not member then
        break
    end
    local target = fallback
    local sep = string.find(member, ':', 1, true)
    if sep then
        local priority = string.sub(member, 1, sep - 1)
        for j = 3, #ARGV do
            if ARGV[j] == priority then
                target = KEYS[j - 1]
                break
            end
        end
    end
    redis.call('LPUSH', target, member)
    moved = moved + 1
end
return moved
"""

#: Protsess bo'yicha Lua holati: `None` — hali sinalmagan, `False` — yo'q.
_lua_supported: bool | None = None


def _mark_lua_unsupported(operation: str, exc: ResponseError) -> None:
    """Lua yo'qligini protsess bo'yicha eslab qoladi (qayta urinmaslik uchun)."""
    global _lua_supported
    _lua_supported = False
    logger.warning(
        "Redis Lua skriptlarini qo'llab-quvvatlamaydi — Python zaxira yo'li ishlatiladi",
        operation=operation,
        error=str(exc),
    )


def _is_lua_unsupported(exc: ResponseError) -> bool:
    """Xato "Lua yo'q" degani emasmi? (skript ichidagi xatodan ajratish uchun)

    Skriptning O'ZIDA xato bo'lsa `ResponseError` baribir keladi, lekin matni
    boshqacha bo'ladi — bunday xatoni yashirish taqiqlanadi, aks holda buzuq
    skript jimgina zaxira yo'liga o'tib, muammo ko'rinmay qolardi.
    """
    message = str(exc).lower()
    return any(marker in message for marker in _LUA_UNSUPPORTED_MARKERS)


@contextmanager
def _queue_guard(operation: str) -> Iterator[None]:
    """Redis xatolarini `QueueError` domen xatosiga o'raydi.

    Service qatlami `HTTPException` tashlamaydi — `main.py` dagi handler
    `QueueError.status_code` (503) ni HTTP javobiga aylantiradi, worker
    protsessida esa ayni shu xato qayta urinish mantig'iga tushadi.
    """
    try:
        yield
    except RedisError as exc:
        raise QueueError(f"Navbat amali bajarilmadi ({operation}): {exc}") from exc


# ---------------------------------------------------------------------------
# Servis
# ---------------------------------------------------------------------------


class QueueService:
    """Job navbati — Durabl'ning ishonchlilik yadrosi.

    Konstruktor Redis klientini oladi (berilmasa global klient). Servis
    holatsiz: har bir metod mustaqil, shuning uchun uni so'rov davomida
    yaratib tashlash arzon.

    Bu servis DB'ga tegmaydi va tranzaksiya egasi emas — `commit()` qilmaydi.
    """

    def __init__(self, redis: Redis | None = None) -> None:
        self.redis: Redis = redis or get_redis()
        self._promote_script: AsyncScript | None = None
        self._requeue_script: AsyncScript | None = None

    # ------------------------------------------------------------------
    # Ichki yordamchilar
    # ------------------------------------------------------------------

    @staticmethod
    def _member(priority: Priority | str, job_id: str | UUID) -> str:
        """Navbatda saqlanadigan a'zo: `f"{priority}:{job_id}"`."""
        return f"{Priority(priority).value}{MEMBER_SEPARATOR}{job_id}"

    @staticmethod
    def _split_member(member: str) -> tuple[Priority, str]:
        """A'zoni `(ustuvorlik, job_id)` ga ajratadi.

        Ajratgich yo'q bo'lsa (eski format yoki qo'lda qo'yilgan qiymat)
        butun matn `job_id` deb olinadi va ustuvorlik `NORMAL` bo'ladi —
        bunday a'zo ham yo'qolmasligi kerak.
        """
        prefix, separator, job_id = member.partition(MEMBER_SEPARATOR)
        if not separator:
            return Priority.NORMAL, member
        try:
            return Priority(prefix), job_id
        except ValueError:
            logger.warning("Navbatda noma'lum ustuvorlikli a'zo", member=member)
            return Priority.NORMAL, job_id

    @staticmethod
    def _queue_keys() -> list[str]:
        """Navbat kalitlari — `PRIORITY_ORDER` tartibida (Lua KEYS uchun)."""
        return [RedisKeys.queue(priority) for priority in PRIORITY_ORDER]

    @staticmethod
    def _priority_names() -> list[str]:
        """Ustuvorlik nomlari — `_queue_keys()` bilan bir tartibda (Lua ARGV)."""
        return [priority.value for priority in PRIORITY_ORDER]

    @staticmethod
    def _fallback_index() -> int:
        """Noma'lum ustuvorlik uchun zaxira navbat indeksi (Lua, 1-asosli)."""
        return PRIORITY_ORDER.index(Priority.NORMAL) + 1

    def _blocking_timeout(self, timeout: int | None) -> int:
        """`BLMOVE` uchun xavfsiz kutish vaqti (soniya).

        `redis-py` bloklanuvchi buyruq uchun socket timeout'ini avtomatik
        uzaytirmaydi: `BLMOVE 5` va `socket_timeout=5` bo'lsa, navbat bo'sh
        paytda server javobi kechikib ulanish uziladi. Shuning uchun kutish
        vaqti socket timeout'idan bir soniya KICHIK qilib olinadi.
        """
        requested = settings.WORKER_POLL_TIMEOUT_SECONDS if timeout is None else int(timeout)
        if requested <= 0:
            return 0
        socket_timeout = settings.REDIS_SOCKET_TIMEOUT
        if socket_timeout and socket_timeout > 0:
            ceiling = max(1, int(socket_timeout) - 1)
            return min(requested, ceiling)
        return requested

    # ------------------------------------------------------------------
    # Metrikalar
    # ------------------------------------------------------------------

    @staticmethod
    def _adjust_depth_metric(priority: Priority, amount: int) -> None:
        """`queue_depth` gauge'ini qadamba-qadam o'zgartiradi (arzon yo'l).

        Har `enqueue`/`dequeue` dan keyin to'liq `depth()` o'qish 4 qo'shimcha
        murojaat degani. Shuning uchun bitta job qo'shilganda/olinganda gauge
        shunchaki +1/-1 qilinadi; aniq qiymat `depth()` chaqirilganda
        (scheduler va admin paneli davriy chaqiradi) tiklanadi.
        """
        if not settings.METRICS_ENABLED or amount == 0:
            return
        metrics.queue_depth.labels(priority=priority.value).inc(amount)

    @staticmethod
    def _publish_depth_metric(depths: Mapping[str, int]) -> None:
        """`depth()` natijasidan gauge'ning ANIQ qiymatini o'rnatadi.

        Faqat ustuvorlik kalitlari uzatiladi — `delayed`/`processing`/`total`
        gauge label'i bo'lmasligi kerak (aks holda soxta timeseries paydo
        bo'ladi).
        """
        metrics.set_queue_depth(
            {priority: depths.get(priority.value, 0) for priority in PRIORITY_ORDER}
        )

    # ------------------------------------------------------------------
    # Navbatga qo'yish
    # ------------------------------------------------------------------

    async def enqueue(
        self,
        job_id: str | UUID,
        priority: Priority | str,
        *,
        delay_seconds: float = 0,
    ) -> None:
        """Job'ni navbatga qo'yadi (`delay_seconds > 0` bo'lsa kechiktiradi).

        Darhol bajarilishi kerak bo'lsa `RPUSH` — a'zo navbat OXIRIGA
        qo'shiladi, worker esa boshidan oladi (FIFO). Kechiktirilgan bo'lsa
        a'zo `RedisKeys.DELAYED` ZSET'ga `score = bajarish vaqti` bilan
        yoziladi; vaqti kelganda `promote_due()` uni navbatga ko'chiradi.

        Args:
            job_id: Job identifikatori.
            priority: Navbat ustuvorligi.
            delay_seconds: Necha soniyadan keyin bajarilsin (0 — darhol).

        Raises:
            QueueError: Redis javob bermadi.
        """
        resolved = Priority(priority)
        member = self._member(resolved, job_id)

        if delay_seconds > 0:
            await self._schedule(member, utc_timestamp() + float(delay_seconds))
            return

        with _queue_guard("enqueue"):
            await self.redis.rpush(RedisKeys.queue(resolved), member)
        self._adjust_depth_metric(resolved, 1)
        logger.debug("Job navbatga qo'yildi", job_id=str(job_id), priority=resolved.value)

    async def enqueue_at(
        self,
        job_id: str | UUID,
        when: datetime,
        priority: Priority | str,
    ) -> None:
        """Job'ni ANIQ vaqtda bajarilishi uchun rejalashtiradi.

        `when` o'tib ketgan bo'lsa job darhol navbatga qo'yiladi — kechikkan
        rejali job "abadiy kelajakda" qolib ketmasligi uchun.

        Raises:
            QueueError: Redis javob bermadi.
        """
        resolved = Priority(priority)
        member = self._member(resolved, job_id)
        score = to_timestamp(when)

        if score <= utc_timestamp():
            with _queue_guard("enqueue_at"):
                await self.redis.rpush(RedisKeys.queue(resolved), member)
            self._adjust_depth_metric(resolved, 1)
            logger.debug(
                "Rejalashtirilgan vaqt o'tgan — job darhol navbatga qo'yildi",
                job_id=str(job_id),
                priority=resolved.value,
            )
            return

        await self._schedule(member, score)

    async def _schedule(self, member: str, score: float) -> None:
        """A'zoni kechiktirilgan ZSET'ga yozadi (`score` = unix timestamp).

        `ZADD` bir xil a'zo uchun score'ni YANGILAYDI — shu tufayli bitta job
        ikki marta rejalashtirilsa, ZSET'da bitta yozuv qoladi va job ikki
        marta navbatga tushmaydi.
        """
        with _queue_guard("schedule"):
            await self.redis.zadd(RedisKeys.DELAYED, {member: score})
        logger.debug(
            "Job kechiktirildi",
            member=member,
            due_at=isoformat(from_timestamp(score)),
        )

    # ------------------------------------------------------------------
    # Navbatdan olish
    # ------------------------------------------------------------------

    # ASYNC109 bu yerda qo'llanmaydi: `timeout` — `asyncio.timeout()` bilan
    # almashtiriladigan mijoz tomoni kutishi EMAS, balki Redis'ning `BLMOVE`
    # buyrug'iga uzatiladigan SERVER tomoni kutish vaqti. `asyncio.timeout()`
    # bilan bekor qilish bloklanib turgan Redis ulanishini yarim yo'lda
    # qoldiradi va keyingi buyruq javobini buzadi. Imzo CONTRACTS.md §6 da
    # kelishilgan.
    async def dequeue(self, worker_id: str, *, timeout: int | None = None) -> str | None:  # noqa: ASYNC109
        """Navbatdan job oladi va uni worker'ning `processing` ro'yxatiga ko'chiradi.

        Ustuvorlik `PRIORITY_ORDER` tartibida hurmat qilinadi:

        * birinchi navbatlar (`high`, `normal`) `LMOVE` bilan BLOKLANMASDAN
          tekshiriladi — `high` da job bo'lsa `low` kutilmaydi;
        * ENG OXIRGI navbat (`low`) `BLMOVE` bilan `timeout` soniya kutadi —
          shu tufayli navbatlar bo'sh paytda worker protsessor bandligini
          oshirmaydi (busy-wait bo'lmaydi).

        `LMOVE src dst LEFT RIGHT` atomar: job navbat boshidan olinadi va
        ayni paytda `processing` oxiriga qo'shiladi. Shu sababli worker
        keyingi lahzada qulasa ham job `processing` da qoladi va
        `requeue_stale()` uni qaytaradi.

        Args:
            worker_id: Job'ni oladigan worker identifikatori.
            timeout: Oxirgi navbatni kutish vaqti (soniya). `None` —
                `settings.WORKER_POLL_TIMEOUT_SECONDS`; `0` — umuman kutmaydi.

        Returns:
            `job_id` (ustuvorlik prefiksi olib tashlangan) yoki navbat bo'sh
            bo'lsa `None`.

        Raises:
            QueueError: Redis javob bermadi.
        """
        destination = RedisKeys.processing(worker_id)
        blocking_timeout = self._blocking_timeout(timeout)
        last_index = len(PRIORITY_ORDER) - 1

        with _queue_guard("dequeue"):
            for index, priority in enumerate(PRIORITY_ORDER):
                source = RedisKeys.queue(priority)
                if index == last_index and blocking_timeout > 0:
                    member = await self.redis.blmove(
                        source, destination, blocking_timeout, "LEFT", "RIGHT"
                    )
                else:
                    member = await self.redis.lmove(source, destination, "LEFT", "RIGHT")
                if member is None:
                    continue

                member_priority, job_id = self._split_member(str(member))
                self._adjust_depth_metric(member_priority, -1)
                logger.debug(
                    "Job navbatdan olindi",
                    job_id=job_id,
                    priority=member_priority.value,
                    worker_id=worker_id,
                )
                return job_id

        return None

    async def ack(self, worker_id: str, job_id: str | UUID) -> None:
        """Job muvaffaqiyatli qayta ishlandi — `processing` ro'yxatidan o'chiradi.

        Worker job'ni to'liq yakunlagandan (DB'ga yozib, commit qilgandan)
        KEYIN chaqirilishi shart. Shundan oldin chaqirilsa, worker qulaganda
        job `requeue_stale()` bilan qaytarilmaydi va yo'qoladi.

        A'zoda ustuvorlik prefiksi borligi uchun barcha ustuvorlik
        variantlari bitta pipeline'da `LREM` qilinadi — bu bir martalik
        murojaat va chaqiruvchi ustuvorlikni bilishi kerak emas.

        Raises:
            QueueError: Redis javob bermadi.
        """
        removed = await self._remove_from_processing(worker_id, job_id)
        if removed == 0:
            logger.warning(
                "ack: job processing ro'yxatida topilmadi",
                job_id=str(job_id),
                worker_id=worker_id,
            )

    async def nack(
        self,
        worker_id: str,
        job_id: str | UUID,
        priority: Priority | str,
    ) -> None:
        """Job bajarilmadi — `processing` dan olib navbatga QAYTARADI.

        Worker job'ni bajara olmasa (graceful shutdown, lease yo'qoldi,
        qayta urinish kerak) shu metod chaqiriladi. A'zo `LPUSH` bilan
        navbat BOSHIGA qo'yiladi: job allaqachon kutgan, shuning uchun
        navbatdagi yangi job'lardan oldin bajarilishi FIFO ma'nosiga mos.

        Raises:
            QueueError: Redis javob bermadi.
        """
        resolved = Priority(priority)
        await self._remove_from_processing(worker_id, job_id)
        with _queue_guard("nack"):
            await self.redis.lpush(RedisKeys.queue(resolved), self._member(resolved, job_id))
        self._adjust_depth_metric(resolved, 1)
        logger.info(
            "Job navbatga qaytarildi (nack)",
            job_id=str(job_id),
            priority=resolved.value,
            worker_id=worker_id,
        )

    async def _remove_from_processing(self, worker_id: str, job_id: str | UUID) -> int:
        """Job'ni `processing` ro'yxatidan o'chiradi; o'chirilgan a'zolar soni.

        Ustuvorlik noma'lum bo'lishi mumkin, shuning uchun barcha variantlar
        sinab ko'riladi (`LREM count=0` — barcha mos a'zolar).
        """
        key = RedisKeys.processing(worker_id)
        with _queue_guard("processing_remove"):
            async with self.redis.pipeline(transaction=False) as pipe:
                for priority in PRIORITY_ORDER:
                    pipe.lrem(key, 0, self._member(priority, job_id))
                pipe.lrem(key, 0, str(job_id))
                results = await pipe.execute()
        return sum(int(result or 0) for result in results)

    async def processing_jobs(self, worker_id: str) -> list[str]:
        """Worker olgan, lekin hali `ack` qilmagan job'lar (`job_id` ro'yxati).

        Admin paneli va `reliability_service` qulagan worker'ni tekshirishda
        ishlatadi. Tartib: eng avval olingan job birinchi.

        Raises:
            QueueError: Redis javob bermadi.
        """
        with _queue_guard("processing_jobs"):
            members = await self.redis.lrange(RedisKeys.processing(worker_id), 0, -1)
        return [self._split_member(str(member))[1] for member in members]

    async def requeue_stale(self, worker_id: str) -> int:
        """Qulagan worker'ning barcha job'larini O'Z navbatiga qaytaradi.

        Bu — "reliable queue" namunasining ikkinchi yarmi. `processing`
        ro'yxatidagi har bir a'zoda ustuvorlik prefiksi saqlanganligi uchun
        job AYNI o'sha navbatga (`high` -> `high`) qaytadi — mijozning
        ustuvorligi yo'qolmaydi.

        Lua skript bor bo'lsa butun ko'chirish ATOMAR bajariladi. Zaxira
        yo'lda `RPOP` + `LPUSH` juftligi ishlatiladi: `RPOP` a'zoni faqat
        BITTA chaqiruvchiga beradi, shuning uchun bir job ikki marta
        navbatga tushmaydi (ikki reaper bir vaqtda ishlasa ham).

        Returns:
            Navbatga qaytarilgan job'lar soni.

        Raises:
            QueueError: Redis javob bermadi.
        """
        key = RedisKeys.processing(worker_id)
        moved = await self._requeue_stale_lua(key)
        if moved is None:
            moved = await self._requeue_stale_fallback(key)

        if moved:
            logger.warning(
                "Qulagan worker job'lari navbatga qaytarildi",
                worker_id=worker_id,
                requeued=moved,
            )
            await self._refresh_depth_metrics()
        return moved

    async def _requeue_stale_lua(self, key: str) -> int | None:
        """Lua bilan atomar qaytarish; Lua yo'q bo'lsa `None`."""
        if _lua_supported is False:
            return None
        if self._requeue_script is None:
            self._requeue_script = self.redis.register_script(REQUEUE_STALE_LUA)

        keys = [key, *self._queue_keys()]
        args: list[str | int | float] = [
            self._fallback_index(),
            MAX_REQUEUE_BATCH,
            *self._priority_names(),
        ]
        try:
            with _queue_guard("requeue_stale"):
                return int(await self._requeue_script(keys=keys, args=args) or 0)
        except QueueError as exc:
            cause = exc.__cause__
            if isinstance(cause, ResponseError) and _is_lua_unsupported(cause):
                _mark_lua_unsupported("requeue_stale", cause)
                return None
            raise

    async def _requeue_stale_fallback(self, key: str) -> int:
        """Lua'siz qaytarish: `RPOP` + `LPUSH` (har a'zo aniq bir marta)."""
        moved = 0
        with _queue_guard("requeue_stale"):
            while moved < MAX_REQUEUE_BATCH:
                member = await self.redis.rpop(key)
                if member is None:
                    break
                priority, _ = self._split_member(str(member))
                await self.redis.lpush(RedisKeys.queue(priority), str(member))
                moved += 1
        return moved

    # ------------------------------------------------------------------
    # Kechiktirilgan job'lar
    # ------------------------------------------------------------------

    async def promote_due(
        self,
        now: datetime | None = None,
        *,
        limit: int = DEFAULT_PROMOTE_LIMIT,
    ) -> list[str]:
        """Vaqti kelgan kechiktirilgan job'larni navbatga ko'chiradi.

        `SchedulerWorker` shu metodni davriy chaqiradi. Ko'chirish ikki
        qadamdan iborat (`ZREM` + `RPUSH`), shuning uchun atomarlik muhim:
        job IKKI MARTA navbatga tushsa, kod ikki marta bajarilib Durabl'ning
        asosiy kafolati buzilardi.

        * Lua bor bo'lsa — butun partiya bitta atomar skriptda.
        * Lua yo'q bo'lsa — `ZREM` natijasi tekshiriladi: a'zoni faqat
          `ZREM` dan `1` olgan chaqiruvchi navbatga qo'yadi. Ikkinchi
          chaqiruvchi `0` oladi va a'zoni o'tkazib yuboradi.

        Args:
            now: Chegara vaqti (`None` — hozir). Bundan oldin bajarilishi
                kerak bo'lgan job'lar ko'chiriladi.
            limit: Bir chaqiruvdagi maksimal job soni.

        Returns:
            Navbatga ko'chirilgan `job_id` lar ro'yxati (ikkinchi chaqiruvda
            ayni shu job'lar QAYTA qaytmaydi).

        Raises:
            QueueError: Redis javob bermadi.
        """
        if limit <= 0:
            return []
        threshold = utc_timestamp() if now is None else to_timestamp(now)

        promoted = await self._promote_due_lua(threshold, limit)
        if promoted is None:
            promoted = await self._promote_due_fallback(threshold, limit)

        if promoted:
            logger.info("Kechiktirilgan job'lar navbatga ko'chirildi", promoted=len(promoted))
            await self._refresh_depth_metrics()
        return promoted

    async def _promote_due_lua(self, threshold: float, limit: int) -> list[str] | None:
        """Lua bilan atomar ko'chirish; Lua yo'q bo'lsa `None`."""
        if _lua_supported is False:
            return None
        if self._promote_script is None:
            self._promote_script = self.redis.register_script(PROMOTE_DUE_LUA)

        keys = [RedisKeys.DELAYED, *self._queue_keys()]
        args: list[str | int | float] = [
            threshold,
            limit,
            self._fallback_index(),
            *self._priority_names(),
        ]
        try:
            with _queue_guard("promote_due"):
                raw = await self._promote_script(keys=keys, args=args)
        except QueueError as exc:
            cause = exc.__cause__
            if isinstance(cause, ResponseError) and _is_lua_unsupported(cause):
                _mark_lua_unsupported("promote_due", cause)
                return None
            raise
        return [str(job_id) for job_id in (raw or [])]

    async def _promote_due_fallback(self, threshold: float, limit: int) -> list[str]:
        """Lua'siz ko'chirish: `ZREM` `1` qaytarsagina `RPUSH` qilinadi."""
        promoted: list[str] = []
        with _queue_guard("promote_due"):
            due = await self.redis.zrangebyscore(
                RedisKeys.DELAYED, "-inf", threshold, start=0, num=limit
            )
            for member in due:
                if int(await self.redis.zrem(RedisKeys.DELAYED, str(member)) or 0) != 1:
                    continue  # Boshqa chaqiruvchi allaqachon oldi
                priority, job_id = self._split_member(str(member))
                await self.redis.rpush(RedisKeys.queue(priority), str(member))
                promoted.append(job_id)
        return promoted

    # ------------------------------------------------------------------
    # O'chirish
    # ------------------------------------------------------------------

    async def remove(
        self,
        job_id: str | UUID,
        priority: Priority | str | None = None,
    ) -> bool:
        """Job'ni navbatdan va kechiktirilganlar ro'yxatidan o'chiradi.

        Job bekor qilinganda (`cancel`) chaqiriladi — worker uni endi
        olmasligi kerak. Ustuvorlik berilmasa barcha navbatlar tekshiriladi.

        Returns:
            `True` — kamida bitta joydan o'chirildi.

        Raises:
            QueueError: Redis javob bermadi.
        """
        candidates = (Priority(priority),) if priority is not None else PRIORITY_ORDER

        with _queue_guard("remove"):
            async with self.redis.pipeline(transaction=False) as pipe:
                for candidate in candidates:
                    member = self._member(candidate, job_id)
                    pipe.lrem(RedisKeys.queue(candidate), 0, member)
                    pipe.zrem(RedisKeys.DELAYED, member)
                results = await pipe.execute()

        removed = sum(int(result or 0) for result in results)
        if removed:
            await self._refresh_depth_metrics()
            logger.info("Job navbatdan o'chirildi", job_id=str(job_id), removed=removed)
        return removed > 0

    async def purge(self) -> int:
        """BARCHA navbatlarni, kechiktirilganlarni va `processing` ni tozalaydi.

        **Faqat test va lokal ishlab chiqish uchun.** Production'da bu amal
        navbatdagi job'larni yo'q qiladi (DB'da ular `queued` holatida
        qoladi va faqat qo'lda tiklanadi).

        Returns:
            O'chirilgan a'zolar umumiy soni.

        Raises:
            QueueError: Redis javob bermadi.
        """
        with _queue_guard("purge"):
            keys = [*self._queue_keys()]
            processing_keys = [
                str(key)
                async for key in self.redis.scan_iter(
                    match=RedisKeys.processing("*"), count=SCAN_COUNT
                )
            ]
            keys.extend(processing_keys)

            async with self.redis.pipeline(transaction=False) as pipe:
                for key in keys:
                    pipe.llen(key)
                pipe.zcard(RedisKeys.DELAYED)
                counts = await pipe.execute()

            total = sum(int(count or 0) for count in counts)
            await self.redis.delete(*keys, RedisKeys.DELAYED)

        await self._refresh_depth_metrics()
        logger.warning("Navbat to'liq tozalandi (purge)", removed=total)
        return total

    # ------------------------------------------------------------------
    # Chuqurlik va statistika
    # ------------------------------------------------------------------

    async def depth(self) -> dict[str, int]:
        """Navbat chuqurligi — `{"high", "normal", "low", "delayed", "processing", "total"}`.

        `total` = `high + normal + low` (bajarishga TAYYOR job'lar).
        `delayed` va `processing` alohida ko'rsatiladi, chunki ular hali
        (yoki endi) navbatda turmaydi — `schemas.admin.QueueDepth.total`
        ham ayni shu hisobga tayanadi.

        Chaqiruv `queue_depth` metrikasining ANIQ qiymatini ham o'rnatadi.

        Raises:
            QueueError: Redis javob bermadi.
        """
        with _queue_guard("depth"):
            processing_keys = [
                str(key)
                async for key in self.redis.scan_iter(
                    match=RedisKeys.processing("*"), count=SCAN_COUNT
                )
            ]
            async with self.redis.pipeline(transaction=False) as pipe:
                for priority in PRIORITY_ORDER:
                    pipe.llen(RedisKeys.queue(priority))
                pipe.zcard(RedisKeys.DELAYED)
                for key in processing_keys:
                    pipe.llen(key)
                results = await pipe.execute()

        counts = [int(value or 0) for value in results]
        priority_count = len(PRIORITY_ORDER)
        depths: dict[str, int] = {
            priority.value: counts[index] for index, priority in enumerate(PRIORITY_ORDER)
        }
        depths["delayed"] = counts[priority_count]
        depths["processing"] = sum(counts[priority_count + 1 :])
        depths["total"] = sum(depths[priority.value] for priority in PRIORITY_ORDER)

        self._publish_depth_metric(depths)
        return depths

    async def depth_for(self, priority: Priority | str) -> int:
        """Bitta ustuvorlik navbatining uzunligi (bitta `LLEN` — eng arzon yo'l).

        Shu ustuvorlik uchun `queue_depth` metrikasi ham aniq qiymatga
        keltiriladi (boshqa ustuvorliklarga tegilmaydi).

        Raises:
            QueueError: Redis javob bermadi.
        """
        resolved = Priority(priority)
        with _queue_guard("depth_for"):
            length = int(await self.redis.llen(RedisKeys.queue(resolved)) or 0)
        metrics.set_queue_depth({resolved: length})
        return length

    async def _refresh_depth_metrics(self) -> None:
        """Gauge'ni aniq qiymatga keltiradi; xato ilovani buzmaydi.

        Metrika — yordamchi signal, shuning uchun uni yangilash
        muvaffaqiyatsiz bo'lsa asosiy amal (ko'chirish, tozalash) baribir
        bajarilgan deb hisoblanadi.
        """
        try:
            await self.depth()
        except QueueError as exc:  # pragma: no cover - faqat Redis qulaganda
            logger.warning("Navbat metrikasini yangilash muvaffaqiyatsiz", error=str(exc))

    async def stats(self) -> dict[str, Any]:
        """Admin paneli uchun navbat holati.

        Tarkibi: chuqurlik (`depth()` natijasi), worker'lar bo'yicha
        `processing` soni va eng yaqin kechiktirilgan job vaqti.

        Raises:
            QueueError: Redis javob bermadi.
        """
        depths = await self.depth()

        with _queue_guard("stats"):
            processing_keys = [
                str(key)
                async for key in self.redis.scan_iter(
                    match=RedisKeys.processing("*"), count=SCAN_COUNT
                )
            ]
            async with self.redis.pipeline(transaction=False) as pipe:
                for key in processing_keys:
                    pipe.llen(key)
                lengths = await pipe.execute()
            upcoming = await self.redis.zrange(RedisKeys.DELAYED, 0, 0, withscores=True)

        prefix = RedisKeys.processing("")
        per_worker = {
            key.removeprefix(prefix): int(length or 0)
            for key, length in zip(processing_keys, lengths, strict=False)
        }
        next_due_at = isoformat(from_timestamp(float(upcoming[0][1]))) if upcoming else None

        return {
            "depth": depths,
            "ready": depths["total"],
            "delayed": depths["delayed"],
            "processing": depths["processing"],
            "processing_by_worker": per_worker,
            "workers_with_jobs": sum(1 for count in per_worker.values() if count > 0),
            "next_delayed_at": next_due_at,
            "lua_enabled": _lua_supported is not False,
        }

    # ------------------------------------------------------------------
    # Hodisalar (Pub/Sub)
    # ------------------------------------------------------------------

    async def publish_event(
        self,
        event: dict[str, Any],
        *,
        user_id: str | UUID | None = None,
    ) -> None:
        """Job hodisasini Redis Pub/Sub orqali tarqatadi.

        IKKI kanalga yuboriladi:

        * `RedisKeys.EVENTS_JOBS` — umumiy kanal (admin monitoringi, DLQ
          kuzatuvchisi, metrikalar);
        * `RedisKeys.events_user(user_id)` — WebSocket foydalanuvchi bo'yicha
          AYNI shu kanalga obuna bo'ladi, shuning uchun bir mijoz boshqa
          mijozning hodisasini ko'rmaydi.

        `user_id` ochiq berilmasa, hodisa TANASIDAGI `user_id` ishlatiladi:
        `serializers.job_event_payload()` bu maydonni HAR DOIM to'ldiradi,
        shuning uchun chaqiruvchi uni ikki marta uzatishi shart emas. Shu
        zaxira bo'lmasa, argumentni uzatishni unutgan chaqiruvchida hodisa
        faqat umumiy kanalga ketib, WebSocket mijozlari real vaqtdagi
        yangilanishni JIMGINA olmay qolardi.

        Hodisa `Pub/Sub` orqali ketadi — ya'ni **eng ko'pi bir marta**
        (at-most-once) yetkaziladi: obunachisi bo'lmasa xabar yo'qoladi. Shu
        sababli hodisa HECH QACHON yagona haqiqat manbai emas; job holati
        PostgreSQL'da saqlanadi va mijoz uni polling bilan ham oladi.

        Args:
            event: Hodisa tanasi (odatda `job_event_payload(job)` natijasi).
            user_id: Qaysi foydalanuvchining kanaliga yuborilsin. `None` —
                hodisa tanasidagi `user_id` dan olinadi.

        Raises:
            QueueError: Redis javob bermadi.
        """
        payload = dump_json(event)
        target_user = user_id if user_id is not None else event.get("user_id")

        with _queue_guard("publish_event"):
            async with self.redis.pipeline(transaction=False) as pipe:
                pipe.publish(RedisKeys.EVENTS_JOBS, payload)
                if target_user is not None:
                    pipe.publish(RedisKeys.events_user(target_user), payload)
                await pipe.execute()

        logger.debug(
            "Job hodisasi tarqatildi",
            event_type=event.get("status") or event.get("type"),
            user_id=str(target_user) if target_user is not None else None,
        )


__all__ = [
    "DEFAULT_PROMOTE_LIMIT",
    "MAX_REQUEUE_BATCH",
    "MEMBER_SEPARATOR",
    "PROMOTE_DUE_LUA",
    "REQUEUE_STALE_LUA",
    "SCAN_COUNT",
    "QueueService",
]
