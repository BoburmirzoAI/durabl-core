"""Durabl — xavfsizlik yordamchilari: parol hash, JWT, API kalit, webhook imzo.

Dizayn qarorlari:

* **Parol** — bcrypt. bcrypt 72 baytdan uzun parolni kesib tashlaydi, shuning
  uchun avval SHA-256 + base64 qilib "pre-hash" qilinadi (uzun parol ham
  to'liq hisobga olinadi).
* **API kalit** — mijozga bir marta to'liq ko'rsatiladi. DB'da bcrypt emas,
  SHA-256 saqlanadi: kalit yuqori entropiyali tasodifiy qiymat, shuning uchun
  sekin hash shart emas, lekin O(1) qidiruv juda muhim (har so'rovda tekshiriladi).
* **JWT** — HS256, `sub` = user id, `type` = access|refresh, `jti` bilan.
* **Webhook imzo** — Stripe uslubidagi `t=<ts>,v1=<hmac>`: timestamp imzoga
  kiritilgani uchun replay hujumi oldini oladi.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid
from datetime import timedelta
from typing import Any, Final, Literal

import bcrypt
import jwt

from app.config import settings
from app.exceptions import InvalidTokenError, TokenExpiredError, ValidationError
from app.utils.time_utils import utcnow

TokenType = Literal["access", "refresh"]

_BCRYPT_PREHASH_ENCODING: Final = "utf-8"


# ---------------------------------------------------------------------------
# Parol
# ---------------------------------------------------------------------------


def _prehash_password(password: str) -> bytes:
    """Parolni bcrypt'ning 72-bayt chegarasiga sig'dirish uchun SHA-256 + base64."""
    digest = hashlib.sha256(password.encode(_BCRYPT_PREHASH_ENCODING)).digest()
    return base64.b64encode(digest)  # 44 bayt — har doim 72'dan kichik


def hash_password(password: str) -> str:
    """Parolni bcrypt bilan hash qiladi."""
    if not password:
        raise ValidationError("Parol bo'sh bo'lishi mumkin emas")
    salt = bcrypt.gensalt(rounds=settings.BCRYPT_ROUNDS)
    return bcrypt.hashpw(_prehash_password(password), salt).decode("ascii")


def verify_password(password: str, hashed: str | None) -> bool:
    """Parol hash'ga mos keladimi. Vaqt hujumiga chidamli (bcrypt ichida)."""
    if not password or not hashed:
        return False
    try:
        return bcrypt.checkpw(_prehash_password(password), hashed.encode("ascii"))
    except (ValueError, TypeError):
        # Buzilgan hash — autentifikatsiya muvaffaqiyatsiz, lekin xato tashlamaymiz
        return False


def validate_password_strength(password: str) -> None:
    """Parol minimal talablarga javob beradimi; aks holda `ValidationError`."""
    violations: list[str] = []
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        violations.append(f"kamida {settings.PASSWORD_MIN_LENGTH} belgi bo'lishi kerak")
    if not any(char.isalpha() for char in password):
        violations.append("kamida bitta harf bo'lishi kerak")
    if not any(char.isdigit() for char in password):
        violations.append("kamida bitta raqam bo'lishi kerak")
    if violations:
        raise ValidationError(
            "Parol talablarga javob bermaydi: " + ", ".join(violations),
            details={"violations": violations},
        )


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------


