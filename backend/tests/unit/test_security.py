"""Durabl — `app/utils/security.py` birlik testlari.

Bu modulning har bir xatosi xavfsizlik tuynugi:

* bcrypt'ning 72-bayt chegarasi — SHA-256 pre-hash bo'lmasa, 80 belgili
  parolning oxirgi 8 belgisi HISOBGA OLINMAYDI (ya'ni boshqa parol ham
  o'tib ketardi);
* JWT `type` claim'i tekshirilmasa, refresh token bilan API'ga kirish
  mumkin bo'lardi;
* webhook imzosida timestamp bo'lmasa, eski so'rovni qayta yuborish
  (replay) ishlardi.

`BCRYPT_ROUNDS=4` (conftest) — testlar tez ishlashi uchun; production'da 12.
"""

from __future__ import annotations

import time
import uuid
from datetime import timedelta

import pytest
from app.config import settings
from app.exceptions import InvalidTokenError, TokenExpiredError, ValidationError
from app.utils.security import (
    API_KEY_DISPLAY_PREFIX_LENGTH,
    constant_time_compare,
    create_access_token,
    create_refresh_token,
    create_token,
    decode_token,
    generate_api_key,
    generate_correlation_id,
    generate_token,
    generate_webhook_secret,
    hash_api_key,
    hash_password,
    is_api_key_format,
    mask_api_key,
    sign_webhook,
    token_subject,
    validate_password_strength,
    verify_password,
    verify_webhook_signature,
)

pytestmark = pytest.mark.unit

PASSWORD = "Parol12345"
SECRET = "whsec_test_secret"
PAYLOAD = '{"job_id":"abc","status":"success"}'


# ---------------------------------------------------------------------------
# Parol
# ---------------------------------------------------------------------------


def test_hash_password_bcrypt_formatida() -> None:
    """Hash bcrypt belgisi bilan boshlanadi va xom parolni saqlamaydi."""
    hashed = hash_password(PASSWORD)
    assert hashed.startswith("$2")
    assert PASSWORD not in hashed


def test_hash_password_har_chaqiruvda_boshqa_tuz() -> None:
    """Bir xil parol har safar BOSHQA hash beradi (tasodifiy salt)."""
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_verify_password_togri_parol() -> None:
    """To'g'ri parol tasdiqlanadi."""
    assert verify_password(PASSWORD, hash_password(PASSWORD)) is True


def test_verify_password_notogri_parol() -> None:
    """Noto'g'ri parol rad etiladi."""
    assert verify_password("BoshqaParol1", hash_password(PASSWORD)) is False


def test_hash_password_bosh_parol_xato() -> None:
    """Bo'sh parol hash qilinmaydi."""
    with pytest.raises(ValidationError):
        hash_password("")


@pytest.mark.parametrize("hashed", [None, "", "buzilgan-hash", "$2b$04$qisqa"])
def test_verify_password_yaroqsiz_hash_false(hashed: str | None) -> None:
    """Buzilgan yoki bo'sh hash xato TASHLAMAYDI, faqat `False` beradi."""
    assert verify_password(PASSWORD, hashed) is False


def test_verify_password_bosh_parol_false() -> None:
    """Bo'sh parol hech qachon mos kelmaydi."""
    assert verify_password("", hash_password(PASSWORD)) is False


def test_uzun_parol_toliq_hisobga_olinadi() -> None:
    """KRITIK: 72 baytdan uzun parolning OXIRI ham ahamiyatli.

    bcrypt o'zi 72 baytdan keyinini kesib tashlaydi; `_prehash_password`
    bo'lmasa quyidagi ikki parol AYNI hash bergan bo'lardi.
    """
    base = "A1" + "x" * 80
    other = base[:-1] + "y"  # faqat OXIRGI belgi farq qiladi
    hashed = hash_password(base)
    assert verify_password(base, hashed) is True
    assert verify_password(other, hashed) is False


@pytest.mark.parametrize("password", ["Parol123", "a1" * 5, "Juda-Uzun-Parol-2026"])
def test_validate_password_strength_otadi(password: str) -> None:
    """Harf va raqam bor, uzunlik yetarli — talablarga javob beradi."""
    validate_password_strength(password)


