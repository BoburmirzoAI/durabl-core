"""Durabl — autentifikatsiya va API kalit boshqaruvi.

Bu service ikki xil "kim ekanligini aniqlash" yo'lini bir joyda jamlaydi:

1. **JWT** (`resolve_token`) — brauzer va dashboard uchun. Qisqa muddatli
   access token + uzoq muddatli refresh token juftligi beriladi.
2. **API kalit** (`resolve_api_key`) — SDK, CI va server-to-server uchun.
   Xom kalit DB'da SAQLANMAYDI: faqat SHA-256 hash'i yoziladi, shuning uchun
   kalit mijozga BIR MARTA — yaratish javobida — ko'rsatiladi.

**Vaqt hujumidan himoya.** `authenticate()` foydalanuvchi topilmaganda ham
`verify_password()` ni soxta (lekin haqiqiy bcrypt) hash bilan chaqiradi.
Aks holda javob vaqti "email ro'yxatdan o'tganmi yo'qmi" degan savolga javob
berib qo'yardi (hisob sanab chiqish — account enumeration).

**Tranzaksiya chegarasi.** Public metodlar o'z yozuvini o'zi `commit` qiladi
(`api` qatlami qo'shimcha commit chaqirmaydi). `fastapi` import QILINMAYDI va
`HTTPException` tashlanmaydi — ayni shu kod worker protsesslarida ham ishlaydi.

**Log qoidasi.** Parol, xom API kalit va token HECH QACHON log qilinmaydi;
kalit faqat niqoblangan ko'rinishda (`mask_api_key`) yoziladi.
"""

from __future__ import annotations

import uuid
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.exceptions import (
    ApiKeyNotFoundError,
    DatabaseError,
    DuplicateEmailError,
    InactiveUserError,
    InvalidApiKeyError,
    InvalidCredentialsError,
    InvalidTokenError,
    UserNotFoundError,
    ValidationError,
)
from app.logging_config import get_logger
from app.models.api_key import ApiKey
from app.models.user import User
from app.repositories.api_key_repo import ApiKeyRepository
from app.repositories.subscription_repo import SubscriptionRepository
from app.repositories.user_repo import UserRepository
from app.schemas.api_key import ApiKeyCreate
from app.schemas.auth import (
    LoginRequest,
    PasswordChangeRequest,
    RegisterRequest,
    TokenResponse,
)
from app.utils.security import (
    create_access_token,
    create_refresh_token,
    generate_api_key,
    hash_api_key,
    hash_password,
    is_api_key_format,
    mask_api_key,
    token_subject,
    validate_password_strength,
    verify_password,
)
from app.utils.time_utils import ensure_utc, utcnow

logger = get_logger(__name__)

#: Bitta foydalanuvchida bir vaqtda faol bo'lishi mumkin bo'lgan kalitlar soni.
#: Cheklov bor, chunki har bir kalit — alohida sirli ma'lumot: ularning soni
#: ko'paygani sari "kalit o'g'irlandi" xavfi va audit yuki ham ortadi.
MAX_ACTIVE_API_KEYS: int = 20

#: `last_used_at` ni qayta yozish oralig'i (soniya).
#: Har bir so'rovda `UPDATE api_keys SET last_used_at = ...` qilish eng ko'p
#: bajariladigan so'rovga keraksiz yozish qo'shadi (va WAL/replikatsiyani
#: shishiradi). Bizga "kalit taxminan qachon ishlatilgan" yetarli.
API_KEY_TOUCH_INTERVAL_SECONDS: float = 60.0

#: Soxta hash uchun parol — hech qachon haqiqiy hisobga mos kelmaydi.
_TIMING_GUARD_PASSWORD = "durabl-timing-guard-not-a-real-password"


@lru_cache(maxsize=1)
def _timing_guard_hash() -> str:
    """Foydalanuvchi topilmaganda solishtiriladigan soxta bcrypt hash.

    Dangasa (lazy) hisoblanadi va keshlanadi: modul import qilinganda
    bcrypt'ni ishga solish import vaqtini `BCRYPT_ROUNDS`ga bog'lab qo'yardi.
    Hash haqiqiy `settings.BCRYPT_ROUNDS` bilan yasaladi — shuning uchun
    tekshiruv vaqti haqiqiy parol tekshiruvi bilan bir xil.
    """
    return hash_password(_TIMING_GUARD_PASSWORD)


