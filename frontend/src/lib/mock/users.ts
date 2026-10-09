/** Foydalanuvchi va admin mock ma'lumoti. */

import type { ActivityEvent, AdminStats, AdminUser, PlanType, User } from '@/types'
import { initialsFromName } from '@/lib/utils/format'

import { PLAN_LIMITS } from './billing'
import { dlqDepth } from './dlq'
import { USER_EMAILS, USER_NAMES } from './fixtures'
import { allJobs, statusCounts } from './jobs'
import { NOW, Rng } from './seed'
import { activeWorkerCount } from './workers'
import { MockCollection } from './store'

/**
 * Joriy (kirgan) foydalanuvchi — dizaynda sidebar pastida
 * "Jordan Diaz / jordan@durabl.dev" ko'rsatilgan.
 */
export const CURRENT_USER: User = {
  id: 'usr_current',
  email: 'jordan@durabl.dev',
  full_name: 'Jordan Diaz',
  initials: 'JD',
  is_active: true,
  // Admin panelini ko'rsatish uchun mock foydalanuvchi admin
  is_admin: true,
  plan: 'pro',
  last_login_at: new Date(NOW - 42 * 60_000).toISOString(),
  created_at: new Date(NOW - 412 * 86_400_000).toISOString(),
}

const PLAN_WEIGHTS: readonly (readonly [PlanType, number])[] = [
  ['free', 52],
  ['starter', 28],
  ['pro', 16],
  ['enterprise', 4],
]

const ADMIN_USER_COUNT = 64

/** Foydalanuvchi to'plami — bir marta quriladi, keyin o'zgartiriladi. */
export const userStore = new MockCollection<AdminUser>(build, (item) => item.id)

function build(): AdminUser[] {
  const users: AdminUser[] = [
    {
      ...CURRENT_USER,
      job_count: 18_240,
      jobs_this_period: 284_120,
      dlq_depth: dlqDepth(),
      api_key_count: 3,
    },
  ]

  for (let i = 0; i < ADMIN_USER_COUNT; i += 1) {
    const rng = new Rng(i * 48_271 + 101)
    const name = USER_NAMES[i % USER_NAMES.length] as string
    const emailBase = USER_EMAILS[i % USER_EMAILS.length] as string
    // Takrorlanmas email: indeks qo'shiladi
    const email = i < USER_EMAILS.length ? emailBase : emailBase.replace('@', `${i}@`)
    const plan = rng.weighted(PLAN_WEIGHTS)
    const isActive = rng.bool(0.88)

    users.push({
      id: `usr_${rng.hex(8)}`,
      email,
      full_name: name,
      initials: initialsFromName(name, email),
      is_active: isActive,
      is_admin: rng.bool(0.04),
      plan,
      last_login_at: isActive
        ? new Date(NOW - rng.int(5, 20_000) * 60_000).toISOString()
        : new Date(NOW - rng.int(30, 300) * 86_400_000).toISOString(),
      created_at: new Date(NOW - rng.int(1, 700) * 86_400_000).toISOString(),
      job_count: rng.int(0, 92_000),
      jobs_this_period: rng.int(0, 48_000),
      dlq_depth: rng.bool(0.3) ? rng.int(1, 12) : 0,
      api_key_count: rng.int(0, 5),
    })
  }
  return users
}

export function allAdminUsers(): AdminUser[] {
  return userStore.all()
}

export function adminStats(): AdminStats {
  const users = allAdminUsers()
  const counts = statusCounts()
  const jobs = allJobs()
  const dayAgo = NOW - 86_400_000
  const weekAgo = NOW - 7 * 86_400_000

  const byPlan: Partial<Record<PlanType, number>> = {}
  let mrr = 0
  for (const u of users) {
    byPlan[u.plan] = (byPlan[u.plan] ?? 0) + 1
    if (u.is_active) mrr += PLAN_LIMITS[u.plan].price_usd_month
  }

  const durations = jobs.map((j) => j.duration_ms).filter((d): d is number => d !== null)
  const finished = counts.success + counts.failed + counts.dead_letter + counts.cancelled

  return {
    total_users: users.length,
    active_users: users.filter((u) => u.is_active).length,
    new_users_7d: users.filter((u) => new Date(u.created_at).getTime() >= weekAgo).length,
    total_jobs: 2_418_902,
    jobs_24h: jobs.filter((j) => new Date(j.created_at).getTime() >= dayAgo).length * 42,
    jobs_by_status: counts,
    users_by_plan: byPlan,
    success_rate: finished ? Math.round((counts.success / finished) * 1000) / 10 : 100,
    avg_duration_ms: durations.length
      ? Math.round(durations.reduce((s, d) => s + d, 0) / durations.length)
      : null,
    dlq_depth: dlqDepth(),
    active_workers: activeWorkerCount(),
    mrr_usd: mrr,
  }
}

