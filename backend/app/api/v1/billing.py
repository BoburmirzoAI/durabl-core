"""Durabl — obuna va foydalanish endpointlari (`/api/v1/billing/*`).

Beshta endpoint: joriy iste'mol (`usage`), rejalar katalogi (`plans`),
obunani o'qish va almashtirish (`subscription`) va oylik tarix
(`history`).

**`GET /billing/plans` OMMAVIY** (`CONTRACTS.md` "QO'SHIMCHA 2") — narx
sahifasi tizimga kirmagan mehmonga ham ko'rinishi kerak. Lekin token
BO'LSA `is_current` to'g'ri belgilanishi shart, aks holda kirgan
foydalanuvchi o'z rejasini tanimaydi. Shuning uchun bu yerda **ixtiyoriy**
autentifikatsiya bor: `resolve_optional_plan` dependency'si tokenni
YUMSHOQ tekshiradi — yaroqsiz bo'lsa 401 QAYTARMAYDI, `None` beradi.

**To'lov tizimi ULANMAGAN.** `POST /billing/subscription` rejani DARHOL
o'zgartiradi va hech qanday to'lovni ushlamaydi (demo loyiha). Haqiqiy
integratsiyada bu endpoint o'rniga to'lov provayderining webhook'i
obunani yangilaydi.

**Tarix SAHIFALANMAGAN**: `GET /billing/history` to'g'ridan-to'g'ri
`list[UsageHistoryItem]` qaytaradi (`PaginatedResponse` EMAS) — frontend
va SDK aynan shu shaklni kutadi. Yozuvlar soni oylar bilan o'lchanadi,
ya'ni tabiiy ravishda kichik.
"""

from __future__ import annotations

from typing import Annotated, Any, Final

from fastapi import APIRouter, Depends, Path, Query, Request, status

from app.constants import PlanType
from app.dependencies import AuthSvc, BillingSvc, CurrentUser, ScopeAdmin
from app.exceptions import DurablError
from app.logging_config import get_logger
from app.middleware.auth_middleware import extract_credentials
from app.schemas.base import ErrorResponse
from app.schemas.billing import (
    CostEstimate,
    CostEstimateRequest,
    CostProjection,
    PlanChangePreview,
    PlanChangeRequest,
    PlansResponse,
    QuotaBreakdown,
    RuntimeCost,
    StatementRead,
    SubscriptionRead,
    UsageHistoryItem,
    UsageSummary,
)
from app.services.billing_service import DEFAULT_HISTORY_MONTHS, MAX_HISTORY_MONTHS
from app.utils.security import is_api_key_format

logger = get_logger(__name__)

#: Scope darvozasi ROUTER darajasida EMAS, har endpointda alohida.
#:
#: Sababi: `GET /billing/plans` ATAYLAB ommaviy (narx ro'yxati,
#: autentifikatsiya talab qilmaydi). Router darajasidagi darvoza unga
#: ham auth majburlab qo'yardi — bu aynan sinab ko'rilgan va uch test
#: shu sababdan yiqilgan edi:
#:
#:     test_plans_without_authentication
#:     test_plans_tolerates_broken_token
#:     test_request_id_generated   (ommaviy yo'lni ishlatadi)
#:
#: Ya'ni router darvozasi qulay, lekin ISTISNONI ko'rmaydi. Shuning
#: uchun billing'da `ScopeAdmin` qo'lda, `/plans` dan tashqari barcha
#: endpointga qo'yiladi.
#:
#: Doira `admin`: frontend `API_KEY_SCOPE_INFO.admin` tavsifi
#: ("everything above, plus billing, webhooks, team and API key
#: management") shuni belgilaydi.
router = APIRouter(prefix="/billing", tags=["billing"])

#: Autentifikatsiya talab qiladigan endpointlarning umumiy xato javoblari.
AUTH_RESPONSES: Final[dict[int | str, dict[str, Any]]] = {
    status.HTTP_401_UNAUTHORIZED: {
        "model": ErrorResponse,
        "description": "Autentifikatsiya talab qilinadi",
    },
    status.HTTP_403_FORBIDDEN: {
        "model": ErrorResponse,
        "description": "Hisob faolsizlantirilgan yoki kalit doirasi yetarli emas",
    },
}


