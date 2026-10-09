/** Jadval va shablon endpointlari. */

import type {
  CronParseResult,
  JobTemplate,
  Paginated,
  Schedule,
  ScheduleCreateInput,
  ScheduleFilters,
  ScheduleRun,
  TemplateCreateInput,
} from '@/types'
import {
  allSchedules,
  allTemplates,
  findSchedule,
  scheduleRuns,
  scheduleStore,
  templateStore,
} from '@/lib/mock/schedules'
import { CronError, describeCron, nextCronRuns, runsPerDay } from '@/lib/utils/cron'
import { Rng } from '@/lib/mock/seed'

import { ApiError, mockResponse, notFound } from './client'
import { DEFAULT_PAGE_SIZE, filterByAny, paginate, searchIn, sortBy } from './paginate'

// ───────────────────────────────────────────────────────────────────────────
// Jadvallar
// ───────────────────────────────────────────────────────────────────────────

/** `GET /api/v1/schedules` */
export async function getSchedules(filters: ScheduleFilters = {}): Promise<Paginated<Schedule>> {
  return mockResponse(() => {
    let rows = allSchedules()
    rows = searchIn(rows, filters.search, ['name', 'description', 'cron'])
    rows = filterByAny(rows, filters.status, (s) => s.status)
    rows = sortBy(rows, filters.sort_by ?? 'next_run_at', filters.sort_order ?? 'asc')
    return paginate(rows, filters.page ?? 1, filters.page_size ?? DEFAULT_PAGE_SIZE)
  })
}

/** `GET /api/v1/schedules/{id}` */
export async function getSchedule(id: string): Promise<Schedule> {
  return mockResponse(() => {
    const schedule = findSchedule(id)
    if (!schedule) throw notFound('Schedule', id)
    return schedule
  })
}

/** `GET /api/v1/schedules/{id}/runs` */
export async function getScheduleRuns(id: string): Promise<ScheduleRun[]> {
  return mockResponse(() => {
    if (!findSchedule(id)) throw notFound('Schedule', id)
    return scheduleRuns(id)
  }, 380)
}

/**
 * `POST /api/v1/schedules/{id}/pause` va `/resume`
 *
 * Pauza faqat holatni emas, `next_run_at` ni ham tozalaydi: aks holda
 * jadval "to'xtatilgan" deb yozilib turib, keyingi ishga tushish vaqtini
 * ko'rsatardi.
 */
export async function setScheduleEnabled(id: string, enabled: boolean): Promise<Schedule> {
  return mockResponse(() => {
    const schedule = findSchedule(id)
    if (!schedule) throw notFound('Schedule', id)
    return (
      scheduleStore.update(id, {
        status: enabled ? 'active' : 'paused',
        next_run_at: enabled
          ? (nextCronRuns(schedule.cron, 1)[0]?.toISOString() ?? null)
          : null,
        // Qayta yoqish xatolar hisobini nollaydi — aks holda jadval
        // darhol yana "errored" ga tushib qolardi
        consecutive_failures: enabled ? 0 : schedule.consecutive_failures,
      }) ?? schedule
    )
  }, 350)
}

/** `POST /api/v1/schedules/{id}/run-now` — jadvaldan tashqari bir marta. */
export async function runScheduleNow(id: string): Promise<{ job_id: string }> {
  return mockResponse(() => {
    const schedule = findSchedule(id)
    if (!schedule) throw notFound('Schedule', id)
    const rng = new Rng(Date.now() % 800_011)
    scheduleStore.update(id, {
      last_run_at: new Date().toISOString(),
      last_run_status: 'running',
      total_runs: schedule.total_runs + 1,
    })
    return { job_id: `job_${rng.hex(10)}` }
  }, 600)
}

export interface SchedulePatch {
  name?: string
  description?: string | null
  cron?: string
  priority?: Schedule['priority']
  allow_overlap?: boolean
  timeout_seconds?: number
  max_retries?: number
}

/** `PUT /api/v1/schedules/{id}` */
export async function updateSchedule(id: string, patch: SchedulePatch): Promise<Schedule> {
  return mockResponse(() => {
    const schedule = findSchedule(id)
    if (!schedule) throw notFound('Schedule', id)
    if (patch.cron !== undefined) {
      try {
        describeCron(patch.cron)
      } catch (error) {
        throw new ApiError({
          status: 422,
          code: 'INVALID_CRON',
          message: error instanceof CronError ? error.message : 'That cron expression is not valid',
        })
      }
    }
    return (
      scheduleStore.update(id, {
        ...patch,
        updated_at: new Date().toISOString(),
        ...(patch.cron !== undefined && schedule.status !== 'paused'
          ? { next_run_at: nextCronRuns(patch.cron, 1)[0]?.toISOString() ?? null }
          : {}),
      }) ?? schedule
    )
  }, 420)
}

