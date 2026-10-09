/** Job va bajarish (execution) turlari. */

import type { Id, IsoDateTime, ListParams, SortOrder } from './common'

/**
 * Job hayot sikli holatlari — backend `JobStatus` enumiga AYNAN mos.
 *
 * Dizaynda beshtasi ko'rsatilgan (success/running/failed/pending/queued),
 * qolgan uchtasi backend'da bor va UI ularni ham to'g'ri ko'rsatishi kerak.
 */
export type JobStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'success'
  | 'failed'
  | 'retrying'
  | 'cancelled'
  | 'dead_letter'

export const JOB_STATUSES: readonly JobStatus[] = [
  'pending',
  'queued',
  'running',
  'success',
  'failed',
  'retrying',
  'cancelled',
  'dead_letter',
] as const

/** Yakuniy holatlar — bundan keyin job avtomatik o'zgarmaydi. */
export const TERMINAL_STATUSES: readonly JobStatus[] = [
  'success',
  'cancelled',
  'dead_letter',
] as const

export type Runtime = 'python' | 'node'
export const RUNTIMES: readonly Runtime[] = ['python', 'node'] as const

export type Priority = 'high' | 'normal' | 'low'
export const PRIORITIES: readonly Priority[] = ['high', 'normal', 'low'] as const

/** Log qatorining oqimi. */
export type LogStream = 'stdout' | 'stderr' | 'system'

/** Xato sababi — DLQ va urinishlarni tasniflash uchun. */
export type FailureReason =
  | 'non_zero_exit'
  | 'timeout'
  | 'out_of_memory'
  | 'sandbox_error'
  | 'validation_error'
  | 'lease_lost'
  | 'max_retries_exceeded'
  | 'internal_error'
  | 'output_too_large'

export const FAILURE_REASONS: readonly FailureReason[] = [
  'non_zero_exit',
  'timeout',
  'out_of_memory',
  'sandbox_error',
  'validation_error',
  'lease_lost',
  'max_retries_exceeded',
  'internal_error',
  'output_too_large',
] as const

/** Ro'yxat uchun yengil job ko'rinishi (`code` YO'Q). */
export interface JobSummary {
  id: Id
  user_id: Id
  idempotency_key: string | null
  runtime: Runtime
  priority: Priority
  status: JobStatus
  attempts_used: number
  max_retries: number
  retry_count: number
  duration_ms: number | null
  exit_code: number | null
  failure_reason: FailureReason | null
  created_at: IsoDateTime
  queued_at: IsoDateTime | null
  started_at: IsoDateTime | null
  finished_at: IsoDateTime | null
  tags: string[] | null
  worker_id: string | null
  is_terminal: boolean
}

/** To'liq job (detal sahifasi uchun — kod, natija, chiqish bilan). */
export interface Job extends JobSummary {
  code: string
  payload: Record<string, unknown> | null
  env_vars: Record<string, string> | null
  timeout_seconds: number
  memory_mb: number | null
  cpus: number | null
  scheduled_at: IsoDateTime | null
  cron_expression: string | null
  cancelled_at: IsoDateTime | null
  result: { value: unknown } | null
  stdout: string | null
  stderr: string | null
  error: string | null
  correlation_id: string
}

/** Bitta bajarish urinishi. */
export interface Execution {
  id: Id
  job_id: Id
  attempt_number: number
  worker_id: string | null
  status: ExecutionStatus
  started_at: IsoDateTime | null
  finished_at: IsoDateTime | null
  duration_ms: number | null
  exit_code: number | null
  error_message: string | null
  failure_reason: FailureReason | null
  stdout_bytes: number
  stderr_bytes: number
  lease_expires_at: IsoDateTime | null
}

export type ExecutionStatus =
  | 'pending'
  | 'running'
  | 'success'
  | 'failed'
  | 'timeout'
  | 'cancelled'
  | 'lost'

/** Bitta log qatori. */
export interface JobLog {
  id: Id
  execution_id: Id
  job_id: Id
  stream: LogStream
  content: string
  sequence: number
  timestamp: IsoDateTime
}

/** Job natijasi (polling uchun). */
export interface JobResult {
  id: Id
  status: JobStatus
  exit_code: number | null
  stdout: string | null
  stderr: string | null
  result: unknown
  duration_ms: number | null
  error: string | null
  failure_reason: FailureReason | null
}

