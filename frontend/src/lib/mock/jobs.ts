/**
 * Job mock generatori.
 *
 * 420 ta job yasaydi — "band tizim" taassuroti uchun yetarli, lekin
 * brauzerni sekinlashtirmaydi. Holatlar realistik taqsimlangan:
 * ko'pchiligi muvaffaqiyatli, oz qismi xato va DLQ'da.
 *
 * Hammasi DETERMINISTIK (`Rng`), shuning uchun sahifa qayta yuklanganda
 * ayni ma'lumot chiqadi va hydration xatosi bo'lmaydi.
 */

import type {
  Execution,
  ExecutionStatus,
  FailureReason,
  IdempotencyRequest,
  Job,
  JobIdempotency,
  JobLeaseHistory,
  JobLog,
  JobStatus,
  JobSummary,
  LeaseEvent,
  Priority,
  Runtime,
} from '@/types'

import {
  CODE_SAMPLES,
  ERROR_SAMPLES,
  IDEMPOTENCY_PREFIXES,
  LOG_LINES,
  REGIONS,
  RUNTIME_BANNER,
  TAGS,
} from './fixtures'
import { NOW, Rng, addMs } from './seed'
import { MockCollection } from './store'

/** Yasaladigan job soni. */
export const JOB_COUNT = 420

/**
 * Holat taqsimoti — og'irliklar realistik ishlab turgan tizimdan olingan:
 * 99.2% muvaffaqiyat (dizayndagi KPI) degani xatolar kam bo'lishi kerak,
 * lekin UI'ni sinash uchun har bir holatdan yetarlicha namuna kerak.
 */
const STATUS_WEIGHTS: readonly (readonly [JobStatus, number])[] = [
  ['success', 68],
  ['running', 6],
  ['queued', 5],
  ['pending', 4],
  ['failed', 7],
  ['retrying', 3],
  ['cancelled', 2],
  ['dead_letter', 5],
]

const PRIORITY_WEIGHTS: readonly (readonly [Priority, number])[] = [
  ['normal', 72],
  ['high', 20],
  ['low', 8],
]

const RUNTIME_WEIGHTS: readonly (readonly [Runtime, number])[] = [
  ['python', 64],
  ['node', 36],
]

function makeJobId(rng: Rng): string {
  return `job_${rng.hex(10)}`
}

function makeIdempotencyKey(rng: Rng): string | null {
  // Job'larning ~70% ida idempotency kaliti bor
  if (!rng.bool(0.7)) return null
  const prefix = rng.pick(IDEMPOTENCY_PREFIXES)
  return `${prefix}-${rng.int(1000, 99999)}`
}

/** Holatga mos davomiylik (ms) yoki `null` (hali boshlanmagan). */
function makeDuration(rng: Rng, status: JobStatus): number | null {
  if (status === 'pending' || status === 'queued') return null
  if (status === 'running') return null
  if (status === 'cancelled') return rng.int(80, 2_400)
  // Timeout'ga uchraganlar 30s atrofida
  if (rng.bool(0.08)) return rng.int(29_800, 30_200)
  // Asosiy massa: 40ms..6s, log-normal'ga o'xshash taqsimot
  const base = rng.float(0.04, 1)
  return Math.round(base * base * 6_000 + 40)
}

function makeExitCode(status: JobStatus, reason: FailureReason | null): number | null {
  if (status === 'success') return 0
  if (status === 'pending' || status === 'queued' || status === 'running') return null
  if (status === 'cancelled') return 143
  if (reason === 'timeout') return 143
  if (reason === 'out_of_memory') return 137
  return 1
}

interface GeneratedJob {
  job: Job
  executions: Execution[]
  logs: JobLog[]
}

