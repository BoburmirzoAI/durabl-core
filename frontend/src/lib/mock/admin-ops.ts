/** Admin operatsion ma'lumoti: audit, billing, e'lonlar, tiketlar. */

import type {
  Announcement,
  AuditCategory,
  AuditEntry,
  OverdueAccount,
  PlanType,
  PlatformBilling,
  RevenueByPlan,
  RevenuePoint,
  DlqByUser,
  PlanWorkload,
  PlatformDlq,
  PlatformExecutions,
  PlatformWebhookRow,
  PlatformWebhooks,
  SupportMessage,
  SupportTicket,
  TicketPriority,
  TicketStatus,
  WorkerExecutionHealth,
} from '@/types'

import { PLAN_LIMITS } from './billing'
import { allAdminUsers } from './users'
import { allWorkers } from './workers'
import { NOW, Rng } from './seed'
import { MockCollection } from './store'

// ───────────────────────────────────────────────────────────────────────────
// Audit jurnali
// ───────────────────────────────────────────────────────────────────────────

const AUDIT_TEMPLATES: readonly {
  category: AuditCategory
  action: string
  targetType: AuditEntry['target_type']
  summary: string
  before?: string
  after?: string
  weight: number
}[] = [
  {
    category: 'user',
    action: 'user.suspended',
    targetType: 'user',
    summary: 'Suspended the account for repeated quota abuse',
    before: 'active',
    after: 'suspended',
    weight: 8,
  },
  {
    category: 'user',
    action: 'user.reactivated',
    targetType: 'user',
    summary: 'Reactivated the account after payment cleared',
    before: 'suspended',
    after: 'active',
    weight: 6,
  },
  {
    category: 'billing',
    action: 'plan.changed',
    targetType: 'user',
    summary: 'Moved the account to a different plan',
    before: 'starter',
    after: 'pro',
    weight: 12,
  },
  {
    category: 'billing',
    action: 'credit.granted',
    targetType: 'user',
    summary: 'Granted goodwill credit after an incident',
    before: '$0.00',
    after: '$150.00',
    weight: 9,
  },
  {
    category: 'security',
    action: 'api_keys.revoked',
    targetType: 'user',
    summary: 'Revoked every API key after a leak report',
    weight: 5,
  },
  {
    category: 'security',
    action: 'secret.rotated',
    targetType: 'secret',
    summary: 'Rotated a platform secret',
    weight: 4,
  },
  {
    category: 'security',
    action: 'impersonation.started',
    targetType: 'user',
    summary: 'Viewed the dashboard as this customer for a support call',
    weight: 7,
  },
  {
    category: 'config',
    action: 'queue.updated',
    targetType: 'config',
    summary: 'Changed the lease TTL',
    before: '15s',
    after: '20s',
    weight: 5,
  },
  {
    category: 'config',
    action: 'sandbox.updated',
    targetType: 'config',
    summary: 'Changed the default sandbox memory limit',
    before: '512 MB',
    after: '768 MB',
    weight: 4,
  },
  {
    category: 'config',
    action: 'rate_limit.updated',
    targetType: 'plan',
    summary: 'Raised the per-minute rate limit',
    before: '600',
    after: '900',
    weight: 5,
  },
  {
    category: 'job',
    action: 'job.force_failed',
    targetType: 'job',
    summary: 'Force-failed a job stuck on an unreachable worker',
    weight: 10,
  },
  {
    category: 'job',
    action: 'dlq.purged',
    targetType: 'dlq',
    summary: 'Purged resolved dead letters older than 30 days',
    weight: 6,
  },
  {
    category: 'system',
    action: 'maintenance.enabled',
    targetType: 'config',
    summary: 'Enabled maintenance mode for a database migration',
    before: 'off',
    after: 'on',
    weight: 3,
  },
  {
    category: 'system',
    action: 'backup.restored',
    targetType: 'config',
    summary: 'Requested a database restore',
    weight: 1,
  },
  {
    category: 'system',
    action: 'worker.drained',
    targetType: 'worker',
    summary: 'Drained a worker before a rolling deploy',
    weight: 8,
  },
]

const ADMIN_ACTORS = ['admin@durabl.dev', 'ops@durabl.dev', 'jordan@durabl.dev', 'system'] as const

export const auditStore = new MockCollection<AuditEntry>(buildAudit, (e) => e.id)

