"""Durabl — `app/services/queue_service.py` birlik testlari.

Navbat — platformaning ishonchlilik yadrosi, shuning uchun test quyidagi
kafolatlarni tekshiradi:

* **Ustuvorlik.** `high` navbatda job bo'lsa worker `low` ni kutmaydi.
* **FIFO.** Yangi job oxiriga (`RPUSH`), worker boshidan oladi (`LEFT`).
  `nack`/`requeue_stale` esa BOSHIGA qaytaradi — ular allaqachon kutgan.
* **Hech narsa yo'qolmaydi.** `dequeue` atomar `LMOVE` bilan job'ni
  `processing` ro'yxatiga ko'chiradi; worker qulasa `requeue_stale()` uni
  AYNI ustuvorlikka qaytaradi.
* **Hech narsa IKKILANMAYDI.** `promote_due()` ikki marta chaqirilsa ayni
  job ikki marta navbatga TUSHMAYDI (aks holda kod ikki marta bajarilardi).

`fake_redis` fixture'i `fakeredis[lua]` bilan ishlaydi, ya'ni Lua skriptlar
HAQIQATAN bajariladi — zaxira (Python) yo'liga tushmaydi.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import pytest
from app.constants import PRIORITY_ORDER, Priority, RedisKeys
from app.services.queue_service import MEMBER_SEPARATOR, QueueService
from app.utils.time_utils import seconds_from_now, utcnow

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from redis.asyncio import Redis

pytestmark = pytest.mark.unit

WORKER = "worker-test-1"


@pytest.fixture
def queue(fake_redis: Redis) -> QueueService:
    """Test klienti bilan navbat servisi."""
    return QueueService(fake_redis)


async def _drain(queue: QueueService, worker: str = WORKER) -> list[str]:
    """Navbat bo'shaguncha barcha job'larni oladi (bloklanmasdan)."""
    collected: list[str] = []
    while True:
        job_id = await queue.dequeue(worker, timeout=0)
        if job_id is None:
            return collected
        collected.append(job_id)


async def _next_event(pubsub: Any) -> dict[str, Any] | None:
    """Pub/Sub'dan keyingi haqiqiy xabarni oladi (obuna tasdiqlarini tashlab)."""
    for _ in range(20):
        message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
        if message is not None:
            return dict(message)
    return None


# ---------------------------------------------------------------------------
# enqueue / dequeue
# ---------------------------------------------------------------------------


async def test_enqueue_va_dequeue(queue: QueueService) -> None:
    """Navbatga qo'yilgan job qaytib olinadi (faqat `job_id`, prefikssiz)."""
    job_id = str(uuid.uuid4())
    await queue.enqueue(job_id, Priority.NORMAL)
    assert await queue.dequeue(WORKER, timeout=0) == job_id


async def test_dequeue_bosh_navbatda_none(queue: QueueService) -> None:
    """Navbat bo'sh bo'lsa `None` qaytadi (bloklanmaydi)."""
    assert await queue.dequeue(WORKER, timeout=0) is None


async def test_dequeue_ustuvorlik_tartibi(queue: QueueService) -> None:
    """KRITIK: `high` -> `normal` -> `low` tartibi hurmat qilinadi."""
    low, normal, high = (str(uuid.uuid4()) for _ in range(3))
    await queue.enqueue(low, Priority.LOW)
    await queue.enqueue(normal, Priority.NORMAL)
    await queue.enqueue(high, Priority.HIGH)

    assert await _drain(queue) == [high, normal, low]


async def test_dequeue_fifo_ayni_ustuvorlikda(queue: QueueService) -> None:
    """Bir xil ustuvorlikda eng ESKI job birinchi bajariladi."""
    job_ids = [str(uuid.uuid4()) for _ in range(5)]
    for job_id in job_ids:
        await queue.enqueue(job_id, Priority.NORMAL)

    assert await _drain(queue) == job_ids


