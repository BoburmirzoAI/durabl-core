/** Worker (ishchi) turlari — dashboard paneli va admin fleet jadvali. */

import type { Id, IsoDateTime } from './common'

export type WorkerState = 'starting' | 'idle' | 'busy' | 'draining' | 'stopped' | 'dead'

export const WORKER_STATES: readonly WorkerState[] = [
  'starting',
  'idle',
  'busy',
  'draining',
  'stopped',
  'dead',
] as const

/** Bitta worker holati. */
export interface Worker {
  id: string
  /** Joylashuv (`us-east-1a`) — dizaynda ko'rsatilgan. */
  region: string
  state: WorkerState
  /** Hozir bajarilayotgan job'lar soni. */
  active_jobs: number
  concurrency: number
  /** CPU yuklamasi foizi (0..100) — progress bar. */
  cpu: number
  memory_mb: number
  memory_limit_mb: number
  jobs_processed: number
  /** Ishga tushgandan beri o'tgan vaqt (soniya). */
  uptime_seconds: number
  last_heartbeat_at: IsoDateTime
  current_job_id: Id | null
  version: string
}

/** Navbat chuqurligi (ustuvorlik bo'yicha). */
export interface QueueDepth {
  priority: 'high' | 'normal' | 'low'
  depth: number
  /** Worker olgan, lekin hali tugatmagan. */
  processing: number
}

/** Tizim holati (admin). */
export interface SystemStatus {
  status: 'ok' | 'degraded' | 'down'
  version: string
  environment: string
  checks: Record<string, boolean>
  uptime_seconds: number
  workers: Worker[]
  active_workers: number
  queues: QueueDepth[]
  delayed_jobs: number
  dlq_depth: number
  webhook_queue_depth: number
  sandbox_available: boolean
}
