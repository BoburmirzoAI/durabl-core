/** Platforma konfiguratsiyasi endpointlari (faqat admin). */

import type {
  BackupRecord,
  BackupSettings,
  PlanConfig,
  PlanType,
  PlatformSecret,
  QueueConfig,
  RateLimitRule,
  SandboxConfig,
} from '@/types'
import {
  allBackups,
  allPlanConfigs,
  allRateLimits,
  allSecrets,
  backupSettings,
  backupSettingsStore,
  backupStore,
  planConfigStore,
  queueConfig,
  queueConfigStore,
  rateLimitStore,
  sandboxConfig,
  sandboxConfigStore,
  secretStore,
} from '@/lib/mock/platform'
import { Rng } from '@/lib/mock/seed'

import { ApiError, mockResponse, notFound } from './client'

// ───────────────────────────────────────────────────────────────────────────
// Tezlik chegaralari
// ───────────────────────────────────────────────────────────────────────────

/** `GET /api/v1/admin/config/rate-limits` */
export async function getRateLimits(): Promise<RateLimitRule[]> {
  return mockResponse(() => allRateLimits(), 280)
}

/** `PUT /api/v1/admin/config/rate-limits/{plan}` */
export async function updateRateLimit(
  plan: PlanType,
  patch: Partial<RateLimitRule>,
): Promise<RateLimitRule> {
  return mockResponse(() => {
    const rule = allRateLimits().find((r) => r.plan === plan)
    if (!rule) throw notFound('Rate limit', plan)
    const next = { ...rule, ...patch }
    if (next.burst < next.requests_per_minute) {
      throw new ApiError({
        status: 422,
        code: 'BURST_TOO_LOW',
        message: 'The burst size must be at least the per-minute rate, otherwise the bucket never fills',
      })
    }
    if (next.requests_per_minute < 1) {
      throw new ApiError({
        status: 422,
        code: 'INVALID_RATE',
        message: 'The per-minute rate must be at least 1',
      })
    }
    return rateLimitStore.update(plan, patch) ?? rule
  }, 420)
}

// ───────────────────────────────────────────────────────────────────────────
// Tariflar
// ───────────────────────────────────────────────────────────────────────────

/** `GET /api/v1/admin/config/plans` */
export async function getPlanConfigs(): Promise<PlanConfig[]> {
  return mockResponse(() => allPlanConfigs(), 280)
}

/**
 * `PUT /api/v1/admin/config/plans/{plan}`
 *
 * Narx o'zgarishi MAVJUD mijozlarga darhol tegmaydi (backend ularni
 * keyingi davrdan ko'chiradi), lekin yangi obunalar darhol yangi narxda
 * bo'ladi. UI buni aniq aytadi.
 */
export async function updatePlanConfig(
  plan: PlanType,
  patch: Partial<PlanConfig>,
): Promise<PlanConfig> {
  return mockResponse(() => {
    const config = allPlanConfigs().find((p) => p.plan === plan)
    if (!config) throw notFound('Plan', plan)
    const next = { ...config, ...patch }
    if (next.price_usd_month < 0 || next.monthly_jobs < 0) {
      throw new ApiError({
        status: 422,
        code: 'NEGATIVE_VALUE',
        message: 'Price and quota cannot be negative',
      })
    }
    if (plan === 'free' && next.price_usd_month > 0) {
      throw new ApiError({
        status: 422,
        code: 'FREE_MUST_BE_FREE',
        message: 'The free plan cannot have a price — create a new plan instead',
      })
    }
    return planConfigStore.update(plan, patch) ?? config
  }, 480)
}

// ───────────────────────────────────────────────────────────────────────────
// Sandbox va navbat
// ───────────────────────────────────────────────────────────────────────────

/** `GET /api/v1/admin/config/sandbox` */
export async function getSandboxConfig(): Promise<SandboxConfig> {
  return mockResponse(() => sandboxConfig(), 260)
}

/** `PUT /api/v1/admin/config/sandbox` */
export async function updateSandboxConfig(patch: Partial<SandboxConfig>): Promise<SandboxConfig> {
  return mockResponse(() => {
    const next = { ...sandboxConfig(), ...patch }
    if (next.runtime === 'runc' && next.allow_network) {
      throw new ApiError({
        status: 422,
        code: 'UNSAFE_COMBINATION',
        message:
          'runc with outbound network is an unsafe combination for customer code. Switch to gVisor (runsc) or turn the network off',
      })
    }
    sandboxConfigStore.update('self', patch)
    return sandboxConfig()
  }, 520)
}

/** `GET /api/v1/admin/config/queue` */
export async function getQueueConfig(): Promise<QueueConfig> {
  return mockResponse(() => queueConfig(), 260)
}

/**
 * `PUT /api/v1/admin/config/queue`
 *
 * Eng muhim tekshiruv: heartbeat oralig'i lease muddatidan KICHIK
 * bo'lishi shart. Teng yoki katta bo'lsa, sog'lom worker ham lease'ni
 * yangilashga ulgurmaydi va uning job'lari doimiy ravishda boshqa
 * worker'ga o'tib ketadi.
 */