function buildAudit(): AuditEntry[] {
  const users = allAdminUsers()
  const weights = AUDIT_TEMPLATES.map((t) => [t, t.weight] as const)

  return Array.from({ length: 140 }, (_, i) => {
    const rng = new Rng(i * 2_654_435_761 % 1_000_003)
    const template = rng.weighted(weights)
    const user = users[rng.int(0, users.length - 1)]
    const actor =
      template.category === 'system' && rng.bool(0.5)
        ? 'system'
        : (ADMIN_ACTORS[rng.int(0, ADMIN_ACTORS.length - 2)] as string)

    // Rad etilgan amallar ham jurnalga tushadi — aks holda "kim nimani
    // qilmoqchi bo'ldi" degan savol javobsiz qoladi
    const result: AuditEntry['result'] = rng.bool(0.93)
      ? 'success'
      : rng.bool(0.7)
        ? 'denied'
        : 'error'

    const target =
      template.targetType === 'user'
        ? (user?.email ?? 'unknown')
        : template.targetType === 'job'
          ? `job_${rng.hex(10)}`
          : template.targetType === 'secret'
            ? rng.pick(['JWT_SECRET', 'WEBHOOK_SIGNING_KEY', 'STRIPE_SECRET_KEY'])
            : template.targetType === 'worker'
              ? `wrk_${rng.hex(6)}`
              : template.targetType === 'plan'
                ? rng.pick(['free', 'starter', 'pro', 'enterprise'])
                : 'platform'

    return {
      id: `aud_${rng.hex(10)}`,
      at: new Date(NOW - (i * 97 + rng.int(1, 90)) * 60_000).toISOString(),
      category: template.category,
      action: template.action,
      actor,
      target,
      target_type: template.targetType,
      summary: template.summary,
      before: template.before ?? null,
      after: template.after ?? null,
      ip: actor === 'system' ? '10.0.0.4' : `${rng.int(20, 210)}.${rng.int(0, 255)}.${rng.int(0, 255)}.${rng.int(1, 254)}`,
      result,
    }
  })
}

export function allAuditEntries(): AuditEntry[] {
  return auditStore.all()
}

// ───────────────────────────────────────────────────────────────────────────
// Platforma billing'i
// ───────────────────────────────────────────────────────────────────────────

const PAYMENT_FAILURES = [
  'Card declined — insufficient funds',
  'Card expired',
  'Issuer declined — do not honour',
  'No payment method on file',
  'Bank transfer not received',
] as const

/**
 * Platforma daromadi.
 *
 * Barcha raqamlar HAQIQIY foydalanuvchi ro'yxatidan hisoblanadi: MRR —
 * faol hisoblarning tarif narxlari yig'indisi. Alohida tasodifiy son
 * qo'yilsa, "Users" sahifasidagi 40 ta hisob bilan "MRR $84k" mos
 * kelmasdi va butun sahifa yolg'onga o'xshardi.
 */
export function platformBilling(): PlatformBilling {
  const users = allAdminUsers()
  const rng = new Rng(884_221)

  const byPlan: RevenueByPlan[] = (Object.keys(PLAN_LIMITS) as PlanType[]).map((plan) => {
    const accounts = users.filter((u) => u.plan === plan && u.is_active)
    const price = PLAN_LIMITS[plan].price_usd_month
    const mrr = accounts.length * price
    return {
      plan,
      accounts: accounts.length,
      mrr_usd: mrr,
      change_percent: Math.round((rng.next() * 30 - 8) * 10) / 10,
      arpa_usd: accounts.length === 0 ? 0 : Math.round((mrr / accounts.length) * 100) / 100,
    }
  })

  const mrr = byPlan.reduce((sum, row) => sum + row.mrr_usd, 0)

  // 12 oylik tarix — hozirgi MRR'ga olib keladigan o'sish egri chizig'i
  const history: RevenuePoint[] = Array.from({ length: 12 }, (_, i) => {
    const monthsBack = 11 - i
    const date = new Date(NOW)
    date.setUTCMonth(date.getUTCMonth() - monthsBack, 1)
    // Oyiga ~6% o'sish bilan orqaga hisoblaymiz
    const value = Math.round(mrr / 1.06 ** monthsBack)
    const newRevenue = Math.round(value * (0.07 + rng.next() * 0.05))
    return {
      month: date.toISOString().slice(0, 7),
      mrr_usd: value,
      new_usd: newRevenue,
      churned_usd: Math.round(newRevenue * (0.15 + rng.next() * 0.3)),
    }
  })

  const previous = history[history.length - 2]?.mrr_usd ?? mrr
  const churned = history[history.length - 1]?.churned_usd ?? 0

  const overdue: OverdueAccount[] = users
    .filter((u) => u.plan !== 'free' && !u.is_active)
    .slice(0, 6)
    .map((user, i) => {
      const r = new Rng(i * 7_919 + 3)
      return {
        user_id: user.id,
        email: user.email,
        plan: user.plan,
        amount_usd: PLAN_LIMITS[user.plan].price_usd_month * r.int(1, 3),
        days_overdue: r.int(3, 74),
        last_attempt_at: new Date(NOW - r.int(1, 9) * 86_400_000).toISOString(),
        failure_reason: r.pick(PAYMENT_FAILURES),
      }
    })
    .sort((a, b) => b.days_overdue - a.days_overdue)

  return {
    mrr_usd: mrr,
    mrr_change_percent:
      previous === 0 ? 0 : Math.round(((mrr - previous) / previous) * 1_000) / 10,
    arr_usd: mrr * 12,
    churn_percent: mrr === 0 ? 0 : Math.round((churned / mrr) * 1_000) / 10,
    outstanding_usd: overdue.reduce((sum, row) => sum + row.amount_usd, 0),
    paying_accounts: users.filter((u) => u.is_active && u.plan !== 'free').length,
    trial_accounts: users.filter((u) => u.is_active && u.plan === 'free').length,
    by_plan: byPlan,
    history,
    overdue,
  }
}

