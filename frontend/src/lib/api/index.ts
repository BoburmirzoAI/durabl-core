/**
 * API qatlamining yagona kirish nuqtasi.
 *
 * ═══════════════════════════════════════════════════════════════════
 * BACKEND SHU YERGA ULANADI
 * ═══════════════════════════════════════════════════════════════════
 *
 * Har bir `*.api.ts` fayli hozir `lib/mock/*` dan ma'lumot oladi.
 * Backend tayyor bo'lganda faqat o'sha fayllar ichidagi
 * `mockResponse(() => ...)` chaqiruvlari `request<T>('/yo\'l', ...)` ga
 * almashtiriladi. Funksiya nomlari, parametrlari va qaytaradigan turlari
 * O'ZGARMAYDI, shuning uchun:
 *
 *   - `lib/hooks/*` ga TEGILMAYDI
 *   - barcha komponentlarga TEGILMAYDI
 *
 * Mos keladigan backend yo'llari har bir funksiya ustidagi izohda.
 */

export * from './client'
export * from './paginate'

export * as jobsApi from './jobs.api'
export * as executionsApi from './executions.api'
export * as dlqApi from './dlq.api'
export * as analyticsApi from './analytics.api'
export * as webhooksApi from './webhooks.api'
export * as apiKeysApi from './api-keys.api'
export * as billingApi from './billing.api'
export * as workersApi from './workers.api'
export * as adminApi from './admin.api'
export * as notificationsApi from './notifications.api'
export * as accountApi from './account.api'
export * as schedulesApi from './schedules.api'
export * as platformApi from './platform.api'
export * as adminOpsApi from './admin-ops.api'
