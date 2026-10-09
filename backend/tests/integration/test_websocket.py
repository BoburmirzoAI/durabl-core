"""Durabl — `WS /ws/jobs` integratsiya testlari.

## Nega bu fayl `client` fixture'ini ISHLATMAYDI

WebSocket'ni ASGI orqali sinash uchun ikki yo'nalish (server -> mijoz va
mijoz -> server) AYNI hodisa halqasida ishlashi kerak. `httpx.AsyncClient`
WebSocket'ni qo'llab-quvvatlamaydi, shuning uchun starlette'ning
`TestClient` i ishlatiladi — u o'z portalida (alohida thread) hodisa
halqasini yuritadi va `conftest.py` ning async fixture'lari bilan ayni
halqani BAHAM KO'RMAYDI. Shu sababli modul infratuzilmani o'zi quradi:
engine, fakeredis va foydalanuvchi.

## Nega fakeredis `FakeServer` baham ko'riladi

Server tomoni ASYNC klient (`fakeredis.aioredis.FakeRedis`) bilan obuna
bo'ladi, test esa hodisani SINXRON klient bilan e'lon qiladi. Ikkisi BITTA
`FakeServer()` nusxasiga bog'lansa `publish()` async obunachiga yetib
boradi — alohida thread yoki `asyncio` ko'prigi kerak emas.

## Nega `with` blokining oxirida OCHIQ `close()` + kichik `sleep()`

`TestClient.websocket_connect` konteksti chiqishda portalning
`CancelScope` ini DARHOL bekor qiladi va hodisa halqasiga navbat
bermaydi. Natijada server handler'i `finally` dagi `await` nuqtasida
bekor qilinadi va test `CancelledError` bilan yiqiladi. Bu ilova xatosi
EMAS (uvicorn handler tugashini kutadi), shuning uchun har test
`_finish()` bilan yakunlanadi: ochiq `close(1000)` va qisqa pauza.
"""

from __future__ import annotations

import time
import uuid
from typing import TYPE_CHECKING, Any

import fakeredis
import fakeredis.aioredis
import pytest
from app.config import settings
from app.constants import JobStatus, RedisKeys
from app.database import create_engine, set_engine
from app.main import create_app
from app.redis_client import set_redis
from app.schemas.websocket import WS_TYPE_ERROR, WS_TYPE_PONG, WS_TYPE_SUBSCRIBED
from app.utils.serializers import dump_json
from starlette.testclient import TestClient

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from collections.abc import Iterator

    from starlette.testclient import WebSocketTestSession

pytestmark = pytest.mark.integration

#: `.test` TLD `email-validator` tomonidan rad etiladi (RFC 2606
#: "special-use"), shuning uchun HTTP orqali ro'yxatdan o'tadigan
#: foydalanuvchi `@durabl.dev` domenida bo'lishi SHART.
WS_EMAIL = "ws@durabl.dev"
WS_PASSWORD = "Parol12345"

#: Ulanish yopilgandan keyin serverga tozalanish uchun beriladigan vaqt.
TEARDOWN_PAUSE_SECONDS = 0.2


class WsEnv:
    """Test muhiti: HTTP mijoz, token, foydalanuvchi id va sinxron Redis."""

    def __init__(self, client: TestClient, token: str, user_id: str, redis: Any) -> None:
        self.client = client
        self.token = token
        self.user_id = user_id
        self.redis = redis

    @property
    def url(self) -> str:
        """Yaroqli token bilan WebSocket manzili."""
        return f"/ws/jobs?token={self.token}"

    def publish_job_event(self, job_id: str, status: JobStatus) -> None:
        """Foydalanuvchining kanaliga tekis job hodisasini e'lon qiladi.

        Tana ataylab `type` siz: `websocket._parse_channel_message()` turni
        `status` dan hisoblashi kerak (`success` -> `job.succeeded`).
        """
        self.redis.publish(
            RedisKeys.events_user(self.user_id),
            dump_json({"job_id": job_id, "status": status.value, "retry_count": 0}),
        )


@pytest.fixture
def ws_env() -> Iterator[WsEnv]:
    """Ko'tarilgan ilova + ro'yxatdan o'tgan foydalanuvchi + JWT.

    Foydalanuvchi bevosita DB'ga emas, HAQIQIY `POST /auth/register` orqali
    yaratiladi: shunda test sinxron bo'lib qoladi (`TestClient` ning
    portalidan tashqarida `await` qilish kerak emas) va yo'l-yo'lakay
    ro'yxatdan o'tish oqimi ham tekshiriladi.
    """
    server = fakeredis.FakeServer()
    set_redis(fakeredis.aioredis.FakeRedis(server=server, decode_responses=True))
    engine = create_engine()
    set_engine(engine)

    sync_redis = fakeredis.FakeStrictRedis(server=server, decode_responses=True)
    prefix = settings.API_V1_PREFIX
    try:
        # `TestClient` lifespan'ni ishga tushiradi -> `init_db(create_all=True)`.
        with TestClient(create_app()) as client:
            registered = client.post(
                f"{prefix}/auth/register",
                json={"email": WS_EMAIL, "password": WS_PASSWORD, "full_name": "WS User"},
            )
            assert registered.status_code == 201, registered.text
            user_id = registered.json()["id"]

            logged_in = client.post(
                f"{prefix}/auth/login",
                json={"email": WS_EMAIL, "password": WS_PASSWORD},
            )
            assert logged_in.status_code == 200, logged_in.text

            yield WsEnv(client, logged_in.json()["access_token"], user_id, sync_redis)
    finally:
        sync_redis.close()
        set_redis(None)
        set_engine(None)