class AuthService:
    """Foydalanuvchi autentifikatsiyasi, token va API kalitlar."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)
        self.api_keys = ApiKeyRepository(session)
        self.subscriptions = SubscriptionRepository(session)

    # ------------------------------------------------------------------
    # Ro'yxatdan o'tish va kirish
    # ------------------------------------------------------------------

    async def register(self, data: RegisterRequest) -> User:
        """Yangi foydalanuvchi yaratadi va unga FREE obuna beradi.

        Qadamlar: email bandligini tekshirish -> parol kuchini tekshirish ->
        hash -> foydalanuvchi -> obuna -> `commit`.

        `settings.BOOTSTRAP_ADMIN_EMAIL` bilan mos kelgan email `is_admin=True`
        bo'lib ro'yxatdan o'tadi — tizimning birinchi administratori shu
        yo'l bilan yaratiladi (boshqa hech qanday yo'l bilan admin bo'lib
        ro'yxatdan o'tish mumkin emas).

        Raises:
            DuplicateEmailError: Email allaqachon band.
            ValidationError: Parol talablarga javob bermaydi.
        """
        email = self._normalize_email(data.email)

        if await self.users.email_exists(email):
            raise DuplicateEmailError(details={"email": email})

        validate_password_strength(data.password)

        is_admin = self._is_bootstrap_admin(email)
        try:
            user = await self.users.create(
                email=email,
                hashed_password=hash_password(data.password),
                full_name=data.full_name,
                is_active=True,
                is_admin=is_admin,
            )
        except DatabaseError as exc:
            # Poyga (race): ikki so'rov bir vaqtda bir xil email bilan keldi.
            # `_flush` IntegrityError'ni `DatabaseError`ga o'rab rollback qilgan,
            # shuning uchun hozir toza sessiyada qayta tekshirish mumkin.
            if await self.users.email_exists(email):
                raise DuplicateEmailError(details={"email": email}) from exc
            raise

        # Har bir foydalanuvchining obunasi BORLIGI kafolatlanadi — kvota
        # tekshiruvi (`BillingService.check_quota`) shunga tayanadi.
        await self.subscriptions.ensure_for_user(user.id)

        await self.session.commit()
        logger.info(
            "foydalanuvchi ro'yxatdan o'tdi",
            user_id=str(user.id),
            email=user.email,
            is_admin=user.is_admin,
        )
        return user

    async def authenticate(self, email: str, password: str) -> User:
        """Email va parolni tekshiradi; muvaffaqiyatda `last_login_at` yoziladi.

        Foydalanuvchi topilmasa ham parol SOXTA hash bilan tekshiriladi —
        javob vaqti email mavjudligini oshkor qilmasligi uchun (vaqt hujumi).

        Public metod: `last_login_at` yozuvini o'zi `commit` qiladi.

        Raises:
            InvalidCredentialsError: Email yoki parol noto'g'ri.
            InactiveUserError: Hisob bloklangan.
        """
        normalized = self._normalize_email(email)
        user = await self.users.get_by_email(normalized)

        stored_hash = user.hashed_password if user is not None else _timing_guard_hash()
        password_ok = verify_password(password, stored_hash)

        if user is None or not password_ok:
            logger.warning("muvaffaqiyatsiz kirish urinishi", email=normalized)
            raise InvalidCredentialsError()

        if not user.is_active:
            logger.warning(
                "bloklangan hisobga kirish urinishi",
                user_id=str(user.id),
                email=user.email,
            )
            raise InactiveUserError()

        await self.users.mark_login(user)
        await self.session.commit()
        logger.info("foydalanuvchi kirdi", user_id=str(user.id), email=user.email)
        return user

    async def login(self, data: LoginRequest) -> TokenResponse:
        """Email/parol bilan kirish — access va refresh token juftligi.

        Yozish `authenticate()` ichida bajariladi va u o'zi commit qiladi,
        shuning uchun bu metod qo'shimcha commit chaqirmaydi.
        """
        user = await self.authenticate(data.email, data.password)
        return self._issue_tokens(user)

    async def refresh(self, token: str) -> TokenResponse:
        """Refresh token orqali yangi juftlik beradi.

        Token turi ATAYLAB tekshiriladi (`expected_type="refresh"`): access
        token bilan yangilashga urinish `InvalidTokenError` beradi.

        Raises:
            InvalidTokenError: Token yaroqsiz, turi boshqa yoki egasi yo'q.
            TokenExpiredError: Token muddati tugagan (`decode_token` tashlaydi).
            InactiveUserError: Hisob bloklangan.
        """
        subject = token_subject(token, expected_type="refresh")
        user = await self.users.get(subject)
        if user is None:
            # Hisob o'chirilgan — token texnik jihatdan to'g'ri, lekin egasi yo'q.
            raise InvalidTokenError("Token egasi topilmadi")
        if not user.is_active:
            raise InactiveUserError()

        logger.info("token yangilandi", user_id=str(user.id))
        return self._issue_tokens(user)

    # ------------------------------------------------------------------
    # Foydalanuvchini aniqlash (dependencies ishlatadi)
    # ------------------------------------------------------------------

    async def get_user(self, user_id: uuid.UUID | str) -> User:
        """ID bo'yicha foydalanuvchi.

        Raises:
            UserNotFoundError: Bunday foydalanuvchi yo'q.
        """
        user = await self.users.get(user_id)
        if user is None:
            raise UserNotFoundError(user_id)
        return user

    async def resolve_token(self, token: str) -> User:
        """Access tokenni foydalanuvchiga aylantiradi (`dependencies.py` uchun).

        Faqat o'qiydi — hech narsa yozmaydi va commit qilmaydi.

        Raises:
            InvalidTokenError: Token yaroqsiz yoki egasi yo'q.
            TokenExpiredError: Muddat tugagan.
            InactiveUserError: Hisob bloklangan.
        """
        subject = token_subject(token, expected_type="access")
        user = await self.users.get(subject)
        if user is None:
            raise InvalidTokenError("Token egasi topilmadi")
        if not user.is_active:
            raise InactiveUserError()
        return user

    async def resolve_api_key(self, raw_key: str) -> tuple[User, ApiKey]:
        """`X-API-Key` qiymatini `(foydalanuvchi, kalit)` juftligiga aylantiradi.

        Xom kalit SHA-256 bilan hash qilinadi va unique indeks bo'yicha
        qidiriladi (O(1), bcrypt kerak emas — kalit yuqori entropiyali).
        Egasi `selectinload(ApiKey.user)` bilan OCHIQ yuklanadi, chunki
        modellarda barcha bog'lanishlar `lazy="raise"`.

        `last_used_at` har so'rovda emas, `API_KEY_TOUCH_INTERVAL_SECONDS`
        oralig'ida bir marta yoziladi (yozish — eng qimmat qism).

        Raises:
            InvalidApiKeyError: Kalit shakli noto'g'ri, topilmadi, bekor
                qilingan yoki muddati tugagan.
            InactiveUserError: Kalit egasi bloklangan.
        """
        candidate = (raw_key or "").strip()
        if not candidate or not is_api_key_format(candidate):
            raise InvalidApiKeyError()

        api_key = await self.api_keys.get_by_hash(hash_api_key(candidate), with_user=True)
        if api_key is None or not api_key.is_valid:
            logger.warning(
                "yaroqsiz API kalit bilan so'rov",
                api_key=mask_api_key(candidate),
                found=api_key is not None,
                revoked=bool(api_key is not None and api_key.is_revoked),
            )
            raise InvalidApiKeyError()

        user = api_key.user
        if not user.is_active:
            raise InactiveUserError()

        if self._needs_touch(api_key):
            await self.api_keys.touch(api_key)
            await self.session.commit()

        return user, api_key

    # ------------------------------------------------------------------
    # API kalitlar CRUD
    # ------------------------------------------------------------------

    async def create_api_key(self, user: User, data: ApiKeyCreate) -> tuple[ApiKey, str]:
        """Yangi API kalit yaratadi.

        DB'ga faqat `key_hash`, `key_prefix` va `last_four` yoziladi. XOM
        kalit saqlanmaydi — u faqat shu metodning ikkinchi qaytarma qiymati
        sifatida bir marta beriladi.

        Returns:
            `(kalit_yozuvi, xom_kalit)` juftligi.

        Raises:
            ValidationError: Faol kalitlar soni `MAX_ACTIVE_API_KEYS`dan oshdi.
        """
        active = await self.api_keys.count_active(user.id)
        if active >= MAX_ACTIVE_API_KEYS:
            raise ValidationError(
                f"Faol API kalitlar soni {MAX_ACTIVE_API_KEYS} dan oshmasligi kerak — "
                "eskilarini bekor qilib keyin yangisini yarating",
                details={"active": active, "limit": MAX_ACTIVE_API_KEYS},
            )

        generated = generate_api_key()
        api_key = await self.api_keys.create(
            user_id=user.id,
            key_hash=generated.key_hash,
            key_prefix=generated.key_prefix,
            last_four=generated.last_four,
            name=data.name,
            scopes=list(data.scopes or []),
            expires_at=data.expires_at,
        )
        await self.session.commit()

        logger.info(
            "API kalit yaratildi",
            user_id=str(user.id),
            api_key_id=str(api_key.id),
            api_key=api_key.masked,
            name=api_key.name,
            expires_at=api_key.expires_at,
        )
        return api_key, generated.raw

    async def list_api_keys(
        self,
        user: User,
        *,
        include_revoked: bool = False,
    ) -> list[ApiKey]:
        """Foydalanuvchining kalitlari (yangisi birinchi).

        `include_revoked=False` — bekor qilinganlar ro'yxatga kirmaydi.
        """
        return await self.api_keys.list_for_user(user.id, include_revoked=include_revoked)

    async def revoke_api_key(self, user: User, key_id: uuid.UUID | str) -> None:
        """Kalitni bekor qiladi (o'chirmaydi — audit uchun yozuv qoladi).

        Boshqa foydalanuvchining kaliti ham "topilmadi" deb qaytariladi:
        kalit mavjudligini oshkor qilmaymiz.

        Raises:
            ApiKeyNotFoundError: Kalit yo'q yoki boshqa foydalanuvchiga tegishli.
        """
        api_key = await self.api_keys.get_for_user(key_id, user.id)
        if api_key is None:
            raise ApiKeyNotFoundError(key_id)

        await self.api_keys.revoke(api_key)
        await self.session.commit()
        logger.info(
            "API kalit bekor qilindi",
            user_id=str(user.id),
            api_key_id=str(api_key.id),
            api_key=api_key.masked,
        )

    # ------------------------------------------------------------------
    # Parol
    # ------------------------------------------------------------------

    async def change_password(self, user: User, data: PasswordChangeRequest) -> None:
        """Joriy parolni bilgan holda yangisiga almashtiradi.

        Raises:
            InvalidCredentialsError: Joriy parol noto'g'ri.
            ValidationError: Yangi parol talablarga javob bermaydi yoki
                eskisidan farq qilmaydi.
        """
        if not verify_password(data.current_password, user.hashed_password):
            logger.warning(
                "parol almashtirishda joriy parol noto'g'ri",
                user_id=str(user.id),
            )
            raise InvalidCredentialsError("Joriy parol noto'g'ri")

        validate_password_strength(data.new_password)

        if verify_password(data.new_password, user.hashed_password):
            raise ValidationError("Yangi parol joriy paroldan farq qilishi kerak")

        await self.users.set_password(user, hash_password(data.new_password))
        await self.session.commit()
        logger.info("parol almashtirildi", user_id=str(user.id))

    # ------------------------------------------------------------------
    # Ichki yordamchilar
    # ------------------------------------------------------------------

    def _issue_tokens(self, user: User) -> TokenResponse:
        """Foydalanuvchi uchun access + refresh juftligini yasaydi.

        `extra_claims` ichiga `is_admin` va `email` qo'shiladi: shu tufayli
        oddiy tekshiruvlar uchun token'ni dekod qilish bilan cheklanish
        mumkin (har so'rovda DB'ga bormaslik imkoniyati). Baribir huquq
        yakuniy tarzda DB'dagi `is_admin` bo'yicha tekshiriladi — token
        eskirgan bo'lishi mumkin.
        """
        claims: dict[str, object] = {"is_admin": user.is_admin, "email": user.email}
        return TokenResponse(
            access_token=create_access_token(user.id, extra_claims=claims),
            refresh_token=create_refresh_token(user.id, extra_claims=claims),
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    @staticmethod
    def _normalize_email(email: str) -> str:
        """Email'ni saqlash va solishtirish uchun bir ko'rinishga keltiradi."""
        return (email or "").strip().lower()

    @classmethod
    def _is_bootstrap_admin(cls, email: str) -> bool:
        """Shu email sozlamadagi bootstrap admin emailiga mos keladimi?"""
        configured = settings.BOOTSTRAP_ADMIN_EMAIL
        if not configured:
            return False
        return cls._normalize_email(configured) == email

    @staticmethod
    def _needs_touch(api_key: ApiKey) -> bool:
        """`last_used_at` ni hozir qayta yozish kerakmi?"""
        last_used = ensure_utc(api_key.last_used_at)
        if last_used is None:
            return True
        return (utcnow() - last_used).total_seconds() >= API_KEY_TOUCH_INTERVAL_SECONDS


__all__ = [
    "API_KEY_TOUCH_INTERVAL_SECONDS",
    "MAX_ACTIVE_API_KEYS",
    "AuthService",
]
