'use client'

import { create } from 'zustand'

import type { DlqGroupBy, JobStatus, Priority, Runtime, SortOrder } from '@/types'

/**
 * Jadval filtrlari holati.
 *
 * Nega global store: foydalanuvchi job detaliga kirib, orqaga qaytganda
 * filtrlari saqlanib turishi kerak. URL bilan sinxronlash ham shu yerdan
 * (`toSearchParams` / `applySearchParams`).
 */
export interface JobFilterState {
  search: string
  status: JobStatus[]
  runtime: Runtime[]
  priority: Priority[]
  range: string
  page: number
  pageSize: number
  sortBy: string
  sortOrder: SortOrder
}

const INITIAL_JOB_FILTERS: JobFilterState = {
  search: '',
  status: [],
  runtime: [],
  priority: [],
  range: 'all',
  page: 1,
  pageSize: 25,
  sortBy: 'created_at',
  sortOrder: 'desc',
}

interface FilterState {
  jobs: JobFilterState
  setJobFilter: <K extends keyof JobFilterState>(key: K, value: JobFilterState[K]) => void
  /** Filtrni almashtiradi (ko'p tanlovli chiplar uchun). */
  toggleJobStatus: (status: JobStatus) => void
  toggleJobRuntime: (runtime: Runtime) => void
  resetJobFilters: () => void
  /** Ustun sarlavhasi bosilganda tartibni almashtiradi. */
  toggleJobSort: (field: string) => void

  dlqGroupBy: DlqGroupBy
  dlqSearch: string
  dlqResolved: boolean | undefined
  dlqPage: number
  setDlqGroupBy: (group: DlqGroupBy) => void
  setDlqSearch: (search: string) => void
  setDlqResolved: (resolved: boolean | undefined) => void
  setDlqPage: (page: number) => void
  resetDlqFilters: () => void
}

/** Filtr o'zgarsa sahifa 1'ga qaytishi kerak — aks holda bo'sh sahifa chiqadi. */
const RESETS_PAGE: readonly (keyof JobFilterState)[] = [
  'search',
  'status',
  'runtime',
  'priority',
  'range',
  'pageSize',
  'sortBy',
  'sortOrder',
]

export const useFilterStore = create<FilterState>((set) => ({
  jobs: INITIAL_JOB_FILTERS,

  setJobFilter: (key, value) =>
    set((s) => ({
      jobs: {
        ...s.jobs,
        [key]: value,
        ...(RESETS_PAGE.includes(key) ? { page: 1 } : {}),
      },
    })),

  toggleJobStatus: (status) =>
    set((s) => {
      const next = s.jobs.status.includes(status)
        ? s.jobs.status.filter((v) => v !== status)
        : [...s.jobs.status, status]
      return { jobs: { ...s.jobs, status: next, page: 1 } }
    }),

  toggleJobRuntime: (runtime) =>
    set((s) => {
      const next = s.jobs.runtime.includes(runtime)
        ? s.jobs.runtime.filter((v) => v !== runtime)
        : [...s.jobs.runtime, runtime]
      return { jobs: { ...s.jobs, runtime: next, page: 1 } }
    }),

  resetJobFilters: () => set({ jobs: INITIAL_JOB_FILTERS }),

  toggleJobSort: (field) =>
    set((s) => ({
      jobs: {
        ...s.jobs,
        sortBy: field,
        // Ayni ustun ikkinchi marta bosilsa yo'nalish almashadi
        sortOrder: s.jobs.sortBy === field && s.jobs.sortOrder === 'desc' ? 'asc' : 'desc',
        page: 1,
      },
    })),

  dlqGroupBy: 'all',
  dlqSearch: '',
  dlqResolved: false,
  dlqPage: 1,
  setDlqGroupBy: (group) => set({ dlqGroupBy: group, dlqPage: 1 }),
  setDlqSearch: (search) => set({ dlqSearch: search, dlqPage: 1 }),
  setDlqResolved: (resolved) => set({ dlqResolved: resolved, dlqPage: 1 }),
  setDlqPage: (page) => set({ dlqPage: page }),
  resetDlqFilters: () => set({ dlqGroupBy: 'all', dlqSearch: '', dlqResolved: false, dlqPage: 1 }),
}))

/** Faol filtrlar soni (dizayndagi "Clear filters" ko'rinishini boshqaradi). */
export function activeJobFilterCount(f: JobFilterState): number {
  let count = 0
  if (f.search.trim()) count += 1
  count += f.status.length
  count += f.runtime.length
  count += f.priority.length
  if (f.range !== 'all') count += 1
  return count
}
