"""Durabl — API kalit ruxsat doiralari (`scopes`) MAJBURLANISHI.

## Nega bu testlar bor

`scopes` maydoni avval DB'ga yozilardi va API'da qaytarilardi, lekin
HECH BIR endpoint uni tekshirmasdi. Ya'ni mijoz `jobs:read` bergan
kalit ham billing'ni ko'rar, webhook'ni o'chirar va DLQ'ni tozalar edi.

Bu **yolg'on xavfsizlik hissi** — eng yomon turdagi bo'shliq: mijoz
"kalitni cheklab qo'ydim" deb o'ylab, aslida hech narsa cheklanmagan.

Testlar uch narsani qotiradi:

1. tor doiradagi kalit ruxsat etilmagan amalga **401/403 oladi**;
2. keng doiradagi (yoki `admin`) kalit **o'tadi**;
3. JWT bilan kirilganda scope **TEKSHIRILMAYDI** (dashboard shu yo'ldan
   ishlaydi va u foydalanuvchining o'z nomidan).

## Nega bo'sh ro'yxat to'liq huquq beradi

Majburlash qo'shilishidan OLDIN yaratilgan kalitlar bo'sh ro'yxat
bilan yozilgan. Agar bo'sh ro'yxat "hech narsaga ruxsat yo'q" deb
o'qilsa, mavjud barcha kalitlar BIR VAQTDA ishlashdan to'xtardi.

`ApiKeyCreate` tavsifi ham "bo'sh ro'yxat — barcha standart huquqlar"
deb yozilgan, ya'ni bu shartnomaning qismi, yon ta'sir emas.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from app.constants import HEADER_API_KEY, ApiKeyScope
from app.schemas.api_key import ApiKeyCreate
from app.services.auth_service import AuthService

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    import httpx
    from app.models.user import User
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


async def make_key(session: AsyncSession, user: User, scopes: list[str] | None) -> dict[str, str]:
    """Berilgan doiralar bilan kalit yasaydi va header'ini qaytaradi."""
    service = AuthService(session)
    _, raw = await service.create_api_key(
        user, ApiKeyCreate(name=f"scope-test-{scopes}", scopes=scopes)
    )
    return {HEADER_API_KEY: raw}


