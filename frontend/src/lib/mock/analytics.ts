/**
 * Analitika mock generatori.
 *
 * Throughput grafigi dizayndagi matematikani AYNAN takrorlaydi:
 *   daily = 255 + 140 * sin((t*24 - 9) / 24 * 2π)
 * — ya'ni sutkalik to'lqin (tongda o'sadi, kechasi tushadi), ustiga
 * deterministik shovqin qo'shiladi. Shuning uchun grafik "haqiqiy
 * trafik"ka o'xshaydi, tekis chiziq emas.
 */

import type {
  AnalyticsOverview,
  BusiestHours,
  CostEfficiencyPoint,
  CostEfficiencySeries,
  DashboardData,
  DlqDepthSeries,
  FailureReasonRow,
  HeatmapCell,
  KpiData,
  LatencyHistogram,
  LatencyPercentilePoint,
  LatencyPercentileSeries,
  Runtime,
  PeriodComparison,
  PeriodMetric,
  RetryRatePoint,
  RetryRateSeries,
  RuntimeComparisonRow,
  RuntimeShare,
  SlowJobRow,
  StatCardData,
  SuccessRateSeries,
  ThroughputPoint,
  ThroughputSeries,
  TimeSeriesPoint,
  WorkerEfficiency,
  WorkerEfficiencyRow,
} from '@/types'

import { dlqDepth, dlqStats } from './dlq'
import { allJobs, statusCounts } from './jobs'
import { NOW, Rng, hash } from './seed'
import { parseRange, previousRange, rangeLabel } from '@/lib/utils/time'
import { activeWorkerCount, allWorkers } from './workers'
import { failureReasonLabel } from '@/lib/utils/status'

/**
 * Oraliqqa qarab nuqtalar soni va qadam (daqiqa).
 *
 * Ixtiyoriy (`custom:`) oraliq uchun qadam uzunlikdan hisoblanadi: nuqta
 * soni ~60 atrofida qoladi, chunki 400 nuqtali grafik o'qilmaydi.
 */
function resolution(range: string): { points: number; stepMinutes: number; interval: 'minute' | 'hour' | 'day' } {
  switch (range) {
    case '1h':
      return { points: 60, stepMinutes: 1, interval: 'minute' }
    case '7d':
      return { points: 84, stepMinutes: 120, interval: 'hour' }
    case '30d':
      return { points: 60, stepMinutes: 720, interval: 'day' }
    case '24h':
      // 24 soat · 30 daqiqalik qadam = 48 nuqta (dizaynda aynan shunday)
      return { points: 48, stepMinutes: 30, interval: 'hour' }
    default: {
      const { hours } = parseRange(range)
      if (!Number.isFinite(hours)) return { points: 60, stepMinutes: 720, interval: 'day' }
      if (hours <= 2) return { points: 60, stepMinutes: Math.max(1, Math.round((hours * 60) / 60)), interval: 'minute' }
      if (hours <= 48) {
        const step = Math.max(5, Math.round((hours * 60) / 48 / 5) * 5)
        return { points: Math.max(2, Math.round((hours * 60) / step)), stepMinutes: step, interval: 'hour' }
      }
      const step = Math.max(60, Math.round((hours * 60) / 60 / 60) * 60)
      return {
        points: Math.max(2, Math.round((hours * 60) / step)),
        stepMinutes: step,
        interval: hours > 24 * 7 ? 'day' : 'hour',
      }
    }
  }
}

