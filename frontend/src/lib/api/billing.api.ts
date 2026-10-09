/** Billing endpointlari. */

import type {
  CostEstimate,
  CostProjection,
  DailyVolumePoint,
  Invoice,
  PlanChangePreview,
  PlanCompareRow,
  PlanInfo,
  PlanType,
  QuotaBreakdown,
  RuntimeCost,
  UsageSummary,
} from '@/types'
import {
  CURRENT_PLAN,
  allPlans,
  costProjection,
  dailyVolume,
  estimateCost,
  invoices,
  planChangePreview,
  planCompareRows,
  quotaBreakdown,
  runtimeCosts,
  usageSummary,
} from '@/lib/mock/billing'

import { mockResponse, notFound } from './client'

/** `GET /api/v1/billing/plans` */
export async function getPlans(currentPlan: PlanType = CURRENT_PLAN): Promise<PlanInfo[]> {
  return mockResponse(() => allPlans(currentPlan))
}

/** `GET /api/v1/billing/usage` */
export async function getUsage(): Promise<UsageSummary> {
  return mockResponse(() => usageSummary())
}

/** Kunlik hajm grafigi. */
export async function getDailyVolume(): Promise<DailyVolumePoint[]> {
  return mockResponse(() => dailyVolume())
}

/** `GET /api/v1/billing/invoices` */
export async function getInvoices(): Promise<Invoice[]> {
  return mockResponse(() => invoices())
}

/** Reja taqqoslash jadvali. */
export async function getPlanComparison(): Promise<PlanCompareRow[]> {
  return mockResponse(() => planCompareRows())
}

/** `POST /api/v1/billing/subscription` — rejani o'zgartirish. */
export async function changePlan(plan: PlanType): Promise<{ plan: PlanType }> {
  return mockResponse(() => ({ plan }), 700)
}

/** `GET /api/v1/billing/projection` — oy oxirigacha xarajat prognozi. */
export async function getCostProjection(): Promise<CostProjection> {
  return mockResponse(() => costProjection())
}

/** `GET /api/v1/billing/runtime-costs` — runtime bo'yicha xarajat. */
export async function getRuntimeCosts(): Promise<RuntimeCost[]> {
  return mockResponse(() => runtimeCosts())
}

/** `GET /api/v1/billing/usage/{key}` — bitta o'lchagich tafsiloti. */
export async function getQuotaBreakdown(key: string): Promise<QuotaBreakdown> {
  return mockResponse(() => {
    const data = quotaBreakdown(key)
    if (!data) throw notFound('Quota', key)
    return data
  }, 380)
}

/**
 * `POST /api/v1/billing/estimate`
 *
 * Narx hisob-kitobi SERVER tomonda bo'lishi kerak — tarif o'zgarganda
 * UI'ni qayta chiqarmaslik uchun. Shuning uchun mock rejimida ham
 * endpoint shaklida saqlanadi.
 */
export async function estimateMonthlyCost(
  monthlyJobs: number,
  avgDurationMs: number,
): Promise<CostEstimate> {
  return mockResponse(() => estimateCost(monthlyJobs, avgDurationMs), 220)
}

/** `GET /api/v1/billing/plans/{plan}/preview` */
export async function getPlanChangePreview(plan: PlanType): Promise<PlanChangePreview> {
  return mockResponse(() => planChangePreview(plan), 320)
}
