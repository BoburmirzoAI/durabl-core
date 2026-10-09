'use client'

import Link from 'next/link'

import { RelativeTime } from '@/components/common/RelativeTime'
import { SkeletonRows } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/common/EmptyState'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils/cn'
import { formatDuration } from '@/lib/utils/format'
import { jobStatusStyle, runtimeStyle } from '@/lib/utils/status'
import type { SlowJobRow } from '@/types'

const GRID = 'minmax(130px,1.3fr) 80px 90px 90px minmax(80px,1fr)'

/**
 * Eng sekin job'lar.
 *
 * "Medianadan necha barobar sekin" ustuni muhim: 40 soniya o'z-o'zidan
 * yomon emas, lekin ayni runtime medianasi 2 soniya bo'lsa — bu anomaliya.
 */
export function SlowestJobsTable({
  rows,
  loading,
}: {
  rows: SlowJobRow[] | undefined
  loading?: boolean
}) {
  return (
    <Card className="overflow-hidden p-0">
      <CardHeader className="px-4 pb-3 pt-[15px]">
        <CardTitle className="text-md">Slowest jobs</CardTitle>
        <span className="text-xs text-fg-dim">Outliers worth investigating</span>
      </CardHeader>

      <div className="table-head grid items-center px-4" style={{ gridTemplateColumns: GRID }}>
        <span>Job</span>
        <span>Runtime</span>
        <span className="text-right">Duration</span>
        <span className="text-right">vs median</span>
        <span>Created</span>
      </div>

      {loading && !rows ? (
        <SkeletonRows rows={6} columns={GRID} />
      ) : !rows || rows.length === 0 ? (
        <EmptyState icon="M12 8v5M12 16h.01" title="Nothing slow enough to flag" tone="positive" />
      ) : (
        rows.map((row) => {
          const status = jobStatusStyle(row.status)
          const runtime = runtimeStyle(row.runtime)
          return (
            <Link
              key={row.id}
              href={`/jobs/${row.id}`}
              className="grid h-11 items-center border-b border-line-subtle px-4 transition-colors last:border-b-0 hover:bg-surface-3"
              style={{ gridTemplateColumns: GRID }}
            >
              <span className="flex min-w-0 items-center gap-2">
                <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', status.dot)} aria-hidden />
                <span className="truncate font-mono text-sm text-fg-bright">{row.id}</span>
              </span>
              <span className={cn('text-xs', runtime.text)}>{row.runtime}</span>
              <span className="tabular text-right font-mono text-sm text-failed">
                {formatDuration(row.duration_ms)}
              </span>
              <span
                className={cn(
                  'tabular text-right font-mono text-sm',
                  row.slower_than_median >= 5 ? 'text-failed' : 'text-pending',
                )}
              >
                {row.slower_than_median}×
              </span>
              <RelativeTime value={row.created_at} className="text-xs text-fg-faint" />
            </Link>
          )
        })
      )}
    </Card>
  )
}
