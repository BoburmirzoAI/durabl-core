/**
 * Umumiy turlar — sahifalash, API javob konverti, filtr asoslari.
 *
 * MUHIM: maydon nomlari `snake_case` — backend (FastAPI + Pydantic) aynan
 * shunday qaytaradi. Mock qatlami ham shu shaklni beradi, shuning uchun
 * `lib/api/*.api.ts` ichidagi mock chaqiruvi real `fetch` ga almashtirilganda
 * komponentlarga TEGISH KERAK EMAS.
 */

/** ISO-8601 UTC vaqt matni (`"2026-10-04T12:00:00Z"`). */
export type IsoDateTime = string

/** UUID yoki `job_xxx` ko'rinishidagi identifikator. */
export type Id = string

/** Sahifalash meta-ma'lumoti (backend `PaginationMeta`). */
export interface PaginationMeta {
  page: number
  page_size: number
  total: number
  total_pages: number
  has_next: boolean
  has_prev: boolean
}

/** Sahifalangan ro'yxat javobi (backend `PaginatedResponse[T]`). */
export interface Paginated<T> {
  items: T[]
  pagination: PaginationMeta
}

/** Xato javobi tanasi (backend `ErrorResponse`). */
export interface ApiErrorBody {
  error: {
    code: string
    message: string
    details?: Record<string, unknown>
  }
  request_id?: string
}

/** Oddiy "bajarildi" javobi (backend `SuccessResponse`). */
export interface SuccessResponse {
  success: boolean
  message: string
  data?: Record<string, unknown>
}

/** Ro'yxat so'rovining umumiy parametrlari. */
export interface ListParams {
  page?: number
  page_size?: number
  sort_by?: string
  sort_order?: SortOrder
}

export type SortOrder = 'asc' | 'desc'

/** Vaqt oralig'i tanlagichi (dizayndagi 24h/7d/30d tablari). */
export type TimeRange = '1h' | '24h' | '7d' | '30d'

export const TIME_RANGES: readonly TimeRange[] = ['1h', '24h', '7d', '30d'] as const

/** Grafik qadamlash oraligi. */
export type Interval = 'minute' | 'hour' | 'day'

/** Jadval ustuni bo'yicha tartiblash holati. */
export interface SortState {
  field: string
  order: SortOrder
}

/** Vaqt qatorining bitta nuqtasi. */
export interface TimeSeriesPoint {
  timestamp: IsoDateTime
  value: number
}