function generateOne(index: number): GeneratedJob {
  const rng = new Rng(index * 7919 + 13)

  const status = rng.weighted(STATUS_WEIGHTS)
  const runtime = rng.weighted(RUNTIME_WEIGHTS)
  const priority = rng.weighted(PRIORITY_WEIGHTS)
  const sample = rng.pick(CODE_SAMPLES.filter((c) => c.runtime === runtime))
  const id = makeJobId(rng)

  const isFailure = status === 'failed' || status === 'dead_letter' || status === 'retrying'
  // Xato namunasi RUNTIME'ga mos bo'lishi shart: Python job'ining loglarida
  // JavaScript traceback'i chiqsa, ma'lumot ishonchsiz ko'rinadi.
  const errorSample = isFailure
    ? rng.pick(ERROR_SAMPLES.filter((e) => e.runtime === runtime || e.runtime === 'any'))
    : null
  const failureReason: FailureReason | null =
    status === 'dead_letter' && rng.bool(0.3)
      ? 'max_retries_exceeded'
      : (errorSample?.reason ?? null)

  const maxRetries = rng.weighted([
    [3, 60],
    [0, 15],
    [5, 15],
    [1, 10],
  ] as const)

  // Urinishlar soni: DLQ'ga tushganlar hammasini sarflagan
  const retryCount =
    status === 'dead_letter' ? maxRetries : status === 'retrying' ? rng.int(1, Math.max(1, maxRetries - 1)) : 0

  // Yangi job'lar yuqorida ko'rinishi uchun: index 0 — eng yangi
  const ageMinutes = Math.round((index + 1) * 2.4 + rng.float(0, 2))
  const createdAt = new Date(NOW - ageMinutes * 60_000).toISOString()

  const queueWaitMs = rng.int(12, 900)
  const queuedAt = status === 'pending' ? null : addMs(createdAt, queueWaitMs)
  const durationMs = makeDuration(rng, status)
  const startedAt = queuedAt && status !== 'queued' ? addMs(queuedAt, rng.int(20, 600)) : null
  const finishedAt =
    startedAt && durationMs !== null && status !== 'running' ? addMs(startedAt, durationMs) : null

  const exitCode = makeExitCode(status, failureReason)
  const tagCount = rng.weighted([
    [0, 30],
    [1, 40],
    [2, 25],
    [3, 5],
  ] as const)
  const tags = tagCount === 0 ? null : rng.shuffle(TAGS).slice(0, tagCount)

  // Oxirgi urinish worker'i — job sarlavhasi va loglar BIR XIL worker'ni
  // ko'rsatishi uchun shu qiymat ikkala joyda ishlatiladi.
  const workerId = startedAt ? `wkr-${String(rng.int(1, 6)).padStart(2, '0')}` : null
  // Uzluksiz bo'lak — ketma-ketlik buzilmaydi (shuffle QILINMAYDI)
  const stdoutLines = [RUNTIME_BANNER[runtime], ...LOG_LINES.slice(0, rng.int(3, 9))]

  const job: Job = {
    id,
    user_id: `usr_${rng.hex(8)}`,
    idempotency_key: makeIdempotencyKey(rng),
    runtime,
    priority,
    status,
    attempts_used: retryCount + 1,
    max_retries: maxRetries,
    retry_count: retryCount,
    duration_ms: durationMs,
    exit_code: exitCode,
    failure_reason: failureReason,
    created_at: createdAt,
    queued_at: queuedAt,
    started_at: startedAt,
    finished_at: finishedAt,
    tags,
    worker_id: workerId,
    is_terminal: status === 'success' || status === 'cancelled' || status === 'dead_letter',
    code: sample.code,
    payload: rng.bool(0.6) ? { args: [rng.int(1, 999)], kwargs: {} } : null,
    env_vars: rng.bool(0.25) ? { LOG_LEVEL: 'info', REGION: rng.pick(REGIONS) } : null,
    timeout_seconds: rng.pick([30, 30, 30, 60, 120, 300] as const),
    memory_mb: rng.bool(0.3) ? rng.pick([256, 512, 1024] as const) : null,
    cpus: rng.bool(0.2) ? rng.pick([0.5, 1, 2] as const) : null,
    scheduled_at: status === 'pending' && rng.bool(0.3) ? addMs(createdAt, rng.int(60_000, 3_600_000)) : null,
    cron_expression: rng.bool(0.06) ? '0 */4 * * *' : null,
    cancelled_at: status === 'cancelled' ? finishedAt : null,
    result:
      status === 'success' ? { value: { ok: true, processed: rng.int(1, 2_400) } } : null,
    stdout: startedAt ? `${stdoutLines.join('\n')}\n` : null,
    stderr: errorSample ? errorSample.traceback : null,
    error: errorSample ? `${errorSample.type}: ${errorSample.message}` : null,
    correlation_id: rng.hex(32),
  }

  // --- Urinishlar (executions) ---
  const executions: Execution[] = []
  const attemptTotal = retryCount + 1
  for (let attempt = 1; attempt <= attemptTotal; attempt += 1) {
    const isLast = attempt === attemptTotal
    const attemptStart = startedAt
      ? addMs(startedAt, (attempt - 1) * ((durationMs ?? 1_000) + rng.int(1_000, 4_000)))
      : null
    const attemptDuration = isLast ? durationMs : rng.int(200, 8_000)
    const attemptStatus: ExecutionStatus = isLast
      ? status === 'success'
        ? 'success'
        : status === 'running'
          ? 'running'
          : status === 'cancelled'
            ? 'cancelled'
            : failureReason === 'timeout'
              ? 'timeout'
              : failureReason === 'lease_lost'
                ? 'lost'
                : 'failed'
      : 'failed'

    executions.push({
      id: `exec_${rng.hex(10)}`,
      job_id: id,
      attempt_number: attempt,
      // Oxirgi urinish job sarlavhasidagi worker bilan bir xil bo'lishi SHART
      worker_id: attemptStart ? (isLast ? workerId : `wkr-${String(rng.int(1, 6)).padStart(2, '0')}`) : null,
      status: attemptStatus,
      started_at: attemptStart,
      finished_at: attemptStart && attemptDuration !== null ? addMs(attemptStart, attemptDuration) : null,
      duration_ms: attemptDuration,
      exit_code: isLast ? exitCode : 1,
      error_message: isLast
        ? (job.error ?? null)
        : `${errorSample?.type ?? 'RuntimeError'}: ${errorSample?.message ?? 'attempt failed'}`,
      failure_reason: attemptStatus === 'success' ? null : failureReason,
      stdout_bytes: rng.int(120, 8_400),
      stderr_bytes: errorSample ? rng.int(200, 2_000) : 0,
      lease_expires_at: attemptStatus === 'running' ? addMs(new Date(NOW).toISOString(), 15_000) : null,
    })
  }

  // --- Loglar (oxirgi urinish bo'yicha) ---
  const logs: JobLog[] = []
  const lastExec = executions[executions.length - 1]
  if (lastExec?.started_at) {
    let seq = 0
    const push = (stream: JobLog['stream'], content: string, offsetMs: number) => {
      logs.push({
        id: `log_${rng.hex(8)}_${seq}`,
        execution_id: lastExec.id,
        job_id: id,
        stream,
        content,
        sequence: seq,
        timestamp: addMs(lastExec.started_at as string, offsetMs),
      })
      seq += 1
    }
    // Vaqt siljishi TO'PLANIB boradi. Ilgari `40 + i * rng.int(30, 320)`
    // yozilgan edi — `rng.int` har iteratsiyada yangi son bergani uchun
    // vaqt goh oldinga, goh ORQAGA ketardi (log 18:37:08.800 dan keyin
    // 18:37:08.540 chiqardi).
    let offset = 0
    push('system', `worker ${lastExec.worker_id} claimed job (attempt ${lastExec.attempt_number})`, offset)
    stdoutLines.forEach((line) => {
      offset += rng.int(30, 320)
      push('stdout', line, offset)
    })
    if (errorSample) {
      errorSample.traceback.split('\n').forEach((line) => {
        offset += rng.int(8, 24)
        push('stderr', line, offset)
      })
      offset += rng.int(30, 120)
      push('system', `job failed with ${errorSample.type} (exit ${exitCode})`, offset)
    } else if (status === 'success') {
      offset += rng.int(30, 120)
      push('system', `job completed in ${durationMs}ms (exit 0)`, offset)
    }
  }

  return { job, executions, logs }
}