@pytest.mark.parametrize(
    ("password", "sabab"),
    [
        ("a1", "qisqa"),
        ("12345678", "harf yo'q"),
        ("parolparol", "raqam yo'q"),
        ("", "bo'sh"),
    ],
)
def test_validate_password_strength_rad_etadi(password: str, sabab: str) -> None:
    """Talabga javob bermagan parol `ValidationError` beradi."""
    with pytest.raises(ValidationError):
        validate_password_strength(password)


def test_validate_password_strength_buzilishlarni_qaytaradi() -> None:
    """Xato tafsilotida buzilishlar ro'yxati bo'ladi (422 javobi uchun)."""
    with pytest.raises(ValidationError) as info:
        validate_password_strength("ab")
    details = info.value.details or {}
    assert len(details.get("violations", [])) == 2  # qisqa + raqam yo'q


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def test_create_access_token_claimlari() -> None:
    """Access token majburiy claim'lar bilan yasaladi."""
    subject = uuid.uuid4()
    payload = decode_token(create_access_token(subject))
    assert payload["sub"] == str(subject)
    assert payload["type"] == "access"
    assert payload["iss"] == settings.APP_NAME.lower()
    assert "jti" in payload
    assert payload["exp"] > payload["iat"]


def test_create_refresh_token_turi() -> None:
    """Refresh token `type=refresh` bilan yasaladi."""
    assert decode_token(create_refresh_token(uuid.uuid4()))["type"] == "refresh"


def test_refresh_token_muddati_accessdan_uzun() -> None:
    """Refresh token access tokendan uzoqroq yashaydi."""
    subject = uuid.uuid4()
    access = decode_token(create_access_token(subject))
    refresh = decode_token(create_refresh_token(subject))
    assert refresh["exp"] > access["exp"]


def test_decode_token_kutilgan_tur_mos() -> None:
    """Tur mos kelsa dekod muvaffaqiyatli."""
    token = create_access_token(uuid.uuid4())
    assert decode_token(token, expected_type="access")["type"] == "access"


def test_decode_token_notogri_tur_xato() -> None:
    """KRITIK: refresh token access o'rniga ishlatilmaydi."""
    token = create_refresh_token(uuid.uuid4())
    with pytest.raises(InvalidTokenError):
        decode_token(token, expected_type="access")


def test_decode_token_muddati_otgan() -> None:
    """Muddati o'tgan token `TokenExpiredError` beradi."""
    token = create_token(uuid.uuid4(), expires_delta=timedelta(seconds=-10))
    with pytest.raises(TokenExpiredError):
        decode_token(token)


def test_decode_token_imzosi_buzilgan() -> None:
    """Imzosi o'zgartirilgan token qabul qilinmaydi."""
    token = create_access_token(uuid.uuid4())
    tampered = token[:-4] + ("abcd" if not token.endswith("abcd") else "efgh")
    with pytest.raises(InvalidTokenError):
        decode_token(tampered)


def test_decode_token_boshqa_kalit_bilan_imzolangan(monkeypatch: pytest.MonkeyPatch) -> None:
    """Boshqa `SECRET_KEY` bilan yasalgan token rad etiladi."""
    monkeypatch.setattr(settings, "SECRET_KEY", "boshqa-maxfiy-kalit-kamida-32-belgi")
    foreign = create_access_token(uuid.uuid4())
    monkeypatch.undo()
    with pytest.raises(InvalidTokenError):
        decode_token(foreign)


@pytest.mark.parametrize("token", ["", "abc", "a.b.c", "Bearer xyz"])
def test_decode_token_yaroqsiz_shakl(token: str) -> None:
    """JWT bo'lmagan matn `InvalidTokenError` beradi."""
    with pytest.raises(InvalidTokenError):
        decode_token(token)


def test_create_token_qoshimcha_claim() -> None:
    """`extra_claims` tokenga qo'shiladi (masalan `is_admin`)."""
    token = create_token(uuid.uuid4(), extra_claims={"is_admin": True})
    assert decode_token(token)["is_admin"] is True


def test_token_subject_uuid_qaytaradi() -> None:
    """`token_subject` `sub` ni UUID ko'rinishida beradi."""
    subject = uuid.uuid4()
    assert token_subject(create_access_token(subject)) == subject