async def test_enqueue_matn_ustuvorlik_bilan(queue: QueueService) -> None:
    """Ustuvorlik matn ko'rinishida ham qabul qilinadi."""
    job_id = str(uuid.uuid4())
    await queue.enqueue(job_id, "high")
    assert await queue.depth_for(Priority.HIGH) == 1


async def test_enqueue_uuid_obyekti_bilan(queue: QueueService) -> None:
    """`UUID` obyekti ham qabul qilinadi (matnga aylantiriladi)."""
    job_id = uuid.uuid4()
    await queue.enqueue(job_id, Priority.NORMAL)
    assert await queue.dequeue(WORKER, timeout=0) == str(job_id)


async def test_azo_formati_ustuvorlikni_saqlaydi(queue: QueueService, fake_redis: Redis) -> None:
    """Navbatda a'zo `"{priority}:{job_id}"` ko'rinishida saqlanadi."""
    job_id = str(uuid.uuid4())
    await queue.enqueue(job_id, Priority.HIGH)
    members = await fake_redis.lrange(RedisKeys.queue(Priority.HIGH), 0, -1)
    assert members == [f"high{MEMBER_SEPARATOR}{job_id}"]


# ---------------------------------------------------------------------------
# processing / ack / nack
# ---------------------------------------------------------------------------


async def test_dequeue_processing_royxatiga_kochiradi(queue: QueueService) -> None:
    """KRITIK: job navbatdan olinib `processing` ro'yxatiga TUSHADI."""
    job_id = str(uuid.uuid4())
    await queue.enqueue(job_id, Priority.NORMAL)
    await queue.dequeue(WORKER, timeout=0)

    assert await queue.processing_jobs(WORKER) == [job_id]


async def test_ack_processingdan_ochiradi(queue: QueueService) -> None:
    """`ack` job'ni `processing` dan olib tashlaydi (yakunlangan)."""
    job_id = str(uuid.uuid4())
    await queue.enqueue(job_id, Priority.NORMAL)
    await queue.dequeue(WORKER, timeout=0)
    await queue.ack(WORKER, job_id)

    assert await queue.processing_jobs(WORKER) == []


async def test_ack_navbatga_qaytarmaydi(queue: QueueService) -> None:
    """`ack` dan keyin job navbatda ham, `processing` da ham yo'q."""
    job_id = str(uuid.uuid4())
    await queue.enqueue(job_id, Priority.NORMAL)
    await queue.dequeue(WORKER, timeout=0)
    await queue.ack(WORKER, job_id)

    assert (await queue.depth())["total"] == 0


async def test_ack_mavjud_bolmagan_job_xato_bermaydi(queue: QueueService) -> None:
    """Yo'q job'ni `ack` qilish xato tashlamaydi (faqat ogohlantirish)."""
    await queue.ack(WORKER, uuid.uuid4())


async def test_nack_navbat_boshiga_qaytaradi(queue: QueueService) -> None:
    """`nack` job'ni navbat BOSHIGA qo'yadi — u yangilardan oldin bajariladi."""
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    await queue.enqueue(first, Priority.NORMAL)
    await queue.dequeue(WORKER, timeout=0)
    await queue.enqueue(second, Priority.NORMAL)

    await queue.nack(WORKER, first, Priority.NORMAL)

    assert await _drain(queue) == [first, second]


async def test_nack_processingdan_ochiradi(queue: QueueService) -> None:
    """`nack` dan keyin job `processing` da qolmaydi (ikkilanmaslik uchun)."""
    job_id = str(uuid.uuid4())
    await queue.enqueue(job_id, Priority.NORMAL)
    await queue.dequeue(WORKER, timeout=0)
    await queue.nack(WORKER, job_id, Priority.NORMAL)

    assert await queue.processing_jobs(WORKER) == []
    assert await queue.depth_for(Priority.NORMAL) == 1