// ───────────────────────────────────────────────────────────────────────────
// E'lonlar
// ───────────────────────────────────────────────────────────────────────────

const ANNOUNCEMENT_DEFS: readonly {
  title: string
  body: string
  level: Announcement['level']
  status: Announcement['status']
  audience: PlanType[]
  dismissible: boolean
  startOffsetDays: number
  endOffsetDays: number | null
}[] = [
  {
    title: 'Scheduled maintenance on Sunday 02:00–04:00 UTC',
    body: 'The API will accept submissions throughout. Workers pause for roughly 20 minutes while the database is upgraded, so jobs queue instead of running.',
    level: 'warning',
    status: 'scheduled',
    audience: [],
    dismissible: true,
    startOffsetDays: 3,
    endOffsetDays: 4,
  },
  {
    title: 'Elevated webhook delivery latency',
    body: 'Deliveries are retrying normally but arriving 2–5 minutes late. No events are lost. We are adding capacity to the delivery workers.',
    level: 'critical',
    status: 'live',
    audience: [],
    dismissible: false,
    startOffsetDays: -0.2,
    endOffsetDays: null,
  },
  {
    title: 'Node 22 runtime now available',
    body: 'Submit with runtime "node22" to try it. Node 20 stays the default until the end of the quarter.',
    level: 'info',
    status: 'live',
    audience: ['pro', 'enterprise'],
    dismissible: true,
    startOffsetDays: -6,
    endOffsetDays: 20,
  },
  {
    title: 'Free plan quota changes from next month',
    body: 'The monthly allowance moves from 1,000 to 750 jobs. Existing accounts keep 1,000 until their next renewal.',
    level: 'warning',
    status: 'draft',
    audience: ['free'],
    dismissible: true,
    startOffsetDays: 14,
    endOffsetDays: 45,
  },
  {
    title: 'Incident resolved: queue backlog on 2026-09-21',
    body: 'A deploy left two workers unable to renew leases for 14 minutes. Affected jobs were re-queued automatically and completed. No data was lost.',
    level: 'info',
    status: 'ended',
    audience: [],
    dismissible: true,
    startOffsetDays: -15,
    endOffsetDays: -13,
  },
]

export const announcementStore = new MockCollection<Announcement>(buildAnnouncements, (a) => a.id)

function buildAnnouncements(): Announcement[] {
  return ANNOUNCEMENT_DEFS.map((def, i) => {
    const rng = new Rng(i * 15_485_867 % 900_007)
    return {
      id: `ann_${rng.hex(10)}`,
      title: def.title,
      body: def.body,
      level: def.level,
      status: def.status,
      audience: def.audience,
      starts_at: new Date(NOW + def.startOffsetDays * 86_400_000).toISOString(),
      ends_at:
        def.endOffsetDays === null ? null : new Date(NOW + def.endOffsetDays * 86_400_000).toISOString(),
      dismissible: def.dismissible,
      created_by: 'ops@durabl.dev',
      created_at: new Date(NOW - rng.int(1, 30) * 86_400_000).toISOString(),
      seen_by: def.status === 'draft' ? 0 : rng.int(40, 2_400),
    }
  })
}

