/** Billing, reja va foydalanish mock ma'lumoti. */

import type {
  CostEstimate,
  CostProjection,
  DailyVolumePoint,
  Invoice,
  PlanChangePreview,
  PlanChangeRow,
  PlanCompareRow,
  PlanCostEstimate,
  PlanInfo,
  PlanLimits,
  PlanType,
  QuotaBreakdown,
  QuotaDailyPoint,
  QuotaSlice,
  Runtime,
  RuntimeCost,
  UsageMeterData,
  UsageSummary,
} from '@/types'
import { formatCompact } from '@/lib/utils/format'

import { allApiKeys } from './api-keys'
import { allJobs } from './jobs'
import { NOW, Rng, hash } from './seed'

/**
 * Reja limitlari — backend `app/constants.py` dagi `PLAN_LIMITS` bilan
 * AYNAN bir xil. Backend ulanganda bu jadval o'rniga `/billing/plans`
 * javobi keladi, shuning uchun qiymatlar mos bo'lishi muhim.
 */
export const PLAN_LIMITS: Record<PlanType, PlanLimits> = {
  free: {
    plan: 'free',
    monthly_jobs: 1_000,
    requests_per_minute: 30,
    max_concurrent_jobs: 2,
    max_timeout_seconds: 30,
    max_memory_mb: 256,
    max_cpus: 0.5,
    log_retention_days: 3,
    allow_network: false,
    price_usd_month: 0,
  },
  starter: {
    plan: 'starter',
    monthly_jobs: 50_000,
    requests_per_minute: 120,
    max_concurrent_jobs: 10,
    max_timeout_seconds: 120,
    max_memory_mb: 512,
    max_cpus: 1,
    log_retention_days: 14,
    allow_network: true,
    price_usd_month: 29,
  },
  pro: {
    plan: 'pro',
    monthly_jobs: 500_000,
    requests_per_minute: 600,
    max_concurrent_jobs: 50,
    max_timeout_seconds: 300,
    max_memory_mb: 1_024,
    max_cpus: 2,
    log_retention_days: 30,
    allow_network: true,
    price_usd_month: 99,
  },
  enterprise: {
    plan: 'enterprise',
    monthly_jobs: 10_000_000,
    requests_per_minute: 5_000,
    max_concurrent_jobs: 500,
    max_timeout_seconds: 900,
    max_memory_mb: 4_096,
    max_cpus: 4,
    log_retention_days: 90,
    allow_network: true,
    price_usd_month: 499,
  },
}

const PRESENTATION: Record<PlanType, { name: string; description: string; features: string[] }> = {
  free: {
    name: 'Free',
    description: 'Kick the tyres. No card required.',
    features: ['1K jobs / month', '30s max runtime', '3-day log retention', 'Community support'],
  },
  starter: {
    name: 'Starter',
    description: 'For side projects moving to production.',
    features: ['50K jobs / month', '2m max runtime', '14-day logs', 'Outbound network', 'Email support'],
  },
  pro: {
    name: 'Pro',
    description: 'For teams running critical background work.',
    features: [
      '500K jobs / month',
      '5m max runtime',
      '30-day logs',
      '50 concurrent jobs',
      'DLQ alerts + webhooks',
      'Priority support',
    ],
  },
  enterprise: {
    name: 'Enterprise',
    description: 'Dedicated capacity and compliance controls.',
    features: [
      '10M jobs / month',
      '15m max runtime',
      '90-day logs',
      'Dedicated workers',
      'SSO + audit log',
      'SLA + Slack channel',
    ],
  },
}

/** Mock foydalanuvchining joriy rejasi (dizaynda "Pro Plan"). */
export const CURRENT_PLAN: PlanType = 'pro'

export function allPlans(currentPlan: PlanType = CURRENT_PLAN): PlanInfo[] {
  return (Object.keys(PLAN_LIMITS) as PlanType[]).map((plan) => {
    const limits = PLAN_LIMITS[plan]
    const info = PRESENTATION[plan]
    return {
      plan,
      name: info.name,
      description: info.description,
      price_usd_month: limits.price_usd_month,
      limits,
      features: info.features,
      is_popular: plan === 'pro',
      is_current: plan === currentPlan,
    }
  })
}

