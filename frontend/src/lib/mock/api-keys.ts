/** API kalit mock generatori. */

import type {
  ApiKey,
  ApiKeyEndpointUsage,
  ApiKeyScope,
  ApiKeyUsage,
  ApiKeyUsagePoint,
} from '@/types'

import { NOW, Rng } from './seed'
import { MockCollection } from './store'

const KEY_DEFS: readonly { name: string; scopes: ApiKeyScope[]; revoked?: boolean; expired?: boolean }[] = [
  { name: 'Production', scopes: ['jobs:read', 'jobs:write', 'dlq:read', 'dlq:write'] },
  { name: 'CI / GitHub Actions', scopes: ['jobs:read', 'jobs:write'] },
  { name: 'Read-only dashboard', scopes: ['jobs:read', 'dlq:read'] },
  { name: 'Old laptop', scopes: ['jobs:read', 'jobs:write'], revoked: true },
  { name: 'Load test (temp)', scopes: ['jobs:write'], expired: true },
]

/** API kaliti to'plami — bir marta quriladi, keyin o'zgartiriladi. */
export const apiKeyStore = new MockCollection<ApiKey>(build, (item) => item.id)

function build(): ApiKey[] {
  return KEY_DEFS.map((def, i) => {
    const rng = new Rng(i * 2_654_435 + 17)
    const prefix = `durabl_${rng.hex(8)}`
    const lastFour = rng.hex(4)
    const revokedAt = def.revoked ? new Date(NOW - rng.int(2, 30) * 86_400_000).toISOString() : null
    const expiresAt = def.expired
      ? new Date(NOW - rng.int(1, 10) * 86_400_000).toISOString()
      : rng.bool(0.3)
        ? new Date(NOW + rng.int(30, 300) * 86_400_000).toISOString()
        : null

    return {
      id: `key_${rng.hex(10)}`,
      name: def.name,
      // Niqoblangan ko'rinish — xom kalit HECH QACHON saqlanmaydi
      masked_key: `${prefix}${'•'.repeat(8)}${lastFour}`,
      key_prefix: prefix,
      last_four: lastFour,
      scopes: def.scopes,
      created_at: new Date(NOW - rng.int(5, 400) * 86_400_000).toISOString(),
      last_used_at:
        def.revoked || def.expired
          ? new Date(NOW - rng.int(10, 60) * 86_400_000).toISOString()
          : new Date(NOW - rng.int(1, 300) * 60_000).toISOString(),
      expires_at: expiresAt,
      revoked_at: revokedAt,
      is_active: !def.revoked && !def.expired,
    }
  })
}

export function allApiKeys(): ApiKey[] {
  return apiKeyStore.all()
}

/** Yangi kalit yaratishda qaytariladigan XOM qiymat (bir marta ko'rsatiladi). */
export function generateRawKey(): string {
  const rng = new Rng(NOW % 100_000)
  return `durabl_${rng.hex(43)}`
}

// ───────────────────────────────────────────────────────────────────────────
// Kalit tafsiloti (foydalanish statistikasi)
// ───────────────────────────────────────────────────────────────────────────

/** Kalit nomidan barqaror urug' — qayta yuklashda bir xil grafik chiqadi. */
function keySeed(keyId: string): number {
  let h = 2_166_136_261
  for (let i = 0; i < keyId.length; i += 1) {
    h ^= keyId.charCodeAt(i)
    h = Math.imul(h, 16_777_619)
  }
  return Math.abs(h)
}

/** Har bir huquq ortida qanday endpointlar turadi. */
const SCOPE_ENDPOINTS: Readonly<
  Record<ApiKeyScope, readonly { method: ApiKeyEndpointUsage['method']; path: string; weight: number }[]>
> = {
  'jobs:read': [
    { method: 'GET', path: '/api/v1/jobs', weight: 30 },
    { method: 'GET', path: '/api/v1/jobs/{id}', weight: 46 },
    { method: 'GET', path: '/api/v1/jobs/{id}/logs', weight: 12 },
  ],
  'jobs:write': [
    { method: 'POST', path: '/api/v1/jobs', weight: 52 },
    { method: 'POST', path: '/api/v1/jobs/{id}/cancel', weight: 4 },
    { method: 'POST', path: '/api/v1/jobs/{id}/retry', weight: 3 },
  ],
  'dlq:read': [{ method: 'GET', path: '/api/v1/dlq', weight: 9 }],
  'dlq:write': [{ method: 'POST', path: '/api/v1/dlq/{id}/retry', weight: 5 }],
  admin: [
    { method: 'GET', path: '/api/v1/admin/stats', weight: 7 },
    { method: 'PUT', path: '/api/v1/admin/users/{id}', weight: 2 },
  ],
}

