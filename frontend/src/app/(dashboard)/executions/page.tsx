'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { CountPill, SectionHeader } from '@/components/common/SectionHeader'
import { EmptyState } from '@/components/common/EmptyState'
import { ErrorState } from '@/components/common/ErrorState'
import { MonoId } from '@/components/common/MonoId'
import { Pagination } from '@/components/common/Pagination'
import { RelativeTime } from '@/components/common/RelativeTime'
import { StatusBadge } from '@/components/common/StatusBadge'
import { FilterSelect } from '@/components/ui/filter-select'
import { SearchField } from '@/components/ui/input'
import { SkeletonRows } from '@/components/ui/skeleton'
import { useDebounce } from '@/lib/hooks/useDebounce'
import { useExecutionLogs, useExecutions } from '@/lib/hooks/useExecutions'
import { RetryChain } from '@/components/executions/RetryChain'
import { cn } from '@/lib/utils/cn'
import { formatDuration, formatNumber } from '@/lib/utils/format'
import { formatLogTime } from '@/lib/utils/time'
import { executionStatusStyle } from '@/lib/utils/status'
import type { Execution, ExecutionStatus } from '@/types'
import { failureReasonLabel } from '@/lib/utils/status'
import { useSearchFocus } from '@/lib/hooks/useKeyboard'

/**
 * Bajarish urinishlari — har bir job urinishining alohida yozuvi.
 *
 * Dizaynda alohida mockup yo'q (sidebar'da "Executions" bandi bor).
 * Jadval uslubi Jobs sahifasidan olingan; qator ochilganda O'SHA
 * urinishning loglari ko'rinadi — bu retry'ni tahlil qilishning
 * eng tez yo'li.
 */
const GRID = 'minmax(96px,1.2fr) 64px minmax(80px,0.8fr) 104px 86px 70px 96px'

const STATUS_OPTIONS: { value: ExecutionStatus; label: string; dotClassName: string }[] = (
  ['pending', 'running', 'success', 'failed', 'timeout', 'cancelled', 'lost'] as const
).map((status) => ({
  value: status,
  label: executionStatusStyle(status).label,
  dotClassName: executionStatusStyle(status).dot,
}))

export default function ExecutionsPage() {
  const router = useRouter()
  const [search, setSearch] = useState('')
  const searchRef = useSearchFocus()
  const [statuses, setStatuses] = useState<ExecutionStatus[]>([])
  const [page, setPage] = useState(1)
  const [openId, setOpenId] = useState<string | null>(null)

  const debouncedSearch = useDebounce(search, 300)
  const query = useExecutions({
    search: debouncedSearch || undefined,
    status: statuses.length ? statuses : undefined,
    page,
    page_size: 25,
  })
  const logs = useExecutionLogs(openId)

  const toggleStatus = (status: ExecutionStatus): void => {
    setStatuses((current) =>
      current.includes(status) ? current.filter((s) => s !== status) : [...current, status],
    )
    setPage(1)
  }

  return (
    <>
      <SectionHeader
        title="Executions"
        description="Every attempt Durabl made, including retries and lost leases"
        count={query.data ? <CountPill>{formatNumber(query.data.pagination.total)}</CountPill> : null}
      />

      <div className="flex flex-wrap items-center gap-2.5">
        <SearchField
          ref={searchRef}
          shortcut="/"
          placeholder="Search execution, job or worker…"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
            setPage(1)
          }}
          containerClassName="w-[300px]"
          aria-label="Search executions"
        />
        <FilterSelect
          prefix="Status:"
          options={STATUS_OPTIONS}
          value={statuses}
          onToggle={(value) => toggleStatus(value as ExecutionStatus)}
          onClear={() => setStatuses([])}
        />
      </div>

      {query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          <div className="overflow-hidden rounded-2xl border border-line bg-surface">
            <div className="table-head grid items-center px-3.5" style={{ gridTemplateColumns: GRID }}>
              <span>Job ID</span>
              <span>Attempt</span>
              <span>Worker</span>
              <span>Status</span>
              <span>Duration</span>
              <span>Exit</span>
              <span className="text-right">Started</span>
            </div>

            {query.isLoading && !query.data ? (
              <SkeletonRows rows={12} columns={GRID} />
            ) : (query.data?.items.length ?? 0) === 0 ? (
              <EmptyState
                icon="M4 12h4l2 6 4-15 2 9h4"
                title="No executions match your filters"
                description="Executions appear as soon as a worker picks up a job."
              />
            ) : (
              query.data?.items.map((execution) => (
                <ExecutionRow
                  key={execution.id}
                  execution={execution}
                  isOpen={openId === execution.id}
                  onToggle={() => setOpenId(openId === execution.id ? null : execution.id)}
                  onOpenJob={() => router.push(`/jobs/${execution.job_id}`)}
                  logs={openId === execution.id ? logs.data : undefined}
                  logsLoading={openId === execution.id && logs.isLoading}
                />
              ))
            )}
          </div>

          {query.data ? (
            <Pagination pagination={query.data.pagination} onPageChange={setPage} />
          ) : null}
        </>
      )}
    </>
  )
}

