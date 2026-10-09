/** Worker fleet mock generatori — dashboard paneli va admin jadvali. */

import type { QueueDepth, SystemStatus, Worker, WorkerState } from '@/types'

import { REGIONS } from './fixtures'
import { NOW, Rng } from './seed'
import { MockCollection } from './store'

const WORKER_COUNT = 6

const STATE_WEIGHTS: readonly (readonly [WorkerState, number])[] = [
  ['busy', 55],
  ['idle', 30],
  ['draining', 8],
  ['starting', 4],
  ['dead', 3],
]

/** Worker to'plami — bir marta quriladi, keyin o'zgartiriladi. */
export const workerStore = new MockCollection<Worker>(build, (item) => item.id)

function build(): Worker[] {
  return Array.from({ length: WORKER_COUNT }, (_, i) => {
    const rng = new Rng(i * 31_337 + 5)
    const state = i < 4 ? (i === 0 ? 'busy' : rng.weighted(STATE_WEIGHTS)) : rng.weighted(STATE_WEIGHTS)
    const dead = state === 'dead'
    const concurrency = rng.pick([4, 4, 8] as const)
    const active = state === 'busy' ? rng.int(1, concurrency) : state === 'idle' ? 0 : rng.int(0, 2)
    const cpu = dead ? 0 : state === 'idle' ? rng.int(8, 30) : rng.int(35, 94)

    return {
      id: `wkr-${String(i + 1).padStart(2, '0')}`,
      region: REGIONS[i % REGIONS.length] as string,
      state,
      active_jobs: active,
      concurrency,
      cpu,
      memory_mb: dead ? 0 : rng.int(120, 900),
      memory_limit_mb: 1_024,
      jobs_processed: rng.int(840, 24_800),
      uptime_seconds: dead ? 0 : rng.int(3_600, 86_400 * 9),
      // O'lgan worker heartbeat yubormaydi — vaqti ancha oldin
      last_heartbeat_at: new Date(NOW - (dead ? rng.int(90, 600) * 1_000 : rng.int(1, 4) * 1_000)).toISOString(),
      current_job_id: state === 'busy' ? `job_${rng.hex(10)}` : null,
      version: '2.4.0',
    }
  })
}

export function allWorkers(): Worker[] {
  return workerStore.all()
}

export function activeWorkerCount(): number {
  return allWorkers().filter((w) => w.state !== 'dead' && w.state !== 'stopped').length
}

export function queueDepths(): QueueDepth[] {
  const rng = new Rng(99_991)
  return [
    { priority: 'high', depth: rng.int(0, 14), processing: rng.int(0, 4) },
    { priority: 'normal', depth: rng.int(40, 180), processing: rng.int(2, 9) },
    { priority: 'low', depth: rng.int(5, 60), processing: rng.int(0, 3) },
  ]
}

export function systemStatus(dlqDepth: number): SystemStatus {
  const workers = allWorkers()
  const hasDead = workers.some((w) => w.state === 'dead')
  return {
    // O'lgan worker bo'lsa tizim "degraded" — yolg'on "hammasi joyida" demaymiz
    status: hasDead ? 'degraded' : 'ok',
    version: '2.4.0',
    environment: 'production',
    checks: { database: true, redis: true, sandbox: true },
    uptime_seconds: 86_400 * 12 + 4_210,
    workers,
    active_workers: activeWorkerCount(),
    queues: queueDepths(),
    delayed_jobs: 37,
    dlq_depth: dlqDepth,
    webhook_queue_depth: 4,
    sandbox_available: true,
  }
}
