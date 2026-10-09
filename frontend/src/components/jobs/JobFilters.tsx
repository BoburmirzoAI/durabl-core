'use client'

import { useEffect, useMemo, useState } from 'react'

import { FilterChips, type FilterChip } from '@/components/common/FilterChips'
import { FilterSelect, SingleSelect } from '@/components/ui/filter-select'
import { SearchField } from '@/components/ui/input'
import { useDebounce } from '@/lib/hooks/useDebounce'
import { useSearchFocus } from '@/lib/hooks/useKeyboard'
import { jobStatusStyle, runtimeStyle } from '@/lib/utils/status'
import { rangeLabel } from '@/lib/utils/time'
import { activeJobFilterCount, useFilterStore } from '@/stores/filterStore'
import { JOB_STATUSES, PRIORITIES, RUNTIMES, type JobStatus, type Priority, type Runtime } from '@/types'

/**
 * Job filtr paneli — dizaynda qidiruv + uch dropdown + chiplar.
 *
 * Dizayn faqat KO'RINISHNI bergan; filtr mantig'i, chiplar va URL
 * sinxronizatsiyasi shu yerda amalga oshirilgan.
 */
const STATUS_OPTIONS = JOB_STATUSES.map((status) => ({
  value: status,
  label: jobStatusStyle(status).label,
  dotClassName: jobStatusStyle(status).dot,
}))

const RUNTIME_OPTIONS = RUNTIMES.map((runtime) => ({
  value: runtime,
  label: runtimeStyle(runtime).label,
  dotClassName: runtimeStyle(runtime).dot,
}))

const PRIORITY_OPTIONS = PRIORITIES.map((priority) => ({
  value: priority,
  label: priority.charAt(0).toUpperCase() + priority.slice(1),
}))

const RANGE_OPTIONS = [
  { value: 'all', label: 'All time' },
  { value: '1h', label: 'Last hour' },
  { value: '24h', label: 'Last 24h' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
] as const

export function JobFilters() {
  const filters = useFilterStore((s) => s.jobs)
  const setFilter = useFilterStore((s) => s.setJobFilter)
  const toggleStatus = useFilterStore((s) => s.toggleJobStatus)
  const toggleRuntime = useFilterStore((s) => s.toggleJobRuntime)
  const reset = useFilterStore((s) => s.resetJobFilters)

  // Ixtiyoriy oraliq (analitikadan drill-down) ro'yxatda yo'q — tanlangan
  // bo'lsa vaqtincha qo'shamiz, aks holda tanlagich bo'sh ko'rinadi
  const rangeOptions = useMemo(
    () =>
      RANGE_OPTIONS.some((r) => r.value === filters.range)
        ? RANGE_OPTIONS
        : [...RANGE_OPTIONS, { value: filters.range, label: rangeLabel(filters.range) }],
    [filters.range],
  )

  // Qidiruv maydonini mahalliy holatda saqlaymiz va debounce bilan
  // store'ga uzatamiz — har harfda so'rov ketmasligi uchun
  const [searchDraft, setSearchDraft] = useState(filters.search)
  const debouncedSearch = useDebounce(searchDraft, 300)

  useEffect(() => {
    if (debouncedSearch !== filters.search) setFilter('search', debouncedSearch)
  }, [debouncedSearch, filters.search, setFilter])

  // Store tashqaridan tozalansa (chip o'chirilganda) maydon ham tozalanadi
  useEffect(() => {
    if (filters.search === '' && searchDraft !== '') setSearchDraft('')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters.search])

  const searchRef = useSearchFocus()

  const chips: FilterChip[] = [
    ...filters.status.map((status) => ({
      kind: 'Status',
      label: jobStatusStyle(status).label,
      onRemove: () => toggleStatus(status),
    })),
    ...filters.runtime.map((runtime) => ({
      kind: 'Runtime',
      label: runtimeStyle(runtime).label,
      onRemove: () => toggleRuntime(runtime),
    })),
    ...filters.priority.map((priority) => ({
      kind: 'Priority',
      label: priority,
      onRemove: () =>
        setFilter(
          'priority',
          filters.priority.filter((p) => p !== priority),
        ),
    })),
    ...(filters.range !== 'all'
      ? [
          {
            kind: 'Range',
            // Analitikadan drill-down qilganda oraliq `custom:<from>|<to>`
            // bo'ladi — xom qator o'rniga o'qiladigan sana ko'rsatiladi
            label: RANGE_OPTIONS.find((r) => r.value === filters.range)?.label ?? rangeLabel(filters.range),
            onRemove: () => setFilter('range', 'all'),
          },
        ]
      : []),
    ...(filters.search.trim()
      ? [{ kind: 'Search', label: filters.search, onRemove: () => setFilter('search', '') }]
      : []),
  ]

  const hasFilters = activeJobFilterCount(filters) > 0

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2.5">
        <SearchField
          ref={searchRef}
          shortcut="/"
          placeholder="Search by job ID, key…"
          value={searchDraft}
          onChange={(event) => setSearchDraft(event.target.value)}
          containerClassName="w-[272px]"
          aria-label="Search jobs"
        />

        <FilterSelect
          prefix="Status:"
          options={STATUS_OPTIONS}
          value={filters.status}
          onToggle={(value) => toggleStatus(value as JobStatus)}
          onClear={() => setFilter('status', [])}
        />
        <FilterSelect
          prefix="Runtime:"
          options={RUNTIME_OPTIONS}
          value={filters.runtime}
          onToggle={(value) => toggleRuntime(value as Runtime)}
          onClear={() => setFilter('runtime', [])}
        />
        <FilterSelect
          prefix="Priority:"
          options={PRIORITY_OPTIONS}
          value={filters.priority}
          onToggle={(value) => {
            const priority = value as Priority
            setFilter(
              'priority',
              filters.priority.includes(priority)
                ? filters.priority.filter((p) => p !== priority)
                : [...filters.priority, priority],
            )
          }}
          onClear={() => setFilter('priority', [])}
        />
        <SingleSelect
          prefix="When:"
          options={rangeOptions}
          value={filters.range}
          onChange={(value) => setFilter('range', value)}
        />

        {hasFilters ? (
          <button
            type="button"
            onClick={reset}
            className="text-sm font-medium text-fg-dim transition-colors hover:text-fg-muted"
          >
            Clear filters
          </button>
        ) : null}
      </div>

      <FilterChips chips={chips} onClearAll={reset} />
    </div>
  )
}