def test_token_subject_uuid_bolmasa_xato() -> None:
    """`sub` UUID bo'lmasa `InvalidTokenError`."""
    token = create_token("men-uuid-emasman")
    with pytest.raises(InvalidTokenError):
        token_subject(token)


def test_token_subject_refresh_turini_talab_qiladi() -> None:
    """`expected_type` bilan refresh tokendan ham `sub` olinadi."""
    subject = uuid.uuid4()
    token = create_refresh_token(subject)
    assert token_subject(token, expected_type="refresh") == subject


# ---------------------------------------------------------------------------
# API kalitlar
# ---------------------------------------------------------------------------


def test_generate_api_key_shakli() -> None:
    """Kalit `durabl_` prefiksi bilan boshlanadi va yetarli uzun."""
    generated = generate_api_key()
    assert generated.raw.startswith(settings.API_KEY_PREFIX)
    assert len(generated.raw) > 40
    assert generated.last_four == generated.raw[-4:]
    assert (
        generated.key_prefix
        == generated.raw[: len(settings.API_KEY_PREFIX) + API_KEY_DISPLAY_PREFIX_LENGTH]
    )


def test_generate_api_key_takrorlanmaydi() -> None:
    """Har chaqiruvda boshqa kalit (tasodifiylik)."""
    assert len({generate_api_key().raw for _ in range(50)}) == 50


def test_generate_api_key_hash_mos() -> None:
    """Obyektdagi hash `hash_api_key()` natijasiga teng."""
    generated = generate_api_key()
    assert generated.key_hash == hash_api_key(generated.raw)
    assert len(generated.key_hash) == 64


def test_hash_api_key_deterministik() -> None:
    """Bir xil kalit har doim bir xil hash beradi (DB'da qidirish uchun)."""
    generated = generate_api_key()
    assert hash_api_key(generated.raw) == hash_api_key(generated.raw)


def test_hash_api_key_bosh_joyni_tashlaydi() -> None:
    """Header'dan kelgan ortiqcha bo'sh joy natijaga ta'sir qilmaydi."""
    raw = generate_api_key().raw
    assert hash_api_key(f"  {raw}  ") == hash_api_key(raw)


def test_hash_api_key_turli_kalitlar_turli_hash() -> None:
    """Turli kalitlar to'qnashmaydi."""
    assert hash_api_key("durabl_a") != hash_api_key("durabl_b")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("durabl_abc", True), ("eyJhbGciOi.xxx.yyy", False), ("", False), ("durab_abc", False)],
)
def test_is_api_key_format(value: str, expected: bool) -> None:
    """API kalit JWT'dan prefiks bo'yicha ajratiladi."""
    assert is_api_key_format(value) is expected


def test_mask_api_key_maxfiy_qismni_yashiradi() -> None:
    """Niqoblangan ko'rinishda kalitning o'rtasi yo'q."""
    raw = generate_api_key().raw
    masked = mask_api_key(raw)
    assert masked.startswith(settings.API_KEY_PREFIX)
    assert masked.endswith(raw[-4:])
    assert raw not in masked
    assert "*" in masked


def test_mask_api_key_qisqa_qiymat_toliq_yashiriladi() -> None:
    """Qisqa qiymat butunlay yulduzchaga aylanadi (ma'lumot chiqmaydi)."""
    assert mask_api_key("durabl_1") == "*" * 8


def test_generated_api_key_masked_metodi() -> None:
    """`GeneratedApiKey.masked()` ro'yxatda ko'rsatish uchun shakl beradi."""
    generated = generate_api_key()
    masked = generated.masked()
    assert masked.startswith(generated.key_prefix)
    assert masked.endswith(generated.last_four)


# ---------------------------------------------------------------------------
# Webhook imzosi
# ---------------------------------------------------------------------------


def test_sign_webhook_shakli() -> None:
    """Imzo `t=<ts>,v1=<hex>` ko'rinishida (Stripe uslubi)."""
    signature = sign_webhook(PAYLOAD, SECRET, timestamp=1_700_000_000)
    assert signature.startswith("t=1700000000,v1=")
    digest = signature.split("v1=", 1)[1]
    assert len(digest) == 64
    int(digest, 16)