export function allAnnouncements(): Announcement[] {
  return announcementStore.all()
}

// ───────────────────────────────────────────────────────────────────────────
// Qo'llab-quvvatlash tiketlari
// ───────────────────────────────────────────────────────────────────────────

const TICKET_DEFS: readonly {
  subject: string
  status: TicketStatus
  priority: TicketPriority
  question: string
  reply: string | null
  withJob: boolean
}[] = [
  {
    subject: 'Jobs stuck in queued for 20 minutes',
    status: 'open',
    priority: 'urgent',
    question:
      'We submitted about 400 jobs at 09:00 and none of them started. The dashboard shows them all queued. Is something wrong on your side?',
    reply: null,
    withJob: true,
  },
  {
    subject: 'Webhook signature does not verify',
    status: 'pending',
    priority: 'high',
    question:
      'We compute HMAC_SHA256 over the raw body but the signature never matches. Are we supposed to include the timestamp?',
    reply:
      'Yes — sign the string "{t}." + raw_body, where t is the timestamp from the X-Durabl-Signature header. Signing the body alone will never match.',
    withJob: false,
  },
  {
    subject: 'Charged twice this month',
    status: 'open',
    priority: 'high',
    question: 'We see two charges of $99 on the same day. Could you check?',
    reply: null,
    withJob: false,
  },
  {
    subject: 'How do I replay a dead letter with a fixed payload?',
    status: 'resolved',
    priority: 'normal',
    question:
      'One of our jobs died because of a bad field in the payload. Can I fix the payload and retry the same job?',
    reply:
      'Use Edit & retry on the DLQ row. It submits a NEW job with the corrected payload — the original stays in the DLQ for the record, and the new one gets a fresh idempotency key.',
    withJob: true,
  },
  {
    subject: 'Request: increase concurrency limit',
    status: 'pending',
    priority: 'normal',
    question: 'We are hitting the 50 concurrent job limit during our nightly batch. Can we raise it?',
    reply:
      'We can raise it to 120 on your current plan. It takes effect immediately — confirm and we will apply it.',
    withJob: false,
  },
  {
    subject: 'Timeout on a job that used to finish in 40s',
    status: 'open',
    priority: 'normal',
    question:
      'Same code, same payload, but since yesterday it hits the 300s timeout. Nothing changed on our side.',
    reply: null,
    withJob: true,
  },
  {
    subject: 'Invoice address change',
    status: 'closed',
    priority: 'low',
    question: 'Please update the billing address on our invoices.',
    reply: 'Updated — the next invoice will use the new address.',
    withJob: false,
  },
  {
    subject: 'SSO setup for our workspace',
    status: 'pending',
    priority: 'normal',
    question: 'We would like to connect Okta. What do you need from us?',
    reply: 'Send us your metadata URL and the email domains to allow, and we will configure it.',
    withJob: false,
  },
]

const STAFF = ['mina@durabl.dev', 'raul@durabl.dev', 'ops@durabl.dev'] as const

export const ticketStore = new MockCollection<SupportTicket>(buildTickets, (t) => t.id)

function buildTickets(): SupportTicket[] {
  const users = allAdminUsers().filter((u) => !u.is_admin)

  return TICKET_DEFS.map((def, i) => {
    const rng = new Rng(i * 104_729 + 41)
    const user = users[i % users.length]
    const createdAt = NOW - (i * 9 + rng.int(1, 8)) * 3_600_000
    const answered = def.reply !== null

    const messages: SupportMessage[] = [
      {
        id: `msg_${rng.hex(8)}`,
        at: new Date(createdAt).toISOString(),
        author: user?.email ?? 'customer@example.com',
        from_staff: false,
        body: def.question,
      },
    ]
    const responseMinutes = answered ? rng.int(6, 320) : null
    if (answered && responseMinutes !== null) {
      messages.push({
        id: `msg_${rng.hex(8)}`,
        at: new Date(createdAt + responseMinutes * 60_000).toISOString(),
        author: rng.pick(STAFF),
        from_staff: true,
        body: def.reply as string,
      })
    }

    return {
      id: `tkt_${rng.hex(8)}`,
      subject: def.subject,
      user_id: user?.id ?? 'usr_unknown',
      user_email: user?.email ?? 'customer@example.com',
      plan: user?.plan ?? 'starter',
      status: def.status,
      priority: def.priority,
      first_response_minutes: responseMinutes,
      created_at: new Date(createdAt).toISOString(),
      updated_at: new Date(
        createdAt + (responseMinutes ?? rng.int(5, 60)) * 60_000,
      ).toISOString(),
      assignee: answered ? rng.pick(STAFF) : null,
      related_job_id: def.withJob ? `job_${rng.hex(10)}` : null,
      messages,
    }
  })
}

