/**
 * Admin uchun foydalanuvchi detali.
 *
 * ═══════════════════════════════════════════════════════════════════════
 * NEGA ALOHIDA GENERATOR
 * ═══════════════════════════════════════════════════════════════════════
 *
 * Loyihadagi boshqa mock'lar BITTA foydalanuvchi uchun qurilgan (job'lar,
 * DLQ, kalitlar — hammasi joriy hisobniki). Admin esa boshqa odamlarning
 * hisobini ko'radi: har bir foydalanuvchi uchun BOSHQA ma'lumot chiqishi
 * kerak, aks holda 40 ta foydalanuvchining hammasi bir xil ko'rinadi va
 * sahifa yolg'onga aylanadi.
 *
 * Shuning uchun hamma narsa foydalanuvchi ID'sidan kelib chiqadigan
 * barqaror urug' bilan generatsiya qilinadi: bir odam qayta ochilganda
 * ayni ma'lumot chiqadi, boshqa odamda esa boshqasi.
 */

import type {
  AdminCreditEntry,
  AdminUser,
  AdminUserActivity,
  AdminUserDetail,
  AdminUserDlqEntry,
  AdminUserJob,
  AdminUserKey,
  AdminUserWebhook,
  AdminUsagePoint,
  JobStatus,
  Runtime,
} from '@/types'

import { allAdminUsers } from './users'
import { NOW, Rng } from './seed'
import { MockCollection } from './store'

/** Foydalanuvchi ID'sidan barqaror urug'. */
function seedOf(userId: string): number {
  let h = 2_166_136_261
  for (let i = 0; i < userId.length; i += 1) {
    h ^= userId.charCodeAt(i)
    h = Math.imul(h, 16_777_619)
  }
  return Math.abs(h) % 2_000_003
}

const JOB_STATUS_WEIGHTS: readonly (readonly [JobStatus, number])[] = [
  ['success', 72],
  ['failed', 9],
  ['running', 6],
  ['queued', 6],
  ['dead_letter', 4],
  ['cancelled', 3],
]

const ERROR_TYPES = [
  'TimeoutError',
  'ConnectionError',
  'KeyError',
  'MemoryError',
  'ValueError',
  'HTTPError',
] as const

const KEY_NAMES = ['Production', 'CI pipeline', 'Local dev', 'Staging', 'Data team'] as const

const WEBHOOK_HOSTS = [
  'https://hooks.acme.io/durabl',
  'https://api.partner.dev/events',
  'https://ops.internal.example/webhook',
] as const

/** Admin yozgan eslatmalar — tahrirlanadi, shuning uchun do'konda. */
export const adminNoteStore = new MockCollection<{ id: string; note: string }>(() => [], (n) => n.id)

/** Qo'lda qo'shilgan kredit yozuvlari (asosiy tarixdan tashqari). */
export const creditStore = new MockCollection<AdminCreditEntry & { user_id: string }>(
  () => [],
  (c) => c.id,
)

function buildUsage(rng: Rng, user: AdminUser): AdminUsagePoint[] {
  const daily = Math.max(1, Math.round(user.jobs_this_period / 30))
  return Array.from({ length: 30 }, (_, i) => {
    const date = new Date(NOW - (29 - i) * 86_400_000)
    const weekend = date.getUTCDay() === 0 || date.getUTCDay() === 6
    const jobs = user.is_active
      ? Math.round(daily * (weekend ? 0.4 : 1) * (0.7 + rng.next() * 0.6))
      : 0
    return {
      date: date.toISOString().slice(0, 10),
      jobs,
      failed: Math.round(jobs * (rng.next() * 0.06)),
    }
  })
}

function buildJobs(rng: Rng, user: AdminUser): AdminUserJob[] {
  if (user.job_count === 0) return []
  return Array.from({ length: Math.min(12, user.job_count) }, (_, i) => {
    const status = rng.weighted(JOB_STATUS_WEIGHTS)
    const terminal = status !== 'running' && status !== 'queued'
    return {
      id: `job_${rng.hex(10)}`,
      status,
      runtime: rng.pick(['python', 'node'] as Runtime[]),
      created_at: new Date(NOW - (i * 37 + rng.int(1, 30)) * 60_000).toISOString(),
      duration_ms: terminal ? rng.int(180, 42_000) : null,
      attempts: status === 'dead_letter' ? rng.int(3, 5) : status === 'failed' ? rng.int(1, 3) : 1,
    }
  })
}

function buildDlq(rng: Rng, user: AdminUser): AdminUserDlqEntry[] {
  return Array.from({ length: user.dlq_depth }, (_, i) => {
    const errorType = rng.pick(ERROR_TYPES)
    return {
      id: `dlq_${rng.hex(10)}`,
      job_id: `job_${rng.hex(10)}`,
      error_type: errorType,
      last_error:
        errorType === 'TimeoutError'
          ? 'Execution exceeded the 300s timeout'
          : errorType === 'MemoryError'
            ? 'Sandbox killed: memory limit exceeded'
            : `${errorType} raised in main()`,
      failed_at: new Date(NOW - (i * 5 + rng.int(1, 40)) * 3_600_000).toISOString(),
      retry_count: rng.int(3, 5),
    }
  })
}

