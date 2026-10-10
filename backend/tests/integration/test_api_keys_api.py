"""Durabl — `/api-keys` endpointlarining integratsiya testlari.

## Shu routerning ikki asosiy qoidasi

1. **Faqat JWT.** Kalitlarni boshqarish `JwtUser` dependency'si bilan
   himoyalangan: API kalit bilan kelgan so'rov 403 oladi. Aks holda bitta
   o'g'irlangan kalit yangi kalitlar yasab abadiy kirish huquqini olardi.
2. **Xom kalit faqat BIR MARTA.** `ApiKeyCreated` javobida `key` maydoni
   bor, qolgan barcha javoblarda (`ApiKeyRead`) faqat `masked_key`. DB'da
   SHA-256 hash saqlanadi, ya'ni kalitni tiklash IMKONSIZ.

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

## Nega bekor qilish `DELETE` bo'lsa ham yozuv qoladi

`AuthService.revoke_api_key()` yozuvni FIZIK o'chirmaydi — `revoked_at`
qo'yadi. Shuning uchun `?include_revoked=true` bilan kalit hamon ko'rinadi
(audit uchun), lekin u bilan autentifikatsiya 401 beradi.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import pytest
from app.constants import HEADER_API_KEY

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    import httpx
    from app.models.user import User
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def create_key(
    client: httpx.AsyncClient,
    api_prefix: str,
    headers: dict[str, str],
    name: str = "deploy-kaliti",
) -> dict[str, object]:
    """`POST /api-keys` chaqiradi va javob tanasini qaytaradi."""
    response = await client.post(f"{api_prefix}/api-keys", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


async def test_create_returns_raw_key_once(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str], user: User
) -> None:
    """Yaratishda xom `key` qaytadi va `key_prefix`/`last_four` unga mos."""
    body = await create_key(client, api_prefix, auth_headers)

    raw = body["key"]
    assert isinstance(raw, str)
    assert raw.startswith(str(body["key_prefix"]))
    assert raw.endswith(str(body["last_four"]))
    assert body["user_id"] == str(user.id)
    assert body["revoked_at"] is None


async def test_list_hides_raw_key(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Ro'yxatda xom kalit YO'Q, faqat `masked_key`."""
    created = await create_key(client, api_prefix, auth_headers)

    response = await client.get(f"{api_prefix}/api-keys", headers=auth_headers)

    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert [item["id"] for item in items] == [created["id"]]
    assert "key" not in items[0]
    assert items[0]["masked_key"]
    assert items[0]["is_valid"] is True


async def test_created_key_authenticates(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str], user: User
) -> None:
    """Yangi kalit bilan `GET /auth/me` ishlaydi."""
    body = await create_key(client, api_prefix, auth_headers)

    response = await client.get(f"{api_prefix}/auth/me", headers={HEADER_API_KEY: str(body["key"])})

    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(user.id)


async def test_revoke_then_key_rejected(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Bekor qilingan kalit 401 oladi, lekin yozuv tarixda qoladi."""
    body = await create_key(client, api_prefix, auth_headers)
    raw = str(body["key"])

    deleted = await client.delete(f"{api_prefix}/api-keys/{body['id']}", headers=auth_headers)
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["success"] is True

    rejected = await client.get(f"{api_prefix}/auth/me", headers={HEADER_API_KEY: raw})
    assert rejected.status_code == 401, rejected.text
    assert rejected.json()["error"]["code"] == "INVALID_API_KEY"


async def test_revoked_key_hidden_unless_requested(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Bekor qilingan kalit standart ro'yxatda YO'Q, `include_revoked` bilan BOR."""
    body = await create_key(client, api_prefix, auth_headers)
    await client.delete(f"{api_prefix}/api-keys/{body['id']}", headers=auth_headers)

    default = await client.get(f"{api_prefix}/api-keys", headers=auth_headers)
    assert default.json()["pagination"]["total"] == 0

    with_revoked = await client.get(
        f"{api_prefix}/api-keys?include_revoked=true", headers=auth_headers
    )
    assert with_revoked.status_code == 200, with_revoked.text
    items = with_revoked.json()["items"]
    assert [item["id"] for item in items] == [body["id"]]
    assert items[0]["is_revoked"] is True
    assert items[0]["is_valid"] is False


async def test_delete_unknown_key_not_found(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Mavjud bo'lmagan kalitni bekor qilish 404 beradi."""
    response = await client.delete(f"{api_prefix}/api-keys/{uuid.uuid4()}", headers=auth_headers)

    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "API_KEY_NOT_FOUND"


async def test_cannot_touch_other_users_key(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    other_user: User,
) -> None:
    """Begona kalit ro'yxatda ko'rinmaydi va bekor qilinmaydi (404)."""
    from app.schemas.api_key import ApiKeyCreate
    from app.services.auth_service import AuthService

    foreign, _raw = await AuthService(db_session).create_api_key(
        other_user, ApiKeyCreate(name="begona")
    )
    await db_session.commit()
    foreign_id = str(foreign.id)

    listed = await client.get(f"{api_prefix}/api-keys", headers=auth_headers)
    assert listed.json()["pagination"]["total"] == 0

    response = await client.delete(f"{api_prefix}/api-keys/{foreign_id}", headers=auth_headers)
    assert response.status_code == 404, response.text


async def test_api_key_cannot_manage_api_keys(
    client: httpx.AsyncClient, api_prefix: str, api_key_headers: dict[str, str]
) -> None:
    """API kalit bilan kalitlarni boshqarish 403 (modul docstring'iga qara)."""
    listed = await client.get(f"{api_prefix}/api-keys", headers=api_key_headers)
    created = await client.post(
        f"{api_prefix}/api-keys", headers=api_key_headers, json={"name": "zanjir"}
    )

    assert listed.status_code == 403, listed.text
    assert created.status_code == 403, created.text
    assert created.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_requires_authentication(client: httpx.AsyncClient, api_prefix: str) -> None:
    """Tokensiz so'rov 401 beradi."""
    response = await client.get(f"{api_prefix}/api-keys")

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


async def test_pagination(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Ro'yxat `?page`/`?page_size` ni qabul qiladi va meta'si to'g'ri."""
    for index in range(3):
        await create_key(client, api_prefix, auth_headers, name=f"kalit-{index}")

    response = await client.get(f"{api_prefix}/api-keys?page=2&page_size=2", headers=auth_headers)

    assert response.status_code == 200, response.text
    meta = response.json()["pagination"]
    assert meta["total"] == 3
    assert meta["total_pages"] == 2
    assert meta["has_prev"] is True
    assert meta["has_next"] is False
    assert len(response.json()["items"]) == 1


async def test_invalid_name_unprocessable(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Bo'sh nom 422 `VALIDATION_ERROR` beradi."""
    response = await client.post(f"{api_prefix}/api-keys", headers=auth_headers, json={"name": ""})

    assert response.status_code == 422, response.text
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


__all__ = ["create_key"]
