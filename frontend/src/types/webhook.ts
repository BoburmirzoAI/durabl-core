/** Webhook turlari. */

import type { Id, IsoDateTime, ListParams } from './common'

/** Mijoz obuna bo'lishi mumkin bo'lgan hodisalar. */
export type WebhookEventName =
  | 'job.queued'
  | 'job.started'
  | 'job.succeeded'
  | 'job.failed'
  | 'job.cancelled'
  | 'job.dead_lettered'

export const WEBHOOK_EVENTS: readonly WebhookEventName[] = [
  'job.queued',
  'job.started',
  'job.succeeded',
  'job.failed',
  'job.cancelled',
  'job.dead_lettered',
] as const

/** Webhook sozlamasi (dizayndagi karta). */
export interface Webhook {
  id: Id
  user_id: Id
  url: string
  /** Faqat yaratilganda qaytadi. */
  secret?: string
  events: WebhookEventName[]
  is_active: boolean
  description: string | null
  last_triggered_at: IsoDateTime | null
  /** Muvaffaqiyat foizi (0..100) — kartada ko'rsatiladi. */
  success_rate: number
  consecutive_failures: number
  created_at: IsoDateTime
}

export type DeliveryStatus = 'pending' | 'success' | 'failed' | 'retrying' | 'exhausted'

/** Yuborish urinishi (dizayndagi delivery jadvali). */
export interface WebhookDelivery {
  id: Id
  webhook_id: Id
  /** Qaysi webhook URL'iga ketgani — jadvalda ko'rsatiladi. */
  webhook_url: string
  job_id: Id | null
  event: WebhookEventName
  status: DeliveryStatus
  attempt: number
  response_code: number | null
  /** So'rov tanasi (ochilganda ko'rinadi). */
  request_body: string
  /** Javob tanasi (ochilganda ko'rinadi). */
  response_body: string
  error_message: string | null
  duration_ms: number | null
  delivered_at: IsoDateTime | null
  created_at: IsoDateTime

  // --- Tafsilot ko'rinishi uchun -------------------------------------------
  /** Biz YUBORGAN sarlavhalar (imzo shu yerda). */
  request_headers: Record<string, string>
  /** Mijoz endpointi QAYTARGAN sarlavhalar. */
  response_headers: Record<string, string>
  /**
   * HMAC-SHA256 imzosi: `t=<unix>,v1=<hex>`.
   *
   * Mijoz uni `secret` bilan qayta hisoblab tekshiradi — shuning uchun
   * tafsilot oynasida u to'liq ko'rsatiladi.
   */
  signature: string
  /**
   * Imzo tekshiruvi natijasi.
   *
   * Mock rejimida har doim `true`; backend ulanganda bu maydon mijoz
   * endpointi imzoni qabul qilgan-qilmaganini aks ettiradi.
   */
  signature_valid: boolean
}

export interface WebhookCreateInput {
  url: string
  events: WebhookEventName[]
  description?: string
}

export interface DeliveryFilters extends ListParams {
  webhook_id?: Id
  status?: DeliveryStatus[]
}

/** Test yuborish natijasi. */
export interface WebhookTestResult {
  success: boolean
  status_code: number | null
  response_body: string | null
  duration_ms: number
  error: string | null
  signature: string
}

/** `POST /webhooks/{id}/rotate-secret` javobi. */
export interface WebhookSecretRotation {
  webhook_id: Id
  /** YANGI secret — FAQAT shu javobda qaytadi, boshqa hech qayerda. */
  secret: string
  rotated_at: IsoDateTime
  /**
   * Eski secret qachongacha ishlaydi.
   *
   * Rotatsiya darhol bo'lsa, mijozning ishlab turgan integratsiyasi
   * uziladi — shuning uchun eski kalit qisqa vaqt amal qiladi.
   */
  old_secret_valid_until: IsoDateTime
}
