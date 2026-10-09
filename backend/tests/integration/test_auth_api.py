"""Durabl — `/auth/*` endpointlarining integratsiya testlari.

HTTP qatlami orqali tekshiriladi (`httpx.ASGITransport`), ya'ni middleware,
dependency va exception handler'lar HAM zanjirga kiradi — xuddi haqiqiy
so'rovda bo'lgani kabi.

## Nega email domeni `@example.com` va nega `user` fixture'i yetarli emas

`pydantic[email]` ning `email-validator` kutubxonasi `.test` kabi
"special-use" TLD'larni RAD ETADI (RFC 2606). `conftest.py` dagi
`user`/`admin_user` fixture'lari DB'ga BEVOSITA yoziladi, shuning uchun
ularda `@durabl.test` ishlaydi — lekin `POST /auth/register` va
`POST /auth/login` schema validatsiyasidan o'tadi, ya'ni u yerda shu email
422 beradi.

Shuning uchun parol talab qiladigan testlar (`login`, `change-password`,
`DELETE /auth/me`) foydalanuvchini `register_user()` yordamchisi bilan
HTTP orqali yaratadi — bu baribir to'g'riroq integratsiya testi: ro'yxatdan
o'tish va kirish zanjiri uchidan-uchiga tekshiriladi. Token KERAK bo'lmagan
testlar (`/auth/me`, `PUT /auth/me`) tezroq `auth_headers` fixture'idan
foydalanadi.

## Nega "J" ustuni qat'iy tekshiriladi

CONTRACTS "QO'SHIMCHA 2 / AUTH" jadvalida `PUT /auth/me`,
`POST /auth/change-password` va `DELETE /auth/me` faqat JWT qabul qiladi.
API kalit bilan kelgan so'rov 403 olishi SHART — aks holda o'g'irlangan
kalit darhol to'liq hisob egaligiga aylanardi.
"""

from __future__ import annotations

import itertools
from typing import TYPE_CHECKING

import pytest
from app.utils.security import create_refresh_token

if TYPE_CHECKING:  # pragma: no cover - faqat tur tekshiruvi
    import httpx
    from app.models.user import User

pytestmark = pytest.mark.integration

#: HTTP orqali yaratiladigan foydalanuvchilarning paroli (siyosatdan o'tadi).
NEW_PASSWORD = "YangiParol123"

#: Boshqa parolga almashtirish testlari uchun ikkinchi yaroqli parol.
OTHER_PASSWORD = "BoshqaParol456"

#: Takrorlanmas email yasash uchun hisoblagich (`email-validator` qabul
#: qiladigan domen bilan).
_emails = itertools.count(1)


def next_email() -> str:
    """`api-1@example.com` ko'rinishidagi takrorlanmas email."""
    return f"api-{next(_emails)}@example.com"


def register_body(email: str, password: str = NEW_PASSWORD) -> dict[str, str]:
    """`POST /auth/register` uchun minimal tana."""
    return {"email": email, "password": password, "full_name": "Yangi Foydalanuvchi"}


async def register_user(
    client: httpx.AsyncClient,
    api_prefix: str,
    *,
    email: str | None = None,
    password: str = NEW_PASSWORD,
) -> tuple[str, str]:
    """HTTP orqali hisob yaratadi va `(email, parol)` qaytaradi."""
    address = email or next_email()
    response = await client.post(
        f"{api_prefix}/auth/register", json=register_body(address, password)
    )
    assert response.status_code == 201, response.text
    return address, password


async def login(
    client: httpx.AsyncClient, api_prefix: str, email: str, password: str
) -> httpx.Response:
    """`POST /auth/login` so'rovi (javob tekshirilmaydi)."""
    return await client.post(
        f"{api_prefix}/auth/login", json={"email": email, "password": password}
    )


async def test_register_creates_user(client: httpx.AsyncClient, api_prefix: str) -> None:
    """Yangi hisob 201 bilan yaratiladi va `UserRead` qaytadi."""
    email = next_email()
    response = await client.post(f"{api_prefix}/auth/register", json=register_body(email))

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == email
    assert body["is_active"] is True
    assert body["is_admin"] is False
    # Parol hech qanday ko'rinishda javobga tushmasligi SHART.
    assert "password" not in body
    assert "hashed_password" not in body


async def test_register_duplicate_email_conflicts(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    """Mavjud email bilan ro'yxatdan o'tish 409 `DUPLICATE_EMAIL` beradi."""
    email, _ = await register_user(client, api_prefix)

    response = await client.post(f"{api_prefix}/auth/register", json=register_body(email))

    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "DUPLICATE_EMAIL"


@pytest.mark.parametrize(
    "password",
    ["qisqa", "faqatharflar", "1234567890"],
    ids=["too_short", "no_digit", "no_letter"],
)
async def test_register_weak_password_rejected(
    client: httpx.AsyncClient, api_prefix: str, password: str
) -> None:
    """Kuchsiz parol 422 `VALIDATION_ERROR` bilan rad etiladi."""
    response = await client.post(
        f"{api_prefix}/auth/register", json=register_body(next_email(), password)
    )

    assert response.status_code == 422, response.text
    error = response.json()["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"]["errors"]


async def test_login_returns_token_pair(client: httpx.AsyncClient, api_prefix: str) -> None:
    """To'g'ri parol access va refresh juftligini beradi."""
    email, password = await register_user(client, api_prefix)

    response = await login(client, api_prefix, email, password)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]
    assert body["expires_in"] > 0

    # Olingan token HAQIQATAN ishlaydi.
    me = await client.get(
        f"{api_prefix}/auth/me",
        headers={"Authorization": f"Bearer {body['access_token']}"},
    )
    assert me.status_code == 200, me.text
    assert me.json()["email"] == email


