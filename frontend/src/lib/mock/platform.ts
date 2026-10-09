/** Platforma konfiguratsiyasi mock'i (faqat admin). */

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

import { PLAN_LIMITS } from './billing'
import { NOW, Rng } from './seed'
import { MockCollection } from './store'

// ───────────────────────────────────────────────────────────────────────────
// Tezlik chegaralari
// ───────────────────────────────────────────────────────────────────────────

/**
 * Chegaralar `PLAN_LIMITS` dan keltirib chiqariladi.
 *
 * Ikki joyda alohida yozilsa, tahrir qilinganda ular ajralib ketadi va
 * `/billing` sahifasi bir narsa, admin boshqa narsa ko'rsatadi.
 */
export const rateLimitStore = new MockCollection<RateLimitRule>(
  () =>
    (Object.keys(PLAN_LIMITS) as PlanType[]).map((plan) => {
      const limits = PLAN_LIMITS[plan]
      return {
        plan,
        requests_per_minute: limits.requests_per_minute,
        // Portlash chegarasi daqiqalik chegaraning yarmi — qisqa
        // ko'tarilishga yo'l ochadi, lekin suiiste'molga emas
        burst: Math.max(5, Math.round(limits.requests_per_minute / 2)),
        max_concurrent_jobs: limits.max_concurrent_jobs,
        daily_submit_cap: plan === 'free' ? 200 : null,
        on_exceed: plan === 'free' ? 'reject' : 'queue',
      }
    }),
  (rule) => rule.plan,
)

export function allRateLimits(): RateLimitRule[] {
  return rateLimitStore.all()
}

// ───────────────────────────────────────────────────────────────────────────
// Tariflar
// ───────────────────────────────────────────────────────────────────────────

export const planConfigStore = new MockCollection<PlanConfig>(
  () =>
    (Object.keys(PLAN_LIMITS) as PlanType[]).map((plan) => {
      const limits = PLAN_LIMITS[plan]
      return {
        plan,
        price_usd_month: limits.price_usd_month,
        monthly_jobs: limits.monthly_jobs,
        overage_per_1k_usd: plan === 'free' ? 0 : 2.5,
        max_timeout_seconds: limits.max_timeout_seconds,
        max_memory_mb: limits.max_memory_mb,
        max_cpus: limits.max_cpus,
        log_retention_days: limits.log_retention_days,
        allow_network: limits.allow_network,
        is_public: true,
      }
    }),
  (config) => config.plan,
)

export function allPlanConfigs(): PlanConfig[] {
  return planConfigStore.all()
}

// ───────────────────────────────────────────────────────────────────────────
// Sandbox
// ───────────────────────────────────────────────────────────────────────────

export const sandboxConfigStore = new MockCollection<SandboxConfig & { id: string }>(
  () => [
    {
      id: 'self',
      runtime: 'runsc',
      default_timeout_seconds: 300,
      default_memory_mb: 512,
      default_cpus: 1,
      allow_network: false,
      read_only_rootfs: true,
      run_as_uid: 10_001,
      python_image: 'durabl/sandbox-python:3.12',
      node_image: 'durabl/sandbox-node:20',
      max_output_bytes: 1_048_576,
      cleanup_after_seconds: 60,
    },
  ],
  (row) => row.id,
)

export function sandboxConfig(): SandboxConfig {
  const { id: _id, ...rest } = sandboxConfigStore.all()[0] as SandboxConfig & { id: string }
  return rest
}

// ───────────────────────────────────────────────────────────────────────────
// Navbat
// ───────────────────────────────────────────────────────────────────────────

export const queueConfigStore = new MockCollection<QueueConfig & { id: string }>(
  () => [
    {
      id: 'self',
      // Backend'dagi haqiqiy qiymatlar bilan bir xil
      lease_ttl_seconds: 15,
      heartbeat_interval_seconds: 5,
      reaper_interval_seconds: 5,
      prefetch_count: 1,
      default_max_retries: 3,
      retry_backoff: 'exponential',
      retry_base_delay_seconds: 2,
      retry_max_delay_seconds: 300,
      dlq_alert_threshold: 25,
    },
  ],
  (row) => row.id,
)

export function queueConfig(): QueueConfig {
  const { id: _id, ...rest } = queueConfigStore.all()[0] as QueueConfig & { id: string }
  return rest
}

// ───────────────────────────────────────────────────────────────────────────
// Sirlar
// ───────────────────────────────────────────────────────────────────────────

