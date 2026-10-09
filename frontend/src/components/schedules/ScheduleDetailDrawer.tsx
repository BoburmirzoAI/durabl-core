'use client'

import Link from 'next/link'

import { DetailDrawer, DrawerRow, DrawerSection } from '@/components/common/DetailDrawer'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useRunScheduleNow, useScheduleRuns } from '@/lib/hooks/useSchedules'
import { formatDuration, formatNumber } from '@/lib/utils/format'
import { describeCron } from '@/lib/utils/cron'
import { formatTimestamp } from '@/lib/utils/time'
import { cn } from '@/lib/utils/cn'
import type { Schedule, ScheduleRun } from '@/types'

const STATUS_CLASS: Record<string, string> = {
  success: 'bg-success/[0.12] text-success',
  failed: 'bg-failed/[0.12] text-failed',
  running: 'bg-running/[0.12] text-running',
  skipped: 'bg-surface-4 text-fg-faint',
}

/**
 * Jadval tafsiloti — asosan ISHGA TUSHISHLAR TARIXI.
 *
 * ## Nega "scheduled" va "started" ikkalasi ham ko'rsatiladi
 *
 * Jadval 02:00 da ishga tushishi kerak edi, lekin navbat band bo'lgani
 * uchun 02:04 da boshlangan bo'lishi mumkin. Bu farq — "jadvalim
 * kechikyaptimi?" degan savolga javob, va u faqat ikkala vaqtni yonma-yon
 * ko'rsatganda ko'rinadi.
 */
export function ScheduleDetailDrawer({
  schedule,
  onOpenChange,
  onEdit,
}: {
  schedule: Schedule | null
  onOpenChange: (open: boolean) => void
  onEdit: (schedule: Schedule) => void
}) {
  const runs = useScheduleRuns(schedule?.id ?? null)
  const runNow = useRunScheduleNow()

  let description = ''
  if (schedule) {
    try {
      description = describeCron(schedule.cron)
    } catch {
      description = schedule.cron
    }
  }

  const successRate =
    schedule && schedule.total_runs > 0
      ? Math.round(((schedule.total_runs - schedule.failed_runs) / schedule.total_runs) * 1_000) / 10
      : null

  return (
    <DetailDrawer
      open={schedule !== null}
      onOpenChange={onOpenChange}
      width="lg"
      title={
        <span className="flex min-w-0 items-center gap-2.5">
          <span className="truncate">{schedule?.name}</span>
          {schedule?.status === 'errored' ? (
            <Badge variant="danger">Failing</Badge>
          ) : schedule?.status === 'paused' ? (
            <Badge className="bg-pending/[0.12] text-pending">Paused</Badge>
          ) : (
            <Badge variant="success">Active</Badge>
          )}
        </span>
      }
      description={description}
      stats={
        schedule
          ? [
              { label: 'Total runs', value: formatNumber(schedule.total_runs) },
              {
                label: 'Success',
                value: successRate === null ? '—' : `${successRate}%`,
                tone: successRate === null ? 'default' : successRate >= 95 ? 'good' : 'bad',
              },
              {
                label: 'Next run',
                value: schedule.next_run_at
                  ? formatTimestamp(schedule.next_run_at).replace(' UTC', '')
                  : 'paused',
                tone: schedule.next_run_at ? 'default' : 'warn',
              },
              {
                label: 'Failures in a row',
                value: String(schedule.consecutive_failures),
                tone: schedule.consecutive_failures > 0 ? 'bad' : 'default',
              },
            ]
          : undefined
      }
      loading={runs.isLoading}
      error={runs.error}
      onRetry={() => void runs.refetch()}
      footer={
        schedule ? (
          <div className="flex w-full items-center gap-2">
            <span className="min-w-0 flex-1 font-mono text-xs text-fg-faint">{schedule.cron}</span>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Close
            </Button>
            <Button variant="secondary" onClick={() => onEdit(schedule)}>
              Edit
            </Button>
            <Button
              variant="primary"
              disabled={runNow.isPending}
              onClick={() => runNow.mutate(schedule.id)}
            >
              {runNow.isPending ? 'Queuing…' : 'Run now'}
            </Button>
          </div>
        ) : null
      }
    >
      {schedule ? (
        <div className="space-y-3.5">
          {schedule.status === 'errored' ? (
            <div className="rounded-lg border border-failed/25 bg-failed/[0.07] px-3.5 py-3 text-sm leading-[1.55] text-failed-text">
              The last {schedule.consecutive_failures} runs failed. Durabl keeps retrying on the
              cron, but repeated failures usually mean the code or an upstream dependency changed —
              check the most recent run below.
            </div>
          ) : null}

          <DrawerSection title="Configuration">
            <DrawerRow label="Cron" value={schedule.cron} mono />
            <DrawerRow label="Time zone" value={schedule.timezone} />
            <DrawerRow label="Runtime" value={schedule.runtime} />
            <DrawerRow label="Priority" value={schedule.priority} />
            <DrawerRow label="Timeout" value={`${schedule.timeout_seconds}s`} />
            <DrawerRow label="Max retries" value={String(schedule.max_retries)} />
            <DrawerRow
              label="Overlapping runs"
              value={
                schedule.allow_overlap
                  ? 'Allowed — a new run starts even if the previous one is still going'
                  : 'Skipped — a run is dropped if the previous one is still going'
              }
            />
          </DrawerSection>

          <DrawerSection title={`Recent runs (${runs.data?.length ?? 0})`}>
            {(runs.data?.length ?? 0) === 0 ? (
              <p className="text-sm text-fg-dim">This schedule has not run yet.</p>
            ) : (
              <div className="space-y-px">
                {runs.data?.map((run) => (
                  <RunRow key={run.id} run={run} />
                ))}
              </div>
            )}
          </DrawerSection>
        </div>
      ) : null}
    </DetailDrawer>
  )
}

function RunRow({ run }: { run: ScheduleRun }) {
  // Rejalashtirilgan vaqt bilan boshlanish orasidagi kechikish
  const lagMs =
    run.started_at === null
      ? null
      : new Date(run.started_at).getTime() - new Date(run.scheduled_for).getTime()

  const body = (
    <>
      <span className="tabular w-[150px] shrink-0 font-mono text-xs text-fg-muted">
        {formatTimestamp(run.scheduled_for).replace(' UTC', '')}
      </span>
      <Badge size="sm" className={STATUS_CLASS[run.status] ?? 'bg-surface-4 text-fg-faint'}>
        {run.status}
      </Badge>
      <span className="min-w-0 flex-1 truncate text-xs text-fg-faint">
        {run.skip_reason ?? (lagMs !== null && lagMs > 2_000 ? `started ${Math.round(lagMs / 1_000)}s late` : '')}
      </span>
      <span className="tabular shrink-0 font-mono text-xs text-fg-faint">
        {formatDuration(run.duration_ms)}
      </span>
    </>
  )

  return run.job_id ? (
    <Link
      href={`/jobs/${run.job_id}`}
      className="flex items-center gap-2.5 rounded-md px-2 py-1.5 transition-colors hover:bg-surface-3"
    >
      {body}
    </Link>
  ) : (
    <div className={cn('flex items-center gap-2.5 rounded-md px-2 py-1.5 opacity-70')}>{body}</div>
  )
}
