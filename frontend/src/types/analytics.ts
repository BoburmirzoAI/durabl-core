/** Analitika turlari — KPI kartalar va grafiklar uchun. */

import type { IsoDateTime, Interval, TimeSeriesPoint } from './common'
import type { FailureReason, JobStatus, Runtime } from './job'
import type { WorkerState } from './worker'

/** Dashboard'dagi statistika kartasi. */
export interface StatCardData {
  label: string
  value: string
  /** `↑ 8.2%` ko'rinishidagi o'zgarish. */
  trend: string
  /** O'zgarish yaxshimi yoki yomonmi (rangni belgilaydi). */
  trend_direction: 'up' | 'down' | 'flat'
  trend_is_good: boolean
  sub: string
  /** Qiymat qizil bo'lishi kerakmi (DLQ Depth kabi). */
  is_alert?: boolean
}

/** KPI karta + sparkline (analitika sahifasi). */
export interface KpiData extends StatCardData {
  sparkline: number[]
}

/** Throughput grafigi ma'lumoti (ikki seriya). */
export interface ThroughputSeries {
  start: IsoDateTime
  end: IsoDateTime
  interval: Interval
  points: ThroughputPoint[]
  total_completed: number
  total_failed: number
  peak: number
}

export interface ThroughputPoint {
  timestamp: IsoDateTime
  /** O'q yorlig'i uchun qisqa vaqt (`14:30`). */
  label: string
  completed: number
  failed: number
}

/** Latency taqsimoti (histogramma). */
export interface LatencyHistogram {
  buckets: LatencyBucket[]
  p50_ms: number
  p90_ms: number
  p95_ms: number
  p99_ms: number
  avg_ms: number
}

export interface LatencyBucket {
  /** Diapazon yorlig'i (`0-100ms`). */
  label: string
  count: number
  /** Eng baland ustunga nisbatan ulush (0..1). */
  ratio: number
}

/** Runtime bo'yicha ulush (donut). */
export interface RuntimeShare {
  runtime: Runtime
  count: number
  percent: number
}

/** Muvaffaqiyat foizi tendensiyasi. */
export interface SuccessRateSeries {
  points: TimeSeriesPoint[]
  /** Maqsad chizig'i (dizaynda 99%). */
  target: number
  current: number
  min: number
}

/** DLQ chuqurligi tendensiyasi. */
export interface DlqDepthSeries {
  points: TimeSeriesPoint[]
  current: number
  peak: number
  /** Alert chegarasi (gorizontal chiziq). */
  threshold: number
}

/** Eng ko'p uchraydigan xatolar jadvali. */
export interface FailureReasonRow {
  reason: FailureReason
  label: string
  count: number
  percent: number
  trend: string
  trend_is_good: boolean
}

/** Analitika sahifasining to'liq ma'lumoti. */
export interface AnalyticsOverview {
  kpis: KpiData[]
  throughput: ThroughputSeries
  latency: LatencyHistogram
  runtimes: RuntimeShare[]
  success_rate: SuccessRateSeries
  dlq_depth: DlqDepthSeries
  top_failures: FailureReasonRow[]
}

/** Dashboard sahifasining to'liq ma'lumoti. */
export interface DashboardData {
  stats: StatCardData[]
  throughput: ThroughputSeries
  status_breakdown: Partial<Record<JobStatus, number>>
}

/**
 * Kechikish persentillari — vaqt bo'ylab p50/p90/p99.
 *
 * Gistogrammadan farqi: gistogramma BIR LAHZADAGI taqsimotni ko'rsatadi,
 * bu esa tendensiyani — qaysi persentil qachon yomonlashganini.
 */
export interface LatencyPercentilePoint {
  t: string
  p50: number
  p90: number
  p99: number
}

export interface LatencyPercentileSeries {
  points: LatencyPercentilePoint[]
  p50: number
  p90: number
  p99: number
  /** SLA chegarasi (ms) — grafikda gorizontal chiziq. */
  sla_ms: number
}

/** Haftaning kuni × soat issiqlik xaritasi uchun bitta katak. */
export interface HeatmapCell {
  /** 0 = Dushanba. */
  day: number
  hour: number
  count: number
}

export interface BusiestHours {
  cells: HeatmapCell[]
  max: number
  /** Eng band katak ("Tue 14:00"). */
  peak_label: string
}

/** Eng sekin job'lar jadvali. */
export interface SlowJobRow {
  id: string
  runtime: Runtime
  duration_ms: number
  status: JobStatus
  created_at: string
  /** Shu runtime uchun o'rtachadan necha barobar sekin. */
  slower_than_median: number
}

