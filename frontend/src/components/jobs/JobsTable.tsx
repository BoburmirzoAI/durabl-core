'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useMemo, useState } from 'react'

import { BULK_ICONS, BulkActionBar } from '@/components/common/BulkActionBar'
import { type Column, DataTable } from '@/components/common/DataTable'
import { EmptyState } from '@/components/common/EmptyState'
import { MonoId } from '@/components/common/MonoId'
import { RelativeTime } from '@/components/common/RelativeTime'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Skeleton, SkeletonRows } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils/cn'
import { formatDuration } from '@/lib/utils/format'
import { failureReasonLabel } from '@/lib/utils/status'
import { formatLogTime } from '@/lib/utils/time'
import { type CsvColumn, downloadCsv, timestampedName, toCsv } from '@/lib/utils/csv'
import { useToast } from '@/components/common/ToastProvider'
import {
  useBulkCancelJobs,
  useBulkRetryJobs,
  useCancelJob,
  useDeleteJob,
  useJobLogs,
  useRetryJob,
} from '@/lib/hooks/useJobs'
import { ICON_COPY } from '@/lib/constants/icons'
import { useCopy } from '@/lib/hooks/useCopy'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { useFilterStore } from '@/stores/filterStore'
import type { JobSummary, SortOrder } from '@/types'

import { JobStatusBadge, RuntimeBadge } from './JobStatusBadge'

/**
 * Job'lar jadvali.
 *
 * Ustun kengliklari dizayndan AYNAN olingan:
 * `36px minmax(96px,1.3fr) minmax(70px,1fr) 78px 104px 58px 78px 86px 44px`
 * (birinchi 36px — checkbox, uni `DataTable` o'zi qo'shadi).
 */
const GRID = 'minmax(96px,1.3fr) minmax(70px,1fr) 78px 104px 58px 78px 86px 44px'

export const JOBS_SCOPE = 'jobs'

