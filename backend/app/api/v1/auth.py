"""Durabl — autentifikatsiya va profil endpointlari (`/auth/*`).

Bu router CONTRACTS "QO'SHIMCHA 2 / AUTH" jadvalidagi yetti yo'lni beradi:

| Metod  | Yo'l                    | Auth | Javob             |
|--------|-------------------------|------|-------------------|
| POST   | `/auth/register`        | —    | `UserRead` (201)  |
| POST   | `/auth/login`           | —    | `TokenResponse`   |
| POST   | `/auth/refresh`         | —    | `TokenResponse`   |
| GET    | `/auth/me`              | J/K  | `UserRead`        |
| PUT    | `/auth/me`              | J    | `UserRead`        |
| POST   | `/auth/change-password` | J    | `SuccessResponse` |
| DELETE | `/auth/me`              | J    | `SuccessResponse` |

## Nega ba'zi yo'llar FAQAT JWT qabul qiladi

Shartnomadagi "J" ustuni ataylab qat'iy: API kalit server-server
integratsiyalari uchun mo'ljallangan va u bilan HISOBNING O'ZINI boshqarish
(parolni almashtirish, profilni tahrirlash, hisobni faolsizlantirish) mumkin
emas. Aks holda o'g'irlangan kalit darhol to'liq hisob egaligiga aylanardi.
Shu cheklovni `JwtUser` dependency'si qo'llaydi (`api_keys.py` ham shundan
foydalanadi).

## Qatlam qoidalari

Router biznes logika yozmaydi va `select()` ishlatmaydi: so'rovni oladi ->
`AuthService` ni chaqiradi -> javob schema'siga o'raydi. `HTTPException`
tashlanmaydi — domen xatolarini `main.py` dagi `DurablError` handler'i HTTP
javobiga aylantiradi.

**Ma'lum murosa.** `AuthService` da profilni tahrirlash va hisobni
faolsizlantirish metodlari YO'Q (service qatlami boshqa agentga tegishli va
muzlatilgan). Shuning uchun bu ikki endpoint service ichidagi tayyor
repozitoriy (`svc.users`) va ayni sessiya (`svc.session`) bilan ishlaydi:
xom SQL yozilmaydi, tranzaksiya chegarasi buzilmaydi. Service qatlamiga
`update_profile()` / `deactivate()` qo'shilganda bu yerdagi ikki chaqiruv
bitta service chaqiruviga almashtiriladi.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status

from app.dependencies import AuthSvc, CurrentPrincipal, CurrentUser
from app.exceptions import InactiveUserError, PermissionDeniedError
from app.logging_config import get_logger
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    PasswordChangeRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserRead,
    UserUpdate,
)
from app.schemas.base import ErrorResponse, SuccessResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


def _errors(*items: tuple[int, str]) -> dict[int | str, dict[str, Any]]:
    """OpenAPI `responses` lug'atini yasaydi — barcha xatolar `ErrorResponse`.

    Args:
        items: `(status_kodi, tavsif)` juftliklari.
    """
    return {code: {"model": ErrorResponse, "description": text} for code, text in items}


# ---------------------------------------------------------------------------
# FAQAT JWT talab qiladigan dependency
# ---------------------------------------------------------------------------


async def get_jwt_user(principal: CurrentPrincipal) -> User:
    """Faqat JWT bilan autentifikatsiya qilingan faol foydalanuvchini qaytaradi.

    API kalit bilan kelgan so'rov `PermissionDeniedError` (403) oladi: kalit
    hisob sozlamalarini o'zgartirish huquqini bermaydi (modul docstring'iga
    qara).

    Raises:
        PermissionDeniedError: So'rov API kalit bilan yuborilgan.
        InactiveUserError: Hisob faolsizlantirilgan.
    """
    if principal.auth_method != "jwt":
        logger.warning(
            "API kalit bilan hisob boshqaruviga urinish",
            user_id=str(principal.user_id),
        )
        raise PermissionDeniedError(
            "Bu amal uchun `Authorization: Bearer <access_token>` talab qilinadi — "
            "API kalit hisob sozlamalarini o'zgartirishga ruxsat bermaydi",
        )
    if not principal.user.is_active:
        raise InactiveUserError()
    return principal.user


#: `PUT /auth/me`, `POST /auth/change-password`, `DELETE /auth/me` va
#: `api_keys.py` endpointlari shu turni ishlatadi.
JwtUser = Annotated[User, Depends(get_jwt_user)]


# ---------------------------------------------------------------------------
# Ommaviy endpointlar
# ---------------------------------------------------------------------------


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ro'yxatdan o'tish",
    description=(
        "Yangi hisob yaratadi va unga FREE obunani bog'laydi. Parol kamida "
        "bitta harf va bitta raqamdan tashkil topishi kerak."
    ),
    responses=_errors(
        (409, "Bu email allaqachon ro'yxatdan o'tgan"),
        (422, "Email yoki parol talablarga javob bermaydi"),
    ),
)
async def register(data: RegisterRequest, svc: AuthSvc) -> UserRead:
    """Yangi foydalanuvchi yaratadi."""
    user = await svc.register(data)
    return UserRead.model_validate(user)


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Tizimga kirish",
    description=(
        "Email va parolni tekshiradi; access va refresh token juftligini "
        "qaytaradi. Muvaffaqiyatli kirish `last_login_at` ga yoziladi."
    ),
    responses=_errors(
        (401, "Email yoki parol noto'g'ri"),
        (403, "Hisob faolsizlantirilgan"),
        (422, "So'rov shakli noto'g'ri"),
    ),
)
async def login(data: LoginRequest, svc: AuthSvc) -> TokenResponse:
    """Email/parol bilan token juftligini beradi."""
    return await svc.login(data)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Tokenni yangilash",
    description=(
        "Refresh token orqali yangi access/refresh juftligini beradi. "
        "Access token bilan yangilashga urinish 401 qaytaradi."
    ),
    responses=_errors(
        (401, "Token yaroqsiz, turi boshqa yoki muddati tugagan"),
        (403, "Hisob faolsizlantirilgan"),
        (422, "So'rov shakli noto'g'ri"),
    ),
)
async def refresh(data: RefreshRequest, svc: AuthSvc) -> TokenResponse:
    """Refresh token bo'yicha yangi juftlik beradi."""
    return await svc.refresh(data.refresh_token)