/** Joriy davrdagi foydalanish (dizayndagi uch o'lchagich). */
export function usageSummary(): UsageSummary {
  const limits = PLAN_LIMITS[CURRENT_PLAN]
  const jobCount = 284_120
  const successCount = Math.round(jobCount * 0.992)
  const executionSeconds = 412_880

  const meter = (
    key: string,
    label: string,
    current: number,
    limit: number,
    fmt: (n: number) => string,
  ): UsageMeterData => {
    const percent = Math.round((current / limit) * 1000) / 10
    return {
      key,
      label,
      current,
      limit,
      current_label: fmt(current),
      limit_label: fmt(limit),
      percent,
      level: percent >= 100 ? 'over' : percent >= 80 ? 'warn' : 'ok',
    }
  }

  const periodStart = new Date(NOW)
  periodStart.setUTCDate(1)
  periodStart.setUTCHours(0, 0, 0, 0)
  const periodEnd = new Date(periodStart)
  periodEnd.setUTCMonth(periodEnd.getUTCMonth() + 1)

  return {
    period: new Date(NOW).toISOString().slice(0, 7),
    plan: CURRENT_PLAN,
    job_count: jobCount,
    success_count: successCount,
    failed_count: jobCount - successCount,
    execution_seconds: executionSeconds,
    monthly_limit: limits.monthly_jobs,
    remaining: Math.max(0, limits.monthly_jobs - jobCount),
    usage_percent: Math.round((jobCount / limits.monthly_jobs) * 1000) / 10,
    period_start: periodStart.toISOString(),
    period_end: periodEnd.toISOString(),
    is_over_limit: jobCount > limits.monthly_jobs,
    meters: [
      meter('jobs', 'Jobs', jobCount, limits.monthly_jobs, formatCompact),
      // `formatCompact(1_000_000) + 's'` = "1Ms" bo'lardi — bu "1 millisekund"
      // deb o'qiladi. Soatga o'girish aniq va qisqa.
      meter('compute', 'Compute time', executionSeconds, 1_000_000, (n) =>
        `${(n / 3_600).toFixed(n >= 36_000 ? 0 : 1)}h`,
      ),
      meter('concurrency', 'Concurrent jobs', 38, limits.max_concurrent_jobs, String),
    ],
  }
}

/** Kunlik hajm ustunlari (dizayndagi bar chart, 30 kun). */
export function dailyVolume(): DailyVolumePoint[] {
  const dailyLimit = Math.round(PLAN_LIMITS[CURRENT_PLAN].monthly_jobs / 30)
  const today = new Date(NOW).getUTCDate()
  return Array.from({ length: 30 }, (_, i) => {
    const date = new Date(NOW - (29 - i) * 86_400_000)
    // Kelajak kunlari bo'sh turadi
    const future = i > today - 1 && date.getUTCMonth() === new Date(NOW).getUTCMonth()
    const count = future ? 0 : Math.round(8_000 + hash(i * 5.3 + 2) * 11_000)
    return {
      date: date.toISOString(),
      label: String(date.getUTCDate()),
      count,
      over_limit: count > dailyLimit,
    }
  })
}

export function invoices(): Invoice[] {
  const rng = new Rng(8_191)
  return Array.from({ length: 6 }, (_, i) => {
    const date = new Date(NOW)
    date.setUTCMonth(date.getUTCMonth() - (i + 1))
    date.setUTCDate(4)
    return {
      id: `inv_${rng.hex(8)}`,
      date: date.toISOString(),
      amount_usd: PLAN_LIMITS[CURRENT_PLAN].price_usd_month,
      status: 'paid' as const,
      pdf_url: '#',
    }
  })
}