export async function updateQueueConfig(patch: Partial<QueueConfig>): Promise<QueueConfig> {
  return mockResponse(() => {
    const next = { ...queueConfig(), ...patch }
    if (next.heartbeat_interval_seconds >= next.lease_ttl_seconds) {
      throw new ApiError({
        status: 422,
        code: 'HEARTBEAT_TOO_SLOW',
        message:
          'The heartbeat interval must be shorter than the lease TTL, otherwise even a healthy worker loses its lease',
      })
    }
    if (next.heartbeat_interval_seconds * 2 > next.lease_ttl_seconds) {
      throw new ApiError({
        status: 422,
        code: 'HEARTBEAT_MARGIN',
        message:
          'The lease TTL must be at least twice the heartbeat interval, so one missed heartbeat does not hand the job to another worker',
      })
    }
    if (next.reaper_interval_seconds > next.lease_ttl_seconds) {
      throw new ApiError({
        status: 422,
        code: 'REAPER_TOO_SLOW',
        message: 'If the reaper runs slower than leases expire, a dead worker\'s jobs hang for longer than they need to',
      })
    }
    if (next.retry_base_delay_seconds > next.retry_max_delay_seconds) {
      throw new ApiError({
        status: 422,
        code: 'BACKOFF_INVERTED',
        message: 'The base delay cannot exceed the maximum delay',
      })
    }
    queueConfigStore.update('self', patch)
    return queueConfig()
  }, 520)
}

// ───────────────────────────────────────────────────────────────────────────
// Sirlar
// ───────────────────────────────────────────────────────────────────────────

/** `GET /api/v1/admin/config/secrets` — qiymatlar NIQOBLANGAN. */
export async function getSecrets(): Promise<PlatformSecret[]> {
  return mockResponse(() => allSecrets(), 300)
}

/**
 * `PUT /api/v1/admin/config/secrets/{key}`
 *
 * Yangi qiymat yuboriladi, lekin javobda ham NIQOBLANGAN ko'rinish
 * qaytadi: hech qanday API sirni o'qib bera olmasligi kerak.
 */
export async function updateSecret(key: string, value: string): Promise<PlatformSecret> {
  return mockResponse(() => {
    const secret = allSecrets().find((s) => s.key === key)
    if (!secret) throw notFound('Secret', key)
    const trimmed = value.trim()
    if (trimmed.length < 8) {
      throw new ApiError({
        status: 422,
        code: 'SECRET_TOO_SHORT',
        message: 'A secret must be at least 8 characters',
      })
    }
    const tail = trimmed.slice(-4)
    return (
      secretStore.update(key, {
        masked_value: `${'•'.repeat(16)}${tail}`,
        updated_at: new Date().toISOString(),
        updated_by: 'admin@durabl.dev',
      }) ?? secret
    )
  }, 560)
}

// ───────────────────────────────────────────────────────────────────────────
// Zaxira nusxalar
// ───────────────────────────────────────────────────────────────────────────

/** `GET /api/v1/admin/backups` */
export async function getBackups(): Promise<BackupRecord[]> {
  return mockResponse(() => allBackups(), 320)
}

/** `GET /api/v1/admin/backups/settings` */
export async function getBackupSettings(): Promise<BackupSettings> {
  return mockResponse(() => backupSettings(), 240)
}

/** `PUT /api/v1/admin/backups/settings` */
export async function updateBackupSettings(
  patch: Partial<BackupSettings>,
): Promise<BackupSettings> {
  return mockResponse(() => {
    backupSettingsStore.update('self', patch)
    return backupSettings()
  }, 420)
}

/**
 * `POST /api/v1/admin/backups`
 *
 * Yozuv darhol `running` holatida qo'shiladi — haqiqiy zaxira ham
 * daqiqalar davom etadi va UI uni kutib turgan holatda ko'rsatishi kerak.
 */
export async function triggerBackup(): Promise<BackupRecord> {
  return mockResponse(() => {
    const rng = new Rng(Date.now() % 400_009)
    const record: BackupRecord = {
      id: `bkp_${rng.hex(10)}`,
      started_at: new Date().toISOString(),
      finished_at: null,
      status: 'running',
      size_bytes: 0,
      trigger: 'manual',
      tables: 11,
      destination: backupSettings().destination,
      error: null,
    }
    backupStore.insert(record)
    return record
  }, 700)
}

/**
 * `POST /api/v1/admin/backups/{id}/restore`
 *
 * Mock rejimida HECH NARSA tiklanmaydi — buni yashirmaymiz. Haqiqiy
 * tiklash xizmatni to'xtatishni, bazani almashtirishni va keyin qayta
 * ishga tushirishni talab qiladi; uni bitta tugma bilan "soxta"
 * ko'rsatish zararli bo'lardi.
 */
export async function restoreBackup(id: string): Promise<{ accepted: boolean; message: string }> {
  return mockResponse(() => {
    const record = allBackups().find((b) => b.id === id)
    if (!record) throw notFound('Backup', id)
    if (record.status !== 'completed') {
      throw new ApiError({
        status: 409,
        code: 'BACKUP_NOT_RESTORABLE',
        message: 'Only a completed backup can be restored',
      })
    }
    return {
      accepted: true,
      message:
        'Restore accepted. In a real deployment this stops the API and workers, replaces the database, then restarts them — expect several minutes of downtime.',
    }
  }, 800)
}
