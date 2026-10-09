'use client'

import Link from 'next/link'

import { DetailDrawer, DrawerSection } from '@/components/common/DetailDrawer'
import { JobStatusBadge } from '@/components/jobs/JobStatusBadge'
import { MonoId } from '@/components/common/MonoId'
import { Button } from '@/components/ui/button'
import { useJobs } from '@/lib/hooks/useJobs'
import { formatDuration, formatNumber } from '@/lib/utils/format'
import { customRange, formatTimestamp } from '@/lib/utils/time'
import type { ThroughputPoint } from '@/types'

/**
 * Grafik nuqtasidan job'larga drill-down.
 *
 * ## Qanday ishlaydi
 *
 * Grafikdagi har bir nuqta — vaqt OYNASI (masalan 30 daqiqa). Nuqta
 * bosilganda shu oynaga tushgan job'lar `custom:<from>|<to>` oraliq
 * filtri bilan so'raladi. Aynan shu filtr `/jobs` sahifasida ham ishlaydi,
 * shuning uchun "View in Jobs" tugmasi bir xil natijani beradi.
 *
 * ## Nega sonlar har doim ham mos tushmaydi
 *
 * Grafik — AGREGAT (backend tomonda hisoblangan), ro'yxat esa saqlangan
 * job yozuvlari. Mock rejimida saqlangan job'lar agregat sonidan kam,
 * shuning uchun panel buni yashirmaydi: "showing N of M" deb yoziladi.
 */
export function WindowDrilldown({
  point,
  /** Oynaning uzunligi (daqiqa) — grafik qadamiga teng. */
  stepMinutes,
  onOpenChange,
}: {
  point: ThroughputPoint | null
  stepMinutes: number
  onOpenChange: (open: boolean) => void
}) {
  const to = point ? new Date(point.timestamp).getTime() : 0
  const from = to - stepMinutes * 60_000
  const range = point ? customRange(new Date(from), new Date(to)) : ''

  const jobs = useJobs(
    { range, page_size: 15, sort_by: 'created_at', sort_order: 'desc' },
    { autoRefresh: false },
  )

  const total = point ? point.completed + point.failed : 0
  const successRate = total === 0 ? 0 : Math.round((point!.completed / total) * 1_000) / 10
  const stored = jobs.data?.pagination.total ?? 0

  return (
    <DetailDrawer
      open={point !== null}
      onOpenChange={onOpenChange}
      width="md"
      title={point ? `Window ${point.label}` : ''}
      description={
        point
          ? `${formatTimestamp(new Date(from).toISOString())} → ${formatTimestamp(point.timestamp)}`
          : ''
      }
      stats={
        point
          ? [
              { label: 'Jobs', value: formatNumber(total) },
              { label: 'Completed', value: formatNumber(point.completed), tone: 'good' },
              {
                label: 'Failed',
                value: formatNumber(point.failed),
                tone: point.failed > 0 ? 'bad' : 'default',
              },
              {
                label: 'Success',
                value: `${successRate}%`,
                tone: successRate >= 99 ? 'good' : successRate >= 95 ? 'warn' : 'bad',
              },
            ]
          : undefined
      }
      loading={jobs.isLoading}
      error={jobs.error}
      onRetry={() => void jobs.refetch()}
      footer={
        point ? (
          <div className="flex w-full items-center gap-2">
            <span className="min-w-0 flex-1 text-xs text-fg-faint">
              {stepMinutes}-minute window
            </span>
            <Button variant="ghost" onClick={() => onOpenChange(false)}>
              Close
            </Button>
            <Button asChild variant="secondary">
              <Link href={`/jobs?range=${encodeURIComponent(range)}`}>View in Jobs →</Link>
            </Button>
          </div>
        ) : null
      }
    >
      <DrawerSection title={`Jobs in this window — showing ${jobs.data?.items.length ?? 0} of ${formatNumber(stored)} stored`}>
        {(jobs.data?.items.length ?? 0) === 0 ? (
          <p className="text-sm leading-[1.6] text-fg-dim">
            No stored job records fall inside this window. The chart above is an aggregate
            counter — individual job rows are only retained for recent activity.
          </p>
        ) : (
          <div className="space-y-px">
            {jobs.data?.items.map((job) => (
              <Link
                key={job.id}
                href={`/jobs/${job.id}`}
                className="flex items-center gap-3 rounded-md px-2 py-2 transition-colors hover:bg-surface-3"
              >
                <JobStatusBadge status={job.status} />
                <MonoId value={job.id} copyable={false} className="shrink-0" />
                <span className="min-w-0 flex-1 truncate text-sm text-fg-dim">{job.runtime}</span>
                <span className="tabular shrink-0 font-mono text-xs text-fg-faint">
                  {formatDuration(job.duration_ms)}
                </span>
              </Link>
            ))}
          </div>
        )}
      </DrawerSection>

      {total > 0 && stored < total ? (
        <p className="mt-3 text-xs leading-[1.6] text-fg-ghost">
          The aggregate counted {formatNumber(total)} jobs in this window;{' '}
          {formatNumber(stored)} detailed records are still available.
        </p>
      ) : null}
    </DetailDrawer>
  )
}