export function JobsTable({
  jobs,
  loading = false,
  onNewJob,
}: {
  jobs: JobSummary[] | undefined
  loading?: boolean
  onNewJob?: () => void
}) {
  const router = useRouter()
  // DIQQAT: bu yerda `({ field, order })` kabi YANGI obyekt qaytarib bo'lmaydi —
  // Zustand `Object.is` bilan solishtiradi va har render yangi obyektni
  // "o'zgargan" deb biladi (cheksiz tsikl). Ikkita primitiv selektor xavfsiz.
  const sortBy = useFilterStore((s) => s.jobs.sortBy)
  const sortOrder = useFilterStore((s) => s.jobs.sortOrder as SortOrder)
  const sort = useMemo<{ field: string; order: SortOrder }>(
    () => ({ field: sortBy, order: sortOrder }),
    [sortBy, sortOrder],
  )
  const toggleSort = useFilterStore((s) => s.toggleJobSort)

  const cancelJob = useCancelJob()
  const deleteJob = useDeleteJob()
  const copy = useCopy()
  const { toast } = useToast()
  const [confirmDelete, setConfirmDelete] = useState<JobSummary | null>(null)
  const retryJob = useRetryJob()
  const bulkCancel = useBulkCancelJobs()
  const bulkRetry = useBulkRetryJobs()

  const columns: Column<JobSummary>[] = [
    {
      key: 'id',
      header: 'Job ID',
      sortable: true,
      cell: (job) => <MonoId value={job.id} />,
    },
    {
      key: 'idempotency_key',
      header: 'Idempotency Key',
      cell: (job) => (
        <span className="block truncate font-mono text-sm text-fg-faint" title={job.idempotency_key ?? undefined}>
          {job.idempotency_key ?? '—'}
        </span>
      ),
    },
    {
      key: 'runtime',
      header: 'Runtime',
      sortable: true,
      cell: (job) => <RuntimeBadge runtime={job.runtime} size="sm" />,
    },
    {
      key: 'status',
      header: 'Status',
      sortable: true,
      cell: (job) => <JobStatusBadge status={job.status} />,
    },
    {
      key: 'attempts_used',
      header: 'Attempts',
      sortable: true,
      cell: (job) => (
        <span
          className={cn(
            'tabular font-mono text-sm',
            // Bir martadan ko'p urinish — e'tibor talab qiladi
            job.attempts_used > 1 ? 'text-pending' : 'text-fg-muted',
          )}
        >
          {job.attempts_used}/{job.max_retries + 1}
        </span>
      ),
    },
    {
      key: 'duration_ms',
      header: 'Duration',
      sortable: true,
      cell: (job) => (
        <span className="tabular font-mono text-sm text-fg-muted">
          {formatDuration(job.duration_ms)}
        </span>
      ),
    },
    {
      key: 'created_at',
      header: 'Created',
      sortable: true,
      cell: (job) => (
        <RelativeTime value={job.created_at} className="tabular font-mono text-sm text-fg-faint" />
      ),
    },
    {
      key: 'actions',
      header: 'Actions',
      srOnlyHeader: true,
      align: 'right',
      cell: (job) => (
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
            <DropdownMenuContent>
              <DropdownMenuItem onSelect={() => router.push(`/jobs/${job.id}`)}>
                <Icon path="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
                View details
              </DropdownMenuItem>
              <DropdownMenuItem
                disabled={!job.is_terminal}
                onSelect={() => retryJob.mutate(job.id)}
              >
                <Icon path={BULK_ICONS.retry} />
                Retry
              </DropdownMenuItem>
              <DropdownMenuItem
                danger
                disabled={job.is_terminal}
                onSelect={() => cancelJob.mutate(job.id)}
              >
                <Icon path={BULK_ICONS.cancel} />
                Cancel
              </DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={() => void copy(job.id, 'Job ID copied')}>
                <Icon path={ICON_COPY} />
                Copy ID
              </DropdownMenuItem>
              <DropdownMenuItem danger onSelect={() => setConfirmDelete(job)}>
                <Icon path="M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14M10 11v6M14 11v6" />
                Delete
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </span>
      ),
    },
  ]

  return (
    <>
      <ConfirmDialog
        open={confirmDelete !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmDelete(null)
        }}
        title="Delete job?"
        description={
          confirmDelete
            ? `${confirmDelete.id} and its logs, attempts and result are removed permanently. This cannot be undone.`
            : ''
        }
        confirmLabel="Delete"
        destructive
        pending={deleteJob.isPending}
        onConfirm={() => {
          if (!confirmDelete) return
          deleteJob.mutate(confirmDelete.id)
          setConfirmDelete(null)
        }}
      />
    <DataTable
      aria-label="Jobs"
      scope={JOBS_SCOPE}
      rows={jobs ?? []}
      columns={columns}
      gridTemplate={GRID}
      rowId={(job) => job.id}
      onRowClick={(job) => router.push(`/jobs/${job.id}`)}
      selectable
      renderExpanded={(job) => <JobPeek job={job} />}
      sort={sort}
      onSortChange={toggleSort}
      loading={loading}
      loadingState={<SkeletonRows rows={12} columns={`36px ${GRID}`} />}
      overlay={
        <BulkActionBar
          scope={JOBS_SCOPE}
          actions={[
            {
              label: 'Retry',
              icon: BULK_ICONS.retry,
              onClick: (ids) => bulkRetry.mutate(ids),
            },
            {
              label: 'Cancel',
              icon: BULK_ICONS.cancel,
              iconClassName: 'text-failed',
              onClick: (ids) => bulkCancel.mutate(ids),
            },
            {
              label: 'Export CSV',
              icon: 'M12 3v12M7 10l5 5 5-5M4 19h16',
              onClick: (ids) => {
                const chosen = (jobs ?? []).filter((j) => ids.includes(j.id))
                downloadCsv(timestampedName('durabl-jobs'), toCsv(chosen, JOB_CSV_COLUMNS))
                toast({
                  title: `Exported ${chosen.length} jobs`,
                  variant: 'success',
                })
              },
            },
          ]}
        />
      }
      emptyState={
        <EmptyState
          icon="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"
          title="No jobs match your filters"
          description="Try widening the time range or clearing a filter."
          action={
            onNewJob ? (
              <button
                type="button"
                onClick={onNewJob}
                className="text-sm font-medium text-accent hover:text-accent-light"
              >
                Submit a job instead →
              </button>
            ) : null
          }
        />
      }
    />
    </>
  )
}

