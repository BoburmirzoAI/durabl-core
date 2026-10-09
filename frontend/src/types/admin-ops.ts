/** Admin operatsion sahifalari: audit, billing, e'lonlar, qo'llab-quvvatlash. */

import type { Id, IsoDateTime, ListParams } from './common'
import type { PlanType } from './billing'

// ───────────────────────────────────────────────────────────────────────────
// Audit jurnali
// ───────────────────────────────────────────────────────────────────────────

export type AuditCategory = 'user' | 'billing' | 'security' | 'config' | 'job' | 'system'

/**
 * Audit yozuvi.
 *
 * `ActivityEvent` dan farqi: faollik oqimi — JONLI lenta ("hozir nima
 * bo'layapti"), audit esa IZ ("kim nima qildi va nimani o'zgartirdi").
 * Shuning uchun bu yerda eski va yangi qiymat, IP va natija bor.
 */
export interface AuditEntry {
  id: Id
  at: IsoDateTime
  category: AuditCategory
  action: string
  /** Amalni bajargan (admin emaili yoki `system`). */
  actor: string
  /** Amal tegishli bo'lgan obyekt. */
  target: string
  target_type: 'user' | 'job' | 'plan' | 'secret' | 'worker' | 'config' | 'dlq'
  summary: string
  /** O'zgargan qiymatlar — konfiguratsiya tahriri uchun. */
  before: string | null
  after: string | null
  ip: string
  result: 'success' | 'denied' | 'error'
}

export interface AuditFilters extends ListParams {
  search?: string
  category?: AuditCategory[]
  actor?: string
  result?: AuditEntry['result'][]
}

// ───────────────────────────────────────────────────────────────────────────
// Platforma billing'i
// ───────────────────────────────────────────────────────────────────────────

/** Tarif bo'yicha daromad. */
export interface RevenueByPlan {
  plan: PlanType
  accounts: number
  mrr_usd: number
  /** O'tgan oyga nisbatan o'zgarish (%). */
  change_percent: number
  /** Shu tarifdagi hisoblarning o'rtacha oylik to'lovi. */
  arpa_usd: number
}

export interface RevenuePoint {
  month: string
  mrr_usd: number
  new_usd: number
  churned_usd: number
}

/** To'lovi kechikkan hisob. */
export interface OverdueAccount {
  user_id: Id
  email: string
  plan: PlanType
  amount_usd: number
  days_overdue: number
  last_attempt_at: IsoDateTime
  /** Oxirgi urinish nega muvaffaqiyatsiz bo'lgan. */
  failure_reason: string
}

export interface PlatformBilling {
  mrr_usd: number
  /** O'tgan oyga nisbatan MRR o'zgarishi (%). */
  mrr_change_percent: number
  arr_usd: number
  /** Oylik tark etish foizi. */
  churn_percent: number
  /** To'lanmagan umumiy summa. */
  outstanding_usd: number
  paying_accounts: number
  trial_accounts: number
  by_plan: RevenueByPlan[]
  history: RevenuePoint[]
  overdue: OverdueAccount[]
}

// ───────────────────────────────────────────────────────────────────────────
// E'lonlar
// ───────────────────────────────────────────────────────────────────────────

export type AnnouncementLevel = 'info' | 'warning' | 'critical'
export type AnnouncementStatus = 'draft' | 'scheduled' | 'live' | 'ended'

/**
 * Platforma e'loni.
 *
 * Mijozlarga ko'rinadigan bannerlar: rejalashtirilgan ta'mirlash, hodisa
 * haqida xabar, yangi imkoniyat. Jo'natish o'rniga BANNER, chunki
 * hodisa paytida email yetib bormasligi mumkin.
 */
export interface Announcement {
  id: Id
  title: string
  body: string
  level: AnnouncementLevel
  status: AnnouncementStatus
  /** Kimga ko'rinadi; bo'sh — hammaga. */
  audience: PlanType[]
  starts_at: IsoDateTime
  ends_at: IsoDateTime | null
  /** Mijoz bannerni yopa oladimi. */
  dismissible: boolean
  created_by: string
  created_at: IsoDateTime
  /** Nechta hisob ko'rgan. */
  seen_by: number
}

