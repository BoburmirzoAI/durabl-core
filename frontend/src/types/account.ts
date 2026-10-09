/** Hisob sozlamalari: sessiyalar, 2FA, jamoa, bildirishnomalar. */

import type { Id, IsoDateTime } from './common'
import type { Priority, Runtime } from './job'

// ───────────────────────────────────────────────────────────────────────────
// Sessiyalar va kirish tarixi
// ───────────────────────────────────────────────────────────────────────────

/** Faol sessiya — "qayerdan kirilgan" ro'yxati. */
export interface UserSession {
  id: Id
  browser: string
  os: string
  device_type: 'desktop' | 'mobile' | 'tablet' | 'api'
  ip: string
  location: string
  created_at: IsoDateTime
  last_active_at: IsoDateTime
  /** Shu brauzerdagi joriy sessiya — uni bekor qilib bo'lmaydi. */
  is_current: boolean
}

export type LoginResult = 'success' | 'failed_password' | 'failed_2fa' | 'blocked'

/** Kirish urinishi — buzilgan hisobni aniqlashda eng kerakli jurnal. */
export interface LoginEvent {
  id: Id
  at: IsoDateTime
  result: LoginResult
  ip: string
  location: string
  browser: string
  os: string
  /** Kirish usuli. */
  method: 'password' | 'password+2fa' | 'api_key'
}

// ───────────────────────────────────────────────────────────────────────────
// Ikki bosqichli tasdiqlash
// ───────────────────────────────────────────────────────────────────────────

export interface TwoFactorStatus {
  enabled: boolean
  enabled_at: IsoDateTime | null
  /** Qolgan tiklash kodlari soni. */
  recovery_codes_left: number
}

/**
 * `POST /api/v1/account/2fa/setup` javobi.
 *
 * `secret` va `otpauth_url` FAQAT sozlash jarayonida qaytadi; yoqilgandan
 * keyin ularni qayta ko'rsatib bo'lmaydi.
 */
export interface TwoFactorSetup {
  secret: string
  otpauth_url: string
  recovery_codes: string[]
}

// ───────────────────────────────────────────────────────────────────────────
// Jamoa
// ───────────────────────────────────────────────────────────────────────────

export type TeamRole = 'owner' | 'admin' | 'developer' | 'viewer'

export const TEAM_ROLES: readonly TeamRole[] = ['owner', 'admin', 'developer', 'viewer'] as const

/** Har bir rol nimaga ruxsat beradi. */
export const TEAM_ROLE_INFO: Readonly<Record<TeamRole, { title: string; description: string }>> = {
  owner: {
    title: 'Owner',
    description: 'Everything, including billing and deleting the account. Exactly one owner.',
  },
  admin: {
    title: 'Admin',
    description: 'Manage members, API keys and webhooks. Cannot change billing.',
  },
  developer: {
    title: 'Developer',
    description: 'Submit, cancel and retry jobs. Read logs and the dead letter queue.',
  },
  viewer: {
    title: 'Viewer',
    description: 'Read-only: jobs, logs and analytics. Cannot submit or change anything.',
  },
}

export type TeamMemberStatus = 'active' | 'invited' | 'suspended'

export interface TeamMember {
  id: Id
  email: string
  full_name: string | null
  initials: string
  role: TeamRole
  status: TeamMemberStatus
  joined_at: IsoDateTime | null
  last_active_at: IsoDateTime | null
  /** Taklif qachon kuchini yo'qotadi (faqat `invited` uchun). */
  invite_expires_at: IsoDateTime | null
}

export interface TeamInviteInput {
  email: string
  role: TeamRole
}

// ───────────────────────────────────────────────────────────────────────────
// Bildirishnoma sozlamalari
// ───────────────────────────────────────────────────────────────────────────

export type NotificationEvent =
  | 'job.failed'
  | 'job.dead_lettered'
  | 'dlq.threshold'
  | 'quota.warning'
  | 'quota.exceeded'
  | 'worker.down'
  | 'api_key.expiring'
  | 'weekly.digest'

/** Bitta hodisa uchun kanal tanlovi. */
export interface NotificationSetting {
  event: NotificationEvent
  label: string
  description: string
  email: boolean
  in_app: boolean
  webhook: boolean
  /** Shovqinli bo'lishi mumkinmi — ogohlantirish ko'rsatiladi. */
  noisy: boolean
}

// ───────────────────────────────────────────────────────────────────────────
// Job uchun standart qiymatlar
// ───────────────────────────────────────────────────────────────────────────

/**
 * Yangi job yuborishda aniq ko'rsatilmasa ishlatiladigan qiymatlar.
 *
 * Bu SDK'dagi `DurablClient(...)` argumentlariga to'g'ridan-to'g'ri
 * mos keladi — shuning uchun sozlama sahifasida tahrirlanishi mantiqiy.
 */
export interface ApiDefaults {
  runtime: Runtime
  timeout_seconds: number
  memory_mb: number
  max_retries: number
  /** Qayta urinishlar orasidagi kechikish strategiyasi. */
  retry_backoff: 'fixed' | 'linear' | 'exponential'
  priority: Priority
  /** Idempotentlik kaliti berilmasa, tanadan avtomatik hisoblansinmi. */
  auto_idempotency: boolean
}