def test_verify_webhook_signature_togri() -> None:
    """O'z imzosi tasdiqlanadi."""
    signature = sign_webhook(PAYLOAD, SECRET)
    assert verify_webhook_signature(PAYLOAD, signature, SECRET) is True


def test_verify_webhook_signature_baytlar_bilan_ham() -> None:
    """Tana `bytes` ko'rinishida kelsa ham ishlaydi (HTTP tanasi)."""
    body = PAYLOAD.encode("utf-8")
    assert verify_webhook_signature(body, sign_webhook(body, SECRET), SECRET) is True


def test_verify_webhook_signature_notogri_maxfiy_kalit() -> None:
    """Boshqa kalit bilan tekshirish muvaffaqiyatsiz."""
    signature = sign_webhook(PAYLOAD, SECRET)
    assert verify_webhook_signature(PAYLOAD, signature, "boshqa-kalit") is False


def test_verify_webhook_signature_ozgartirilgan_tana() -> None:
    """Tana o'zgarsa imzo mos kelmaydi."""
    signature = sign_webhook(PAYLOAD, SECRET)
    assert verify_webhook_signature(PAYLOAD + " ", signature, SECRET) is False


def test_verify_webhook_signature_eskirgan_imzo() -> None:
    """Tolerantlikdan eski imzo rad etiladi (replay himoyasi)."""
    old = int(time.time()) - 10_000
    signature = sign_webhook(PAYLOAD, SECRET, timestamp=old)
    assert verify_webhook_signature(PAYLOAD, signature, SECRET, tolerance_seconds=300) is False


def test_verify_webhook_signature_kelajakdan_kelgan_imzo() -> None:
    """Kelajakdan kelgan imzo ham rad etiladi (soat buzilgan yoki hujum)."""
    future = int(time.time()) + 10_000
    signature = sign_webhook(PAYLOAD, SECRET, timestamp=future)
    assert verify_webhook_signature(PAYLOAD, signature, SECRET, tolerance_seconds=300) is False


def test_verify_webhook_signature_tolerantlik_nol_bolsa_vaqt_tekshirilmaydi() -> None:
    """`tolerance_seconds=0` — vaqt tekshiruvi o'chadi (SDK test rejimi)."""
    old = int(time.time()) - 10_000
    signature = sign_webhook(PAYLOAD, SECRET, timestamp=old)
    assert verify_webhook_signature(PAYLOAD, signature, SECRET, tolerance_seconds=0) is True


@pytest.mark.parametrize(
    "header",
    ["", "v1=abc", "t=123", "t=abc,v1=def", "salom", "t=,v1="],
)
def test_verify_webhook_signature_yaroqsiz_header(header: str) -> None:
    """Buzilgan header xato TASHLAMAYDI, faqat `False` beradi."""
    assert verify_webhook_signature(PAYLOAD, header, SECRET) is False


def test_generate_webhook_secret_shakli() -> None:
    """Webhook maxfiy kaliti `whsec_` prefiksi bilan va takrorlanmas."""
    secrets_set = {generate_webhook_secret() for _ in range(20)}
    assert len(secrets_set) == 20
    assert all(value.startswith("whsec_") for value in secrets_set)


# ---------------------------------------------------------------------------
# Umumiy yordamchilar
# ---------------------------------------------------------------------------


def test_constant_time_compare_teng_qiymatlar() -> None:
    """Bir xil matn `True` beradi."""
    assert constant_time_compare("durabl", "durabl") is True


@pytest.mark.parametrize(
    ("left", "right"), [("a", "b"), ("abc", "abd"), ("abc", "abcd"), ("", "a")]
)
def test_constant_time_compare_turli_qiymatlar(left: str, right: str) -> None:
    """Farqli matnlar (uzunligi boshqa bo'lsa ham) `False` beradi."""
    assert constant_time_compare(left, right) is False


def test_generate_correlation_id_shakli() -> None:
    """Korrelyatsiya ID — 32 belgili hex, takrorlanmas."""
    values = {generate_correlation_id() for _ in range(50)}
    assert len(values) == 50
    assert all(len(value) == 32 for value in values)


def test_generate_token_uzunligi_sozlanadi() -> None:
    """Token uzunligi argument bilan boshqariladi."""
    assert len(generate_token(8)) < len(generate_token(64))
