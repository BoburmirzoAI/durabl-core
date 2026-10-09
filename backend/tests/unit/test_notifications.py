"""Durabl — `app/services/notification_service.py` birlik testlari.

## Nega bu servis alohida tekshiriladi

`NotificationService` operatorga yetib boradigan YAGONA kanal, lekin test
muhitida `NOTIFICATIONS_ENABLED=false` — ya'ni integratsiya testlari uning
faqat "o'chirilgan" yo'lini bosib o'tadi. Shu tufayli bo'g'ish (throttle)
mantig'i, Slack tanasining shakli va HTTP xatosini yutish xulq-atvori hech
qaerda qoplanmay qolardi. Aynan shu uch narsa muhim:

* **bo'g'ish** — `DlqProcessor` har 30 soniyada chaqiradi, bo'g'ish
  ishlamasa operator spam oladi va haqiqiy alertni ko'rmaydi;
* **xatoni yutish** — alert yiqilsa asosiy ish (job bajarish) TO'XTAMASLIGI
  kerak, shuning uchun `alert()` hech qachon istisno tashlamaydi;
* **maxfiylik** — `ALERT_WEBHOOK_URL` yo'lida Slack tokeni bo'ladi, logga
  faqat host yozilishi kerak.

## Nega `reset_throttle()` har testda chaqiriladi

`_THROTTLE` lug'ati MODUL darajasida (protsess bo'yicha global), ya'ni
testlar bir-birining bo'g'ish holatini ko'radi. `autouse` fixture uni
har testdan oldin va keyin tozalaydi.
"""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import respx
from app.config import settings
from app.constants import Priority
from app.services.notification_service import (
    THROTTLE_WINDOW_SECONDS,
    AlertLevel,
    NotificationService,
    _safe_host,
    reset_throttle,
    throttle_remaining,
)

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from collections.abc import Iterator

pytestmark = pytest.mark.unit

#: Testlarda ishlatiladigan soxta Slack webhook'i (yo'lida "token" bor).
ALERT_URL = "https://hooks.example.test/services/T000/B000/juda-maxfiy-token"


@pytest.fixture(autouse=True)
def clean_throttle() -> Iterator[None]:
    """Global bo'g'ish lug'atini har test uchun tozalaydi."""
    reset_throttle()
    yield
    reset_throttle()


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bildirishnomalarni yoqadi va soxta webhook manzilini qo'yadi."""
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(settings, "ALERT_WEBHOOK_URL", ALERT_URL)


# ---------------------------------------------------------------------------
# Bo'g'ish
# ---------------------------------------------------------------------------


async def test_alert_is_throttled_for_repeated_key(enabled: None) -> None:
    """AYNI kalit bilan ikkinchi alert YUBORILMAYDI (operator spam olmaydi)."""
    service = NotificationService()
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(ALERT_URL).mock(return_value=httpx.Response(200))

        first = await service.alert("DLQ to'ldi", "chuqurlik 150", throttle_key="dlq")
        second = await service.alert("DLQ to'ldi", "chuqurlik 151", throttle_key="dlq")

    assert first is True
    assert second is False
    # Faqat BITTA HTTP so'rov ketdi.
    assert route.call_count == 1


async def test_throttle_is_per_key(enabled: None) -> None:
    """Turli kalitlar bir-birini bo'g'maydi (har worker uchun alohida oyna)."""
    service = NotificationService()
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(ALERT_URL).mock(return_value=httpx.Response(200))

        assert await service.alert("Worker o'ldi", "a", throttle_key="worker:a") is True
        assert await service.alert("Worker o'ldi", "b", throttle_key="worker:b") is True

    assert route.call_count == 2


async def test_throttle_remaining_reports_window(enabled: None) -> None:
    """`throttle_remaining()` qolgan vaqtni qaytaradi, `reset_throttle()` nollaydi."""
    service = NotificationService()
    with respx.mock(assert_all_called=False) as mock:
        mock.post(ALERT_URL).mock(return_value=httpx.Response(200))
        await service.alert("Sarlavha", "tana", throttle_key="kalit")

    remaining = throttle_remaining("kalit")
    assert 0 < remaining <= THROTTLE_WINDOW_SECONDS
    assert throttle_remaining("boshqa-kalit") == 0.0

    reset_throttle("kalit")
    assert throttle_remaining("kalit") == 0.0


async def test_default_throttle_key_uses_level_and_title(enabled: None) -> None:
    """`throttle_key` berilmasa kalit `<level>:<title>` dan yasaladi."""
    service = NotificationService()
    with respx.mock(assert_all_called=False) as mock:
        mock.post(ALERT_URL).mock(return_value=httpx.Response(200))
        await service.alert("Navbat to'ldi", "tana", level=AlertLevel.CRITICAL.value)

    assert throttle_remaining(f"{AlertLevel.CRITICAL.value}:Navbat to'ldi") > 0


# ---------------------------------------------------------------------------
# O'chirilgan va sozlanmagan holatlar
# ---------------------------------------------------------------------------