export function throughputSeries(range = '24h'): ThroughputSeries {
  const { points: n, stepMinutes, interval } = resolution(range)
  const { to } = parseRange(range, NOW)
  const points: ThroughputPoint[] = []
  let totalCompleted = 0
  let totalFailed = 0
  let peak = 0

  for (let i = 0; i < n; i += 1) {
    const minutesBack = (n - 1 - i) * stepMinutes
    const atMs = to - minutesBack * 60_000
    const date = new Date(atMs)
    // Sutkalik to'lqin — dizayndagi formula, lekin HAQIQIY soatga bog'langan.
    // Nisbiy pozitsiyaga bog'lansa, har qanday oraliq bir xil egri chiziq
    // berardi va "davrlarni solishtirish" soxta bo'lib qolardi.
    const hourOfDay = date.getUTCHours() + date.getUTCMinutes() / 60
    const daily = 255 + 140 * Math.sin(((hourOfDay - 9) / 24) * Math.PI * 2)
    // Shovqin ham absolut vaqtga bog'langan — bir xil oyna har safar bir xil
    const seed = Math.floor(atMs / 60_000)
    const completed = Math.max(95, Math.round(daily + (hash(seed * 12.9898 + 4) - 0.5) * 72))
    const failed = Math.max(1, Math.round(completed * 0.011 + hash(seed * 78.233 + 1.3) * 7))
    const timestamp = date.toISOString()

    totalCompleted += completed
    totalFailed += failed
    peak = Math.max(peak, completed)

    points.push({
      timestamp,
      label:
        interval === 'day'
          ? new Date(timestamp).toISOString().slice(5, 10)
          : new Date(timestamp).toISOString().slice(11, 16),
      completed,
      failed,
    })
  }

  return {
    start: points[0]?.timestamp ?? new Date(NOW).toISOString(),
    end: points[points.length - 1]?.timestamp ?? new Date(NOW).toISOString(),
    interval,
    points,
    total_completed: totalCompleted,
    total_failed: totalFailed,
    peak,
  }
}

/** Latency histogrammasi — haqiqiy job davomiyliklaridan hisoblanadi. */
export function latencyHistogram(): LatencyHistogram {
  const durations = allJobs()
    .map((j) => j.duration_ms)
    .filter((d): d is number => d !== null)
    .sort((a, b) => a - b)

  const edges = [0, 100, 250, 500, 1_000, 2_500, 5_000, Number.POSITIVE_INFINITY]
  const labels = ['0–100ms', '100–250ms', '250–500ms', '0.5–1s', '1–2.5s', '2.5–5s', '5s+']
  const counts = new Array(labels.length).fill(0) as number[]

  for (const d of durations) {
    for (let i = 0; i < edges.length - 1; i += 1) {
      if (d >= (edges[i] as number) && d < (edges[i + 1] as number)) {
        counts[i] = (counts[i] ?? 0) + 1
        break
      }
    }
  }

  const max = Math.max(...counts, 1)
  const pct = (p: number): number => durations[Math.floor((durations.length - 1) * p)] ?? 0

  return {
    buckets: labels.map((label, i) => ({
      label,
      count: counts[i] ?? 0,
      ratio: (counts[i] ?? 0) / max,
    })),
    p50_ms: pct(0.5),
    p90_ms: pct(0.9),
    p95_ms: pct(0.95),
    p99_ms: pct(0.99),
    avg_ms: durations.length
      ? Math.round(durations.reduce((s, d) => s + d, 0) / durations.length)
      : 0,
  }
}

export function runtimeShares(): RuntimeShare[] {
  const jobs = allJobs()
  const python = jobs.filter((j) => j.runtime === 'python').length
  const node = jobs.length - python
  return [
    { runtime: 'python', count: python, percent: Math.round((python / jobs.length) * 1000) / 10 },
    { runtime: 'node', count: node, percent: Math.round((node / jobs.length) * 1000) / 10 },
  ]
}

export function successRateSeries(range = '7d'): SuccessRateSeries {
  const n = range === '30d' ? 30 : 7
  const points: TimeSeriesPoint[] = []
  for (let i = 0; i < n; i += 1) {
    // 98.4..99.8 oralig'ida tebranish
    const value = Math.round((98.4 + hash(i * 3.7 + 11) * 1.4) * 10) / 10
    points.push({
      timestamp: new Date(NOW - (n - 1 - i) * 86_400_000).toISOString(),
      value,
    })
  }
  const values = points.map((p) => p.value)
  return {
    points,
    target: 99,
    current: values[values.length - 1] ?? 99,
    min: Math.min(...values),
  }
}

