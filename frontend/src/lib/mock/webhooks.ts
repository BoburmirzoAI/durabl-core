/** Webhook va yuborish tarixi mock generatori. */

import type {
  DeliveryStatus,
  IsoDateTime,
  Webhook,
  WebhookDelivery,
  WebhookEventName,
} from '@/types'

import { allJobs } from './jobs'
import { NOW, Rng } from './seed'
import { MockCollection } from './store'

const HOOK_DEFS: readonly { url: string; events: WebhookEventName[]; description: string }[] = [
  {
    url: 'https://api.acme.io/durabl/events',
    events: ['job.succeeded', 'job.failed', 'job.dead_lettered'],
    description: 'Production event sink',
  },
  {
    url: 'https://hooks.slack.com/services/T04/B07/xQn2',
    events: ['job.dead_lettered'],
    description: 'Slack #alerts — DLQ only',
  },
  {
    url: 'https://staging.shipfast.co/webhooks/durabl',
    events: ['job.queued', 'job.started', 'job.succeeded', 'job.failed'],
    description: 'Staging mirror',
  },
]

/** Webhook to'plami — bir marta quriladi, keyin o'zgartiriladi. */
export const webhookStore = new MockCollection<Webhook>(buildHooks, (w) => w.id)
/** Yetkazishlar to'plami — test/resend amallari shu yerga yozadi. */
export const deliveryStore = new MockCollection<WebhookDelivery>(buildDeliveries, (d) => d.id)

function buildHooks(): Webhook[] {
  return HOOK_DEFS.map((def, i) => {
    const rng = new Rng(i * 7_013 + 23)
    // Uchinchi webhook nosoz — UI ogohlantirish holatini ko'rsatishi uchun
    const failing = i === 2
    return {
      id: `whk_${rng.hex(10)}`,
      user_id: 'usr_current',
      url: def.url,
      events: def.events,
      is_active: !failing || rng.bool(0.5),
      description: def.description,
      last_triggered_at: new Date(NOW - rng.int(1, 40) * 60_000).toISOString(),
      success_rate: failing ? rng.int(62, 78) : rng.int(97, 100),
      consecutive_failures: failing ? rng.int(3, 7) : 0,
      created_at: new Date(NOW - rng.int(20, 240) * 86_400_000).toISOString(),
    }
  })
}

export function allWebhooks(): Webhook[] {
  return webhookStore.all()
}

export function findWebhook(id: string): Webhook | undefined {
  return allWebhooks().find((w) => w.id === id)
}

const DELIVERY_WEIGHTS: readonly (readonly [DeliveryStatus, number])[] = [
  ['success', 78],
  ['failed', 9],
  ['retrying', 7],
  ['exhausted', 4],
  ['pending', 2],
]

/**
 * Hodisa nomidan job holatini keltirib chiqaradi.
 *
 * Payload'dagi `status` hodisaga MOS kelishi shart: `job.succeeded`
 * ichida `status: "failed"` turgan tanani mijoz xato deb hisoblaydi.
 */
function eventStatus(event: WebhookEventName): string {
  switch (event) {
    case 'job.queued':
      return 'queued'
    case 'job.started':
      return 'running'
    case 'job.succeeded':
      return 'success'
    case 'job.failed':
      return 'failed'
    case 'job.cancelled':
      return 'cancelled'
    case 'job.dead_lettered':
      return 'dead_letter'
  }
}

function requestBody(
  event: WebhookEventName,
  jobId: string,
  createdAt: IsoDateTime,
  durationMs: number,
): string {
  return JSON.stringify(
    {
      event,
      // Hodisa vaqti yetkazish vaqtidan KEYIN bo'lishi mumkin emas.
      timestamp: createdAt,
      data: {
        job_id: jobId,
        status: eventStatus(event),
        runtime: 'python',
        duration_ms: durationMs,
      },
    },
    null,
    2,
  )
}