export interface AnnouncementInput {
  title: string
  body: string
  level: AnnouncementLevel
  audience: PlanType[]
  dismissible: boolean
  starts_at: IsoDateTime
  ends_at: IsoDateTime | null
}

// ───────────────────────────────────────────────────────────────────────────
// Qo'llab-quvvatlash
// ───────────────────────────────────────────────────────────────────────────

export type TicketStatus = 'open' | 'pending' | 'resolved' | 'closed'
export type TicketPriority = 'low' | 'normal' | 'high' | 'urgent'

export interface SupportMessage {
  id: Id
  at: IsoDateTime
  author: string
  /** Mijozmi yoki qo'llab-quvvatlash jamoasi. */
  from_staff: boolean
  body: string
}

export interface SupportTicket {
  id: Id
  subject: string
  user_id: Id
  user_email: string
  plan: PlanType
  status: TicketStatus
  priority: TicketPriority
  /** Mijoz birinchi javobni qancha kutgan (daqiqa); `null` — hali javob yo'q. */
  first_response_minutes: number | null
  created_at: IsoDateTime
  updated_at: IsoDateTime
  /** Biriktirilgan xodim. */
  assignee: string | null
  /** Bog'liq job — ko'pincha shikoyat aniq job haqida bo'ladi. */
  related_job_id: Id | null
  messages: SupportMessage[]
}

export interface TicketFilters extends ListParams {
  search?: string
  status?: TicketStatus[]
  priority?: TicketPriority[]
}

// ───────────────────────────────────────────────────────────────────────────
// Platforma bo'yicha agregatlar
// ───────────────────────────────────────────────────────────────────────────

/** Worker bo'yicha bajarish sifati. */
export interface WorkerExecutionHealth {
  worker_id: string
  region: string
  state: string
  executions: number
  succeeded: number
  failed: number
  /** Lease yo'qolgani uchun yo'qolgan urinishlar — eng muhim ko'rsatkich. */
  lost: number
  timeout: number
  avg_duration_ms: number
  /** Eng ko'p uchragan exit kodlari. */
  top_exit_codes: { code: number; count: number }[]
}

export interface PlatformExecutions {
  total: number
  lost: number
  timeout: number
  /** Yo'qolgan urinishlar ulushi (%). */
  lost_rate: number
  by_worker: WorkerExecutionHealth[]
}

/** Foydalanuvchi bo'yicha DLQ holati. */
export interface DlqByUser {
  user_id: Id
  email: string
  plan: PlanType
  depth: number
  /** Eng ko'p uchragan xato turi. */
  top_error: string
  oldest_at: IsoDateTime
  /** Oxirgi 24 soatda qo'shilganlar. */
  added_24h: number
}

export interface PlatformDlq {
  depth: number
  added_24h: number
  resolved_24h: number
  /** Eng eski hal qilinmagan yozuv. */
  oldest_at: IsoDateTime | null
  by_user: DlqByUser[]
  by_error: { error_type: string; count: number; percent: number }[]
}

/** Foydalanuvchi webhook'i (platforma ko'rinishi). */
export interface PlatformWebhookRow {
  id: Id
  user_id: Id
  email: string
  plan: PlanType
  url: string
  is_active: boolean
  success_rate: number
  consecutive_failures: number
  deliveries_24h: number
  failed_24h: number
  last_triggered_at: IsoDateTime | null
}

export interface PlatformWebhooks {
  endpoints: number
  failing: number
  deliveries_24h: number
  /** 24 soatdagi muvaffaqiyat foizi. */
  success_rate_24h: number
  rows: PlatformWebhookRow[]
}

/** Tarif bo'yicha ish hajmi (platforma analitikasi). */
export interface PlanWorkload {
  plan: PlanType
  accounts: number
  jobs_24h: number
  success_rate: number
  p95_ms: number
  dlq_depth: number
  /** Platformadagi ish hajmidan ulushi (%). */
  share: number
}
