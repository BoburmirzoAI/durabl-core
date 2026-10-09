/** Webhook endpointlari. */

import type {
  DeliveryFilters,
  Paginated,
  Webhook,
  WebhookCreateInput,
  WebhookDelivery,
  WebhookSecretRotation,
  WebhookTestResult,
} from '@/types'
import { allDeliveries, allWebhooks, deliveryStore, findWebhook, webhookStore } from '@/lib/mock/webhooks'
import { Rng } from '@/lib/mock/seed'

import { mockResponse, notFound } from './client'
import { DEFAULT_PAGE_SIZE, filterByAny, paginate, sortBy } from './paginate'

/** `GET /api/v1/webhooks` */
export async function getWebhooks(): Promise<Webhook[]> {
  return mockResponse(() => allWebhooks())
}

/** `GET /api/v1/webhooks/{id}` */
export async function getWebhook(id: string): Promise<Webhook> {
  return mockResponse(() => {
    const hook = findWebhook(id)
    if (!hook) throw notFound('Webhook', id)
    return hook
  })
}

/** `POST /api/v1/webhooks` — `secret` FAQAT shu javobda qaytadi. */
export async function createWebhook(input: WebhookCreateInput): Promise<Webhook> {
  return mockResponse(() => {
    const rng = new Rng(Date.now() % 100_000)
    const hook: Webhook = {
      id: `whk_${rng.hex(10)}`,
      user_id: 'usr_current',
      url: input.url,
      secret: `whsec_${rng.hex(43)}`,
      events: input.events,
      is_active: true,
      description: input.description ?? null,
      last_triggered_at: null,
      success_rate: 100,
      consecutive_failures: 0,
      created_at: new Date().toISOString(),
    }
    webhookStore.insert(hook)
    return hook
  }, 450)
}

/** `PUT /api/v1/webhooks/{id}` */
export async function updateWebhook(id: string, patch: Partial<WebhookCreateInput> & { is_active?: boolean }): Promise<Webhook> {
  return mockResponse(() => {
    const hook = findWebhook(id)
    if (!hook) throw notFound('Webhook', id)
    // `secret` hech qachon qayta qaytarilmaydi — faqat yaratilishda ko'rinadi
    const next = webhookStore.update(id, { ...patch, secret: undefined })
    return next ?? hook
  }, 300)
}

/** `DELETE /api/v1/webhooks/{id}` */
export async function deleteWebhook(id: string): Promise<{ deleted: boolean }> {
  return mockResponse(() => {
    if (!findWebhook(id)) throw notFound('Webhook', id)
    // Webhook o'chsa, uning yetkazishlari ham ro'yxatda qolmasligi kerak
    deliveryStore.removeWhere((d) => d.webhook_id === id)
    return { deleted: webhookStore.remove(id) }
  }, 300)
}