def create_token(
    subject: str | uuid.UUID,
    *,
    token_type: TokenType = "access",
    expires_delta: timedelta | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """JWT yaratadi.

    Args:
        subject: Foydalanuvchi ID (`sub` claim).
        token_type: `access` yoki `refresh`.
        expires_delta: Maxsus muddat; berilmasa sozlamadan olinadi.
        extra_claims: Qo'shimcha claim'lar (masalan `is_admin`).
    """
    now = utcnow()
    if expires_delta is None:
        expires_delta = (
            timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
            if token_type == "access"
            else timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        )

    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": uuid.uuid4().hex,
        "iss": settings.APP_NAME.lower(),
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(
    subject: str | uuid.UUID, **kwargs: Any
) -> str:
    """Qisqa muddatli access token."""
    return create_token(subject, token_type="access", **kwargs)


def create_refresh_token(subject: str | uuid.UUID, **kwargs: Any) -> str:
    """Uzoq muddatli refresh token."""
    return create_token(subject, token_type="refresh", **kwargs)


def decode_token(token: str, *, expected_type: TokenType | None = None) -> dict[str, Any]:
    """JWT'ni dekod qiladi va tekshiradi.

    Raises:
        TokenExpiredError: Muddat tugagan.
        InvalidTokenError: Imzo/format/tur noto'g'ri.
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            issuer=settings.APP_NAME.lower(),
            options={"require": ["exp", "sub", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError() from exc
    except jwt.InvalidTokenError as exc:
        raise InvalidTokenError(f"Token yaroqsiz: {exc}") from exc

    if expected_type is not None and payload.get("type") != expected_type:
        raise InvalidTokenError(
            f"'{expected_type}' turidagi token kutilgan, '{payload.get('type')}' keldi"
        )
    return payload


def token_subject(token: str, *, expected_type: TokenType | None = "access") -> uuid.UUID:
    """Tokendan foydalanuvchi ID'sini ajratib oladi."""
    payload = decode_token(token, expected_type=expected_type)
    raw = payload.get("sub")
    try:
        return uuid.UUID(str(raw))
    except (ValueError, TypeError) as exc:
        raise InvalidTokenError("Token `sub` maydoni UUID emas") from exc


# ---------------------------------------------------------------------------
# API kalitlar
# ---------------------------------------------------------------------------

#: Mijozga ko'rsatiladigan prefiks uzunligi (`durabl_` + 8 belgi)
API_KEY_DISPLAY_PREFIX_LENGTH: Final = 8


class GeneratedApiKey:
    """Yangi yaratilgan API kalit — faqat bir marta qaytariladi."""

    __slots__ = ("key_hash", "key_prefix", "last_four", "raw")

    def __init__(self, raw: str, key_hash: str, key_prefix: str, last_four: str) -> None:
        self.raw = raw            #: To'liq kalit — faqat yaratilganda ko'rsatiladi
        self.key_hash = key_hash  #: DB'ga saqlanadi
        self.key_prefix = key_prefix  #: Ro'yxatda ko'rsatish uchun
        self.last_four = last_four    #: `durabl_ab...wxyz` ko'rinishi uchun

    def masked(self) -> str:
        """Ro'yxatda ko'rsatiladigan niqoblangan ko'rinish."""
        return f"{self.key_prefix}{'*' * 8}{self.last_four}"


def generate_api_key() -> GeneratedApiKey:
    """Yangi API kalit yaratadi: `durabl_<43 belgi base64url>`."""
    random_part = secrets.token_urlsafe(settings.API_KEY_RANDOM_BYTES)
    raw = f"{settings.API_KEY_PREFIX}{random_part}"
    return GeneratedApiKey(
        raw=raw,
        key_hash=hash_api_key(raw),
        key_prefix=raw[: len(settings.API_KEY_PREFIX) + API_KEY_DISPLAY_PREFIX_LENGTH],
        last_four=raw[-4:],
    )


def hash_api_key(raw_key: str) -> str:
    """API kalitni SHA-256 bilan hash qiladi (DB'da qidirish uchun deterministik)."""
    return hashlib.sha256(raw_key.strip().encode("utf-8")).hexdigest()


def is_api_key_format(value: str) -> bool:
    """Berilgan matn API kalitga o'xshaydimi (JWT'dan ajratish uchun)."""
    return value.startswith(settings.API_KEY_PREFIX)


def mask_api_key(raw_key: str) -> str:
    """Logda ko'rsatish uchun kalitni niqoblaydi."""
    if len(raw_key) <= 12:
        return "*" * len(raw_key)
    head = raw_key[: len(settings.API_KEY_PREFIX) + API_KEY_DISPLAY_PREFIX_LENGTH]
    return f"{head}{'*' * 8}{raw_key[-4:]}"


# ---------------------------------------------------------------------------
# Webhook imzosi
# ---------------------------------------------------------------------------


def generate_webhook_secret() -> str:
    """Webhook uchun maxfiy kalit (`whsec_...`)."""
    return f"whsec_{secrets.token_urlsafe(32)}"


def sign_webhook(payload: str | bytes, secret: str, *, timestamp: int | None = None) -> str:
    """Webhook imzosini hisoblaydi.

    Format: `t=<unix_ts>,v1=<hex_hmac_sha256>`
    Imzolanadigan matn: `<unix_ts>.<payload>` — timestamp imzoga kirgani uchun
    eski so'rovni qayta yuborish (replay) ishlamaydi.
    """
    ts = timestamp if timestamp is not None else int(utcnow().timestamp())
    body = payload.encode("utf-8") if isinstance(payload, str) else payload
    signed_payload = f"{ts}.".encode() + body
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    return f"t={ts},v1={digest}"


def verify_webhook_signature(
    payload: str | bytes,
    signature_header: str,
    secret: str,
    *,
    tolerance_seconds: int | None = None,
) -> bool:
    """Webhook imzosini tekshiradi (SDK va test endpointi ishlatadi)."""
    tolerance = (
        tolerance_seconds
        if tolerance_seconds is not None
        else settings.WEBHOOK_SIGNATURE_TOLERANCE_SECONDS
    )
    parts: dict[str, str] = {}
    for chunk in signature_header.split(","):
        key, _, value = chunk.strip().partition("=")
        if key and value:
            parts[key] = value

    raw_ts, received = parts.get("t"), parts.get("v1")
    if not raw_ts or not received:
        return False
    try:
        ts = int(raw_ts)
    except ValueError:
        return False

    if tolerance > 0 and abs(int(utcnow().timestamp()) - ts) > tolerance:
        return False  # Imzo juda eski yoki kelajakdan

    expected = sign_webhook(payload, secret, timestamp=ts)
    expected_digest = expected.split("v1=", 1)[1]
    return hmac.compare_digest(expected_digest, received)


# ---------------------------------------------------------------------------
# Umumiy
# ---------------------------------------------------------------------------


def constant_time_compare(left: str, right: str) -> bool:
    """Vaqt hujumiga chidamli matn solishtirish."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def generate_correlation_id() -> str:
    """So'rov zanjirini kuzatish uchun identifikator."""
    return uuid.uuid4().hex


def generate_token(length: int = 32) -> str:
    """Umumiy maqsadli tasodifiy token (email tasdiqlash, parol tiklash)."""
    return secrets.token_urlsafe(length)


__all__ = [
    "API_KEY_DISPLAY_PREFIX_LENGTH",
    "GeneratedApiKey",
    "TokenType",
    "constant_time_compare",
    "create_access_token",
    "create_refresh_token",
    "create_token",
    "decode_token",
    "generate_api_key",
    "generate_correlation_id",
    "generate_token",
    "generate_webhook_secret",
    "hash_api_key",
    "hash_password",
    "is_api_key_format",
    "mask_api_key",
    "sign_webhook",
    "token_subject",
    "validate_password_strength",
    "verify_password",
    "verify_webhook_signature",
]