/** Reja taqqoslash jadvali (dizaynda 3 ustun). */
export function planCompareRows(): PlanCompareRow[] {
  const val = (fn: (l: PlanLimits) => string): Record<PlanType, string> => ({
    free: fn(PLAN_LIMITS.free),
    starter: fn(PLAN_LIMITS.starter),
    pro: fn(PLAN_LIMITS.pro),
    enterprise: fn(PLAN_LIMITS.enterprise),
  })
  return [
    { label: 'Jobs per month', values: val((l) => formatCompact(l.monthly_jobs)) },
    { label: 'Max runtime', values: val((l) => `${l.max_timeout_seconds}s`) },
    { label: 'Concurrent jobs', values: val((l) => String(l.max_concurrent_jobs)) },
    { label: 'Memory per job', values: val((l) => `${l.max_memory_mb} MB`) },
    { label: 'Log retention', values: val((l) => `${l.log_retention_days} days`) },
    { label: 'Outbound network', values: val((l) => (l.allow_network ? 'Yes' : 'No')) },
    { label: 'Requests / minute', values: val((l) => formatCompact(l.requests_per_minute)) },
  ]
}

/** Tarif rejasining oylik asosiy to'lovi ($). */
const PLAN_BASE_USD: Record<PlanType, number> = {
  free: 0,
  starter: 29,
  pro: 99,
  enterprise: 499,
}

/** Limitdan oshgan har 1000 job uchun qo'shimcha to'lov ($). */
const OVERAGE_PER_1K_USD = 2.5

/**
 * Oy oxirigacha xarajat prognozi.
 *
 * Prognoz JORIY TEZLIK asosida: davr boshidan hozirgacha o'rtacha kunlik
 * sarf topiladi va qolgan kunlarga ko'paytiriladi. Bu sodda model, lekin
 * foydalanuvchiga "shu sur'atda davom etsa" degan savolga javob beradi.
 */
export function costProjection(): CostProjection {
  const summary = usageSummary()
  const start = new Date(summary.period_start).getTime()
  const end = new Date(summary.period_end).getTime()
  const daysTotal = Math.max(1, Math.round((end - start) / 86_400_000))
  const daysElapsed = Math.max(1, Math.round((NOW - start) / 86_400_000))
  const daysRemaining = Math.max(0, daysTotal - daysElapsed)

  const base = PLAN_BASE_USD[summary.plan]
  const overUsed = Math.max(0, summary.job_count - summary.monthly_limit)
  const overageNow = (overUsed / 1_000) * OVERAGE_PER_1K_USD

  const projectedJobs = Math.round((summary.job_count / daysElapsed) * daysTotal)
  const projectedOverUsed = Math.max(0, projectedJobs - summary.monthly_limit)
  const projectedOverage = (projectedOverUsed / 1_000) * OVERAGE_PER_1K_USD

  return {
    spent_usd: Math.round((base + overageNow) * 100) / 100,
    projected_usd: Math.round((base + projectedOverage) * 100) / 100,
    base_usd: base,
    overage_usd: Math.round(projectedOverage * 100) / 100,
    days_remaining: daysRemaining,
    days_total: daysTotal,
    will_exceed: projectedJobs > summary.monthly_limit,
  }
}

/**
 * Runtime bo'yicha xarajat taqsimoti.
 *
 * Narx hisob-kitobi compute-sekundga bog'liq (job soniga emas) — uzoq
 * ishlaydigan job ko'proq turadi.
 */
export function runtimeCosts(): RuntimeCost[] {
  const summary = usageSummary()
  const jobs = allJobs()
  const finished = jobs.filter((j) => j.duration_ms !== null)

  const rows = (['python', 'node'] as Runtime[]).map((runtime) => {
    const mine = finished.filter((j) => j.runtime === runtime)
    const seconds = mine.reduce((sum, j) => sum + (j.duration_ms ?? 0) / 1_000, 0)
    return { runtime, jobs: mine.length, compute_seconds: Math.round(seconds) }
  })

  const totalSeconds = rows.reduce((sum, r) => sum + r.compute_seconds, 0) || 1
  // Umumiy compute xarajati tarif asosiy to'lovining 60% i deb olinadi
  const computeBudget = PLAN_BASE_USD[summary.plan] * 0.6

  return rows.map((row) => ({
    ...row,
    cost_usd: Math.round((row.compute_seconds / totalSeconds) * computeBudget * 100) / 100,
    percent: Math.round((row.compute_seconds / totalSeconds) * 1000) / 10,
  }))
}

