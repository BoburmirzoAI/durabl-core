"""Durabl — ishonchlilik servisi: platformaning YURAGI.

Bu fayl `Durabl_Architecture.md` 6-QISM dagi oltita mexanizmning TO'RTTASINI
amalga oshiradi. Ularning har biri "job jimgina yo'qolmaydi" kafolatining
bir bo'lagi:

## 3. Lease + Heartbeat (worker qulasa)

Worker job'ni olganda `RedisKeys.lease(job_id)` kalitini `SET ... NX EX ttl`
bilan EGALLAB OLADI. `NX` — "faqat kalit yo'q bo'lsa yoz" — Redis darajasida
atomar, shuning uchun ikki worker bir job'ni OLA OLMAYDI. Keyin worker har
`HEARTBEAT_INTERVAL_SECONDS` da lease'ni yangilaydi. Worker qulasa (SIGKILL,
OOM, server o'chdi) heartbeat to'xtaydi, `LEASE_TTL_SECONDS` dan keyin kalit
Redis'dan o'zi yo'qoladi va `reap_expired_leases()` job'ni boshqa worker'ga
o'tkazadi.

**Nega oddiy `EXPIRE` ishlatilmaydi.** Lease muddati tugab, job'ni boshqa
worker olgandan keyin eski worker "uyqudan turib" `EXPIRE` qilsa — YANGI
egasining lease'ini uzaytirib qo'yardi va ikki worker bir job'ni parallel
bajarib yuborardi. Shuning uchun yangilash va bo'shatish ATOMAR
"tekshir-va-yoz" (compare-and-set) amali: Lua skript yoki `WATCH`/`MULTI`.

**Haqiqat manbai — Redis, DB esa ko'rinish.** `executions.lease_expires_at`
admin paneli va reaper so'rovi uchun saqlanadi, lekin tiriklik haqida yakuniy
qarorni FAQAT Redis kaliti beradi: `reap_expired_leases()` DB'dan nomzod
olgach, Redis'da lease haqiqatan yo'qligini TASDIQLAYDI (1-qadam) va lease
tirik bo'lsa DB qiymatini o'zi oldinga suradi (o'z-o'zini tuzatish). Shu
tufayli `renew_lease()` DB'ga yozmaydi — u heartbeat fon vazifasidan
chaqiriladi va `AsyncSession` ni ikki vazifada parallel ishlatish xavfli.

## 4. Retry (qayta urinish)

`handle_failure()` — faylning eng muhim metodi: xato kelganda RETRY yoki DLQ
qarorini qabul qiladi. Qaror `utils/retry_policy.py` ga topshirilgan
(eksponensial backoff + jitter + `NON_RETRYABLE_REASONS`), shuning uchun
siyosat bir joyda turadi.

Retry'da job `RETRYING` holatida QOLADI va kechiktirilgan navbatga
(`RedisKeys.DELAYED` ZSET) tushadi. `QUEUED` ga o'tishni `scheduler`
(`promote_due()`) bajaradi — ya'ni "backoff kutilmoqda" va "bajarishga tayyor"
holatlari aralashmaydi.

## 5. DLQ (o'lik xatlar navbati)

Urinishlar tugagach job `DEAD_LETTER` bo'lib `dlq_entries` ga yoziladi.
`job_id` UNIQUE — qayta ikkinchi yozuv yaratilmaydi, mavjudi yangilanadi.
Mijoz sababini ko'radi, kodni tuzatib `retry_from_dlq()` bilan qayta uradi.

## 6. Lifecycle logging

Har bir muhim qarordan keyin `execution_logs` ga `LogStream.SYSTEM` qatori
yoziladi ("worker javob bermadi", "qayta urinish rejalashtirildi", "DLQ'ga
o'tkazildi"), shuning uchun mijoz loglarida Durabl'ning O'Z qarorlari ham
ko'rinadi — "nega mening job'im ikki marta ishladi?" savoli javobsiz qolmaydi.

---

## Tranzaksiya chegarasi (chaqiruvchi uchun MAJBURIY o'qish)

| Metod | commit |
|---|---|
| `acquire_lease`, `renew_lease`, `release_lease`, `lease_holder` | YO'Q (Redis + flush) |
| `handle_failure`, `schedule_retry`, `move_to_dlq` | YO'Q — **ichki**, chaqiruvchi commit qiladi |
| `reap_expired_leases` | HA — har tiklangan job uchun alohida commit |
| `retry_from_dlq` | HA — foydalanuvchi boshlagan amal |
| worker reestri va bekor qilish signali | DB'ga tegmaydi |

Qatlam qoidasi: `fastapi` import QILINMAYDI, `HTTPException` tashlanmaydi —
ayni shu kod worker protsesslarida ham ishlaydi.
"""

from __future__ import annotations

import os
import socket
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from redis.exceptions import RedisError, ResponseError, WatchError
from sqlalchemy import ColumnElement, asc, desc, func, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from app import metrics
from app.config import settings
from app.constants import (
    ExecutionStatus,
    FailureReason,
    JobStatus,
    LogStream,
    Priority,
    RedisKeys,
    WebhookEvent,
    WorkerState,
)
from app.exceptions import (
    DatabaseError,
    DlqEntryAlreadyResolvedError,
    DlqEntryNotFoundError,
    ExecutionError,
    InvalidStateTransitionError,
    JobNotFoundError,
    LeaseLostError,
    QueueError,
)
from app.logging_config import get_logger
from app.models.dlq_entry import DlqEntry
from app.models.execution import Execution
from app.models.job import Job
from app.redis_client import get_redis
from app.repositories.dlq_repo import DlqRepository
from app.repositories.execution_log_repo import ExecutionLogRepository
from app.repositories.execution_repo import ExecutionRepository
from app.repositories.job_repo import JobRepository
from app.schemas.base import PaginationParams
from app.schemas.dlq import DLQ_SORT_FIELDS, DlqFilter, DlqRetryRequest
from app.services import job_state
from app.services.queue_service import QueueService
from app.utils.retry_policy import RetryPolicy
from app.utils.serializers import dump_json, job_event_payload, load_json, truncate
from app.utils.time_utils import isoformat, seconds_from_now, seconds_until, utcnow

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from redis.commands.core import AsyncScript
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Lua skriptlar — lease atomarligi
# ---------------------------------------------------------------------------

