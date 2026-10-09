'use client'

/** Dashboard va analitika ma'lumoti. */

import { useQuery } from '@tanstack/react-query'

import { analyticsApi } from '@/lib/api'

import { QK } from './keys'

/** Dashboard — statistika + throughput bitta so'rovda. */
export function useDashboard(range: string) {
  return useQuery({
    queryKey: QK.analytics.dashboard(range),
    queryFn: () => analyticsApi.getDashboard(range),
    staleTime: 20_000,
    refetchInterval: 60_000,
  })
}

export function useAnalyticsOverview(range: string) {
  return useQuery({
    queryKey: QK.analytics.overview(range),
    queryFn: () => analyticsApi.getAnalyticsOverview(range),
    staleTime: 30_000,
  })
}

export function useThroughput(range: string) {
  return useQuery({
    queryKey: QK.analytics.throughput(range),
    queryFn: () => analyticsApi.getThroughput(range),
    staleTime: 30_000,
  })
}

/** Kechikish persentillari — vaqt oralig'i bilan boshqariladi. */
export function useLatencyPercentiles(range: string) {
  return useQuery({
    queryKey: QK.analytics.percentiles(range),
    queryFn: () => analyticsApi.getLatencyPercentiles(range),
    placeholderData: (previous) => previous,
  })
}

export function useBusiestHours() {
  return useQuery({
    queryKey: QK.analytics.busiest,
    queryFn: () => analyticsApi.getBusiestHours(),
  })
}

export function useSlowestJobs(limit = 10) {
  return useQuery({
    queryKey: QK.analytics.slowest,
    queryFn: () => analyticsApi.getSlowestJobs(limit),
  })
}

/** Qayta urinish tendensiyasi — ishonchlilik tabi. */
export function useRetryRate(range: string) {
  return useQuery({
    queryKey: QK.analytics.retryRate(range),
    queryFn: () => analyticsApi.getRetryRate(range),
    placeholderData: (previous) => previous,
  })
}

export function useWorkerEfficiency() {
  return useQuery({
    queryKey: QK.analytics.workerEfficiency,
    queryFn: () => analyticsApi.getWorkerEfficiency(),
  })
}

export function useCostEfficiency(range: string) {
  return useQuery({
    queryKey: QK.analytics.costEfficiency(range),
    queryFn: () => analyticsApi.getCostEfficiency(range),
    placeholderData: (previous) => previous,
  })
}

export function useRuntimeComparison() {
  return useQuery({
    queryKey: QK.analytics.runtimeComparison,
    queryFn: () => analyticsApi.getRuntimeComparison(),
  })
}

/**
 * Davrlarni solishtirish.
 *
 * `enabled` bilan boshqariladi: solishtirish YOQILMAGUNCHA ikki barobar
 * ma'lumot hisoblash keraksiz.
 */
export function usePeriodComparison(range: string, enabled: boolean) {
  return useQuery({
    queryKey: QK.analytics.comparison(range),
    queryFn: () => analyticsApi.getPeriodComparison(range),
    enabled,
    placeholderData: (previous) => previous,
  })
}