// ───────────────────────────────────────────────────────────────────────────
// Kvota tafsiloti
// ───────────────────────────────────────────────────────────────────────────

/** Har bir o'lchagich ortidagi tushuntirish matnlari. */
const QUOTA_COPY: Record<
  string,
  { counted: string; at_limit: string; overage: string | null; tips: string[] }
> = {
  jobs: {
    counted:
      'Every job accepted by the API, including ones that later fail or are dead-lettered. Deduplicated submissions (same idempotency key) are counted once.',
    at_limit:
      'New submissions are rejected with 402 QUOTA_EXCEEDED. Jobs already queued keep running.',
    overage: `$${OVERAGE_PER_1K_USD.toFixed(2)} per extra 1,000 jobs`,
    tips: [
      'Use an Idempotency-Key — retried submissions then stop counting twice.',
      'Batch small units of work into one job instead of one job per item.',
      'Dead-lettered jobs already consumed quota; fix the cause instead of replaying blindly.',
    ],
  },
  compute: {
    counted:
      'Wall-clock seconds spent inside the sandbox, summed across every attempt. Queue time is not counted.',
    at_limit: 'Running jobs are allowed to finish; new ones are rejected until the period resets.',
    overage: null,
    tips: [
      'Lower the per-job timeout — a runaway job burns the quota for everyone.',
      'Retries re-run the whole job, so reducing the retry rate directly cuts compute.',
      'Node has a shorter cold start than Python for short-lived jobs.',
    ],
  },
  concurrency: {
    counted: 'The highest number of jobs running at the same moment during this period.',
    at_limit: 'Extra jobs stay queued instead of being rejected — throughput drops, nothing fails.',
    overage: null,
    tips: [
      'Spread submissions out instead of sending a burst at the top of the hour.',
      'Give latency-sensitive work a higher priority so it is not stuck behind batch jobs.',
    ],
  },
}

/** Kvota qiymatini o'lchagich bilan BIR XIL birlikda formatlaydi. */
function formatQuotaValue(key: string, value: number): string {
  return key === 'compute' ? `${(value / 3_600).toFixed(1)}h` : formatCompact(value)
}

/**
 * Bitta kvota o'lchagichining tafsiloti.
 *
 * Kunlik taqsimot `dailyVolume()` dan olinadi va o'lchagichning JAMI
 * qiymatiga moslashtiriladi — aks holda grafik yig'indisi karta ustidagi
 * son bilan to'g'ri kelmaydi va foydalanuvchi qaysi biriga ishonishni
 * bilmay qoladi.
 */
export function quotaBreakdown(key: string): QuotaBreakdown | null {
  const summary = usageSummary()
  const meter = summary.meters.find((m) => m.key === key)
  if (!meter) return null

  const copy = QUOTA_COPY[key] ?? {
    counted: 'Usage recorded against this plan limit.',
    at_limit: 'New requests are rejected once the limit is reached.',
    overage: null,
    tips: [],
  }

  const volume = dailyVolume()
  const volumeTotal = volume.reduce((sum, d) => sum + d.count, 0) || 1
  const daily: QuotaDailyPoint[] = volume.map((d) => ({
    date: d.date,
    label: d.label,
    // Umumiy sonni o'lchagichnikiga keltiramiz
    value: Math.round((d.count / volumeTotal) * meter.current),
  }))

  const costs = runtimeCosts()
  const runtimeTotal = costs.reduce((sum, r) => sum + r.compute_seconds, 0) || 1
  const by_runtime: QuotaSlice[] = costs.map((row) => {
    const share = row.compute_seconds / runtimeTotal
    const value = Math.round(meter.current * share)
    return {
      label: row.runtime,
      value,
      value_label: formatQuotaValue(key, value),
      percent: Math.round(share * 1_000) / 10,
    }
  })

  // Kalitlar bo'yicha taqsimot — faol kalitlar og'irligi bir xil emas
  const keys = allApiKeys().filter((k) => k.is_active)
  const weights = keys.map((k, i) => 1 / (i + 1.4) + (k.scopes.includes('jobs:write') ? 0.8 : 0))
  const weightTotal = weights.reduce((sum, w) => sum + w, 0) || 1
  const by_api_key: QuotaSlice[] = keys.map((k, i) => {
    const share = (weights[i] ?? 0) / weightTotal
    const value = Math.round(meter.current * share)
    return {
      label: k.name,
      value,
      value_label: formatQuotaValue(key, value),
      percent: Math.round(share * 1_000) / 10,
    }
  })

  return {
    key: meter.key,
    label: meter.label,
    current: meter.current,
    limit: meter.limit,
    percent: meter.percent,
    current_label: meter.current_label,
    limit_label: meter.limit_label,
    resets_at: summary.period_end,
    counted: copy.counted,
    at_limit: copy.at_limit,
    overage_label: copy.overage,
    daily,
    by_runtime,
    by_api_key: by_api_key.sort((a, b) => b.value - a.value),
    tips: copy.tips,
  }
}

