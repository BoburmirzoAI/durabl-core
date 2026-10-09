"""Durabl — webhook servisi: mijoz CRUD, hodisa tarqatish va HTTP yuborish.

## Nima uchun ikki bosqich (dispatch -> deliver)

Job tugaganda mijozga darhol HTTP POST qilish **xato dizayn**: mijozning
endpoint'i 10 soniya javob bermasa, job'ning yakunlanishi ham 10 soniya
kechikadi, worker esa band turadi. Mijozning sekin serveri butun platformaning
o'tkazuvchanligini pasaytirardi.

Shuning uchun yuborish ikkiga bo'lingan:

1. **`dispatch(job, event)`** — tezkor, faqat DB + Redis. Har mos webhook
   uchun `webhook_deliveries` jadvaliga `PENDING` yozuv yaratadi va
   `RedisKeys.WEBHOOK_QUEUE` ga uning id'sini `RPUSH` qiladi.
   **HTTP so'rov YUBORMAYDI.**
2. **`deliver(delivery)`** — haqiqiy HTTP POST. Uni `webhook_sender` worker'i
   alohida protsessda chaqiradi, shuning uchun mijozning sekinligi job
   bajarilishiga ta'sir qilmaydi.

## At-least-once kafolati

Yuborish navbati Redis'da, lekin **haqiqat manbai PostgreSQL**. Har bir
delivery `next_retry_at=utcnow()` bilan yaratiladi, ya'ni Redis'dagi yozuv
yo'qolsa ham (`RPUSH` xato berdi, Redis qulab qayta ko'tarildi, worker
`BLPOP` dan keyin qulab tushdi) `retry_pending()` ni `WebhookDeliveryRepository.
pending_retries()` orqali o'sha yozuvni TOPADI va davom ettiradi. Redis bu
yerda faqat "darhol xabar berish" vositasi, bardoshlilik emas.

Teskari tomoni: `dispatch()` tranzaksiya egasi EMAS (`job_service` commit
qiladi), shuning uchun `RPUSH` commit'dan OLDIN ketishi mumkin va worker
hali ko'rinmaydigan qatorni so'rab qolishi mumkin. Bu holat xavfsiz —
worker qatorni topmasa shunchaki tashlab ketadi, `pending_retries()` esa
commit'dan keyin uni baribir oladi.

## Retry va o'chirish siyosati

| Natija | Holat | Izoh |
|---|---|---|
| 2xx | `SUCCESS` | `consecutive_failures=0` |
| 408, 429, 5xx, tarmoq xatosi | `RETRYING` -> `EXHAUSTED` | `webhook_policy()` backoff'i |
| 3xx | `EXHAUSTED` | redirect ATAYLAB kuzatilmaydi (SSRF) |
| boshqa 4xx | `EXHAUSTED` | mijoz endpointi buzuq, qayta urinish befoyda |
| SSRF bloki | `EXHAUSTED` | URL endi ichki manzilga ishora qiladi |

`consecutive_failures` `AUTO_DISABLE_THRESHOLD` ga yetsa webhook avtomatik
o'chiriladi (`is_active=False`, `disabled_at`) va operatorga bildirishnoma
yuboriladi. Mijoz `update(is_active=True)` bilan qayta yoqsa hisoblagich
nolga qaytadi.

## DNS rebinding himoyasi

URL faqat yaratilganda emas, **har yuborish oldidan ham** tekshiriladi
(`validate_webhook_url_async`). Aks holda mijoz bugun `https://ok.example.com`
ni ro'yxatdan o'tkazib, ertaga uning DNS yozuvini `10.0.0.1` ga o'zgartirib
bizning serverimizdan ichki tarmoqqa so'rov yuborishga erishardi.

## Tranzaksiya chegarasi

* **`dispatch()` — ICHKI metod, commit QILMAYDI.** Uni `job_service` chaqiradi
  va o'z tranzaksiyasi ichida commit qiladi.
* **`deliver()` — commit QILADI.** Uni worker halqasi chaqiradi; har urinish
  natijasi darhol bardoshli bo'lishi kerak, aks holda protsess qulaganda
  ayni webhook ikkinchi marta yuborilardi. Shu sababli partiyadagi bitta
  yomon delivery boshqalarining natijasini rollback qilmaydi.
* CRUD metodlari (`create`/`update`/`delete`/`test`) commit qiladi.
* `list`/`get`/`deliveries` faqat o'qiydi.

Qatlam qoidasi: `fastapi` import QILINMAYDI, `HTTPException` tashlanmaydi —
ayni shu kod `webhook_sender` worker protsessida ham ishlaydi.
"""

from __future__ import annotations

import builtins  # `list` klass ichida metod nomi — builtin'ga ochiq murojaat uchun
import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

import httpx
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.constants import (
    HEADER_WEBHOOK_DELIVERY,
    HEADER_WEBHOOK_EVENT,
    HEADER_WEBHOOK_SIGNATURE,
    HEADER_WEBHOOK_TIMESTAMP,
    DeliveryStatus,
    JobStatus,
    Priority,
    RedisKeys,
    Runtime,
    WebhookEvent,
)
from app.exceptions import (
    DatabaseError,
    ValidationError,
    WebhookNotFoundError,
    WebhookUrlNotAllowedError,
)
from app.logging_config import get_logger
from app.metrics import track_webhook_delivery
from app.models.job import Job
from app.models.user import User
from app.models.webhook import Webhook
from app.models.webhook_delivery import WebhookDelivery
from app.redis_client import get_redis
from app.repositories.webhook_delivery_repo import WebhookDeliveryRepository
from app.repositories.webhook_repo import WebhookRepository
from app.schemas.base import PaginationParams
from app.schemas.webhook import (
    WebhookCreate,
    WebhookTestRequest,
    WebhookTestResponse,
    WebhookUpdate,
)
from app.services.notification_service import NotificationService
from app.utils.retry_policy import webhook_policy
from app.utils.security import generate_webhook_secret, sign_webhook
from app.utils.serializers import dump_json, job_event_payload, truncate
from app.utils.time_utils import isoformat, utcnow
from app.utils.validators import validate_webhook_url_async

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Konstantalar
# ---------------------------------------------------------------------------