# ---------------------------------------------------------------------------
# requeue_stale
# ---------------------------------------------------------------------------


async def test_requeue_stale_jobni_qaytaradi(queue: QueueService) -> None:
    """Qulagan worker'ning job'i navbatga qaytadi (hech narsa yo'qolmaydi)."""
    job_id = str(uuid.uuid4())
    await queue.enqueue(job_id, Priority.NORMAL)
    await queue.dequeue(WORKER, timeout=0)

    assert await queue.requeue_stale(WORKER) == 1
    assert await queue.processing_jobs(WORKER) == []
    assert await queue.dequeue("boshqa-worker", timeout=0) == job_id


@pytest.mark.parametrize("priority", list(PRIORITY_ORDER))
async def test_requeue_stale_togri_ustuvorlikka_qaytaradi(
    queue: QueueService, priority: Priority
) -> None:
    """KRITIK: job O'Z navbatiga qaytadi — mijozning ustuvorligi yo'qolmaydi."""
    job_id = str(uuid.uuid4())
    await queue.enqueue(job_id, priority)
    await queue.dequeue(WORKER, timeout=0)

    assert await queue.requeue_stale(WORKER) == 1
    assert await queue.depth_for(priority) == 1
    for other in PRIORITY_ORDER:
        if other is not priority:
            assert await queue.depth_for(other) == 0


async def test_requeue_stale_bir_necha_job(queue: QueueService) -> None:
    """Barcha job'lar qaytariladi, soni to'g'ri hisoblanadi."""
    for _ in range(4):
        await queue.enqueue(str(uuid.uuid4()), Priority.NORMAL)
    for _ in range(4):
        await queue.dequeue(WORKER, timeout=0)

    assert await queue.requeue_stale(WORKER) == 4
    assert await queue.depth_for(Priority.NORMAL) == 4


async def test_requeue_stale_bosh_royxat_nol(queue: QueueService) -> None:
    """`processing` bo'sh bo'lsa `0` qaytadi."""
    assert await queue.requeue_stale("yoq-worker") == 0


async def test_requeue_stale_ikki_marta_ikkilantirmaydi(queue: QueueService) -> None:
    """Ikkinchi chaqiruv hech narsa qaytarmaydi (job ikki marta tushmaydi)."""
    await queue.enqueue(str(uuid.uuid4()), Priority.NORMAL)
    await queue.dequeue(WORKER, timeout=0)

    assert await queue.requeue_stale(WORKER) == 1
    assert await queue.requeue_stale(WORKER) == 0
    assert await queue.depth_for(Priority.NORMAL) == 1


# ---------------------------------------------------------------------------
# Kechiktirilgan job'lar
# ---------------------------------------------------------------------------


async def test_enqueue_kechikish_bilan_navbatga_tushmaydi(queue: QueueService) -> None:
    """`delay_seconds > 0` — job darhol navbatga TUSHMAYDI."""
    await queue.enqueue(str(uuid.uuid4()), Priority.NORMAL, delay_seconds=60)
    depths = await queue.depth()
    assert depths["total"] == 0
    assert depths["delayed"] == 1


async def test_enqueue_at_otgan_vaqt_darhol_navbatga(queue: QueueService) -> None:
    """Vaqti o'tib ketgan rejali job darhol navbatga qo'yiladi."""
    job_id = str(uuid.uuid4())
    await queue.enqueue_at(job_id, seconds_from_now(-60), Priority.NORMAL)

    assert await queue.dequeue(WORKER, timeout=0) == job_id


async def test_enqueue_at_kelajak_vaqt_kechiktiriladi(queue: QueueService) -> None:
    """Kelajakdagi vaqt ZSET'ga yoziladi."""
    await queue.enqueue_at(str(uuid.uuid4()), seconds_from_now(300), Priority.HIGH)
    assert (await queue.depth())["delayed"] == 1


