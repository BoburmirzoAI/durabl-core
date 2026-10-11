"""Durabl — Faza 1B da qo'shilgan API kalit boshqaruvi.

| Metod | Yo'l | Nima beradi |
|---|---|---|
| `GET` | `/api-keys/{id}` | bitta kalit tafsiloti |
| `PUT` | `/api-keys/{id}/scopes` | huquqlarni almashtirish |
| `PUT` | `/api-keys/{id}/expiry` | muddatni o'zgartirish |
| `POST` | `/api-keys/{id}/rotate` | kalitni joyida almashtirish |

## Rotatsiya — eng muhim qism

Rotatsiya "joyida almashtirish": `id`, nom va huquqlar saqlanadi,
faqat qiymat o'zgaradi. Eski kalit DARHOL o'lmaydi — unga grace
muddati beriladi.

Nega bu muhim: mijozning CI, serveri va lokal muhiti bir xil kalitni
ishlatayotgan bo'lishi mumkin. Darhol bekor qilish ularning hammasini
BIR VAQTDA uzadi, ya'ni rotatsiya "xavfsizlik amali" emas, "avariya"
bo'lib qolardi.

Shu sababli uch narsa alohida tekshiriladi:

1. yangi kalit ishlaydi;
2. eski kalit grace oynasida HAM ishlaydi;
3. grace tugagandan keyin eski kalit ISHLAMAYDI (aks holda u abadiy
   ochiq qolardi — eng yomon xato).

## Scope'lar haqida ogohlantirish

Testlar scope'ning SAQLANISHINI tekshiradi, MAJBURLANISHINI emas —
chunki hozirda hech bir endpoint scope'ni tekshirmaydi. Bu alohida
bo'shliq (`docs/TASKS.md` da yozilgan), test esa mavjud xulqni
qotiradi.
"""

from __future__ import annotations

from datetime import timedelta
from typing import TYPE_CHECKING

import pytest
from app.constants import HEADER_API_KEY
from app.services.auth_service import API_KEY_ROTATION_GRACE_HOURS
from app.utils.time_utils import isoformat, utcnow

if TYPE_CHECKING:  # pragma: no cover - faqat tip tekshiruvi uchun
    import httpx
    from app.models.api_key import ApiKey
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# GET /api-keys/{id}
# ---------------------------------------------------------------------------


async def test_bitta_kalit_qaytadi_xom_qiymatsiz(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    api_key: tuple[ApiKey, str],
) -> None:
    """Tafsilot qaytadi, lekin XOM kalit yo'q — u faqat bir marta ko'rsatiladi."""
    record, raw = api_key

    response = await client.get(f"{api_prefix}/api-keys/{record.id}", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(record.id)
    assert body["masked_key"].endswith(body["last_four"])
    # Xom kalit javobda BO'LMASLIGI shart.
    assert "key" not in body
    assert raw not in response.text


async def test_boshqa_foydalanuvchining_kalitida_404(
    client: httpx.AsyncClient,
    api_prefix: str,
    other_user_headers: dict[str, str],
    api_key: tuple[ApiKey, str],
) -> None:
    """Begona kalit uchun 404 (403 EMAS) — mavjudligi oshkor qilinmaydi."""
    record, _ = api_key

    response = await client.get(f"{api_prefix}/api-keys/{record.id}", headers=other_user_headers)

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# PUT /api-keys/{id}/scopes
# ---------------------------------------------------------------------------


async def test_huquqlar_BUTUNLAY_almashtiriladi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    api_key: tuple[ApiKey, str],
) -> None:
    """Ro'yxat qo'shilmaydi, ALMASHTIRILADI — mijoz yakuniy to'plam yuboradi."""
    record, _ = api_key

    response = await client.put(
        f"{api_prefix}/api-keys/{record.id}/scopes",
        headers=auth_headers,
        json={"scopes": ["jobs:read"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["scopes"] == ["jobs:read"]


async def test_takrorlangan_huquq_bir_marta_qoladi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    api_key: tuple[ApiKey, str],
) -> None:
    """Takrorlanish olib tashlanadi, tartib saqlanadi."""
    record, _ = api_key

    response = await client.put(
        f"{api_prefix}/api-keys/{record.id}/scopes",
        headers=auth_headers,
        json={"scopes": ["jobs:write", "jobs:read", "jobs:write"]},
    )

    assert response.json()["scopes"] == ["jobs:write", "jobs:read"]


# ---------------------------------------------------------------------------
# PUT /api-keys/{id}/expiry
# ---------------------------------------------------------------------------


async def test_muddat_uzaytiriladi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    api_key: tuple[ApiKey, str],
) -> None:
    """Kelajakdagi muddat qabul qilinadi."""
    record, _ = api_key
    future = utcnow() + timedelta(days=30)

    response = await client.put(
        f"{api_prefix}/api-keys/{record.id}/expiry",
        headers=auth_headers,
        json={"expires_at": isoformat(future)},
    )

    assert response.status_code == 200, response.text
    assert response.json()["expires_at"] is not None


async def test_muddat_olib_tashlanadi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    api_key: tuple[ApiKey, str],
) -> None:
    """`expires_at: null` — kalit muddatsiz bo'ladi (ATAYLAB ruxsat etilgan)."""
    record, _ = api_key
    record.expires_at = utcnow() + timedelta(days=1)
    await db_session.commit()
    key_id = record.id

    response = await client.put(
        f"{api_prefix}/api-keys/{key_id}/expiry",
        headers=auth_headers,
        json={"expires_at": None},
    )

    assert response.status_code == 200, response.text
    assert response.json()["expires_at"] is None