#: Bitta foydalanuvchida nechta webhook bo'lishi mumkin. Chegara ikki sababdan
#: kerak: (a) `dispatch()` har hodisada shu qadar qator yozadi va shu qadar
#: HTTP so'rov yaratadi — cheklanmasa bitta mijoz butun `webhook_sender`
#: quvvatini egallaydi; (b) `active_for_event()` hodisa bo'yicha saralashni
#: Python tomonida bajaradi, ya'ni ro'yxat kichik bo'lishiga tayanadi.
MAX_WEBHOOKS_PER_USER: Final = 10

#: Ketma-ket shuncha xatodan keyin webhook AVTOMATIK o'chiriladi.
#: `settings` da bu qiymat yo'q va `config.py` ga tegish taqiqlangan, shuning
#: uchun konstanta shu modulda (shartnomada ko'rsatilgan 10 qiymati bilan).
AUTO_DISABLE_THRESHOLD: Final = 10

#: `webhook_deliveries.response_body` shu belgidan uzun bo'lsa kesiladi.
#: `app.schemas.webhook.MAX_TEST_RESPONSE_BODY` va modeldagi "4KB" izohi bilan
#: bir xil — mijozning 10 MB HTML xato sahifasi jadvalni to'ldirmasligi uchun.
MAX_RESPONSE_BODY_CHARS: Final = 4_096

#: Mijoz logida ko'rinadigan agent nomi.
USER_AGENT: Final = "Durabl-Webhook/1.0"

#: Qayta urinishga ARZIYDIGAN 4xx kodlar. 408 (Request Timeout) va 429
#: (Too Many Requests) vaqtinchalik holat bildiradi, qolgan 4xx esa mijoz
#: endpoint'ining doimiy nosozligi.
RETRYABLE_CLIENT_CODES: Final[frozenset[int]] = frozenset({408, 429})

#: `retry_pending()` uchun standart partiya hajmi.
DEFAULT_RETRY_LIMIT: Final = 50

#: `test()` javobidagi sun'iy job'ning davomiyligi (ms) — mijoz shaklni
#: ko'rishi uchun nol bo'lmagan namuna qiymat.
SAMPLE_DURATION_MS: Final = 1_234


# ---------------------------------------------------------------------------
# Sinov (test) natijasi
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class WebhookTestOutcome:
    """`test()` ning TO'LIQ natijasi — imzo bilan birga.

    **Nega alohida dataclass kerak.** Shartnoma `test()` dan `signature`
    maydonini ham talab qiladi, lekin tayyor `app/schemas/webhook.py` dagi
    `WebhookTestResponse` da bunday maydon YO'Q va u `ORMSchema` (ya'ni
    `extra="ignore"`) — `signature=` uzatilsa JIMGINA tashlab yuborilardi va
    mijoz imzoni tekshirib ko'ra olmasdi.

    Shuning uchun imzo shu dataclass'da qaytariladi: `test()` shartnomadagi
    `WebhookTestResponse` ni beradi, `send_test()` esa imzo bilan to'liq
    natijani. Schema egasi `WebhookTestResponse` ga `signature` maydonini
    qo'shsa, `to_response()` ni bir qatorda to'ldirish kifoya.
    """

    event: WebhookEvent
    success: bool
    #: `X-Durabl-Signature` header'ining aynan yuborilgan qiymati
    #: (`t=<ts>,v1=<hmac>`). `verify_webhook_signature(body, signature, secret)`
    #: bilan tekshirib ko'rish mumkin.
    signature: str
    #: Imzolangan tana — imzoni tekshirish uchun AYNAN shu baytlar kerak.
    body: bytes
    status_code: int | None = None
    duration_ms: int = 0
    response_body: str | None = None
    error: str | None = None
    sent_at: datetime | None = None
    delivery_id: uuid.UUID | None = None
    #: Yuborilgan JSON tanasining lug'at ko'rinishi (UI'da ko'rsatish uchun).
    payload: dict[str, Any] = field(default_factory=dict)

    def to_response(self) -> WebhookTestResponse:
        """Shartnomadagi `WebhookTestResponse` schema'siga aylantiradi."""
        return WebhookTestResponse(
            success=self.success,
            event=self.event,
            status_code=self.status_code,
            duration_ms=self.duration_ms,
            response_body=self.response_body,
            error=self.error,
            sent_at=self.sent_at,
        )


class _SampleJob:
    """`test()` uchun sun'iy job — HAQIQIY hodisa bilan AYNI shaklni beradi.

    `job_event_payload()` modelga faqat `getattr` orqali murojaat qiladi
    (`app/utils/serializers.py` docstring'iga qara), shuning uchun oddiy
    obyekt yetarli — bazaga soxta qator yozish kerak emas. Shaklning haqiqiy
    hodisa bilan bir xilligi muhim: mijoz sinov payload'i bo'yicha parser
    yozadi va u ishlab chiqarishda ham ishlashi kerak.
    """

    __slots__ = (
        "correlation_id",
        "created_at",
        "duration_ms",
        "error",
        "exit_code",
        "failure_reason",
        "finished_at",
        "id",
        "priority",
        "retry_count",
        "runtime",
        "started_at",
        "status",
        "user_id",
    )

    def __init__(self, user_id: uuid.UUID | str) -> None:
        now = utcnow()
        self.id = uuid.uuid4()
        self.user_id = user_id
        self.status = JobStatus.SUCCESS
        self.runtime = Runtime.PYTHON
        self.priority = Priority.NORMAL
        self.created_at = now
        self.started_at = now
        self.finished_at = now
        self.duration_ms = SAMPLE_DURATION_MS
        self.exit_code = 0
        self.retry_count = 0
        self.failure_reason = None
        self.error = None
        self.correlation_id = uuid.uuid4().hex