export function dlqDepthSeries(range = '7d'): DlqDepthSeries {
  const n = range === '30d' ? 30 : 7
  const current = dlqDepth()
  const points: TimeSeriesPoint[] = []
  for (let i = 0; i < n; i += 1) {
    // Oxirgi nuqta HAQIQIY chuqurlik bo'lishi kerak — aks holda grafik
    // va DLQ sahifasidagi raqam bir-biriga mos kelmaydi
    const value =
      i === n - 1 ? current : Math.max(0, Math.round(current * (0.4 + hash(i * 9.1 + 3) * 1.1)))
    points.push({
      timestamp: new Date(NOW - (n - 1 - i) * 86_400_000).toISOString(),
      value,
    })
  }
  return {
    points,
    current,
    peak: Math.max(...points.map((p) => p.value)),
    threshold: 100,
  }
}

export function topFailureReasons(): FailureReasonRow[] {
  const stats = dlqStats()
  const total = Object.values(stats.by_reason).reduce((s, v) => s + (v ?? 0), 0) || 1
  const rng = new Rng(555)
  return Object.entries(stats.by_reason)
    .sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))
    .map(([reason, count]) => {
      const delta = rng.int(-18, 24)
      return {
        reason: reason as FailureReasonRow['reason'],
        label: failureReasonLabel(reason),
        count: count ?? 0,
        percent: Math.round(((count ?? 0) / total) * 1000) / 10,
        trend: `${delta >= 0 ? '↑' : '↓'} ${Math.abs(delta)}%`,
        // Xato SONINING kamayishi — yaxshi
        trend_is_good: delta < 0,
      }
    })
}

/** Dizayndagi to'rt statistika kartasi. */
export function dashboardStats(): StatCardData[] {
  const counts = statusCounts()
  const th = throughputSeries('24h')
  const latency = latencyHistogram()
  const depth = dlqDepth()
  const totalFinished = counts.success + counts.failed + counts.dead_letter + counts.cancelled
  const successRate = totalFinished ? (counts.success / totalFinished) * 100 : 100

  return [
    {
      label: 'Jobs Today',
      value: th.total_completed.toLocaleString('en-US'),
      trend: '↑ 8.2%',
      trend_direction: 'up',
      trend_is_good: true,
      sub: 'vs yesterday',
    },
    {
      label: 'Success Rate',
      value: `${successRate.toFixed(1)}%`,
      trend: '↑ 0.3%',
      trend_direction: 'up',
      trend_is_good: true,
      sub: 'last 24h',
    },
    {
      label: 'Avg Latency',
      value: `${latency.p50_ms}ms`,
      trend: '↓ 12ms',
      trend_direction: 'down',
      trend_is_good: true,
      sub: 'p50 · last 24h',
    },
    {
      label: 'DLQ Depth',
      value: String(depth),
      trend: `↑ ${dlqStats().added_last_24h}`,
      trend_direction: 'up',
      // DLQ o'sishi — YOMON
      trend_is_good: false,
      sub: depth > 0 ? 'needs attention' : 'all clear',
      is_alert: depth > 0,
    },
  ]
}

export function dashboardData(range = '24h'): DashboardData {
  return {
    stats: dashboardStats(),
    throughput: throughputSeries(range),
    status_breakdown: statusCounts(),
  }
}

/** Analitika sahifasidagi KPI kartalar (sparkline bilan). */
export function analyticsKpis(): KpiData[] {
  const base = dashboardStats()
  const spark = (seed: number, length = 24): number[] =>
    Array.from({ length }, (_, i) => Math.round(40 + hash(i * 1.7 + seed) * 60))
  return base.map((s, i) => ({ ...s, sparkline: spark(i * 13 + 2) }))
}

export function analyticsOverview(range = '24h'): AnalyticsOverview {
  return {
    kpis: analyticsKpis(),
    throughput: throughputSeries(range),
    latency: latencyHistogram(),
    runtimes: runtimeShares(),
    success_rate: successRateSeries(range === '30d' ? '30d' : '7d'),
    dlq_depth: dlqDepthSeries(range === '30d' ? '30d' : '7d'),
    top_failures: topFailureReasons(),
  }
}

/** Admin bosh sahifasi uchun qo'shimcha ko'rsatkich. */
export function platformThroughput(): ThroughputSeries {
  return throughputSeries('24h')
}

export { activeWorkerCount }