async def test_login_wrong_password_unauthorized(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    """Noto'g'ri parol 401 `INVALID_CREDENTIALS` beradi."""
    email, _ = await register_user(client, api_prefix)

    response = await login(client, api_prefix, email, OTHER_PASSWORD)

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"


async def test_me_with_jwt_and_api_key(
    client: httpx.AsyncClient,
    api_prefix: str,
    user: User,
    auth_headers: dict[str, str],
    api_key_headers: dict[str, str],
) -> None:
    """`GET /auth/me` IKKI usulni ham qabul qiladi va AYNI profilni beradi."""
    by_jwt = await client.get(f"{api_prefix}/auth/me", headers=auth_headers)
    by_key = await client.get(f"{api_prefix}/auth/me", headers=api_key_headers)

    assert by_jwt.status_code == 200, by_jwt.text
    assert by_key.status_code == 200, by_key.text
    assert by_jwt.json()["id"] == by_key.json()["id"] == str(user.id)


async def test_me_without_credentials_unauthorized(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    """Autentifikatsiyasiz so'rov 401 beradi."""
    response = await client.get(f"{api_prefix}/auth/me")

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


async def test_refresh_issues_new_pair(
    client: httpx.AsyncClient, api_prefix: str, user: User
) -> None:
    """Refresh token yangi juftlik beradi."""
    response = await client.post(
        f"{api_prefix}/auth/refresh", json={"refresh_token": create_refresh_token(user.id)}
    )

    assert response.status_code == 200, response.text
    assert response.json()["access_token"]


async def test_refresh_with_invalid_token_unauthorized(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    """Yaroqsiz refresh token 401 beradi."""
    response = await client.post(
        f"{api_prefix}/auth/refresh", json={"refresh_token": "mutlaqo.yaroqsiz.token"}
    )

    assert response.status_code == 401, response.text
    assert response.json()["error"]["code"] in {"INVALID_TOKEN", "TOKEN_EXPIRED"}


async def test_update_profile(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """`PUT /auth/me` to'liq ismni o'zgartiradi."""
    response = await client.put(
        f"{api_prefix}/auth/me", headers=auth_headers, json={"full_name": "Yangilangan Ism"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["full_name"] == "Yangilangan Ism"

    again = await client.get(f"{api_prefix}/auth/me", headers=auth_headers)
    assert again.json()["full_name"] == "Yangilangan Ism"


async def test_update_profile_with_api_key_forbidden(
    client: httpx.AsyncClient, api_prefix: str, api_key_headers: dict[str, str]
) -> None:
    """API kalit hisob sozlamalarini o'zgartirishga ruxsat bermaydi (403)."""
    response = await client.put(
        f"{api_prefix}/auth/me", headers=api_key_headers, json={"full_name": "Kalit bilan"}
    )

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


async def test_change_password_invalidates_old_one(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    """Parol almashtirilgach ESKI parol bilan kirish ishlamaydi."""
    email, password = await register_user(client, api_prefix)
    tokens = await login(client, api_prefix, email, password)
    headers = {"Authorization": f"Bearer {tokens.json()['access_token']}"}

    changed = await client.post(
        f"{api_prefix}/auth/change-password",
        headers=headers,
        json={"current_password": password, "new_password": OTHER_PASSWORD},
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["success"] is True

    with_old = await login(client, api_prefix, email, password)
    assert with_old.status_code == 401

    with_new = await login(client, api_prefix, email, OTHER_PASSWORD)
    assert with_new.status_code == 200, with_new.text


async def test_change_password_wrong_current_unauthorized(
    client: httpx.AsyncClient, api_prefix: str, auth_headers: dict[str, str]
) -> None:
    """Joriy parol noto'g'ri bo'lsa 401 qaytadi."""
    response = await client.post(
        f"{api_prefix}/auth/change-password",
        headers=auth_headers,
        json={"current_password": "ButunlayBoshqa1", "new_password": OTHER_PASSWORD},
    )

    assert response.status_code == 401, response.text


async def test_deactivate_account_blocks_login(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    """`DELETE /auth/me` hisobni faolsizlantiradi; keyin login 403 beradi."""
    email, password = await register_user(client, api_prefix)
    tokens = await login(client, api_prefix, email, password)
    headers = {"Authorization": f"Bearer {tokens.json()['access_token']}"}

    response = await client.delete(f"{api_prefix}/auth/me", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["data"]["is_active"] is False

    again = await login(client, api_prefix, email, password)
    assert again.status_code == 403, again.text
    assert again.json()["error"]["code"] == "INACTIVE_USER"


async def test_deactivated_account_token_rejected(
    client: httpx.AsyncClient, api_prefix: str
) -> None:
    """Faolsizlantirilgandan keyin MAVJUD token ham 403 oladi."""
    email, password = await register_user(client, api_prefix)
    tokens = await login(client, api_prefix, email, password)
    headers = {"Authorization": f"Bearer {tokens.json()['access_token']}"}

    await client.delete(f"{api_prefix}/auth/me", headers=headers)

    response = await client.get(f"{api_prefix}/auth/me", headers=headers)
    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "INACTIVE_USER"


async def test_admin_cannot_deactivate_self(
    client: httpx.AsyncClient, api_prefix: str, admin_headers: dict[str, str]
) -> None:
    """Administrator o'z hisobini faolsizlantira olmaydi (403)."""
    response = await client.delete(f"{api_prefix}/auth/me", headers=admin_headers)

    assert response.status_code == 403, response.text
    assert response.json()["error"]["code"] == "PERMISSION_DENIED"


__all__ = [
    "NEW_PASSWORD",
    "OTHER_PASSWORD",
    "login",
    "next_email",
    "register_body",
    "register_user",
]