export function allTickets(): SupportTicket[] {
  return ticketStore.all()
}

// ───────────────────────────────────────────────────────────────────────────
// Platforma agregatlari
// ───────────────────────────────────────────────────────────────────────────

/**
 * Worker bo'yicha bajarish sifati.
 *
 * Mijozning `/executions` sahifasi "mening urinishlarim qanday ketdi"
 * degan savolga javob beradi. Admin uchun savol boshqacha: "QAYSI WORKER
 * ishni yo'qotayapti". Shuning uchun bu yerda agregat worker bo'yicha,
 * va `lost` (lease yo'qolgani uchun uzilgan urinish) birinchi o'rinda —
 * aynan shu ko'rsatkich nosog'lom mashinani ochib beradi.
 */
export function platformExecutions(): PlatformExecutions {
  const workers = allWorkers()

  const byWorker: WorkerExecutionHealth[] = workers.map((worker, i) => {
    const rng = new Rng(i * 48_271 + worker.jobs_processed)
    const executions = Math.max(1, worker.jobs_processed + rng.int(0, 400))
    const dead = worker.state === 'dead'
    // O'lgan worker ko'p urinish yo'qotadi — bu sabab-oqibat bog'liqligi
    const lost = dead ? rng.int(4, 22) : rng.bool(0.3) ? rng.int(1, 3) : 0
    const timeout = Math.round(executions * (rng.next() * 0.02))
    const failed = Math.round(executions * (0.02 + rng.next() * 0.05)) + timeout

    const codes = [0, 1, 137, 2, 124]
    return {
      worker_id: worker.id,
      region: worker.region,
      state: worker.state,
      executions,
      succeeded: executions - failed - lost,
      failed,
      lost,
      timeout,
      avg_duration_ms: rng.int(640, 4_200),
      top_exit_codes: codes
        .map((code) => ({
          code,
          count:
            code === 0
              ? executions - failed - lost
              : code === 137
                ? Math.round(failed * 0.2)
                : Math.round(failed * (0.1 + rng.next() * 0.3)),
        }))
        .filter((row) => row.count > 0)
        .sort((a, b) => b.count - a.count)
        .slice(0, 3),
    }
  })

  const total = byWorker.reduce((sum, w) => sum + w.executions, 0)
  const lost = byWorker.reduce((sum, w) => sum + w.lost, 0)

  return {
    total,
    lost,
    timeout: byWorker.reduce((sum, w) => sum + w.timeout, 0),
    lost_rate: total === 0 ? 0 : Math.round((lost / total) * 10_000) / 100,
    // Eng muammolilari tepada
    by_worker: byWorker.sort((a, b) => b.lost - a.lost || b.failed - a.failed),
  }
}

const DLQ_ERROR_TYPES = [
  'TimeoutError',
  'ConnectionError',
  'KeyError',
  'MemoryError',
  'ValueError',
  'HTTPError',
] as const

/**
 * Platforma DLQ'si — FOYDALANUVCHI bo'yicha.
 *
 * Admin uchun "15 ta dead letter bor" foydasiz. Kerakli savol: "QAYSI
 * mijozda muammo?" — chunki javob qo'ng'iroq qilish yoki kutish degan
 * qarorni belgilaydi.
 */
