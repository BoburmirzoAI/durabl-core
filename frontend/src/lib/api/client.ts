/**
 * HTTP klient va mock qatlamining almashinish nuqtasi.
 *
 * ═══════════════════════════════════════════════════════════════════
 * BACKEND ULANGANDA NIMA O'ZGARADI
 * ═══════════════════════════════════════════════════════════════════
 *
 * HOZIR: `*.api.ts` fayllari `mockResponse(...)` ni chaqiradi — ma'lumot
 * `lib/mock/*` dan keladi, sun'iy tarmoq kechikishi bilan.
 *
 * KEYIN: ayni fayllardagi `mockResponse(...)` o'rniga `request(...)`
 * yoziladi. Funksiya IMZOSI va QAYTARADIGAN TURI o'zgarmaydi, shuning
 * uchun `lib/hooks/*` va barcha komponentlar TEGILMAYDI.
 *
 * Misol:
 *   // hozir
 *   export const getJobs = (f: JobFilters) => mockResponse(() => mockJobs(f))
 *   // keyin
 *   export const getJobs = (f: JobFilters) => request<Paginated<JobSummary>>('/jobs', { params: f })
 */

import type { ApiErrorBody } from '@/types'

/** Backend manzili (`.env.local`). */
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

/** API prefiksi — backend `settings.API_V1_PREFIX`. */
export const API_PREFIX = '/api/v1'

/** Mock qatlamining sun'iy kechikishi (ms). */
const MOCK_LATENCY = Number(process.env.NEXT_PUBLIC_MOCK_LATENCY_MS ?? 200)

/**
 * Backend xatosini tashuvchi klass.
 *
 * Mock rejimida ham ayni klass tashlanadi (masalan "job topilmadi"),
 * shuning uchun `ErrorState` komponenti ikki rejimda ham bir xil ishlaydi.
 */
export class ApiError extends Error {
  readonly status: number
  readonly code: string
  readonly details?: Record<string, unknown>
  readonly requestId?: string

  constructor(params: {
    status: number
    code: string
    message: string
    details?: Record<string, unknown>
    requestId?: string
  }) {
    super(params.message)
    this.name = 'ApiError'
    this.status = params.status
    this.code = params.code
    this.details = params.details
    this.requestId = params.requestId
  }

  /** 4xx — mijoz xatosi, qayta urinish foydasiz. */
  get isClientError(): boolean {
    return this.status >= 400 && this.status < 500
  }

  get isNotFound(): boolean {
    return this.status === 404
  }

  get isUnauthorized(): boolean {
    return this.status === 401 || this.status === 403
  }
}

/** Mock rejimida "topilmadi" xatosini tashlash uchun qisqa yo'l. */
export function notFound(resource: string, id: string): ApiError {
  return new ApiError({
    status: 404,
    code: 'NOT_FOUND',
    message: `${resource} not found: ${id}`,
    details: { resource, id },
  })
}

/**
 * Mock javobini sun'iy kechikish bilan qaytaradi.
 *
 * Kechikish bo'lmasa UI yuklanish holatlarini hech qachon ko'rsatmaydi va
 * skeleton'lar sinalmay qoladi — shuning uchun ataylab ~200ms qo'yilgan.
 */
export async function mockResponse<T>(produce: () => T, latencyMs = MOCK_LATENCY): Promise<T> {
  // Generatsiya kechikishdan OLDIN bajariladi, shunda xato darhol chiqadi
  const value = produce()
  if (latencyMs > 0) {
    await new Promise((resolve) => setTimeout(resolve, latencyMs))
  }
  return value
}

/** Query parametrlarini qurish (massivlar takrorlanuvchi kalit sifatida). */
export function buildQuery(params: Record<string, unknown> | undefined): string {
  if (!params) return ''
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue
    if (Array.isArray(value)) {
      for (const item of value) search.append(key, String(item))
    } else {
      search.set(key, String(value))
    }
  }
  const qs = search.toString()
  return qs ? `?${qs}` : ''
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  params?: Record<string, unknown>
  body?: unknown
  /** Idempotency-Key header (faqat `POST /jobs` uchun). */
  idempotencyKey?: string
  signal?: AbortSignal
}

/**
 * HAQIQIY HTTP so'rov — hozircha ishlatilmaydi, backend ulanganda
 * `*.api.ts` fayllari shu funksiyaga o'tadi.
 *
 * Token `lib/auth.ts` dan olinadi (mock autentifikatsiya ham shu yerda
 * token saqlaydi, shuning uchun almashtirishda o'zgarmaydi).
 */
export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', params, body, idempotencyKey, signal } = options
  const { getAccessToken } = await import('@/lib/auth')

  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const token = getAccessToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (idempotencyKey) headers['Idempotency-Key'] = idempotencyKey

  const response = await fetch(`${API_BASE_URL}${API_PREFIX}${path}${buildQuery(params)}`, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
    signal,
  })

  if (response.status === 204) return undefined as T

  const text = await response.text()
  const parsed: unknown = text ? JSON.parse(text) : null

  if (!response.ok) {
    const errorBody = parsed as ApiErrorBody | null
    throw new ApiError({
      status: response.status,
      code: errorBody?.error?.code ?? 'UNKNOWN_ERROR',
      message: errorBody?.error?.message ?? `The request failed with status ${response.status}`,
      details: errorBody?.error?.details,
      requestId: errorBody?.request_id,
    })
  }

  return parsed as T
}
