'use client'

import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils/cn'
import { formatDurationShort } from '@/lib/utils/format'
import { formatTimestamp } from '@/lib/utils/time'
import type { JobTimeline as TimelineData, JobTimelineStep } from '@/types'

/**
 * Hayot sikli stepper — dizayndagi gorizontal qadamlar.
 *
 * Har qadam: 32px dumaloq ikonka + chiziq + yorliq/vaqt/o'tgan vaqt.
 * Holat ranglari: bajarilgan — aksent, joriy — ko'k pulsatsiya,
 * kutilayotgan — kulrang, xato — qizil.
 */
/**
 * Yakuniy qadam XATO bilan tugaganda ✓ emas, ✗ ko'rsatiladi.
 *
 * Ilgari ikonka faqat `step.key` bo'yicha tanlanardi, shuning uchun yiqilgan
 * job'da ham qizil doira ichida BELGI (✓) turardi — holatga qarama-qarshi.
 */
const STEP_ICON_FAILED = 'M6 6l12 12M18 6 6 18'

const STEP_ICONS: Record<JobTimelineStep['key'], string> = {
  submitted: 'M12 5v14M5 12h14',
  queued: 'M4 7h16M4 12h16M4 17h10',
  running: 'M5 3l14 9-14 9z',
  finished: 'M5 12l5 5 9-11',
  dlq: 'M12 3 2 20h20zM12 10v4M12 17h.01',
}

const STATE_STYLES: Record<
  JobTimelineStep['state'],
  { circle: string; icon: string; label: string; line: string }
> = {
  done: {
    circle: 'border-accent/40 bg-accent/[0.12]',
    icon: 'text-accent',
    label: 'text-fg',
    line: 'bg-accent/40',
  },
  current: {
    circle: 'border-running/50 bg-running/[0.14]',
    icon: 'text-running',
    label: 'text-fg',
    line: 'bg-line',
  },
  pending: {
    circle: 'border-line bg-surface-2',
    icon: 'text-fg-ghost',
    label: 'text-fg-faint',
    line: 'bg-line',
  },
  error: {
    circle: 'border-failed/45 bg-failed/[0.12]',
    icon: 'text-failed',
    label: 'text-failed',
    line: 'bg-failed/40',
  },
}

export function JobTimeline({
  timeline,
  loading = false,
}: {
  timeline: TimelineData | undefined
  loading?: boolean
}) {
  return (
    <Card className="px-5 py-[18px]">
      <div className="mb-4 flex items-center gap-4">
        <span className="text-base font-semibold text-fg-soft">Lifecycle</span>
        {timeline ? (
          <span className="ml-auto flex items-center gap-4 text-sm text-fg-dim">
            <span>
              queue wait{' '}
              <span className="tabular font-mono text-fg-muted">
                {formatDurationShort(timeline.queue_wait_ms)}
              </span>
            </span>
            <span>
              execution{' '}
              <span className="tabular font-mono text-fg-muted">
                {formatDurationShort(timeline.execution_ms)}
              </span>
            </span>
            <span>
              total{' '}
              <span className="tabular font-mono text-fg-muted">
                {formatDurationShort(timeline.total_ms)}
              </span>
            </span>
          </span>
        ) : null}
      </div>

      {loading && !timeline ? (
        <Skeleton className="h-16 w-full" />
      ) : (
        <div className="flex items-start overflow-x-auto pb-1">
          {(timeline?.steps ?? []).map((step, index, steps) => {
            const style = STATE_STYLES[step.state]
            const isLast = index === steps.length - 1
            return (
              <div key={step.key} className="flex min-w-[128px] flex-1 items-start">
                <div className="flex w-12 shrink-0 flex-col items-center">
                  <div
                    className={cn(
                      'flex h-8 w-8 items-center justify-center rounded-full border-[1.5px]',
                      style.circle,
                    )}
                  >
                    <svg
                      width="16"
                      height="16"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2.2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      className={style.icon}
                      aria-hidden
                    >
                      <path
                        d={
                          step.key === 'finished' && step.state === 'error'
                            ? STEP_ICON_FAILED
                            : STEP_ICONS[step.key]
                        }
                      />
                    </svg>
                  </div>
                </div>

                <div className="-ml-1.5 mr-1.5 min-w-0 flex-1">
                  <div className="flex h-8 items-center">
                    {!isLast ? (
                      <div className={cn('h-0.5 flex-1 rounded-sm', style.line)} />
                    ) : null}
                  </div>
                  <div className="mt-2 pl-0.5">
                    <div className={cn('text-sm font-semibold', style.label)}>{step.label}</div>
                    <div
                      className="mt-[3px] font-mono text-xs text-fg-faint"
                      title={step.timestamp ? formatTimestamp(step.timestamp) : undefined}
                    >
                      {step.timestamp
                        ? new Date(step.timestamp).toISOString().slice(11, 19)
                        : '—'}
                    </div>
                    {step.gap_ms !== null && step.gap_ms > 0 ? (
                      <div className="mt-0.5 font-mono text-2xs text-fg-faint">
                        +{formatDurationShort(step.gap_ms)}
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}