class WebhookService:
    """Mijoz webhook'lari: CRUD, hodisa tarqatish va HTTP yetkazish."""

    def __init__(self, session: AsyncSession, redis: Redis | None = None) -> None:
        self.session = session
        self.redis = redis or get_redis()
        self.webhooks = WebhookRepository(session)
        self.deliveries_repo = WebhookDeliveryRepository(session)
        self.notifications = NotificationService()

    # ------------------------------------------------------------------
    # Mijoz CRUD
    # ------------------------------------------------------------------

    async def create(self, user: User, data: WebhookCreate) -> Webhook:
        """Yangi webhook ro'yxatdan o'tkazadi.

        Tekshiruvlar TARTIBI muhim — eng arzoni va eng xavflisi birinchi:

        1. **SSRF** (`validate_webhook_url_async`) — `http://localhost/...`,
           `http://169.254.169.254/...` (cloud metadata) va DNS'i ichki IP'ga
           yechiladigan hostlar rad etiladi (`WebhookUrlNotAllowedError`).
           Bu tekshiruv birinchi, chunki uni o'tmagan URL uchun boshqa hech
           narsani hisoblash kerak emas.
        2. **Soni** — `MAX_WEBHOOKS_PER_USER` dan oshmasligi.
        3. **Hodisalar** — har biri `WebhookEvent` enumiga tegishli bo'lishi.

        Imzo kaliti: mijoz `secret` yuborsa o'shanisi (o'z tizimida allaqachon
        saqlangan kalitni qayta ishlatish imkoniyati), aks holda
        `generate_webhook_secret()` xavfsiz tasodifiy kalit yasaydi. Kalit
        mijozga FAQAT `WebhookCreated` javobida bir marta ko'rsatiladi.

        Tranzaksiya: o'zi egasi — oxirida `commit()` qiladi.

        Raises:
            WebhookUrlNotAllowedError: URL ichki/mahalliy manzilga ishora qiladi.
            ValidationError: URL shakli, webhook soni yoki hodisa nomi noto'g'ri.
        """
        await validate_webhook_url_async(data.url)

        existing = await self.webhooks.count_for_user(user.id)
        if existing >= MAX_WEBHOOKS_PER_USER:
            raise ValidationError(
                f"Webhook'lar soni chegarasiga yetdi (maksimum {MAX_WEBHOOKS_PER_USER})",
                details={"count": existing, "limit": MAX_WEBHOOKS_PER_USER},
            )

        events = self._normalize_events(data.events)
        webhook = await self.webhooks.create(
            user_id=user.id,
            url=data.url,
            secret=data.secret or generate_webhook_secret(),
            events=events,
            description=data.description,
            is_active=data.is_active,
            consecutive_failures=0,
        )
        await self.session.commit()

        logger.info(
            "webhook.created",
            webhook_id=str(webhook.id),
            user_id=str(user.id),
            url=webhook.url,
            events=events,
            is_active=webhook.is_active,
        )
        return webhook

    async def update(
        self,
        user: User,
        webhook_id: uuid.UUID | str,
        data: WebhookUpdate,
    ) -> Webhook:
        """Webhook sozlamasini qismiy yangilaydi.

        Faqat OCHIQ berilgan maydonlar o'zgaradi (`model_fields_set`) — shu
        tufayli `description=None` uzatish "izohni o'chirish" degani bo'ladi,
        maydonni umuman yubormaslik esa "tegmaslik".

        **Qayta yoqish (`is_active=True`) `disabled_at` va
        `consecutive_failures` ni ham tozalaydi.** Busiz mijoz endpoint'ini
        tuzatib webhook'ni yoqsa, hisoblagich 10 da turgani uchun KEYINGI
        xatoda darhol yana o'chib qolardi.

        URL o'zgarsa SSRF tekshiruvi qaytadan bajariladi — aks holda mijoz
        bloklangan manzilga "yangilash" orqali o'tib ketardi.

        Tranzaksiya: o'zi egasi — o'zgarish bo'lsa `commit()` qiladi.

        Raises:
            WebhookNotFoundError: Webhook yo'q yoki boshqa foydalanuvchiga tegishli.
            WebhookUrlNotAllowedError: Yangi URL ruxsat etilmagan.
            ValidationError: Hodisa nomi noto'g'ri.
        """
        webhook = await self._owned(user, webhook_id)
        provided = data.model_fields_set
        values: dict[str, Any] = {}

        if "url" in provided and data.url is not None and data.url != webhook.url:
            await validate_webhook_url_async(data.url)
            values["url"] = data.url
        if "events" in provided and data.events is not None:
            values["events"] = self._normalize_events(data.events)
        if "description" in provided:
            values["description"] = data.description
        if "is_active" in provided and data.is_active is not None:
            values["is_active"] = data.is_active
            if data.is_active:
                values["disabled_at"] = None
                values["consecutive_failures"] = 0

        if not values:
            logger.debug(
                "webhook.update_noop",
                webhook_id=str(webhook.id),
                user_id=str(user.id),
            )
            return webhook

        await self.webhooks.update(webhook, **values)
        await self.session.commit()

        logger.info(
            "webhook.updated",
            webhook_id=str(webhook.id),
            user_id=str(user.id),
            changed=sorted(values),
        )
        return webhook

    async def delete(self, user: User, webhook_id: uuid.UUID | str) -> None:
        """Webhook'ni butunlay o'chiradi.

        Yuborish tarixi (`webhook_deliveries`) DB darajasidagi
        `ON DELETE CASCADE` bilan birga o'chadi (`passive_deletes=True`),
        shuning uchun qatorlarni qo'lda tanlash kerak emas.

        Tranzaksiya: o'zi egasi — oxirida `commit()` qiladi.
        """
        webhook = await self._owned(user, webhook_id)
        url = webhook.url
        await self.webhooks.delete(webhook)
        await self.session.commit()

        logger.info(
            "webhook.deleted",
            webhook_id=str(webhook_id),
            user_id=str(user.id),
            url=url,
        )

    async def list(self, user: User, *, active_only: bool = False) -> list[Webhook]:
        """Foydalanuvchining webhook'lari (yangisidan boshlab).

        `active_only=True` — faqat haqiqatan ishlayotganlari: mijoz yoqqan
        (`is_active`) VA tizim o'chirmagan (`disabled_at IS NULL`). Bu
        `Webhook.is_enabled` xossasining SQL ko'rinishi.
        """
        return await self.webhooks.list_for_user(user.id, active_only=active_only)

    async def get(self, user: User, webhook_id: uuid.UUID | str) -> Webhook:
        """Bitta webhook (egalik tekshiruvi bilan).

        Raises:
            WebhookNotFoundError: Yo'q yoki boshqa foydalanuvchiga tegishli.
        """
        return await self._owned(user, webhook_id)

    async def deliveries(
        self,
        user: User,
        webhook_id: uuid.UUID | str,
        pagination: PaginationParams,
    ) -> tuple[builtins.list[WebhookDelivery], int]:
        """Bitta webhook'ning yuborish tarixi: `(yozuvlar, umumiy_son)`.

        Egalik AVVAL tekshiriladi — aks holda boshqa foydalanuvchining
        webhook id'si bilan uning yuborish tarixini (ya'ni job payload'larini)
        o'qib olish mumkin bo'lardi.
        """
        webhook = await self._owned(user, webhook_id)
        return await self.deliveries_repo.list_for_webhook(
            webhook.id,
            page=pagination.page,
            page_size=pagination.page_size,
        )

    # ------------------------------------------------------------------
    # Hodisa tarqatish
    # ------------------------------------------------------------------

    @staticmethod
    def build_payload(job: Job | Any, event: WebhookEvent) -> dict[str, Any]:
        """Webhook tanasining YAGONA shakli.

        ```json
        {"event": "job.succeeded", "timestamp": "...Z", "data": {...}}
        ```

        `data` — `serializers.job_event_payload(job)`, ya'ni WebSocket orqali
        boradigan hodisa bilan AYNAN bir xil lug'at. Shu tufayli mijoz
        webhook va WebSocket uchun bitta parser yozadi, shakl esa faqat
        `serializers` da o'zgaradi.

        `timestamp` — hodisa YASALGAN vaqt, yuborilgan vaqt emas: qayta
        urinishda ham o'zgarmaydi, shuning uchun mijoz uni hodisalarni
        tartiblash va dublikatni aniqlash uchun ishlatishi mumkin.
        """
        return {
            "event": WebhookEvent(event).value,
            "timestamp": isoformat(utcnow()),
            "data": job_event_payload(job),
        }

    async def dispatch(self, job: Job, event: WebhookEvent) -> int:
        """Hodisaga mos webhook'lar uchun yetkazish yozuvlarini yaratadi.

        **HTTP so'rov YUBORMAYDI** — modul docstring'idagi "nima uchun ikki
        bosqich" bo'limiga qara. Faqat:

        1. `WebhookRepository.active_for_event(job.user_id, event)` bilan mos
           FAOL webhook'larni topadi;
        2. har biri uchun `PENDING` delivery yozadi (`attempt=1`,
           `next_retry_at=utcnow()` — ya'ni darhol yuborilishi kerak va
           Redis yo'qolsa `pending_retries()` uni topadi);
        3. `webhook.last_triggered_at` ni yangilaydi ("hodisa mos keldi"
           ma'nosida — yuborish muvaffaqiyati `delivery.delivered_at` da);
        4. delivery id'larini `RedisKeys.WEBHOOK_QUEUE` ga `RPUSH` qiladi.

        **ICHKI metod: `commit()` QILMAYDI.** Chaqiruvchi (`job_service`)
        o'z tranzaksiyasi ichida commit qiladi — shu tufayli job holati va
        webhook yozuvlari bir atomar o'zgarishda boradi.

        Redis xatosi YUTILADI (`warning` log): navbat — tezlik vositasi,
        bardoshlilik esa DB'da.

        Returns:
            Yaratilgan delivery yozuvlari soni. Mos webhook bo'lmasa yoki
            `settings.WEBHOOK_ENABLED=False` bo'lsa `0`.
        """
        if not settings.WEBHOOK_ENABLED:
            logger.debug(
                "webhook.dispatch_disabled",
                job_id=str(job.id),
                webhook_event=WebhookEvent(event).value,
            )
            return 0

        targets = await self.webhooks.active_for_event(job.user_id, event)
        if not targets:
            return 0

        payload = self.build_payload(job, event)
        now = utcnow()
        created: list[WebhookDelivery] = []

        for webhook in targets:
            delivery = await self.deliveries_repo.create(
                webhook_id=webhook.id,
                job_id=job.id,
                event=WebhookEvent(event),
                status=DeliveryStatus.PENDING,
                attempt=1,
                payload=payload,
                next_retry_at=now,
            )
            created.append(delivery)
            webhook.last_triggered_at = now

        await self.session.flush()
        await self._enqueue(created)

        logger.info(
            "webhook.dispatched",
            job_id=str(job.id),
            webhook_event=WebhookEvent(event).value,
            created=len(created),
            webhook_ids=[str(item.webhook_id) for item in created],
        )
        return len(created)

    # ------------------------------------------------------------------
    # HTTP yetkazish
    # ------------------------------------------------------------------

    async def deliver(self, delivery: WebhookDelivery) -> bool:
        """Bitta delivery'ni HAQIQIY HTTP POST bilan yuboradi.

        **HECH QACHON xato tashlamaydi** — `webhook_sender` worker'ining
        halqasi bitta buzuq mijoz endpoint'i sababli to'xtamasligi kerak.
        Natija faqat `bool` bilan bildiriladi, tafsilot esa DB'da
        (`status`, `response_code`, `error_message`) va logda qoladi.

        Qadamlar:

        1. Delivery `selectinload(WebhookDelivery.webhook)` bilan QAYTA
           o'qiladi. Buning ikki sababi bor: (a) `lazy="raise"` tufayli
           `delivery.webhook` ga shunchaki murojaat `InvalidRequestError`
           beradi; (b) argument boshqa sessiyada yuklangan bo'lishi mumkin
           (worker uni navbatdan olgan), shuning uchun yozuv ayni shu
           sessiyaga bog'lanishi kerak.
        2. Yakuniy holatdagi delivery QAYTA yuborilmaydi (idempotentlik —
           Redis navbatidagi dublikat id xavfsiz).
        3. DNS rebinding tekshiruvi (`validate_webhook_url_async`).
        4. Tana `dump_json(payload)` ning UTF-8 baytlari — imzolanadigan va
           yuboriladigan baytlar AYNAN bir xil bo'lishi uchun bir marta
           kodlanadi.
        5. POST, natijaga qarab `SUCCESS` / `RETRYING` / `EXHAUSTED`.

        Returns:
            `True` — 2xx javob olindi. Boshqa barcha holatda `False`.
        """
        try:
            delivery_id = delivery.id
        except Exception as exc:
            # Argument "expired" holatda bo'lishi mumkin (chaqiruvchining
            # sessiyasi rollback qilgan) — bunda atributni o'qish DB'ga
            # murojaat qiladi va `MissingGreenlet` beradi. Bu ham yutiladi.
            logger.error(
                "webhook.delivery_id_unreadable",
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False
        return await self._deliver_by_id(delivery_id)

    async def _deliver_by_id(self, delivery_id: uuid.UUID) -> bool:
        """`deliver()` ning id bo'yicha varianti — xato to'sig'i shu yerda.

        **`delivery_id` ODDIY lokal o'zgaruvchi bo'lishi SHART** (ORM obyekti
        atributi emas): `_safe_rollback()` sessiyadagi barcha obyektlarni
        "expired" qiladi, shundan keyin `delivery.id` ga murojaat DB'dan
        qayta o'qishga urinadi va sinxron `except` bloki ichida
        `MissingGreenlet` tashlaydi. Ya'ni "xato tashlamaydi" kafolati
        AYNAN xato log qilinayotgan paytda buzilardi.
        """
        try:
            return await self._deliver_inner(delivery_id)
        except Exception as exc:  # yetkazish HECH QACHON worker halqasini yiqitmaydi
            await self._safe_rollback()
            logger.error(
                "webhook.deliver_unexpected_error",
                delivery_id=str(delivery_id),
                error=str(exc),
                error_type=type(exc).__name__,
            )
            return False

    async def retry_pending(
        self,
        *,
        now: datetime | None = None,
        limit: int = DEFAULT_RETRY_LIMIT,
    ) -> int:
        """Vaqti kelgan qayta urinishlarni yuboradi.

        `webhook_sender` worker'i shu metodni davriy (`WEBHOOK_SENDER_INTERVAL_SECONDS`)
        chaqiradi. Bu AYNI PAYTDA Redis navbatining zaxirasi: `dispatch()`
        yaratgan `PENDING` yozuv ham `next_retry_at=utcnow()` bilan kelgani
        uchun shu yerda topiladi, ya'ni Redis butunlay ishlamasa ham webhook'lar
        yuboriladi (faqat `WEBHOOK_SENDER_INTERVAL_SECONDS` kechikish bilan).

        Yetkazishlar KETMA-KET bajariladi, ataylab: parallel yuborish bitta
        mijozning serverini "o'z-o'zidan DDoS" qilishi mumkin, qolaversa har
        `deliver()` o'z `commit()` ini qiladi va bitta sessiyada parallel
        tranzaksiya ishlamaydi.

        Returns:
            MUVAFFAQIYATLI yetkazilganlar soni (urinishlar soni emas).
        """
        if not settings.WEBHOOK_ENABLED:
            return 0

        moment = now or utcnow()
        try:
            due = await self.deliveries_repo.pending_retries(moment, limit)
        except DatabaseError as exc:
            logger.error("webhook.retry_scan_failed", error=str(exc))
            return 0

        if not due:
            return 0

        # ID'lar BIRINCHI navbatda o'qiladi: `deliver()` xato bo'lganda
        # `rollback()` qiladi va `due` ro'yxatidagi QOLGAN obyektlar
        # "expired" bo'lib qoladi — keyin ularning `id` sini o'qish DB'ga
        # murojaat qilib `MissingGreenlet` berardi.
        ids = [item.id for item in due]

        delivered = 0
        for delivery_id in ids:
            if await self._deliver_by_id(delivery_id):
                delivered += 1

        logger.info(
            "webhook.retry_batch",
            scanned=len(due),
            delivered=delivered,
            failed=len(due) - delivered,
        )
        return delivered

    # ------------------------------------------------------------------
    # Sinov yuborish
    # ------------------------------------------------------------------

    async def test(
        self,
        user: User,
        webhook_id: uuid.UUID | str,
        data: WebhookTestRequest,
    ) -> WebhookTestResponse:
        """Sinov hodisasini DARHOL yuboradi (navbatga qo'ymaydi).

        Mijoz "ulanishni tekshirish" tugmasini bosganda imzo, header'lar va
        tana shakli ishlab chiqarishdagi bilan AYNAN bir xil bo'lishi kerak,
        aks holda sinov hech narsani isbotlamaydi.

        Imzo qiymati javobga sig'maydi (`WebhookTestOutcome` docstring'iga
        qara) — kerak bo'lsa `send_test()` ni chaqiring.
        """
        outcome = await self.send_test(user, webhook_id, data)
        return outcome.to_response()

    async def send_test(
        self,
        user: User,
        webhook_id: uuid.UUID | str,
        data: WebhookTestRequest,
    ) -> WebhookTestOutcome:
        """`test()` ning to'liq varianti — imzo va imzolangan tanani ham beradi.

        Farqlari (ataylab):

        * **`consecutive_failures` ga TA'SIR QILMAYDI.** Sinov muvaffaqiyatsiz
          bo'lsa webhook avtomatik o'chishga yaqinlashmasligi kerak — aks
          holda mijoz "tekshirib ko'rish" bilan o'z webhook'ini o'chirib
          qo'yardi. Shu sababli `last_triggered_at` ham yangilanmaydi.
        * **Qayta urinish YO'Q.** Natija `SUCCESS` yoki `FAILED` —
          `FAILED` `RETRYABLE_STATUSES` ga kirmaydi, shuning uchun
          `pending_retries()` bu yozuvni hech qachon olmaydi.
        * **`is_active` tekshirilmaydi** — o'chirilgan webhook'ni tuzatishdan
          oldin sinab ko'rish mumkin bo'lishi kerak.

        Audit uchun `webhook_deliveries` ga yozuv baribir yaratiladi
        (`job_id=NULL` — model bu holatni ochiq qo'llab-quvvatlaydi).

        Tranzaksiya: o'zi egasi — oxirida `commit()` qiladi.
        """
        webhook = await self._owned(user, webhook_id)
        event = WebhookEvent(data.event)
        payload = (
            data.payload
            if data.payload is not None
            else self.build_payload(_SampleJob(webhook.user_id), event)
        )

        delivery = await self.deliveries_repo.create(
            webhook_id=webhook.id,
            job_id=None,
            event=event,
            status=DeliveryStatus.PENDING,
            attempt=1,
            payload=payload,
            next_retry_at=None,
        )

        body = dump_json(payload).encode("utf-8")
        timestamp = int(utcnow().timestamp())
        signature = sign_webhook(body, webhook.secret, timestamp=timestamp)
        headers = self._headers(
            event=event,
            delivery_id=delivery.id,
            signature=signature,
            timestamp=timestamp,
        )

        sent_at = utcnow()
        started = time.perf_counter()
        status_code: int | None = None
        response_body: str | None = None
        error: str | None = None

        try:
            async with httpx.AsyncClient(
                timeout=settings.WEBHOOK_TIMEOUT_SECONDS,
                follow_redirects=False,
            ) as client:
                response = await client.post(webhook.url, content=body, headers=headers)
            status_code = response.status_code
            response_body = self._clip(response.text)
        except httpx.HTTPError as exc:
            error = self._describe_network_error(exc)
        except Exception as exc:  # sinov ham mijozga xato tashlamaydi
            error = f"{type(exc).__name__}: {exc}"

        duration = self._elapsed_ms(started)
        success = status_code is not None and 200 <= status_code < 300
        if not success and error is None and status_code is not None:
            error = f"HTTP {status_code}"

        await self.deliveries_repo.record_attempt(
            delivery,
            status=DeliveryStatus.SUCCESS if success else DeliveryStatus.FAILED,
            response_code=status_code,
            response_body=response_body,
            error_message=error,
            duration_ms=duration,
            next_retry_at=None,
        )
        track_webhook_delivery(
            DeliveryStatus.SUCCESS if success else DeliveryStatus.FAILED,
            duration_seconds=duration / 1000.0,
        )
        await self.session.commit()

        logger.info(
            "webhook.tested",
            webhook_id=str(webhook.id),
            user_id=str(user.id),
            webhook_event=event.value,
            success=success,
            status_code=status_code,
            duration_ms=duration,
            error=error,
        )

        return WebhookTestOutcome(
            event=event,
            success=success,
            signature=signature,
            body=body,
            status_code=status_code,
            duration_ms=duration,
            response_body=response_body,
            error=error,
            sent_at=sent_at,
            delivery_id=delivery.id,
            payload=payload,
        )

    # ------------------------------------------------------------------
    # Ichki: yetkazish bosqichlari
    # ------------------------------------------------------------------

    async def _deliver_inner(self, delivery_id: uuid.UUID) -> bool:
        """`deliver()` ning asosiy mantiqi (tashqi `try` ichida chaqiriladi)."""
        loaded = await self._load_delivery(delivery_id)
        if loaded is None:
            # Job (va kaskad bilan delivery) o'chirilgan, yoki `dispatch()`
            # ning tranzaksiyasi hali commit qilinmagan. Ikki holat ham
            # xavfsiz: `pending_retries()` yozuv ko'ringanda qaytib keladi.
            logger.warning("webhook.delivery_missing", delivery_id=str(delivery_id))
            return False

        webhook = loaded.webhook
        if webhook is None:
            # Webhook sozlamasi yo'q: qator o'chirilgan (kaskad ulgurmagan
            # yoki FK majburlanmagan DB'da yetim qolgan). Yozuvni YAKUNIY
            # holatga o'tkazish SHART — aks holda `pending_retries()` uni
            # abadiy qaytarib turadi va `webhook_sender` har tsiklda shu
            # yetim yozuvni qayta ishlab, `limit` ni band qilib bo'sh aylanadi.
            await self.deliveries_repo.record_attempt(
                loaded,
                status=DeliveryStatus.EXHAUSTED,
                error_message="Webhook sozlamasi topilmadi (o'chirilgan)",
            )
            await self.session.commit()
            logger.warning(
                "webhook.delivery_orphaned",
                delivery_id=str(loaded.id),
                webhook_id=str(loaded.webhook_id),
            )
            return False

        if loaded.is_terminal:
            logger.debug(
                "webhook.delivery_already_final",
                delivery_id=str(loaded.id),
                status=DeliveryStatus(loaded.status).value,
            )
            return loaded.is_successful

        body = dump_json(loaded.payload).encode("utf-8")
        timestamp = int(utcnow().timestamp())
        headers = self._headers(
            event=WebhookEvent(loaded.event),
            delivery_id=loaded.id,
            signature=sign_webhook(body, webhook.secret, timestamp=timestamp),
            timestamp=timestamp,
        )

        try:
            await validate_webhook_url_async(webhook.url)
        except (WebhookUrlNotAllowedError, ValidationError) as exc:
            # URL yaratilganda ruxsat etilgan edi, endi emas (DNS rebinding
            # yoki mijoz URL'ni o'zgartirgan). Qayta urinish befoyda.
            logger.warning(
                "webhook.url_blocked",
                delivery_id=str(loaded.id),
                webhook_id=str(webhook.id),
                url=webhook.url,
                error=exc.message,
            )
            return await self._record_failure(
                loaded,
                webhook,
                response_code=None,
                response_body=None,
                error_message=f"URL bloklandi: {exc.message}",
                duration_ms=0,
                retryable=False,
            )

        started = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                timeout=settings.WEBHOOK_TIMEOUT_SECONDS,
                follow_redirects=False,
            ) as client:
                response = await client.post(webhook.url, content=body, headers=headers)
        except httpx.HTTPError as exc:
            # Tarmoq xatosi (ulanmadi, timeout, TLS) — vaqtinchalik deb
            # hisoblanadi va backoff bilan qayta urinamiz.
            return await self._record_failure(
                loaded,
                webhook,
                response_code=None,
                response_body=None,
                error_message=self._describe_network_error(exc),
                duration_ms=self._elapsed_ms(started),
                retryable=True,
            )

        duration = self._elapsed_ms(started)
        code = response.status_code
        body_text = self._clip(response.text)

        if 200 <= code < 300:
            return await self._record_success(
                loaded,
                webhook,
                response_code=code,
                response_body=body_text,
                duration_ms=duration,
            )

        return await self._record_failure(
            loaded,
            webhook,
            response_code=code,
            response_body=body_text,
            error_message=f"HTTP {code}",
            duration_ms=duration,
            retryable=self._is_retryable_code(code),
        )

    async def _record_success(
        self,
        delivery: WebhookDelivery,
        webhook: Webhook,
        *,
        response_code: int,
        response_body: str | None,
        duration_ms: int,
    ) -> bool:
        """2xx javob: delivery `SUCCESS`, webhook hisoblagichi nolga qaytadi.

        `disabled_at` ATAYLAB tozalanmaydi: tizim o'chirgan webhook'ni faqat
        mijoz qayta yoqishi kerak (`update(is_active=True)`). Aks holda
        o'chirish arafasida yo'lda qolgan bitta muvaffaqiyatli urinish
        o'chirishni bekor qilib qo'yardi.
        """
        await self.deliveries_repo.record_attempt(
            delivery,
            status=DeliveryStatus.SUCCESS,
            response_code=response_code,
            response_body=response_body,
            error_message=None,
            duration_ms=duration_ms,
        )
        await self.webhooks.update(
            webhook,
            consecutive_failures=0,
            last_triggered_at=utcnow(),
        )
        track_webhook_delivery(
            DeliveryStatus.SUCCESS,
            duration_seconds=duration_ms / 1000.0,
        )
        await self.session.commit()

        logger.info(
            "webhook.delivered",
            delivery_id=str(delivery.id),
            webhook_id=str(webhook.id),
            webhook_event=WebhookEvent(delivery.event).value,
            attempt=delivery.attempt,
            status_code=response_code,
            duration_ms=duration_ms,
        )
        return True

    async def _record_failure(
        self,
        delivery: WebhookDelivery,
        webhook: Webhook,
        *,
        response_code: int | None,
        response_body: str | None,
        error_message: str,
        duration_ms: int,
        retryable: bool,
    ) -> bool:
        """Muvaffaqiyatsiz urinishni yozadi va keyingi holatni tanlaydi.

        * `retryable=True` va urinishlar qolgan bo'lsa -> `RETRYING`,
          `next_retry_at` `webhook_policy()` backoff'i bilan, `attempt += 1`.
        * aks holda -> `EXHAUSTED` (`record_attempt` `next_retry_at` ni
          `None` ga tushiradi, ya'ni `pending_retries()` boshqa olmaydi).

        Ikki holatda ham `consecutive_failures` oshadi va chegaraga yetganda
        webhook o'chiriladi. `commit()` dan KEYIN bildirishnoma yuboriladi:
        avval holat bardoshli bo'lishi, keyin odam xabardor qilinishi kerak
        (teskari tartibda "o'chirildi" xabari kelib, DB'da esa o'chmagan
        bo'lib qolishi mumkin edi).

        Har doim `False` qaytaradi — chaqiruvchi uni to'g'ridan-to'g'ri
        `return` qiladi.
        """
        policy = webhook_policy()
        attempt = delivery.attempt
        next_retry_at: datetime | None = None
        extra: dict[str, Any] = {}

        if retryable and policy.should_retry(attempt):
            status = DeliveryStatus.RETRYING
            _, next_retry_at = policy.schedule(attempt)
            extra = {"attempt": attempt + 1, "next_retry_at": next_retry_at}
        else:
            status = DeliveryStatus.EXHAUSTED

        await self.deliveries_repo.record_attempt(
            delivery,
            status=status,
            response_code=response_code,
            response_body=response_body,
            error_message=error_message,
            duration_ms=duration_ms,
            **extra,
        )
        auto_disabled = await self._register_failure(webhook)
        track_webhook_delivery(status, duration_seconds=duration_ms / 1000.0)
        await self.session.commit()

        logger.warning(
            "webhook.delivery_failed",
            delivery_id=str(delivery.id),
            webhook_id=str(webhook.id),
            webhook_event=WebhookEvent(delivery.event).value,
            delivery_status=status.value,
            attempt=attempt,
            status_code=response_code,
            error=error_message,
            duration_ms=duration_ms,
            next_retry_at=isoformat(next_retry_at),
            consecutive_failures=webhook.consecutive_failures,
            auto_disabled=auto_disabled,
        )

        if auto_disabled:
            logger.error(
                "webhook.auto_disabled",
                webhook_id=str(webhook.id),
                user_id=str(webhook.user_id),
                url=webhook.url,
                consecutive_failures=webhook.consecutive_failures,
                threshold=AUTO_DISABLE_THRESHOLD,
            )
            await self.notifications.notify_webhook_disabled(
                webhook.url,
                user_id=webhook.user_id,
            )
        return False

    async def _register_failure(self, webhook: Webhook) -> bool:
        """`consecutive_failures` ni oshiradi; chegaraga yetsa o'chiradi.

        Returns:
            `True` — webhook AYNI SHU chaqiruvda avtomatik o'chirildi
            (bildirishnoma faqat bir marta yuborilishi uchun).
        """
        failures = (webhook.consecutive_failures or 0) + 1
        values: dict[str, Any] = {"consecutive_failures": failures}
        disabled_now = failures >= AUTO_DISABLE_THRESHOLD and webhook.disabled_at is None
        if disabled_now:
            values["is_active"] = False
            values["disabled_at"] = utcnow()
        await self.webhooks.update(webhook, **values)
        return disabled_now

    # ------------------------------------------------------------------
    # Ichki yordamchilar
    # ------------------------------------------------------------------

    async def _owned(self, user: User, webhook_id: uuid.UUID | str) -> Webhook:
        """Webhook'ni EGASI bo'yicha oladi; topilmasa `WebhookNotFoundError`.

        Boshqa foydalanuvchining webhook'i so'ralganda ham AYNI "topilmadi"
        xatosi beriladi — yozuvning mavjudligi oshkor bo'lmasligi uchun
        (IDOR himoyasi).
        """
        webhook = await self.webhooks.get_for_user(webhook_id, user.id)
        if webhook is None:
            raise WebhookNotFoundError(webhook_id)
        return webhook

    async def _load_delivery(self, delivery_id: uuid.UUID) -> WebhookDelivery | None:
        """Delivery'ni `webhook` bilan birga yuklaydi (`lazy="raise"` uchun)."""
        stmt = (
            select(WebhookDelivery)
            .options(selectinload(WebhookDelivery.webhook))
            .where(WebhookDelivery.id == delivery_id)
        )
        try:
            result = await self.session.execute(stmt)
        except SQLAlchemyError as exc:
            raise DatabaseError(f"Delivery o'qishda xato: {exc}") from exc
        return result.scalars().first()

    async def _enqueue(self, deliveries: Sequence[WebhookDelivery]) -> None:
        """Delivery id'larini webhook navbatiga qo'yadi (best-effort).

        Redis xatosi TASHLANMAYDI: navbat — "darhol yuborish" signali, yozuv
        esa DB'da `next_retry_at=utcnow()` bilan turadi va `retry_pending()`
        uni baribir oladi. Shu sababli Redis nosozligi webhook'ni yo'qotmaydi,
        faqat kechiktiradi.
        """
        if not deliveries:
            return
        try:
            async with self.redis.pipeline(transaction=False) as pipe:
                for item in deliveries:
                    pipe.rpush(RedisKeys.WEBHOOK_QUEUE, str(item.id))
                await pipe.execute()
        except RedisError as exc:
            logger.warning(
                "webhook.enqueue_failed",
                count=len(deliveries),
                error=str(exc),
                note="yozuvlar DB'da qoldi, retry_pending() ularni oladi",
            )

    @staticmethod
    def _headers(
        *,
        event: WebhookEvent,
        delivery_id: uuid.UUID,
        signature: str,
        timestamp: int,
    ) -> dict[str, str]:
        """Yuborish header'lari.

        `HEADER_WEBHOOK_TIMESTAMP` imzo ichidagi `t=` qiymati bilan AYNAN bir
        xil bo'lishi shart — SDK ikkisini solishtirib replay hujumini
        aniqlaydi, mos kelmasa imzo tekshiruvi yiqiladi.
        """
        return {
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
            HEADER_WEBHOOK_SIGNATURE: signature,
            HEADER_WEBHOOK_EVENT: WebhookEvent(event).value,
            HEADER_WEBHOOK_DELIVERY: str(delivery_id),
            HEADER_WEBHOOK_TIMESTAMP: str(timestamp),
        }

    @staticmethod
    def _normalize_events(events: Sequence[WebhookEvent | str]) -> builtins.list[str]:
        """Hodisalarni tekshiradi, takrorlanganini olib tashlaydi (tartib saqlanadi).

        Schema (`WebhookCreate`) hodisalarni allaqachon `WebhookEvent` ga
        aylantiradi, lekin service qatlami o'zini mustaqil tutishi kerak:
        uni worker, migratsiya skripti yoki test XOM matn bilan chaqirishi
        mumkin.

        Raises:
            ValidationError: Noma'lum hodisa nomi yoki bo'sh ro'yxat.
        """
        normalized: list[str] = []
        unknown: list[str] = []
        for item in events:
            try:
                value = WebhookEvent(item).value
            except ValueError:
                unknown.append(str(item))
                continue
            if value not in normalized:
                normalized.append(value)

        if unknown:
            raise ValidationError(
                f"Noma'lum webhook hodisasi: {', '.join(unknown)}",
                details={"unknown_events": unknown, "allowed": WebhookEvent.all()},
            )
        if not normalized:
            raise ValidationError(
                "Kamida bitta hodisa ko'rsatilishi kerak",
                details={"allowed": WebhookEvent.all()},
            )
        return normalized

    @staticmethod
    def _is_retryable_code(code: int) -> bool:
        """HTTP kodi bo'yicha qayta urinish kerakmi.

        * `408`/`429` — vaqtinchalik mijoz tomoni holati -> urinamiz;
        * `3xx` — redirect KUZATILMAYDI (`follow_redirects=False`, SSRF
          himoyasi), shuning uchun bu sozlama xatosi -> urinmaymiz;
        * boshqa `4xx` — endpoint buzuq/yo'q -> urinmaymiz;
        * `5xx` va g'alati kodlar (`<200`) — server vaqtincha nosog' -> urinamiz.
        """
        if code in RETRYABLE_CLIENT_CODES:
            return True
        if 300 <= code < 500:
            return False
        return True

    @staticmethod
    def _clip(text: str | None) -> str | None:
        """Javob tanasini `MAX_RESPONSE_BODY_CHARS` gacha kesadi; bo'sh -> `None`."""
        clipped, _ = truncate(text, MAX_RESPONSE_BODY_CHARS)
        return clipped or None

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        """`time.perf_counter()` boshlanishidan o'tgan vaqt (ms).

        Monotonik soat ishlatiladi: tizim vaqti NTP bilan orqaga surilsa ham
        davomiylik manfiy chiqmaydi.
        """
        return max(0, int((time.perf_counter() - started) * 1000))

    @staticmethod
    def _describe_network_error(exc: httpx.HTTPError) -> str:
        """Tarmoq xatosini o'qishli matnga aylantiradi.

        `httpx` ba'zi xatolarda bo'sh `str(exc)` beradi (masalan
        `ConnectTimeout`), shuning uchun tur nomi HAR DOIM qo'shiladi —
        aks holda `error_message` ustunida bo'm-bo'sh matn qolardi.
        """
        detail = str(exc).strip()
        return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__

    async def _safe_rollback(self) -> None:
        """Sessiyani tozalaydi; rollback o'zi yiqilsa ham xato chiqarmaydi."""
        try:
            await self.session.rollback()
        except SQLAlchemyError as exc:  # pragma: no cover - sessiya allaqachon buzilgan
            logger.error("webhook.rollback_failed", error=str(exc))


__all__ = [
    "AUTO_DISABLE_THRESHOLD",
    "DEFAULT_RETRY_LIMIT",
    "MAX_RESPONSE_BODY_CHARS",
    "MAX_WEBHOOKS_PER_USER",
    "RETRYABLE_CLIENT_CODES",
    "SAMPLE_DURATION_MS",
    "USER_AGENT",
    "WebhookService",
    "WebhookTestOutcome",
]
