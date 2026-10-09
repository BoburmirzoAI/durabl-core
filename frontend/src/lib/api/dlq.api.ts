/** DLQ endpointlari. */

import type { DlqEntry, DlqFilters, DlqRetryResult, DlqStats, Paginated } from '@/types'
import { allDlqEntries, dlqStats, dlqStore, findDlqEntry } from '@/lib/mock/dlq'
import { updateJob } from '@/lib/mock/jobs'

import { ApiError, mockResponse, notFound } from './client'
import { DEFAULT_PAGE_SIZE, filterByAny, paginate, searchIn, sortBy } from './paginate'

/** `GET /api/v1/dlq` */
export async function getDlqEntries(filters: DlqFilters = {}): Promise<Paginated<DlqEntry>> {
  return mockResponse(() => {
    let rows = allDlqEntries()
    if (filters.resolved !== undefined) rows = rows.filter((e) => e.resolved === filters.resolved)
    rows = searchIn(rows, filters.search, ['job_id', 'error_type', 'last_error', 'user_email'])
    rows = filterByAny(rows, filters.failure_reason, (e) => e.failure_reason)
    rows = sortBy(rows, filters.sort_by ?? 'failed_at', filters.sort_order ?? 'desc')
    return paginate(rows, filters.page ?? 1, filters.page_size ?? DEFAULT_PAGE_SIZE)
  })
}

/** `GET /api/v1/dlq/stats` */
export async function getDlqStats(): Promise<DlqStats> {
  return mockResponse(() => dlqStats())
}

/** `GET /api/v1/dlq/{id}` */
export async function getDlqEntry(id: string): Promise<DlqEntry> {
  return mockResponse(() => {
    const entry = findDlqEntry(id)
    if (!entry) throw notFound('Dead letter', id)
    return entry
  })
}

/** `POST /api/v1/dlq/{id}/retry` */
export async function retryDlqEntry(id: string): Promise<DlqRetryResult> {
  return mockResponse(() => {
    const entry = findDlqEntry(id)
    if (!entry) throw notFound('Dead letter', id)
    if (entry.resolved) {
      throw new ApiError({
        status: 409,
        code: 'DLQ_ALREADY_RESOLVED',
        message: 'This dead letter has already been resolved',
      })
    }
    const retriedAt = new Date().toISOString()
    // Yozuv HAL QILINGAN deb belgilanadi va asl job navbatga qaytariladi
    dlqStore.update(id, { resolved: true, resolved_at: retriedAt })
    updateJob(entry.job_id, {
      status: 'queued',
      queued_at: retriedAt,
      finished_at: null,
      is_terminal: false,
    })
    return {
      entry_id: entry.id,
      job_id: entry.job_id,
      requeued: true,
      resolved: true,
      retried_at: retriedAt,
    }
  }, 400)
}

/** `DELETE /api/v1/dlq/{id}` */
export async function deleteDlqEntry(id: string): Promise<{ deleted: boolean }> {
  return mockResponse(() => {
    if (!findDlqEntry(id)) throw notFound('Dead letter', id)
    return { deleted: dlqStore.remove(id) }
  }, 300)
}

/** Ommaviy qayta urinish (UI bulk amali). Faqat HAL QILINMAGANLARI. */
export async function retryDlqEntries(ids: string[]): Promise<{ retried: number }> {
  return mockResponse(() => ({ retried: requeue(ids) }), 500)
}

/** Ommaviy o'chirish. */
export async function deleteDlqEntries(ids: string[]): Promise<{ deleted: number }> {
  return mockResponse(() => ({ deleted: dlqStore.removeMany(ids) }), 400)
}

/** "Retry All" tugmasi — barcha hal qilinmagan yozuvlarni qayta uradi. */
export async function retryAllDlq(): Promise<{ retried: number }> {
  return mockResponse(() => {
    const open = allDlqEntries()
      .filter((e) => !e.resolved)
      .map((e) => e.id)
    return { retried: requeue(open) }
  }, 700)
}

/**
 * Yozuvlarni hal qilingan deb belgilaydi va asl job'larni navbatga qaytaradi.
 *
 * Alohida yordamchi: bitta va ommaviy qayta urinish AYNI mantiqdan
 * foydalanishi kerak, aks holda ikkisi vaqt o'tib bir-biridan ajralib ketadi.
 */
function requeue(ids: string[]): number {
  const retriedAt = new Date().toISOString()
  let count = 0
  for (const id of ids) {
    const entry = findDlqEntry(id)
    if (!entry || entry.resolved) continue
    dlqStore.update(id, { resolved: true, resolved_at: retriedAt })
    updateJob(entry.job_id, {
      status: 'queued',
      queued_at: retriedAt,
      finished_at: null,
      is_terminal: false,
    })
    count += 1
  }
  return count
}

/**
 * `POST /api/v1/admin/dlq/purge`
 *
 * FAQAT hal qilingan deb belgilangan yozuvlarni o'chiradi.
 *
 * Hal qilinmagan yozuvni admin o'chira olmasligi muhim: u mijozning
 * hali ko'rmagan nosozligi, va uni "tozalash" muammoni yashirish bilan
 * teng bo'lardi.
 */
export async function purgeResolvedDlq(): Promise<{ purged: number }> {
  return mockResponse(() => {
    const purged = dlqStore.removeWhere((entry) => entry.resolved)
    return { purged }
  }, 700)
}