/** Qancha nuqta kerakligini oraliqdan aniqlaydi. */
function pointsForRange(range: string): { count: number; stepMs: number; fmt: (d: Date) => string } {
  if (range === '1h') return { count: 60, stepMs: 60_000, fmt: (d) => `${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}` }
  if (range === '7d') return { count: 7 * 24, stepMs: 3_600_000, fmt: (d) => `${d.getDate()}/${d.getMonth() + 1}` }
  if (range === '30d') return { count: 30, stepMs: 86_400_000, fmt: (d) => `${d.getDate()}/${d.getMonth() + 1}` }
  return { count: 24, stepMs: 3_600_000, fmt: (d) => `${String(d.getHours()).padStart(2, '0')}:00` }
}

/**
 * Kechikish persentillari vaqt bo'ylab.
 *
 * p50 < p90 < p99 MUNOSABATI har nuqtada saqlanadi — aks holda grafik
 * mantiqsiz ko'rinadi (p50 p99 dan yuqori chiqib qolishi mumkin emas).
 */
export function latencyPercentiles(range = '24h'): LatencyPercentileSeries {
  const { count, stepMs, fmt } = pointsForRange(range)
  const rng = new Rng(44_111)
  const points: LatencyPercentilePoint[] = []

  for (let i = count - 1; i >= 0; i -= 1) {
    const date = new Date(NOW - i * stepMs)
    const hour = date.getHours()
    // Ish vaqtida yuklama yuqori — kechikish ham oshadi
    const busy = hour >= 9 && hour <= 18 ? 1.35 : 0.8
    const p50 = Math.round(rng.int(180, 320) * busy)
    const p90 = p50 + Math.round(rng.int(240, 620) * busy)
    const p99 = p90 + Math.round(rng.int(400, 1_900) * busy)
    points.push({ t: fmt(date), p50, p90, p99 })
  }

  const last = points[points.length - 1] as LatencyPercentilePoint
  return { points, p50: last.p50, p90: last.p90, p99: last.p99, sla_ms: 2_000 }
}

/** Haftaning kuni × soat bo'yicha yuklama issiqlik xaritasi. */
export function busiestHours(): BusiestHours {
  const rng = new Rng(77_003)
  const cells: HeatmapCell[] = []
  let max = 0
  let peak = { day: 0, hour: 0, count: 0 }

  for (let day = 0; day < 7; day += 1) {
    const weekend = day >= 5
    for (let hour = 0; hour < 24; hour += 1) {
      // Ish kunlarining ish soatlari eng band
      const business = hour >= 9 && hour <= 18
      const base = weekend ? (business ? 90 : 30) : business ? 420 : 110
      const count = Math.max(0, base + rng.int(-60, 90))
      cells.push({ day, hour, count })
      if (count > max) {
        max = count
        peak = { day, hour, count }
      }
    }
  }

  const DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  return {
    cells,
    max,
    peak_label: `${DAY_NAMES[peak.day]} ${String(peak.hour).padStart(2, '0')}:00`,
  }
}

/**
 * Eng sekin job'lar.
 *
 * Haqiqiy job to'plamidan olinadi — bu yerda alohida urug' ishlatilsa
 * jadvaldagi ID'lar hech qayerga olib bormasdi.
 */
export function slowestJobs(limit = 10): SlowJobRow[] {
  const finished = allJobs().filter((j) => j.duration_ms !== null && j.duration_ms > 0)

  // Runtime bo'yicha median — "necha barobar sekin" ni hisoblash uchun
  const medians = new Map<Runtime, number>()
  for (const runtime of ['python', 'node'] as Runtime[]) {
    const durations = finished
      .filter((j) => j.runtime === runtime)
      .map((j) => j.duration_ms as number)
      .sort((a, b) => a - b)
    medians.set(runtime, durations[Math.floor(durations.length / 2)] ?? 1)
  }

  return [...finished]
    .sort((a, b) => (b.duration_ms as number) - (a.duration_ms as number))
    .slice(0, limit)
    .map((job) => ({
      id: job.id,
      runtime: job.runtime,
      duration_ms: job.duration_ms as number,
      status: job.status,
      created_at: job.created_at,
      slower_than_median:
        Math.round(((job.duration_ms as number) / (medians.get(job.runtime) ?? 1)) * 10) / 10,
    }))
}