def _finish(socket: WebSocketTestSession) -> None:
    """Ulanishni OCHIQ yopadi va serverga tozalanish uchun navbat beradi."""
    socket.close(1000)
    time.sleep(TEARDOWN_PAUSE_SECONDS)


def _receive(socket: WebSocketTestSession) -> dict[str, Any]:
    """Keyingi xabarni lug'at sifatida oladi."""
    payload = socket.receive_json()
    assert isinstance(payload, dict), payload
    return payload


# ---------------------------------------------------------------------------
# Ulanish va xizmat xabarlari
# ---------------------------------------------------------------------------


def test_connect_sends_connected_envelope(ws_env: WsEnv) -> None:
    """Yaroqli token -> birinchi xabar `connected` konvertida keladi."""
    with ws_env.client.websocket_connect(ws_env.url) as socket:
        first = _receive(socket)
        assert first["type"] == "connected"
        assert first["data"]["user_id"] == ws_env.user_id
        # Konvert shakli frontend `WsEvent` bilan AYNI.
        assert set(first) == {"type", "data", "timestamp"}
        _finish(socket)


def test_client_ping_gets_pong(ws_env: WsEnv) -> None:
    """Frontend shaklidagi `ping` (`{"type": ..., "data": null}`) -> `pong`."""
    with ws_env.client.websocket_connect(ws_env.url) as socket:
        _receive(socket)  # connected
        socket.send_json({"type": "ping", "data": None, "timestamp": 1})
        assert _receive(socket)["type"] == WS_TYPE_PONG
        _finish(socket)


def test_subscribe_accepts_frontend_shape(ws_env: WsEnv) -> None:
    """`{"type": "subscribe", "data": {"job_id": ...}}` qabul qilinadi."""
    job_id = str(uuid.uuid4())
    with ws_env.client.websocket_connect(ws_env.url) as socket:
        _receive(socket)
        socket.send_json({"type": "subscribe", "data": {"job_id": job_id}})
        confirmation = _receive(socket)
        assert confirmation["type"] == WS_TYPE_SUBSCRIBED
        assert confirmation["data"]["job_ids"] == [job_id]
        _finish(socket)


def test_subscribe_accepts_contract_shape(ws_env: WsEnv) -> None:
    """Shartnoma shakli (`action` + `job_ids`) ham ishlaydi."""
    job_ids = sorted(str(uuid.uuid4()) for _ in range(2))
    with ws_env.client.websocket_connect(ws_env.url) as socket:
        _receive(socket)
        socket.send_json({"action": "subscribe", "job_ids": job_ids})
        confirmation = _receive(socket)
        assert confirmation["type"] == WS_TYPE_SUBSCRIBED
        assert confirmation["data"]["job_ids"] == job_ids

        socket.send_json({"action": "unsubscribe"})
        reset = _receive(socket)
        assert reset["type"] == WS_TYPE_SUBSCRIBED
        assert reset["data"]["job_ids"] is None
        _finish(socket)


# ---------------------------------------------------------------------------
# Hodisalar
# ---------------------------------------------------------------------------


def test_job_event_is_forwarded_with_computed_type(ws_env: WsEnv) -> None:
    """Pub/Sub dagi TEKIS tana `job.succeeded` turiga aylanadi."""
    job_id = str(uuid.uuid4())
    with ws_env.client.websocket_connect(ws_env.url) as socket:
        _receive(socket)
        ws_env.publish_job_event(job_id, JobStatus.SUCCESS)
        event = _receive(socket)
        assert event["type"] == "job.succeeded"
        assert event["data"]["job_id"] == job_id
        _finish(socket)


def test_status_without_webhook_event_falls_back_to_prefix(ws_env: WsEnv) -> None:
    """`WebhookEvent` da nomi yo'q holat -> `job.<status>` (frontend taniydi)."""
    job_id = str(uuid.uuid4())
    with ws_env.client.websocket_connect(ws_env.url) as socket:
        _receive(socket)
        ws_env.publish_job_event(job_id, JobStatus.RETRYING)
        assert _receive(socket)["type"] == "job.retrying"
        _finish(socket)