function buildKeys(rng: Rng, user: AdminUser): AdminUserKey[] {
  return Array.from({ length: user.api_key_count }, (_, i) => {
    const prefix = `durabl_${rng.hex(8)}`
    const active = user.is_active && rng.bool(0.85)
    return {
      id: `key_${rng.hex(10)}`,
      name: KEY_NAMES[i % KEY_NAMES.length] as string,
      masked_key: `${prefix}${'•'.repeat(8)}${rng.hex(4)}`,
      last_used_at: active ? new Date(NOW - rng.int(1, 4_000) * 60_000).toISOString() : null,
      created_at: new Date(NOW - rng.int(10, 400) * 86_400_000).toISOString(),
      is_active: active,
    }
  })
}

function buildWebhooks(rng: Rng, user: AdminUser): AdminUserWebhook[] {
  const count = user.is_active ? rng.int(0, 3) : 0
  return Array.from({ length: count }, (_, i) => {
    const failing = rng.bool(0.2)
    return {
      id: `wh_${rng.hex(10)}`,
      url: `${WEBHOOK_HOSTS[i % WEBHOOK_HOSTS.length]}/${rng.hex(6)}`,
      is_active: !failing || rng.bool(0.5),
      success_rate: failing ? rng.int(30, 80) : rng.int(95, 100),
      consecutive_failures: failing ? rng.int(1, 9) : 0,
      last_triggered_at: new Date(NOW - rng.int(2, 3_000) * 60_000).toISOString(),
    }
  })
}

const CREDIT_REASONS = [
  'Goodwill credit after the May incident',
  'Annual prepay discount',
  'Refund — duplicate charge',
  'Monthly subscription',
  'Overage charge',
] as const

function buildCredits(rng: Rng): AdminCreditEntry[] {
  const count = rng.int(2, 6)
  return Array.from({ length: count }, (_, i) => {
    const kind = rng.pick(['credit', 'refund', 'charge', 'adjustment'] as const)
    const magnitude = rng.int(5, 400)
    return {
      id: `cr_${rng.hex(10)}`,
      at: new Date(NOW - (i * 24 + rng.int(1, 20)) * 86_400_000).toISOString(),
      amount_usd: kind === 'charge' ? -magnitude : magnitude,
      reason: rng.pick(CREDIT_REASONS),
      actor: kind === 'charge' ? 'system' : 'admin@durabl.dev',
      kind,
    }
  }).sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime())
}

function buildActivity(rng: Rng, user: AdminUser): AdminUserActivity[] {
  const events: { action: string; summary: string; admin: boolean }[] = [
    { action: 'user.created', summary: 'Account created', admin: false },
    { action: 'api_key.created', summary: 'Created API key "Production"', admin: false },
    { action: 'plan.changed', summary: `Plan changed to ${user.plan}`, admin: true },
    { action: 'webhook.created', summary: 'Added a webhook endpoint', admin: false },
    { action: 'job.cancelled', summary: 'Cancelled a running job', admin: false },
    { action: 'dlq.purged', summary: 'Purged 12 dead letters', admin: true },
    { action: 'api_key.revoked', summary: 'Revoked API key "Local dev"', admin: false },
    { action: 'user.deactivated', summary: 'Account suspended for non-payment', admin: true },
  ]
  const count = user.is_active ? rng.int(4, 7) : events.length
  return events.slice(0, count).map((event, i) => ({
    id: `act_${rng.hex(10)}`,
    at: new Date(NOW - (i * 31 + rng.int(1, 28)) * 86_400_000).toISOString(),
    action: event.action,
    summary: event.summary,
    actor: event.admin ? 'admin@durabl.dev' : user.email,
    by_admin: event.admin,
  }))
}

/** Bitta foydalanuvchining to'liq admin ko'rinishi. */
export function adminUserDetail(userId: string): AdminUserDetail | null {
  const user = allAdminUsers().find((u) => u.id === userId)
  if (!user) return null

  const rng = new Rng(seedOf(userId))
  const credits = [
    ...creditStore.all().filter((c) => c.user_id === userId),
    ...buildCredits(rng),
  ].sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime())

  const creditBalance = credits
    .filter((c) => c.kind !== 'charge')
    .reduce((sum, c) => sum + c.amount_usd, 0)

  return {
    user,
    usage: buildUsage(rng, user),
    jobs: buildJobs(rng, user),
    dlq: buildDlq(rng, user),
    keys: buildKeys(rng, user),
    webhooks: buildWebhooks(rng, user),
    credits,
    activity: buildActivity(rng, user),
    balance_usd: Math.round(rng.int(0, 48_000) / 100) / 10,
    credit_balance_usd: Math.round(creditBalance * 100) / 100,
    note: adminNoteStore.find(userId)?.note ?? null,
  }
}