/** `POST /api/v1/webhooks/{id}/test` — darhol sinov so'rovi yuboradi. */
export async function testWebhook(id: string): Promise<WebhookTestResult> {
  return mockResponse(() => {
    const hook = findWebhook(id)
    if (!hook) throw notFound('Webhook', id)
    const rng = new Rng(Date.now() % 50_000)
    // Nosoz webhook sinovda ham yiqiladi — UI ikki holatni ham ko'rsatadi
    const ok = hook.consecutive_failures === 0 || rng.bool(0.4)
    const now = new Date().toISOString()
    const durationMs = rng.int(48, 840)
    const testSignature = `t=${Math.floor(Date.now() / 1000)},v1=${rng.hex(64)}`

    // Sinov natijasi "Recent Deliveries" ro'yxatida DARHOL ko'rinadi
    deliveryStore.insert({
      id: `whd_${rng.hex(10)}`,
      webhook_id: id,
      webhook_url: hook.url,
      job_id: null,
      event: 'job.succeeded',
      status: ok ? 'success' : 'failed',
      response_code: ok ? 200 : 502,
      attempt: 1,
      request_body: '{"event":"webhook.test","data":{"test":true}}',
      response_body: ok ? '{"received":true}' : '{"error":"Bad Gateway"}',
      error_message: ok ? null : 'Upstream returned 502',
      duration_ms: durationMs,
      delivered_at: ok ? now : null,
      created_at: now,
      signature: testSignature,
      signature_valid: true,
      request_headers: {
        'Content-Type': 'application/json',
        'User-Agent': 'Durabl-Webhooks/2.4',
        'X-Durabl-Signature': testSignature,
        'X-Durabl-Event-Id': `evt_${rng.hex(12)}`,
        'X-Durabl-Delivery-Attempt': '1',
      },
      response_headers: ok
        ? { 'Content-Type': 'application/json', Server: 'nginx/1.27' }
        : { 'Content-Type': 'text/plain', Server: 'nginx/1.27' },
    })
    webhookStore.update(id, {
      last_triggered_at: now,
      consecutive_failures: ok ? 0 : hook.consecutive_failures + 1,
    })

    return {
      success: ok,
      status_code: ok ? 200 : 502,
      response_body: ok ? '{"received":true}' : '{"error":"Bad Gateway"}',
      duration_ms: durationMs,
      error: ok ? null : 'Upstream returned 502',
      signature: testSignature,
    }
  }, 900)
}

/** `GET /api/v1/webhooks/{id}/deliveries` (yoki hammasi). */
export async function getDeliveries(filters: DeliveryFilters = {}): Promise<Paginated<WebhookDelivery>> {
  return mockResponse(() => {
    let rows = allDeliveries()
    if (filters.webhook_id) rows = rows.filter((d) => d.webhook_id === filters.webhook_id)
    rows = filterByAny(rows, filters.status, (d) => d.status)
    rows = sortBy(rows, filters.sort_by ?? 'created_at', filters.sort_order ?? 'desc')
    return paginate(rows, filters.page ?? 1, filters.page_size ?? DEFAULT_PAGE_SIZE)
  })
}

/** Bitta yuborishni qayta jo'natish — YANGI urinish yozuvi qo'shiladi. */
export async function resendDelivery(id: string): Promise<{ resent: boolean }> {
  return mockResponse(() => {
    const original = deliveryStore.find(id)
    if (!original) throw notFound('Delivery', id)
    const rng = new Rng(Date.now() % 70_000)
    const ok = rng.bool(0.8)
    const now = new Date().toISOString()
    deliveryStore.insert({
      ...original,
      id: `whd_${rng.hex(10)}`,
      attempt: original.attempt + 1,
      status: ok ? 'success' : 'failed',
      response_code: ok ? 200 : 502,
      error_message: ok ? null : 'Upstream returned 502',
      duration_ms: rng.int(48, 900),
      delivered_at: ok ? now : null,
      created_at: now,
    })
    return { resent: true }
  }, 600)
}

/**
 * `POST /api/v1/webhooks/{id}/rotate-secret`
 *
 * Yangi imzolash kalitini yaratadi. Eski kalit DARHOL o'chmaydi — mijozning
 * ishlab turgan integratsiyasi uzilmasligi uchun qisqa vaqt amal qiladi.
 * Shu oynada mijoz yangi kalitni o'z tomoniga ko'chirib ulguradi.
 */
export async function rotateWebhookSecret(id: string): Promise<WebhookSecretRotation> {
  return mockResponse(() => {
    const hook = findWebhook(id)
    if (!hook) throw notFound('Webhook', id)
    const rng = new Rng(Date.now() % 80_000)
    const now = new Date()
    const secret = `whsec_${rng.hex(43)}`
    webhookStore.update(id, { secret })
    return {
      webhook_id: id,
      secret,
      rotated_at: now.toISOString(),
      // Eski kalit 24 soat ishlaydi — o'tish davri
      old_secret_valid_until: new Date(now.getTime() + 24 * 3_600_000).toISOString(),
    }
  }, 700)
}