function responseBody(status: DeliveryStatus, code: number | null): string {
  if (status === 'success') return JSON.stringify({ received: true, id: 'evt_8f21c' }, null, 2)
  if (code === 404) return JSON.stringify({ error: 'Not Found' }, null, 2)
  if (code === 429) return JSON.stringify({ error: 'Too Many Requests', retry_after: 30 }, null, 2)
  if (code === null) return 'connect ETIMEDOUT 203.0.113.42:443'
  return JSON.stringify({ error: 'Internal Server Error' }, null, 2)
}

function buildDeliveries(): WebhookDelivery[] {
  const hooks = allWebhooks()
  const jobs = allJobs().slice(0, 60)
  return Array.from({ length: 48 }, (_, i) => {
    const rng = new Rng(i * 15_485_863 + 41)
    const hook = hooks[i % hooks.length] as Webhook
    const job = jobs[i % jobs.length]
    const status = rng.weighted(DELIVERY_WEIGHTS)
    const event = rng.pick(hook.events)
    const code =
      status === 'success'
        ? 200
        : status === 'pending'
          ? null
          : rng.pick([500, 502, 429, 404, null] as const)

    const createdAt = new Date(NOW - (i * 7 + rng.int(1, 6)) * 60_000).toISOString()

    return {
      id: `dlv_${rng.hex(10)}`,
      webhook_id: hook.id,
      webhook_url: hook.url,
      job_id: job?.id ?? null,
      event,
      status,
      attempt: status === 'success' ? 1 : rng.int(1, 5),
      response_code: code,
      request_body: requestBody(
        event,
        job?.id ?? 'job_unknown',
        createdAt,
        job?.duration_ms ?? 1_240,
      ),
      response_body: responseBody(status, code),
      error_message:
        status === 'success' || status === 'pending'
          ? null
          : code === null
            ? 'Connection timed out after 10s'
            : `Upstream returned ${code}`,
      duration_ms: status === 'pending' ? null : rng.int(42, 2_400),
      delivered_at: status === 'success' ? createdAt : null,
      created_at: createdAt,
      ...deliveryHeaders(rng, createdAt, status, code),
    }
  })
}

export function allDeliveries(): WebhookDelivery[] {
  return deliveryStore.all()
}

/**
 * Yetkazish sarlavhalari va imzosi.
 *
 * Imzo shakli backend bilan AYNI: `t=<unix>,v1=<hmac-sha256-hex>`. Mijoz
 * uni `secret` bilan qayta hisoblab tekshiradi, shuning uchun tafsilot
 * oynasida u to'liq ko'rsatiladi (yashirilmaydi — bu sir emas, imzo).
 */
function deliveryHeaders(
  rng: Rng,
  createdAt: string,
  status: DeliveryStatus,
  code: number | null,
): Pick<
  WebhookDelivery,
  'request_headers' | 'response_headers' | 'signature' | 'signature_valid'
> {
  const timestamp = Math.floor(new Date(createdAt).getTime() / 1_000)
  const signature = `t=${timestamp},v1=${rng.hex(64)}`

  return {
    signature,
    // Mock rejimida imzo har doim to'g'ri — backend ulangach bu maydon
    // mijoz endpointi imzoni qabul qilgan-qilmaganini aks ettiradi.
    signature_valid: true,
    request_headers: {
      'Content-Type': 'application/json',
      'User-Agent': 'Durabl-Webhooks/2.4',
      'X-Durabl-Signature': signature,
      'X-Durabl-Event-Id': `evt_${rng.hex(12)}`,
      'X-Durabl-Delivery-Attempt': '1',
      'Idempotency-Key': `whd_${rng.hex(10)}`,
    },
    response_headers:
      status === 'pending'
        ? {}
        : {
            'Content-Type': 'application/json',
            Date: new Date(createdAt).toUTCString(),
            Server: rng.pick(['nginx/1.27', 'cloudflare', 'envoy', 'gunicorn/22.0']),
            ...(code === 429 ? { 'Retry-After': String(rng.int(5, 60)) } : {}),
          },
  }
}
