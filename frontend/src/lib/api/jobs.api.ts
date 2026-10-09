/**
 * Job endpointlari.
 *
 * Har bir funksiyaning tepasida backend yo'li izohda ko'rsatilgan — ulanish
 * paytida `mockResponse(...)` ni `request(...)` ga almashtirish kifoya.
 */

import type {
  Execution,
  Job,
  JobCreateInput,
  JobFilters,
  JobIdempotency,
  JobLeaseHistory,
  JobLog,
  JobResult,
  JobSummary,
  JobTimeline,
  JobTimelineStep,
  Paginated,
  Priority,
} from '@/types'
import {
  allJobSummaries,
  appendExecution,
  findJob,
  insertJob,
  jobExecutions,
  jobIdempotency,
  jobLeaseHistory,
  jobLogs,
  removeJob,
  updateJob,
  updateJobs,
} from '@/lib/mock/jobs'
import { diffMs } from '@/lib/utils/time'

import { ApiError, mockResponse, notFound } from './client'
import { DEFAULT_PAGE_SIZE, filterByAny, filterByRange, paginate, searchIn, sortBy } from './paginate'

/** `GET /api/v1/jobs` — filtrlangan, tartiblangan, sahifalangan ro'yxat. */
export async function getJobs(filters: JobFilters = {}): Promise<Paginated<JobSummary>> {
  return mockResponse(() => {
    let rows = allJobSummaries()
    rows = searchIn(rows, filters.search, ['id', 'idempotency_key', 'worker_id'])
    rows = filterByAny(rows, filters.status, (j) => j.status)
    rows = filterByAny(rows, filters.runtime, (j) => j.runtime)
    rows = filterByAny(rows, filters.priority, (j) => j.priority)
    rows = filterByRange(rows, filters.range, (j) => j.created_at)
    rows = sortBy(rows, filters.sort_by ?? 'created_at', filters.sort_order ?? 'desc')
    return paginate(rows, filters.page ?? 1, filters.page_size ?? DEFAULT_PAGE_SIZE)
  })
}

/** `GET /api/v1/jobs/{id}` */
export async function getJob(id: string): Promise<Job> {
  return mockResponse(() => {
    const job = findJob(id)
    if (!job) throw notFound('Job', id)
    return job
  })
}

/** `GET /api/v1/jobs/{id}/logs` */
export async function getJobLogs(id: string): Promise<JobLog[]> {
  return mockResponse(() => {
    if (!findJob(id)) throw notFound('Job', id)
    return jobLogs(id)
  })
}

/** `GET /api/v1/executions?job_id={id}` — job'ning barcha urinishlari. */
export async function getJobExecutions(id: string): Promise<Execution[]> {
  return mockResponse(() => {
    if (!findJob(id)) throw notFound('Job', id)
    return jobExecutions(id)
  })
}

/** `GET /api/v1/jobs/{id}/result` */
export async function getJobResult(id: string): Promise<JobResult> {
  return mockResponse(() => {
    const job = findJob(id)
    if (!job) throw notFound('Job', id)
    if (!job.is_terminal) {
      throw new ApiError({
        status: 409,
        code: 'RESULT_NOT_READY',
        message: `The job has not finished yet (status: ${job.status})`,
        details: { status: job.status },
      })
    }
    return {
      id: job.id,
      status: job.status,
      exit_code: job.exit_code,
      stdout: job.stdout,
      stderr: job.stderr,
      result: job.result?.value ?? null,
      duration_ms: job.duration_ms,
      error: job.error,
      failure_reason: job.failure_reason,
    }
  })
}

/**
 * `GET /api/v1/jobs/{id}/timeline` — hayot sikli qadamlari.
 *
 * Qadamlar job vaqt belgilaridan hisoblanadi; oldingi qadamdan o'tgan vaqt
 * (`gap_ms`) dizayndagi `+1.2s` yorlig'iga aylanadi.
 */