// ───────────────────────────────────────────────────────────────────────────
// "Nima bo'lardi" kalkulyatori
// ───────────────────────────────────────────────────────────────────────────

/**
 * Berilgan hajm har bir rejada qancha turishini hisoblaydi.
 *
 * Model ataylab SODDA va oshkora: asosiy to'lov + limitdan oshgan har
 * 1000 job uchun qo'shimcha. Yashirin koeffitsientlar yo'q, shuning
 * uchun foydalanuvchi raqamni o'zi tekshira oladi.
 */
export function estimateCost(monthlyJobs: number, avgDurationMs: number): CostEstimate {
  const jobs = Math.max(0, Math.round(monthlyJobs))
  const durationMs = Math.max(1, Math.round(avgDurationMs))

  const plans: PlanCostEstimate[] = (Object.keys(PLAN_LIMITS) as PlanType[]).map((plan) => {
    const limit = PLAN_LIMITS[plan].monthly_jobs
    const over = Math.max(0, jobs - limit)
    const overage = Math.round((over / 1_000) * OVERAGE_PER_1K_USD * 100) / 100
    const base = PLAN_BASE_USD[plan]
    return {
      plan,
      base_usd: base,
      overage_usd: overage,
      total_usd: Math.round((base + overage) * 100) / 100,
      fits: over === 0,
      over_by: limit === 0 ? 0 : Math.round((jobs / limit) * 10) / 10,
    }
  })

  // Tavsiya: hajm SIG'ADIGAN rejalardan eng arzoni. Hech biri sig'masa —
  // umumiy narxi eng kichik reja (oshirib ishlatish ba'zan arzonroq)
  const fitting = plans.filter((p) => p.fits)
  const pool = fitting.length > 0 ? fitting : plans
  const best = pool.reduce((cheapest, p) => (p.total_usd < cheapest.total_usd ? p : cheapest), pool[0] as PlanCostEstimate)
  const current = plans.find((p) => p.plan === CURRENT_PLAN) as PlanCostEstimate

  return {
    monthly_jobs: jobs,
    avg_duration_ms: durationMs,
    compute_seconds: Math.round((jobs * durationMs) / 1_000),
    plans,
    recommended: best.plan,
    savings_usd: Math.round((current.total_usd - best.total_usd) * 100) / 100,
  }
}

// ───────────────────────────────────────────────────────────────────────────
// Reja almashtirish ko'rinishi
// ───────────────────────────────────────────────────────────────────────────

function limitRow(
  label: string,
  from: number,
  to: number,
  fmt: (n: number) => string,
): PlanChangeRow {
  return {
    label,
    from: fmt(from),
    to: fmt(to),
    direction: to > from ? 'better' : to < from ? 'worse' : 'same',
  }
}

