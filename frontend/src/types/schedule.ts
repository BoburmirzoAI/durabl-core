/** Rejalashtirilgan (takroriy) job'lar va shablonlar. */

import type { Id, IsoDateTime, ListParams } from './common'
import type { JobStatus, Priority, Runtime } from './job'

// ───────────────────────────────────────────────────────────────────────────
// Jadval (cron)
// ───────────────────────────────────────────────────────────────────────────

export type ScheduleStatus = 'active' | 'paused' | 'errored'

/** Takroriy job. */
export interface Schedule {
  id: Id
  name: string
  description: string | null
  /** 5 maydonli cron ifodasi, masalan har 15 daqiqada. */
  cron: string
  /** IANA zona nomi — cron shu zonada hisoblanadi. */
  timezone: string
  runtime: Runtime
  priority: Priority
  status: ScheduleStatus
  /** Bir ishga tushish tugamasdan keyingisi boshlanishi mumkinmi. */
  allow_overlap: boolean
  timeout_seconds: number
  max_retries: number
  created_at: IsoDateTime
  updated_at: IsoDateTime
  last_run_at: IsoDateTime | null
  last_run_status: JobStatus | null
  next_run_at: IsoDateTime | null
  /** Ketma-ket muvaffaqiyatsizliklar — 3 tadan keyin jadval to'xtaydi. */
  consecutive_failures: number
  total_runs: number
  failed_runs: number
}

/** Jadval bo'yicha bitta ishga tushish. */
export interface ScheduleRun {
  id: Id
  schedule_id: Id
  job_id: Id | null
  /** Rejalashtirilgan vaqt. */
  scheduled_for: IsoDateTime
  /** Haqiqatda boshlangan vaqt (`null` — o'tkazib yuborilgan). */
  started_at: IsoDateTime | null
  status: JobStatus | 'skipped'
  duration_ms: number | null
  /** O'tkazib yuborilgan bo'lsa — sababi. */
  skip_reason: string | null
}

export interface ScheduleCreateInput {
  name: string
  description?: string
  cron: string
  timezone: string
  code: string
  runtime: Runtime
  priority: Priority
  allow_overlap: boolean
  timeout_seconds: number
  max_retries: number
}

export interface ScheduleFilters extends ListParams {
  search?: string
  status?: ScheduleStatus[]
}

/** Cron ifodasini tahlil natijasi. */
export interface CronParseResult {
  valid: boolean
  /** Odam o'qiydigan tavsif (`Every 15 minutes`). */
  description: string
  error: string | null
  /** Keyingi ishga tushish vaqtlari. */
  next_runs: IsoDateTime[]
  /** Sutkada necha marta ishga tushadi. */
  runs_per_day: number
}

// ───────────────────────────────────────────────────────────────────────────
// Shablonlar
// ───────────────────────────────────────────────────────────────────────────

/**
 * Job shabloni.
 *
 * Bir xil kodni qayta-qayta nusxalash o'rniga saqlab qo'yiladi; "New job"
 * sahifasi shablondan boshlashi mumkin.
 */
export interface JobTemplate {
  id: Id
  name: string
  description: string
  /** Guruhlash uchun yorliq (`etl`, `report`, `maintenance`). */
  category: string
  runtime: Runtime
  code: string
  /** Namuna payload (JSON matn). */
  payload: string
  timeout_seconds: number
  memory_mb: number
  max_retries: number
  priority: Priority
  /** Durabl tomonidan tayyorlangan shablon — tahrirlanmaydi, nusxalanadi. */
  is_builtin: boolean
  use_count: number
  created_at: IsoDateTime
  last_used_at: IsoDateTime | null
}

export interface TemplateCreateInput {
  name: string
  description: string
  category: string
  runtime: Runtime
  code: string
  payload: string
  timeout_seconds: number
  memory_mb: number
  max_retries: number
  priority: Priority
}
