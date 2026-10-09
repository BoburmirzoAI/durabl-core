/** Bajarish (execution) endpointlari. */

import type { Execution, JobLog, ListParams, Paginated } from '@/types'
import { allExecutions, jobLogs } from '@/lib/mock/jobs'

import { mockResponse, notFound } from './client'
import { DEFAULT_PAGE_SIZE, filterByAny, paginate, searchIn, sortBy } from './paginate'

export interface ExecutionFilters extends ListParams {
  search?: string
  status?: Execution['status'][]
  job_id?: string
}

/** `GET /api/v1/executions` */
export async function getExecutions(filters: ExecutionFilters = {}): Promise<Paginated<Execution>> {
  return mockResponse(() => {
    let rows = allExecutions()
    if (filters.job_id) rows = rows.filter((e) => e.job_id === filters.job_id)
    rows = searchIn(rows, filters.search, ['id', 'job_id', 'worker_id'])
    rows = filterByAny(rows, filters.status, (e) => e.status)
    rows = sortBy(rows, filters.sort_by ?? 'started_at', filters.sort_order ?? 'desc')
    return paginate(rows, filters.page ?? 1, filters.page_size ?? DEFAULT_PAGE_SIZE)
  })
}

/** `GET /api/v1/executions/{id}` */
export async function getExecution(id: string): Promise<Execution> {
  return mockResponse(() => {
    const row = allExecutions().find((e) => e.id === id)
    if (!row) throw notFound('Execution', id)
    return row
  })
}

/** `GET /api/v1/executions/{id}/logs` */
export async function getExecutionLogs(id: string): Promise<JobLog[]> {
  return mockResponse(() => {
    const row = allExecutions().find((e) => e.id === id)
    if (!row) throw notFound('Execution', id)
    return jobLogs(row.job_id).filter((l) => l.execution_id === id)
  })
}