const SECRET_DEFS: readonly {
  key: string
  label: string
  description: string
  required: boolean
  usedBy: string
  prefix: string
}[] = [
  {
    key: 'DATABASE_URL',
    label: 'Database URL',
    description: 'PostgreSQL connection string for the API and workers.',
    required: true,
    usedBy: 'api, worker',
    prefix: 'postgresql://durabl:',
  },
  {
    key: 'REDIS_URL',
    label: 'Redis URL',
    description: 'Queue, idempotency keys and lease bookkeeping.',
    required: true,
    usedBy: 'api, worker',
    prefix: 'redis://:',
  },
  {
    key: 'JWT_SECRET',
    label: 'JWT signing secret',
    description: 'Signs access tokens. Rotating it signs every user out.',
    required: true,
    usedBy: 'api',
    prefix: '',
  },
  {
    key: 'WEBHOOK_SIGNING_KEY',
    label: 'Webhook signing key',
    description: 'Base key used to derive per-endpoint HMAC secrets.',
    required: true,
    usedBy: 'worker',
    prefix: 'whsec_',
  },
  {
    key: 'SMTP_PASSWORD',
    label: 'SMTP password',
    description: 'Outbound email for alerts and invitations.',
    required: false,
    usedBy: 'api',
    prefix: '',
  },
  {
    key: 'STRIPE_SECRET_KEY',
    label: 'Stripe secret key',
    description: 'Billing. Without it, plan changes are recorded but not charged.',
    required: false,
    usedBy: 'api',
    prefix: 'sk_live_',
  },
  {
    key: 'SENTRY_DSN',
    label: 'Sentry DSN',
    description: 'Error reporting. Optional, but strongly recommended.',
    required: false,
    usedBy: 'api, worker',
    prefix: 'https://',
  },
]

export const secretStore = new MockCollection<PlatformSecret>(buildSecrets, (s) => s.key)

function buildSecrets(): PlatformSecret[] {
  return SECRET_DEFS.map((def, i) => {
    const rng = new Rng(i * 31_337 + 7)
    const tail = rng.hex(4)
    return {
      key: def.key,
      label: def.label,
      description: def.description,
      // Qiymat HECH QACHON to'liq ko'rsatilmaydi
      masked_value: `${def.prefix}${'•'.repeat(16)}${tail}`,
      updated_at: new Date(NOW - rng.int(5, 400) * 86_400_000).toISOString(),
      updated_by: rng.bool(0.6) ? 'admin@durabl.dev' : 'deploy-bot',
      required: def.required,
      used_by: def.usedBy,
    }
  })
}

export function allSecrets(): PlatformSecret[] {
  return secretStore.all()
}

// ───────────────────────────────────────────────────────────────────────────
// Zaxira nusxalar
// ───────────────────────────────────────────────────────────────────────────

export const backupSettingsStore = new MockCollection<BackupSettings & { id: string }>(
  () => [
    {
      id: 'self',
      enabled: true,
      cron: '0 3 * * *',
      retention_days: 30,
      destination: 's3://durabl-backups/production',
      last_successful_at: new Date(NOW - 7 * 3_600_000).toISOString(),
    },
  ],
  (row) => row.id,
)

export function backupSettings(): BackupSettings {
  const { id: _id, ...rest } = backupSettingsStore.all()[0] as BackupSettings & { id: string }
  return rest
}

export const backupStore = new MockCollection<BackupRecord>(buildBackups, (b) => b.id)

function buildBackups(): BackupRecord[] {
  return Array.from({ length: 10 }, (_, i) => {
    const rng = new Rng(i * 65_537 + 13)
    // Bitta eski nusxa muvaffaqiyatsiz — tarix "hammasi yaxshi" bo'lib
    // ko'rinsa, "restore" tugmasini bosish qanchalik jiddiyligi bilinmaydi
    const failed = i === 4
    const startedAt = NOW - (i * 24 + rng.int(0, 2)) * 3_600_000
    const durationMs = rng.int(40_000, 220_000)
    return {
      id: `bkp_${rng.hex(10)}`,
      started_at: new Date(startedAt).toISOString(),
      finished_at: failed ? null : new Date(startedAt + durationMs).toISOString(),
      status: failed ? 'failed' : 'completed',
      size_bytes: failed ? 0 : rng.int(180, 920) * 1_048_576,
      trigger: i === 0 ? 'manual' : 'scheduled',
      tables: 11,
      destination: 's3://durabl-backups/production',
      error: failed ? 'Upload aborted: 403 from the object store (expired credentials)' : null,
    }
  })
}

export function allBackups(): BackupRecord[] {
  return backupStore.all()
}
