/** Worker va tizim holati endpointlari. */

import type { QueueDepth, SystemStatus, Worker } from '@/types'
import { dlqDepth, dlqStore } from '@/lib/mock/dlq'
import { REGIONS } from '@/lib/mock/fixtures'
import { Rng } from '@/lib/mock/seed'
import {
  type FeatureFlag,
  setMaintenanceMode,
  setQueuePaused,
  systemControls,
  toggleFlag,
} from '@/lib/mock/system'
import { allWorkers, queueDepths, systemStatus, workerStore } from '@/lib/mock/workers'

import { ApiError, mockResponse, notFound } from './client'

/** `GET /api/v1/admin/system` dagi `workers` qismi. */
export async function getWorkers(): Promise<Worker[]> {
  return mockResponse(() => allWorkers())
}

/** Navbat chuqurligi. */
export async function getQueueDepths(): Promise<QueueDepth[]> {
  return mockResponse(() => queueDepths())
}

/** `GET /api/v1/admin/system` */
export async function getSystemStatus(): Promise<SystemStatus> {
  return mockResponse(() => systemStatus(dlqDepth()))
}

/**
 * `POST /api/v1/admin/workers/{id}/drain`
 *
 * "Drain" — worker joriy job'larini tugatadi, lekin YANGI job olmaydi.
 * To'xtatishdan farqi: ishlayotgan job uzilmaydi.
 */
export async function drainWorker(id: string): Promise<Worker> {
  return mockResponse(() => {
    const worker = workerStore.find(id)
    if (!worker) throw notFound('Worker', id)
    if (worker.state === 'dead') {
      throw new ApiError({
        status: 409,
        code: 'WORKER_DEAD',
        message: 'A dead worker cannot be drained',
      })
    }
    return workerStore.update(id, { state: 'draining' }) ?? worker
  }, 400)
}

/** `POST /api/v1/admin/workers/{id}/resume` — drain'dan qaytarish. */
export async function resumeWorker(id: string): Promise<Worker> {
  return mockResponse(() => {
    const worker = workerStore.find(id)
    if (!worker) throw notFound('Worker', id)
    return (
      workerStore.update(id, { state: worker.active_jobs > 0 ? 'busy' : 'idle' }) ?? worker
    )
  }, 400)
}

/** `POST /api/v1/admin/workers/{id}/restart` */
export async function restartWorker(id: string): Promise<Worker> {
  return mockResponse(() => {
    const worker = workerStore.find(id)
    if (!worker) throw notFound('Worker', id)
    return (
      workerStore.update(id, {
        state: 'starting',
        active_jobs: 0,
        current_job_id: null,
        cpu: 0,
        memory_mb: 0,
        uptime_seconds: 0,
        last_heartbeat_at: new Date().toISOString(),
      }) ?? worker
    )
  }, 900)
}

/** `POST /api/v1/admin/workers` — fleet'ga yangi worker qo'shish. */
export async function addWorker(): Promise<Worker> {
  return mockResponse(() => {
    const existing = allWorkers()
    const rng = new Rng(Date.now() % 60_000)
    const nextNumber = existing.length + 1
    const worker: Worker = {
      id: `wkr-${String(nextNumber).padStart(2, '0')}`,
      region: REGIONS[nextNumber % REGIONS.length] as string,
      state: 'starting',
      active_jobs: 0,
      concurrency: rng.pick([4, 8] as const),
      cpu: 0,
      memory_mb: 0,
      memory_limit_mb: 1_024,
      jobs_processed: 0,
      uptime_seconds: 0,
      last_heartbeat_at: new Date().toISOString(),
      current_job_id: null,
      version: '2.4.0',
    }
    workerStore.insert(worker, 'end')
    return worker
  }, 1_100)
}

/** `GET /api/v1/admin/system/controls` — texnik xizmat va bayroqlar. */
export async function getSystemControls(): Promise<ReturnType<typeof systemControls>> {
  return mockResponse(() => systemControls(), 120)
}

/** `POST /api/v1/admin/system/maintenance` */
export async function setMaintenance(enabled: boolean): Promise<{ maintenance_mode: boolean }> {
  return mockResponse(() => ({ maintenance_mode: setMaintenanceMode(enabled) }), 500)
}

/** `POST /api/v1/admin/queues/pause` — navbatni to'xtatish/davom ettirish. */
export async function setQueuePause(paused: boolean): Promise<{ queue_paused: boolean }> {
  return mockResponse(() => ({ queue_paused: setQueuePaused(paused) }), 450)
}

/** `PUT /api/v1/admin/system/flags/{key}` */
export async function setFeatureFlag(key: string, enabled: boolean): Promise<FeatureFlag> {
  return mockResponse(() => {
    const flag = toggleFlag(key, enabled)
    if (!flag) throw notFound('Feature flag', key)
    return flag
  }, 300)
}

/**
 * `POST /api/v1/admin/system/{subsystem}/restart`
 *
 * Mock rejimida haqiqatan hech narsa qayta ishga tushmaydi — amal muvaffaqiyatli
 * deb qaytariladi, UI esa jarayonni ko'rsatadi.
 */
export async function restartSubsystem(
  subsystem: 'database' | 'redis' | 'sandbox',
): Promise<{ subsystem: string; restarted: boolean }> {
  return mockResponse(() => ({ subsystem, restarted: true }), 1_400)
}

/** `POST /api/v1/admin/cache/flush` */
export async function flushCache(): Promise<{ keys_removed: number }> {
  return mockResponse(() => ({ keys_removed: new Rng(Date.now() % 40_000).int(1_200, 48_000) }), 1_200)
}

/** `POST /api/v1/admin/search/reindex` */
export async function rebuildIndex(): Promise<{ documents: number }> {
  return mockResponse(() => ({ documents: new Rng(Date.now() % 30_000).int(40_000, 220_000) }), 1_800)
}

/** `DELETE /api/v1/admin/dlq` — butun DLQ'ni tozalash (xavfli). */
export async function clearDlq(): Promise<{ removed: number }> {
  return mockResponse(() => {
    const removed = dlqStore.all().length
    dlqStore.removeWhere(() => true)
    return { removed }
  }, 900)
}
