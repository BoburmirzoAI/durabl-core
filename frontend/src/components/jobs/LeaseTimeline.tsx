'use client'

import { Card } from '@/components/ui/card'
import { EmptyState } from '@/components/common/EmptyState'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils/cn'
import { formatDurationShort } from '@/lib/utils/format'
import { formatLogTime } from '@/lib/utils/time'
import type { JobLeaseHistory, LeaseEventKind } from '@/types'

/**
 * Lease va heartbeat vaqt o'qi.
 *
 * ## Nega bu sahifa muhim
 *
 * "Worker o'lsa job yo'qolmaydi" — bizning asosiy va'damiz. Lekin uni
 * so'z bilan aytish kifoya emas: foydalanuvchi MEXANIZMNI ko'rishi kerak.
 * Bu ro'yxat aynan shuni ko'rsatadi:
 *
 *   acquired -> renewed x N -> released        (normal yakun)
 *   acquired -> renewed x N -> expired -> reaped  (worker o'ldi, job tiklandi)
 *
 * `expired` + `reaped` juftligi — bizning differensiatsiyamizning
 * ko'rinadigan isboti.
 */
const KIND_STYLE: Record<
  LeaseEventKind,
  { label: string; dot: string; text: string; icon: string }
> = {
  acquired: {
    label: 'Lease acquired',
    dot: 'bg-accent',
    text: 'text-fg',
    icon: 'M5 12l5 5 9-11',
  },
  renewed: {
    label: 'Heartbeat',
    dot: 'bg-running',
    text: 'text-fg-soft',
    icon: 'M3 12h4l3 8 4-16 3 8h4',
  },
  expired: {
    label: 'Lease expired',
    dot: 'bg-failed',
    text: 'text-failed-text',
    icon: 'M12 8v5M12 16h.01M12 3 2 20h20z',
  },
  reaped: {
    label: 'Re-queued by reaper',
    dot: 'bg-pending',
    text: 'text-pending',
    icon: 'M4 4v6h6M20 20v-6h-6M20 9a8 8 0 0 0-14-3M4 15a8 8 0 0 0 14 3',
  },
  released: {
    label: 'Lease released',
    dot: 'bg-success',
    text: 'text-fg-soft',
    icon: 'M5 12l5 5 9-11',
  },
  lost: {
    label: 'Lease lost',
    dot: 'bg-failed',
    text: 'text-failed-text',
    icon: 'M6 6l12 12M18 6 6 18',
  },
}

