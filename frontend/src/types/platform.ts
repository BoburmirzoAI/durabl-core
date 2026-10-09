/** Platforma konfiguratsiyasi (faqat admin). */

import type { Id, IsoDateTime } from './common'
import type { PlanType } from './billing'

// ───────────────────────────────────────────────────────────────────────────
// Tezlik chegaralari
// ───────────────────────────────────────────────────────────────────────────

/** Bitta tarif uchun tezlik chegaralari. */
export interface RateLimitRule {
  plan: PlanType
  requests_per_minute: number
  /** Qisqa muddatli portlash uchun ruxsat (token bucket hajmi). */
  burst: number
  max_concurrent_jobs: number
  /** Sutkalik yuborish chegarasi; `null` — faqat oylik kvota ishlaydi. */
  daily_submit_cap: number | null
  /** Chegaradan oshganda nima bo'ladi. */
  on_exceed: 'reject' | 'queue'
}

// ───────────────────────────────────────────────────────────────────────────
// Tarif va narx
// ───────────────────────────────────────────────────────────────────────────

/** Tahrirlanadigan tarif konfiguratsiyasi. */
export interface PlanConfig {
  plan: PlanType
  price_usd_month: number
  monthly_jobs: number
  /** Limitdan oshgan har 1000 job narxi. */
  overage_per_1k_usd: number
  max_timeout_seconds: number
  max_memory_mb: number
  max_cpus: number
  log_retention_days: number
  allow_network: boolean
  /** Ro'yxatda ko'rsatilsinmi (eski tariflar yashiriladi). */
  is_public: boolean
}

// ───────────────────────────────────────────────────────────────────────────
// Sandbox
// ───────────────────────────────────────────────────────────────────────────

export interface SandboxConfig {
  /** Ishlatiladigan izolyatsiya: gVisor yoki oddiy runc. */
  runtime: 'runsc' | 'runc'
  /** Standart timeout (soniya) — tarif chegarasidan oshmaydi. */
  default_timeout_seconds: number
  default_memory_mb: number
  default_cpus: number
  /** Sandbox ichidan tashqariga chiqish. */
  allow_network: boolean
  /** Fayl tizimi faqat o'qish uchunmi. */
  read_only_rootfs: boolean
  /** Sandbox ichidagi foydalanuvchi UID. */
  run_as_uid: number
  /** Image'lar. */
  python_image: string
  node_image: string
  /** Natija hajmi chegarasi (bayt) — oshsa `output_too_large`. */
  max_output_bytes: number
  /** Ishlatilgan konteyner qancha vaqtdan keyin o'chiriladi. */
  cleanup_after_seconds: number
}

// ───────────────────────────────────────────────────────────────────────────
// Navbat
// ───────────────────────────────────────────────────────────────────────────

export interface QueueConfig {
  /** Lease amal qilish muddati (soniya). */
  lease_ttl_seconds: number
  /** Worker heartbeat yuborish oralig'i (soniya). */
  heartbeat_interval_seconds: number
  /** Muddati o'tgan lease'larni yig'uvchi qanchada bir ishlaydi. */
  reaper_interval_seconds: number
  /** Bitta worker bir vaqtda nechta job oladi. */
  prefetch_count: number
  /** Standart qayta urinishlar soni. */
  default_max_retries: number
  retry_backoff: 'fixed' | 'linear' | 'exponential'
  /** Birinchi qayta urinishgacha kutish (soniya). */
  retry_base_delay_seconds: number
  /** Qayta urinishlar orasidagi eng katta kutish (soniya). */
  retry_max_delay_seconds: number
  /** DLQ chuqurligi shu sondan oshsa ogohlantirish yuboriladi. */
  dlq_alert_threshold: number
}

// ───────────────────────────────────────────────────────────────────────────
// Sirlar
// ───────────────────────────────────────────────────────────────────────────

/**
 * Platforma siri.
 *
 * Qiymat HECH QACHON to'liq qaytmaydi — faqat niqoblangan ko'rinish va
 * oxirgi 4 belgi. Yangilash mumkin, o'qish mumkin emas.
 */
export interface PlatformSecret {
  key: string
  label: string
  description: string
  masked_value: string
  /** Kim va qachon oxirgi marta o'zgartirgan. */
  updated_at: IsoDateTime
  updated_by: string
  /** Shu sirsiz tizim ishlamaydi. */
  required: boolean
  /** Qayerda ishlatiladi. */
  used_by: string
}

// ───────────────────────────────────────────────────────────────────────────
// Zaxira nusxa
// ───────────────────────────────────────────────────────────────────────────

export type BackupStatus = 'completed' | 'running' | 'failed'

export interface BackupRecord {
  id: Id
  started_at: IsoDateTime
  finished_at: IsoDateTime | null
  status: BackupStatus
  /** Hajm (bayt). */
  size_bytes: number
  /** Qo'lda yoki jadval bo'yicha. */
  trigger: 'manual' | 'scheduled'
  /** Qamrab olingan jadvallar soni. */
  tables: number
  /** Saqlangan joy. */
  destination: string
  error: string | null
}

export interface BackupSettings {
  /** Avtomatik zaxira yoqilganmi. */
  enabled: boolean
  /** Cron ifodasi. */
  cron: string
  /** Nusxalar necha kun saqlanadi. */
  retention_days: number
  destination: string
  /** Oxirgi muvaffaqiyatli nusxa. */
  last_successful_at: IsoDateTime | null
}
