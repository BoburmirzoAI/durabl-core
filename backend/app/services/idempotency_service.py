"""Durabl — idempotentlik servisi ("bir xil job ikki marta bajarilmaydi").

Muammo. Mijoz `POST /api/v1/jobs` yuboradi, server job yaratadi, lekin javob
yo'lda yo'qoladi (tarmoq uzildi, timeout). Mijoz "yuborilmadi" deb o'ylab
so'rovni QAYTA yuboradi. Idempotentlik bo'lmasa — bitta to'lov ikki marta
o'tadi, bitta xat ikki marta ketadi.

Yechim. Mijoz `Idempotency-Key` header'i bilan yuboradi. Birinchi so'rov
kalitni Redis'da **band qiladi**, ikkinchisi esa band qilingan yozuvni
ko'radi va yangi job YARATMAYDI — eski job qaytariladi.

Band qilish `SET key value NX EX ttl` bilan bajariladi. `NX` — "faqat kalit
yo'q bo'lsa yoz" — Redis darajasida ATOMAR, shuning uchun ikki so'rov AYNI
millisekundda kelsa ham faqat bittasi `True` oladi. Ikki qadamga ajratilgan
(`EXISTS` keyin `SET`) tekshiruv bu kafolatni bermaydi.

**Barmoq izi (fingerprint).** Bir xil kalit bilan BOSHQA so'rov tanasi kelsa
bu mijoz xatosi: kalit qayta ishlatilgan. Bunda eski job'ni qaytarish xato
bo'lardi (mijoz boshqa kod yuborgan, lekin boshqa natija oladi), shuning
uchun `IdempotencyConflictError` tashlanadi. Iz `serializers.fingerprint`
bilan hisoblanadi — kalitlar tartiblanadi, shuning uchun maydonlar tartibi
o'zgarsa ham iz O'ZGARMAYDI.

**Fail-closed.** Cache xatosi ilovani buzmaydi, lekin idempotentlik xatosi
BUZADI: Redis javob bermasa biz takrorlanishni aniqlay olmaymiz, shuning
uchun so'rovni rad etish (503) yagona xavfsiz yo'l. Aks holda Redis uzilgan
paytda har bir takroriy so'rov yangi job yaratib ketardi.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal
from uuid import UUID

from redis.exceptions import RedisError

from app.config import settings
from app.constants import RedisKeys
from app.exceptions import (
    IdempotencyConflictError,
    IdempotencyInProgressError,
    InfrastructureError,
    ValidationError,
)
from app.logging_config import get_logger
from app.redis_client import get_redis
from app.utils.serializers import dump_json, load_json
from app.utils.serializers import fingerprint as payload_fingerprint

if TYPE_CHECKING:
    from collections.abc import Mapping

    from redis.asyncio import Redis

logger = get_logger(__name__)

#: Yozuv holati: band qilingan (job hali yaratilmagan) yoki yakunlangan.
IdempotencyState = Literal["in_progress", "completed"]

STATE_IN_PROGRESS: Final[IdempotencyState] = "in_progress"
STATE_COMPLETED: Final[IdempotencyState] = "completed"

#: `reserve()` ichidagi poyga (race) uchun maksimal urinish soni.
#: Yozuv `SET NX` muvaffaqiyatsiz bo'lgandan keyin, lekin `GET` dan OLDIN
#: TTL bo'yicha o'chib ketishi mumkin — bunda qayta band qilib ko'riladi.
MAX_RESERVE_ATTEMPTS: Final = 3


@dataclass(slots=True)
class IdempotencyRecord:
    """Redis'da saqlanadigan idempotentlik yozuvi.

    Attributes:
        state: `in_progress` — kalit band qilindi, job hali yaratilmagan;
            `completed` — job yaratildi, `job_id` to'ldirilgan.
        job_id: Yaratilgan job identifikatori (`in_progress` da `None`).
        fingerprint: So'rov tanasining barqaror SHA-256 izi.
    """

    state: IdempotencyState
    job_id: str | None
    fingerprint: str

    @property
    def is_completed(self) -> bool:
        """Job allaqachon yaratilganmi?"""
        return self.state == STATE_COMPLETED

    def to_dict(self) -> dict[str, Any]:
        """Redis'ga yoziladigan JSON lug'ati."""
        return {"state": self.state, "job_id": self.job_id, "fingerprint": self.fingerprint}

    @classmethod
    def parse(cls, raw: str | bytes | None) -> IdempotencyRecord | None:
        """Redis'dagi xom JSON'dan yozuv yasaydi; yaroqsiz bo'lsa `None`.

        Yaroqsiz yozuv (qo'lda o'zgartirilgan, eski format) ilovani
        yiqitmasligi kerak — `None` qaytariladi va chaqiruvchi kalitni
        bo'sh deb hisoblaydi.
        """
        if not raw:
            return None
        try:
            decoded = load_json(raw)
        except ValidationError:
            logger.warning("Idempotency yozuvi yaroqsiz JSON", raw=str(raw)[:200])
            return None
        if not isinstance(decoded, dict):
            return None

        state = decoded.get("state")
        if state not in (STATE_IN_PROGRESS, STATE_COMPLETED):
            return None
        job_id = decoded.get("job_id")
        return cls(
            state=state,
            job_id=None if job_id is None else str(job_id),
            fingerprint=str(decoded.get("fingerprint") or ""),
        )


class IdempotencyService:
    """`Idempotency-Key` bo'yicha takrorlanishni to'xtatuvchi servis.

    Konstruktor Redis klientini oladi (berilmasa global klient). Servis
    DB'ga tegmaydi va `commit()` qilmaydi — `JobService` uni tranzaksiya
    ichida chaqiradi.

    Odatiy ishlatilishi (`JobService.submit`):

        record = await idem.reserve(user.id, key, idem.fingerprint(body))
        if record is not None:               # tayyor job bor
            return await jobs.get(record.job_id), False
        try:
            job = await self._create(...)    # yangi job
        except Exception:
            await idem.release(user.id, key)  # MAJBURIY — aks holda mijoz
            raise                             # 24 soat qulflanib qoladi
        await idem.commit(user.id, key, job.id)
    """

    def __init__(self, redis: Redis | None = None) -> None:
        self.redis: Redis = redis or get_redis()

    # ------------------------------------------------------------------
    # Barmoq izi
    # ------------------------------------------------------------------

    @staticmethod
    def fingerprint(payload: Mapping[str, Any]) -> str:
        """So'rov tanasining barqaror SHA-256 izi (hex, 64 belgi).

        `serializers.fingerprint` ga delegatsiya qiladi: kalitlar
        tartiblanadi, shuning uchun bir xil mazmunli lug'at maydonlar
        tartibidan qat'i nazar HAR DOIM bir xil iz beradi.

        Raises:
            ValidationError: Lug'at JSON'ga aylanmadi.
        """
        return payload_fingerprint(payload)

    # ------------------------------------------------------------------
    # Ichki yordamchilar
    # ------------------------------------------------------------------

    @staticmethod
    def _key(user_id: str | UUID, key: str) -> str:
        """Redis kaliti — foydalanuvchi bo'yicha ajratilgan.

        Kalit `user_id` bilan birga yasaladi: bir mijozning kaliti
        boshqasining job'ini qaytarib yubormasligi kerak.
        """
        return RedisKeys.idempotency(user_id, key)

    @staticmethod
    def _unavailable(operation: str, exc: RedisError) -> InfrastructureError:
        """Redis xatosini domen xatosiga o'raydi (fail-closed, HTTP 503)."""
        logger.error(
            "Idempotency saqlovi javob bermadi — so'rov rad etildi",
            operation=operation,
            error=str(exc),
        )
        return InfrastructureError(
            "Idempotentlik saqlovi (Redis) javob bermadi — "
            "so'rovni takrorlash xavfsiz emas, birozdan keyin qayta urinib ko'ring"
        )

    async def _read(self, redis_key: str, *, operation: str) -> IdempotencyRecord | None:
        """Yozuvni o'qiydi (yo'q yoki yaroqsiz bo'lsa `None`)."""
        try:
            raw = await self.redis.get(redis_key)
        except RedisError as exc:
            raise self._unavailable(operation, exc) from exc
        return IdempotencyRecord.parse(raw)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def reserve(
        self,
        user_id: str | UUID,
        key: str,
        fingerprint: str,
    ) -> IdempotencyRecord | None:
        """Kalitni band qiladi yoki mavjud yozuvni qaytaradi.

        `SET ... NX EX` atomar band qilishi tufayli bir vaqtda kelgan ikki
        so'rovdan faqat BITTASI `None` oladi.

        Args:
            user_id: Kalit egasi.
            key: Mijoz yuborgan `Idempotency-Key`.
            fingerprint: So'rov tanasining izi (`fingerprint()` natijasi).

        Returns:
            `None` — kalit band qilindi, YANGI job yaratish mumkin.
            `IdempotencyRecord` — job allaqachon yaratilgan (`state`
            `completed`), chaqiruvchi mavjud job'ni qaytarishi kerak.

        Raises:
            IdempotencyConflictError: Ayni kalit BOSHQA so'rov tanasi bilan
                ishlatilgan (mijoz kalitni qayta ishlatib yubordi).
            IdempotencyInProgressError: Ayni kalit bilan so'rov HOZIR qayta
                ishlanmoqda (birinchi so'rov hali `commit` qilmagan).
            InfrastructureError: Redis javob bermadi (fail-closed).
        """
        redis_key = self._key(user_id, key)
        reservation = IdempotencyRecord(
            state=STATE_IN_PROGRESS, job_id=None, fingerprint=fingerprint
        )
        payload = dump_json(reservation.to_dict())

        for _ in range(MAX_RESERVE_ATTEMPTS):
            try:
                acquired = await self.redis.set(
                    redis_key,
                    payload,
                    nx=True,
                    ex=settings.IDEMPOTENCY_TTL_SECONDS,
                )
            except RedisError as exc:
                raise self._unavailable("reserve", exc) from exc

            if acquired:
                logger.debug(
                    "Idempotency kaliti band qilindi", user_id=str(user_id), idempotency_key=key
                )
                return None

            existing = await self._read(redis_key, operation="reserve")
            if existing is None:
                # Kalit `SET NX` dan keyin TTL bo'yicha o'chdi (yoki yozuv
                # yaroqsiz) — qayta band qilib ko'ramiz.
                continue

            if existing.fingerprint and existing.fingerprint != fingerprint:
                logger.warning(
                    "Idempotency kaliti boshqa so'rov tanasi bilan ishlatilgan",
                    user_id=str(user_id),
                    idempotency_key=key,
                )
                raise IdempotencyConflictError(key)

            if existing.state == STATE_IN_PROGRESS:
                logger.info(
                    "Idempotency kaliti bilan so'rov hozir bajarilmoqda",
                    user_id=str(user_id),
                    idempotency_key=key,
                )
                raise IdempotencyInProgressError()

            logger.info(
                "Idempotency: mavjud job qaytariladi",
                user_id=str(user_id),
                idempotency_key=key,
                job_id=existing.job_id,
            )
            return existing

        # Bu yerga faqat kalit har urinishda TTL bo'yicha o'chib ketsa
        # yetib kelamiz — amalda deyarli imkonsiz, lekin jim o'tib ketish
        # takroriy job yaratilishiga olib kelardi.
        raise self._unavailable(
            "reserve", RedisError("kalit holati barqarorlashmadi (TTL poygasi)")
        )

    async def commit(self, user_id: str | UUID, key: str, job_id: str | UUID) -> None:
        """Band qilingan kalitni `completed` holatiga o'tkazadi.

        TTL SAQLANADI (`KEEPTTL`): kalit `reserve` paytida qo'yilgan 24 soat
        davomida yashaydi va shu vaqt ichida takroriy so'rov ayni shu job'ni
        oladi. TTL yangilansa kalit abadiy yashab ketishi mumkin edi.

        Yozuv topilmasa (TTL tugadi) yangisi yoziladi — mijozning takroriy
        so'rovi baribir to'g'ri job'ni olishi kerak.

        Bu metod **ichki** emas — lekin faqat Redis bilan ishlaydi,
        shuning uchun `commit()` (DB tranzaksiyasi) qilmaydi. Chaqiruvchi
        uni DB commit'idan KEYIN chaqirishi tavsiya etiladi.

        Raises:
            InfrastructureError: Redis javob bermadi.
        """
        redis_key = self._key(user_id, key)
        existing = await self._read(redis_key, operation="commit")
        record = IdempotencyRecord(
            state=STATE_COMPLETED,
            job_id=str(job_id),
            fingerprint=existing.fingerprint if existing else "",
        )
        payload = dump_json(record.to_dict())

        try:
            if existing is not None:
                await self.redis.set(redis_key, payload, keepttl=True)
            else:
                await self.redis.set(redis_key, payload, ex=settings.IDEMPOTENCY_TTL_SECONDS)
        except RedisError as exc:
            raise self._unavailable("commit", exc) from exc

        logger.debug(
            "Idempotency yozuvi yakunlandi",
            user_id=str(user_id),
            idempotency_key=key,
            job_id=str(job_id),
        )

    async def release(self, user_id: str | UUID, key: str) -> None:
        """Band qilishni bekor qiladi (kalitni o'chiradi).

        **Job yaratish muvaffaqiyatsiz bo'lsa MAJBURIY chaqiriladi.** Aks
        holda kalit `in_progress` holatida 24 soat qolib ketadi va mijoz shu
        kalit bilan boshqa hech narsa yubora olmaydi
        (`IdempotencyInProgressError` oladi) — job esa yaratilmagan.

        Raises:
            InfrastructureError: Redis javob bermadi.
        """
        try:
            deleted = int(await self.redis.delete(self._key(user_id, key)) or 0)
        except RedisError as exc:
            raise self._unavailable("release", exc) from exc

        logger.debug(
            "Idempotency kaliti bo'shatildi",
            user_id=str(user_id),
            idempotency_key=key,
            existed=bool(deleted),
        )

    async def lookup(self, user_id: str | UUID, key: str) -> IdempotencyRecord | None:
        """Kalit holatini o'qiydi — hech narsani o'zgartirmaydi va xato tashlamaydi.

        Barmoq izi solishtirilmaydi: bu metod faqat "shu kalit bo'yicha nima
        bor?" degan savolga javob beradi (`IdempotencyMiddleware` va
        diagnostika uchun).

        Raises:
            InfrastructureError: Redis javob bermadi.
        """
        return await self._read(self._key(user_id, key), operation="lookup")

    async def ttl_seconds(self, user_id: str | UUID, key: str) -> int | None:
        """Kalit yozuvining qolgan muddati (soniya); yo'q bo'lsa `None`.

        `GET /jobs/{id}/idempotency` uchun: mijoz "takroriy so'rovim
        qachongacha ayni job'ni qaytaradi?" degan savolga javob oladi.

        Redis `TTL` qaytaradigan maxsus qiymatlar tarjima qilinadi:
        `-2` — kalit yo'q, `-1` — muddat qo'yilmagan. Ikkisi ham `None`
        bo'ladi, chunki ikkisida ham "tugash vaqti" tushunchasi yo'q.

        Xato TASHLAMAYDI: bu diagnostika ma'lumoti, Redis javob bermasa
        `None` qaytaradi va asosiy javob baribir qaytariladi.
        """
        try:
            raw = await self.redis.ttl(self._key(user_id, key))
        except RedisError as exc:
            logger.warning(
                "idempotency.ttl_unavailable",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return None
        value = int(raw)
        return value if value >= 0 else None


__all__ = [
    "MAX_RESERVE_ATTEMPTS",
    "STATE_COMPLETED",
    "STATE_IN_PROGRESS",
    "IdempotencyRecord",
    "IdempotencyService",
    "IdempotencyState",
]