# ---------------------------------------------------------------------------
# Tor doira — ruxsat etilmagan amal RAD ETILADI
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        # `jobs:write` kerak — job yuborish, bekor qilish, o'chirish.
        ("post", "/jobs", {"code": "print(1)", "runtime": "python"}),
        # `admin` kerak — billing va webhook.
        ("get", "/billing/subscription", None),
        ("get", "/webhooks", None),
        # `dlq:read` kerak.
        ("get", "/dlq", None),
    ],
)
async def test_faqat_jobs_read_bolgan_kalit_rad_etiladi(
    client: httpx.AsyncClient,
    api_prefix: str,
    db_session: AsyncSession,
    user: User,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    """`jobs:read` kalit o'z doirasidan tashqariga chiqa olmaydi."""
    headers = await make_key(db_session, user, [ApiKeyScope.JOBS_READ.value])

    response = await client.request(
        method.upper(), f"{api_prefix}{path}", headers=headers, json=body
    )

    assert response.status_code == 403, f"{method} {path}: {response.text}"
    assert "API_KEY_SCOPE_REQUIRED" in response.text


async def test_rad_etish_xabari_KERAKLI_doirani_aytadi(
    client: httpx.AsyncClient,
    api_prefix: str,
    db_session: AsyncSession,
    user: User,
) -> None:
    """Xato javobi nima kerakligini va nima berilganini ko'rsatadi.

    Busiz mijoz "nega ishlamadi?" degan savolda qolardi va kalitni
    qaytadan yaratib ko'rishga majbur bo'lardi.
    """
    headers = await make_key(db_session, user, [ApiKeyScope.JOBS_READ.value])

    response = await client.post(
        f"{api_prefix}/jobs", headers=headers, json={"code": "print(1)", "runtime": "python"}
    )

    details = response.json()["error"]["details"]
    assert details["required_scope"] == ApiKeyScope.JOBS_WRITE.value
    assert details["granted_scopes"] == [ApiKeyScope.JOBS_READ.value]


# ---------------------------------------------------------------------------
# Yetarli doira — amal O'TADI
# ---------------------------------------------------------------------------


async def test_jobs_read_kalit_royxatni_oqiydi(
    client: httpx.AsyncClient,
    api_prefix: str,
    db_session: AsyncSession,
    user: User,
) -> None:
    """O'z doirasidagi amal o'tadi."""
    headers = await make_key(db_session, user, [ApiKeyScope.JOBS_READ.value])

    response = await client.get(f"{api_prefix}/jobs", headers=headers)

    assert response.status_code == 200, response.text


async def test_jobs_write_kalit_job_yuboradi(
    client: httpx.AsyncClient,
    api_prefix: str,
    db_session: AsyncSession,
    user: User,
) -> None:
    """`jobs:write` kalit job yubora oladi."""
    headers = await make_key(db_session, user, [ApiKeyScope.JOBS_WRITE.value])

    response = await client.post(
        f"{api_prefix}/jobs", headers=headers, json={"code": "print(1)", "runtime": "python"}
    )

    assert response.status_code == 201, response.text


@pytest.mark.parametrize(
    "path", ["/billing/subscription", "/webhooks", "/dlq", "/jobs", "/analytics/overview"]
)
async def test_admin_doirasi_HAMMASINI_qamraydi(
    client: httpx.AsyncClient,
    api_prefix: str,
    db_session: AsyncSession,
    user: User,
    path: str,
) -> None:
    """`admin` — barcha doiralarni qamraydi (frontend tavsifi bo'yicha).

    `API_KEY_SCOPE_INFO.admin`: "everything above, plus billing,
    webhooks, team and API key management".
    """
    headers = await make_key(db_session, user, [ApiKeyScope.ADMIN.value])

    response = await client.get(f"{api_prefix}{path}", headers=headers)

    assert response.status_code == 200, f"{path}: {response.text}"


async def test_bir_nechta_doira_birga_ishlaydi(
    client: httpx.AsyncClient,
    api_prefix: str,
    db_session: AsyncSession,
    user: User,
) -> None:
    """Ikki doira berilsa ikkisi ham ishlaydi, uchinchisi yo'q."""
    headers = await make_key(
        db_session,
        user,
        [ApiKeyScope.JOBS_READ.value, ApiKeyScope.DLQ_READ.value],
    )

    assert (await client.get(f"{api_prefix}/jobs", headers=headers)).status_code == 200
    assert (await client.get(f"{api_prefix}/dlq", headers=headers)).status_code == 200
    # Billing berilmagan.
    assert (
        await client.get(f"{api_prefix}/billing/subscription", headers=headers)
    ).status_code == 403


# ---------------------------------------------------------------------------
# Orqaga moslik va JWT
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scopes", [None, []])
async def test_BOSH_royxat_toliq_huquq_beradi(
    client: httpx.AsyncClient,
    api_prefix: str,
    db_session: AsyncSession,
    user: User,
    scopes: list[str] | None,
) -> None:
    """Bo'sh doira ro'yxati — to'liq huquq (ORQAGA MOSLIK).

    Majburlash qo'shilishidan oldin yaratilgan kalitlar bo'sh ro'yxat
    bilan yozilgan. Agar bo'sh ro'yxat "ruxsat yo'q" deb o'qilsa,
    mavjud BARCHA kalitlar bir vaqtda ishlashdan to'xtardi.
    """
    headers = await make_key(db_session, user, scopes)

    assert (await client.get(f"{api_prefix}/jobs", headers=headers)).status_code == 200
    assert (
        await client.get(f"{api_prefix}/billing/subscription", headers=headers)
    ).status_code == 200


async def test_JWT_bilan_scope_TEKSHIRILMAYDI(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
) -> None:
    """JWT — foydalanuvchining o'z nomidan, scope qo'llanmaydi.

    Scope mashina hisob ma'lumotining xususiyati. Dashboard JWT bilan
    ishlaydi va foydalanuvchi o'z hisobida to'liq huquqqa ega —
    aks holda UI o'zining ma'lumotini ko'rsata olmasdi.
    """
    for path in ("/jobs", "/billing/subscription", "/webhooks", "/dlq"):
        response = await client.get(f"{api_prefix}{path}", headers=auth_headers)
        assert response.status_code == 200, f"{path}: {response.text}"


# ---------------------------------------------------------------------------
# Kalit boshqaruvi API kalit bilan QILINMAYDI (allaqachon shunday edi)
# ---------------------------------------------------------------------------


async def test_admin_endpointi_tor_doiradagi_kalitni_RAD_ETADI(
    client: httpx.AsyncClient,
    api_prefix: str,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    """Admin ROLI yetarli emas — kalitning DOIRASI ham kerak.

    `AdminUser` faqat `user.is_admin` ni tekshiradi, lekin u API kalitni
    ham qabul qiladi. Busiz admin foydalanuvchining `jobs:read` kaliti
    butun admin paneliga yetib borardi: boshqa foydalanuvchilarni
    o'zgartirish, audit jurnalini o'qish.

    Ikki tekshiruv birga: rol (KIM) va doira (QANDAY kalit bilan).
    """
    headers = await make_key(db_session, admin_user, [ApiKeyScope.JOBS_READ.value])

    response = await client.get(f"{api_prefix}/admin/stats", headers=headers)

    assert response.status_code == 403, response.text
    assert "API_KEY_SCOPE_REQUIRED" in response.text


async def test_admin_endpointi_admin_doirasi_bilan_otadi(
    client: httpx.AsyncClient,
    api_prefix: str,
    db_session: AsyncSession,
    admin_user: User,
) -> None:
    """Rol VA doira ikkisi ham bo'lsa — o'tadi."""
    headers = await make_key(db_session, admin_user, [ApiKeyScope.ADMIN.value])

    response = await client.get(f"{api_prefix}/admin/stats", headers=headers)

    assert response.status_code == 200, response.text


async def test_admin_doirasi_lekin_admin_ROLI_yoq_bolsa_rad_etiladi(
    client: httpx.AsyncClient,
    api_prefix: str,
    db_session: AsyncSession,
    user: User,
) -> None:
    """`admin` doirasi ADMIN QILMAYDI — rol alohida tekshiriladi.

    Oddiy foydalanuvchi o'ziga `admin` doirali kalit yasashi mumkin
    (bu o'z hisobi doirasida mantiqiy), lekin bu uni platforma
    administratoriga AYLANTIRMAYDI.
    """
    headers = await make_key(db_session, user, [ApiKeyScope.ADMIN.value])

    response = await client.get(f"{api_prefix}/admin/stats", headers=headers)

    assert response.status_code == 403, response.text
    # Rad etish SABABI boshqa: doira emas, rol.
    assert "API_KEY_SCOPE_REQUIRED" not in response.text


async def test_api_kalit_bilan_kalit_boshqarilmaydi(
    client: httpx.AsyncClient,
    api_prefix: str,
    db_session: AsyncSession,
    user: User,
) -> None:
    """`admin` doirasi ham kalit boshqaruviga yo'l bermaydi.

    `api_keys.py` `JwtUser` ni ishlatadi, ya'ni API kalit bilan kalit
    yaratish/o'chirish/almashtirish BUTUNLAY taqiqlangan — scope'dan
    qat'i nazar.

    Bu ataylab: kalit o'zini o'zi uzaytira yoki yangi kalit yasay
    olmasligi kerak. Aks holda sizib ketgan kalit abadiylashardi.
    """
    headers = await make_key(db_session, user, [ApiKeyScope.ADMIN.value])

    listed = await client.get(f"{api_prefix}/api-keys", headers=headers)
    created = await client.post(f"{api_prefix}/api-keys", headers=headers, json={"name": "yangi"})

    assert listed.status_code == 403, listed.text
    assert created.status_code == 403, created.text