/** `POST /api/v1/schedules` */
export async function createSchedule(input: ScheduleCreateInput): Promise<Schedule> {
  return mockResponse(() => {
    try {
      describeCron(input.cron)
    } catch (error) {
      throw new ApiError({
        status: 422,
        code: 'INVALID_CRON',
        message: error instanceof CronError ? error.message : 'That cron expression is not valid',
      })
    }
    if (input.name.trim().length === 0) {
      throw new ApiError({ status: 422, code: 'NAME_REQUIRED', message: 'A name is required' })
    }
    const rng = new Rng(Date.now() % 900_007)
    const now = new Date().toISOString()
    const schedule: Schedule = {
      id: `sch_${rng.hex(10)}`,
      name: input.name.trim(),
      description: input.description?.trim() || null,
      cron: input.cron.trim(),
      timezone: input.timezone,
      runtime: input.runtime,
      priority: input.priority,
      status: 'active',
      allow_overlap: input.allow_overlap,
      timeout_seconds: input.timeout_seconds,
      max_retries: input.max_retries,
      created_at: now,
      updated_at: now,
      last_run_at: null,
      last_run_status: null,
      next_run_at: nextCronRuns(input.cron, 1)[0]?.toISOString() ?? null,
      consecutive_failures: 0,
      total_runs: 0,
      failed_runs: 0,
    }
    scheduleStore.insert(schedule)
    return schedule
  }, 600)
}

/** `DELETE /api/v1/schedules/{id}` */
export async function deleteSchedule(id: string): Promise<{ deleted: boolean }> {
  return mockResponse(() => {
    if (!findSchedule(id)) throw notFound('Schedule', id)
    scheduleStore.remove(id)
    return { deleted: true }
  }, 400)
}

/**
 * `POST /api/v1/schedules/validate-cron`
 *
 * Tahlil MIJOZDA ham bo'lishi mumkin edi, lekin endpoint shaklida
 * saqlanadi: backend ulanganda cron semantikasi bitta joyda — serverda
 * hal qilinishi kerak, aks holda UI "ishlaydi" deb ko'rsatib, server
 * rad etadigan holat yuzaga keladi.
 */
export async function validateCron(expression: string): Promise<CronParseResult> {
  return mockResponse(() => {
    try {
      return {
        valid: true,
        description: describeCron(expression),
        error: null,
        next_runs: nextCronRuns(expression, 5).map((d) => d.toISOString()),
        runs_per_day: runsPerDay(expression),
      }
    } catch (error) {
      return {
        valid: false,
        description: '',
        error: error instanceof Error ? error.message : 'Invalid cron expression',
        next_runs: [],
        runs_per_day: 0,
      }
    }
  }, 120)
}

// ───────────────────────────────────────────────────────────────────────────
// Shablonlar
// ───────────────────────────────────────────────────────────────────────────

/** `GET /api/v1/templates` */
export async function getTemplates(): Promise<JobTemplate[]> {
  return mockResponse(() => allTemplates(), 300)
}

/** `GET /api/v1/templates/{id}` */
export async function getTemplate(id: string): Promise<JobTemplate> {
  return mockResponse(() => {
    const template = allTemplates().find((t) => t.id === id)
    if (!template) throw notFound('Template', id)
    return template
  })
}

/** `POST /api/v1/templates` */
export async function createTemplate(input: TemplateCreateInput): Promise<JobTemplate> {
  return mockResponse(() => {
    if (input.name.trim().length === 0) {
      throw new ApiError({ status: 422, code: 'NAME_REQUIRED', message: 'A name is required' })
    }
    const rng = new Rng(Date.now() % 700_021)
    const template: JobTemplate = {
      id: `tpl_${rng.hex(10)}`,
      ...input,
      name: input.name.trim(),
      is_builtin: false,
      use_count: 0,
      created_at: new Date().toISOString(),
      last_used_at: null,
    }
    templateStore.insert(template)
    return template
  }, 500)
}

/** `DELETE /api/v1/templates/{id}` */
export async function deleteTemplate(id: string): Promise<{ deleted: boolean }> {
  return mockResponse(() => {
    const template = allTemplates().find((t) => t.id === id)
    if (!template) throw notFound('Template', id)
    if (template.is_builtin) {
      throw new ApiError({
        status: 409,
        code: 'BUILTIN_TEMPLATE',
        message: 'A built-in template cannot be deleted — make a copy instead',
      })
    }
    templateStore.remove(id)
    return { deleted: true }
  }, 400)
}

/** Shablondan foydalanilganini qayd etadi (`use_count`). */
export async function markTemplateUsed(id: string): Promise<JobTemplate> {
  return mockResponse(() => {
    const template = allTemplates().find((t) => t.id === id)
    if (!template) throw notFound('Template', id)
    return (
      templateStore.update(id, {
        use_count: template.use_count + 1,
        last_used_at: new Date().toISOString(),
      }) ?? template
    )
  }, 150)
}