export function LeaseTimeline({
  data,
  loading = false,
}: {
  data: JobLeaseHistory | undefined
  loading?: boolean
}) {
  if (loading && !data) {
    return (
      <Card className="p-4">
        <Skeleton className="h-4 w-40" />
        <div className="mt-4 space-y-2.5">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      </Card>
    )
  }

  if (!data || data.events.length === 0) {
    return (
      <EmptyState
        icon="M12 8v4l3 3M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18z"
        title="No lease activity yet"
        description="A lease appears once a worker claims this job."
      />
    )
  }

  // Urinish bo'yicha guruhlaymiz — har bir urinish alohida lease hayoti
  const byAttempt = new Map<number, typeof data.events>()
  for (const event of data.events) {
    const list = byAttempt.get(event.attempt_number) ?? []
    list.push(event)
    byAttempt.set(event.attempt_number, list)
  }

  return (
    <div className="space-y-4">
      {/* Xulosa */}
      <div className="grid gap-px overflow-hidden rounded-xl border border-line bg-line-subtle sm:grid-cols-4">
        <Summary label="Lease TTL" value={`${data.ttl_seconds}s`} />
        <Summary label="Heartbeat" value={`every ${data.heartbeat_interval_seconds}s`} />
        <Summary label="Renewals" value={String(data.total_renewals)} />
        <Summary
          label="Re-assignments"
          value={String(data.reassignments)}
          tone={data.reassignments > 0 ? 'warn' : 'good'}
        />
      </div>

      {data.reassignments > 0 ? (
        <div className="flex items-start gap-2.5 rounded-xl border border-pending/25 bg-pending/[0.07] px-4 py-3">
          <svg
            width="17"
            height="17"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.9"
            strokeLinecap="round"
            strokeLinejoin="round"
            className="mt-0.5 shrink-0 text-pending"
            aria-hidden
          >
            <path d="M12 3 2 20h20zM12 10v4M12 17h.01" />
          </svg>
          <div className="min-w-0 text-sm">
            <div className="font-medium text-fg">
              This job was re-assigned {data.reassignments} time{data.reassignments === 1 ? '' : 's'}
            </div>
            <div className="mt-0.5 text-fg-dim">
              The worker stopped sending heartbeats, its lease expired, and the reaper handed the
              job to another worker. The job was{' '}
              <span className="font-medium text-fg-soft">never lost</span> — this is exactly the
              mechanism that saved it.
            </div>
          </div>
        </div>
      ) : null}

      {/* Urinishlar bo'yicha vaqt o'qi */}
      {[...byAttempt.entries()].map(([attempt, events]) => (
        <Card key={attempt} className="overflow-hidden">
          <div className="flex items-center gap-2 border-b border-line-inner px-4 py-2.5">
            <span className="text-sm font-medium text-fg">Attempt {attempt}</span>
            <span className="font-mono text-xs text-fg-faint">{events[0]?.worker_id}</span>
            <span className="ml-auto text-xs text-fg-faint">{events.length} events</span>
          </div>

          <div className="p-4">
            <ol className="relative space-y-0">
              {events.map((event, index) => {
                const style = KIND_STYLE[event.kind]
                const isLast = index === events.length - 1
                return (
                  <li key={event.id} className="relative flex gap-3 pb-3 last:pb-0">
                    {/* Ulovchi chiziq */}
                    {!isLast ? (
                      <span
                        className="absolute left-[11px] top-6 h-full w-px bg-line"
                        aria-hidden
                      />
                    ) : null}

                    <span
                      className={cn(
                        'relative z-10 mt-0.5 flex h-[22px] w-[22px] shrink-0 items-center justify-center rounded-full border border-line bg-surface',
                      )}
                    >
                      <span className={cn('h-1.5 w-1.5 rounded-full', style.dot)} aria-hidden />
                    </span>

                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-0.5">
                        <span className={cn('text-sm font-medium', style.text)}>{style.label}</span>
                        <span className="tabular font-mono text-xs text-fg-faint">
                          {formatLogTime(event.at)}
                        </span>
                        {event.since_previous_ms !== null ? (
                          <span className="tabular font-mono text-2xs text-fg-ghost">
                            +{formatDurationShort(event.since_previous_ms)}
                          </span>
                        ) : null}
                        {event.expires_at ? (
                          <span className="rounded-sm bg-surface-3 px-1.5 py-px font-mono text-2xs text-fg-dim">
                            expires {formatLogTime(event.expires_at)}
                          </span>
                        ) : null}
                      </div>
                      {event.note ? (
                        <div className="mt-0.5 text-xs text-fg-dim">{event.note}</div>
                      ) : null}
                    </div>
                  </li>
                )
              })}
            </ol>
          </div>
        </Card>
      ))}
    </div>
  )
}

function Summary({
  label,
  value,
  tone = 'default',
}: {
  label: string
  value: string
  tone?: 'default' | 'good' | 'warn'
}) {
  return (
    <div className="bg-surface px-4 py-3">
      <div className="text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">{label}</div>
      <div
        className={cn(
          'tabular mt-1.5 font-mono text-lg',
          tone === 'warn' ? 'text-pending' : tone === 'good' ? 'text-success' : 'text-fg',
        )}
      >
        {value}
      </div>
    </div>
  )
}