def _with_errors(*items: tuple[int, str]) -> dict[int | str, dict[str, Any]]:
    """`AUTH_RESPONSES` ustiga qo'shimcha xatolarni qo'shadi.

    Autentifikatsiya xatolari har endpointda bir xil, shuning uchun
    ularni qayta yozish o'rniga umumiy lug'at kengaytiriladi — hujjat
    bir joyda qoladi.
    """
    extra: dict[int | str, dict[str, Any]] = {
        code: {"model": ErrorResponse, "description": text} for code, text in items
    }
    return {**AUTH_RESPONSES, **extra}


async def resolve_optional_plan(
    request: Request,
    auth: AuthSvc,
    billing: BillingSvc,
) -> PlanType | None:
    """So'rovdagi tokendan foydalanuvchining rejasini YUMSHOQ aniqlaydi.

    `dependencies.py` da ixtiyoriy principal beradigan dependency yo'q
    (`get_current_principal` ma'lumot bo'lmasa 401 tashlaydi), shuning
    uchun bu yerda ayni `extract_credentials()` yordamchisi bilan
    header'lar o'qiladi va `AuthService` chaqiriladi.

    **Hech qanday holatda xato tashlamaydi.** Token yo'q, yaroqsiz,
    muddati tugagan yoki hisob bloklangan bo'lsa `None` qaytadi va
    katalog anonim ko'rinishda beriladi. Sababi: narx sahifasi eskirgan
    token tufayli OCHILMAY qolmasligi kerak.

    Returns:
        Joriy reja yoki `None` (anonim/yaroqsiz).
    """
    raw_api_key, raw_token = extract_credentials(request)
    raw = raw_api_key or raw_token
    if not raw:
        return None

    try:
        if raw_api_key is not None or is_api_key_format(raw):
            user, _ = await auth.resolve_api_key(raw)
        else:
            user = await auth.resolve_token(raw)
        if not user.is_active:
            return None
        limits = await billing.limits_for(user.id)
    except DurablError as exc:
        #: ATAYLAB keng: autentifikatsiya xatosi ham, DB/Redis nosozligi
        #: ham katalogni bloklamaydi — u statik ma'lumot.
        logger.debug("billing.plans anonim rejimda", error=exc.code)
        return None
    return PlanType(limits.plan)


#: `GET /billing/plans` uchun ixtiyoriy reja.
OptionalPlan = Annotated[PlanType | None, Depends(resolve_optional_plan)]


@router.get(
    "/usage",
    dependencies=[ScopeAdmin],
    response_model=UsageSummary,
    status_code=status.HTTP_200_OK,
    summary="Joriy davr iste'moli",
    description=(
        "Joriy oy bo'yicha yuborilgan job'lar, sarflangan bajarish vaqti "
        "va reja limitlari. `is_over_limit` rost bo'lsa yangi job qabul "
        "qilinmaydi."
    ),
    responses=AUTH_RESPONSES,
)
async def get_usage(user: CurrentUser, svc: BillingSvc) -> UsageSummary:
    """Foydalanuvchining joriy davrdagi iste'moli."""
    return await svc.usage(user)


@router.get(
    "/plans",
    response_model=PlansResponse,
    status_code=status.HTTP_200_OK,
    summary="Rejalar katalogi (ommaviy)",
    description=(
        "Barcha rejalar, narxlari va cheklovlari — autentifikatsiya "
        "TALAB QILINMAYDI. Token yuborilsa foydalanuvchining joriy "
        "rejasida `is_current` belgilanadi."
    ),
)
async def get_plans(svc: BillingSvc, current_plan: OptionalPlan) -> PlansResponse:
    """Rejalar katalogi (anonim ham ishlaydi)."""
    return await svc.plans(current_plan=current_plan)


@router.get(
    "/subscription",
    dependencies=[ScopeAdmin],
    response_model=SubscriptionRead,
    status_code=status.HTTP_200_OK,
    summary="Joriy obuna",
    description=(
        "Foydalanuvchining obunasi va amaldagi cheklovlari. Obuna yozuvi "
        "bo'lmasa FREE reja bilan yaratiladi."
    ),
    responses=AUTH_RESPONSES,
)
async def get_subscription(user: CurrentUser, svc: BillingSvc) -> SubscriptionRead:
    """Obunani o'qiydi (yo'q bo'lsa yaratadi)."""
    subscription = await svc.subscription(user)
    return SubscriptionRead.model_validate(subscription)


