/** Analitika endpointlari. */

import type {
  AnalyticsOverview,
  BusiestHours,
  CostEfficiencySeries,
  DashboardData,
  DlqDepthSeries,
  LatencyHistogram,
  LatencyPercentileSeries,
  PeriodComparison,
  RetryRateSeries,
  RuntimeComparisonRow,
  RuntimeShare,
  SlowJobRow,
  SuccessRateSeries,
  ThroughputSeries,
  WorkerEfficiency,
} from '@/types'
import {
  analyticsOverview,
  busiestHours,
  costEfficiencySeries,
  dashboardData,
  dlqDepthSeries,
  latencyHistogram,
  latencyPercentiles,
  periodComparison,
  retryRateSeries,
  runtimeComparison,
  runtimeShares,
  slowestJobs,
  successRateSeries,
  throughputSeries,
  workerEfficiency,
} from '@/lib/mock/analytics'

import { mockResponse } from './client'

/** Dashboard'ning barcha ma'lumoti (bitta so'rovda — UI tez ko'rinadi). */
export async function getDashboard(range = '24h'): Promise<DashboardData> {
  return mockResponse(() => dashboardData(range))
}

/** `GET /api/v1/analytics/overview` */
export async function getAnalyticsOverview(range = '24h'): Promise<AnalyticsOverview> {
  return mockResponse(() => analyticsOverview(range))
}

/** `GET /api/v1/analytics/throughput` */
export async function getThroughput(range = '24h'): Promise<ThroughputSeries> {
  return mockResponse(() => throughputSeries(range))
}

/** `GET /api/v1/analytics/latency` */
export async function getLatency(): Promise<LatencyHistogram> {
  return mockResponse(() => latencyHistogram())
}

/** `GET /api/v1/analytics/success-rate` */
export async function getSuccessRate(range = '7d'): Promise<SuccessRateSeries> {
  return mockResponse(() => successRateSeries(range))
}

/** `GET /api/v1/analytics/dlq-depth` */
export async function getDlqDepthSeries(range = '7d'): Promise<DlqDepthSeries> {
  return mockResponse(() => dlqDepthSeries(range))
}

/** Runtime ulushi (donut). */
export async function getRuntimeShares(): Promise<RuntimeShare[]> {
  return mockResponse(() => runtimeShares())
}

/** `GET /api/v1/analytics/latency-percentiles` — p50/p90/p99 tendensiyasi. */
export async function getLatencyPercentiles(range = '24h'): Promise<LatencyPercentileSeries> {
  return mockResponse(() => latencyPercentiles(range))
}

/** `GET /api/v1/analytics/busiest-hours` — kun × soat issiqlik xaritasi. */
export async function getBusiestHours(): Promise<BusiestHours> {
  return mockResponse(() => busiestHours())
}

/** `GET /api/v1/analytics/slowest-jobs` */
export async function getSlowestJobs(limit = 10): Promise<SlowJobRow[]> {
  return mockResponse(() => slowestJobs(limit))
}

/** `GET /api/v1/analytics/retry-rate` */
export async function getRetryRate(range = '24h'): Promise<RetryRateSeries> {
  return mockResponse(() => retryRateSeries(range), 320)
}

/** `GET /api/v1/analytics/worker-efficiency` */
export async function getWorkerEfficiency(): Promise<WorkerEfficiency> {
  return mockResponse(() => workerEfficiency(), 300)
}

/** `GET /api/v1/analytics/cost-efficiency` */
export async function getCostEfficiency(range = '24h'): Promise<CostEfficiencySeries> {
  return mockResponse(() => costEfficiencySeries(range), 360)
}

/** `GET /api/v1/analytics/runtime-comparison` */
export async function getRuntimeComparison(): Promise<RuntimeComparisonRow[]> {
  return mockResponse(() => runtimeComparison(), 260)
}

/**
 * `GET /api/v1/analytics/compare?range=…`
 *
 * Joriy oraliqni oldingi TENG uzunlikdagi oraliq bilan solishtiradi.
 */
export async function getPeriodComparison(range = '24h'): Promise<PeriodComparison> {
  return mockResponse(() => periodComparison(range), 420)
}