# ---------------------------------------------------------------------------
# Joriy foydalanuvchi profili
# ---------------------------------------------------------------------------


@router.get(
    "/me",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    summary="Joriy foydalanuvchi",
    description=(
        "So'rovni yuborgan foydalanuvchining profilini qaytaradi. JWT ham, "
        "`X-API-Key` ham qabul qilinadi — kalit kimga tegishli ekanini "
        "tekshirish uchun qulay."
    ),
    responses=_errors(
        (401, "Autentifikatsiya ma'lumoti yo'q yoki yaroqsiz"),
        (403, "Hisob faolsizlantirilgan"),
    ),
)
async def read_me(user: CurrentUser) -> UserRead:
    """Joriy foydalanuvchi profilini qaytaradi."""
    return UserRead.model_validate(user)


@router.put(
    "/me",
    response_model=UserRead,
    status_code=status.HTTP_200_OK,
    summary="Profilni o'zgartirish",
    description=(
        "To'liq ismni o'zgartiradi. `full_name: null` yuborilsa ism "
        "tozalanadi. Email va parol bu endpoint orqali o'zgarmaydi."
    ),
    responses=_errors(
        (401, "Autentifikatsiya ma'lumoti yo'q yoki yaroqsiz"),
        (403, "API kalit bilan ruxsat etilmaydi yoki hisob faolsizlantirilgan"),
        (422, "So'rov shakli noto'g'ri"),
    ),
)
async def update_me(data: UserUpdate, user: JwtUser, svc: AuthSvc) -> UserRead:
    """Profil maydonlarini yangilaydi."""
    await svc.users.update(user, full_name=data.full_name)
    await svc.session.commit()
    logger.info("profil yangilandi", user_id=str(user.id))
    return UserRead.model_validate(user)


@router.post(
    "/change-password",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Parolni almashtirish",
    description=(
        "Joriy parolni tasdiqlab yangisiga almashtiradi. Mavjud token'lar "
        "amal qilishda davom etadi — ularni bekor qilish uchun chiqib qayta "
        "kirish kerak."
    ),
    responses=_errors(
        (401, "Joriy parol noto'g'ri yoki token yaroqsiz"),
        (403, "API kalit bilan ruxsat etilmaydi yoki hisob faolsizlantirilgan"),
        (422, "Yangi parol talablarga javob bermaydi"),
    ),
)
async def change_password(
    data: PasswordChangeRequest,
    user: JwtUser,
    svc: AuthSvc,
) -> SuccessResponse:
    """Parolni almashtiradi."""
    await svc.change_password(user, data)
    return SuccessResponse(
        success=True,
        message="Parol almashtirildi",
        data={"user_id": str(user.id)},
    )


@router.delete(
    "/me",
    response_model=SuccessResponse,
    status_code=status.HTTP_200_OK,
    summary="Hisobni faolsizlantirish",
    description=(
        "Hisobni faolsizlantiradi (`is_active=false`). Ma'lumot FIZIK "
        "o'chirilmaydi: job tarixi, bajarish loglari va billing yozuvlari "
        "saqlanadi. Shundan keyin barcha token va API kalitlar 403 oladi. "
        "Administrator o'z hisobini faolsizlantira olmaydi."
    ),
    responses=_errors(
        (401, "Autentifikatsiya ma'lumoti yo'q yoki yaroqsiz"),
        (403, "Admin hisobi, API kalit bilan so'rov yoki hisob allaqachon faolsiz"),
    ),
)
async def deactivate_me(user: JwtUser, svc: AuthSvc) -> SuccessResponse:
    """Hisobni faolsizlantiradi (o'chirmaydi)."""
    if user.is_admin:
        # Tizimda administrator qolmasligi xavfi: admin hisobini faqat
        # boshqa administrator `PUT /admin/users/{id}` orqali bloklaydi.
        raise PermissionDeniedError(
            "Administrator o'z hisobini faolsizlantira olmaydi — "
            "buni boshqa administrator admin paneli orqali bajarsin",
        )

    await svc.users.set_active(user, active=False)
    await svc.session.commit()
    logger.info("hisob faolsizlantirildi", user_id=str(user.id), email=user.email)
    return SuccessResponse(
        success=True,
        message=(
            "Hisob faolsizlantirildi. Job tarixi va billing yozuvlari "
            "saqlanadi — hisobni tiklash uchun administrator bilan bog'laning."
        ),
        data={"user_id": str(user.id), "is_active": False},
    )


__all__ = ["JwtUser", "get_jwt_user", "router"]
