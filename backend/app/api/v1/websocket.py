"""Durabl — real-time job hodisalari (`WS /ws/jobs`).

Mijoz `?token=<jwt>` bilan ulanadi, server esa uning Redis Pub/Sub
kanaliga (`RedisKeys.events_user(user_id)`) obuna bo'lib, kelgan har bir
job hodisasini `{type, data, timestamp}` konvertida uzatadi.

## Nega `accept()` autentifikatsiyadan OLDIN

WebSocket'da xato sababini mijozga YETKAZISH uchun ulanish qabul
qilingan bo'lishi kerak: qabul qilinmagan ulanishni yopish mijozga
oddiy HTTP 403 beradi va yopilish KODI yo'qoladi. Shartnoma esa aniq
kodlarni talab qiladi (`1008` — token yaroqsiz, `1013` — ulanish limiti),
frontend ham ularni o'qiydi. Shuning uchun tartib: `accept()` ->
autentifikatsiya -> xato bo'lsa `WsErrorMessage` + `close(code=...)`.

## Nega DB sessiyasi uzoq ushlanmaydi

`get_ws_user` ni `Depends()` orqali olish sessiyani BUTUN ulanish
davomida band qilardi (generator dependency faqat ulanish uzilganda
yopiladi) — bir necha ochiq WebSocket butun pool'ni tugatardi. Shuning
uchun autentifikatsiya qisqa `session_scope()` ichida bajariladi va
sessiya DARHOL yopiladi; keyingi ish faqat Redis bilan boradi.

## Mijoz xabarlarining IKKI shakli

Shartnomadagi shakl — `{"action": "subscribe", "job_ids": [...]}`
(`WsSubscribeMessage`). Lekin ALLAQACHON yozilgan frontend
(`frontend/src/lib/websocket.ts`) boshqa shaklni yuboradi:
`{"type": "subscribe", "data": {"job_id": "..."}}` va
`{"type": "ping", "data": null, "timestamp": "..."}`. Ikkisi ham qabul
qilinadi: `_normalize_client_message()` kelgan xabarni schema shakliga
keltiradi. Bu ataylab qilingan murosa — ishlab turgan mijozni buzish
shartnomaning harfiga rioya qilishdan qimmatroq.

## Hodisa turlari

Pub/Sub kanalida ikki xil tana uchraydi:

* **job holati** — `serializers.job_event_payload(job)` (tekis lug'at,
  `type` maydoni YO'Q). Turi holatdan hisoblanadi (`job.succeeded`...);
* **log qatori** — `{"type": "job.log", "data": {...}}` (allaqachon
  konvertda).

Ikkisi ham `WsEvent` ga keltiriladi, shuning uchun mijoz yagona shaklni
ko'radi.

## Yetkazish kafolati

Pub/Sub — **eng ko'pi bir marta**: ulanish uzilgan paytdagi hodisalar
yo'qoladi. Shuning uchun WebSocket hech qachon yagona haqiqat manbai
emas; mijoz qayta ulangach holatni REST orqali qayta o'qiydi (frontend
`useLiveJobs` aynan shunday qiladi).
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from fastapi import APIRouter
from pydantic import ValidationError as PydanticValidationError
from redis.exceptions import RedisError
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from app.config import settings
from app.constants import JobStatus, RedisKeys, WebhookEvent
from app.database import session_scope
from app.dependencies import RedisDep, get_ws_user
from app.exceptions import DurablError, ValidationError
from app.logging_config import get_logger
from app.schemas.websocket import (
    WS_TYPE_PONG,
    WS_TYPE_SUBSCRIBED,
    WsErrorMessage,
    WsEvent,
    WsSubscribeMessage,
)
from app.utils.serializers import dump_json, load_json

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi uchun
    from collections.abc import Mapping

    from app.models.user import User

logger = get_logger(__name__)

router = APIRouter(tags=["websocket"])

# ---------------------------------------------------------------------------
# Konstantalar
# ---------------------------------------------------------------------------

#: Yopilish kodlari (RFC 6455).
WS_CLOSE_NORMAL: Final = 1000
WS_CLOSE_POLICY_VIOLATION: Final = 1008
WS_CLOSE_INTERNAL_ERROR: Final = 1011
WS_CLOSE_TRY_AGAIN_LATER: Final = 1013

#: `close(reason=...)` RFC bo'yicha 123 baytdan oshmasligi kerak.
MAX_CLOSE_REASON_CHARS: Final = 120

#: Xizmat xabarlari turlari (frontend `WsEventType` bilan AYNI).
WS_TYPE_CONNECTED: Final = "connected"
WS_TYPE_PING: Final = "ping"

#: `WebhookEvent` da nomi bo'lmagan holatlar uchun tur prefiksi
#: (`job.pending`, `job.retrying`) — qiymat `JobStatus` dan olinadi.
JOB_EVENT_PREFIX: Final = "job."

#: Mijozga qaytariladigan xato kodlari.
WS_ERROR_CONNECTION_LIMIT: Final = "ws_connection_limit"
WS_ERROR_INVALID_JSON: Final = "ws_invalid_json"
WS_ERROR_INVALID_MESSAGE: Final = "ws_invalid_message"

#: Pub/Sub ni kutish qadami (soniya). Mijoz xabarlari va heartbeat
#: alohida vazifalarda ishlaydi, shuning uchun bu qiymat faqat
#: "hodisa yo'q" holatining tekshirilish tezligini belgilaydi.
EVENT_POLL_SECONDS: Final = 1.0

#: Bo'sh poll'dan keyin minimal pauza. Ba'zi klientlar (fakeredis)
#: `get_message(timeout=...)` ni darhol qaytaradi — pauza bo'lmasa
#: halqa protsessorni bo'sh aylantirib bo'g'ib qo'yardi.
IDLE_PAUSE_SECONDS: Final = 0.01

#: Heartbeat davriyligining eng kichik qiymati (sozlama nolga qo'yilsa
#: server o'zini "ping toshqini" bilan bo'g'ib qo'ymasligi uchun).
MIN_HEARTBEAT_SECONDS: Final = 1.0

#: ASGI xabar turlari (starlette ularni konstanta sifatida eksport qilmaydi).
ASGI_DISCONNECT: Final = "websocket.disconnect"

#: Job holati -> mijoz ko'radigan hodisa turi.
JOB_EVENT_TYPES: Final[dict[JobStatus, str]] = {
    JobStatus.QUEUED: WebhookEvent.JOB_QUEUED.value,
    JobStatus.RUNNING: WebhookEvent.JOB_STARTED.value,
    JobStatus.SUCCESS: WebhookEvent.JOB_SUCCEEDED.value,
    JobStatus.FAILED: WebhookEvent.JOB_FAILED.value,
    JobStatus.CANCELLED: WebhookEvent.JOB_CANCELLED.value,
    JobStatus.DEAD_LETTER: WebhookEvent.JOB_DEAD_LETTERED.value,
}


# ---------------------------------------------------------------------------
# Ulanishlar reestri
# ---------------------------------------------------------------------------


class ConnectionManager:
    """Foydalanuvchi bo'yicha WebSocket ulanishlarini boshqaradi.

    Reestr PROTSESS ichida: bir nechta API nusxasi ishlayotganda har biri
    o'z ulanishlarini biladi. Shu sababli limit ham protsess kesimida
    qo'llanadi — taqsimlangan hisoblagich (Redis) bu yerda ATAYLAB
    ishlatilmagan: u har ulanish uchun qo'shimcha so'rov va "uzilib qolgan
    hisoblagichni tozalash" muammosini keltirardi, foyda esa kichik
    (limit — suiiste'moldan himoya, aniq kvota emas).

    Hodisalar har ulanish uchun ALOHIDA Pub/Sub obunasi orqali keladi
    (`jobs_stream`), shuning uchun `broadcast()` faqat protsess ichidagi
    qo'shimcha yo'l (test va kelajakdagi tizim xabarlari uchun).
    """

    def __init__(self, *, max_per_user: int | None = None) -> None:
        """Reestrni yaratadi.

        Args:
            max_per_user: Foydalanuvchiga ruxsat etilgan ulanishlar soni.
                `None` — `settings.WS_MAX_CONNECTIONS_PER_USER` o'qiladi
                (test sozlamani almashtirishi mumkin).
        """
        self._connections: dict[str, set[WebSocket]] = {}
        self._max_per_user = max_per_user
        self._lock = asyncio.Lock()

    @property
    def max_per_user(self) -> int:
        """Amaldagi ulanish limiti."""
        if self._max_per_user is not None:
            return self._max_per_user
        return int(settings.WS_MAX_CONNECTIONS_PER_USER)

    async def connect(self, user_id: uuid.UUID | str, websocket: WebSocket) -> bool:
        """Ulanishni reestrga qo'shadi.

        Ulanishni QABUL QILMAYDI (`accept()`) — bu endpoint'ning ishi,
        chunki xato xabarini yuborish uchun qabul qilish autentifikatsiyadan
        oldin bajariladi.

        Returns:
            `True` — qo'shildi; `False` — limit oshdi (chaqiruvchi
            `close(1013)` qiladi).
        """
        key = str(user_id)
        async with self._lock:
            bucket = self._connections.setdefault(key, set())
            if len(bucket) >= self.max_per_user:
                if not bucket:  # pragma: no cover - limit 0 bo'lgan holat
                    self._connections.pop(key, None)
                return False
            bucket.add(websocket)
            return True

    def disconnect(self, user_id: uuid.UUID | str, websocket: WebSocket) -> None:
        """Ulanishni reestrdan olib tashlaydi (bo'sh to'plam ham o'chadi)."""
        key = str(user_id)
        bucket = self._connections.get(key)
        if bucket is None:
            return
        bucket.discard(websocket)
        if not bucket:
            self._connections.pop(key, None)

    async def broadcast(self, user_id: uuid.UUID | str, message: dict[str, Any]) -> None:
        """Xabarni foydalanuvchining BARCHA protsess ichidagi ulanishlariga yuboradi.

        Yuborilmagan (uzilgan) ulanish reestrdan olib tashlanadi — aks
        holda o'lik socket limitni band qilib turardi.
        """
        key = str(user_id)
        payload = dump_json(message)
        for websocket in list(self._connections.get(key, ())):
            try:
                await websocket.send_text(payload)
            except (WebSocketDisconnect, RuntimeError, OSError) as exc:
                logger.debug("ws.broadcast_failed", user_id=key, error=str(exc))
                self.disconnect(user_id, websocket)

    def count(self, user_id: uuid.UUID | str | None = None) -> int:
        """Ochiq ulanishlar soni (`user_id` berilmasa — hammasi)."""
        if user_id is None:
            return sum(len(bucket) for bucket in self._connections.values())
        return len(self._connections.get(str(user_id), ()))


#: Protsess bo'yicha yagona reestr.
manager = ConnectionManager()


# ---------------------------------------------------------------------------
# Obuna holati
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _SubscriptionState:
    """Mijozning joriy filtri (`subscribe`/`unsubscribe` bilan boshqariladi).

    `None` — "filtr yo'q", ya'ni foydalanuvchining barcha hodisalari
    uzatiladi (standart holat).
    """

    job_ids: set[str] | None = None
    events: set[str] | None = None

    def apply(self, message: WsSubscribeMessage) -> None:
        """Yangi filtrni o'rnatadi (oldingisini almashtiradi)."""
        self.job_ids = {str(item) for item in message.job_ids} if message.job_ids else None
        self.events = {str(item) for item in message.events} if message.events else None

    def reset(self) -> None:
        """Filtrni bekor qiladi — hamma hodisa yana uzatiladi."""
        self.job_ids = None
        self.events = None

    def matches(self, event: WsEvent) -> bool:
        """Hodisa joriy filtrdan o'tadimi?"""
        if self.events is not None and event.type not in self.events:
            return False
        if self.job_ids is None:
            return True
        job_id = event.data.get("job_id")
        return job_id is not None and str(job_id) in self.job_ids

    def describe(self) -> dict[str, Any]:
        """Mijozga tasdiq sifatida qaytariladigan joriy filtr."""
        return {
            "job_ids": sorted(self.job_ids) if self.job_ids else None,
            "events": sorted(self.events) if self.events else None,
        }


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.websocket("/jobs")
async def jobs_stream(websocket: WebSocket, redis: RedisDep) -> None:
    """Job hodisalarining real-time oqimi (`/ws/jobs?token=<jwt>`).

    Ikki yo'nalish parallel ishlaydi: Redis -> mijoz (hodisalar) va
    mijoz -> server (`ping`, `subscribe`, `unsubscribe`), ularga server
    heartbeat'i qo'shiladi. Biri tugashi (yoki uzilishi) bilan
    qolganlari bekor qilinadi va resurslar `finally` da tozalanadi.
    """
    await websocket.accept()
    user = await _authenticate(websocket)
    if user is None:
        return

    if not await manager.connect(user.id, websocket):
        logger.info("ws.connection_limit", user_id=str(user.id), limit=manager.max_per_user)
        await _send_error(
            websocket,
            WS_ERROR_CONNECTION_LIMIT,
            "Bir vaqtda ruxsat etilgan ulanishlar soni oshdi",
            details={"limit": manager.max_per_user},
        )
        await _close_quietly(websocket, WS_CLOSE_TRY_AGAIN_LATER, "Ulanish limiti")
        return

    channel = RedisKeys.events_user(user.id)
    pubsub = redis.pubsub()
    state = _SubscriptionState()
    try:
        await pubsub.subscribe(channel)
        logger.info("ws.connected", user_id=str(user.id), connections=manager.count(user.id))
        await _send_event(
            websocket,
            WsEvent(type=WS_TYPE_CONNECTED, data={"user_id": str(user.id)}),
        )
        await _run_pumps(websocket, pubsub, state)
        await _close_quietly(websocket, WS_CLOSE_NORMAL)
    except WebSocketDisconnect as exc:
        #: Mijozning uzilishi — NORMAL holat (sahifa yopildi, tarmoq
        #: almashdi). `exception` bilan log qilish monitoringni soxta
        #: xatolar bilan to'ldirardi.
        logger.debug("ws.disconnected", user_id=str(user.id), code=exc.code)
    except RedisError as exc:
        logger.warning("ws.redis_error", user_id=str(user.id), error=str(exc))
        await _close_quietly(websocket, WS_CLOSE_INTERNAL_ERROR, "Hodisa kanali mavjud emas")
    finally:
        manager.disconnect(user.id, websocket)
        with contextlib.suppress(Exception):
            await pubsub.unsubscribe(channel)
        with contextlib.suppress(Exception):
            await pubsub.aclose()


# ---------------------------------------------------------------------------
# Autentifikatsiya
# ---------------------------------------------------------------------------


async def _authenticate(websocket: WebSocket) -> User | None:
    """Tokendan foydalanuvchini aniqlaydi; xato bo'lsa ulanishni yopadi.

    `get_ws_user` ATAYLAB `WebSocketException` tashlamaydi (WebSocket
    uchun FastAPI exception handler'lari ishlamaydi), shuning uchun domen
    xatosini shu yerda tutib mijozga tushunarli kod va xabar yuboriladi.

    Returns:
        Foydalanuvchi yoki `None` (ulanish allaqachon yopilgan).
    """
    try:
        async with session_scope() as session:
            return await get_ws_user(websocket, session)
    except DurablError as exc:
        logger.debug("ws.auth_failed", code=exc.code)
        await _send_error(websocket, exc.code, exc.message, details=exc.details or None)
        await _close_quietly(websocket, WS_CLOSE_POLICY_VIOLATION, exc.message)
        return None


# ---------------------------------------------------------------------------
# Yo'nalishlar (pump'lar)
# ---------------------------------------------------------------------------


async def _run_pumps(
    websocket: WebSocket,
    pubsub: Any,
    state: _SubscriptionState,
) -> None:
    """Uch vazifani parallel boshqaradi; biri tugasa qolganini bekor qiladi.

    `asyncio.wait(FIRST_COMPLETED)` ishlatiladi: `TaskGroup` birinchi
    xatoda qolganlarini bekor qilardi, lekin NORMAL tugash (mijoz uzildi)
    ham shu yerda "tugash" hisoblanadi va u xato emas.

    Raises:
        Exception: Birinchi tugagan vazifaning xatosi (odatda
            `WebSocketDisconnect`) chaqiruvchiga uzatiladi.
    """
    tasks = {
        asyncio.create_task(_pump_events(websocket, pubsub, state), name="ws-events"),
        asyncio.create_task(_pump_client(websocket, state), name="ws-client"),
        asyncio.create_task(_pump_heartbeat(websocket), name="ws-heartbeat"),
    }
    try:
        done, _pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        #: Bekor qilish TUGAGANIGA ishonch: aks holda vazifa yopilgan
        #: socket'ga yozishga urinib "Task was destroyed" ogohlantirishi
        #: chiqardi.
        await asyncio.gather(*tasks, return_exceptions=True)

    for task in done:
        error = task.exception()
        if error is not None:
            raise error


async def _pump_events(
    websocket: WebSocket,
    pubsub: Any,
    state: _SubscriptionState,
) -> None:
    """Redis Pub/Sub -> mijoz yo'nalishi."""
    while True:
        message = await pubsub.get_message(
            ignore_subscribe_messages=True, timeout=EVENT_POLL_SECONDS
        )
        if message is None:
            await asyncio.sleep(IDLE_PAUSE_SECONDS)
            continue
        event = _parse_channel_message(message)
        if event is None or not state.matches(event):
            continue
        await _send_event(websocket, event)


async def _pump_client(websocket: WebSocket, state: _SubscriptionState) -> None:
    """Mijoz -> server yo'nalishi (`ping`, `subscribe`, `unsubscribe`)."""
    while True:
        message = await websocket.receive()
        if message.get("type") == ASGI_DISCONNECT:
            raise WebSocketDisconnect(code=int(message.get("code") or WS_CLOSE_NORMAL))
        raw = _message_text(message)
        if raw:
            await _handle_client_message(websocket, state, raw)


async def _pump_heartbeat(websocket: WebSocket) -> None:
    """Davriy server `ping` — proxy "jim" ulanishni uzib qo'ymasligi uchun."""
    interval = max(MIN_HEARTBEAT_SECONDS, float(settings.WS_HEARTBEAT_INTERVAL_SECONDS))
    while True:
        await asyncio.sleep(interval)
        await _send_event(websocket, WsEvent(type=WS_TYPE_PING))


# ---------------------------------------------------------------------------
# Mijoz xabarlari
# ---------------------------------------------------------------------------


async def _handle_client_message(
    websocket: WebSocket,
    state: _SubscriptionState,
    raw: str,
) -> None:
    """Mijoz xabarini tahlil qiladi va javob yuboradi."""
    try:
        payload = load_json(raw)
    except ValidationError:
        await _send_error(websocket, WS_ERROR_INVALID_JSON, "Xabar yaroqli JSON emas")
        return
    if not isinstance(payload, dict):
        await _send_error(websocket, WS_ERROR_INVALID_JSON, "Xabar JSON obyekti bo'lishi kerak")
        return

    try:
        message = WsSubscribeMessage.model_validate(_normalize_client_message(payload))
    except PydanticValidationError as exc:
        await _send_error(
            websocket,
            WS_ERROR_INVALID_MESSAGE,
            "Xabar shakli noto'g'ri: `action` qiymati `subscribe`, "
            "`unsubscribe` yoki `ping` bo'lishi kerak",
            details={"errors": exc.error_count()},
        )
        return

    if message.action == "ping":
        await _send_event(websocket, WsEvent(type=WS_TYPE_PONG))
        return

    if message.action == "subscribe":
        state.apply(message)
    else:
        state.reset()
    await _send_event(websocket, WsEvent(type=WS_TYPE_SUBSCRIBED, data=state.describe()))


def _normalize_client_message(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Mijoz xabarini `WsSubscribeMessage` shakliga keltiradi.

    Qabul qilinadigan shakllar:

    * shartnoma: `{"action": "subscribe", "job_ids": [...]}`;
    * frontend: `{"type": "subscribe", "data": {"job_id": "..."}}`;
    * frontend heartbeat: `{"type": "ping", "data": null, "timestamp": ...}`.

    `ping` da filtrlar OLIB TASHLANADI: schema ularni taqiqlaydi
    (`_check_action`), frontend esa `data`/`timestamp` ni baribir
    yuboradi.
    """
    action = payload.get("action") or payload.get("type")
    body = payload.get("data")
    nested: Mapping[str, Any] = body if isinstance(body, dict) else {}

    normalized: dict[str, Any] = {"action": action}
    if action == "ping":
        return normalized

    job_ids = payload.get("job_ids") or nested.get("job_ids")
    if job_ids is None:
        single = payload.get("job_id") or nested.get("job_id")
        if single is not None:
            job_ids = [single]
    events = payload.get("events") or nested.get("events")

    if job_ids is not None:
        normalized["job_ids"] = job_ids
    if events is not None:
        normalized["events"] = events
    return normalized


def _message_text(message: Mapping[str, Any]) -> str | None:
    """ASGI `websocket.receive` xabaridan matnni ajratadi.

    Ikkilik (`bytes`) freym ham qabul qilinadi: protokol faqat matn
    ishlatadi, lekin ba'zi mijozlar JSON'ni `Blob` sifatida yuboradi —
    xabarni jimgina tashlab yuborish diagnostikasi qiyin xatolikka
    olib kelardi.
    """
    text = message.get("text")
    if isinstance(text, str):
        return text
    raw = message.get("bytes")
    if isinstance(raw, bytes | bytearray):
        return bytes(raw).decode("utf-8", errors="replace")
    return None


# ---------------------------------------------------------------------------
# Hodisalar
# ---------------------------------------------------------------------------


def _parse_channel_message(message: Mapping[str, Any]) -> WsEvent | None:
    """Pub/Sub xabarini `WsEvent` ga aylantiradi; yaroqsiz bo'lsa `None`."""
    try:
        raw = load_json(message.get("data"))
    except ValidationError as exc:
        logger.debug("ws.event_not_json", error=exc.message)
        return None
    if not isinstance(raw, dict):
        return None

    body = raw.get("data")
    if isinstance(raw.get("type"), str) and isinstance(body, dict):
        #: Allaqachon konvertda (`job.log` kabi).
        return WsEvent(type=str(raw["type"]), data=body)
    return WsEvent(type=_event_type_for_status(raw.get("status")), data=raw)


def _event_type_for_status(status: Any) -> str:
    """Job holatidan mijoz ko'radigan hodisa turini hisoblaydi.

    `WebhookEvent` da nomi bo'lmagan holatlar (`pending`, `retrying`)
    uchun tur `JobStatus` qiymatidan yasaladi (`job.retrying`) — bu
    frontend `WsEventType` ro'yxatidagi nomlarga mos tushadi.
    """
    try:
        resolved = JobStatus(status)
    except ValueError:
        logger.debug("ws.unknown_status", status=str(status))
        return f"{JOB_EVENT_PREFIX}unknown"
    return JOB_EVENT_TYPES.get(resolved, f"{JOB_EVENT_PREFIX}{resolved.value}")


# ---------------------------------------------------------------------------
# Yuborish yordamchilari
# ---------------------------------------------------------------------------


async def _send_event(websocket: WebSocket, event: WsEvent) -> None:
    """Hodisani `{type, data, timestamp}` konvertida yuboradi."""
    await websocket.send_text(event.model_dump_json())


async def _send_error(
    websocket: WebSocket,
    code: str,
    message: str,
    *,
    details: dict[str, Any] | None = None,
) -> None:
    """Xato xabarini yuboradi (yuborilmasa jim yutiladi).

    Xato aytib bo'lmasligi ulanishni yopishga xalaqit bermasligi kerak,
    shuning uchun transport xatolari bu yerda to'xtatiladi.
    """
    payload = WsErrorMessage(code=code, message=message, details=details)
    with contextlib.suppress(WebSocketDisconnect, RuntimeError, OSError):
        await websocket.send_text(payload.model_dump_json())


async def _close_quietly(websocket: WebSocket, code: int, reason: str = "") -> None:
    """Ulanishni yopadi; allaqachon yopilgan bo'lsa hech narsa qilmaydi."""
    if websocket.client_state is WebSocketState.DISCONNECTED:
        return
    with contextlib.suppress(WebSocketDisconnect, RuntimeError, OSError):
        await websocket.close(code=code, reason=reason[:MAX_CLOSE_REASON_CHARS])


__all__ = ["ConnectionManager", "manager", "router"]