export function platformDlq(): PlatformDlq {
  const users = allAdminUsers().filter((u) => u.dlq_depth > 0)

  const byUser: DlqByUser[] = users.map((user, i) => {
    const rng = new Rng(i * 15_173 + user.dlq_depth * 7)
    return {
      user_id: user.id,
      email: user.email,
      plan: user.plan,
      depth: user.dlq_depth,
      top_error: rng.pick(DLQ_ERROR_TYPES),
      oldest_at: new Date(NOW - rng.int(2, 400) * 3_600_000).toISOString(),
      added_24h: rng.bool(0.5) ? rng.int(1, Math.max(1, user.dlq_depth)) : 0,
    }
  })

  const depth = byUser.reduce((sum, row) => sum + row.depth, 0)
  const counts = new Map<string, number>()
  for (const row of byUser) counts.set(row.top_error, (counts.get(row.top_error) ?? 0) + row.depth)

  const oldest = byUser
    .map((row) => new Date(row.oldest_at).getTime())
    .sort((a, b) => a - b)[0]

  return {
    depth,
    added_24h: byUser.reduce((sum, row) => sum + row.added_24h, 0),
    resolved_24h: Math.round(depth * 0.18),
    oldest_at: oldest === undefined ? null : new Date(oldest).toISOString(),
    by_user: byUser.sort((a, b) => b.depth - a.depth),
    by_error: [...counts.entries()]
      .map(([error_type, count]) => ({
        error_type,
        count,
        percent: depth === 0 ? 0 : Math.round((count / depth) * 1_000) / 10,
      }))
      .sort((a, b) => b.count - a.count),
  }
}

const PLATFORM_WEBHOOK_HOSTS = [
  'https://hooks.acme.io/durabl',
  'https://api.partner.dev/events',
  'https://ops.internal.example/webhook',
  'https://n8n.customer.app/webhook/durabl',
  'https://zapier-hooks.example/catch',
] as const

/**
 * Platformadagi barcha webhook endpointlari.
 *
 * Nosozlari TEPADA: yiqilgan endpoint — bu kelayotgan qo'llab-quvvatlash
 * tiketi. Uni mijoz yozishidan oldin ko'rish mumkin.
 */
export function platformWebhooks(): PlatformWebhooks {
  const users = allAdminUsers().filter((u) => u.is_active).slice(0, 18)

  const rows: PlatformWebhookRow[] = users.flatMap((user, i) => {
    const rng = new Rng(i * 69_621 + 11)
    const count = rng.int(0, 2)
    return Array.from({ length: count }, (_, j) => {
      const failing = rng.bool(0.22)
      const deliveries = rng.int(20, 2_400)
      const successRate = failing ? rng.int(28, 82) : rng.int(96, 100)
      return {
        id: `wh_${rng.hex(10)}`,
        user_id: user.id,
        email: user.email,
        plan: user.plan,
        url: `${PLATFORM_WEBHOOK_HOSTS[(i + j) % PLATFORM_WEBHOOK_HOSTS.length]}/${rng.hex(6)}`,
        is_active: !failing || rng.bool(0.6),
        success_rate: successRate,
        consecutive_failures: failing ? rng.int(1, 14) : 0,
        deliveries_24h: deliveries,
        failed_24h: Math.round((deliveries * (100 - successRate)) / 100),
        last_triggered_at: new Date(NOW - rng.int(1, 2_000) * 60_000).toISOString(),
      }
    })
  })

  const deliveries = rows.reduce((sum, row) => sum + row.deliveries_24h, 0)
  const failed = rows.reduce((sum, row) => sum + row.failed_24h, 0)

  return {
    endpoints: rows.length,
    failing: rows.filter((row) => row.consecutive_failures > 0).length,
    deliveries_24h: deliveries,
    success_rate_24h:
      deliveries === 0 ? 100 : Math.round(((deliveries - failed) / deliveries) * 1_000) / 10,
    rows: rows.sort(
      (a, b) => b.consecutive_failures - a.consecutive_failures || a.success_rate - b.success_rate,
    ),
  }
}

/** Tarif bo'yicha ish hajmi. */
export function planWorkload(): PlanWorkload[] {
  const users = allAdminUsers()
  const rows = (Object.keys(PLAN_LIMITS) as PlanType[]).map((plan, i) => {
    const rng = new Rng(i * 104_729 + 97)
    const accounts = users.filter((u) => u.plan === plan)
    const jobs = accounts.reduce((sum, u) => sum + Math.round(u.jobs_this_period / 30), 0)
    return {
      plan,
      accounts: accounts.length,
      jobs_24h: jobs,
      success_rate: Math.round((96 + rng.next() * 3.6) * 10) / 10,
      p95_ms: rng.int(1_200, 9_000),
      dlq_depth: accounts.reduce((sum, u) => sum + u.dlq_depth, 0),
      share: 0,
    }
  })
  const total = rows.reduce((sum, row) => sum + row.jobs_24h, 0) || 1
  return rows.map((row) => ({
    ...row,
    share: Math.round((row.jobs_24h / total) * 1_000) / 10,
  }))
}