async def test_promote_due_vaqti_kelganlarni_kochiradi(queue: QueueService) -> None:
    """Vaqti kelgan job navbatga ko'chadi va `job_id` qaytariladi.

    DIQQAT: `enqueue(delay_seconds=...)` faqat MUSBAT kechikishda ZSET'ga
    yozadi (o'tgan vaqt darhol navbatga tushadi), shuning uchun job kelajakka
    rejalashtiriladi va chegara vaqti `promote_due(now=...)` orqali suriladi.
    """
    job_id = str(uuid.uuid4())
    await queue.enqueue(job_id, Priority.NORMAL, delay_seconds=60)

    assert await queue.promote_due(seconds_from_now(120)) == [job_id]
    assert await queue.dequeue(WORKER, timeout=0) == job_id


async def test_promote_due_ustuvorlikni_saqlaydi(queue: QueueService) -> None:
    """Kechiktirilgan `high` job AYNI `high` navbatiga ko'chadi."""
    job_id = str(uuid.uuid4())
    await queue.enqueue(job_id, Priority.HIGH, delay_seconds=60)

    assert await queue.promote_due(seconds_from_now(120)) == [job_id]
    assert await queue.depth_for(Priority.HIGH) == 1
    assert await queue.depth_for(Priority.NORMAL) == 0


async def test_promote_due_ikki_marta_navbatga_qoymaydi(queue: QueueService) -> None:
    """KRITIK: ikkinchi chaqiruv ayni job'ni QAYTA ko'chirmaydi."""
    job_id = str(uuid.uuid4())
    await queue.enqueue(job_id, Priority.NORMAL, delay_seconds=60)
    threshold = seconds_from_now(120)

    assert await queue.promote_due(threshold) == [job_id]
    assert await queue.promote_due(threshold) == []
    assert await queue.depth_for(Priority.NORMAL) == 1  # faqat BITTA nusxa


async def test_promote_due_vaqti_kelmaganlarga_tegmaydi(queue: QueueService) -> None:
    """Kelajakdagi job ko'chirilmaydi."""
    await queue.enqueue(str(uuid.uuid4()), Priority.NORMAL, delay_seconds=3600)

    assert await queue.promote_due() == []
    assert (await queue.depth())["delayed"] == 1


async def test_promote_due_chegara_vaqti_bilan(queue: QueueService) -> None:
    """`now` argumenti chegara vaqtini belgilaydi."""
    job_id = str(uuid.uuid4())
    await queue.enqueue(job_id, Priority.NORMAL, delay_seconds=100)

    assert await queue.promote_due(utcnow()) == []
    assert await queue.promote_due(seconds_from_now(200)) == [job_id]


async def test_promote_due_limit_hurmat_qiladi(queue: QueueService) -> None:
    """`limit` bir chaqiruvdagi job sonini cheklaydi."""
    for _ in range(5):
        await queue.enqueue(str(uuid.uuid4()), Priority.NORMAL, delay_seconds=60)

    assert len(await queue.promote_due(seconds_from_now(120), limit=2)) == 2
    assert (await queue.depth())["delayed"] == 3


async def test_promote_due_limit_nol_bolsa_bosh_royxat(queue: QueueService) -> None:
    """`limit <= 0` — Redis'ga murojaat ham qilinmaydi."""
    await queue.enqueue(str(uuid.uuid4()), Priority.NORMAL, delay_seconds=60)
    assert await queue.promote_due(seconds_from_now(120), limit=0) == []
    assert (await queue.depth())["delayed"] == 1


async def test_ayni_jobni_ikki_marta_rejalashtirish_bitta_yozuv(queue: QueueService) -> None:
    """`ZADD` score'ni yangilaydi — ZSET'da bitta yozuv qoladi."""
    job_id = str(uuid.uuid4())
    await queue.enqueue(job_id, Priority.NORMAL, delay_seconds=60)
    await queue.enqueue(job_id, Priority.NORMAL, delay_seconds=90)

    assert (await queue.depth())["delayed"] == 1
    assert await queue.promote_due(seconds_from_now(120)) == [job_id]


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


