/** API kalit endpointlari. */

import type {
  ApiKey,
  ApiKeyCreateInput,
  ApiKeyCreated,
  ApiKeyRotation,
  ApiKeyScope,
  ApiKeyUsage,
} from '@/types'
import { allApiKeys, apiKeyStore, apiKeyUsage, generateRawKey } from '@/lib/mock/api-keys'
import { Rng } from '@/lib/mock/seed'

import { ApiError, mockResponse, notFound } from './client'

/** `GET /api/v1/api-keys` */
export async function getApiKeys(): Promise<ApiKey[]> {
  return mockResponse(() => allApiKeys())
}

/**
 * `POST /api/v1/api-keys`
 *
 * XOM kalit FAQAT shu javobda qaytadi — UI uni bir marta ko'rsatadi va
 * boshqa hech qayerda saqlamaydi.
 */
export async function createApiKey(input: ApiKeyCreateInput): Promise<ApiKeyCreated> {
  return mockResponse(() => {
    const rng = new Rng(Date.now() % 90_000)
    const raw = generateRawKey()
    const prefix = raw.slice(0, 15)
    const lastFour = raw.slice(-4)
    const created: ApiKeyCreated = {
      id: `key_${rng.hex(10)}`,
      name: input.name,
      key: raw,
      masked_key: `${prefix}${'•'.repeat(8)}${lastFour}`,
      key_prefix: prefix,
      last_four: lastFour,
      scopes: input.scopes,
      created_at: new Date().toISOString(),
      last_used_at: null,
      expires_at: input.expires_in_days
        ? new Date(Date.now() + input.expires_in_days * 86_400_000).toISOString()
        : null,
      revoked_at: null,
      is_active: true,
    }
    // XOM kalitsiz nusxa jadvalga qo'shiladi — ro'yxatda darhol ko'rinadi
    const { key: _raw, ...stored } = created
    apiKeyStore.insert(stored)
    return created
  }, 500)
}

/** `DELETE /api/v1/api-keys/{id}` — kalitni bekor qiladi. */
export async function revokeApiKey(id: string): Promise<{ revoked: boolean }> {
  return mockResponse(() => {
    if (!allApiKeys().some((k) => k.id === id)) throw notFound('API key', id)
    const revokedAt = new Date().toISOString()
    apiKeyStore.update(id, { revoked_at: revokedAt, is_active: false })
    return { revoked: true }
  }, 300)
}

/** Kalit nomini o'zgartirish. */
export async function renameApiKey(id: string, name: string): Promise<ApiKey> {
  return mockResponse(() => {
    const key = allApiKeys().find((k) => k.id === id)
    if (!key) throw notFound('API key', id)
    return apiKeyStore.update(id, { name }) ?? key
  }, 300)
}

/** `GET /api/v1/api-keys/{id}` */
export async function getApiKey(id: string): Promise<ApiKey> {
  return mockResponse(() => {
    const key = allApiKeys().find((k) => k.id === id)
    if (!key) throw notFound('API key', id)
    return key
  })
}

/** `GET /api/v1/api-keys/{id}/usage` — oxirgi 30 kun. */
export async function getApiKeyUsage(id: string): Promise<ApiKeyUsage> {
  return mockResponse(() => {
    if (!allApiKeys().some((k) => k.id === id)) throw notFound('API key', id)
    return apiKeyUsage(id)
  }, 420)
}

/**
 * `PUT /api/v1/api-keys/{id}/scopes`
 *
 * Huquqlarni o'zgartirish kalitni QAYTA YARATMAYDI — xom qiymat o'sha
 * qoladi, faqat ruxsatlar toraytiriladi yoki kengaytiriladi.
 */
export async function updateApiKeyScopes(id: string, scopes: ApiKeyScope[]): Promise<ApiKey> {
  return mockResponse(() => {
    const key = allApiKeys().find((k) => k.id === id)
    if (!key) throw notFound('API key', id)
    if (key.revoked_at) {
      throw new ApiError({
        status: 409,
        code: 'KEY_REVOKED',
        message: 'The permissions of a revoked key cannot be changed',
      })
    }
    if (scopes.length === 0) {
      throw new ApiError({
        status: 422,
        code: 'NO_SCOPES',
        message: 'A key needs at least one permission',
      })
    }
    return apiKeyStore.update(id, { scopes }) ?? key
  }, 400)
}

/** `PUT /api/v1/api-keys/{id}/expiry` — `null` muddatsiz qiladi. */
export async function updateApiKeyExpiry(
  id: string,
  expiresInDays: number | null,
): Promise<ApiKey> {
  return mockResponse(() => {
    const key = allApiKeys().find((k) => k.id === id)
    if (!key) throw notFound('API key', id)
    return (
      apiKeyStore.update(id, {
        expires_at:
          expiresInDays === null
            ? null
            : new Date(Date.now() + expiresInDays * 86_400_000).toISOString(),
      }) ?? key
    )
  }, 350)
}

/**
 * `POST /api/v1/api-keys/{id}/rotate`
 *
 * Yangi xom kalit beradi, eskisiga `GRACE_HOURS` muddat qoldiradi.
 * Shu sababli rotatsiya ishlab turgan integratsiyani darhol uzmaydi.
 */
const ROTATE_GRACE_HOURS = 24

export async function rotateApiKey(id: string): Promise<ApiKeyRotation> {
  return mockResponse(() => {
    const key = allApiKeys().find((k) => k.id === id)
    if (!key) throw notFound('API key', id)
    if (key.revoked_at) {
      throw new ApiError({
        status: 409,
        code: 'KEY_REVOKED',
        message: 'A revoked key cannot be rotated',
      })
    }
    const rng = new Rng(Date.now() % 90_000)
    const raw = `durabl_${rng.hex(43)}`
    const prefix = raw.slice(0, 15)
    const lastFour = raw.slice(-4)
    const masked = `${prefix}${'•'.repeat(8)}${lastFour}`
    const now = new Date()

    apiKeyStore.update(id, {
      masked_key: masked,
      key_prefix: prefix,
      last_four: lastFour,
      // Rotatsiya kalitni "yangi" qiladi — oxirgi ishlatilgan vaqt nollanadi
      last_used_at: null,
    })

    return {
      key_id: id,
      key: raw,
      masked_key: masked,
      rotated_at: now.toISOString(),
      old_key_valid_until: new Date(now.getTime() + ROTATE_GRACE_HOURS * 3_600_000).toISOString(),
    }
  }, 600)
}