export async function getJobTimeline(id: string): Promise<JobTimeline> {
  return mockResponse(() => {
    const job = findJob(id)
    if (!job) throw notFound('Job', id)

    const isFailure = job.status === 'failed' || job.status === 'dead_letter'
    const steps: JobTimelineStep[] = [
      {
        key: 'submitted',
        label: 'Submitted',
        timestamp: job.created_at,
        gap_ms: null,
        state: 'done',
      },
      {
        key: 'queued',
        label: 'Queued',
        timestamp: job.queued_at,
        gap_ms: diffMs(job.created_at, job.queued_at),
        state: job.queued_at ? 'done' : 'pending',
      },
      {
        key: 'running',
        label: 'Running',
        timestamp: job.started_at,
        gap_ms: diffMs(job.queued_at, job.started_at),
        state: job.started_at ? (job.status === 'running' ? 'current' : 'done') : 'pending',
      },
      {
        key: 'finished',
        label: isFailure ? 'Failed' : job.status === 'cancelled' ? 'Cancelled' : 'Completed',
        timestamp: job.finished_at,
        gap_ms: diffMs(job.started_at, job.finished_at),
        state: job.finished_at ? (isFailure ? 'error' : 'done') : 'pending',
      },
    ]

    // DLQ qadami faqat job o'sha yerga tushganda ko'rinadi
    if (job.status === 'dead_letter') {
      steps.push({
        key: 'dlq',
        label: 'Dead letter',
        timestamp: job.finished_at,
        gap_ms: 0,
        state: 'error',
      })
    }

    return {
      job_id: job.id,
      steps,
      queue_wait_ms: diffMs(job.created_at, job.started_at),
      execution_ms: job.duration_ms,
      total_ms: diffMs(job.created_at, job.finished_at),
    }
  })
}

/** `POST /api/v1/jobs` — yangi job yuborish. */
export async function createJob(input: JobCreateInput): Promise<Job> {
  return mockResponse(() => {
    // Namuna sifatida mavjud job olinadi (barcha maydonlar to'liq bo'lishi
    // uchun), so'ng YANGI job ro'yxat boshiga QO'SHILADI — shuning uchun u
    // jadvalda darhol ko'rinadi va detal sahifasi ham ishlaydi.
    const template = allJobSummaries()[0]
    const base = template ? findJob(template.id) : undefined
    if (!base) throw notFound('Job', 'template')
    const now = new Date().toISOString()
    const job: Job = {
      ...base,
      id: `job_${Math.random().toString(16).slice(2, 12)}`,
      code: input.code,
      runtime: input.runtime,
      priority: input.priority ?? 'normal',
      status: 'queued',
      payload: input.payload ?? null,
      timeout_seconds: input.timeout_seconds ?? 30,
      max_retries: input.max_retries ?? 3,
      retry_count: 0,
      attempts_used: 1,
      tags: input.tags ?? null,
      idempotency_key: input.idempotency_key ?? null,
      created_at: now,
      queued_at: now,
      started_at: null,
      finished_at: null,
      duration_ms: null,
      exit_code: null,
      error: null,
      failure_reason: null,
      stdout: null,
      stderr: null,
      result: null,
      is_terminal: false,
      worker_id: null,
      correlation_id: `cor_${Math.random().toString(16).slice(2, 10)}`,
      cancelled_at: null,
      scheduled_at: null,
    }
    insertJob(job)
    return job
  }, 400)
}

/** `POST /api/v1/jobs/{id}/cancel` */
export async function cancelJob(id: string): Promise<Job> {
  return mockResponse(() => {
    const job = findJob(id)
    if (!job) throw notFound('Job', id)
    if (job.is_terminal) {
      throw new ApiError({
        status: 409,
        code: 'JOB_NOT_CANCELLABLE',
        message: `The job is '${job.status}' — it can no longer be cancelled`,
        details: { status: job.status },
      })
    }
    const now = new Date().toISOString()
    const next = updateJob(id, {
      status: 'cancelled',
      cancelled_at: now,
      finished_at: now,
      is_terminal: true,
    })
    return next ?? job
  }, 300)
}