function Icon({ path }: { path: string }) {
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d={path} />
    </svg>
  )
}

/**
 * Qator ichidagi "tez ko'z tashlash".
 *
 * Detal sahifasiga o'tmasdan eng kerakli uchta narsa: oxirgi log qatorlari,
 * xato (bo'lsa) va asosiy ko'rsatkichlar. Loglar faqat qator OCHILGANDA
 * so'raladi — 25 ta yopiq qator 25 ta keraksiz so'rov yasamasligi uchun.
 */
function JobPeek({ job }: { job: JobSummary }) {
  const logs = useJobLogs(job.id, false)
  const tail = (logs.data ?? []).slice(-6)
  const errorLines = (logs.data ?? [])
    .filter((l) => l.stream === 'stderr')
    .slice(-4)
    .map((l) => l.content)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm">
        <span className="text-fg-dim">
          Worker <span className="font-mono text-fg-muted">{job.worker_id ?? '—'}</span>
        </span>
        <span className="text-fg-dim">
          Attempts{' '}
          <span className="font-mono text-fg-muted">
            {job.attempts_used}/{job.max_retries + 1}
          </span>
        </span>
        <span className="text-fg-dim">
          Duration <span className="font-mono text-fg-muted">{formatDuration(job.duration_ms)}</span>
        </span>
        {job.failure_reason ? (
          <span className="text-fg-dim">
            Reason{' '}
            <span className="font-mono text-failed">{failureReasonLabel(job.failure_reason)}</span>
          </span>
        ) : null}
        <Link
          href={`/jobs/${job.id}`}
          className="ml-auto text-sm text-accent-light transition-colors hover:text-accent-pale"
        >
          Open detail →
        </Link>
      </div>

      {/* `JobSummary` da `error` maydoni YO'Q (ro'yxat yengil bo'lishi uchun) —
          shuning uchun xato matni `stderr` loglaridan olinadi. */}
      {errorLines.length > 0 ? (
        <pre className="m-0 max-h-[120px] overflow-auto whitespace-pre-wrap rounded-lg border border-failed/[0.18] bg-failed/[0.06] px-3 py-2 font-mono text-xs leading-[1.6] text-failed-text">
          {errorLines.join('\n')}
        </pre>
      ) : null}

      <div>
        <div className="mb-1.5 text-xs font-semibold text-fg-dim">Recent logs</div>
        {logs.isLoading ? (
          <Skeleton className="h-20 w-full" />
        ) : tail.length === 0 ? (
          <div className="rounded-lg border border-line-inner bg-canvas-deep px-3 py-2.5 text-xs text-fg-faint">
            No output captured.
          </div>
        ) : (
          <div className="overflow-auto rounded-lg border border-line-inner bg-canvas-deep py-2 font-mono text-xs leading-[1.7]">
            {tail.map((log) => (
              <div key={log.id} className="flex items-baseline px-3">
                <span className="mr-2.5 shrink-0 text-fg-faint">{formatLogTime(log.timestamp)}</span>
                <span
                  className={cn(
                    'min-w-0 whitespace-pre-wrap break-words',
                    log.stream === 'stderr' ? 'text-failed-text' : 'text-fg-soft',
                  )}
                >
                  {log.content}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

/** CSV eksport ustunlari — backend `GET /jobs/export` bilan bir xil tartib. */
export const JOB_CSV_COLUMNS: CsvColumn<JobSummary>[] = [
  { header: 'id', value: (j) => j.id },
  { header: 'status', value: (j) => j.status },
  { header: 'runtime', value: (j) => j.runtime },
  { header: 'priority', value: (j) => j.priority },
  { header: 'idempotency_key', value: (j) => j.idempotency_key },
  { header: 'attempts_used', value: (j) => j.attempts_used },
  { header: 'max_retries', value: (j) => j.max_retries },
  { header: 'duration_ms', value: (j) => j.duration_ms },
  { header: 'exit_code', value: (j) => j.exit_code },
  { header: 'failure_reason', value: (j) => j.failure_reason },
  { header: 'worker_id', value: (j) => j.worker_id },
  { header: 'created_at', value: (j) => j.created_at },
  { header: 'finished_at', value: (j) => j.finished_at },
]
