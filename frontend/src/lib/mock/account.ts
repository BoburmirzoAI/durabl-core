/** Hisob sozlamalari mock ma'lumoti. */

import type {
  ApiDefaults,
  LoginEvent,
  LoginResult,
  NotificationSetting,
  TeamMember,
  TeamRole,
  TwoFactorStatus,
  UserSession,
} from '@/types'

import { NOW, Rng } from './seed'
import { MockCollection } from './store'

// ───────────────────────────────────────────────────────────────────────────
// Sessiyalar
// ───────────────────────────────────────────────────────────────────────────

const SESSION_DEFS: readonly {
  browser: string
  os: string
  device: UserSession['device_type']
  location: string
  current?: boolean
}[] = [
  { browser: 'Chrome 141', os: 'macOS 15.1', device: 'desktop', location: 'Tashkent, UZ', current: true },
  { browser: 'Safari 18', os: 'iOS 18.2', device: 'mobile', location: 'Tashkent, UZ' },
  { browser: 'Firefox 133', os: 'Ubuntu 24.04', device: 'desktop', location: 'Frankfurt, DE' },
  { browser: 'durabl-python/2.4.0', os: 'Linux', device: 'api', location: 'us-east-1' },
]

export const sessionStore = new MockCollection<UserSession>(buildSessions, (s) => s.id)

function buildSessions(): UserSession[] {
  return SESSION_DEFS.map((def, i) => {
    const rng = new Rng(i * 7_919 + 311)
    const createdAt = NOW - rng.int(1, 40) * 86_400_000
    return {
      id: `sess_${rng.hex(10)}`,
      browser: def.browser,
      os: def.os,
      device_type: def.device,
      ip: `${rng.int(20, 210)}.${rng.int(0, 255)}.${rng.int(0, 255)}.${rng.int(1, 254)}`,
      location: def.location,
      created_at: new Date(createdAt).toISOString(),
      last_active_at: new Date(
        def.current ? NOW - rng.int(5, 120) * 1_000 : NOW - rng.int(1, 300) * 60_000,
      ).toISOString(),
      is_current: def.current ?? false,
    }
  })
}

export function allSessions(): UserSession[] {
  return sessionStore.all()
}

// ───────────────────────────────────────────────────────────────────────────
// Kirish tarixi
// ───────────────────────────────────────────────────────────────────────────

const LOGIN_WEIGHTS: readonly (readonly [LoginResult, number])[] = [
  ['success', 78],
  ['failed_password', 14],
  ['failed_2fa', 5],
  ['blocked', 3],
]

/**
 * Kirish tarixi.
 *
 * Muvaffaqiyatsiz urinishlar ataylab aralashtirilgan: jurnalning butun
 * ma'nosi "menikidan boshqa kirish bo'lganmi?" degan savolga javob
 * berish, shuning uchun unda faqat muvaffaqiyatli qatorlar bo'lsa
 * foydasi yo'q.
 */
export function loginHistory(limit = 14): LoginEvent[] {
  return Array.from({ length: limit }, (_, i) => {
    const rng = new Rng(i * 104_729 + 7)
    const result = i === 0 ? 'success' : rng.weighted(LOGIN_WEIGHTS)
    const suspicious = result !== 'success' && rng.bool(0.5)
    return {
      id: `login_${rng.hex(10)}`,
      at: new Date(NOW - (i * 9 + rng.int(1, 8)) * 3_600_000).toISOString(),
      result,
      ip: `${rng.int(20, 210)}.${rng.int(0, 255)}.${rng.int(0, 255)}.${rng.int(1, 254)}`,
      location: suspicious
        ? rng.pick(['Unknown', 'Hanoi, VN', 'São Paulo, BR', 'Lagos, NG'])
        : rng.pick(['Tashkent, UZ', 'Tashkent, UZ', 'Samarkand, UZ', 'Frankfurt, DE']),
      browser: rng.pick(['Chrome 141', 'Safari 18', 'Firefox 133', 'curl/8.7.1']),
      os: rng.pick(['macOS 15.1', 'iOS 18.2', 'Ubuntu 24.04', 'Windows 11']),
      method: rng.pick(['password', 'password+2fa', 'api_key'] as const),
    }
  })
}

// ───────────────────────────────────────────────────────────────────────────
// 2FA
// ───────────────────────────────────────────────────────────────────────────

/** Base32 alifbosi (RFC 4648) — TOTP kaliti shu alifboda bo'lishi shart. */
const BASE32 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567'

export const twoFactorStore = new MockCollection<TwoFactorStatus & { id: string }>(
  () => [{ id: 'self', enabled: false, enabled_at: null, recovery_codes_left: 0 }],
  (row) => row.id,
)

export function twoFactorStatus(): TwoFactorStatus {
  const row = twoFactorStore.all()[0]
  return {
    enabled: row?.enabled ?? false,
    enabled_at: row?.enabled_at ?? null,
    recovery_codes_left: row?.recovery_codes_left ?? 0,
  }
}

/** Yangi TOTP kaliti — har chaqiruvda boshqacha (haqiqiy sozlash shunday). */
export function generateTotpSecret(): string {
  const rng = new Rng(Date.now() % 1_000_003)
  return Array.from({ length: 32 }, () => BASE32[rng.int(0, BASE32.length - 1)]).join('')
}

/** Tiklash kodlari — har biri bir martalik. */
export function generateRecoveryCodes(count = 10): string[] {
  const rng = new Rng((Date.now() + 17) % 1_000_033)
  return Array.from({ length: count }, () => `${rng.hex(4)}-${rng.hex(4)}-${rng.hex(4)}`)
}