// ───────────────────────────────────────────────────────────────────────────
// Chuqur analitika generatorlari
// ───────────────────────────────────────────────────────────────────────────

/**
 * Qayta urinish darajasi vaqt bo'ylab.
 *
 * Throughput bilan BIR XIL oynadan foydalanadi — ikki grafikni yonma-yon
 * qo'yganda nuqtalar mos tushishi kerak, aks holda ularni solishtirib
 * bo'lmaydi.
 */
export function retryRateSeries(range = '24h'): RetryRateSeries {
  const throughput = throughputSeries(range)
  const points: RetryRatePoint[] = throughput.points.map((p) => {
    const total = p.completed + p.failed
    const seed = Math.floor(new Date(p.timestamp).getTime() / 60_000)
    // Qayta urinish xatolik bilan bog'liq: xato ko'p bo'lsa, urinish ham ko'p
    const failureShare = total === 0 ? 0 : p.failed / total
    const retryRate = Math.min(28, (failureShare * 100 * 2.4) + hash(seed * 31.7 + 9) * 4)
    const retried = Math.round((total * retryRate) / 100)
    return {
      timestamp: p.timestamp,
      label: p.label,
      retry_rate: Math.round(retryRate * 10) / 10,
      first_attempt_success: Math.round((100 - retryRate - failureShare * 30) * 10) / 10,
      retried,
      total,
    }
  })

  const totalJobs = points.reduce((sum, p) => sum + p.total, 0)
  const totalRetried = points.reduce((sum, p) => sum + p.retried, 0)
  const retryRate = totalJobs === 0 ? 0 : (totalRetried / totalJobs) * 100

  return {
    points,
    retry_rate: Math.round(retryRate * 10) / 10,
    first_attempt_success:
      Math.round(
        (points.reduce((sum, p) => sum + p.first_attempt_success, 0) / (points.length || 1)) * 10,
      ) / 10,
    // Har bir qayta urinilgan job o'rtacha 1 + 0.6 qo'shimcha urinish oladi
    avg_attempts: Math.round((1 + (retryRate / 100) * 0.6) * 100) / 100,
    // O'rtacha 1.8s × qayta urinishlar = behuda ketgan hisob vaqti
    wasted_compute_seconds: Math.round(totalRetried * 1.8),
  }
}

/**
 * Worker samaradorligi — qaysi worker ishni yaxshi bajaryapti.
 *
 * Haqiqiy worker ro'yxatidan olinadi (`allWorkers`), shuning uchun bu
 * yerdagi ID'lar `/admin/workers` dagilar bilan bir xil.
 */
export function workerEfficiency(): WorkerEfficiency {
  const workers = allWorkers()
  const rows: WorkerEfficiencyRow[] = workers.map((w) => {
    const rng = new Rng(hash(w.id.length * 97 + w.jobs_processed) * 100_000)
    const uptimeHours = Math.max(0.5, w.jobs_processed / rng.int(80, 240))
    const utilisation =
      w.state === 'dead' ? 0 : Math.round(Math.min(100, (w.active_jobs / w.concurrency) * 100))
    return {
      worker_id: w.id,
      region: w.region,
      jobs_processed: w.jobs_processed,
      jobs_per_hour: Math.round(w.jobs_processed / uptimeHours),
      avg_duration_ms: rng.int(820, 3_400),
      utilisation,
      failure_rate: Math.round(rng.next() * 60) / 10,
      // O'lgan worker albatta lease yo'qotgan — mantiqiy bog'liqlik
      lease_losses: w.state === 'dead' ? rng.int(1, 4) : rng.bool(0.25) ? 1 : 0,
      state: w.state,
    }
  })

  const live = rows.filter((r) => r.state !== 'dead')
  const rates = live.map((r) => r.jobs_per_hour).filter((v) => v > 0)
  // `Math.min(...rates, 1)` yozib bo'lmaydi: 1 har doim eng kichik bo'lib
  // chiqadi va tarqalish soxta 200× ko'rsatardi
  const spread =
    rates.length < 2 ? 1 : Math.max(...rates) / Math.min(...rates)

  return {
    rows: rows.sort((a, b) => b.jobs_per_hour - a.jobs_per_hour),
    fleet_utilisation:
      live.length === 0
        ? 0
        : Math.round(live.reduce((sum, r) => sum + r.utilisation, 0) / live.length),
    spread: Math.round(spread * 10) / 10,
  }
}

