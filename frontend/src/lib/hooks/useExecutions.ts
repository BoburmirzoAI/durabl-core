'use client'

/** Bajarish urinishlari ro'yxati. */

import { useQuery } from '@tanstack/react-query'

import type { ExecutionFilters } from '@/lib/api/executions.api'
import { executionsApi } from '@/lib/api'

import { QK } from './keys'

export function useExecutions(filters: ExecutionFilters) {
  return useQuery({
    queryKey: QK.executions.list(filters),
    queryFn: () => executionsApi.getExecutions(filters),
    placeholderData: (previous) => previous,
  })
}

export function useExecutionLogs(id: string | null) {
  return useQuery({
    queryKey: QK.executions.logs(id ?? ''),
    queryFn: () => executionsApi.getExecutionLogs(id as string),
    enabled: Boolean(id),
  })
}