// ───────────────────────────────────────────────────────────────────────────
// Jamoa
// ───────────────────────────────────────────────────────────────────────────

const TEAM_DEFS: readonly {
  email: string
  name: string
  role: TeamRole
  status: TeamMember['status']
}[] = [
  { email: 'jordan@durabl.dev', name: 'Jordan Diaz', role: 'owner', status: 'active' },
  { email: 'mina@durabl.dev', name: 'Mina Okafor', role: 'admin', status: 'active' },
  { email: 'raul@durabl.dev', name: 'Raúl Pérez', role: 'developer', status: 'active' },
  { email: 'kenji@durabl.dev', name: 'Kenji Watanabe', role: 'developer', status: 'active' },
  { email: 'ana@contractor.io', name: null as unknown as string, role: 'viewer', status: 'invited' },
  { email: 'sam@durabl.dev', name: 'Sam Reed', role: 'developer', status: 'suspended' },
]

export const teamStore = new MockCollection<TeamMember>(buildTeam, (m) => m.id)

function buildTeam(): TeamMember[] {
  return TEAM_DEFS.map((def, i) => {
    const rng = new Rng(i * 15_173 + 59)
    const invited = def.status === 'invited'
    return {
      id: `tm_${rng.hex(10)}`,
      email: def.email,
      full_name: def.name ?? null,
      initials: (def.name ?? def.email)
        .split(/[\s@.]/)
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => (part[0] ?? '').toUpperCase())
        .join(''),
      role: def.role,
      status: def.status,
      joined_at: invited ? null : new Date(NOW - rng.int(20, 600) * 86_400_000).toISOString(),
      last_active_at: invited
        ? null
        : new Date(NOW - rng.int(1, 400) * 60_000 * (def.status === 'suspended' ? 900 : 1)).toISOString(),
      invite_expires_at: invited ? new Date(NOW + rng.int(1, 6) * 86_400_000).toISOString() : null,
    }
  })
}

export function allTeamMembers(): TeamMember[] {
  return teamStore.all()
}

// ───────────────────────────────────────────────────────────────────────────
// Bildirishnomalar
// ───────────────────────────────────────────────────────────────────────────

const NOTIFICATION_DEFS: readonly Omit<NotificationSetting, 'email' | 'in_app' | 'webhook'>[] = [
  {
    event: 'job.failed',
    label: 'Job failed',
    description: 'Every individual job failure, before retries are exhausted.',
    noisy: true,
  },
  {
    event: 'job.dead_lettered',
    label: 'Job dead-lettered',
    description: 'A job exhausted all retries and landed in the DLQ.',
    noisy: false,
  },
  {
    event: 'dlq.threshold',
    label: 'DLQ above threshold',
    description: 'The dead letter queue grew past the alert threshold.',
    noisy: false,
  },
  {
    event: 'quota.warning',
    label: 'Quota at 80%',
    description: 'You have used 80% of the monthly job allowance.',
    noisy: false,
  },
  {
    event: 'quota.exceeded',
    label: 'Quota exceeded',
    description: 'New submissions are being rejected with 402.',
    noisy: false,
  },
  {
    event: 'worker.down',
    label: 'Worker stopped responding',
    description: 'A worker missed its heartbeats and its leases expired.',
    noisy: false,
  },
  {
    event: 'api_key.expiring',
    label: 'API key expiring',
    description: 'A key expires within 7 days.',
    noisy: false,
  },
  {
    event: 'weekly.digest',
    label: 'Weekly digest',
    description: 'A Monday summary of volume, failures and spend.',
    noisy: false,
  },
]

/** Standart tanlov — shovqinli hodisalar faqat ilova ichida. */
const DEFAULT_CHANNELS: Record<string, { email: boolean; in_app: boolean; webhook: boolean }> = {
  'job.failed': { email: false, in_app: true, webhook: true },
  'job.dead_lettered': { email: true, in_app: true, webhook: true },
  'dlq.threshold': { email: true, in_app: true, webhook: false },
  'quota.warning': { email: true, in_app: true, webhook: false },
  'quota.exceeded': { email: true, in_app: true, webhook: false },
  'worker.down': { email: true, in_app: true, webhook: false },
  'api_key.expiring': { email: true, in_app: false, webhook: false },
  'weekly.digest': { email: true, in_app: false, webhook: false },
}

export const notificationSettingStore = new MockCollection<NotificationSetting>(
  () =>
    NOTIFICATION_DEFS.map((def) => ({
      ...def,
      ...(DEFAULT_CHANNELS[def.event] ?? { email: false, in_app: true, webhook: false }),
    })),
  (row) => row.event,
)

export function allNotificationSettings(): NotificationSetting[] {
  return notificationSettingStore.all()
}

// ───────────────────────────────────────────────────────────────────────────
// Job standartlari
// ───────────────────────────────────────────────────────────────────────────

export const apiDefaultsStore = new MockCollection<ApiDefaults & { id: string }>(
  () => [
    {
      id: 'self',
      runtime: 'python',
      timeout_seconds: 300,
      memory_mb: 512,
      max_retries: 3,
      retry_backoff: 'exponential',
      priority: 'normal',
      auto_idempotency: true,
    },
  ],
  (row) => row.id,
)

export function apiDefaults(): ApiDefaults {
  const { id: _id, ...rest } = apiDefaultsStore.all()[0] as ApiDefaults & { id: string }
  return rest
}