async def test_remove_navbatdan_ochiradi(queue: QueueService) -> None:
    """Bekor qilingan job navbatdan olib tashlanadi."""
    job_id = str(uuid.uuid4())
    await queue.enqueue(job_id, Priority.NORMAL)

    assert await queue.remove(job_id, Priority.NORMAL) is True
    assert await queue.dequeue(WORKER, timeout=0) is None


async def test_remove_ustuvorliksiz_barcha_navbatlarni_tekshiradi(queue: QueueService) -> None:
    """Ustuvorlik berilmasa barcha navbatlar tekshiriladi."""
    job_id = str(uuid.uuid4())
    await queue.enqueue(job_id, Priority.LOW)

    assert await queue.remove(job_id) is True
    assert (await queue.depth())["total"] == 0


async def test_remove_kechiktirilganlardan_ham_ochiradi(queue: QueueService) -> None:
    """Rejalashtirilgan job ham o'chiriladi (ZSET'dan)."""
    job_id = str(uuid.uuid4())
    await queue.enqueue(job_id, Priority.NORMAL, delay_seconds=600)

    assert await queue.remove(job_id, Priority.NORMAL) is True
    assert (await queue.depth())["delayed"] == 0


async def test_remove_mavjud_bolmagan_job_false(queue: QueueService) -> None:
    """Navbatda yo'q job uchun `False`."""
    assert await queue.remove(uuid.uuid4()) is False


# ---------------------------------------------------------------------------
# depth / depth_for / stats
# ---------------------------------------------------------------------------


async def test_depth_barcha_kalitlar(queue: QueueService) -> None:
    """`depth()` ustuvorliklar + `delayed`/`processing`/`total` beradi."""
    depths = await queue.depth()
    assert set(depths) == {"high", "normal", "low", "delayed", "processing", "total"}
    assert all(value == 0 for value in depths.values())


async def test_depth_total_faqat_tayyor_joblar(queue: QueueService) -> None:
    """`total` = `high + normal + low` (delayed va processing KIRMAYDI)."""
    await queue.enqueue(str(uuid.uuid4()), Priority.HIGH)
    await queue.enqueue(str(uuid.uuid4()), Priority.NORMAL)
    await queue.enqueue(str(uuid.uuid4()), Priority.LOW)
    await queue.enqueue(str(uuid.uuid4()), Priority.NORMAL, delay_seconds=600)

    depths = await queue.depth()
    assert depths == {
        "high": 1,
        "normal": 1,
        "low": 1,
        "delayed": 1,
        "processing": 0,
        "total": 3,
    }


async def test_depth_processing_hisoblanadi(queue: QueueService) -> None:
    """Olingan, lekin `ack` qilinmagan job `processing` da ko'rinadi."""
    await queue.enqueue(str(uuid.uuid4()), Priority.NORMAL)
    await queue.dequeue(WORKER, timeout=0)

    depths = await queue.depth()
    assert depths["processing"] == 1
    assert depths["total"] == 0


async def test_depth_for_bitta_navbat(queue: QueueService) -> None:
    """`depth_for` faqat bitta navbat uzunligini beradi."""
    await queue.enqueue(str(uuid.uuid4()), Priority.HIGH)
    await queue.enqueue(str(uuid.uuid4()), Priority.HIGH)

    assert await queue.depth_for(Priority.HIGH) == 2
    assert await queue.depth_for(Priority.LOW) == 0


