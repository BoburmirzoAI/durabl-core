'use client'

import { useState } from 'react'

import { EmptyState } from '@/components/common/EmptyState'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils/cn'
import { formatDuration } from '@/lib/utils/format'
import { formatLogTime } from '@/lib/utils/time'
import { formatTimestamp } from '@/lib/utils/time'
import { executionStatusStyle } from '@/lib/utils/status'
import type { Execution, JobLog } from '@/types'

/**
 * Urinishlar jadvali — dizayndagi "Attempts" tabi.
 *
 * Ustunlar: `70px minmax(80px,1fr) 150px 84px 74px 100px 44px`.
 * Qator bosilganda xato tafsiloti ochiladi (qizil `pre` bloki).
 */
const GRID = '70px minmax(80px,1fr) 150px 84px 74px 100px 44px'

export function JobAttemptsTable({
  executions,
  loading = false,
  logs,
}: {
  executions: Execution[] | undefined
  loading?: boolean,
  /** Job loglari — har bir urinish o'ziniki ajratib ko'rsatiladi. */
  logs?: JobLog[],
}) {
  const [openIds, setOpenIds] = useState<string[]>([])

  const toggle = (id: string): void => {
    setOpenIds((current) =>
      current.includes(id) ? current.filter((v) => v !== id) : [...current, id],
    )
  }

  if (loading && !executions) {
    return (
      <div className="p-4">
        {Array.from({ length: 3 }, (_, i) => (
          <Skeleton key={i} className="mb-2 h-10" />
        ))}
      </div>
    )
  }

  if (!executions || executions.length === 0) {
    return (
      <EmptyState
        icon="M4 12h4l2 6 4-15 2 9h4"
        title="No attempts yet"
        description="This job hasn't been picked up by a worker."
      />
    )
  }

  return (
    <div>
      <div className="table-head grid items-center px-4" style={{ gridTemplateColumns: GRID }}>
        <span>Attempt</span>
        <span>Worker</span>
        <span>Started</span>
        <span>Duration</span>
        <span>Exit</span>
        <span>Status</span>
        <span className="sr-only">Expand</span>
      </div>

      {executions.map((execution) => {
        const style = executionStatusStyle(execution.status)
        const isOpen = openIds.includes(execution.id)
        const hasError = Boolean(execution.error_message)

        return (
          <div key={execution.id}>
            <button
              type="button"
              aria-expanded={isOpen}
              onClick={() => toggle(execution.id)}
              className="grid h-11 w-full items-center px-4 text-left transition-colors hover:bg-surface-3"
              style={{ gridTemplateColumns: GRID }}
            >
              <span className="font-mono text-sm font-medium text-fg-soft">
                #{execution.attempt_number}
              </span>
              <span className="truncate font-mono text-sm text-fg-muted">
                {execution.worker_id ?? '—'}
              </span>
              <span
                className="tabular font-mono text-sm text-fg-faint"
                title={execution.started_at ? formatTimestamp(execution.started_at) : undefined}
              >
                {execution.started_at
                  ? new Date(execution.started_at).toISOString().slice(11, 19)
                  : '—'}
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
              <span>
                <StatusBadge style={style} />
              </span>
              <span className="flex justify-end text-fg-faint">
                <svg
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className={cn('transition-transform', isOpen && 'rotate-90')}
                  aria-hidden
                >
                  <path d="M9 6l6 6-6 6" />
                </svg>
              </span>
            </button>

            <div className="border-b border-line-subtle" />

            {isOpen ? (
              <div className="animate-slide-down border-b border-line-subtle bg-canvas-sunken px-4 pb-3.5 pt-3">
                {/* Metadata HAR DOIM ko'rsatiladi — ilgari u faqat
                    muvaffaqiyatli urinishlarda chiqardi, ya'ni aynan xato
                    bo'lgan urinish haqida ma'lumot KAM edi. */}
                <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-5">
                  <Detail label="worker" value={execution.worker_id ?? '—'} />
                  <Detail label="stdout" value={`${execution.stdout_bytes} B`} />
                  <Detail label="stderr" value={`${execution.stderr_bytes} B`} />
                  <Detail
                    label="finished"
                    value={
                      execution.finished_at
                        ? new Date(execution.finished_at).toISOString().slice(11, 19)
                        : '—'
                    }
                  />
                  <Detail label="status" value={style.label} />
                </dl>

                {hasError ? (
                  <>
                    <div className="mb-2 mt-3.5 text-xs font-semibold text-fg-dim">
                      Error — attempt #{execution.attempt_number}
                    </div>
                    <pre className="m-0 overflow-x-auto whitespace-pre rounded-lg border border-failed/[0.18] bg-failed/[0.06] px-3.5 py-3 font-mono text-[11.5px] leading-[1.65] text-failed-text">
                      {execution.error_message}
                    </pre>
                  </>
                ) : null}

                {/* SHU urinishning loglari — job'ning barcha loglari emas */}
                <AttemptLogs logs={logs} executionId={execution.id} />
              </div>
            ) : null}
          </div>
        )
      })}
    </div>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">{label}</dt>
      <dd className="tabular mt-0.5 font-mono text-sm text-fg-soft">{value}</dd>
    </div>
  )
}

/**
 * Bitta urinishning loglari.
 *
 * Nega alohida: "Logs" tabi job'ning BARCHA urinishlari loglarini aralash
 * ko'rsatadi. Xatoni tahlil qilayotgan odam esa "aynan 3-urinishda nima
 * bo'ldi?" degan savolga javob izlaydi — shuning uchun bu yerda faqat
 * `execution_id` mos keladigan qatorlar chiqadi.
 */
function AttemptLogs({ logs, executionId }: { logs?: JobLog[]; executionId: string }) {
  const mine = (logs ?? []).filter((log) => log.execution_id === executionId)
  if (mine.length === 0) return null

  return (
    <>
      <div className="mb-2 mt-3.5 flex items-center gap-2 text-xs font-semibold text-fg-dim">
        Logs
        <span className="rounded-sm bg-surface-3 px-1.5 py-px font-mono text-2xs text-fg-faint">
          {mine.length}
        </span>
      </div>
      <div className="max-h-[220px] overflow-auto rounded-lg border border-line-inner bg-canvas-deep py-2 font-mono text-xs leading-[1.7]">
        {mine.map((log, index) => (
          <div key={log.id} className="flex items-baseline px-0">
            <span className="w-[38px] shrink-0 select-none pr-2.5 text-right text-fg-ghost">
              {index + 1}
            </span>
            <span className="mr-2.5 shrink-0 text-fg-faint">{formatLogTime(log.timestamp)}</span>
            <span
              className={cn(
                'mr-2.5 w-[48px] shrink-0 text-2xs font-semibold',
                log.stream === 'stderr'
                  ? 'text-failed'
                  : log.stream === 'system'
                    ? 'text-accent-light'
                    : 'text-fg-faint',
              )}
            >
              {log.stream === 'system' ? 'durabl' : log.stream}
            </span>
            <span
              className={cn(
                'min-w-0 whitespace-pre-wrap break-words pr-3',
                log.stream === 'stderr' ? 'text-failed-text' : 'text-fg-soft',
              )}
            >
              {log.content}
            </span>
          </div>
        ))}
      </div>
    </>
  )
}