/**
 * Reja almashtirishdan OLDIN nima o'zgarishini ko'rsatadi.
 *
 * Eng muhimi `blockers`: joriy sarf yangi rejaning limitidan oshgan
 * bo'lsa, pastga tushish darhol `402 QUOTA_EXCEEDED` ga olib keladi.
 * Buni kechikib bilish eng yomon holat, shuning uchun oldindan aytiladi.
 */
export function planChangePreview(to: PlanType): PlanChangePreview {
  const summary = usageSummary()
  const from = summary.plan
  const a = PLAN_LIMITS[from]
  const b = PLAN_LIMITS[to]

  const direction =
    b.price_usd_month > a.price_usd_month
      ? 'upgrade'
      : b.price_usd_month < a.price_usd_month
        ? 'downgrade'
        : 'same'

  const start = new Date(summary.period_start).getTime()
  const end = new Date(summary.period_end).getTime()
  const daysTotal = Math.max(1, Math.round((end - start) / 86_400_000))
  const daysRemaining = Math.max(0, Math.round((end - NOW) / 86_400_000))
  // Yuqoriga ko'tarilish darhol kuchga kiradi va qolgan kunlar uchun
  // farq undiriladi; pastga tushish davr oxirida kuchga kiradi
  const prorated =
    direction === 'upgrade'
      ? Math.round(((b.price_usd_month - a.price_usd_month) * (daysRemaining / daysTotal)) * 100) / 100
      : 0

  const blockers: string[] = []
  const warnings: string[] = []

  if (summary.job_count > b.monthly_jobs) {
    blockers.push(
      `You have already run ${formatCompact(summary.job_count)} jobs this period, which is above the ${formatCompact(b.monthly_jobs)} allowance on ${to}. Submissions would start failing with 402 immediately.`,
    )
  }
  const concurrency = summary.meters.find((m) => m.key === 'concurrency')
  if (concurrency && concurrency.current > b.max_concurrent_jobs) {
    warnings.push(
      `Peak concurrency this period was ${concurrency.current}, above the ${b.max_concurrent_jobs} allowed on ${to}. Extra jobs would queue instead of running.`,
    )
  }
  if (a.allow_network && !b.allow_network) {
    warnings.push('Sandboxes lose outbound network access — jobs that call external APIs will fail.')
  }
  if (b.log_retention_days < a.log_retention_days) {
    warnings.push(
      `Log retention drops from ${a.log_retention_days} to ${b.log_retention_days} days. Older logs are deleted at the next cleanup.`,
    )
  }

  return {
    from,
    to,
    direction,
    price_delta_usd: b.price_usd_month - a.price_usd_month,
    prorated_usd: prorated,
    effective_at:
      direction === 'downgrade' ? summary.period_end : new Date(NOW).toISOString(),
    rows: [
      limitRow('Monthly jobs', a.monthly_jobs, b.monthly_jobs, formatCompact),
      limitRow('Requests / minute', a.requests_per_minute, b.requests_per_minute, formatCompact),
      limitRow('Concurrent jobs', a.max_concurrent_jobs, b.max_concurrent_jobs, String),
      limitRow('Max timeout', a.max_timeout_seconds, b.max_timeout_seconds, (n) => `${n}s`),
      limitRow('Memory per job', a.max_memory_mb, b.max_memory_mb, (n) => `${n} MB`),
      limitRow('CPUs per job', a.max_cpus, b.max_cpus, String),
      limitRow('Log retention', a.log_retention_days, b.log_retention_days, (n) => `${n} days`),
      {
        label: 'Outbound network',
        from: a.allow_network ? 'Allowed' : 'Blocked',
        to: b.allow_network ? 'Allowed' : 'Blocked',
        direction:
          a.allow_network === b.allow_network ? 'same' : b.allow_network ? 'better' : 'worse',
      },
      {
        label: 'Price',
        from: `$${a.price_usd_month}/mo`,
        to: `$${b.price_usd_month}/mo`,
        direction:
          b.price_usd_month === a.price_usd_month
            ? 'same'
            : b.price_usd_month < a.price_usd_month
              ? 'better'
              : 'worse',
      },
    ],
    blockers,
    warnings,
  }
}