/**
 * Job to'plami — bir marta urug'dan quriladi, keyin O'ZGARTIRILADI.
 *
 * Amallar (bekor qilish, qayta urinish, yangi job) shu to'plamni haqiqatan
 * o'zgartiradi, shuning uchun ro'yxat qayta so'ralganda natija ko'rinadi.
 */
const collection = new MockCollection<GeneratedJob>(
  () => Array.from({ length: JOB_COUNT }, (_, i) => generateOne(i)),
  (d) => d.job.id,
)

function dataset(): GeneratedJob[] {
  return collection.raw()
}

/** Job maydonlarini yangilaydi (bekor qilish, holat o'zgarishi). */
export function updateJob(id: string, patch: Partial<Job>): Job | undefined {
  return collection.update(id, (d) => ({ job: { ...d.job, ...patch } }))?.job
}

/** Bir nechta job'ni birdan yangilaydi. */
export function updateJobs(ids: string[], patch: Partial<Job>): number {
  return collection.updateMany(ids, (d) => ({ job: { ...d.job, ...patch } }))
}

/** Yangi job qo'shadi (ro'yxat boshiga — eng yangisi tepada). */
export function insertJob(job: Job, executions: Execution[] = [], logs: JobLog[] = []): Job {
  collection.insert({ job, executions, logs })
  return job
}

