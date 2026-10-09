/** O'lik xatlar navbati (DLQ) turlari — Durabl'ning ajralib turuvchi funksiyasi. */

import type { Id, IsoDateTime, ListParams } from './common'
import type { FailureReason, Runtime } from './job'

/** DLQ yozuvi — barcha qayta urinishlar tugagach job shu yerga tushadi. */
export interface DlqEntry {
  id: Id
  job_id: Id
  user_id: Id
  user_email: string
  runtime: Runtime
  failure_reason: FailureReason
  /** Xato klassi nomi (`TimeoutError`) — dizaynda ustun sifatida ko'rsatilgan. */
  error_type: string
  /** Qisqa xato xabari. */
  last_error: string
  /** To'liq izma-iz (ochilganda ko'rinadi). */
  traceback: string
  failed_at: IsoDateTime
  retry_count: number
  manual_retry_count: number
  resolved: boolean
  resolved_at: IsoDateTime | null
  notes: string | null
}

/** DLQ statistikasi (dizayndagi uch karta). */
export interface DlqStats {
  /** Hal qilinmagan yozuvlar — alert uchun asosiy ko'rsatkich. */
  depth: number
  total: number
  resolved: number
  unresolved: number
  added_last_24h: number
  /** Eng ko'p uchraydigan xato (dizaynda `TimeoutError ×11`). */
  top_error: { type: string; count: number } | null
  by_reason: Partial<Record<FailureReason, number>>
  oldest_failed_at: IsoDateTime | null
}

/** Guruhlash rejimi (dizayndagi tablar). */
export type DlqGroupBy = 'all' | 'error' | 'user' | 'runtime'

export const DLQ_GROUP_BY: readonly DlqGroupBy[] = ['all', 'error', 'user', 'runtime'] as const

export interface DlqFilters extends ListParams {
  search?: string
  group_by?: DlqGroupBy
  resolved?: boolean
  failure_reason?: FailureReason[]
}

/** Qayta urinish natijasi. */
export interface DlqRetryResult {
  entry_id: Id
  job_id: Id
  requeued: boolean
  resolved: boolean
  retried_at: IsoDateTime
}
