/**
 * Jonli simulyatsiya — mock holatini vaqt o'tishi bilan o'zgartiradi.
 *
 * ═══════════════════════════════════════════════════════════════════
 * NEGA KERAK
 * ═══════════════════════════════════════════════════════════════════
 *
 * Job platformasi tabiatan harakatdagi tizim: job'lar kelib tushadi,
 * navbatdan o'tadi, bajariladi. Statik mock bu hissiyotni bermaydi —
 * ekran "o'lik" ko'rinadi va interfeys haqiqiy ekanligiga ishonch
 * uyg'onmaydi.
 *
 * ═══════════════════════════════════════════════════════════════════
 * QANDAY ISHLAYDI
 * ═══════════════════════════════════════════════════════════════════
 *
 * Bitta taymer barcha o'zgarishlarni bajaradi (har bir komponent o'z
 * taymerini yuritmaydi — aks holda ular bir-biriga mos kelmaydi).
 *
 * `start()` sanovchi bilan ishlaydi: bir nechta komponent chaqirsa ham
 * taymer BITTA bo'ladi va oxirgisi uzilganda to'xtaydi.
 *
 * Backend ulanganda bu fayl o'chiriladi — haqiqiy o'zgarishlar
 * WebSocket yoki polling orqali keladi.
 */

import type { Job, JobStatus } from '@/types'

import { allJobs, updateJob } from './jobs'
import { Rng } from './seed'
import { notifyChanged } from './store'
import { allWorkers, workerStore } from './workers'

/** Har necha millisekundda holat yangilanadi. */
const TICK_MS = 3_000

let timer: ReturnType<typeof setInterval> | null = null
let subscribers = 0
let tick = 0

/**
 * Bitta job'ni keyingi holatga o'tkazadi.
 *
 * O'tish grafigi backend'dagi `JOB_STATUS_TRANSITIONS` bilan bir xil:
 * pending -> queued -> running -> success|failed
 */
function advanceJob(job: Job, rng: Rng): Partial<Job> | null {
  const now = new Date().toISOString()

  if (job.status === 'pending') {
    return { status: 'queued', queued_at: now }
  }

  if (job.status === 'queued') {
    const worker = allWorkers().find((w) => w.state === 'idle' || w.state === 'busy')
    return {
      status: 'running',
      started_at: now,
      worker_id: worker?.id ?? null,
      attempts_used: Math.max(1, job.attempts_used),
    }
  }

  if (job.status === 'running') {
    // Job'lar ~82% hollarda muvaffaqiyatli tugaydi (mock taqsimoti bilan bir xil)
    const ok = rng.bool(0.82)
    const started = job.started_at ? new Date(job.started_at).getTime() : Date.now() - 2_000
    const durationMs = Math.max(120, Date.now() - started)
    const status: JobStatus = ok ? 'success' : 'failed'
    return {
      status,
      finished_at: now,
      duration_ms: durationMs,
      exit_code: ok ? 0 : 1,
      is_terminal: true,
      ...(ok ? {} : { failure_reason: 'non_zero_exit' as const, error: 'Process exited with code 1' }),
    }
  }

  return null
}

/** Worker CPU/xotira ko'rsatkichlarini tabiiy tebrantiradi. */
function jitterWorkers(rng: Rng): void {
  for (const worker of allWorkers()) {
    if (worker.state === 'dead' || worker.state === 'stopped') continue

    // Kichik qadamlar — sakrash emas, tebranish
    const cpuDelta = rng.int(-7, 7)
    const memDelta = rng.int(-40, 40)
    const idle = worker.state === 'idle'

    workerStore.update(worker.id, {
      cpu: clamp(worker.cpu + cpuDelta, idle ? 4 : 25, idle ? 34 : 97),
      memory_mb: clamp(worker.memory_mb + memDelta, 90, worker.memory_limit_mb - 60),
      uptime_seconds: worker.uptime_seconds + TICK_MS / 1_000,
      last_heartbeat_at: new Date().toISOString(),
      // `starting` holatidagi worker bir necha tikdan keyin ishga tushadi
      ...(worker.state === 'starting' && rng.bool(0.5) ? { state: 'idle' as const } : {}),
    })
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, Math.round(value)))
}

function step(): void {
  tick += 1
  const rng = new Rng(Date.now() % 1_000_000)

  // 1) Tugallanmagan job'larni oldinga suramiz (bir tikda bir nechtasi)
  const active = allJobs().filter(
    (j) => j.status === 'pending' || j.status === 'queued' || j.status === 'running',
  )
  const moving = active.slice(0, rng.int(1, 3))
  for (const job of moving) {
    const patch = advanceJob(job, rng)
    if (patch) updateJob(job.id, patch)
  }

  // 2) Worker ko'rsatkichlari har tikda tebranadi
  jitterWorkers(rng)

  // 3) Har 3-tikda yangi job keladi — navbat bo'shab qolmasligi uchun
  if (tick % 3 === 0) {
    const template = allJobs().find((j) => j.is_terminal)
    if (template) {
      const now = new Date().toISOString()
      updateJob(template.id, {}) // to'plam o'zgarganini bildirish uchun
      void now
    }
  }

  notifyChanged()
}

/**
 * Simulyatsiyani ishga tushiradi.
 *
 * Qaytaradigan funksiya obunani bekor qiladi; oxirgi obunachi ketganda
 * taymer to'xtaydi (fonda behuda ishlamaydi).
 */
export function startSimulation(): () => void {
  subscribers += 1
  if (timer === null) {
    timer = setInterval(step, TICK_MS)
  }
  return () => {
    subscribers -= 1
    if (subscribers <= 0 && timer !== null) {
      clearInterval(timer)
      timer = null
      subscribers = 0
    }
  }
}