async def test_otmishdagi_muddat_rad_etiladi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    api_key: tuple[ApiKey, str],
) -> None:
    """O'tmishdagi vaqt 422 — u amalda "bekor qilish" bo'lardi.

    Buning uchun ochiq `DELETE /api-keys/{id}` bor: niyat aniq
    bo'lishi kerak, yashirin yo'l bilan emas.
    """
    record, _ = api_key

    response = await client.put(
        f"{api_prefix}/api-keys/{record.id}/expiry",
        headers=auth_headers,
        json={"expires_at": isoformat(utcnow() - timedelta(hours=1))},
    )

    assert response.status_code == 422, response.text
    assert "DELETE" in response.text


# ---------------------------------------------------------------------------
# POST /api-keys/{id}/rotate — asosiy qism
# ---------------------------------------------------------------------------


async def test_rotatsiya_id_saqlaydi_va_yangi_kalit_beradi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    api_key: tuple[ApiKey, str],
) -> None:
    """`id`, nom va huquqlar saqlanadi, qiymat o'zgaradi."""
    record, old_raw = api_key
    key_id = record.id

    response = await client.post(f"{api_prefix}/api-keys/{key_id}/rotate", headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    # Joyida almashtirish — `id` O'ZGARMAYDI.
    assert body["key_id"] == str(key_id)
    assert body["key"] != old_raw
    assert body["key"].startswith("durabl_")
    assert body["rotated_at"] is not None
    assert body["old_key_valid_until"] is not None


async def test_rotatsiyadan_keyin_YANGI_kalit_ishlaydi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    api_key: tuple[ApiKey, str],
) -> None:
    """Yangi kalit bilan autentifikatsiya o'tadi."""
    record, _ = api_key
    rotated = await client.post(f"{api_prefix}/api-keys/{record.id}/rotate", headers=auth_headers)
    new_raw = rotated.json()["key"]

    response = await client.get(f"{api_prefix}/jobs", headers={HEADER_API_KEY: new_raw})

    assert response.status_code == 200, response.text


async def test_rotatsiyadan_keyin_ESKI_kalit_grace_oynasida_ISHLAYDI(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    api_key: tuple[ApiKey, str],
) -> None:
    """Eski kalit darhol O'LMAYDI — mijozning integratsiyasi uzilmaydi.

    Bu rotatsiyaning butun ma'nosi: mijozning CI, serveri va lokal
    muhiti bir xil kalitni ishlatayotgan bo'lishi mumkin. Darhol bekor
    qilish ularning hammasini bir vaqtda uzadi.
    """
    record, old_raw = api_key
    await client.post(f"{api_prefix}/api-keys/{record.id}/rotate", headers=auth_headers)

    response = await client.get(f"{api_prefix}/jobs", headers={HEADER_API_KEY: old_raw})

    assert response.status_code == 200, response.text


