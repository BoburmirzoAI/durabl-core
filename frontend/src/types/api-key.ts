/** API kalit turlari. */

import type { Id, IsoDateTime } from './common'

/** Kalit huquqlari (dizaynda `Perms` ustuni). */
export type ApiKeyScope = 'jobs:read' | 'jobs:write' | 'dlq:read' | 'dlq:write' | 'admin'

export const API_KEY_SCOPES: readonly ApiKeyScope[] = [
  'jobs:read',
  'jobs:write',
  'dlq:read',
  'dlq:write',
  'admin',
] as const

export interface ApiKey {
  id: Id
  name: string
  /** Niqoblangan ko'rinish (`durabl_ab••••••••wxyz`). */
  masked_key: string
  key_prefix: string
  last_four: string
  scopes: ApiKeyScope[]
  created_at: IsoDateTime
  last_used_at: IsoDateTime | null
  expires_at: IsoDateTime | null
  revoked_at: IsoDateTime | null
  is_active: boolean
}

/** Yaratilgan kalit — XOM qiymat FAQAT shu javobda qaytadi. */
export interface ApiKeyCreated extends ApiKey {
  key: string
}

export interface ApiKeyCreateInput {
  name: string
  scopes: ApiKeyScope[]
  /** Kunlar soni; `null` — muddatsiz. */
  expires_in_days?: number | null
}

// ───────────────────────────────────────────────────────────────────────────
// Kalit tafsiloti
// ───────────────────────────────────────────────────────────────────────────

/** Har bir huquqning nima qilishi — scope muharririda ko'rsatiladi. */
export const API_KEY_SCOPE_INFO: Readonly<
  Record<ApiKeyScope, { title: string; description: string; dangerous?: boolean }>
> = {
  'jobs:read': {
    title: 'Read jobs',
    description: 'List jobs, read status, logs, results and attempts.',
  },
  'jobs:write': {
    title: 'Submit & control jobs',
    description: 'Submit new jobs, cancel running ones and trigger retries.',
  },
  'dlq:read': {
    title: 'Read dead letter queue',
    description: 'List dead-lettered jobs and read their tracebacks.',
  },
  'dlq:write': {
    title: 'Replay & purge DLQ',
    description: 'Retry or permanently delete entries in the dead letter queue.',
  },
  admin: {
    title: 'Full account access',
    description:
      'Everything above, plus billing, webhooks, team and API key management. Grant only to trusted automation.',
    dangerous: true,
  },
}

/** Bir kunlik foydalanish (grafik nuqtasi). */
export interface ApiKeyUsagePoint {
  /** `YYYY-MM-DD`. */
  date: string
  requests: number
  /** 4xx/5xx javoblar soni. */
  errors: number
}

/** Kalit eng ko'p urgan endpoint. */
export interface ApiKeyEndpointUsage {
  method: 'GET' | 'POST' | 'PUT' | 'DELETE'
  path: string
  requests: number
  /** 4xx/5xx foizi (0..100). */
  error_rate: number
  last_used_at: IsoDateTime
}

/**
 * `GET /api/v1/api-keys/{id}/usage`
 *
 * Kalit tafsiloti: "bu kalit nima qilyapti va kim ishlatyapti" savoliga
 * javob beradi — buzilgan kalitni aniqlashda eng kerakli ma'lumot.
 */
export interface ApiKeyUsage {
  key_id: Id
  requests_30d: number
  requests_today: number
  /** 4xx/5xx foizi (0..100). */
  error_rate: number
  /** 429 javoblar — limitga urilgan so'rovlar. */
  rate_limited_30d: number
  daily: ApiKeyUsagePoint[]
  top_endpoints: ApiKeyEndpointUsage[]
  /** Oxirgi ishlatilgan IP — noma'lum manzil = buzilgan kalit belgisi. */
  last_ip: string | null
  last_user_agent: string | null
  /** Kalit ishlatilgan turli IP'lar soni (30 kun). */
  distinct_ips: number
}

/** `POST /api/v1/api-keys/{id}/rotate` javobi. */
export interface ApiKeyRotation {
  key_id: Id
  /** YANGI xom kalit — FAQAT shu javobda qaytadi. */
  key: string
  masked_key: string
  rotated_at: IsoDateTime
  /**
   * Eski kalit qachongacha ishlaydi.
   *
   * Darhol bekor qilish ishlab turgan integratsiyani uzadi — shuning uchun
   * eski kalitga qisqa muddat beriladi.
   */
  old_key_valid_until: IsoDateTime
}
