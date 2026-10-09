'use client'

import { Badge } from '@/components/ui/badge'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/common/EmptyState'
import { SkeletonRows } from '@/components/ui/skeleton'
import { formatDuration, formatNumber } from '@/lib/utils/format'
import type { WorkerEfficiency } from '@/types'

const GRID = 'minmax(110px,1fr) 86px 84px minmax(140px,1.4fr) 84px 92px'

/**
 * Worker samaradorligi.
 *
 * ## Nega "soatiga nechta job", "o'rtacha davomiylik" emas
 *
 * O'rtacha davomiylik workerning ishini emas, JOB'larning og'irligini
 * o'lchaydi. Soatiga bajarilgan ish esa workerlarni yonma-yon solishtirish
 * imkonini beradi: bir xil navbatdan oladigan ikki worker har xil tezlikda
 * ishlasa — biri nosoz.
 *
 * `spread` (eng tez / eng sekin) shuning uchun sarlavhada turadi.
 */
export function WorkerEfficiencyTable({
  data,
  loading,
}: {
  data: WorkerEfficiency | undefined
  loading?: boolean
}) {
  const best = data?.rows.find((r) => r.state !== 'dead')?.jobs_per_hour ?? 1

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div className="flex flex-wrap items-start gap-4">
          <div>
            <CardTitle className="text-md">Worker efficiency</CardTitle>
            <CardDescription>Throughput per worker, not per job</CardDescription>
          </div>
          {data ? (
            <div className="ml-auto flex items-center gap-5 text-xs">
              <span className="flex items-baseline gap-1.5">
                <span className="text-fg-faint">Fleet utilisation</span>
                <span className="tabular font-mono text-fg-soft">{data.fleet_utilisation}%</span>
              </span>
              <span className="flex items-baseline gap-1.5">
                <span className="text-fg-faint">Fastest / slowest</span>
                <span
                  className={`tabular font-mono ${data.spread > 2 ? 'text-pending' : 'text-fg-soft'}`}
                >
                  {data.spread}×
                </span>
              </span>
            </div>
          ) : null}
        </div>
      </CardHeader>

      <div className="table-head grid items-center gap-3 px-4" style={{ gridTemplateColumns: GRID }}>
        <span>Worker</span>
        <span className="text-right">Jobs/hour</span>
        <span className="text-right">Avg time</span>
        <span>Utilisation</span>
        <span className="text-right">Failures</span>
        <span className="text-right">Leases lost</span>
      </div>

      {loading && !data ? (
        <SkeletonRows rows={4} columns={GRID} />
      ) : !data || data.rows.length === 0 ? (
        <EmptyState
          icon="M4 7h16M4 12h16M4 17h10"
          title="No workers"
          description="Start a worker to see efficiency data."
        />
      ) : (
        data.rows.map((row) => (
          <div
            key={row.worker_id}
            className="grid h-11 items-center gap-3 border-b border-line-subtle px-4 last:border-b-0 hover:bg-surface-3"
            style={{ gridTemplateColumns: GRID }}
          >
            <span className="flex min-w-0 items-center gap-2">
              <span className="truncate font-mono text-xs text-fg-soft" title={row.worker_id}>
                {row.region}
              </span>
              {row.state === 'dead' ? (
                <Badge variant="danger" size="sm">
                  dead
                </Badge>
              ) : null}
            </span>

            <span
              className={`tabular text-right font-mono text-sm ${
                row.state !== 'dead' && row.jobs_per_hour < best * 0.6
                  ? 'text-pending'
                  : 'text-fg-muted'
              }`}
            >
              {formatNumber(row.jobs_per_hour)}
            </span>

            <span className="tabular text-right font-mono text-sm text-fg-faint">
              {formatDuration(row.avg_duration_ms)}
            </span>

            <span className="flex items-center gap-2">
              <span className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-surface-4">
                <span
                  className={`block h-full rounded-full ${
                    row.utilisation > 90 ? 'bg-pending' : 'bg-accent'
                  }`}
                  style={{ width: `${row.utilisation}%` }}
                />
              </span>
              <span className="tabular w-9 shrink-0 text-right font-mono text-2xs text-fg-faint">
                {row.utilisation}%
              </span>
            </span>

            <span
              className={`tabular text-right font-mono text-sm ${
                row.failure_rate > 4 ? 'text-failed-text' : 'text-fg-faint'
              }`}
            >
              {row.failure_rate}%
            </span>

            <span
              className={`tabular text-right font-mono text-sm ${
                row.lease_losses > 0 ? 'text-failed-text' : 'text-fg-ghost'
              }`}
            >
              {row.lease_losses}
            </span>
          </div>
        ))
      )}
    </Card>
  )
}
