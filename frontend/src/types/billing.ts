/** Billing va foydalanish turlari. */

import type { Id, IsoDateTime } from './common'
import type { Runtime } from './job'

export type PlanType = 'free' | 'starter' | 'pro' | 'enterprise'

export const PLAN_TYPES: readonly PlanType[] = ['free', 'starter', 'pro', 'enterprise'] as const

/** Reja limitlari. */
export interface PlanLimits {
  plan: PlanType
  monthly_jobs: number
  requests_per_minute: number
  max_concurrent_jobs: number
  max_timeout_seconds: number
  max_memory_mb: number
  max_cpus: number
  log_retention_days: number
  allow_network: boolean
  price_usd_month: number
}

/** Reja ma'lumoti (taqqoslash jadvali va karta uchun). */
export interface PlanInfo {
  plan: PlanType
  name: string
  description: string
  price_usd_month: number
  limits: PlanLimits
  features: string[]
  is_popular: boolean
  is_current: boolean
}

/** Foydalanish o'lchagichi (dizayndagi progress bar). */
export interface UsageMeterData {
  key: string
  label: string
  current: number
  limit: number
  /** Ko'rsatish uchun formatlangan qiymat (`284K`). */
  current_label: string
  limit_label: string
  percent: number
  /** Chegaraga yaqinmi (sariq) yoki oshganmi (qizil). */
  level: 'ok' | 'warn' | 'over'
}

/** Joriy davr foydalanishi. */
export interface UsageSummary {
  period: string
  plan: PlanType
  job_count: number
  success_count: number
  failed_count: number
  execution_seconds: number
  monthly_limit: number
  remaining: number
  usage_percent: number
  period_start: IsoDateTime
  period_end: IsoDateTime
  is_over_limit: boolean
  meters: UsageMeterData[]
}

/** Kunlik hajm ustuni (dizayndagi bar chart). */
export interface DailyVolumePoint {
  date: IsoDateTime
  label: string
  count: number
  /** Kunlik limitdan oshganmi. */
  over_limit: boolean
}

export interface Invoice {
  id: Id
  date: IsoDateTime
  amount_usd: number
  status: 'paid' | 'pending' | 'failed'
  pdf_url: string
}

/** Reja taqqoslash jadvalining bitta qatori. */
export interface PlanCompareRow {
  label: string
  values: Record<PlanType, string>
}

/** Oy oxirigacha prognoz qilingan xarajat. */
export interface CostProjection {
  /** Oy boshidan hozirgacha sarflangan ($). */
  spent_usd: number
  /** Joriy tezlikda oy oxiriga yetadigan summa ($). */
  projected_usd: number
  /** Tarif rejasining asosiy to'lovi ($). */
  base_usd: number
  /** Limitdan oshgani uchun qo'shimcha ($). */
  overage_usd: number
  /** Davr tugashiga necha kun qolgani. */
  days_remaining: number
  days_total: number
  /** Prognoz limitdan oshadimi. */
  will_exceed: boolean
}

/** Runtime bo'yicha xarajat taqsimoti. */
export interface RuntimeCost {
  runtime: Runtime
  jobs: number
  compute_seconds: number
  cost_usd: number
  percent: number
}

// ───────────────────────────────────────────────────────────────────────────
// Kvota tafsiloti va "nima bo'lardi" kalkulyatori
// ───────────────────────────────────────────────────────────────────────────

/** Kvota ichidagi bitta ulush (runtime, kalit yoki holat bo'yicha). */
export interface QuotaSlice {
  label: string
  value: number
  value_label: string
  percent: number
}

export interface QuotaDailyPoint {
  date: IsoDateTime
  label: string
  value: number
}

/**
 * Bitta o'lchagich ortidagi tafsilot.
 *
 * O'lchagich faqat "82%" deydi. Foydalanuvchiga esa uchta narsa kerak:
 * nima hisoblanadi, KIM sarflayapti va limitga yetganda NIMA bo'ladi.
 */
export interface QuotaBreakdown {
  key: string
  label: string
  current: number
  limit: number
  percent: number
  current_label: string
  limit_label: string
  /** Kvota qachon nollanadi. */
  resets_at: IsoDateTime
  /** Nima hisoblanadi — bir gapda. */
  counted: string
  /** Limitga yetganda nima bo'ladi. */
  at_limit: string
  /** Limitdan oshgani uchun narx (`null` — oshirib bo'lmaydi). */
  overage_label: string | null
  daily: QuotaDailyPoint[]
  by_runtime: QuotaSlice[]
  by_api_key: QuotaSlice[]
  /** Sarfni kamaytirish bo'yicha amaliy maslahatlar. */
  tips: string[]
}

/** Bitta reja uchun hisoblangan narx. */
export interface PlanCostEstimate {
  plan: PlanType
  base_usd: number
  overage_usd: number
  total_usd: number
  /** Kiritilgan hajm shu rejaga sig'adimi. */
  fits: boolean
  /** Hajm limitdan necha barobar ko'p (sig'masa). */
  over_by: number
}

/** "Nima bo'lardi" kalkulyatori natijasi. */
export interface CostEstimate {
  monthly_jobs: number
  avg_duration_ms: number
  compute_seconds: number
  plans: PlanCostEstimate[]
  /** Eng arzon mos reja. */
  recommended: PlanType
  /** Joriy reja bilan farq ($/oy). */
  savings_usd: number
}

/** Reja almashtirish oldidan ko'rsatiladigan solishtiruv qatori. */
export interface PlanChangeRow {
  label: string
  from: string
  to: string
  /** Yangi qiymat yaxshiroqmi, yomonroqmi yoki bir xilmi. */
  direction: 'better' | 'worse' | 'same'
}

export interface PlanChangePreview {
  from: PlanType
  to: PlanType
  direction: 'upgrade' | 'downgrade' | 'same'
  price_delta_usd: number
  /** Davrning qolgan qismi uchun hisoblangan to'lov. */
  prorated_usd: number
  effective_at: IsoDateTime
  rows: PlanChangeRow[]
  /**
   * Almashtirishga to'sqinlik qiladigan holatlar.
   *
   * Masalan: joriy sarf yangi rejaning limitidan oshgan bo'lsa, pastga
   * tushish darhol kvota xatosiga olib keladi — buni OLDINDAN aytish kerak.
   */
  blockers: string[]
  warnings: string[]
}