/** 1 soniya hisob vaqti narxi (USD) — `/usage` dagi tarif bilan bir xil. */
const COMPUTE_USD_PER_SECOND = 0.000_018

/**
 * Job narxi tendensiyasi.
 *
 * Narx ikki qismdan: bajarilgan ish + BEHUDA ketgan ish (muvaffaqiyatsiz
 * va qayta urinilgan job'lar). Ikkinchisi alohida ko'rsatiladi, chunki
 * aynan shuni kamaytirish mumkin.
 */
interface CostTotals {
  points: CostEfficiencyPoint[]
  totalCost: number
  wasted: number
  totalJobs: number
}

/**
 * Bitta oyna uchun xarajat nuqtalari.
 *
 * `costEfficiencySeries` dan ALOHIDA, chunki u o'zini oldingi davr uchun
 * qayta chaqirishi kerak — bir funksiyada bo'lsa cheksiz rekursiya bo'lardi.
 */
function costTotals(range: string): CostTotals {
  const throughput = throughputSeries(range)
  const retries = retryRateSeries(range)

  let totalCost = 0
  let wasted = 0
  let totalJobs = 0

  const points: CostEfficiencyPoint[] = throughput.points.map((p, i) => {
    const seed = Math.floor(new Date(p.timestamp).getTime() / 60_000)
    const jobs = p.completed + p.failed
    // O'rtacha hisob vaqti — kun davomida biroz o'zgaradi
    const secondsPerJob = 1.4 + hash(seed * 17.31 + 5) * 1.6
    const retried = retries.points[i]?.retried ?? 0
    const computeSeconds = jobs * secondsPerJob + retried * secondsPerJob
    const cost = computeSeconds * COMPUTE_USD_PER_SECOND
    const wastedHere = (p.failed + retried) * secondsPerJob * COMPUTE_USD_PER_SECOND

    totalCost += cost
    wasted += wastedHere
    totalJobs += jobs

    return {
      timestamp: p.timestamp,
      label: p.label,
      jobs,
      cost_usd: Math.round(cost * 10_000) / 10_000,
      cost_per_job: jobs === 0 ? 0 : Math.round((cost / jobs) * 1_000_000) / 1_000_000,
      compute_seconds_per_job: Math.round(secondsPerJob * 100) / 100,
    }
  })

  return { points, totalCost, wasted, totalJobs }
}

export function costEfficiencySeries(range = '24h'): CostEfficiencySeries {
  const current = costTotals(range)
  // Oldingi TENG oraliq haqiqatan hisoblanadi — `ComparisonStrip` ham shu
  // yo'l bilan hisoblaydi, shuning uchun ikki joyda bir xil raqam chiqadi
  const previous = costTotals(previousRange(range, NOW))

  const costPerJob = current.totalJobs === 0 ? 0 : current.totalCost / current.totalJobs
  const previousPerJob =
    previous.totalJobs === 0 ? costPerJob : previous.totalCost / previous.totalJobs

  return {
    points: current.points,
    cost_per_job: Math.round(costPerJob * 1_000_000) / 1_000_000,
    change_percent:
      previousPerJob === 0
        ? 0
        : Math.round(((costPerJob - previousPerJob) / previousPerJob) * 1_000) / 10,
    wasted_usd: Math.round(current.wasted * 100) / 100,
    total_usd: Math.round(current.totalCost * 100) / 100,
  }
}