/** `POST /api/v1/jobs/{id}/resubmit` — ayni kod bilan yangi job. */
export async function resubmitJob(id: string): Promise<Job> {
  return mockResponse(() => {
    const job = findJob(id)
    if (!job) throw notFound('Job', id)
    const now = new Date().toISOString()
    const attempt = job.attempts_used + 1

    // Yangi urinish "Attempts" jadvalida darhol ko'rinishi uchun qo'shiladi
    appendExecution(id, {
      id: `exec_${Math.random().toString(16).slice(2, 12)}`,
      job_id: id,
      attempt_number: attempt,
      worker_id: null,
      status: 'pending',
      started_at: null,
      finished_at: null,
      duration_ms: null,
      exit_code: null,
      error_message: null,
      failure_reason: null,
      stdout_bytes: 0,
      stderr_bytes: 0,
      lease_expires_at: null,
    })

    const next = updateJob(id, {
      status: 'queued',
      retry_count: job.retry_count + 1,
      attempts_used: attempt,
      queued_at: now,
      started_at: null,
      finished_at: null,
      duration_ms: null,
      exit_code: null,
      error: null,
      failure_reason: null,
      is_terminal: false,
    })
    return next ?? job
  }, 300)
}

/** `POST /api/v1/jobs/{id}/retry` — DLQ'dan yoki xatodan qayta urinish. */
export async function retryJob(id: string): Promise<Job> {
  return resubmitJob(id)
}

/** Ommaviy bekor qilish (UI bulk amali). Faqat BEKOR QILSA BO'LADIGANLARI. */
export async function cancelJobs(ids: string[]): Promise<{ cancelled: number }> {
  return mockResponse(() => {
    const cancellable = ids.filter((id) => {
      const job = findJob(id)
      return job !== undefined && !job.is_terminal
    })
    const now = new Date().toISOString()
    const cancelled = updateJobs(cancellable, {
      status: 'cancelled',
      cancelled_at: now,
      finished_at: now,
      is_terminal: true,
    })
    return { cancelled }
  }, 400)
}

/** Ommaviy qayta urinish. Faqat TUGAGAN (terminal) job'lar qayta urinadi. */
export async function retryJobs(ids: string[]): Promise<{ retried: number }> {
  return mockResponse(() => {
    const retryable = ids.filter((id) => findJob(id)?.is_terminal === true)
    const now = new Date().toISOString()
    const retried = updateJobs(retryable, {
      status: 'queued',
      queued_at: now,
      started_at: null,
      finished_at: null,
      duration_ms: null,
      exit_code: null,
      error: null,
      failure_reason: null,
      is_terminal: false,
    })
    return { retried }
  }, 400)
}

/** `DELETE /api/v1/jobs/{id}` — job yozuvini o'chirish. */
export async function deleteJob(id: string): Promise<{ deleted: boolean }> {
  return mockResponse(() => {
    if (!findJob(id)) throw notFound('Job', id)
    return { deleted: removeJob(id) }
  }, 300)
}

/**
 * `GET /api/v1/jobs/{id}/lease-history`
 *
 * Lease egallash/yangilash/tugash hodisalari. Bu bizning "worker o'lsa job
 * yo'qolmaydi" va'damizni KO'RINADIGAN qiladi: foydalanuvchi heartbeat
 * qanday ishlaganini va job qayta taqsimlanganini o'z ko'zi bilan ko'radi.
 */
export async function getJobLeaseHistory(id: string): Promise<JobLeaseHistory> {
  return mockResponse(() => {
    const history = jobLeaseHistory(id)
    if (!history) throw notFound('Job', id)
    return history
  })
}

/**
 * `GET /api/v1/jobs/{id}/idempotency`
 *
 * Shu job qaysi kalit bilan yaratilgani va o'sha kalit bilan kelgan
 * boshqa so'rovlar — "men ikki marta yubordimmi?" savoliga javob.
 */