#: Lease'ni EGASI bo'lgan worker uchun uzaytiradi.
#:
#: KEYS[1] — `RedisKeys.lease(job_id)`
#: ARGV[1] — lease egasi deb da'vo qilayotgan `worker_id`
#: ARGV[2] — yangi TTL (soniya)
#:
#: Qaytaradi: `1` — uzaytirildi, `0` — egasi boshqa (yoki lease yo'q).
LEASE_RENEW_LUA: Final = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('EXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

#: Lease'ni FAQAT egasi bo'shatadi (begona lease o'chirilmaydi).
#:
#: KEYS[1] — `RedisKeys.lease(job_id)`
#: ARGV[1] — lease egasi deb da'vo qilayotgan `worker_id`
#:
#: Qaytaradi: `1` — o'chirildi, `0` — egasi boshqa (yoki lease yo'q).
LEASE_RELEASE_LUA: Final = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""

#: Lua qo'llab-quvvatlanmaganini bildiruvchi Redis javoblari (fakeredis lupa'siz).
_LUA_UNSUPPORTED_MARKERS: Final = ("unknown command", "not supported", "unsupported")

#: Protsess bo'yicha Lua holati: `None` — hali sinalmagan, `False` — yo'q.
#: `queue_service` dagi ayni shu bayroqdan MUSTAQIL (boshqa modulning xususiy
#: holatiga tegmaslik uchun) — ikkisi bir xil xulosaga mustaqil keladi.
_lua_supported: bool | None = None


# ---------------------------------------------------------------------------
# Konstantalar
# ---------------------------------------------------------------------------

#: `WATCH`/`MULTI` zaxira yo'lida poyga tufayli qayta urinishlar soni.
#: Poyga faqat AYNI kalit boshqa klient tomonidan o'zgartirilganda bo'ladi;
#: lease kaliti bitta egaga tegishli, shuning uchun uch urinish yetarli.
CAS_MAX_ATTEMPTS: Final = 3

#: DLQ va `executions.error_message` uchun xato matnining chegarasi (belgi).
#: `Text` ustunining o'zida chegara yo'q, lekin sandbox'dan megabaytlik
#: traceback kelishi mumkin — DLQ ro'yxati shundan "cho'kib ketmasligi" kerak.
ERROR_TEXT_MAX_CHARS: Final = 8_192

#: Bekor qilish signalining nom maydoni.
#: **DIQQAT:** qiymat `job_service.CANCEL_NAMESPACE` bilan AYNAN bir xil
#: bo'lishi SHART — `JobService.cancel()` signalni yozadi, bu servis esa
#: o'qiydi. Ikki service bir-birini import QILMAYDI (aylanma bog'liqlik
#: bo'lmasligi uchun — `job_state` moduli ayni shu sababdan ajratilgan),
#: shuning uchun konstanta ataylab takrorlangan.
CANCEL_NAMESPACE: Final = "cancel"

#: Bekor qilish signali uchun qo'shimcha zaxira muddat (soniya).
#: `job_service.CANCEL_SIGNAL_GRACE_SECONDS` bilan bir xil.
CANCEL_SIGNAL_GRACE_SECONDS: Final = 30

#: Bir vaqtdalik hisoblagichining "o'z-o'zini tiklash" muddati (soniya).
#: `job_service.CONCURRENCY_KEY_TTL_SECONDS` bilan AYNAN bir xil bo'lishi
#: SHART: ikki service AYNI kalitni (`RedisKeys.concurrency`) boshqaradi.
CONCURRENCY_KEY_TTL_SECONDS: Final = 86_400

#: `reap_expired_leases()` bir chaqiruvda ko'radigan nomzodlar soni (standart).
DEFAULT_REAP_LIMIT: Final = 100

#: Lease tugaganda `execution_logs` ga yoziladigan tizim xabari.
LEASE_LOST_MESSAGE: Final = (
    "Worker javob bermadi — lease muddati tugadi, job qayta navbatga qo'yiladi"
)

#: `DlqFilter.sort_by` qiymati -> tartiblash ustuni.
#:
#: Oq ro'yxat `app.schemas.dlq.DLQ_SORT_FIELDS` dan AVTOMATIK yasaladi, ya'ni
#: schema'ga yangi ustun qo'shilsa shu yerni qo'lda yangilash kerak emas va
#: ikki ro'yxat bir-biridan uzilib qolmaydi. Nomlar mapper ustunlari orasidan
#: olinadi: shu tufayli `@property` yoki mavjud bo'lmagan nom SQL'ga tusha
#: olmaydi (`getattr(DlqEntry, name)` bunga kafolat bermaydi).
DLQ_SORT_COLUMNS: Final[dict[str, ColumnElement[Any]]] = {
    name: DlqEntry.__mapper__.columns[name]
    for name in sorted(DLQ_SORT_FIELDS)
    if name in DlqEntry.__mapper__.columns
}

#: `sort_by` oq ro'yxatda bo'lmasa ishlatiladigan ustun (`DlqFilter` baribir
#: tekshiradi — bu faqat himoya chorasi).
DLQ_DEFAULT_SORT_COLUMN: Final[ColumnElement[Any]] = DlqEntry.__mapper__.columns["failed_at"]


# ---------------------------------------------------------------------------
# Lua yordamchilari
# ---------------------------------------------------------------------------


def _mark_lua_unsupported(operation: str, exc: ResponseError) -> None:
    """Lua yo'qligini protsess bo'yicha eslab qoladi (qayta urinmaslik uchun)."""
    global _lua_supported
    _lua_supported = False
    logger.warning(
        "Redis Lua skriptlarini qo'llab-quvvatlamaydi — WATCH/MULTI zaxira yo'li",
        operation=operation,
        error=str(exc),
    )


def _is_lua_unsupported(exc: ResponseError) -> bool:
    """Xato "Lua yo'q" degani emasmi? (skript ichidagi xatodan ajratish uchun)

    Skriptning O'ZIDA xato bo'lsa ham `ResponseError` keladi, lekin matni
    boshqacha bo'ladi. Bunday xatoni yashirish taqiqlanadi: buzuq skript
    jimgina zaxira yo'liga o'tib, muammo ko'rinmay qolardi.
    """
    message = str(exc).lower()
    return any(marker in message for marker in _LUA_UNSUPPORTED_MARKERS)


# ---------------------------------------------------------------------------
# Servis
# ---------------------------------------------------------------------------


class ReliabilityService:
    """Lease, retry, DLQ va worker reestri — "job yo'qolmaydi" kafolati.

    Konstruktor DB sessiyasini va Redis klientini oladi. Servis holatsiz
    (yagona o'zgaruvchi holat — Lua skript keshi), shuning uchun har so'rov
    yoki har worker halqasi uchun yangisini yasash arzon.
    """

    def __init__(self, session: AsyncSession, redis: Redis | None = None) -> None:
        self.session = session
        self.redis: Redis = redis or get_redis()
        self.jobs = JobRepository(session)
        self.executions = ExecutionRepository(session)
        self.execution_logs = ExecutionLogRepository(session)
        self.dlq = DlqRepository(session)
        self.queue = QueueService(self.redis)
        self._renew_script: AsyncScript | None = None
        self._release_script: AsyncScript | None = None

    # ==================================================================
    # Lease — worker tiriklik nazorati
    # ==================================================================

    async def acquire_lease(
        self,
        job_id: uuid.UUID | str,
        worker_id: str,
        *,
        ttl: int | None = None,
    ) -> bool:
        """Job uchun lease'ni egallab oladi: `SET key worker_id NX EX ttl`.

        `NX` tufayli bu amal ATOMAR: bir job'ni ikki worker olishi mumkin
        emas, ikkinchisi `False` oladi va job'ni navbatga qaytarishi kerak.

        Lease olingach `executions.lease_expires_at` ham oldinga suriladi —
        lekin FAQAT joriy urinish `RUNNING` bo'lsa va shu worker'ga (yoki
        hech kimga) tegishli bo'lsa. Worker oqimida lease urinish
        YARATILISHIDAN OLDIN olinadi (`dequeue -> acquire_lease -> start`),
        shuning uchun ilk chaqiruvda yangilanadigan yozuv bo'lmaydi: boshlang'ich
        `lease_expires_at` ni `ExecutionService.start()` yozadi. Bu yerdagi
        yangilash qayta egallab olish holati (reaper tiklagan job) uchun.

        commit QILMAYDI — worker `session_scope()` ichida ishlaydi va
        tranzaksiya egasi o'zi.

        Args:
            job_id: Job identifikatori.
            worker_id: Lease'ni so'rayotgan worker.
            ttl: Lease muddati (soniya); `None` — `settings.LEASE_TTL_SECONDS`.

        Returns:
            `True` — lease olindi, `False` — boshqa worker ushlab turibdi
            yoki Redis javob bermadi (xavfsiz standart: ishni boshlamaymiz).
        """
        seconds = self._lease_ttl(ttl)
        key = RedisKeys.lease(job_id)

        try:
            acquired = bool(await self.redis.set(key, worker_id, nx=True, ex=seconds))
        except RedisError as exc:
            # Fail-closed: lease olinganiga ISHONCH bo'lmasa job bajarilmaydi.
            # Aks holda ikki worker bir kodni parallel ishga tushirishi mumkin
            # edi — bu Durabl'ning "bir marta bajariladi" kafolatini buzadi.
            logger.warning(
                "lease olinmadi — Redis javob bermadi",
                job_id=str(job_id),
                worker_id=worker_id,
                error=str(exc),
            )
            return False

        if not acquired:
            logger.debug(
                "lease band — job boshqa worker'da",
                job_id=str(job_id),
                worker_id=worker_id,
            )
            return False

        await self._touch_execution_lease(job_id, worker_id, seconds_from_now(seconds))
        logger.debug(
            "lease olindi",
            job_id=str(job_id),
            worker_id=worker_id,
            ttl_seconds=seconds,
        )
        return True

    async def renew_lease(
        self,
        job_id: uuid.UUID | str,
        worker_id: str,
        *,
        ttl: int | None = None,
    ) -> bool:
        """Lease'ni ATOMAR "tekshir-va-yangila" bilan uzaytiradi (heartbeat).

        Faqat lease EGASI uzaytira oladi. `False` qaytsa worker ishini
        DARHOL TO'XTATISHI kerak: lease boshqa worker'ga o'tgan va job
        allaqachon qayta bajarilmoqda (`workers/heartbeat.py` dagi
        `on_lease_lost` callback'i shu uchun bor).

        Bu metod DB'ga YOZMAYDI — ataylab: heartbeat alohida `asyncio`
        vazifasida ishlaydi va bitta `AsyncSession` ni ikki vazifada parallel
        ishlatish SQLAlchemy'da xavfli. `executions.lease_expires_at` ni
        `reap_expired_leases()` o'zi oldinga suradi (fayl boshidagi izohga
        qarang); DB'ga darhol yozish kerak bo'lsa chaqiruvchi o'z sessiyasida
        `ExecutionRepository.renew_lease(execution, until)` ni ishlatadi.

        Returns:
            `True` — uzaytirildi; `False` — egasi boshqa, lease yo'q yoki
            Redis javob bermadi (xavfsiz standart: ishni to'xtatamiz).
        """
        seconds = self._lease_ttl(ttl)
        key = RedisKeys.lease(job_id)

        renewed = await self._lease_cas(
            key,
            worker_id,
            operation="renew_lease",
            script_source=LEASE_RENEW_LUA,
            ttl=seconds,
        )
        if renewed:
            logger.debug(
                "lease uzaytirildi",
                job_id=str(job_id),
                worker_id=worker_id,
                ttl_seconds=seconds,
            )
        else:
            logger.warning(
                "lease uzaytirilmadi — egasi boshqa yoki muddati tugagan",
                job_id=str(job_id),
                worker_id=worker_id,
            )
        return renewed

    async def release_lease(self, job_id: uuid.UUID | str, worker_id: str) -> None:
        """Lease'ni bo'shatadi — ATOMAR "tekshir-va-o'chir".

        Begona lease O'CHIRILMAYDI: oddiy `DEL` bo'lsa, muddati tugab job'ni
        boshqa worker olgandan keyin "kechikkan" worker YANGI egasining
        lease'ini o'chirib yuborardi va job uchinchi worker'ga ham tushardi.

        Xato tashlamaydi: job tugagan, lease baribir TTL bo'yicha o'zi
        yo'qoladi — bo'shatish faqat tezlashtirish (keyingi worker kutib
        qolmasligi uchun).
        """
        released = await self._lease_cas(
            RedisKeys.lease(job_id),
            worker_id,
            operation="release_lease",
            script_source=LEASE_RELEASE_LUA,
            ttl=None,
        )
        if released:
            logger.debug("lease bo'shatildi", job_id=str(job_id), worker_id=worker_id)
        else:
            logger.debug(
                "lease bo'shatilmadi — egasi boshqa yoki muddati allaqachon tugagan",
                job_id=str(job_id),
                worker_id=worker_id,
            )

    async def lease_holder(self, job_id: uuid.UUID | str) -> str | None:
        """Lease'ni hozir kim ushlab turibdi (`None` — hech kim).

        Raises:
            QueueError: Redis javob bermadi. Bu metod `None` ni "lease yo'q"
                deb bildiradi, shuning uchun Redis xatosini JIM O'TKAZISH
                xavfli bo'lardi: `reap_expired_leases()` butun tirik
                worker'larning lease'ini "tugagan" deb hisoblab, hamma
                job'ni tortib olardi.
        """
        try:
            holder = await self.redis.get(RedisKeys.lease(job_id))
        except RedisError as exc:
            raise QueueError(f"Lease egasini o'qib bo'lmadi: {exc}") from exc
        return None if holder is None else str(holder)

    async def reap_expired_leases(self, *, limit: int = DEFAULT_REAP_LIMIT) -> int:
        """Muddati tugagan lease'larni yig'ib job'larni tiklaydi (reaper).

        `SchedulerWorker` shu metodni `LEASE_REAPER_INTERVAL_SECONDS` da bir
        marta chaqiradi. Har bir nomzod uchun:

        1. Redis'da lease HAQIQATAN yo'qligini tasdiqlaydi. Lease tirik bo'lsa
           — DB qiymati shunchaki eskirgan (`renew_lease` DB'ga yozmaydi), shu
           yerda oldinga suriladi va job'ga TEGILMAYDI.
        2. Urinishni `LOST` deb yopadi (`finished_at`, `failure_reason=LEASE_LOST`).
        3. `execution_logs` ga `SYSTEM` qatori qo'shadi — mijoz nega job'i
           ikkinchi marta ishlaganini loglardan ko'radi.
        4. `handle_failure(job, execution, LeaseLostError())` — retry yoki DLQ
           qarori shu metodda markazlashgan.
        5. `lease_expirations_total` metrikasini oshiradi.

        Har job uchun ALOHIDA commit: bitta buzuq job qolganlarini tiklashni
        bekor qilmasligi kerak. Shu sababli nomzodlar AVVAL identifikatorlar
        ro'yxatiga ko'chiriladi va har bir urinish halqa ichida qaytadan
        o'qiladi: `rollback()` sessiyadagi obyektlarni "eskirgan" deb
        belgilaydi va ularga keyin murojaat qilish async rejimda
        `MissingGreenlet` berardi.

        PostgreSQL'da `expired_leases()` qatorlarni `FOR UPDATE SKIP LOCKED`
        bilan qulflaydi, lekin halqa ichidagi commit qulfni BO'SHATADI —
        shuning uchun har bir urinish qaytadan `RUNNING` ekanligi
        tekshiriladi: boshqa reaper nusxasi ulgurib qo'ygan bo'lsa, u ikki
        marta tiklanmaydi.

        Returns:
            Tiklangan (retry yoki DLQ'ga o'tkazilgan) job'lar soni.
        """
        if limit <= 0:
            return 0

        candidates = await self.executions.expired_leases(utcnow(), limit)
        if not candidates:
            return 0

        pending: list[uuid.UUID] = [execution.id for execution in candidates]
        recovered = 0

        for execution_id in pending:
            execution = await self.executions.get(execution_id)
            if execution is None:
                continue
            if ExecutionStatus(execution.status) is not ExecutionStatus.RUNNING:
                # Boshqa reaper nusxasi yoki worker o'zi ulgurgan.
                continue

            try:
                if await self._lease_still_alive(execution):
                    continue
            except QueueError as exc:
                # Redis javob bermaydi — lease tirikligini tasdiqlay olmaymiz.
                # TO'XTATAMIZ: tirik worker'dan job tortib olish, kechikib
                # tiklashdan ancha xavfli (kod ikki marta bajarilardi).
                logger.error(
                    "lease reaper to'xtatildi — Redis tasdiqlab bermadi",
                    processed=recovered,
                    error=str(exc),
                )
                break

            if await self._reap_one(execution):
                recovered += 1

        if recovered:
            metrics.track_lease_expiration(recovered)
            logger.warning("muddati tugagan lease'lar yig'ildi", recovered=recovered)
        return recovered

    # ==================================================================
    # Xato va qayta urinish
    # ==================================================================

    async def handle_failure(
        self,
        job: Job,
        execution: Execution | None,
        error: ExecutionError | BaseException,
    ) -> JobStatus:
        """Xato kelganda RETRY yoki DLQ qarorini qabul qiladi.

        **Faylning eng muhim metodi.** Qaror ketma-ketligi:

        1. `RetryPolicy.for_job(job.max_retries)` — job'ning o'z limiti bilan
           siyosat (reja chegarasiga `min` qilinadi).
        2. `attempt = job.retry_count + 1` — hozir yiqilgan urinish raqami.
        3. `policy.should_retry(attempt, failure_reason=..., retryable=...)`:
           * `retryable=False` (masalan `OutOfMemoryError`) — qayta urinish
             ayni natijani beradi, shuning uchun DARHOL DLQ;
           * `failure_reason in NON_RETRYABLE_REASONS` (validatsiya xatosi,
             OOM, juda katta chiqish) — DARHOL DLQ;
           * `attempt > max_retries` — urinishlar tugadi, DLQ.
        4. Retry bo'lsa: `retry_count` oshadi, job `RETRYING` bo'ladi va
           kechiktirilgan navbatga tushadi. **Webhook YUBORILMAYDI** — har
           qayta urinish uchun webhook mijozga spam bo'lardi; mijoz faqat
           yakuniy natijani (`job.failed` / `job.dead_lettered`) oladi.

        `ExecutionError` bo'lmagan kutilmagan `Exception` avtomatik
        `ExecutionError(..., INTERNAL_ERROR, retryable=True)` ga o'raladi:
        Durabl'ning o'z xatosi mijozning job'ini "o'ldirmasligi" kerak.

        Job allaqachon YAKUNIY holatda bo'lsa (`SUCCESS`, `CANCELLED` yoki
        `DEAD_LETTER`) hech narsa qilinmaydi va joriy holat qaytariladi:
        mijoz bekor qilgan job'ni DLQ'ga tushirish uni chalg'itardi, DLQ'da
        yotgan job'ni esa "yana bir marta" qayta urinish `retry_count`
        hisobini buzardi (qo'lda tiklash uchun `retry_from_dlq()` bor).

        **Ichki metod — commit QILMAYDI.** Chaqiruvchi
        (`ExecutionService.fail()` yoki `reap_expired_leases()`) tranzaksiya
        egasi.

        Returns:
            Job'ning yangi holati: `RETRYING`, `DEAD_LETTER` yoki (hech narsa
            qilinmasa) joriy yakuniy holat.
        """
        current = JobStatus(job.status)
        if current.is_terminal:
            logger.info(
                "job yakuniy holatda — xato e'tiborsiz qoldirildi",
                job_id=str(job.id),
                status=current,
                error=str(error),
            )
            return current

        exec_error = self._as_execution_error(error)
        error_text = truncate(exec_error.message, ERROR_TEXT_MAX_CHARS)[0]
        policy = RetryPolicy.for_job(job.max_retries)
        attempt = int(job.retry_count or 0) + 1

        retry = policy.should_retry(
            attempt,
            failure_reason=exec_error.failure_reason,
            retryable=exec_error.retryable,
        )

        logger.info(
            "job xatosi tahlil qilindi",
            job_id=str(job.id),
            attempt=attempt,
            max_retries=policy.max_retries,
            failure_reason=exec_error.failure_reason,
            retryable=exec_error.retryable,
            decision=JobStatus.RETRYING if retry else JobStatus.DEAD_LETTER,
            correlation_id=job.correlation_id,
        )

        if retry:
            job.retry_count = attempt
            next_at = await self.schedule_retry(
                job,
                attempt=attempt,
                execution=execution,
                error=error_text,
                failure_reason=exec_error.failure_reason,
            )
            logger.warning(
                "job qayta urinishga rejalashtirildi",
                job_id=str(job.id),
                attempt=attempt,
                attempts_remaining=policy.attempts_remaining(attempt),
                next_retry_at=isoformat(next_at),
                correlation_id=job.correlation_id,
            )
            return JobStatus.RETRYING

        await self.move_to_dlq(
            job,
            failure_reason=exec_error.failure_reason,
            error_text=error_text,
            execution=execution,
        )
        return JobStatus.DEAD_LETTER

    async def schedule_retry(
        self,
        job: Job,
        *,
        attempt: int | None = None,
        execution: Execution | None = None,
        **fields: Any,
    ) -> datetime:
        """Job'ni eksponensial backoff bilan qayta urinishga rejalashtiradi.

        Job `RETRYING` holatiga o'tadi va `RedisKeys.DELAYED` ZSET'iga
        `score = bajarish vaqti` bilan tushadi. **`QUEUED` ga O'TKAZILMAYDI**
        — buni `scheduler` (`promote_due()`) vaqti kelganda bajaradi. Shu
        ajratish tufayli "backoff kutilmoqda" va "bajarishga tayyor" holatlari
        aralashmaydi, mijoz dashboard'da `retrying` ni ko'radi.

        Durability: DB `flush` qilinadi, keyin Redis'ga qo'yiladi. Chaqiruvchi
        commit qilmasdan qulasa, job DB'da o'z holatida qoladi va reaper/
        scheduler uni qayta oladi — ya'ni job yo'qolmaydi.

        Args:
            job: Qayta urinilayotgan job.
            attempt: Backoff hisobi uchun urinish raqami (1 = birinchi qayta
                urinish). `None` — `job.retry_count` (kamida 1).
            execution: Yiqilgan urinish — `SYSTEM` log qatorini shunga yozadi.
            **fields: `job_state.apply_transition()` ga uzatiladigan qo'shimcha
                maydonlar (`error`, `failure_reason`, ...).

        Returns:
            Keyingi urinish vaqti (UTC).

        Raises:
            InvalidStateTransitionError: Joriy holatdan `RETRYING` ga o'tish
                mumkin emas (masalan job allaqachon `CANCELLED`).
        """
        number = int(attempt) if attempt is not None else max(1, int(job.retry_count or 0))
        policy = RetryPolicy.for_job(job.max_retries)
        delay, next_at = policy.schedule(number)

        previous = JobStatus(job.status)
        job_state.apply_transition(job, JobStatus.RETRYING, **fields)
        await self.session.flush()

        await self._release_concurrency_slot(job, previous)
        await self._add_system_log(
            execution,
            f"{number}-urinish muvaffaqiyatsiz tugadi — "
            f"{delay:.1f} soniyadan keyin qayta urinib ko'riladi "
            f"({isoformat(next_at)})",
        )
        await self._enqueue(job, delay_seconds=delay)

        metrics.track_retry()
        await self._publish(job)
        return next_at

    # ==================================================================
    # DLQ — o'lik xatlar navbati
    # ==================================================================

    async def move_to_dlq(
        self,
        job: Job,
        *,
        failure_reason: FailureReason | str,
        error_text: str,
        execution: Execution | None = None,
    ) -> DlqEntry:
        """Job'ni `DEAD_LETTER` holatiga o'tkazadi va DLQ yozuvini yasaydi.

        Job "jimgina o'lmaydi": sababi (`failure_reason`), oxirgi xatosi va
        urinishlar soni bilan `dlq_entries` da qoladi.

        **Idempotent.** `dlq_entries.job_id` UNIQUE, shuning uchun ikkinchi
        chaqiruv YANGI yozuv yaratmaydi — mavjudini yangilaydi. Yozuv
        allaqachon "hal qilingan" bo'lsa QAYTA OCHILADI (`resolved=False`):
        qo'lda qayta urinish yana yiqilgan degani, ya'ni operator e'tiboriga
        qaytishi kerak. `notes` va `manual_retry_count` SAQLANADI (tarix).

        **Holat grafigi.** `JOB_STATUS_TRANSITIONS` da `RUNNING -> DEAD_LETTER`
        yo'q (faqat `RETRYING`/`FAILED` dan). Shuning uchun kerak bo'lsa avval
        oraliq `FAILED` qadami qo'llanadi: bu semantik jihatdan ham to'g'ri —
        urinish yiqildi, keyin job DLQ'ga tushdi.

        **Ichki metod — commit QILMAYDI.** Chaqiruvchi tranzaksiya egasi.

        Args:
            job: DLQ'ga o'tkazilayotgan job.
            failure_reason: Xato tasnifi (DLQ'da guruhlash uchun).
            error_text: Oxirgi xato matni (`ERROR_TEXT_MAX_CHARS` gacha kesiladi).
            execution: Oxirgi urinish — `SYSTEM` log qatori shunga yoziladi.

        Returns:
            Yaratilgan yoki yangilangan `DlqEntry`.

        Raises:
            InvalidStateTransitionError: Job `SUCCESS`/`CANCELLED` holatida —
                yakunlangan job DLQ'ga tushmaydi.
        """
        reason = FailureReason(failure_reason)
        message = truncate(error_text, ERROR_TEXT_MAX_CHARS)[0]
        previous = JobStatus(job.status)

        if previous in (JobStatus.SUCCESS, JobStatus.CANCELLED):
            raise InvalidStateTransitionError(previous, JobStatus.DEAD_LETTER)

        if not job_state.can_transition(previous, JobStatus.DEAD_LETTER):
            # Oraliq qadam: urinish avval `FAILED` deb yopiladi. `RUNNING`
            # dan `FAILED` ga o'tish grafikda bor; `PENDING`/`QUEUED` kabi
            # kutilmagan holatda esa bu tiklash amali (`validate=False`).
            job_state.apply_transition(
                job,
                JobStatus.FAILED,
                validate=job_state.can_transition(previous, JobStatus.FAILED),
                error=message,
                failure_reason=reason,
            )

        job_state.apply_transition(
            job,
            JobStatus.DEAD_LETTER,
            error=message,
            failure_reason=reason,
        )
        await self.session.flush()

        entry = await self._upsert_dlq_entry(job, reason=reason, error_text=message)
        await self._release_concurrency_slot(job, previous)
        await self._add_system_log(
            execution,
            f"Barcha urinishlar tugadi ({job.attempts_used} ta) — job DLQ'ga "
            f"o'tkazildi. Sabab: {reason.value}",
        )

        metrics.track_job_completed(JobStatus.DEAD_LETTER)
        await self._refresh_dlq_depth(alert=True)
        await self._publish(job)
        await self._dispatch(job, WebhookEvent.JOB_DEAD_LETTERED)

        logger.error(
            "job DLQ'ga o'tkazildi",
            job_id=str(job.id),
            user_id=str(job.user_id),
            failure_reason=reason,
            attempts=job.attempts_used,
            dlq_entry_id=str(entry.id),
            correlation_id=job.correlation_id,
        )
        return entry

    async def retry_from_dlq(
        self,
        entry: DlqEntry,
        *,
        by_user_id: uuid.UUID | str | None = None,
        notes: str | None = None,
        reset_retry_count: bool = True,
        resolve: bool = True,
    ) -> Job:
        """DLQ yozuvidan job'ni QO'LDA qayta uradi (mijoz kodni tuzatdi).

        Standart holatda `retry_count` NOLLANADI va xato maydonlari
        tozalanadi: bu yangi urinishlar seriyasi, mijoz muammoni bartaraf
        etgan deb hisoblanadi. Avtomatik retry tarixi
        `dlq_entries.retry_count` da va `executions` jadvalida saqlanib
        qoladi, ya'ni ma'lumot yo'qolmaydi.

        Qadamlar tartibi (durability): DB -> commit -> Redis. Navbatga
        qo'yish xato bersa job `QUEUED` holatida DB'da qoladi va scheduler
        uni qayta oladi. `reset_retry_count`/`resolve` bu tartibni
        O'ZGARTIRMAYDI — ikkisi ham AYNI commit'dan oldin qo'llanadi.

        Args:
            entry: DLQ yozuvi.
            by_user_id: Qayta urinishni boshlagan foydalanuvchi/admin.
            notes: Operator izohi (`None` — mavjud izoh o'zgarmaydi).
            reset_retry_count: `False` — `retry_count` saqlanadi, ya'ni job
                faqat QOLGAN urinishlardan foydalanadi (bitta "oxirgi imkon"
                berish uchun).
            resolve: `False` — yozuv DLQ'da HAL QILINMAGAN holda qoladi
                (operator natijani kuzatib turmoqchi); `manual_retry_count`
                baribir oshadi, demak avtomatik DLQ retry chegarasi
                hisoblanishda davom etadi.

        Returns:
            `QUEUED` holatiga o'tgan job.

        Raises:
            DlqEntryAlreadyResolvedError: Yozuv allaqachon hal qilingan.
            JobNotFoundError: Job o'chirilgan (DLQ yozuvi yetim qolgan).
        """
        if entry.resolved:
            raise DlqEntryAlreadyResolvedError(
                details={"dlq_entry_id": str(entry.id), "job_id": str(entry.job_id)}
            )

        # `entry.job` relationship'i `lazy="raise"` — ochiq so'rov SHART.
        job = await self.jobs.get(entry.job_id)
        if job is None:
            raise JobNotFoundError(entry.job_id)

        previous_execution = await self.executions.current(job.id)

        # `DEAD_LETTER -> QUEUED` grafikda ruxsat etilgan, lekin yozuv
        # `FAILED` holatida ham bo'lishi mumkin (avtomatik DLQ'dan oldin),
        # shuning uchun tekshiruv o'tkazib yuboriladi — bu ataylab qilinadigan
        # operator amali.
        changes: dict[str, Any] = {
            "error": None,
            "failure_reason": None,
            "started_at": None,
            "finished_at": None,
            "exit_code": None,
            "duration_ms": None,
        }
        if reset_retry_count:
            changes["retry_count"] = 0
        job_state.apply_transition(job, JobStatus.QUEUED, validate=False, **changes)
        entry.manual_retry_count = int(entry.manual_retry_count or 0) + 1
        if resolve:
            await self.dlq.mark_resolved(entry, resolved_by_id=by_user_id, notes=notes)
        elif notes is not None:
            # Yozuv DLQ'da qoladi, lekin operator izohi yo'qolmasligi kerak.
            await self.dlq.update(entry, notes=notes)
        await self.session.commit()

        await self._add_system_log(
            previous_execution,
            f"DLQ'dan qo'lda qayta urinish (#{entry.manual_retry_count}) — "
            "job qayta navbatga qo'yildi",
        )
        await self._enqueue(job)
        await self._refresh_dlq_depth(alert=False)
        await self._publish(job)

        logger.info(
            "job DLQ'dan qayta urildi",
            job_id=str(job.id),
            dlq_entry_id=str(entry.id),
            manual_retry_count=entry.manual_retry_count,
            by_user_id=None if by_user_id is None else str(by_user_id),
            correlation_id=job.correlation_id,
        )
        return job

    # ==================================================================
    # Mijoz DLQ API'si (`/dlq` routeri ishlatadi)
    # ==================================================================
    #
    # Bu to'rt ommaviy metod (+ uch yordamchi) API qatlami uchun QO'SHILDI:
    # router `select()` yozmaydi
    # va repozitoriyga bevosita tegmaydi, `DlqRepository` da esa `DlqFilter`
    # ning barcha kesimlari (`job_id`, `start`/`end`, tartiblash) uchun metod
    # yo'q. Shu sababli so'rov ayni shu yerda yig'iladi — `repositories/` ga
    # tegilmagan.

    async def list_dlq(
        self,
        user_id: uuid.UUID | str,
        filters: DlqFilter,
        pagination: PaginationParams,
    ) -> tuple[list[DlqEntry], int]:
        """Foydalanuvchining DLQ yozuvlari: `(yozuvlar, umumiy_son)`.

        `user_id` sharti HAR DOIM qo'llanadi — boshqa egadagi yozuv natijaga
        tushmaydi (IDOR himoyasi).

        Tegishli job `selectinload(DlqEntry.job)` bilan OCHIQ yuklanadi:
        barcha relationship'lar `lazy="raise"`, ya'ni `DlqEntryRead` ning
        `job` maydoni busiz `InvalidRequestError` berardi.

        Tartiblash oq ro'yxati `DLQ_SORT_COLUMNS` da; ikkilamchi kalit
        sifatida `id` qo'shiladi — aks holda bir xil `failed_at` ga ega
        yozuvlar sahifalar orasida "sakrab" ketardi.
        """
        conditions = self._dlq_conditions(user_id, filters)

        total_stmt = select(func.count()).select_from(DlqEntry).where(*conditions)
        total = int((await self._fetch(total_stmt)).scalar_one() or 0)

        column = DLQ_SORT_COLUMNS.get(filters.sort_by, DLQ_DEFAULT_SORT_COLUMN)
        direction = asc if filters.sort_order == "asc" else desc
        stmt = (
            select(DlqEntry)
            .where(*conditions)
            .options(selectinload(DlqEntry.job))
            .order_by(direction(column), DlqEntry.id.asc())
            .offset(pagination.offset)
            .limit(pagination.limit)
        )
        rows = list((await self._fetch(stmt)).scalars().all())
        return rows, total

    async def get_dlq_entry(
        self,
        user_id: uuid.UUID | str,
        entry_id: uuid.UUID | str,
    ) -> DlqEntry:
        """Bitta DLQ yozuvi (egalik tekshirilgan, job bilan birga).

        Boshqa foydalanuvchining yozuvi ham "topilmadi" deb qaytariladi —
        resurs borligini oshkor qilmaymiz.

        Raises:
            DlqEntryNotFoundError: Yozuv yo'q yoki boshqa egaga tegishli.
        """
        stmt = (
            select(DlqEntry)
            .where(
                DlqEntry.id == self._dlq_id(entry_id),
                DlqEntry.user_id == self._dlq_id(user_id),
            )
            .options(selectinload(DlqEntry.job))
        )
        entry = (await self._fetch(stmt)).scalars().first()
        if entry is None:
            raise DlqEntryNotFoundError(entry_id)
        return entry

    async def retry_dlq_entry(
        self,
        user_id: uuid.UUID | str,
        entry_id: uuid.UUID | str,
        data: DlqRetryRequest,
    ) -> tuple[DlqEntry, Job]:
        """DLQ yozuvidan job'ni qayta uradi: `(yozuv, job)`.

        `retry_from_dlq()` ustidagi yupqa qobiq — mijoz so'rovidagi
        `priority`, `max_retries` va `timeout_seconds` ni job'ga QO'LLAYDI,
        `reset_retry_count` bilan `resolve` ni esa asosiy metodga uzatadi.
        Barcha o'zgarishlar AYNI tranzaksiyada ketadi: `retry_from_dlq()`
        oxirida `commit()` qiladi, bu yerdagi `update()` esa faqat `flush` —
        ya'ni job yarim o'zgargan holda qolmaydi.

        `DlqRetryRequest.mark_resolved` schema darajasida `resolve` ga
        normallashtirilgan, shuning uchun bu yerda faqat `resolve` o'qiladi.

        Raises:
            DlqEntryNotFoundError: Yozuv yo'q yoki boshqa egaga tegishli.
            DlqEntryAlreadyResolvedError: Yozuv allaqachon hal qilingan.
            JobNotFoundError: Job o'chirilgan (yozuv yetim qolgan).
        """
        entry = await self.get_dlq_entry(user_id, entry_id)
        if entry.resolved:
            # `retry_from_dlq()` ham shu xatoni tashlaydi, lekin tekshiruv
            # job maydonlarini O'ZGARTIRISHDAN OLDIN bo'lishi kerak.
            raise DlqEntryAlreadyResolvedError(
                details={"dlq_entry_id": str(entry.id), "job_id": str(entry.job_id)}
            )

        values: dict[str, Any] = {}
        if data.priority is not None:
            values["priority"] = Priority(data.priority)
        if data.max_retries is not None:
            values["max_retries"] = int(data.max_retries)
        if data.timeout_seconds is not None:
            values["timeout_seconds"] = int(data.timeout_seconds)
        if values:
            job = await self.jobs.get(entry.job_id)
            if job is None:
                raise JobNotFoundError(entry.job_id)
            await self.jobs.update(job, **values)

        job = await self.retry_from_dlq(
            entry,
            by_user_id=user_id,
            notes=data.notes,
            reset_retry_count=data.reset_retry_count,
            resolve=data.resolve,
        )
        return entry, job

    async def resolve_dlq_entry(
        self,
        user_id: uuid.UUID | str,
        entry_id: uuid.UUID | str,
        *,
        notes: str | None = None,
    ) -> DlqEntry:
        """Yozuvni hal qilingan deb belgilaydi (`DELETE /dlq/{id}`).

        Yozuv FIZIK o'chirilmaydi: `job_id` unique, ya'ni o'chirilgan yozuv
        job yana yiqilganda qayta yaratilardi va "bu muammoni ko'rib
        chiqdim" tarixi yo'qolardi. Shuning uchun "o'chirish" = chuqurlikdan
        olib tashlash (`resolved=True`).

        **Idempotent**: allaqachon hal qilingan yozuv uchun xato
        TASHLANMAYDI, yozuv o'zgarmagan holda qaytadi — `DELETE` ni
        takrorlash xavfsiz bo'lishi kerak.

        Raises:
            DlqEntryNotFoundError: Yozuv yo'q yoki boshqa egaga tegishli.
        """
        entry = await self.get_dlq_entry(user_id, entry_id)
        if entry.resolved:
            return entry

        await self.dlq.mark_resolved(entry, resolved_by_id=user_id, notes=notes)
        await self.session.commit()
        await self._refresh_dlq_depth(alert=False)

        logger.info(
            "DLQ yozuvi hal qilingan deb belgilandi",
            dlq_entry_id=str(entry.id),
            job_id=str(entry.job_id),
            by_user_id=str(user_id),
        )
        return entry

    def _dlq_conditions(
        self,
        user_id: uuid.UUID | str,
        filters: DlqFilter,
    ) -> list[ColumnElement[Any]]:
        """`DlqFilter` ni WHERE shartlariga aylantiradi (`None` — filtr yo'q)."""
        conditions: list[ColumnElement[Any]] = [
            DlqEntry.user_id == self._dlq_id(user_id),
        ]
        if filters.resolved is not None:
            conditions.append(DlqEntry.resolved.is_(filters.resolved))
        if filters.failure_reason is not None:
            conditions.append(DlqEntry.failure_reason == FailureReason(filters.failure_reason))
        if filters.job_id is not None:
            conditions.append(DlqEntry.job_id == self._dlq_id(filters.job_id))
        if filters.search is not None:
            # Frontend DLQ sahifasidagi qidiruv maydoni (`?search=`) aynan shu
            # shartga tushadi: xato matni YOKI operator izohi bo'yicha.
            # `ilike` ataylab: PostgreSQL'da `citext` ishlatilmaydi, SQLite'da
            # esa `LIKE` registrga sezgir bo'lmagan holda ishlaydi.
            pattern = f"%{filters.search}%"
            conditions.append(
                or_(DlqEntry.last_error.ilike(pattern), DlqEntry.notes.ilike(pattern))
            )
        if filters.start is not None:
            conditions.append(DlqEntry.failed_at >= filters.start)
        if filters.end is not None:
            conditions.append(DlqEntry.failed_at <= filters.end)
        return conditions

    @staticmethod
    def _dlq_id(value: uuid.UUID | str) -> uuid.UUID | str:
        """Matn ko'rinishidagi UUID'ni `uuid.UUID`ga keltiradi.

        `BaseRepository._coerce_id` bilan AYNI shartnoma: aylantirib
        bo'lmasa qiymat o'z holida qoladi va SQL darajasida "mos kelmadi"
        bo'lib ishlaydi (xato o'rniga bo'sh natija).
        """
        if isinstance(value, uuid.UUID):
            return value
        try:
            return uuid.UUID(str(value))
        except (ValueError, AttributeError, TypeError):
            return value

    async def _fetch(self, stmt: Any) -> Any:
        """`select()` ni bajaradi va drayver xatosini `DatabaseError`ga o'raydi.

        Repozitoriylardagi `_execute()` bilan AYNI shartnoma — API qatlami
        barcha DB xatolarini bitta domen xatosi sifatida ko'radi.
        """
        try:
            return await self.session.execute(stmt)
        except SQLAlchemyError as exc:  # pragma: no cover - infratuzilma xatosi
            raise DatabaseError(f"SQL bajarishda xato: {exc}") from exc

    # ==================================================================
    # Worker reestri
    # ==================================================================

    async def register_worker(
        self,
        worker_id: str,
        *,
        state: WorkerState | str = WorkerState.STARTING,
        **meta: Any,
    ) -> None:
        """Worker'ni reestrga yozadi (`RedisKeys.WORKERS` HASH + heartbeat kaliti).

        Ikki kalit ataylab ajratilgan:

        * HASH — worker haqidagi TO'LIQ ma'lumot (hostname, pid, holat,
          bajargan job'lar soni). HASH maydonining TTL'i bo'lmaydi.
        * `RedisKeys.worker_heartbeat(worker_id)` — TTL'li "tiriklik" kaliti
          (`settings.WORKER_REGISTRY_TTL_SECONDS`). Worker qulasa shu kalit
          O'ZI yo'qoladi va `list_workers()` uni `DEAD` deb ko'rsatadi.

        `meta` ga har qanday qo'shimcha maydon berish mumkin
        (`concurrency`, `version`, ...) — hammasi JSON'da saqlanadi.
        """
        now = utcnow()
        record: dict[str, Any] = {
            "worker_id": worker_id,
            "state": WorkerState(state),
            "hostname": socket.gethostname(),
            "pid": os.getpid(),
            "version": settings.APP_VERSION,
            "concurrency": settings.WORKER_CONCURRENCY,
            "current_job_id": None,
            "jobs_processed": 0,
            "started_at": now,
            "last_heartbeat": now,
            "last_heartbeat_at": now,
        }
        record.update(self._clean_meta(meta))

        await self._write_worker(worker_id, record)
        logger.info(
            "worker ro'yxatdan o'tdi",
            worker_id=worker_id,
            state=record["state"],
            hostname=record["hostname"],
            pid=record["pid"],
        )
        await self._refresh_worker_metric()

    async def heartbeat_worker(self, worker_id: str, **meta: Any) -> None:
        """Worker tirikligini bildiradi va reestrdagi ma'lumotini yangilaydi.

        Heartbeat kalitining TTL'i qayta qo'yiladi, HASH yozuviga esa
        `meta` birlashtiriladi (`state`, `current_job_id`, `jobs_processed` —
        worker nimani o'zgartirgan bo'lsa). Mavjud maydonlar `meta` da
        bo'lmasa O'ZGARMAYDI.

        Yozuv HASH'da topilmasa (worker `prune_dead_workers()` dan keyin
        "tirilgan" yoki Redis tozalangan) — o'zini qayta yozadi. Shu
        o'z-o'zini tiklash tufayli worker admin panelidan "yo'qolib"
        qolmaydi.
        """
        now = utcnow()
        record = await self._read_worker(worker_id)
        if record is None:
            record = {
                "worker_id": worker_id,
                "state": WorkerState.IDLE,
                "hostname": socket.gethostname(),
                "pid": os.getpid(),
                "version": settings.APP_VERSION,
                "concurrency": settings.WORKER_CONCURRENCY,
                "current_job_id": None,
                "jobs_processed": 0,
                "started_at": now,
            }
            logger.warning(
                "worker reestrda topilmadi — yozuv qayta yaratildi",
                worker_id=worker_id,
            )

        record.update(self._clean_meta(meta))
        record["worker_id"] = worker_id
        record["last_heartbeat"] = now
        record["last_heartbeat_at"] = now

        await self._write_worker(worker_id, record)

    async def unregister_worker(self, worker_id: str) -> None:
        """Worker'ni reestrdan o'chiradi (graceful shutdown).

        HASH yozuvi va heartbeat kaliti birga o'chiriladi. Xato tashlamaydi:
        to'xtash yo'lidagi Redis muammosi protsessni yiqitmasligi kerak —
        heartbeat kaliti baribir TTL bo'yicha o'zi yo'qoladi.
        """
        try:
            async with self.redis.pipeline(transaction=False) as pipe:
                pipe.hdel(RedisKeys.WORKERS, worker_id)
                pipe.delete(RedisKeys.worker_heartbeat(worker_id))
                await pipe.execute()
        except RedisError as exc:
            logger.warning(
                "worker reestrdan o'chirilmadi",
                worker_id=worker_id,
                error=str(exc),
            )
            return

        logger.info("worker reestrdan o'chirildi", worker_id=worker_id)
        await self._refresh_worker_metric()

    async def list_workers(self) -> list[dict[str, Any]]:
        """Ro'yxatdan o'tgan barcha worker'lar (admin paneli uchun).

        Har bir worker uchun heartbeat kaliti mavjudligi TEKSHIRILADI: kalit
        yo'q bo'lsa holat `WorkerState.DEAD` ga majburan o'zgartiriladi —
        HASH'dagi `state="busy"` yozuvi worker qulaganda ham o'sha yerda
        qolib ketadi, shuning uchun unga ishonib bo'lmaydi.

        Qaytaradigan lug'at kalitlari (`schemas.admin.WorkerInfo` bilan mos):
        `worker_id`, `state`, `hostname`, `pid`, `version`, `started_at`,
        `last_heartbeat`, `last_heartbeat_at`, `seconds_since_heartbeat`,
        `current_job_id`, `jobs_processed`, `concurrency`, `is_alive`.

        `last_heartbeat` va `last_heartbeat_at` AYNI qiymat: birinchisi shu
        servisning shartnomasida, ikkinchisi tayyor `WorkerInfo` schema'sida
        kelishilgan nom — ikkisi ham beriladi, shuning uchun
        `WorkerInfo(**row)` to'g'ridan-to'g'ri ishlaydi.

        Redis javob bermasa bo'sh ro'yxat qaytadi (admin paneli xato
        o'rniga "worker yo'q" ko'rsatadi) — xato log qilinadi.
        """
        records = await self._read_all_workers()
        if not records:
            return []

        worker_ids = sorted(records)
        alive = await self._heartbeats_alive(worker_ids)

        workers: list[dict[str, Any]] = []
        for worker_id in worker_ids:
            record = records[worker_id]
            workers.append(self._present_worker(worker_id, record, alive=alive.get(worker_id, False)))

        metrics.set_active_workers(sum(1 for row in workers if row["is_alive"]))
        return workers

    async def prune_dead_workers(self) -> int:
        """Heartbeat'i kelmay qolgan worker'larni reestrdan tozalaydi.

        Har bir o'chirilgan worker uchun `NotificationService.notify_worker_down()`
        chaqiriladi — operator worker qulaganini BILISHI kerak, chunki uning
        job'lari `reap_expired_leases()` orqali qayta taqsimlanadi (ya'ni
        kechikish mijozga sezilarli bo'lishi mumkin).

        Returns:
            O'chirilgan worker'lar soni.
        """
        records = await self._read_all_workers()
        if not records:
            metrics.set_active_workers(0)
            return 0

        worker_ids = sorted(records)
        alive = await self._heartbeats_alive(worker_ids)
        dead = [worker_id for worker_id in worker_ids if not alive.get(worker_id, False)]

        if not dead:
            metrics.set_active_workers(len(worker_ids))
            return 0

        try:
            await self.redis.hdel(RedisKeys.WORKERS, *dead)
        except RedisError as exc:
            logger.warning(
                "qulagan worker'lar tozalanmadi",
                workers=dead,
                error=str(exc),
            )
            return 0

        metrics.set_active_workers(max(0, len(worker_ids) - len(dead)))
        for worker_id in dead:
            logger.error(
                "worker qulagan deb belgilandi va reestrdan o'chirildi",
                worker_id=worker_id,
                heartbeat_ttl_seconds=settings.WORKER_REGISTRY_TTL_SECONDS,
            )
            await self._notify_worker_down(worker_id)
        return len(dead)

    # ==================================================================
    # Bekor qilish signali
    # ==================================================================

    async def request_cancel(self, job_id: uuid.UUID | str) -> None:
        """Bajarilayotgan job uchun bekor qilish signalini yozadi.

        Sandbox'ni tashqaridan "o'ldirish" worker'ning ishi, lekin signalni
        boshqa protsess (API yoki admin) beradi — shuning uchun kooperativ
        to'xtatish: signal Redis'da turadi, worker esa heartbeat oynasida
        `is_cancel_requested()` ni tekshiradi.

        Kalit `JobService.cancel()` yozadigan kalit bilan AYNAN bir xil
        (`RedisKeys.cache(CANCEL_NAMESPACE, job_id)`), shuning uchun ikki
        yo'ldan qo'yilgan signal bir xil o'qiladi.

        Signal `MAX_TIMEOUT_SECONDS + LEASE_TTL + grace` davomida yashaydi
        (eng uzun job ham signalni ko'rib qolishi uchun). Worker job'ni
        yopgandan keyin `clear_cancel()` chaqirishi TAVSIYA ETILADI — aks
        holda qoldiq signal shu `job_id` ning keyingi urinishiga ta'sir
        qilishi mumkin.
        """
        ttl = (
            settings.MAX_TIMEOUT_SECONDS
            + settings.LEASE_TTL_SECONDS
            + CANCEL_SIGNAL_GRACE_SECONDS
        )
        try:
            await self.redis.set(
                RedisKeys.cache(CANCEL_NAMESPACE, job_id),
                JobStatus.CANCELLED.value,
                ex=ttl,
            )
        except RedisError as exc:
            logger.warning(
                "bekor qilish signali yozilmadi",
                job_id=str(job_id),
                error=str(exc),
            )
            return
        logger.info("bekor qilish signali yozildi", job_id=str(job_id), ttl_seconds=ttl)

    async def is_cancel_requested(self, job_id: uuid.UUID | str) -> bool:
        """Job uchun bekor qilish so'ralganmi? (worker heartbeat'da tekshiradi)

        Redis javob bermasa `False` qaytadi (fail-open): "bilmayman" ni
        "bekor qil" deb tushunish ishlab turgan job'ni bekorga o'ldirardi.
        Eng yomon holat — job oxirigacha ishlaydi, lekin mijoz baribir
        `CANCELLED` holatini ko'radi (holat PostgreSQL'da).
        """
        try:
            return bool(await self.redis.exists(RedisKeys.cache(CANCEL_NAMESPACE, job_id)))
        except RedisError as exc:
            logger.warning(
                "bekor qilish signali o'qilmadi",
                job_id=str(job_id),
                error=str(exc),
            )
            return False

    async def clear_cancel(self, job_id: uuid.UUID | str) -> None:
        """Bekor qilish signalini o'chiradi (job yopilgandan keyin)."""
        try:
            await self.redis.delete(RedisKeys.cache(CANCEL_NAMESPACE, job_id))
        except RedisError as exc:
            logger.warning(
                "bekor qilish signali o'chirilmadi",
                job_id=str(job_id),
                error=str(exc),
            )

    # ==================================================================
    # Ichki yordamchilar — lease
    # ==================================================================

    @staticmethod
    def _lease_ttl(ttl: int | None) -> int:
        """Lease muddatini normallashtiradi (Redis `EX` kamida 1 soniya)."""
        seconds = settings.LEASE_TTL_SECONDS if ttl is None else int(ttl)
        return max(1, seconds)

    async def _lease_cas(
        self,
        key: str,
        worker_id: str,
        *,
        operation: str,
        script_source: str,
        ttl: int | None,
    ) -> bool:
        """ATOMAR "tekshir-va-yoz": Lua bor bo'lsa skript, yo'q bo'lsa WATCH/MULTI.

        `ttl=None` — kalit O'CHIRILADI (`release`), aks holda `EXPIRE`
        (`renew`). Redis xatosi `False` bilan qaytadi: ikki amalda ham
        "bajarilmadi" deb hisoblash XAVFSIZ standart (worker ishini
        to'xtatadi yoki lease TTL bo'yicha o'zi yo'qoladi).
        """
        result = await self._lease_cas_lua(
            key, worker_id, operation=operation, script_source=script_source, ttl=ttl
        )
        if result is not None:
            return result
        return await self._lease_cas_watch(key, worker_id, operation=operation, ttl=ttl)

    async def _lease_cas_lua(
        self,
        key: str,
        worker_id: str,
        *,
        operation: str,
        script_source: str,
        ttl: int | None,
    ) -> bool | None:
        """Lua skript bilan CAS; Lua qo'llab-quvvatlanmasa `None` qaytaradi."""
        if _lua_supported is False:
            return None

        script = self._script(operation, script_source)
        args: list[Any] = [worker_id] if ttl is None else [worker_id, ttl]
        try:
            return bool(await script(keys=[key], args=args))
        except ResponseError as exc:
            if _is_lua_unsupported(exc):
                _mark_lua_unsupported(operation, exc)
                return None
            # Skriptning O'ZIDA xato — yashirilmaydi, lekin lease amali
            # ilovani yiqitmasligi kerak.
            logger.error("lease skripti xato berdi", operation=operation, error=str(exc))
            return False
        except RedisError as exc:
            logger.warning("lease amali bajarilmadi", operation=operation, error=str(exc))
            return False

    def _script(self, operation: str, source: str) -> AsyncScript:
        """Skriptni dangasa ro'yxatdan o'tkazadi va keshlaydi."""
        if operation == "release_lease":
            if self._release_script is None:
                self._release_script = self.redis.register_script(source)
            return self._release_script
        if self._renew_script is None:
            self._renew_script = self.redis.register_script(source)
        return self._renew_script

    async def _lease_cas_watch(
        self,
        key: str,
        worker_id: str,
        *,
        operation: str,
        ttl: int | None,
    ) -> bool:
        """Lua'siz CAS: `WATCH` -> `GET` -> `MULTI` -> `EXPIRE`/`DEL`.

        `WATCH` qo'yilgandan keyin kalit boshqa klient tomonidan
        o'zgartirilsa `EXEC` bajarilmaydi (`WatchError`) — ya'ni atomarlik
        Lua'siz ham saqlanadi, faqat poyga holatida qayta urinish kerak.
        """
        for _ in range(CAS_MAX_ATTEMPTS):
            try:
                async with self.redis.pipeline(transaction=True) as pipe:
                    await pipe.watch(key)
                    holder = await pipe.get(key)
                    if holder is None or str(holder) != worker_id:
                        await pipe.unwatch()
                        return False
                    pipe.multi()
                    if ttl is None:
                        pipe.delete(key)
                    else:
                        pipe.expire(key, ttl)
                    results = await pipe.execute()
                return bool(results and results[0])
            except WatchError:
                continue  # Kalit o'zgardi — qaytadan o'qib ko'ramiz
            except RedisError as exc:
                logger.warning(
                    "lease amali bajarilmadi (WATCH yo'li)",
                    operation=operation,
                    error=str(exc),
                )
                return False

        logger.warning(
            "lease amali poyga tufayli bajarilmadi",
            operation=operation,
            attempts=CAS_MAX_ATTEMPTS,
        )
        return False

    async def _lease_still_alive(self, execution: Execution) -> bool:
        """Redis'da lease hamon turganmi? Turgan bo'lsa DB qiymati suriladi.

        `renew_lease()` DB'ga yozmaydi, shuning uchun uzoq ishlayotgan
        job'ning `executions.lease_expires_at` i eskirib `expired_leases()`
        so'roviga tushib qoladi. Bu ADASHISH emas — ayni shu yerda tuzatiladi:
        Redis'dagi haqiqiy qolgan muddat olinadi va DB qiymati shunga
        moslanadi, shuning uchun keyingi reaper aylanishi bu yozuvni
        qaytadan ko'rmaydi.

        Raises:
            QueueError: Redis javob bermadi (chaqiruvchi reaping'ni to'xtatadi).
        """
        holder = await self.lease_holder(execution.job_id)
        if holder is None:
            return False

        try:
            remaining = int(await self.redis.ttl(RedisKeys.lease(execution.job_id)))
        except RedisError:
            remaining = -1
        if remaining <= 0:
            remaining = settings.LEASE_TTL_SECONDS

        try:
            await self.executions.renew_lease(execution, seconds_from_now(remaining))
        except Exception as exc:  # tuzatish best-effort
            logger.warning(
                "DB'dagi lease muddati surilmadi",
                execution_id=str(execution.id),
                error=str(exc),
            )

        logger.debug(
            "lease hamon tirik — job tortib olinmadi",
            job_id=str(execution.job_id),
            worker_id=holder,
            ttl_seconds=remaining,
        )
        return True

    async def _reap_one(self, execution: Execution) -> bool:
        """Bitta yo'qolgan urinishni yopadi va job uchun qaror qabul qiladi.

        Returns:
            `True` — job tiklandi (retry yoki DLQ), `False` — tiklanmadi
            (job o'chirilgan yoki xato yuz berdi).
        """
        job = await self.jobs.get(execution.job_id)
        now = utcnow()

        try:
            await self.executions.finish(
                execution,
                status=ExecutionStatus.LOST,
                finished_at=now,
                failure_reason=FailureReason.LEASE_LOST,
                error_message=LEASE_LOST_MESSAGE,
                lease_expires_at=None,
            )
            await self._add_system_log(execution, LEASE_LOST_MESSAGE)

            if job is None:
                # Job o'chirilgan (foydalanuvchi hisobi o'chdi) — urinishni
                # yopish kifoya, aks holda bu yozuv reaper'ni abadiy band
                # qilib turardi.
                await self.session.commit()
                logger.warning(
                    "yo'qolgan urinishning job'i topilmadi — faqat urinish yopildi",
                    execution_id=str(execution.id),
                    job_id=str(execution.job_id),
                )
                return False

            logger.warning(
                "worker javob bermadi — lease muddati tugadi",
                job_id=str(job.id),
                execution_id=str(execution.id),
                attempt_number=execution.attempt_number,
                worker_id=execution.worker_id,
                correlation_id=job.correlation_id,
            )

            status = await self.handle_failure(job, execution, LeaseLostError())
            await self.session.commit()
        except Exception as exc:  # bitta job qolganlarini buzmaydi
            await self.session.rollback()
            logger.error(
                "yo'qolgan lease tiklanmadi",
                execution_id=str(execution.id),
                job_id=str(execution.job_id),
                error=str(exc),
            )
            return False

        logger.info(
            "yo'qolgan job tiklandi",
            job_id=str(job.id),
            status=status,
            retry_count=job.retry_count,
        )
        return True

    async def _touch_execution_lease(
        self,
        job_id: uuid.UUID | str,
        worker_id: str,
        until: datetime,
    ) -> None:
        """Joriy urinishning DB'dagi lease muddatini oldinga suradi.

        Faqat `RUNNING` va shu worker'ga (yoki hech kimga) tegishli urinish
        yangilanadi: aks holda lease YANGI urinish uchun olinganda, OLDINGI
        yiqilgan urinishning yozuvi o'zgarib ketardi.
        """
        try:
            execution = await self.executions.current(job_id)
            if execution is None:
                return
            if ExecutionStatus(execution.status) is not ExecutionStatus.RUNNING:
                return
            if execution.worker_id is not None and execution.worker_id != worker_id:
                return
            await self.executions.renew_lease(execution, until)
        except Exception as exc:  # ko'rinish uchun, kafolat emas
            logger.warning(
                "DB'da lease muddati yozilmadi",
                job_id=str(job_id),
                worker_id=worker_id,
                error=str(exc),
            )

    # ==================================================================
    # Ichki yordamchilar — DLQ
    # ==================================================================

    async def _upsert_dlq_entry(
        self,
        job: Job,
        *,
        reason: FailureReason,
        error_text: str,
    ) -> DlqEntry:
        """DLQ yozuvini yaratadi yoki mavjudini yangilaydi (`job_id` UNIQUE)."""
        now = utcnow()
        existing = await self.dlq.get_by_job(job.id)
        if existing is not None:
            return await self.dlq.update(
                existing,
                failure_reason=reason,
                last_error=error_text,
                failed_at=now,
                retry_count=int(job.retry_count or 0),
                # Qayta yiqilgan job operator e'tiboriga QAYTADI.
                resolved=False,
                resolved_at=None,
            )

        return await self.dlq.create(
            job_id=job.id,
            user_id=job.user_id,
            failure_reason=reason,
            last_error=error_text,
            failed_at=now,
            retry_count=int(job.retry_count or 0),
        )

    async def _refresh_dlq_depth(self, *, alert: bool) -> None:
        """`dlq_depth` metrikasini aniqlashtiradi va kerak bo'lsa alert beradi."""
        try:
            depth = await self.dlq.depth()
        except Exception as exc:  # metrika job'ni buzmaydi
            logger.warning("DLQ chuqurligi o'qilmadi", error=str(exc))
            return

        metrics.set_dlq_depth(depth)
        if alert and depth > settings.DLQ_ALERT_THRESHOLD:
            await self._notify_dlq_threshold(depth)

    # ==================================================================
    # Ichki yordamchilar — worker reestri
    # ==================================================================

    async def _write_worker(self, worker_id: str, record: dict[str, Any]) -> None:
        """Worker yozuvini HASH'ga yozadi va heartbeat kalitini yangilaydi."""
        ttl = max(1, settings.WORKER_REGISTRY_TTL_SECONDS)
        # `isoformat()` faqat `None` kirishda `None` qaytaradi; bu yerda
        # qiymat `or utcnow()` bilan kafolatlangan, ya'ni bo'sh matn
        # HECH QACHON yozilmaydi (zaxira faqat tur tekshiruvchi uchun).
        beat = isoformat(_as_dt(record.get("last_heartbeat")) or utcnow()) or ""
        try:
            async with self.redis.pipeline(transaction=False) as pipe:
                pipe.hset(RedisKeys.WORKERS, worker_id, dump_json(record))
                pipe.set(RedisKeys.worker_heartbeat(worker_id), beat, ex=ttl)
                await pipe.execute()
        except RedisError as exc:
            logger.warning(
                "worker reestri yangilanmadi",
                worker_id=worker_id,
                error=str(exc),
            )

    async def _read_worker(self, worker_id: str) -> dict[str, Any] | None:
        """HASH'dagi bitta worker yozuvi (buzuq JSON bo'lsa `None`)."""
        try:
            raw = await self.redis.hget(RedisKeys.WORKERS, worker_id)
        except RedisError as exc:
            logger.warning("worker yozuvi o'qilmadi", worker_id=worker_id, error=str(exc))
            return None
        return self._parse_worker(worker_id, raw)

    async def _read_all_workers(self) -> dict[str, dict[str, Any]]:
        """Reestrdagi barcha worker yozuvlari (buzuq yozuvlar tashlab yuboriladi)."""
        try:
            raw_map = await self.redis.hgetall(RedisKeys.WORKERS)
        except RedisError as exc:
            logger.error("worker reestri o'qilmadi", error=str(exc))
            return {}

        records: dict[str, dict[str, Any]] = {}
        for worker_id, raw in (raw_map or {}).items():
            parsed = self._parse_worker(str(worker_id), raw)
            if parsed is not None:
                records[str(worker_id)] = parsed
        return records

    async def _heartbeats_alive(self, worker_ids: list[str]) -> dict[str, bool]:
        """Har bir worker uchun heartbeat kaliti mavjudmi (bitta pipeline'da).

        Redis javob bermasa hamma `True` deb hisoblanadi: Redis uzilishida
        barcha worker'ni "qulagan" deb e'lon qilib, reestrni bo'shatib
        yuborish yolg'on alert to'foni bo'lardi.
        """
        if not worker_ids:
            return {}
        try:
            async with self.redis.pipeline(transaction=False) as pipe:
                for worker_id in worker_ids:
                    pipe.exists(RedisKeys.worker_heartbeat(worker_id))
                results = await pipe.execute()
        except RedisError as exc:
            logger.warning("worker heartbeat'lari tekshirilmadi", error=str(exc))
            return dict.fromkeys(worker_ids, True)

        return {
            worker_id: bool(result)
            for worker_id, result in zip(worker_ids, results, strict=False)
        }

    def _present_worker(
        self,
        worker_id: str,
        record: dict[str, Any],
        *,
        alive: bool,
    ) -> dict[str, Any]:
        """Reestr yozuvini admin paneli uchun tayyor lug'atga aylantiradi."""
        last_heartbeat = record.get("last_heartbeat") or record.get("last_heartbeat_at")
        state = WorkerState.DEAD if not alive else self._coerce_state(record.get("state"))
        since = None if last_heartbeat is None else max(0.0, -seconds_until(_as_dt(last_heartbeat)))

        return {
            "worker_id": worker_id,
            "state": state,
            "hostname": record.get("hostname"),
            "pid": self._as_int(record.get("pid")),
            "version": record.get("version"),
            "started_at": record.get("started_at"),
            "last_heartbeat": last_heartbeat,
            "last_heartbeat_at": last_heartbeat,
            "seconds_since_heartbeat": since,
            "current_job_id": record.get("current_job_id"),
            "jobs_processed": self._as_int(record.get("jobs_processed")) or 0,
            "concurrency": self._as_int(record.get("concurrency")) or 0,
            "is_alive": alive and state not in (WorkerState.DEAD, WorkerState.STOPPED),
        }

    async def _refresh_worker_metric(self) -> None:
        """`active_workers` gauge'ini aniq qiymatga keltiradi."""
        records = await self._read_all_workers()
        if not records:
            metrics.set_active_workers(0)
            return
        alive = await self._heartbeats_alive(sorted(records))
        metrics.set_active_workers(sum(1 for value in alive.values() if value))

    @staticmethod
    def _parse_worker(worker_id: str, raw: Any) -> dict[str, Any] | None:
        """JSON yozuvni lug'atga ochadi; buzuq bo'lsa `None` va ogohlantirish."""
        if raw is None:
            return None
        try:
            parsed = load_json(raw)
        except Exception as exc:  # buzuq yozuv reestrni buzmaydi
            logger.warning("worker yozuvi buzuq", worker_id=worker_id, error=str(exc))
            return None
        if not isinstance(parsed, dict):
            logger.warning("worker yozuvi lug'at emas", worker_id=worker_id)
            return None
        return parsed

    @staticmethod
    def _coerce_state(value: Any) -> WorkerState:
        """Noma'lum holat qiymatini `IDLE` ga keltiradi (reestr buzilmasin)."""
        if value is None:
            return WorkerState.IDLE
        try:
            return WorkerState(value)
        except ValueError:
            return WorkerState.IDLE

    @staticmethod
    def _as_int(value: Any) -> int | None:
        """Qiymatni butun songa keltiradi; bo'lmasa `None`."""
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _clean_meta(meta: dict[str, Any]) -> dict[str, Any]:
        """`**meta` dan `None` qiymatlarni chiqarib tashlaydi.

        `heartbeat_worker(state=None)` kabi chaqiruv mavjud qiymatni
        O'CHIRIB YUBORMASLIGI kerak — "berilmagan" va "bo'sh" farqlanadi.
        `current_job_id` ni ataylab tozalash uchun bo'sh matn beriladi.
        """
        cleaned = {key: value for key, value in meta.items() if value is not None}
        if "state" in cleaned:
            cleaned["state"] = WorkerState(cleaned["state"])
        if cleaned.get("current_job_id") == "":
            cleaned["current_job_id"] = None
        return cleaned

    # ==================================================================
    # Ichki yordamchilar — umumiy
    # ==================================================================

    @staticmethod
    def _as_execution_error(error: ExecutionError | BaseException | object) -> ExecutionError:
        """Har qanday xatoni `ExecutionError` ga keltiradi.

        Kutilmagan `Exception` — Durabl'ning O'Z xatosi deb hisoblanadi:
        `INTERNAL_ERROR` + `retryable=True`, ya'ni mijozning job'i bizning
        xatomiz sababli DARHOL DLQ'ga tushmaydi.
        """
        if isinstance(error, ExecutionError):
            return error
        message = str(error) or type(error).__name__
        return ExecutionError(
            message,
            failure_reason=FailureReason.INTERNAL_ERROR,
            retryable=True,
        )

    async def _add_system_log(self, execution: Execution | None, message: str) -> None:
        """`execution_logs` ga `LogStream.SYSTEM` qatorini qo'shadi.

        Nega `ExecutionLog`? `ResultCollector.feed_system()` faqat bajarish
        DAVOMIDA ishlaydi; lease yo'qolgan yoki DLQ qarori qabul qilingan
        paytda collector allaqachon yo'q. Shuning uchun Durabl'ning o'z
        xabarlari to'g'ridan-to'g'ri jadvalga yoziladi va mijoz loglarida
        bajarish chiqishi bilan BIRGA ko'rinadi.

        Log yozilmasligi hech narsani buzmaydi — xato faqat ogohlantirish
        bo'lib qoladi (sessiya `rollback` QILINMAYDI: tranzaksiya egasi
        chaqiruvchi).
        """
        if execution is None:
            return
        try:
            sequence = await self.execution_logs.next_sequence(execution.id)
            await self.execution_logs.bulk_add(
                execution.id,
                execution.job_id,
                [
                    {
                        "stream": LogStream.SYSTEM,
                        "content": message,
                        "sequence": sequence,
                        "timestamp": utcnow(),
                    }
                ],
            )
        except Exception as exc:  # log yozuvi kafolat emas
            logger.warning(
                "tizim log qatori yozilmadi",
                execution_id=str(execution.id),
                error=str(exc),
            )

    async def _enqueue(self, job: Job, *, delay_seconds: float = 0) -> None:
        """Job'ni navbatga qo'yadi; Redis xatosi job'ni YO'QOTMAYDI.

        Job DB'da o'z holatida (`RETRYING` yoki `QUEUED`) qoladi, shuning
        uchun `scheduler`/`reaper` uni qayta topadi. Mijozga xato
        qaytarilmaydi — bu 6-QISM §1 (durability) ning bevosita natijasi.
        """
        try:
            await self.queue.enqueue(job.id, job.priority, delay_seconds=delay_seconds)
        except Exception as exc:  # navbat xatosi job'ni buzmaydi
            logger.error(
                "job navbatga qo'yilmadi — scheduler tiklashi kutiladi",
                job_id=str(job.id),
                status=JobStatus(job.status),
                delay_seconds=delay_seconds,
                error=str(exc),
            )

    async def _publish(self, job: Job) -> None:
        """Job hodisasini Pub/Sub orqali tarqatadi (WebSocket uchun).

        ATAYLAB keng `except`: hodisa — faqat xabardor qilish yo'li. Holat
        PostgreSQL'da saqlangan va mijoz uni polling bilan oladi, shuning
        uchun Pub/Sub muammosi holat o'tishini HECH QACHON buzmasligi kerak.
        """
        try:
            await self.queue.publish_event(job_event_payload(job), user_id=job.user_id)
        except Exception as exc:  # hodisa kafolat emas
            logger.warning("job hodisasi chop etilmadi", job_id=str(job.id), error=str(exc))

    async def _release_concurrency_slot(self, job: Job, previous: JobStatus) -> None:
        """`RUNNING` dan chiqqanda bir vaqtdalik hisoblagichini kamaytiradi.

        `JobService` `RUNNING` ga KIRGANDA `INCR` qiladi, shuning uchun
        chiqishda `DECR` qilish SHU servisning mas'uliyati: aks holda
        hisoblagich "oqib" foydalanuvchini asta-sekin bloklab qo'yardi.
        Hisoblagich 0 dan pastga tushmaydi.
        """
        if previous is not JobStatus.RUNNING:
            return

        key = RedisKeys.concurrency(job.user_id)
        try:
            value = await self.redis.decrby(key, 1)
            if value is not None and int(value) < 0:
                await self.redis.set(key, 0, ex=CONCURRENCY_KEY_TTL_SECONDS)
        except RedisError as exc:
            logger.warning(
                "bir vaqtdalik hisoblagichi kamaytirilmadi",
                user_id=str(job.user_id),
                error=str(exc),
            )

    async def _dispatch(self, job: Job, event: WebhookEvent) -> None:
        """Mos webhook'larga yetkazish yozuvlarini yaratadi (best-effort).

        `WebhookService` DANGASA import qilinadi: shu servis `app.services`
        ichidagi boshqa modullarga import vaqtida bog'lanmasligi kerak, aks
        holda `reliability_service` ni worker yoki scheduler protsessida
        yuklash webhook qatlami tayyor bo'lmaganda yiqilardi.

        `commit` QILINMAYDI va `rollback` ham QILINMAYDI — tranzaksiya egasi
        chaqiruvchi. Yozuvlar uning commit'i bilan birga saqlanadi.

        DIQQAT (structlog): log maydoni `webhook_event` deb nomlangan,
        `event` EMAS. `event` — structlog'ning bound logger metodidagi
        BIRINCHI pozitsion parametr nomi, shuning uchun `logger.info("...",
        event=...)` chaqiruvi `TypeError: got multiple values for argument
        'event'` beradi (sinovda aniqlandi).
        """
        try:
            from app.services.webhook_service import WebhookService
        except ImportError as exc:
            logger.warning(
                "webhook servisi mavjud emas — yetkazish o'tkazib yuborildi",
                webhook_event=event,
                error=str(exc),
            )
            return

        try:
            created = await WebhookService(self.session, self.redis).dispatch(job, event)
        except Exception as exc:  # webhook job'ni buzmaydi
            logger.warning(
                "webhook yetkazish yozuvlari yaratilmadi",
                job_id=str(job.id),
                webhook_event=event,
                error=str(exc),
            )
            return

        if created:
            logger.info(
                "webhook yetkazish yozuvlari yaratildi",
                job_id=str(job.id),
                webhook_event=event,
                deliveries=created,
            )

    async def _notify_dlq_threshold(self, depth: int) -> None:
        """DLQ chuqurligi chegaradan oshdi — operatorga alert (best-effort)."""
        service = self._notification_service()
        if service is None:
            logger.error(
                "DLQ chegarasi oshdi, lekin bildirishnoma servisi mavjud emas",
                depth=depth,
                threshold=settings.DLQ_ALERT_THRESHOLD,
            )
            return
        try:
            await service.notify_dlq_threshold(depth)
        except Exception as exc:  # alert job'ni buzmaydi
            logger.error("DLQ alerti yuborilmadi", depth=depth, error=str(exc))

    async def _notify_worker_down(self, worker_id: str) -> None:
        """Worker qulaganini operatorga bildiradi (best-effort)."""
        service = self._notification_service()
        if service is None:
            return
        try:
            await service.notify_worker_down(worker_id)
        except Exception as exc:  # alert tozalashni buzmaydi
            logger.error("worker alerti yuborilmadi", worker_id=worker_id, error=str(exc))

    @staticmethod
    def _notification_service() -> Any | None:
        """`NotificationService` nusxasi; modul hali yozilmagan bo'lsa `None`.

        Dangasa import — `_dispatch()` dagi bilan ayni sabab: ishonchlilik
        yadrosi bildirishnoma qatlami tayyor bo'lmaganda ham ishlashi kerak.
        """
        try:
            from app.services.notification_service import NotificationService
        except ImportError as exc:
            logger.warning("bildirishnoma servisi mavjud emas", error=str(exc))
            return None
        return NotificationService()


def _as_dt(value: Any) -> datetime | None:
    """ISO matn yoki `datetime` ni `datetime` ga keltiradi (bo'lmasa `None`).

    Reestr Redis'da JSON bo'lib yotadi, shuning uchun `last_heartbeat` matn
    ko'rinishida qaytadi — `seconds_since_heartbeat` ni hisoblash uchun
    qayta `datetime` ga aylantirish kerak.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


__all__ = [
    "CANCEL_NAMESPACE",
    "CANCEL_SIGNAL_GRACE_SECONDS",
    "CAS_MAX_ATTEMPTS",
    "CONCURRENCY_KEY_TTL_SECONDS",
    "DEFAULT_REAP_LIMIT",
    "DLQ_DEFAULT_SORT_COLUMN",
    "DLQ_SORT_COLUMNS",
    "ERROR_TEXT_MAX_CHARS",
    "LEASE_LOST_MESSAGE",
    "LEASE_RELEASE_LUA",
    "LEASE_RENEW_LUA",
    "ReliabilityService",
]
