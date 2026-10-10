"""Durabl — uchdan-uchga (E2E) testlar uchun QO'SHIMCHA fixture'lar.

`tests/conftest.py` infratuzilmani (engine, fakeredis, HTTP mijoz,
foydalanuvchilar) beradi. Shu fayl esa faqat E2E'ga xos narsalarni qo'shadi:
HAQIQIY worker nusxalari va vaqtni "o'tkazib yuborish" yordamchilari.

## Nega `process_one(timeout=0)`

`Worker.run()` cheksiz halqa — testda ishga tushirish mumkin emas.
`process_one()` esa bitta job'ni to'liq (lease, heartbeat, bajarish, ack)
bajaradigan mustaqil kirish nuqtasi. `timeout=0` uzatilishi SHART:
`QueueService.dequeue()` oxirgi navbatni `BLMOVE` bilan kutadi va nol
kutish vaqtida bloklanmaydigan `LMOVE` ga o'tadi — aks holda bo'sh
navbatda test `WORKER_POLL_TIMEOUT_SECONDS` soniya qotib turardi.

## Nega `SchedulerWorker.tick()` to'g'ridan-to'g'ri chaqiriladi

`SchedulerWorker` `exclusive = True`, ya'ni `run()` har siklda taqsimlangan
lock oladi. `tick()` esa lock'dan mustaqil — uni chaqirish bitta
rejalashtirish siklini bajaradi: `promote_due` + `RETRYING -> QUEUED`
DB o'tishi, lease reaper, yo'qolgan job'larni tiklash, cron va metrikalar.
E2E testlar aynan shu to'rt qadamni tekshiradi.

## Nega vaqtni "o'tkazish" ORQAGA surish bilan amalga oshiriladi

Tizim vaqtini o'zgartirish mumkin emas (`utcnow()` butun kodda ishlatiladi
va uni global patch qilish worker ichidagi `asyncio` taymerlarini ham
buzardi). Shuning uchun `advance_time()` TESKARI yo'ldan boradi:
kechiktirilgan ZSET'dagi score'larni va DB'dagi vaqt ustunlarini belgilangan
soniyaga ORQAGA suradi. Natija bir xil — "vaqti kelgan" bo'lib qoladi.

## Nega `fetch_job()` har safar YANGI sessiya ochadi

`db_session` fixture'i uzoq yashaydi va uning identifikatsiya xaritasidagi
(identity map) obyekt worker BOSHQA sessiyada o'zgartirgan holatni
ko'rmaydi. Qisqa umrli sessiya esa har doim DB'dagi haqiqiy qatorni oladi.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Final

import pytest
from app.config import settings
from app.constants import ExecutionStatus, JobStatus, RedisKeys
from app.database import get_sessionmaker
from app.models.execution import Execution
from app.models.job import Job
from app.utils.time_utils import ensure_utc, utcnow
from app.workers.scheduler import SchedulerWorker
from app.workers.webhook_sender import WebhookSender
from app.workers.worker import Worker
from sqlalchemy import func, select, update

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from collections.abc import Awaitable, Callable, Iterable

    from redis.asyncio import Redis

#: `run_until()` ning standart sikl chegarasi. Bitta job uchun 1-2 sikl
#: yetadi, retry zanjiri uchun ko'proq. Chegara MAJBURIY: kutilgan holat
#: hech qachon kelmasa test cheksiz aylanib qolardi.
MAX_CYCLES: Final[int] = 60

#: `worker` va `worker_b` fixture'larining identifikatorlari.
#: Qat'iy nom ataylab: `RedisKeys.processing(worker_id)` kaliti testda
#: ochiq tekshirilishi mumkin bo'lishi kerak.
WORKER_A_ID: Final[str] = "e2e-worker-a"
WORKER_B_ID: Final[str] = "e2e-worker-b"

#: `crash_worker()` lease muddatini shuncha soniya ORTGA suradi.
#: `LEASE_TTL_SECONDS` (15) dan ancha katta bo'lishi kerak.
CRASH_LEASE_SHIFT_SECONDS: Final[int] = 300


# ---------------------------------------------------------------------------
# Worker nusxalari
# ---------------------------------------------------------------------------


@pytest.fixture
def worker(test_engine: Any, fake_redis: Redis) -> Worker:
    """Tayyor `Worker` nusxasi (`process_one()` uchun).

    `test_engine` va `fake_redis` ataylab talab qilinadi: worker ularning
    GLOBAL nusxalari bilan ishlaydi (`session_scope()` va `get_redis()`),
    shuning uchun fixture'lar worker'dan OLDIN qurilgan bo'lishi kerak.
    """
    return Worker(WORKER_A_ID)


@pytest.fixture
def worker_b(test_engine: Any, fake_redis: Redis) -> Worker:
    """Ikkinchi worker — lease poygasi va tiklanish testlari uchun."""
    return Worker(WORKER_B_ID)


@pytest.fixture
def scheduler(test_engine: Any, fake_redis: Redis) -> SchedulerWorker:
    """Tayyor `SchedulerWorker` nusxasi (`tick()` uchun)."""
    return SchedulerWorker()


@pytest.fixture
def webhook_sender(test_engine: Any, fake_redis: Redis) -> WebhookSender:
    """Tayyor `WebhookSender` nusxasi (`tick()` uchun)."""
    return WebhookSender()


# ---------------------------------------------------------------------------
# DB'dan o'qish yordamchilari
# ---------------------------------------------------------------------------


@pytest.fixture
def fetch_job(test_engine: Any) -> Callable[..., Awaitable[Job]]:
    """Job'ni DB'dan QAYTA o'qiydi (worker yozgan holatni ko'rish uchun).

    `expire_on_commit=False` tufayli qaytarilgan obyekt sessiya yopilgandan
    keyin ham o'qiladi — bog'liq ma'lumotlardan tashqari (ular `lazy="raise"`,
    buning uchun `fetch_executions()` bor).
    """

    async def fetch(job_id: uuid.UUID | str) -> Job:
        factory = get_sessionmaker()
        async with factory() as session:
            job = await session.get(Job, _as_uuid(job_id))
            assert job is not None, f"job {job_id} DB'da topilmadi"
            return job

    return fetch


@pytest.fixture
def fetch_executions(test_engine: Any) -> Callable[..., Awaitable[list[Execution]]]:
    """Job'ning barcha urinishlarini `attempt_number` tartibida o'qiydi."""

    async def fetch(job_id: uuid.UUID | str) -> list[Execution]:
        factory = get_sessionmaker()
        async with factory() as session:
            result = await session.execute(
                select(Execution)
                .where(Execution.job_id == _as_uuid(job_id))
                .order_by(Execution.attempt_number)
            )
            return list(result.scalars().all())

    return fetch


@pytest.fixture
def count_jobs(test_engine: Any) -> Callable[..., Awaitable[int]]:
    """`jobs` jadvalidagi qatorlar soni (ixtiyoriy ravishda egasi bo'yicha).

    Idempotentlik testlarining ASOSIY tasdig'i: javob kodi qanday bo'lsa
    ham, jadvalda BITTA qator bo'lishi kerak. Shuning uchun hisob API orqali
    emas, bevosita SQL bilan olinadi — ro'yxat endpointi sahifalash yoki
    filtr tufayli qatorni yashirib qo'yishi mumkin emas.
    """

    async def count(user_id: uuid.UUID | str | None = None) -> int:
        stmt = select(func.count()).select_from(Job)
        if user_id is not None:
            stmt = stmt.where(Job.user_id == _as_uuid(user_id))
        factory = get_sessionmaker()
        async with factory() as session:
            return int(await session.scalar(stmt) or 0)

    return count


# ---------------------------------------------------------------------------
# Sikl haydovchisi
# ---------------------------------------------------------------------------


@pytest.fixture
def run_until(
    worker: Worker,
    scheduler: SchedulerWorker,
    fetch_job: Callable[..., Awaitable[Job]],
    advance_time: Callable[..., Awaitable[None]],
) -> Callable[..., Awaitable[Job]]:
    """Job berilgan holatlardan biriga o'tguncha sikl haydaydi.

    Har siklda UCH qadam bajariladi:

    1. `worker.process_one(timeout=0)` — navbatda job bo'lsa oladi va
       to'liq bajaradi;
    2. `advance_seconds > 0` bo'lsa — SHU job'ning kechiktirilgan muddati
       orqaga suriladi (retry backoff'ini kutmaslik uchun);
    3. `scheduler.tick()` — `RETRYING -> QUEUED` o'tishini, vaqti kelgan
       kechiktirilgan job'larni va yo'qolgan lease'larni qayta ishlaydi.

    Tartib ataylab shunday: avval navbatdagi ish bajariladi, keyin
    scheduler keyingi urinishni tayyorlaydi. Teskari tartibda retry
    zanjirining har bosqichi uchun bitta qo'shimcha sikl kerak bo'lardi.

    Chaqirish shakli:

        job = await run_until(job_id, JobStatus.SUCCESS)
        job = await run_until(job_id, JobStatus.DEAD_LETTER, advance_seconds=60)

    Args:
        job_id: Kuzatilayotgan job.
        targets: Kutilayotgan holatlar (bittasi yetarli).
        max_cycles: Sikl chegarasi — holat kelmasa test yiqiladi.
        drive_scheduler: `False` — faqat worker ishlaydi (scheduler
            ARALASHMASLIGI kerak bo'lgan testlar uchun).
        advance_seconds: Har siklda "o'tkaziladigan" vaqt. `0` — vaqt
            surilmaydi (backoff haqiqatan kutiladi, ya'ni retry zanjiri
            oldinga siljimaydi).

    Returns:
        Kutilgan holatga kelgan job.

    Raises:
        AssertionError: Chegara ichida holat kelmadi.
    """

    async def run(
        job_id: uuid.UUID | str,
        *targets: JobStatus,
        max_cycles: int = MAX_CYCLES,
        drive_scheduler: bool = True,
        advance_seconds: float = 0,
    ) -> Job:
        wanted = set(targets)
        assert wanted, "kamida bitta maqsad holat ko'rsatilishi kerak"

        job = await fetch_job(job_id)
        if JobStatus(job.status) in wanted:
            return job

        for _ in range(max_cycles):
            await worker.process_one(timeout=0)
            if advance_seconds > 0:
                await advance_time(advance_seconds, job_ids=[job_id])
            if drive_scheduler:
                await scheduler.tick()
            job = await fetch_job(job_id)
            if JobStatus(job.status) in wanted:
                return job

        expected = sorted(status.value for status in wanted)

        # ## Nega sabab BIRINCHI QATORDA
        #
        # pytest ning qisqa xulosasi (`FAILED ...`) xato xabarining
        # faqat BIRINCHI qatorini ko'rsatadi, CI esa aynan shu qatorni
        # `::error::` annotatsiyasi qilib chiqaradi (log'ni o'qish uchun
        # admin huquqi kerak). Ya'ni tafsilot ikkinchi qatorga tushsa,
        # CI'da KO'RINMAYDI.
        #
        # Buning narxini amalda ko'rdik: `test_node_runtime_executes`
        # Linux'da yiqilganda xabar faqat "holatga kelmadi" derdi va
        # sabab bir necha marta ko'r izlandi. Shuning uchun eng kerakli
        # maydonlar bitta qatorga jipslashtirilgan, to'liq matn esa
        # keyingi qatorlarda qoladi.
        reason = job.failure_reason.value if job.failure_reason else None
        empty = "(bo'sh)"
        stderr_full = (job.stderr or "").strip().replace("\n", " | ")
        stdout_full = (job.stdout or "").strip().replace("\n", " | ")
        headline = (
            f"job {job_id} {max_cycles} siklda {expected} holatiga kelmadi "
            f"[holat={JobStatus(job.status).value} retry={job.retry_count} "
            f"exit={job.exit_code} sabab={reason} "
            f"stderr={stderr_full[:200] or empty}]"
        )
        raise AssertionError(
            f"{headline}\n"
            f"  error : {job.error or empty}\n"
            f"  stderr: {stderr_full[:2000] or empty}\n"
            f"  stdout: {stdout_full[:500] or empty}"
        )

    return run


# ---------------------------------------------------------------------------
# Vaqt bilan o'ynash
# ---------------------------------------------------------------------------


@pytest.fixture
def advance_time(fake_redis: Redis, test_engine: Any) -> Callable[..., Awaitable[None]]:
    """ "Vaqt o'tdi" ta'sirini beradi — muddatlarni belgilangan qadar orqaga suradi.

    Nima suriladi:

    * `RedisKeys.DELAYED` ZSET a'zolarining score'i — `promote_due()` ularni
      "vaqti keldi" deb ko'radi (backoff kutayotgan va rejalashtirilgan
      job'lar shu yerda turadi);
    * `jobs.scheduled_at` — rejalashtirilgan job'ning o'z vaqti ham o'tgan
      bo'lishi kerak;
    * `jobs.queued_at` — `SchedulerWorker` "yo'qolgan job" ni faqat
      `LOST_JOB_GRACE_SECONDS` dan eski bo'lsa qaytaradi, ya'ni Redis
      qulashini sinash uchun shu ustun ham surilishi SHART;
    * `executions.lease_expires_at` — lease reaper uchun.

    `created_at` ATAYLAB tegilmaydi: u analitika oynalarining asosi va uni
    surish `/analytics/*` javoblarini bilib bo'lmaydigan holga keltirardi.

    Args:
        seconds: Qancha vaqt "o'tdi".
        job_ids: Faqat shu job'larga qo'llanadi (ZSET a'zosi ham `job_id`
            bo'yicha filtrlanadi). `None` — barcha job'lar va urinishlar.
    """

    async def advance(
        seconds: float,
        *,
        job_ids: Iterable[uuid.UUID | str] | None = None,
    ) -> None:
        shift = float(seconds)
        wanted = None if job_ids is None else {str(_as_uuid(item)) for item in job_ids}

        # --- Redis: kechiktirilgan navbat ----------------------------
        #
        # A'zo shakli `"<priority>:<job_id>"` (`QueueService._member`),
        # shuning uchun filtr uchun oxirgi bo'lak ajratiladi.
        members = await fake_redis.zrange(RedisKeys.DELAYED, 0, -1, withscores=True)
        shifted = {
            str(member): float(score) - shift
            for member, score in members
            if wanted is None or str(member).rpartition(":")[2] in wanted
        }
        if shifted:
            await fake_redis.zadd(RedisKeys.DELAYED, shifted)

        # --- DB: rejalashtirilgan vaqt va lease muddati --------------
        #
        # Ayirish SQL'da emas, PYTHON'da bajariladi: SQLite'da `DATETIME`
        # ustunidan `timedelta` ayirish qiymatni matn bo'lmagan shaklga
        # aylantiradi va keyingi o'qishda `fromisoformat` yiqiladi.
        delta = timedelta(seconds=shift)

        job_stmt = select(Job)
        execution_stmt = select(Execution).where(Execution.lease_expires_at.is_not(None))
        if wanted is not None:
            ids = [_as_uuid(item) for item in wanted]
            job_stmt = job_stmt.where(Job.id.in_(ids))
            execution_stmt = execution_stmt.where(Execution.job_id.in_(ids))

        factory = get_sessionmaker()
        async with factory() as session:
            for job in (await session.execute(job_stmt)).scalars():
                if job.scheduled_at is not None:
                    job.scheduled_at = ensure_utc(job.scheduled_at) - delta
                if job.queued_at is not None:
                    job.queued_at = ensure_utc(job.queued_at) - delta
            for execution in (await session.execute(execution_stmt)).scalars():
                execution.lease_expires_at = ensure_utc(execution.lease_expires_at) - delta
            await session.commit()

    return advance


@pytest.fixture
def crash_worker(fake_redis: Redis, test_engine: Any) -> Callable[..., Awaitable[None]]:
    """Worker'ning "qulashini" taqlid qiladi (lease yo'qoladi).

    Haqiqiy qulashda (OOM, `SIGKILL`, server o'chishi) ikki narsa yuz
    beradi: Redis'dagi lease kaliti TTL bo'yicha o'chadi va DB'dagi
    `lease_expires_at` o'tmishda qoladi. Shu yordamchi ayni holatni
    QO'LDA yasaydi — TTL ni kutmasdan.

    `RUNNING` urinish DB'da tegilmagan holda qoladi: aynan shuni
    `reap_expired_leases()` topib `LOST` deb yopishi kerak.

    Raises:
        AssertionError: Job uchun `RUNNING` urinish yozuvi yo'q (ya'ni
            test "qulash" ni emas, boshqa holatni tekshirgan bo'lardi).
    """

    async def crash(job_id: uuid.UUID | str) -> None:
        job_uuid = _as_uuid(job_id)
        await fake_redis.delete(RedisKeys.lease(job_id))

        past = utcnow() - timedelta(seconds=CRASH_LEASE_SHIFT_SECONDS)
        factory = get_sessionmaker()
        async with factory() as session:
            await session.execute(
                update(Execution)
                .where(
                    Execution.job_id == job_uuid,
                    Execution.status == ExecutionStatus.RUNNING,
                )
                .values(lease_expires_at=past)
            )
            await session.commit()
            found = await session.execute(
                select(Execution.id).where(
                    Execution.job_id == job_uuid,
                    Execution.status == ExecutionStatus.RUNNING,
                    Execution.lease_expires_at == past,
                )
            )
            assert found.scalars().first() is not None, (
                f"job {job_id} uchun `RUNNING` urinish topilmadi — "
                "qulashni taqlid qilish uchun worker uni olgan bo'lishi kerak"
            )

    return crash


# ---------------------------------------------------------------------------
# Webhook muhiti
# ---------------------------------------------------------------------------


@pytest.fixture
def allow_remote_webhooks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Webhook URL tekshiruvidan DNS/SSRF qadamini olib tashlaydi.

    `validate_webhook_url()` standart holatda hostni DNS bilan yechib,
    ichki IP'ga ishora qilmasligini tekshiradi. Testda bu keraksiz: `respx`
    so'rovni baribir tutib qoladi (haqiqiy ulanish bo'lmaydi), DNS so'rovi
    esa tarmoqsiz muhitda sekin. Tekshiruvning O'ZI birlik testlarida
    sinaladi, shuning uchun bu yerda bayroq o'chiriladi.
    """
    monkeypatch.setattr(settings, "WEBHOOK_BLOCK_PRIVATE_IPS", False)


# ---------------------------------------------------------------------------
# Ichki yordamchilar
# ---------------------------------------------------------------------------


def _as_uuid(value: uuid.UUID | str) -> uuid.UUID:
    """Matn ko'rinishidagi identifikatorni `UUID` ga aylantiradi."""
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


__all__ = [
    "CRASH_LEASE_SHIFT_SECONDS",
    "MAX_CYCLES",
    "WORKER_A_ID",
    "WORKER_B_ID",
    "advance_time",
    "allow_remote_webhooks",
    "count_jobs",
    "crash_worker",
    "fetch_executions",
    "fetch_job",
    "run_until",
    "scheduler",
    "webhook_sender",
    "worker",
    "worker_b",
]