async def test_stats_navbat_holatini_beradi(queue: QueueService) -> None:
    """Admin paneli uchun statistika to'liq va mos."""
    await queue.enqueue(str(uuid.uuid4()), Priority.NORMAL)
    await queue.enqueue(str(uuid.uuid4()), Priority.NORMAL)
    await queue.dequeue(WORKER, timeout=0)
    await queue.enqueue(str(uuid.uuid4()), Priority.NORMAL, delay_seconds=600)

    stats = await queue.stats()
    assert stats["ready"] == 1
    assert stats["delayed"] == 1
    assert stats["processing"] == 1
    assert stats["processing_by_worker"][WORKER] == 1
    assert stats["workers_with_jobs"] == 1
    assert stats["next_delayed_at"] is not None


async def test_stats_bosh_navbatda(queue: QueueService) -> None:
    """Bo'sh navbatda `next_delayed_at` yo'q."""
    stats = await queue.stats()
    assert stats["ready"] == 0
    assert stats["next_delayed_at"] is None


# ---------------------------------------------------------------------------
# purge
# ---------------------------------------------------------------------------


async def test_purge_hammasini_tozalaydi(queue: QueueService) -> None:
    """`purge` navbat, kechiktirilgan va `processing` ni tozalaydi."""
    await queue.enqueue(str(uuid.uuid4()), Priority.HIGH)
    await queue.enqueue(str(uuid.uuid4()), Priority.NORMAL, delay_seconds=600)
    await queue.enqueue(str(uuid.uuid4()), Priority.LOW)
    await queue.dequeue(WORKER, timeout=0)

    assert await queue.purge() >= 3

    depths = await queue.depth()
    assert depths["total"] == 0
    assert depths["delayed"] == 0


async def test_purge_bosh_navbatda_nol(queue: QueueService) -> None:
    """Bo'sh navbatni tozalash `0` qaytaradi."""
    assert await queue.purge() == 0


# ---------------------------------------------------------------------------
# publish_event
# ---------------------------------------------------------------------------


async def test_publish_event_umumiy_kanalga(queue: QueueService, fake_redis: Redis) -> None:
    """Hodisa umumiy kanalga tushadi (admin monitoringi uchun)."""
    pubsub = fake_redis.pubsub()
    await pubsub.subscribe(RedisKeys.EVENTS_JOBS)
    try:
        await queue.publish_event({"job_id": "j1", "status": "success"})
        message = await _next_event(pubsub)
    finally:
        await pubsub.unsubscribe(RedisKeys.EVENTS_JOBS)
        await pubsub.close()

    assert message is not None
    assert '"job_id":"j1"' in str(message["data"])


async def test_publish_event_foydalanuvchi_kanaliga(queue: QueueService, fake_redis: Redis) -> None:
    """Hodisa tanasidagi `user_id` dan foydalanuvchi kanali aniqlanadi."""
    user_id = str(uuid.uuid4())
    pubsub = fake_redis.pubsub()
    await pubsub.subscribe(RedisKeys.events_user(user_id))
    try:
        await queue.publish_event({"job_id": "j1", "user_id": user_id, "status": "running"})
        message = await _next_event(pubsub)
    finally:
        await pubsub.unsubscribe(RedisKeys.events_user(user_id))
        await pubsub.close()

    assert message is not None
    assert user_id in str(message["data"])


async def test_publish_event_ochiq_user_id_ustun(queue: QueueService, fake_redis: Redis) -> None:
    """Ochiq berilgan `user_id` hodisa tanasidagi qiymatdan ustun turadi."""
    target = str(uuid.uuid4())
    pubsub = fake_redis.pubsub()
    await pubsub.subscribe(RedisKeys.events_user(target))
    try:
        await queue.publish_event({"user_id": "boshqa"}, user_id=target)
        message = await _next_event(pubsub)
    finally:
        await pubsub.unsubscribe(RedisKeys.events_user(target))
        await pubsub.close()

    assert message is not None


async def test_publish_event_user_id_yoq_bolsa_xato_bermaydi(queue: QueueService) -> None:
    """Foydalanuvchi aniqlanmasa faqat umumiy kanalga ketadi — xato yo'q."""
    await queue.publish_event({"type": "system", "message": "test"})