// ───────────────────────────────────────────────────────────────────────────
// Chuqur analitika
// ───────────────────────────────────────────────────────────────────────────

/**
 * Qayta urinish darajasi — ishonchlilikning ASOSIY ko'rsatkichi.
 *
 * Muvaffaqiyat foizi 99% bo'lishi mumkin, lekin agar uning yarmi 3-chi
 * urinishdan kelayotgan bo'lsa, tizim aslida kasal: har bir qayta urinish
 * kechikish va pul.
 */
export interface RetryRatePoint {
  timestamp: IsoDateTime
  label: string
  /** Kamida bir marta qayta urinilgan job'lar ulushi (0..100). */
  retry_rate: number
  /** BIRINCHI urinishda muvaffaqiyat (0..100). */
  first_attempt_success: number
  retried: number
  total: number
}

export interface RetryRateSeries {
  points: RetryRatePoint[]
  retry_rate: number
  first_attempt_success: number
  /** Muvaffaqiyatga yetguncha o'rtacha urinishlar soni. */
  avg_attempts: number
  /** Qayta urinishlarga ketgan qo'shimcha hisob vaqti (soniya). */
  wasted_compute_seconds: number
}

/** Worker samaradorligi qatori. */
export interface WorkerEfficiencyRow {
  worker_id: string
  /** Joylashuv (`us-east-1a`) — `Worker.region` bilan bir xil. */
  region: string
  jobs_processed: number
  /** Soatiga nechta job tugatadi. */
  jobs_per_hour: number
  avg_duration_ms: number
  /** Band vaqt ulushi (0..100). */
  utilisation: number
  /** Muvaffaqiyatsizlik foizi (0..100). */
  failure_rate: number
  /** Lease yo'qotish soni — nosog'lom worker belgisi. */
  lease_losses: number
  state: WorkerState
}

export interface WorkerEfficiency {
  rows: WorkerEfficiencyRow[]
  fleet_utilisation: number
  /** Eng tez va eng sekin worker orasidagi farq (barobar). */
  spread: number
}

/**
 * Job narxi tendensiyasi.
 *
 * `/usage` sahifasi "hisobim qancha bo'ladi" degan savolga javob beradi.
 * Bu esa boshqa savol: "bir xil ishni qilish QIMMATLASHYAPTIMI?" — ya'ni
 * samaradorlik ko'rsatkichi, hisob emas.
 */
export interface CostEfficiencyPoint {
  timestamp: IsoDateTime
  label: string
  jobs: number
  cost_usd: number
  /** Bitta job'ning o'rtacha narxi (USD). */
  cost_per_job: number
  /** Bitta job'ga ketgan hisob soniyalari. */
  compute_seconds_per_job: number
}

export interface CostEfficiencySeries {
  points: CostEfficiencyPoint[]
  cost_per_job: number
  /** Oldingi teng oraliqqa nisbatan o'zgarish (%). */
  change_percent: number
  /** Muvaffaqiyatsiz va qayta urinilgan job'larga ketgan pul (USD). */
  wasted_usd: number
  total_usd: number
}

/** Runtime'larni yonma-yon solishtirish. */
export interface RuntimeComparisonRow {
  runtime: Runtime
  jobs: number
  share: number
  success_rate: number
  p50_ms: number
  p95_ms: number
  avg_memory_mb: number
  /** 1000 ta job narxi (USD). */
  cost_per_1k: number
  cold_start_ms: number
}

/** Ikki davrni solishtirish — bitta ko'rsatkich. */
export interface PeriodMetric {
  key: string
  label: string
  current: number
  previous: number
  /** O'zgarish foizi; `previous === 0` bo'lsa `null`. */
  change_percent: number | null
  /** Qiymat qanday formatlanadi. */
  unit: 'count' | 'percent' | 'ms' | 'usd'
  /** O'sish YAXSHImi (throughput) yoki YOMONmi (kechikish). */
  higher_is_better: boolean
}

export interface PeriodComparison {
  current_label: string
  previous_label: string
  metrics: PeriodMetric[]
}

/** Grafik ustunidan drill-down qilinganda qaytadigan oyna. */
export interface TimeWindowSummary {
  from: IsoDateTime
  to: IsoDateTime
  label: string
  completed: number
  failed: number
  /** Shu oynadagi job'lar namunasi (hammasi emas). */
  sample_total: number
}