def test_subscription_filter_drops_other_jobs(ws_env: WsEnv) -> None:
    """Obuna filtri boshqa job'ning hodisasini O'TKAZMAYDI."""
    wanted = str(uuid.uuid4())
    ignored = str(uuid.uuid4())
    with ws_env.client.websocket_connect(ws_env.url) as socket:
        _receive(socket)
        socket.send_json({"action": "subscribe", "job_ids": [wanted]})
        _receive(socket)  # subscribed

        ws_env.publish_job_event(ignored, JobStatus.SUCCESS)
        ws_env.publish_job_event(wanted, JobStatus.SUCCESS)

        event = _receive(socket)
        # Filtrdan O'TGAN yagona hodisa — kutilgan job.
        assert event["data"]["job_id"] == wanted
        _finish(socket)


def test_log_event_keeps_its_own_envelope(ws_env: WsEnv) -> None:
    """Kanalda allaqachon konvertda kelgan tana (`job.log`) o'zgarmaydi."""
    job_id = str(uuid.uuid4())
    with ws_env.client.websocket_connect(ws_env.url) as socket:
        _receive(socket)
        ws_env.redis.publish(
            RedisKeys.events_user(ws_env.user_id),
            dump_json({"type": "job.log", "data": {"job_id": job_id, "content": "salom"}}),
        )
        event = _receive(socket)
        assert event["type"] == "job.log"
        assert event["data"]["content"] == "salom"
        _finish(socket)


# ---------------------------------------------------------------------------
# Xato yo'llari
# ---------------------------------------------------------------------------


def test_invalid_json_returns_error_envelope(ws_env: WsEnv) -> None:
    """JSON bo'lmagan xabar -> `error` konverti, ulanish UZILMAYDI."""
    with ws_env.client.websocket_connect(ws_env.url) as socket:
        _receive(socket)
        socket.send_text("bu JSON emas")
        error = _receive(socket)
        assert error["type"] == WS_TYPE_ERROR
        assert error["code"] == "ws_invalid_json"

        # Ulanish tirik: keyingi `ping` hamon javob beradi.
        socket.send_json({"action": "ping"})
        assert _receive(socket)["type"] == WS_TYPE_PONG
        _finish(socket)


def test_unknown_action_returns_error_envelope(ws_env: WsEnv) -> None:
    """Noma'lum `action` -> `ws_invalid_message`."""
    with ws_env.client.websocket_connect(ws_env.url) as socket:
        _receive(socket)
        socket.send_json({"action": "nomalum"})
        error = _receive(socket)
        assert error["type"] == WS_TYPE_ERROR
        assert error["code"] == "ws_invalid_message"
        _finish(socket)


def test_invalid_token_is_closed_with_policy_violation(ws_env: WsEnv) -> None:
    """Yaroqsiz token -> `error` xabari + yopilish kodi 1008.

    Ulanish AVVAL qabul qilinadi (`accept()`), aks holda mijoz yopilish
    kodini umuman ko'rmay oddiy HTTP 403 olardi.
    """
    with ws_env.client.websocket_connect("/ws/jobs?token=buzilgan.token.qiymati") as socket:
        error = _receive(socket)
        assert error["type"] == WS_TYPE_ERROR
        assert error["code"] in {"INVALID_TOKEN", "AUTHENTICATION_REQUIRED"}
        closing = socket.receive()
        assert closing["type"] == "websocket.close"
        assert closing["code"] == 1008


def test_missing_token_is_rejected(ws_env: WsEnv) -> None:
    """Tokensiz ulanish ham 1008 bilan yopiladi."""
    with ws_env.client.websocket_connect("/ws/jobs") as socket:
        assert _receive(socket)["type"] == WS_TYPE_ERROR
        assert socket.receive()["code"] == 1008


def test_connection_limit_closes_with_try_again_later(
    ws_env: WsEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Limit oshsa ulanish 1013 (`try again later`) bilan yopiladi."""
    monkeypatch.setattr(settings, "WS_MAX_CONNECTIONS_PER_USER", 1)
    with ws_env.client.websocket_connect(ws_env.url) as first:
        assert _receive(first)["type"] == "connected"

        with ws_env.client.websocket_connect(ws_env.url) as second:
            error = _receive(second)
            assert error["type"] == WS_TYPE_ERROR
            assert error["code"] == "ws_connection_limit"
            assert error["details"]["limit"] == 1
            assert second.receive()["code"] == 1013

        _finish(first)


# ---------------------------------------------------------------------------
# Reestr
# ---------------------------------------------------------------------------


def test_registry_releases_connection_on_disconnect(ws_env: WsEnv) -> None:
    """Uzilgandan keyin ulanish reestrdan chiqadi (limit band qolmaydi)."""
    from app.api.v1.websocket import manager

    with ws_env.client.websocket_connect(ws_env.url) as socket:
        _receive(socket)
        assert manager.count(ws_env.user_id) == 1
        _finish(socket)

    assert manager.count(ws_env.user_id) == 0


__all__ = [
    "TEARDOWN_PAUSE_SECONDS",
    "WS_EMAIL",
    "WS_PASSWORD",
    "WsEnv",
    "ws_env",
]
