/** Foydalanuvchi va admin turlari. */

import type { Id, IsoDateTime, ListParams } from './common'
import type { PlanType } from './billing'
import type { JobStatus, Runtime } from './job'

export interface User {
  id: Id
  email: string
  full_name: string | null
  /** Bosh harflar (avatar uchun, masalan `JD`). */
  initials: string
  is_active: boolean
  is_admin: boolean
  plan: PlanType
  last_login_at: IsoDateTime | null
  created_at: IsoDateTime
}

/** Admin ro'yxatidagi foydalanuvchi (agregatlar bilan). */
export interface AdminUser extends User {
  job_count: number
  jobs_this_period: number
  dlq_depth: number
  api_key_count: number
}

export interface AdminUserFilters extends ListParams {
  search?: string
  plan?: PlanType[]
  is_active?: boolean
  is_admin?: boolean
}

/** Platforma statistikasi (admin bosh sahifasi). */
export interface AdminStats {
  total_users: number
  active_users: number
  new_users_7d: number
  total_jobs: number
  jobs_24h: number
  jobs_by_status: Record<string, number>
  users_by_plan: Partial<Record<PlanType, number>>
  success_rate: number
  avg_duration_ms: number | null
  dlq_depth: number
  active_workers: number
  mrr_usd: number
}

export type AuditAction =
  | 'user.created'
  | 'user.updated'
  | 'user.deactivated'
  | 'user.activated'
  | 'user.promoted'
  | 'job.cancelled'
  | 'job.force_retried'
  | 'dlq.purged'
  | 'api_key.revoked'
  | 'plan.changed'

/** Jonli faollik oqimining bitta yozuvi (admin). */
export interface ActivityEvent {
  id: Id
  kind: 'job' | 'user' | 'worker' | 'dlq' | 'webhook'
  message: string
  actor: string | null
  severity: 'info' | 'warn' | 'error'
  at: IsoDateTime
}

/** Autentifikatsiya javobi (mock). */
export interface AuthSession {
  access_token: string
  refresh_token: string
  token_type: 'bearer'
  expires_in: number
  user: User
}

/** Foydalanuvchi sozlamalari (settings sahifasi). */
export interface UserPreferences {
  /** Jadval qatorlari zichligi. */
  density: 'compact' | 'comfortable'
  /** Ro'yxatlar avtomatik yangilanishi. */
  auto_refresh: boolean
  /** DLQ chegarasidan oshganda bildirishnoma. */
  notify_dlq_threshold: boolean
  notify_job_failed: boolean
  /** Log ko'rinishida vaqt belgisi ko'rsatilsinmi. */
  show_log_timestamps: boolean
  /** Avatar fon rangi (`accent` | `success` | `pending` | `failed` | `neutral`). */
  avatar_color: string
}

// ───────────────────────────────────────────────────────────────────────────
// Admin: foydalanuvchi detal sahifasi
// ───────────────────────────────────────────────────────────────────────────

/** Foydalanuvchining qisqa job yozuvi (admin ko'rinishi). */
export interface AdminUserJob {
  id: Id
  status: JobStatus
  runtime: Runtime
  created_at: IsoDateTime
  duration_ms: number | null
  attempts: number
}

/** Foydalanuvchining DLQ yozuvi (admin ko'rinishi). */
export interface AdminUserDlqEntry {
  id: Id
  job_id: Id
  error_type: string
  last_error: string
  failed_at: IsoDateTime
  retry_count: number
}

/** Foydalanuvchining API kaliti (admin ko'rinishi — xom qiymat YO'Q). */
export interface AdminUserKey {
  id: Id
  name: string
  masked_key: string
  last_used_at: IsoDateTime | null
  created_at: IsoDateTime
  is_active: boolean
}

/** Foydalanuvchining webhook'i (admin ko'rinishi). */
export interface AdminUserWebhook {
  id: Id
  url: string
  is_active: boolean
  success_rate: number
  consecutive_failures: number
  last_triggered_at: IsoDateTime | null
}

/** Hisobdagi pul harakati. */
export interface AdminCreditEntry {
  id: Id
  at: IsoDateTime
  /** Musbat — kredit berildi, manfiy — hisobdan yechildi. */
  amount_usd: number
  reason: string
  /** Kim amalga oshirgan. */
  actor: string
  kind: 'credit' | 'refund' | 'charge' | 'adjustment'
}

/** Foydalanuvchi bilan bog'liq hodisa (admin audit). */
export interface AdminUserActivity {
  id: Id
  at: IsoDateTime
  action: AuditAction | string
  summary: string
  actor: string
  /** Admin qilganmi yoki foydalanuvchining o'zimi. */
  by_admin: boolean
}

/** Kunlik foydalanish nuqtasi (admin grafigi). */
export interface AdminUsagePoint {
  date: string
  jobs: number
  failed: number
}

/**
 * Admin uchun to'liq foydalanuvchi ko'rinishi.
 *
 * Alohida chaqiruv: ro'yxatda bu ma'lumotlarning hech biri kerak emas,
 * lekin detal sahifasida hammasi bir vaqtda kerak.
 */
export interface AdminUserDetail {
  user: AdminUser
  usage: AdminUsagePoint[]
  jobs: AdminUserJob[]
  dlq: AdminUserDlqEntry[]
  keys: AdminUserKey[]
  webhooks: AdminUserWebhook[]
  credits: AdminCreditEntry[]
  activity: AdminUserActivity[]
  /** Joriy davrda hisoblangan summa (USD). */
  balance_usd: number
  /** Berilgan kreditlar yig'indisi (USD). */
  credit_balance_usd: number
  /** Admin yozib qo'ygan ichki eslatma. */
  note: string | null
}

export interface AdminCreateUserInput {
  email: string
  full_name?: string
  plan: PlanType
  is_admin: boolean
  /** Hisobga darhol qo'shiladigan kredit (USD). */
  starting_credit_usd?: number
}