/** Jonli faollik oqimi (admin bosh sahifasi). */
export function activityFeed(): ActivityEvent[] {
  const rng = new Rng(3_571)
  const templates: readonly { kind: ActivityEvent['kind']; severity: ActivityEvent['severity']; make: (r: Rng) => string }[] = [
    { kind: 'job', severity: 'info', make: (r) => `job_${r.hex(8)} completed in ${r.int(80, 4_200)}ms` },
    { kind: 'dlq', severity: 'error', make: (r) => `job_${r.hex(8)} moved to DLQ after ${r.int(2, 5)} attempts` },
    { kind: 'worker', severity: 'warn', make: (r) => `wkr-0${r.int(1, 6)} heartbeat missed — lease reaped` },
    { kind: 'user', severity: 'info', make: (r) => `${r.pick(USER_EMAILS)} created an API key` },
    { kind: 'webhook', severity: 'warn', make: (r) => `webhook delivery failed (${r.pick([500, 502, 429] as const)})` },
    { kind: 'job', severity: 'info', make: (r) => `${r.int(40, 320)} jobs enqueued by cron schedule` },
    { kind: 'user', severity: 'info', make: (r) => `${r.pick(USER_EMAILS)} upgraded to Pro` },
  ]

  return Array.from({ length: 24 }, (_, i) => {
    const t = templates[i % templates.length] as (typeof templates)[number]
    return {
      id: `act_${rng.hex(8)}`,
      kind: t.kind,
      message: t.make(rng),
      actor: t.kind === 'user' ? rng.pick(USER_EMAILS) : null,
      severity: t.severity,
      at: new Date(NOW - (i * 90 + rng.int(5, 80)) * 1_000).toISOString(),
    }
  })
}

/**
 * Oqim uchun bitta YANGI hodisa.
 *
 * `activityFeed()` dan farqi: bu har chaqiriqda boshqa natija beradi
 * (joriy vaqt urug'i bilan), chunki jonli tasma uchun takrorlanmaslik
 * kerak. Deterministik ro'yxat faqat sahifa birinchi yuklanishida
 * ishlatiladi.
 */
export function nextActivityEvent(): ActivityEvent {
  const rng = new Rng(Date.now() % 1_000_003)
  const templates: readonly { kind: ActivityEvent['kind']; severity: ActivityEvent['severity']; make: (r: Rng) => string }[] = [
    { kind: 'job', severity: 'info', make: (r) => `job_${r.hex(8)} completed in ${r.int(80, 4_200)}ms` },
    { kind: 'job', severity: 'info', make: (r) => `job_${r.hex(8)} claimed by wkr-0${r.int(1, 6)}` },
    { kind: 'dlq', severity: 'error', make: (r) => `job_${r.hex(8)} moved to DLQ after ${r.int(2, 5)} attempts` },
    { kind: 'worker', severity: 'warn', make: (r) => `wkr-0${r.int(1, 6)} heartbeat missed — lease reaped` },
    { kind: 'webhook', severity: 'warn', make: (r) => `webhook delivery failed (${r.pick([500, 502, 429] as const)})` },
    { kind: 'user', severity: 'info', make: (r) => `${r.pick(USER_EMAILS)} created an API key` },
  ]
  const template = rng.pick(templates)
  return {
    id: `act_${rng.hex(10)}_${Date.now()}`,
    kind: template.kind,
    message: template.make(rng),
    actor: template.kind === 'user' ? rng.pick(USER_EMAILS) : null,
    severity: template.severity,
    at: new Date().toISOString(),
  }
}
