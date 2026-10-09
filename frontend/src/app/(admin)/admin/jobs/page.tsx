'use client'

import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'

import { CountPill, SectionHeader } from '@/components/common/SectionHeader'
import { EmptyState } from '@/components/common/EmptyState'
import { ErrorState } from '@/components/common/ErrorState'
import { MonoId } from '@/components/common/MonoId'
import { Pagination } from '@/components/common/Pagination'
import { RelativeTime } from '@/components/common/RelativeTime'
import { Badge } from '@/components/ui/badge'
import { FilterSelect } from '@/components/ui/filter-select'
import { SearchField } from '@/components/ui/input'
import { SkeletonRows } from '@/components/ui/skeleton'
import { BULK_ICONS, BulkActionBar } from '@/components/common/BulkActionBar'
import { Checkbox } from '@/components/ui/checkbox'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  useBulkCancelJobs,
  useBulkRetryJobs,
  useCancelJob,
  useForceFailJob,
  useReassignJob,
  useRetryJob,
  useSetJobPriority,
} from '@/lib/hooks/useJobs'
import { useSelectionStore } from '@/stores/selectionStore'
import { JobStatusBadge, RuntimeBadge } from '@/components/jobs/JobStatusBadge'
import { useDebounce } from '@/lib/hooks/useDebounce'
import { useJobs } from '@/lib/hooks/useJobs'
import { cn } from '@/lib/utils/cn'
import { formatDuration, formatNumber } from '@/lib/utils/format'
import { jobStatusStyle } from '@/lib/utils/status'
import { JOB_STATUSES, type JobStatus, type JobSummary } from '@/types'
import { useSearchFocus } from '@/lib/hooks/useKeyboard'
import { rangeLabel } from '@/lib/utils/time'

/**
 * Admin — BARCHA foydalanuvchilarning job'lari.
 *
 * Mijoz jadvalidan farqi: "User" ustuni bor va "Force fail" amali mavjud —
 * worker aloqasi uzilib qolgan, lekin job `running` holatida qotib qolgan
 * vaziyatlar uchun. Bu faqat adminda bo'ladi.
 */
/** Tanlov doirasi — mijoz jadvallari bilan aralashmaydi. */
const SCOPE = 'admin-jobs'

/** Barqaror bo'sh massiv — Zustand selektori uchun (cheksiz render oldini oladi). */
const EMPTY_IDS: string[] = []

const GRID =
  '34px minmax(96px,1.2fr) minmax(120px,1fr) 78px 104px 58px 78px 86px 44px'

const STATUS_OPTIONS = JOB_STATUSES.map((status) => ({
  value: status,
  label: jobStatusStyle(status).label,
  dotClassName: jobStatusStyle(status).dot,
}))

export default function AdminJobsPage() {
  return (
    <Suspense fallback={null}>
      <AdminJobsContent />
    </Suspense>
  )
}