/** Runtime'lar solishtiruvi — har biri uchun bir xil o'lchovlar. */
export function runtimeComparison(): RuntimeComparisonRow[] {
  const jobs = allJobs()
  const shares = runtimeShares()

  return shares.map((share) => {
    const rows = jobs.filter((j) => j.runtime === share.runtime)
    const durations = rows
      .map((j) => j.duration_ms)
      .filter((d): d is number => d !== null && d > 0)
      .sort((a, b) => a - b)
    const pick = (q: number): number =>
      durations.length === 0 ? 0 : (durations[Math.min(durations.length - 1, Math.floor(durations.length * q))] ?? 0)
    const succeeded = rows.filter((j) => j.status === 'success').length
    const finished = rows.filter((j) => j.status === 'success' || j.status === 'failed').length
    const rng = new Rng(hash(share.runtime.length * 613 + share.count) * 100_000)

    return {
      runtime: share.runtime,
      jobs: share.count,
      share: share.percent,
      success_rate: finished === 0 ? 0 : Math.round((succeeded / finished) * 1_000) / 10,
      p50_ms: pick(0.5),
      p95_ms: pick(0.95),
      avg_memory_mb: share.runtime === 'python' ? rng.int(96, 180) : rng.int(64, 128),
      cost_per_1k:
        Math.round(pick(0.5) * 0.001 * COMPUTE_USD_PER_SECOND * 1_000 * 10_000) / 10_000,
      // Node sovuq start'da tezroq — V8 Python interpretatoridan yengilroq
      cold_start_ms: share.runtime === 'python' ? rng.int(190, 320) : rng.int(70, 140),
    }
  })
}

/**
 * Ikki davrni solishtirish.
 *
 * Har bir ko'rsatkich uchun `higher_is_better` beriladi: o'tkazuvchanlikning
 * o'sishi yaxshi, kechikishning o'sishi yomon. Rangni shu belgilaydi.
 */
export function periodComparison(range = '24h'): PeriodComparison {
  const prevRange = previousRange(range, NOW)
  const now = throughputSeries(range)
  const prev = throughputSeries(prevRange)
  const nowRetry = retryRateSeries(range)
  const prevRetry = retryRateSeries(prevRange)
  const nowCost = costEfficiencySeries(range)
  const prevCost = costEfficiencySeries(prevRange)

  const successRate = (s: ThroughputSeries): number => {
    const total = s.total_completed + s.total_failed
    return total === 0 ? 0 : Math.round((s.total_completed / total) * 1_000) / 10
  }

  const change = (current: number, previous: number): number | null =>
    previous === 0 ? null : Math.round(((current - previous) / previous) * 1_000) / 10

  const metrics: PeriodMetric[] = [
    {
      key: 'jobs',
      label: 'Jobs run',
      current: now.total_completed + now.total_failed,
      previous: prev.total_completed + prev.total_failed,
      change_percent: change(now.total_completed + now.total_failed, prev.total_completed + prev.total_failed),
      unit: 'count',
      higher_is_better: true,
    },
    {
      key: 'success_rate',
      label: 'Success rate',
      current: successRate(now),
      previous: successRate(prev),
      change_percent: change(successRate(now), successRate(prev)),
      unit: 'percent',
      higher_is_better: true,
    },
    {
      key: 'failed',
      label: 'Failed jobs',
      current: now.total_failed,
      previous: prev.total_failed,
      change_percent: change(now.total_failed, prev.total_failed),
      unit: 'count',
      higher_is_better: false,
    },
    {
      key: 'retry_rate',
      label: 'Retry rate',
      current: nowRetry.retry_rate,
      previous: prevRetry.retry_rate,
      change_percent: change(nowRetry.retry_rate, prevRetry.retry_rate),
      unit: 'percent',
      higher_is_better: false,
    },
    {
      key: 'cost_per_job',
      label: 'Cost per job',
      current: nowCost.cost_per_job,
      previous: prevCost.cost_per_job,
      // `change(...)` yaxlitlangan qiymatlardan hisoblanardi va grafikdagi
      // raqamdan 0.2% farq qilardi — yagona manba `cost_per_job` seriyasi
      change_percent: nowCost.change_percent,
      unit: 'usd',
      higher_is_better: false,
    },
    {
      key: 'wasted',
      label: 'Wasted spend',
      current: nowCost.wasted_usd,
      previous: prevCost.wasted_usd,
      change_percent: change(nowCost.wasted_usd, prevCost.wasted_usd),
      unit: 'usd',
      higher_is_better: false,
    },
  ]

  return { current_label: rangeLabel(range), previous_label: 'previous period', metrics }
}