export async function getJobIdempotency(id: string): Promise<JobIdempotency> {
  return mockResponse(() => {
    const info = jobIdempotency(id)
    if (!info) throw notFound('Job', id)
    return info
  })
}

// ───────────────────────────────────────────────────────────────────────────
// Admin amallari
// ───────────────────────────────────────────────────────────────────────────

/**
 * `POST /api/v1/admin/jobs/{id}/force-fail`
 *
 * ## Nega bu `cancel` dan FARQ qiladi
 *
 * Bekor qilish — foydalanuvchining qarori: "bu ish endi kerak emas".
 * Majburiy yiqitish — operatorning qarori: "bu ish yo'qolib ketgan".
 * Natija ham boshqacha:
 *
 * - `cancelled` — statistikada muvaffaqiyatsizlik DEB HISOBLANMAYDI,
 *   qayta urinilmaydi, DLQ'ga tushmaydi.
 * - `failed` — urinishlar tugagan bo'lsa DLQ'ga tushadi, muvaffaqiyat
 *   foiziga ta'sir qiladi, `failure_reason` yoziladi.
 *
 * Ilgari bu tugma `cancelJob` ni chaqirardi va yorlig'i yolg'on edi.
 */
export async function forceFailJob(id: string, reason?: string): Promise<Job> {
  return mockResponse(() => {
    const job = findJob(id)
    if (!job) throw notFound('Job', id)
    if (job.is_terminal) {
      throw new ApiError({
        status: 409,
        code: 'JOB_ALREADY_TERMINAL',
        message: `The job is '${job.status}' — it has already finished`,
        details: { status: job.status },
      })
    }
    const now = new Date().toISOString()
    // Urinishlar tugagan bo'lsa DLQ'ga tushadi — aynan haqiqiy oqim shunday
    const exhausted = job.attempts_used >= job.max_retries
    return (
      updateJob(id, {
        status: exhausted ? 'dead_letter' : 'failed',
        failure_reason: 'lease_lost',
        error: reason?.trim() || 'Force-failed by an administrator',
        finished_at: now,
        is_terminal: true,
      }) ?? job
    )
  }, 450)
}

/**
 * `PUT /api/v1/admin/jobs/{id}/priority`
 *
 * Navbat band bo'lganda operator muhim ishni oldinga surishi kerak.
 * Ishlab turgan job'ning prioriteti o'zgartirilmaydi — u allaqachon
 * worker'da, prioritet esa faqat NAVBATdan olishga ta'sir qiladi.
 */
export async function setJobPriority(id: string, priority: Priority): Promise<Job> {
  return mockResponse(() => {
    const job = findJob(id)
    if (!job) throw notFound('Job', id)
    if (job.status !== 'queued' && job.status !== 'retrying') {
      throw new ApiError({
        status: 409,
        code: 'NOT_QUEUED',
        message: 'Priority can only be changed while a job is queued',
        details: { status: job.status },
      })
    }
    return updateJob(id, { priority }) ?? job
  }, 350)
}

/**
 * `POST /api/v1/admin/jobs/{id}/reassign`
 *
 * Job'ni boshqa worker'ga o'tkazadi: joriy lease bekor qilinadi va job
 * navbatga qaytariladi. Aniq worker ko'rsatilsa, u o'sha worker'ga
 * biriktiriladi.
 *
 * `worker_id = null` — shunchaki navbatga qaytarish (eng keng tarqalgan
 * holat: worker javob bermay qoldi, lekin lease hali tugamagan).
 */
export async function reassignJob(id: string, workerId: string | null): Promise<Job> {
  return mockResponse(() => {
    const job = findJob(id)
    if (!job) throw notFound('Job', id)
    if (job.is_terminal) {
      throw new ApiError({
        status: 409,
        code: 'JOB_TERMINAL',
        message: 'A finished job cannot be reassigned',
        details: { status: job.status },
      })
    }
    return (
      updateJob(id, {
        status: 'queued',
        worker_id: workerId,
        started_at: null,
      }) ?? job
    )
  }, 450)
}
