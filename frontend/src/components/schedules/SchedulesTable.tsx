'use client'

import { Badge } from '@/components/ui/badge'
import { EmptyState } from '@/components/common/EmptyState'
import { RelativeTime } from '@/components/common/RelativeTime'
import { SkeletonRows } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useRunScheduleNow, useSetScheduleEnabled } from '@/lib/hooks/useSchedules'
import { cn } from '@/lib/utils/cn'
import { formatTimestamp } from '@/lib/utils/time'
import type { Schedule } from '@/types'

const GRID = 'minmax(190px,1.6fr) minmax(130px,1fr) 130px 130px 92px 46px 44px'

/**
 * Jadvallar ro'yxati.
 *
 * ## Nega "keyingi ishga tushish" eng muhim ustun
 *
 * Jadval sahifasiga kiradigan odamning birinchi savoli — "bu qachon
 * ishlaydi?". Shuning uchun keyingi vaqt aniq ko'rsatiladi, cron ifodasi
 * esa uning yonida izoh sifatida turadi.
 *
 * To'xtatilgan jadvalda keyingi vaqt YO'Q — "—" ko'rsatiladi, chunki
 * bo'lmagan vaqtni ko'rsatish yolg'on bo'lardi.
 */
export function SchedulesTable({
  schedules,
  loading,
  onOpenDetail,
  onEdit,
  onDelete,
  onCreate,
}: {
  schedules: Schedule[] | undefined
  loading?: boolean
  onOpenDetail: (schedule: Schedule) => void
  onEdit: (schedule: Schedule) => void
  onDelete: (schedule: Schedule) => void
  onCreate?: () => void
}) {
  const setEnabled = useSetScheduleEnabled()
  const runNow = useRunScheduleNow()

  return (
    <div className="overflow-hidden rounded-2xl border border-line bg-surface">
      <div className="table-head grid items-center gap-3 px-4" style={{ gridTemplateColumns: GRID }}>
        <span>Schedule</span>
        <span>Cron</span>
        <span>Next run</span>
        <span>Last run</span>
        <span className="text-right">Success</span>
        <span className="text-center">On</span>
        <span className="sr-only">Actions</span>
      </div>

      {loading && !schedules ? (
        <SkeletonRows rows={4} columns={GRID} />
      ) : !schedules || schedules.length === 0 ? (
        <EmptyState
          icon="M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z"
          title="No schedules yet"
          description="Run a job on a cron instead of calling the API yourself."
          action={
            onCreate ? (
              <button
                type="button"
                onClick={onCreate}
                className="text-sm font-medium text-accent hover:text-accent-light"
              >
                Create your first schedule →
              </button>
            ) : null
          }
        />
      ) : (
        schedules.map((schedule) => {
          const successRate =
            schedule.total_runs === 0
              ? null
              : Math.round(((schedule.total_runs - schedule.failed_runs) / schedule.total_runs) * 1_000) / 10
          const broken = schedule.status === 'errored'
          return (
            <div
              key={schedule.id}
              role="button"
              tabIndex={0}
              onClick={() => onOpenDetail(schedule)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' || event.key === ' ') {
                  event.preventDefault()
                  onOpenDetail(schedule)
                }
              }}
              className="grid h-[54px] cursor-pointer items-center gap-3 border-b border-line-subtle px-4 last:border-b-0 transition-colors hover:bg-surface-3 focus-visible:bg-surface-3 focus-visible:outline-none"
              style={{ gridTemplateColumns: GRID }}
            >
              <span className="min-w-0">
                <span className="flex items-center gap-2">
                  <span className="truncate text-base text-fg-soft">{schedule.name}</span>
                  {broken ? (
                    <Badge variant="danger" size="sm">
                      {schedule.consecutive_failures} fails
                    </Badge>
                  ) : null}
                </span>
                <span className="block truncate text-xs text-fg-faint">
                  {schedule.description ?? `${schedule.runtime} · ${schedule.priority} priority`}
                </span>
              </span>

              <span className="truncate font-mono text-xs text-fg-muted" title={schedule.cron}>
                {schedule.cron}
              </span>

              <span className="min-w-0">
                {schedule.next_run_at ? (
                  <>
                    <RelativeTime
                      value={schedule.next_run_at}
                      className="block truncate text-sm text-fg-soft"
                    />
                    <span className="block truncate text-2xs text-fg-ghost">
                      {formatTimestamp(schedule.next_run_at).replace(' UTC', '')}
                    </span>
                  </>
                ) : (
                  <span className="text-sm text-fg-ghost">— paused</span>
                )}
              </span>

              <span className="min-w-0">
                <RelativeTime
                  value={schedule.last_run_at}
                  className="block truncate text-sm text-fg-muted"
                />
                {schedule.last_run_status ? (
                  <span
                    className={cn(
                      'block truncate text-2xs',
                      schedule.last_run_status === 'success' ? 'text-success' : 'text-failed-text',
                    )}
                  >
                    {schedule.last_run_status}
                  </span>
                ) : null}
              </span>

              <span
                className={cn(
                  'tabular text-right font-mono text-sm',
                  successRate === null
                    ? 'text-fg-ghost'
                    : successRate >= 95
                      ? 'text-fg-muted'
                      : 'text-failed-text',
                )}
              >
                {successRate === null ? '—' : `${successRate}%`}
              </span>

              <span className="flex justify-center" onClick={(event) => event.stopPropagation()}>
                <Switch
                  checked={schedule.status !== 'paused'}
                  disabled={setEnabled.isPending}
                  onCheckedChange={(enabled) => setEnabled.mutate({ id: schedule.id, enabled })}
                  aria-label={`${schedule.name} enabled`}
                />
              </span>

              <span className="flex justify-end">
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button
                      type="button"
                      aria-label={`Actions for ${schedule.name}`}
                      onClick={(event) => event.stopPropagation()}
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
                    <DropdownMenuItem onSelect={() => onOpenDetail(schedule)}>
                      View runs
                    </DropdownMenuItem>
                    <DropdownMenuItem onSelect={() => onEdit(schedule)}>Edit</DropdownMenuItem>
                    <DropdownMenuItem
                      disabled={runNow.isPending}
                      onSelect={() => runNow.mutate(schedule.id)}
                    >
                      Run now
                    </DropdownMenuItem>
                    <DropdownMenuItem danger onSelect={() => onDelete(schedule)}>
                      Delete
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </span>
            </div>
          )
        })
      )}
    </div>
  )
}

/** Sarlavhadagi ixcham tugma ikonkasi. */
export function ScheduleIcon() {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}