const USER_AGENTS = [
  'durabl-python/2.4.0 (CPython 3.12.3)',
  'durabl-js/2.4.0 (node 20.11.1)',
  'curl/8.7.1',
  'GitHub-Actions/durabl-deploy',
] as const

/**
 * Kalit foydalanish statistikasi.
 *
 * Grafik kalit YARATILGANIDAN keyingi kunlarni qamraydi: 3 kunlik kalit
 * 30 kunlik tarixga ega bo'lishi mantiqsiz. Bekor qilingan kalit esa
 * bekor qilingan kundan keyin nol so'rov ko'rsatadi.
 */
export function apiKeyUsage(keyId: string): ApiKeyUsage {
  const key = allApiKeys().find((k) => k.id === keyId)
  const rng = new Rng(keySeed(keyId))

  const createdMs = key ? new Date(key.created_at).getTime() : NOW - 30 * 86_400_000
  const stopMs = key?.revoked_at
    ? new Date(key.revoked_at).getTime()
    : key?.expires_at && new Date(key.expires_at).getTime() < NOW
      ? new Date(key.expires_at).getTime()
      : NOW

  // Faol kalit kuniga qancha so'rov yuboradi (kalit turiga qarab)
  const base = key?.scopes.includes('jobs:write') ? rng.int(900, 4_200) : rng.int(40, 320)

  const daily: ApiKeyUsagePoint[] = []
  for (let back = 29; back >= 0; back -= 1) {
    const dayMs = NOW - back * 86_400_000
    const dayStart = new Date(dayMs).toISOString().slice(0, 10)
    // Kalit hali yo'q edi yoki allaqachon o'lgan edi → nol
    const alive = dayMs >= createdMs - 86_400_000 && dayMs <= stopMs + 86_400_000
    if (!alive) {
      daily.push({ date: dayStart, requests: 0, errors: 0 })
      continue
    }
    const weekday = new Date(dayMs).getUTCDay()
    // Dam olish kunlari kamroq trafik — grafik tirik ko'rinadi
    const weekendFactor = weekday === 0 || weekday === 6 ? 0.45 : 1
    const requests = Math.round(base * weekendFactor * (0.75 + rng.next() * 0.5))
    daily.push({
      date: dayStart,
      requests,
      errors: Math.round(requests * (rng.next() * 0.035)),
    })
  }

  const requests30d = daily.reduce((sum, d) => sum + d.requests, 0)
  const errors30d = daily.reduce((sum, d) => sum + d.errors, 0)
  const today = daily[daily.length - 1]

  // Endpointlarni kalit huquqlaridan yig'amiz — ko'rsatilgan yo'llar
  // kalit haqiqatda chaqira oladigan yo'llar bo'lishi kerak
  const scopes = key?.scopes ?? ['jobs:read']
  const defs = scopes.flatMap((scope) => SCOPE_ENDPOINTS[scope] ?? [])
  const totalWeight = defs.reduce((sum, d) => sum + d.weight, 0) || 1
  const topEndpoints: ApiKeyEndpointUsage[] = defs
    .map((def) => ({
      method: def.method,
      path: def.path,
      requests: Math.round((requests30d * def.weight) / totalWeight),
      error_rate: Math.round(rng.next() * 40) / 10,
      last_used_at: new Date(stopMs - rng.int(1, 600) * 60_000).toISOString(),
    }))
    .sort((a, b) => b.requests - a.requests)

  return {
    key_id: keyId,
    requests_30d: requests30d,
    requests_today: key?.is_active ? (today?.requests ?? 0) : 0,
    error_rate: requests30d === 0 ? 0 : Math.round((errors30d / requests30d) * 1_000) / 10,
    rate_limited_30d: Math.round(errors30d * 0.3),
    daily,
    top_endpoints: topEndpoints,
    last_ip: key?.last_used_at
      ? `${rng.int(20, 210)}.${rng.int(0, 255)}.${rng.int(0, 255)}.${rng.int(1, 254)}`
      : null,
    last_user_agent: key?.last_used_at ? rng.pick(USER_AGENTS) : null,
    distinct_ips: key?.is_active ? rng.int(1, 6) : rng.int(0, 2),
  }
}