/** Hayot sikli qadami (dizayndagi stepper). */
export interface JobTimelineStep {
  key: 'submitted' | 'queued' | 'running' | 'finished' | 'dlq'
  label: string
  timestamp: IsoDateTime | null
  /** Oldingi qadamdan o'tgan vaqt (ms) — `+1.2s` ko'rinishida chiqadi. */
  gap_ms: number | null
  state: 'done' | 'current' | 'pending' | 'error'
}

/** Job hayot sikli (detal sahifasi). */
export interface JobTimeline {
  job_id: Id
  steps: JobTimelineStep[]
  queue_wait_ms: number | null
  execution_ms: number | null
  total_ms: number | null
}

/** Job ro'yxati filtrlari (dizayndagi filtr paneli). */
export interface JobFilters extends ListParams {
  search?: string
  status?: JobStatus[]
  runtime?: Runtime[]
  priority?: Priority[]
  /** Nisbiy oraliq (`24h`) yoki `all`. */
  range?: string
}

/** Yangi job yuborish so'rovi. */
export interface JobCreateInput {
  code: string
  runtime: Runtime
  priority?: Priority
  payload?: Record<string, unknown> | null
  timeout_seconds?: number
  max_retries?: number
  tags?: string[]
  idempotency_key?: string | null
}

export type { SortOrder }

// ---------------------------------------------------------------------------
// Ishonchlilik ko'rinishi (UI uchun) — bizning differensiatsiyamizni
// ko'rinadigan qiladi: lease/heartbeat va idempotency.
// ---------------------------------------------------------------------------

/** Lease hodisasi turi. */
export type LeaseEventKind =
  | 'acquired'
  | 'renewed'
  | 'expired'
  | 'released'
  | 'reaped'
  | 'lost'

/**
 * Bitta lease hodisasi.
 *
 * Backend buni `executions` + structlog chiqishidan yig'adi; UI uchun esa
 * yagona vaqt o'qi kerak — "worker job'ni qachon egalladi, necha marta
 * yangiladi, qachon yo'qotdi".
 */
export interface LeaseEvent {
  id: Id
  execution_id: Id
  attempt_number: number
  kind: LeaseEventKind
  worker_id: string
  at: IsoDateTime
  /** Shu paytdagi lease muddati. */
  expires_at: IsoDateTime | null
  /** Oldingi hodisadan o'tgan vaqt (ms) — jadvalda ko'rsatiladi. */
  since_previous_ms: number | null
  /** Odam o'qiydigan izoh. */
  note: string | null
}

/** Job uchun to'liq lease tarixi va xulosasi. */
export interface JobLeaseHistory {
  job_id: Id
  events: LeaseEvent[]
  /** Lease TTL (soniya) — sozlamadan. */
  ttl_seconds: number
  /** Heartbeat davri (soniya). */
  heartbeat_interval_seconds: number
  /** Jami yangilanishlar soni. */
  total_renewals: number
  /** Lease yo'qolgan va job boshqa worker'ga o'tgan holatlar soni. */
  reassignments: number
}

/**
 * Idempotency ma'lumoti.
 *
 * Mijoz "men bu so'rovni ikki marta yubordimmi?" degan savolga javob
 * topishi uchun: kalit, barmoq izi va shu kalit bilan kelgan so'rovlar.
 */
export interface IdempotencyRequest {
  at: IsoDateTime
  /** Javob kodi: 201 — yangi job, 200 — takroriy, 409 — ziddiyat. */
  status_code: number
  outcome: 'created' | 'deduplicated' | 'conflict'
  /** So'rov manbasi (SDK, curl, dashboard). */
  source: string
  request_id: string
}

export interface JobIdempotency {
  job_id: Id
  /** Kalit berilmagan bo'lsa `null` — har so'rov yangi job yaratadi. */
  key: string | null
  /** So'rov tanasining SHA-256 izi (qisqartirilgan). */
  fingerprint: string | null
  /** Shu job takroriy so'rov natijasida qaytarilganmi. */
  was_deduplicated: boolean
  /** Redis'dagi yozuv muddati tugaydigan vaqt. */
  expires_at: IsoDateTime | null
  /** Shu kalit bilan kelgan barcha so'rovlar. */
  requests: IdempotencyRequest[]
}