/** Job'ni o'chiradi. */
export function removeJob(id: string): boolean {
  return collection.remove(id)
}

/** Job'ga yangi urinish (execution) qo'shadi — "Retry" amali uchun. */
export function appendExecution(jobId: string, execution: Execution): void {
  collection.update(jobId, (d) => ({ executions: [...d.executions, execution] }))
}

/** Job loglariga qator qo'shadi (jonli simulyatsiya uchun). */
export function appendJobLogs(jobId: string, entries: JobLog[]): void {
  collection.update(jobId, (d) => ({ logs: [...d.logs, ...entries] }))
}

export function allJobs(): Job[] {
  return dataset().map((d) => d.job)
}

export function allJobSummaries(): JobSummary[] {
  return dataset().map(({ job }) => {
    // `code`, `payload` va boshqa og'ir maydonlarni tashlab yuboramiz —
    // backend `JobSummary` ham aynan shunday yengil
    const {
      code: _code,
      payload: _payload,
      env_vars: _env,
      result: _result,
      stdout: _stdout,
      stderr: _stderr,
      error: _error,
      correlation_id: _cid,
      timeout_seconds: _timeout,
      memory_mb: _mem,
      cpus: _cpus,
      scheduled_at: _sched,
      cron_expression: _cron,
      cancelled_at: _cancelled,
      ...summary
    } = job
    return summary
  })
}

export function findJob(id: string): Job | undefined {
  return dataset().find((d) => d.job.id === id)?.job
}

export function jobExecutions(jobId: string): Execution[] {
  return dataset().find((d) => d.job.id === jobId)?.executions ?? []
}

export function jobLogs(jobId: string): JobLog[] {
  return dataset().find((d) => d.job.id === jobId)?.logs ?? []
}

export function allExecutions(): Execution[] {
  return dataset().flatMap((d) => d.executions)
}

/** Holat bo'yicha sanoq (dashboard va analitika uchun). */
export function statusCounts(): Record<JobStatus, number> {
  const counts = {
    pending: 0,
    queued: 0,
    running: 0,
    success: 0,
    failed: 0,
    retrying: 0,
    cancelled: 0,
    dead_letter: 0,
  } satisfies Record<JobStatus, number>
  for (const { job } of dataset()) counts[job.status] += 1
  return counts
}

// ---------------------------------------------------------------------------
// Ishonchlilik ko'rinishi — lease/heartbeat va idempotency
// ---------------------------------------------------------------------------

/** Lease TTL va heartbeat davri — backend `config.py` bilan bir xil. */
const LEASE_TTL_SECONDS = 15
const HEARTBEAT_INTERVAL_SECONDS = 5

/**
 * Job uchun lease hodisalari tarixi.
 *
 * Har bir urinish uchun: egallash -> bir necha yangilash -> yakun.
 * Yakun urinish holatiga qarab farq qiladi:
 *
 * * `success`/`failed` -> `released` (worker o'zi qo'yib yubordi);
 * * `lost`             -> `expired` + `reaped` (heartbeat to'xtadi, reaper
 *   lease'ni yig'di va job boshqa worker'ga o'tdi) — bu bizning
 *   "worker o'lsa job yo'qolmaydi" va'damizni KO'RINADIGAN qiladi.
 */
