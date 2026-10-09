'use client'

/** Billing, reja va foydalanish. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { PlanType } from '@/types'
import { billingApi } from '@/lib/api'
import { useToast } from '@/components/common/ToastProvider'

import { QK } from './keys'

export function usePlans() {
  return useQuery({
    queryKey: QK.billing.plans,
    queryFn: () => billingApi.getPlans(),
    // Rejalar deyarli o'zgarmaydi
    staleTime: 5 * 60_000,
  })
}

export function useUsage() {
  return useQuery({ queryKey: QK.billing.usage, queryFn: () => billingApi.getUsage() })
}

export function useDailyVolume() {
  return useQuery({ queryKey: QK.billing.volume, queryFn: () => billingApi.getDailyVolume() })
}

export function useInvoices() {
  return useQuery({ queryKey: QK.billing.invoices, queryFn: () => billingApi.getInvoices() })
}

export function usePlanComparison() {
  return useQuery({
    queryKey: QK.billing.comparison,
    queryFn: () => billingApi.getPlanComparison(),
    staleTime: 5 * 60_000,
  })
}

export function useChangePlan() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (plan: PlanType) => billingApi.changePlan(plan),
    onSuccess: ({ plan }) => {
      void qc.invalidateQueries({ queryKey: QK.billing.all })
      toast({ title: `Switched to ${plan}`, variant: 'success' })
    },
  })
}

/** Oy oxirigacha xarajat prognozi. */
export function useCostProjection() {
  return useQuery({
    queryKey: QK.billing.projection,
    queryFn: () => billingApi.getCostProjection(),
  })
}

/** Runtime bo'yicha xarajat taqsimoti. */
export function useRuntimeCosts() {
  return useQuery({
    queryKey: QK.billing.runtimeCosts,
    queryFn: () => billingApi.getRuntimeCosts(),
  })
}

/** Kvota tafsiloti — panel ochilgandagina so'raladi. */
export function useQuotaBreakdown(key: string | null) {
  return useQuery({
    queryKey: QK.billing.quota(key ?? 'none'),
    queryFn: () => billingApi.getQuotaBreakdown(key as string),
    enabled: key !== null,
  })
}

/**
 * Narx kalkulyatori.
 *
 * `keepPreviousData` emas, `placeholderData` ishlatiladi: slayder
 * surilganda jadval o'rnida turishi kerak, aks holda har harakatda
 * skeletlar chaqnaydi.
 */
export function useCostEstimate(monthlyJobs: number, avgDurationMs: number) {
  return useQuery({
    queryKey: QK.billing.estimate(monthlyJobs, avgDurationMs),
    queryFn: () => billingApi.estimateMonthlyCost(monthlyJobs, avgDurationMs),
    placeholderData: (previous) => previous,
  })
}

export function usePlanChangePreview(plan: PlanType | null) {
  return useQuery({
    queryKey: QK.billing.planPreview(plan ?? 'none'),
    queryFn: () => billingApi.getPlanChangePreview(plan as PlanType),
    enabled: plan !== null,
  })
}