@router.post(
    "/subscription",
    dependencies=[ScopeAdmin],
    response_model=SubscriptionRead,
    status_code=status.HTTP_200_OK,
    summary="Rejani almashtirish (to'lov tizimi ulanmagan)",
    description=(
        "Obuna rejasini almashtiradi. **Diqqat:** bu demo loyihada to'lov "
        "tizimi ulanmagan — reja darhol o'zgaradi, hech qanday to'lov "
        "ushlanmaydi va bekor qilish ham darhol kuchga kiradi. Muddat "
        "qayta boshlanadi (`started_at` yangilanadi)."
    ),
    responses=AUTH_RESPONSES,
)
async def change_subscription(
    user: CurrentUser,
    svc: BillingSvc,
    payload: PlanChangeRequest,
) -> SubscriptionRead:
    """Rejani almashtiradi va yangilangan obunani qaytaradi."""
    subscription = await svc.change_plan(user, payload.plan)
    return SubscriptionRead.model_validate(subscription)


@router.get(
    "/history",
    dependencies=[ScopeAdmin],
    response_model=list[UsageHistoryItem],
    status_code=status.HTTP_200_OK,
    summary="Oylik foydalanish tarixi",
    description=(
        "Oxirgi oylar bo'yicha iste'mol yozuvlari (yangisidan boshlab). "
        "Javob SAHIFALANMAGAN — oddiy ro'yxat."
    ),
    responses=AUTH_RESPONSES,
)
async def get_history(
    user: CurrentUser,
    svc: BillingSvc,
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_HISTORY_MONTHS,
            description="Nechta oy qaytarilsin",
        ),
    ] = DEFAULT_HISTORY_MONTHS,
) -> list[UsageHistoryItem]:
    """Oylik foydalanish tarixi."""
    return await svc.history(user, limit=limit)


@router.get(
    "/invoices",
    dependencies=[ScopeAdmin],
    response_model=list[StatementRead],
    status_code=status.HTTP_200_OK,
    summary="Oylik hisob-kitoblar",
    description=(
        "Davr bo'yicha foydalanish va hisoblangan summa.\n\n"
        "DIQQAT: loyihada to'lov tizimi ulanmagan — `status` va `pdf_url` "
        "`null` qaytadi, `payments_enabled` buni ko'rsatadi. Foydalanish "
        "ma'lumoti (`job_count`, `execution_seconds`) va summa esa haqiqiy.\n\n"
        "Narx JORIY reja bo'yicha hisoblanadi: o'tgan davrlarda qaysi reja "
        "amal qilgani saqlanmaydi (`plan_history_tracked`)."
    ),
    responses=AUTH_RESPONSES,
)
async def get_invoices(
    user: CurrentUser,
    svc: BillingSvc,
    limit: Annotated[
        int,
        Query(ge=1, le=MAX_HISTORY_MONTHS, description="Nechta davr qaytarilsin"),
    ] = DEFAULT_HISTORY_MONTHS,
) -> list[StatementRead]:
    """Oylik hisob-kitoblar ro'yxati."""
    rows = await svc.statements(user, limit=limit)
    return [StatementRead.model_validate(row) for row in rows]


@router.get(
    "/projection",
    dependencies=[ScopeAdmin],
    response_model=CostProjection,
    status_code=status.HTTP_200_OK,
    summary="Oy oxirigacha prognoz",
    description=(
        "Joriy tezlik (`kunlik o'rtacha`) oy oxirigacha davom etadi deb "
        "hisoblanadi.\n\n"
        "`will_exceed` \"qo'shimcha pul to'laysiz\" EMAS — Durabl kvotada "
        "job'ni rad etadi, shuning uchun u \"limitga yetib job'lar rad "
        'etila boshlaydi" degani.\n\n'
        "Oyning birinchi kunida prognoz berilmaydi: bir kunlik ma'lumotni "
        "30 ga ko'paytirish xatoni 30 barobar kattalashtirardi."
    ),
    responses=AUTH_RESPONSES,
)
async def get_projection(user: CurrentUser, svc: BillingSvc) -> CostProjection:
    """Oy oxirigacha xarajat va kvota prognozi."""
    return CostProjection.model_validate(await svc.projection(user))