async def test_grace_tugagandan_keyin_ESKI_kalit_ISHLAMAYDI(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    api_key: tuple[ApiKey, str],
) -> None:
    """Grace tugasa eski kalit 401 — aks holda u ABADIY ochiq qolardi.

    Muddat o'tgandan keyin `previous_key_hash` DB'da qolishi mumkin
    (tozalash kechikadi), shuning uchun VAQT tekshiruvi hal qiluvchi
    ahamiyatga ega. Shu test busiz eng xavfli xato jim o'tib ketardi.
    """
    record, old_raw = api_key
    key_id = record.id
    await client.post(f"{api_prefix}/api-keys/{key_id}/rotate", headers=auth_headers)

    # Grace oynasini "o'tkazamiz": muddatni orqaga suramiz.
    fresh = await db_session.get(type(record), key_id)
    assert fresh is not None
    fresh.previous_key_expires_at = utcnow() - timedelta(seconds=1)
    await db_session.commit()

    response = await client.get(f"{api_prefix}/jobs", headers={HEADER_API_KEY: old_raw})

    assert response.status_code == 401, response.text


async def test_takroriy_rotatsiya_birinchi_eski_kalitni_oldiradi(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    api_key: tuple[ApiKey, str],
) -> None:
    """Ikki marta rotatsiya -> BIRINCHI eski kalit darhol o'ladi.

    Bitta `previous_key_hash` ustuni bor, ya'ni zanjir uzaytirilmaydi.
    Bu ataylab: aks holda sizib ketgan kalit har rotatsiyada yana
    24 soat qo'shib, uzoq vaqt ochiq qolardi.
    """
    record, first_raw = api_key
    key_id = record.id

    first = await client.post(f"{api_prefix}/api-keys/{key_id}/rotate", headers=auth_headers)
    second_raw = first.json()["key"]
    second = await client.post(f"{api_prefix}/api-keys/{key_id}/rotate", headers=auth_headers)
    third_raw = second.json()["key"]

    # Eng yangi — ishlaydi.
    assert (
        await client.get(f"{api_prefix}/jobs", headers={HEADER_API_KEY: third_raw})
    ).status_code == 200
    # Oldingi — grace oynasida, ishlaydi.
    assert (
        await client.get(f"{api_prefix}/jobs", headers={HEADER_API_KEY: second_raw})
    ).status_code == 200
    # BIRINCHI — endi ishlamaydi.
    assert (
        await client.get(f"{api_prefix}/jobs", headers={HEADER_API_KEY: first_raw})
    ).status_code == 401


async def test_grace_muddati_sozlamaga_mos(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    api_key: tuple[ApiKey, str],
) -> None:
    """`old_key_valid_until` ≈ hozir + `API_KEY_ROTATION_GRACE_HOURS`."""
    record, _ = api_key
    before = utcnow()

    body = (
        await client.post(f"{api_prefix}/api-keys/{record.id}/rotate", headers=auth_headers)
    ).json()

    expected = before + timedelta(hours=API_KEY_ROTATION_GRACE_HOURS)
    actual = body["old_key_valid_until"]
    # Soniyalardagi farq — test bajarilish vaqti hisobga olinadi.
    assert actual[:13] == isoformat(expected)[:13], f"{actual} vs {isoformat(expected)}"


# ---------------------------------------------------------------------------
# Bekor qilingan kalit — o'zgartirish amallari
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("put", "scopes", {"scopes": ["jobs:read"]}),
        ("put", "expiry", {"expires_at": None}),
        ("post", "rotate", None),
    ],
)
async def test_bekor_qilingan_kalitda_409(
    client: httpx.AsyncClient,
    api_prefix: str,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
    api_key: tuple[ApiKey, str],
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    """Bekor qilish YAKUNIY — huquq, muddat va rotatsiya qo'llanmaydi.

    Uni "orqaga qaytarish" mijozni chalg'itadi: kalit qiymati baribir
    yo'qolgan. Javobda yangi kalit yaratish taklif qilinadi.
    """
    record, _ = api_key
    record.revoked_at = utcnow()
    await db_session.commit()
    key_id = record.id

    response = await client.request(
        method.upper(),
        f"{api_prefix}/api-keys/{key_id}/{path}",
        headers=auth_headers,
        json=body,
    )

    assert response.status_code == 409, response.text
    assert "API_KEY_REVOKED" in response.text