export function jobLeaseHistory(jobId: string): JobLeaseHistory | undefined {
  const entry = collection.find(jobId)
  if (!entry) return undefined

  const events: LeaseEvent[] = []
  let renewals = 0
  let reassignments = 0

  for (const execution of entry.executions) {
    if (!execution.started_at || !execution.worker_id) continue

    const rng = new Rng(hashString(execution.id))
    const startMs = new Date(execution.started_at).getTime()
    const durationMs = execution.duration_ms ?? 2_000
    const workerId = execution.worker_id

    const push = (
      kind: LeaseEvent['kind'],
      offsetMs: number,
      note: string | null,
      previousMs: number | null,
    ): void => {
      events.push({
        id: `lease_${execution.id}_${events.length}`,
        execution_id: execution.id,
        attempt_number: execution.attempt_number,
        kind,
        worker_id: workerId,
        at: addMs(execution.started_at as string, offsetMs),
        expires_at:
          kind === 'expired' || kind === 'released' || kind === 'reaped'
            ? null
            : addMs(execution.started_at as string, offsetMs + LEASE_TTL_SECONDS * 1_000),
        since_previous_ms: previousMs,
        note,
      })
    }

    push('acquired', 0, `${workerId} claimed the job · lease ${LEASE_TTL_SECONDS}s`, null)

    // Heartbeat har 5 soniyada — bajarilish davomiyligiga qarab
    const beats = Math.max(0, Math.floor(durationMs / (HEARTBEAT_INTERVAL_SECONDS * 1_000)))
    let previous = 0
    for (let i = 1; i <= Math.min(beats, 12); i += 1) {
      const at = i * HEARTBEAT_INTERVAL_SECONDS * 1_000 + rng.int(-200, 200)
      push('renewed', at, `heartbeat — lease extended by another ${LEASE_TTL_SECONDS}s`, at - previous)
      previous = at
      renewals += 1
    }

    if (execution.status === 'lost') {
      const expiredAt = previous + LEASE_TTL_SECONDS * 1_000
      push(
        'expired',
        expiredAt,
        `no heartbeat for ${LEASE_TTL_SECONDS}s — lease expired`,
        expiredAt - previous,
      )
      push('reaped', expiredAt + rng.int(500, 4_000), 'reaper re-queued the job', null)
      reassignments += 1
    } else if (execution.finished_at) {
      push('released', durationMs, `attempt finished: ${execution.status}`, durationMs - previous)
    }
    void startMs
  }

  return {
    job_id: jobId,
    events,
    ttl_seconds: LEASE_TTL_SECONDS,
    heartbeat_interval_seconds: HEARTBEAT_INTERVAL_SECONDS,
    total_renewals: renewals,
    reassignments,
  }
}

/** Matndan barqaror son — deterministik `Rng` urug'i uchun. */
function hashString(value: string): number {
  let h = 0
  for (let i = 0; i < value.length; i += 1) {
    h = (h * 31 + value.charCodeAt(i)) % 2_147_483_647
  }
  return h
}

/**
 * Job uchun idempotency ma'lumoti.
 *
 * Kalit yo'q bo'lsa — bo'sh tarix (har so'rov yangi job). Kalit bor bo'lsa,
 * deterministik ravishda 1–3 so'rov yasaladi: birinchisi `created`,
 * keyingilari `deduplicated` (va ba'zan `conflict` — boshqa tana bilan).
 */
export function jobIdempotency(jobId: string): JobIdempotency | undefined {
  const entry = collection.find(jobId)
  if (!entry) return undefined
  const job = entry.job

  if (!job.idempotency_key) {
    return {
      job_id: jobId,
      key: null,
      fingerprint: null,
      was_deduplicated: false,
      expires_at: null,
      requests: [],
    }
  }

  const rng = new Rng(hashString(job.idempotency_key))
  const extra = rng.weighted([
    [0, 55],
    [1, 30],
    [2, 15],
  ] as const)

  const requests: IdempotencyRequest[] = [
    {
      at: job.created_at,
      status_code: 201,
      outcome: 'created',
      source: rng.pick(['durabl-python/1.2.0', 'durabl-js/1.1.0', 'curl/8.4.0', 'dashboard']),
      request_id: `req_${rng.hex(12)}`,
    },
  ]

  for (let i = 0; i < extra; i += 1) {
    // Oxirgi so'rov ba'zan ziddiyat bo'ladi — mijoz tanani o'zgartirib yuborgan
    const conflict = i === extra - 1 && rng.bool(0.25)
    requests.push({
      at: addMs(job.created_at, (i + 1) * rng.int(80, 2_400)),
      status_code: conflict ? 409 : 200,
      outcome: conflict ? 'conflict' : 'deduplicated',
      source: rng.pick(['durabl-python/1.2.0', 'durabl-js/1.1.0', 'curl/8.4.0']),
      request_id: `req_${rng.hex(12)}`,
    })
  }

  return {
    job_id: jobId,
    key: job.idempotency_key,
    fingerprint: `sha256:${rng.hex(16)}…`,
    was_deduplicated: extra > 0,
    // Redis yozuvi 24 soat yashaydi
    expires_at: addMs(job.created_at, 24 * 3_600_000),
    requests,
  }
}