@router.get(
    "/runtime-costs",
    dependencies=[ScopeAdmin],
    response_model=list[RuntimeCost],
    status_code=status.HTTP_200_OK,
    summary="Runtime bo'yicha xarajat",
    description=(
        "Joriy davrda xarajatning runtime bo'yicha taqsimi.\n\n"
        "Reja narxi oylik va yagona — runtime bo'yicha alohida tarif yo'q, "
        "shuning uchun xarajat BAJARISH SONIYALARI nisbatida taqsimlanadi. "
        "Hech qanday soniya bajarilmagan bo'lsa taqsim ham nol bo'ladi."
    ),
    responses=AUTH_RESPONSES,
)
async def get_runtime_costs(user: CurrentUser, svc: BillingSvc) -> list[RuntimeCost]:
    """Runtime bo'yicha xarajat taqsimoti."""
    rows = await svc.runtime_costs(user)
    return [RuntimeCost.model_validate(row) for row in rows]


@router.get(
    "/usage/{key}",
    dependencies=[ScopeAdmin],
    response_model=QuotaBreakdown,
    status_code=status.HTTP_200_OK,
    summary="Kvota o'lchagichi tafsiloti",
    description=(
        "O'lchagich faqat \"82%\" deydi; bu yo'l NIMA hisoblanishini, KIM "
        "sarflayotganini va limitga yetganda NIMA bo'lishini aytadi.\n\n"
        "Qo'llanadigan kalitlar: `monthly_jobs`, `compute_seconds`. "
        "`max_concurrent_jobs` va `requests_per_minute` ATAYLAB yo'q — "
        "ular Redis'da lahzalik qiymat sifatida yashaydi va tarixi "
        "saqlanmaydi, ya'ni tahlil yasash uchun ma'lumot yo'q.\n\n"
        "`daily` va `by_api_key` hozircha bo'sh (`*_tracked` maydonlari "
        "sababini ko'rsatadi)."
    ),
    responses=_with_errors((422, "Noma'lum o'lchagich kaliti")),
)
async def get_quota_breakdown(
    user: CurrentUser,
    svc: BillingSvc,
    key: Annotated[str, Path(description="O'lchagich kaliti")],
) -> QuotaBreakdown:
    """Bitta kvota o'lchagichi ortidagi tafsilot."""
    return QuotaBreakdown.model_validate(await svc.quota_breakdown(user, key))


@router.post(
    "/estimate",
    dependencies=[ScopeAdmin],
    response_model=CostEstimate,
    status_code=status.HTTP_200_OK,
    summary="Narx kalkulyatori",
    description=(
        "Kiritilgan hajm uchun har reja narxini hisoblaydi. Hech narsa "
        "o'qilmaydi va yozilmaydi — faqat reja katalogi ustidagi hisob.\n\n"
        "`recommended` FAQAT sig'adigan rejalar orasidan tanlanadi: Durabl "
        "kvotada bloklaydi, ya'ni sig'maydigan reja arzon bo'lsa ham "
        "mijozga yaramaydi."
    ),
    responses=_with_errors((422, "Kiritilgan qiymatlar chegaradan tashqarida")),
)
async def estimate_cost(
    user: CurrentUser,
    svc: BillingSvc,
    payload: CostEstimateRequest,
) -> CostEstimate:
    """Hajm bo'yicha narx hisoblaydi."""
    subscription = await svc.subscription(user)
    result = await svc.estimate(
        monthly_jobs=payload.monthly_jobs,
        avg_duration_ms=payload.avg_duration_ms,
        current_plan=subscription.plan,
    )
    return CostEstimate.model_validate(result)


@router.get(
    "/plans/{plan}/preview",
    dependencies=[ScopeAdmin],
    response_model=PlanChangePreview,
    status_code=status.HTTP_200_OK,
    summary="Reja almashtirish oqibati",
    description=(
        "Almashtirishdan OLDIN nima o'zgarishini ko'rsatadi.\n\n"
        "Eng muhim maydon — `blockers`: pastga tushishda joriy sarf yangi "
        "rejaning limitidan oshgan bo'lsa, almashtirish DARHOL kvota "
        "xatosiga olib keladi va mijozning job'lari rad etila boshlaydi. "
        "Buni oldindan aytish kerak.\n\n"
        "`prorated_usd` har doim 0: to'lov tizimi yo'q, ya'ni davr "
        "o'rtasida qayta hisoblash ham yo'q."
    ),
    responses=_with_errors((422, "Noma'lum reja")),
)
async def preview_plan_change(
    user: CurrentUser,
    svc: BillingSvc,
    plan: Annotated[PlanType, Path(description="Yangi reja")],
) -> PlanChangePreview:
    """Reja almashtirish oqibatini qaytaradi."""
    return PlanChangePreview.model_validate(await svc.plan_change_preview(user, plan))


__all__ = ["router"]