function AdminJobsContent() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const userFilter = searchParams.get('user')
  // Foydalanuvchi sahifasidagi kunlik grafikdan aniq sutka bilan kelinadi
  const rangeFilter = searchParams.get('range')

  const [search, setSearch] = useState(userFilter ?? '')
  const searchRef = useSearchFocus()
  const [statuses, setStatuses] = useState<JobStatus[]>([])
  const [page, setPage] = useState(1)
  const [forceFail, setForceFail] = useState<JobSummary | null>(null)

  const selected = useSelectionStore((s) => s.selected[SCOPE] ?? EMPTY_IDS)
  const setMany = useSelectionStore((s) => s.setMany)
  const toggleSelect = useSelectionStore((s) => s.toggle)
  const clearSelection = useSelectionStore((s) => s.clear)

  const retryJob = useRetryJob()
  const cancelJob = useCancelJob()
  const bulkRetry = useBulkRetryJobs()
  const bulkCancel = useBulkCancelJobs()
  const forceFailJob = useForceFailJob()
  const setPriority = useSetJobPriority()
  const reassign = useReassignJob()

  const debouncedSearch = useDebounce(search, 300)
  const query = useJobs({
    search: debouncedSearch || undefined,
    status: statuses.length ? statuses : undefined,
    range: rangeFilter ?? undefined,
    page,
    page_size: 25,
  })

  const rows = query.data?.items ?? []
  const allSelected = rows.length > 0 && rows.every((j) => selected.includes(j.id))

  return (
    <>
      <SectionHeader
        title="All jobs"
        description="Every job submitted by every user"
        count={
          <>
            {query.data ? <CountPill>{formatNumber(query.data.pagination.total)}</CountPill> : null}
            <Badge variant="danger">ADMIN</Badge>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2.5">
        <SearchField
          ref={searchRef}
          shortcut="/"
          placeholder="Search job ID, key, worker…"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
            setPage(1)
          }}
          containerClassName="w-[300px]"
          aria-label="Search all jobs"
        />
        <FilterSelect
          prefix="Status:"
          options={STATUS_OPTIONS}
          value={statuses}
          onToggle={(value) => {
            const status = value as JobStatus
            setStatuses((current) =>
              current.includes(status) ? current.filter((s) => s !== status) : [...current, status],
            )
            setPage(1)
          }}
          onClear={() => setStatuses([])}
        />
        {rangeFilter ? (
          <span className="flex items-center gap-2 rounded-md border border-line-strong bg-surface-3 px-2.5 py-1 text-sm text-fg-soft">
            <span className="text-fg-faint">When</span>
            <span>{rangeLabel(rangeFilter)}</span>
            <button
              type="button"
              aria-label="Clear time filter"
              onClick={() =>
                router.push(userFilter ? `/admin/jobs?user=${encodeURIComponent(userFilter)}` : '/admin/jobs')
              }
              className="text-fg-dim hover:text-fg"
            >
              ×
            </button>
          </span>
        ) : null}
        {userFilter ? (
          <span className="flex items-center gap-2 rounded-md border border-line-strong bg-surface-3 px-2.5 py-1 text-sm text-fg-soft">
            <span className="text-fg-faint">User</span>
            <span className="font-mono">{userFilter}</span>
            <button
              type="button"
              aria-label="Clear user filter"
              onClick={() => router.push('/admin/jobs')}
              className="text-fg-dim hover:text-fg"
            >
              ×
            </button>
          </span>
        ) : null}
      </div>

      {query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          <div className="relative overflow-hidden rounded-2xl border border-line bg-surface">
            <BulkActionBar
              scope={SCOPE}
              actions={[
                {
                  label: 'Retry',
                  icon: BULK_ICONS.retry,
                  onClick: (ids) => {
                    bulkRetry.mutate(ids)
                    clearSelection(SCOPE)
                  },
                },
                {
                  label: 'Cancel',
                  icon: BULK_ICONS.cancel,
                  iconClassName: 'text-failed',
                  onClick: (ids) => {
                    bulkCancel.mutate(ids)
                    clearSelection(SCOPE)
                  },
                },
              ]}
            />
            <div className="table-head grid items-center px-3.5" style={{ gridTemplateColumns: GRID }}>
              <Checkbox
                checked={allSelected}
                indeterminate={!allSelected && selected.length > 0}
                onToggle={() =>
                  setMany(SCOPE, selected.length === rows.length ? [] : rows.map((j) => j.id))
                }
                aria-label="Select all jobs on this page"
              />
              <span>Job ID</span>
              <span>User</span>
              <span>Runtime</span>
              <span>Status</span>
              <span>Attempts</span>
              <span>Duration</span>
              <span className="text-right">Created</span>
              <span className="sr-only">Actions</span>
            </div>

            {query.isLoading && !query.data ? (
              <SkeletonRows rows={12} columns={GRID} />
            ) : (query.data?.items.length ?? 0) === 0 ? (
              <EmptyState
                icon="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"
                title="No jobs match your filters"
              />
            ) : (
              query.data?.items.map((job) => (
                <div
                  key={job.id}
                  role="button"
                  tabIndex={0}
                  onClick={() => router.push(`/jobs/${job.id}`)}
                  onKeyDown={(event) => {
                    if (event.key === 'Enter') router.push(`/jobs/${job.id}`)
                  }}
                  className={cn(
                    'grid h-10 cursor-pointer items-center border-b border-line-subtle px-3.5 transition-colors',
                    selected.includes(job.id) ? 'bg-accent/[0.06]' : 'hover:bg-surface-3',
                  )}
                  style={{ gridTemplateColumns: GRID }}
                >
                  <span onClick={(event) => event.stopPropagation()}>
                    <Checkbox
                      checked={selected.includes(job.id)}
                      onToggle={() => toggleSelect(SCOPE, job.id)}
                      aria-label={`Select ${job.id}`}
                    />
                  </span>
                  <MonoId value={job.id} />
                  <span className="truncate font-mono text-sm text-fg-faint" title={job.user_id}>
                    {job.user_id}
                  </span>
                  <span>
                    <RuntimeBadge runtime={job.runtime} size="sm" />
                  </span>
                  <span>
                    <JobStatusBadge status={job.status} />
                  </span>
                  <span
                    className={cn(
                      'tabular font-mono text-sm',
                      job.attempts_used > 1 ? 'text-pending' : 'text-fg-muted',
                    )}
                  >
                    {job.attempts_used}/{job.max_retries + 1}
                  </span>
                  <span className="tabular font-mono text-sm text-fg-muted">
                    {formatDuration(job.duration_ms)}
                  </span>
                  <RelativeTime
                    value={job.created_at}
                    className="tabular text-right font-mono text-sm text-fg-faint"
                  />
                  <span className="flex justify-end" onClick={(event) => event.stopPropagation()}>
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button
                          type="button"
                          aria-label={`Actions for ${job.id}`}
                          className="inline-flex h-[26px] w-[26px] items-center justify-center rounded-md text-fg-dim transition-colors hover:bg-line hover:text-fg"
                        >
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                            <circle cx="12" cy="5" r="1.6" />
                            <circle cx="12" cy="12" r="1.6" />
                            <circle cx="12" cy="19" r="1.6" />
                          </svg>
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent className="min-w-[160px]">
                        <DropdownMenuItem onSelect={() => router.push(`/jobs/${job.id}`)}>
                          View job
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          disabled={!job.is_terminal}
                          onSelect={() => retryJob.mutate(job.id)}
                        >
                          Retry
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          danger
                          disabled={job.is_terminal}
                          onSelect={() => cancelJob.mutate(job.id)}
                        >
                          Cancel
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          disabled={job.status !== 'queued' && job.status !== 'retrying'}
                          onSelect={() =>
                            setPriority.mutate({
                              id: job.id,
                              priority: job.priority === 'high' ? 'normal' : 'high',
                            })
                          }
                        >
                          {job.priority === 'high' ? 'Lower to normal priority' : 'Raise to high priority'}
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          disabled={job.is_terminal}
                          onSelect={() => reassign.mutate({ id: job.id, workerId: null })}
                        >
                          Return to the queue
                        </DropdownMenuItem>
                        <DropdownMenuItem
                          danger
                          disabled={job.is_terminal}
                          onSelect={() => setForceFail(job)}
                        >
                          Force fail
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </span>
                </div>
              ))
            )}
          </div>

          {query.data ? (
            <Pagination pagination={query.data.pagination} onPageChange={setPage} />
          ) : null}
        </>
      )}

      <ConfirmDialog
        open={forceFail !== null}
        onOpenChange={(open) => {
          if (!open) setForceFail(null)
        }}
        title="Force fail this job?"
        description={
          forceFail
            ? `${forceFail.id} is marked failed immediately without waiting for its worker. ` +
              (forceFail.attempts_used >= forceFail.max_retries
                ? 'It has already used every retry, so it goes straight to the dead letter queue.'
                : `It has ${forceFail.max_retries - forceFail.attempts_used} ${forceFail.max_retries - forceFail.attempts_used === 1 ? 'retry' : 'retries'} left and will be retried. ` +
                  'Use Cancel instead if the work is simply no longer wanted — a cancelled job does not count as a failure.')
            : ''
        }
        confirmLabel="Force fail"
        destructive
        pending={forceFailJob.isPending}
        onConfirm={() => {
          if (!forceFail) return
          forceFailJob.mutate({ id: forceFail.id })
          setForceFail(null)
        }}
      />
    </>
  )
}