async def test_alert_returns_false_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """`NOTIFICATIONS_ENABLED=False` -> HTTP so'rov YO'Q, lekin xato ham yo'q."""
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", False)
    monkeypatch.setattr(settings, "ALERT_WEBHOOK_URL", ALERT_URL)

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(ALERT_URL).mock(return_value=httpx.Response(200))
        assert await NotificationService().alert("Sarlavha", "tana") is False

    assert route.call_count == 0


async def test_alert_returns_false_without_webhook_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Manzil sozlanmagan bo'lsa ham servis jim `False` qaytaradi."""
    monkeypatch.setattr(settings, "NOTIFICATIONS_ENABLED", True)
    monkeypatch.setattr(settings, "ALERT_WEBHOOK_URL", "")

    assert await NotificationService().alert("Sarlavha", "tana") is False


# ---------------------------------------------------------------------------
# HTTP xatolari — alert asosiy ishni YIQITMAYDI
# ---------------------------------------------------------------------------


async def test_alert_swallows_transport_error(enabled: None) -> None:
    """Tarmoq xatosi istisno TASHLAMAYDI, `False` qaytadi."""
    with respx.mock(assert_all_called=False) as mock:
        mock.post(ALERT_URL).mock(side_effect=httpx.ConnectError("ulanmadi"))

        assert await NotificationService().alert("Sarlavha", "tana") is False


async def test_alert_treats_non_2xx_as_failure(enabled: None) -> None:
    """Qabul qiluvchi 500 bersa — `False` (lekin istisno yo'q)."""
    with respx.mock(assert_all_called=False) as mock:
        mock.post(ALERT_URL).mock(return_value=httpx.Response(500, text="xato"))

        assert await NotificationService().alert("Sarlavha", "tana") is False


# ---------------------------------------------------------------------------
# Slack tanasining shakli
# ---------------------------------------------------------------------------


async def test_slack_payload_shape(enabled: None) -> None:
    """Tana Slack "Incoming Webhook" shaklida: `text` + bitta `attachment`."""
    captured: dict[str, Any] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200)

    with respx.mock(assert_all_called=False) as mock:
        mock.post(ALERT_URL).mock(side_effect=capture)
        await NotificationService().alert(
            "DLQ chuqurligi oshdi",
            "Chuqurlik 150 ga yetdi",
            level=AlertLevel.CRITICAL.value,
            context={"depth": 150, "threshold": 100},
        )

    assert settings.APP_NAME in captured["text"]
    assert "CRITICAL" in captured["text"]
    attachment = captured["attachments"][0]
    assert attachment["title"] == "DLQ chuqurligi oshdi"
    assert attachment["text"] == "Chuqurlik 150 ga yetdi"
    # `context` Slack `fields` ga aylanadi (har biri `short`).
    assert {field["title"] for field in attachment["fields"]} == {"depth", "threshold"}
    assert all(field["short"] is True for field in attachment["fields"])
    assert isinstance(attachment["ts"], int)


async def test_unknown_level_falls_back_to_default(enabled: None) -> None:
    """Noma'lum daraja standart (`warning`) ga tushadi — istisno yo'q."""
    captured: dict[str, Any] = {}

    def capture(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(200)

    with respx.mock(assert_all_called=False) as mock:
        mock.post(ALERT_URL).mock(side_effect=capture)
        await NotificationService().alert("Sarlavha", "tana", level="bunday-daraja-yoq")

    assert AlertLevel.WARNING.value.upper() in captured["text"]


# ---------------------------------------------------------------------------
# Domenga xos bildirishnomalar
# ---------------------------------------------------------------------------


async def test_notify_helpers_send_one_alert_each(enabled: None) -> None:
    """Beshta `notify_*` metodi beshta ALOHIDA alert yuboradi.

    Har biri o'z `throttle_key` ini ishlatadi, shuning uchun biri
    ikkinchisini bo'g'ib qo'ymaydi.
    """
    service = NotificationService()
    user_id = uuid.uuid4()

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(ALERT_URL).mock(return_value=httpx.Response(200))

        await service.notify_dlq_threshold(150, user_id=user_id)
        await service.notify_worker_down("worker-1")
        await service.notify_queue_backlog(5_000, priority=Priority.HIGH)
        await service.notify_webhook_disabled("https://mijoz.example.test/hook", user_id=user_id)
        await service.notify_quota_exceeded(user_id, plan="free", used=1_200, limit=1_000)

    assert route.call_count == 5


async def test_notify_worker_down_is_throttled_per_worker(enabled: None) -> None:
    """Ayni worker uchun takroriy ogohlantirish bo'g'iladi, boshqasi uchun — yo'q."""
    service = NotificationService()
    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(ALERT_URL).mock(return_value=httpx.Response(200))

        await service.notify_worker_down("worker-1")
        await service.notify_worker_down("worker-1")
        await service.notify_worker_down("worker-2")

    assert route.call_count == 2


# ---------------------------------------------------------------------------
# Maxfiylik
# ---------------------------------------------------------------------------


def test_safe_host_hides_webhook_token() -> None:
    """Logga faqat host yoziladi — yo'ldagi maxfiy token oshkor bo'lmaydi."""
    assert _safe_host(ALERT_URL) == "hooks.example.test"
    assert "token" not in _safe_host(ALERT_URL)
    assert _safe_host(None) == "-"
    assert _safe_host("") == "-"


__all__ = ["ALERT_URL"]
