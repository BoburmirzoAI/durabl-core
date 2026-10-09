/**
 * Bildirishnomalar mock ma'lumoti.
 *
 * Deterministik: bir xil urug'dan har doim bir xil ro'yxat chiqadi, shuning
 * uchun server va mijoz bir xil HTML ko'radi (hidratsiya nomuvofiqligi yo'q).
 */

import type { AppNotification, NotificationKind, NotificationSeverity } from '@/types'

import { Rng, hoursAgo, minutesAgo } from './seed'

interface Template {
  kind: NotificationKind
  severity: NotificationSeverity
  title: string
  body: (rng: Rng) => string
  href: (rng: Rng) => string | null
}

const jobId = (rng: Rng): string => `job_${rng.hex(8)}`

const TEMPLATES: Template[] = [
  {
    kind: 'job_failed',
    severity: 'critical',
    title: 'Job failed after 3 attempts',
    body: (r) => `${jobId(r)} exhausted its retry budget and moved to the dead letter queue.`,
    href: (r) => `/jobs/${jobId(r)}`,
  },
  {
    kind: 'dlq_entry',
    severity: 'critical',
    title: 'New dead letter entry',
    body: (r) => `A job with key report-${r.int(100, 999)} could not be delivered.`,
    href: () => '/dlq',
  },
  {
    kind: 'webhook_failed',
    severity: 'warning',
    title: 'Webhook delivery failing',
    body: (r) =>
      `${r.pick(['api.acme.io', 'hooks.slack.com', 'staging.shipfast.co'])} returned ${r.pick([500, 502, 503, 504])} on ${r.int(2, 9)} consecutive attempts.`,
    href: () => '/webhooks',
  },
  {
    kind: 'worker_down',
    severity: 'critical',
    title: 'Worker stopped heartbeating',
    body: (r) => `worker-${r.hex(4)} missed its lease renewal and was marked lost.`,
    href: () => '/admin/workers',
  },
  {
    kind: 'quota_warning',
    severity: 'warning',
    title: 'Approaching plan limit',
    body: (r) => `You have used ${r.int(80, 96)}% of this month's job quota.`,
    href: () => '/usage',
  },
  {
    kind: 'job_succeeded',
    severity: 'info',
    title: 'Long-running job finished',
    body: (r) => `${jobId(r)} completed in ${r.int(4, 58)}m ${r.int(10, 59)}s.`,
    href: (r) => `/jobs/${jobId(r)}`,
  },
  {
    kind: 'api_key_created',
    severity: 'info',
    title: 'New API key created',
    body: (r) => `Key dk_live_${r.hex(6)} was created from the dashboard.`,
    href: () => '/api-keys',
  },
  {
    kind: 'system',
    severity: 'info',
    title: 'Scheduled maintenance',
    body: () => 'Queue workers will restart in a rolling fashion. No downtime expected.',
    href: () => null,
  },
]

const COUNT = 24

/** Barcha bildirishnomalar — eng yangisi birinchi. */
export function allNotifications(): AppNotification[] {
  const items: AppNotification[] = []
  for (let i = 0; i < COUNT; i += 1) {
    const rng = new Rng(9_100 + i * 37)
    const template = TEMPLATES[rng.int(0, TEMPLATES.length - 1)] as Template
    // Birinchi 4 tasi soatlar ichida, qolgani kunlar bo'ylab tarqaladi
    const created = i < 4 ? minutesAgo(rng.int(3, 55) + i * 7) : hoursAgo(i * 3 + rng.int(1, 5))
    items.push({
      id: `ntf_${rng.hex(10)}`,
      kind: template.kind,
      severity: template.severity,
      title: template.title,
      body: template.body(rng),
      created_at: created,
      // Dastlabki bir nechtasi o'qilmagan — qo'ng'iroqda nishon ko'rinishi uchun
      read: i >= 5,
      href: template.href(rng),
    })
  }
  return items
}

/** O'qilmaganlar soni — qo'ng'iroq nishoni uchun. */
export function unreadNotificationCount(): number {
  return allNotifications().filter((n) => !n.read).length
}