function ExecutionRow({
  execution,
  isOpen,
  onToggle,
  onOpenJob,
  logs,
  logsLoading,
}: {
  execution: Execution
  isOpen: boolean
  onToggle: () => void
  onOpenJob: () => void
  logs: { id: string; stream: string; content: string; timestamp: string }[] | undefined
  logsLoading: boolean
}) {
  const style = executionStatusStyle(execution.status)

  return (
    <div>
      <div
        role="button"
        tabIndex={0}
        aria-expanded={isOpen}
        onClick={onToggle}
        onKeyDown={(event) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault()
            onToggle()
          }
        }}
        className="grid h-10 cursor-pointer items-center px-3.5 transition-colors hover:bg-surface-3"
        style={{ gridTemplateColumns: GRID }}
      >
        <MonoId value={execution.job_id} />
        <span className="tabular font-mono text-sm text-fg-soft">#{execution.attempt_number}</span>
        <span className="truncate font-mono text-sm text-fg-muted">
          {execution.worker_id ?? '—'}
        </span>
        <span>
          <StatusBadge style={style} />
        </span>
        <span className="tabular font-mono text-sm text-fg-muted">
          {formatDuration(execution.duration_ms)}
        </span>
        <span
          className={cn(
            'tabular font-mono text-sm',
            execution.exit_code === 0 ? 'text-fg-muted' : 'text-failed',
          )}
        >
          {execution.exit_code ?? '—'}
        </span>
        <RelativeTime
          value={execution.started_at}
          className="tabular text-right font-mono text-sm text-fg-faint"
        />
      </div>

      <div className="border-b border-line-subtle" />

      {isOpen ? (
        <div className="animate-slide-down border-b border-line-subtle bg-canvas-sunken px-4 pb-3.5 pt-3">
          <div className="mb-2.5 flex flex-wrap items-center gap-4 text-sm">
            {execution.failure_reason ? (
              <span className="text-fg-dim">
                Reason{' '}
                <span className="font-mono text-failed">{failureReasonLabel(execution.failure_reason)}</span>
              </span>
            ) : null}
            <span className="text-fg-dim">
              stdout <span className="font-mono text-fg-muted">{execution.stdout_bytes} B</span>
            </span>
            <span className="text-fg-dim">
              stderr <span className="font-mono text-fg-muted">{execution.stderr_bytes} B</span>
            </span>
            <button
              type="button"
              onClick={(event) => {
                event.stopPropagation()
                onOpenJob()
              }}
              className="ml-auto text-sm font-medium text-accent hover:text-accent-light"
            >
              Open job →
            </button>
          </div>

          {execution.error_message ? (
            <pre className="m-0 mb-3 max-h-[200px] overflow-auto whitespace-pre rounded-lg border border-failed/[0.18] bg-failed/[0.06] px-3.5 py-3 font-mono text-[11.5px] leading-[1.65] text-failed-text">
              {execution.error_message}
            </pre>
          ) : null}

          {/* Zanjir — "nega bu urinish bo'lgan?" savoliga kontekst beradi */}
          <div className="mb-3">
            {/* `jobStatus` berilmaydi: bu sahifada job holati yo'q (faqat
                urinishlar ro'yxati). Job detalida u beriladi va zanjir
                oxiriga DLQ tuguni qo'shiladi. */}
            <RetryChain jobId={execution.job_id} currentExecutionId={execution.id} />
          </div>

          <div className="mb-1.5 text-xs font-semibold text-fg-dim">Logs for this attempt</div>
          <div className="max-h-[240px] overflow-auto rounded-lg border border-line-inner bg-canvas-deep px-3 py-2 font-mono text-xs leading-[1.7]">
            {logsLoading ? (
              <div className="py-4 text-center text-fg-faint">Loading logs…</div>
            ) : !logs || logs.length === 0 ? (
              <div className="py-4 text-center text-fg-faint">No output captured.</div>
            ) : (
              logs.map((log) => (
                <div key={log.id} className="flex gap-3">
                  <span className="shrink-0 text-fg-faint">{formatLogTime(log.timestamp)}</span>
                  <span
                    className={cn(
                      'min-w-0 whitespace-pre-wrap break-words',
                      log.stream === 'stderr'
                        ? 'text-failed-text'
                        : log.stream === 'system'
                          ? 'text-fg-dim'
                          : 'text-fg-soft',
                    )}
                  >
                    {log.content}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      ) : null}
    </div>
  )
}
