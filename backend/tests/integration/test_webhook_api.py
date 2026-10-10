"""Durabl — `/webhooks/*` endpointlarining integratsiya testlari.

## Nega `.invalid` domeni

`validate_webhook_url()` DNS yechishga urinadi va yechilgan IP ichki
bo'lsa URL'ni rad etadi. Testda tashqi tarmoqqa chiqmaslik uchun
`*.durabl-test.invalid` ishlatiladi: `.invalid` TLD hech qachon yechilmaydi
(RFC 2606), validator esa yechilmagan nom uchun fail-open qiladi
(`require_resolution=False`), ya'ni URL qabul qilinadi. Haqiqiy HTTP
chaqiruvi `respx` bilan ushlanadi, shuning uchun tarmoq umuman kerak emas.

## Xato javobidan KEYIN ORM obyektiga murojaat qilmaslik

`get_db()` dependency'si istisno chiqqanda `session.rollback()` qiladi.
SQLite xotira bazasi `StaticPool` bilan BITTA ulanishda yashagani uchun bu
rollback `db_session` dagi obyektlarni ham "eskirgan" (expired) qilib
qo'yadi. Shundan keyin `job.id` kabi oddiy murojaat DB'ga SO'ROV yuborishga
urinadi va sinxron kontekstda `MissingGreenlet` beradi.

Shuning uchun qoida: 4xx/5xx qaytaradigan so'rovdan OLDIN kerakli
qiymatlar (`str(obj.id)`) oddiy o'zgaruvchiga ko'chiriladi. Kerak bo'lsa
`await db_session.refresh(obj)` ham ishlaydi, lekin identifikatorni
oldindan olish — ancha sodda.

## Imzo tekshiruvi — eng muhim test

`verify_webhook_signature(body, signature, secret)` AYNAN yuborilgan
baytlar bilan ishlaydi. Shuning uchun `respx` callback'i `request.content`
ni to'liq saqlaydi: tanani qayta serializatsiya qilsak (masalan
`json.dumps(request.json())`) bo'shliqlar farq qilib imzo yiqilardi.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import httpx
import pytest
import respx
from app.constants import (
    HEADER_WEBHOOK_DELIVERY,
    HEADER_WEBHOOK_EVENT,
    HEADER_WEBHOOK_SIGNATURE,
    HEADER_WEBHOOK_TIMESTAMP,
    WebhookEvent,
)
from app.services.webhook_service import MAX_WEBHOOKS_PER_USER
from app.utils.security import verify_webhook_signature

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    from app.models.user import User
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

#: Testlarda ishlatiladigan (hech qachon yechilmaydigan) webhook manzili.
HOOK_URL = "https://hook.durabl-test.invalid/durabl"


def create_body(url: str = HOOK_URL, **overrides: Any) -> dict[str, Any]:
    """`POST /webhooks` uchun minimal tana."""
    body: dict[str, Any] = {"url": url, "events": [WebhookEvent.JOB_SUCCEEDED.value]}
    body.update(overrides)
    return body


async def create_webhook(
    client: httpx.AsyncClient,
    api_prefix: str,
    headers: dict[str, str],
    **overrides: Any,
) -> dict[str, Any]:
    """Webhook yaratadi va javob tanasini qaytaradi (`secret` bilan)."""
    response = await client.post(
        f"{api_prefix}/webhooks", headers=headers, json=create_body(**overrides)
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_returns_secret_once(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str], user: User
) -> None:
    """Yaratishda `secret` qaytadi; keyingi o'qishlarda U YO'Q."""
    created = await create_webhook(client, api_prefix, auth_headers)

    assert created["secret"].startswith("whsec_")
    assert created["user_id"] == str(user.id)
    assert created["is_active"] is True

    fetched = await client.get(f"{api_prefix}/webhooks/{created['id']}", headers=auth_headers)
    assert fetched.status_code == 200, fetched.text
    assert "secret" not in fetched.json()


async def test_localhost_url_rejected(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """SSRF himoyasi: `localhost` va cloud metadata manzili rad etiladi."""
    for url in ("http://localhost:9000/hook", "http://169.254.169.254/latest/meta-data"):
        response = await client.post(
            f"{api_prefix}/webhooks", headers=auth_headers, json=create_body(url)
        )
        assert response.status_code == 422, f"{url}: {response.text}"
        assert response.json()["error"]["code"] == "WEBHOOK_URL_NOT_ALLOWED"


async def test_list_and_update(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Ro'yxat sahifalangan; `PUT` hodisalar va holatni o'zgartiradi."""
    created = await create_webhook(client, api_prefix, auth_headers)

    listed = await client.get(f"{api_prefix}/webhooks", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    assert listed.json()["pagination"]["total"] == 1
    assert "secret" not in listed.json()["items"][0]

    updated = await client.put(
        f"{api_prefix}/webhooks/{created['id']}",
        headers=auth_headers,
        json={
            "events": [WebhookEvent.JOB_FAILED.value, WebhookEvent.JOB_DEAD_LETTERED.value],
            "is_active": False,
            "description": "Faqat xatolar",
        },
    )
    assert updated.status_code == 200, updated.text
    body = updated.json()
    assert set(body["events"]) == {
        WebhookEvent.JOB_FAILED.value,
        WebhookEvent.JOB_DEAD_LETTERED.value,
    }
    assert body["is_active"] is False
    assert body["description"] == "Faqat xatolar"


async def test_delete_removes_webhook(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """`DELETE` dan keyin webhook topilmaydi."""
    created = await create_webhook(client, api_prefix, auth_headers)

    deleted = await client.delete(f"{api_prefix}/webhooks/{created['id']}", headers=auth_headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["success"] is True

    missing = await client.get(f"{api_prefix}/webhooks/{created['id']}", headers=auth_headers)
    assert missing.status_code == 404, missing.text
    assert missing.json()["error"]["code"] == "WEBHOOK_NOT_FOUND"


async def test_test_endpoint_signs_payload(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """`POST /webhooks/{id}/test` imzolangan so'rov yuboradi va imzo TASDIQLANADI."""
    created = await create_webhook(client, api_prefix, auth_headers)
    captured: dict[str, Any] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        captured["headers"] = request.headers
        return httpx.Response(200, json={"received": True})

    with respx.mock(assert_all_called=True) as mock:
        mock.post(HOOK_URL).mock(side_effect=_handler)
        response = await client.post(
            f"{api_prefix}/webhooks/{created['id']}/test", headers=auth_headers, json={}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["status_code"] == 200

    headers = captured["headers"]
    assert headers[HEADER_WEBHOOK_EVENT] == WebhookEvent.JOB_SUCCEEDED.value
    assert uuid.UUID(headers[HEADER_WEBHOOK_DELIVERY])
    signature = headers[HEADER_WEBHOOK_SIGNATURE]
    # Imzo ichidagi `t=` header'dagi timestamp bilan AYNAN mos kelishi shart.
    assert f"t={headers[HEADER_WEBHOOK_TIMESTAMP]}," in signature
    assert verify_webhook_signature(captured["body"], signature, created["secret"]) is True
    # Boshqa kalit bilan imzo TASDIQLANMAYDI.
    assert verify_webhook_signature(captured["body"], signature, "whsec_boshqa") is False


async def test_deliveries_listed_after_test(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Sinov yuborishdan keyin delivery yozuvi ro'yxatda ko'rinadi."""
    created = await create_webhook(client, api_prefix, auth_headers)

    with respx.mock(assert_all_called=True) as mock:
        mock.post(HOOK_URL).mock(return_value=httpx.Response(204))
        await client.post(
            f"{api_prefix}/webhooks/{created['id']}/test", headers=auth_headers, json={}
        )

    response = await client.get(
        f"{api_prefix}/webhooks/{created['id']}/deliveries", headers=auth_headers
    )

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["webhook_id"] == created["id"]
    assert items[0]["response_code"] == 204
    assert items[0]["event"] == WebhookEvent.JOB_SUCCEEDED.value


async def test_test_endpoint_reports_failure(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Mijoz endpointi 500 bersa javobda `success=false` bo'ladi (HTTP 200)."""
    created = await create_webhook(client, api_prefix, auth_headers)

    with respx.mock(assert_all_called=True) as mock:
        mock.post(HOOK_URL).mock(return_value=httpx.Response(500, text="ichki xato"))
        response = await client.post(
            f"{api_prefix}/webhooks/{created['id']}/test", headers=auth_headers, json={}
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is False
    assert body["status_code"] == 500


async def test_other_users_webhook_not_found(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    other_user: User,
) -> None:
    """Begona webhook HAR DOIM 404 (IDOR himoyasi)."""
    from tests.factories import make_webhook

    foreign = make_webhook(user_id=other_user.id, url=HOOK_URL)
    db_session.add(foreign)
    await db_session.commit()
    foreign_id = str(foreign.id)

    for method, path in (
        ("get", f"/webhooks/{foreign_id}"),
        ("get", f"/webhooks/{foreign_id}/deliveries"),
        ("delete", f"/webhooks/{foreign_id}"),
    ):
        response = await getattr(client, method)(api_prefix + path, headers=auth_headers)
        assert response.status_code == 404, f"{method} {path}: {response.text}"

    listed = await client.get(f"{api_prefix}/webhooks", headers=auth_headers)
    assert listed.json()["pagination"]["total"] == 0


async def test_webhook_limit_per_user(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """`MAX_WEBHOOKS_PER_USER` dan ortiq webhook yaratilmaydi (422)."""
    for index in range(MAX_WEBHOOKS_PER_USER):
        await create_webhook(
            client, api_prefix, auth_headers, url=f"https://h{index}.durabl-test.invalid/x"
        )

    response = await client.post(
        f"{api_prefix}/webhooks",
        headers=auth_headers,
        json=create_body("https://oshib-ketdi.durabl-test.invalid/x"),
    )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]["limit"] == MAX_WEBHOOKS_PER_USER


async def test_unknown_event_rejected(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Noma'lum hodisa nomi 422 beradi."""
    response = await client.post(
        f"{api_prefix}/webhooks", headers=auth_headers, json=create_body(events=["job.yoq"])
    )

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_requires_authentication(client: httpx.AsyncClient, api_prefix: str) -> None:
    """Tokensiz so'rov 401 beradi."""
    response = await client.get(f"{api_prefix}/webhooks")

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


__all__ = ["HOOK_URL", "create_body", "create_webhook"]
