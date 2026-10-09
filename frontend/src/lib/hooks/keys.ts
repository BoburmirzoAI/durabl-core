/**
 * TanStack Query kalitlari — yagona manba.
 *
 * Kalitlar iyerarxik: `['jobs']` butun bo'limni invalidatsiya qiladi,
 * `['jobs', 'list', filters]` esa faqat bitta ro'yxatni. Shu tufayli
 * mutatsiyadan keyin keraksiz qayta so'rovlar bo'lmaydi.
 */

import type {
  AdminUserFilters,
  AuditFilters,
  DeliveryFilters,
  DlqFilters,
  JobFilters,
  NotificationFilters,
  ScheduleFilters,
  TicketFilters,
} from '@/types'
import type { ExecutionFilters } from '@/lib/api/executions.api'

export const QK = {
  jobs: {
    all: ['jobs'] as const,
    list: (filters: JobFilters) => ['jobs', 'list', filters] as const,
    detail: (id: string) => ['jobs', 'detail', id] as const,
    logs: (id: string) => ['jobs', 'logs', id] as const,
    executions: (id: string) => ['jobs', 'executions', id] as const,
    timeline: (id: string) => ['jobs', 'timeline', id] as const,
    result: (id: string) => ['jobs', 'result', id] as const,
    lease: (id: string) => ['jobs', 'lease', id] as const,
    idempotency: (id: string) => ['jobs', 'idempotency', id] as const,
  },
  executions: {
    all: ['executions'] as const,
    list: (filters: ExecutionFilters) => ['executions', 'list', filters] as const,
    detail: (id: string) => ['executions', 'detail', id] as const,
    logs: (id: string) => ['executions', 'logs', id] as const,
  },
  dlq: {
    all: ['dlq'] as const,
    list: (filters: DlqFilters) => ['dlq', 'list', filters] as const,
    detail: (id: string) => ['dlq', 'detail', id] as const,
    stats: ['dlq', 'stats'] as const,
  },
  analytics: {
    all: ['analytics'] as const,
    dashboard: (range: string) => ['analytics', 'dashboard', range] as const,
    overview: (range: string) => ['analytics', 'overview', range] as const,
    throughput: (range: string) => ['analytics', 'throughput', range] as const,
    percentiles: (range: string) => ['analytics', 'percentiles', range] as const,
    busiest: ['analytics', 'busiest-hours'] as const,
    slowest: ['analytics', 'slowest-jobs'] as const,
    retryRate: (range: string) => ['analytics', 'retry-rate', range] as const,
    workerEfficiency: ['analytics', 'worker-efficiency'] as const,
    costEfficiency: (range: string) => ['analytics', 'cost-efficiency', range] as const,
    runtimeComparison: ['analytics', 'runtime-comparison'] as const,
    comparison: (range: string) => ['analytics', 'comparison', range] as const,
  },
  webhooks: {
    all: ['webhooks'] as const,
    list: ['webhooks', 'list'] as const,
    detail: (id: string) => ['webhooks', 'detail', id] as const,
    deliveries: (filters: DeliveryFilters) => ['webhooks', 'deliveries', filters] as const,
  },
  schedules: {
    all: ['schedules'] as const,
    list: (filters: ScheduleFilters) => ['schedules', 'list', filters] as const,
    detail: (id: string) => ['schedules', 'detail', id] as const,
    runs: (id: string) => ['schedules', 'runs', id] as const,
    cron: (expression: string) => ['schedules', 'cron', expression] as const,
  },
  templates: {
    all: ['templates'] as const,
    list: ['templates', 'list'] as const,
  },
  account: {
    all: ['account'] as const,
    sessions: ['account', 'sessions'] as const,
    loginHistory: ['account', 'login-history'] as const,
    twoFactor: ['account', '2fa'] as const,
    team: ['account', 'team'] as const,
    notificationSettings: ['account', 'notification-settings'] as const,
    apiDefaults: ['account', 'job-defaults'] as const,
  },
  apiKeys: {
    all: ['api-keys'] as const,
    list: ['api-keys', 'list'] as const,
    usage: (id: string) => ['api-keys', 'usage', id] as const,
  },
  billing: {
    all: ['billing'] as const,
    plans: ['billing', 'plans'] as const,
    usage: ['billing', 'usage'] as const,
    volume: ['billing', 'volume'] as const,
    projection: ['billing', 'projection'] as const,
    runtimeCosts: ['billing', 'runtime-costs'] as const,
    invoices: ['billing', 'invoices'] as const,
    comparison: ['billing', 'comparison'] as const,
    quota: (key: string) => ['billing', 'quota', key] as const,
    estimate: (jobs: number, durationMs: number) =>
      ['billing', 'estimate', jobs, durationMs] as const,
    planPreview: (plan: string) => ['billing', 'plan-preview', plan] as const,
  },
  workers: {
    all: ['workers'] as const,
    list: ['workers', 'list'] as const,
    queues: ['workers', 'queues'] as const,
    system: ['workers', 'system'] as const,
    controls: ['workers', 'controls'] as const,
  },
  notifications: {
    all: ['notifications'] as const,
    list: (filters: NotificationFilters) => ['notifications', 'list', filters] as const,
    unread: ['notifications', 'unread'] as const,
  },
  adminOps: {
    all: ['admin-ops'] as const,
    audit: (filters: AuditFilters) => ['admin-ops', 'audit', filters] as const,
    billing: ['admin-ops', 'billing'] as const,
    announcements: ['admin-ops', 'announcements'] as const,
    tickets: (filters: TicketFilters) => ['admin-ops', 'tickets', filters] as const,
    executions: ['admin-ops', 'executions'] as const,
    dlq: ['admin-ops', 'dlq'] as const,
    webhooks: ['admin-ops', 'webhooks'] as const,
    planWorkload: ['admin-ops', 'plan-workload'] as const,
  },
  platform: {
    all: ['platform'] as const,
    rateLimits: ['platform', 'rate-limits'] as const,
    plans: ['platform', 'plans'] as const,
    sandbox: ['platform', 'sandbox'] as const,
    queue: ['platform', 'queue'] as const,
    secrets: ['platform', 'secrets'] as const,
    backups: ['platform', 'backups'] as const,
    backupSettings: ['platform', 'backup-settings'] as const,
  },
  admin: {
    all: ['admin'] as const,
    stats: ['admin', 'stats'] as const,
    users: (filters: AdminUserFilters) => ['admin', 'users', filters] as const,
    user: (id: string) => ['admin', 'user', id] as const,
    activity: ['admin', 'activity'] as const,
    userDetail: (id: string) => ['admin', 'user-detail', id] as const,
  },
} as const
