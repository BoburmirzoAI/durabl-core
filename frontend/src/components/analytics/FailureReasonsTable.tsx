'use client'

import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/common/EmptyState'
import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils/cn'
import { formatNumber, formatPercent } from '@/lib/utils/format'
import { trendClass } from '@/lib/utils/status'
import type { FailureReasonRow } from '@/types'

/** Eng ko'p uchraydigan xato sabablari — dizayndagi oxirgi jadval. */
export function FailureReasonsTable({ rows }: { rows: FailureReasonRow[] | undefined }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">Top Failure Reasons</CardTitle>
      </CardHeader>

      {!rows || rows.length === 0 ? (
        <EmptyState
          tone="positive"
          icon="M5 12l5 5 9-11"
          title="No failures in this range"
          description="Every job completed successfully."
        />
      ) : (
        <>
          <div
            className="table-head grid items-center"
            style={{ gridTemplateColumns: 'minmax(140px,1.4fr) 72px 1fr 78px' }}
          >
            <span>Reason</span>
            <span className="text-right">Count</span>
            <span>Share</span>
            <span className="text-right">Trend</span>
          </div>
          {rows.map((row) => (
            <div
              key={row.reason}
              className="grid h-11 items-center gap-3 border-b border-line-subtle px-3.5 last:border-b-0"
              style={{ gridTemplateColumns: 'minmax(140px,1.4fr) 72px 1fr 78px' }}
            >
              <span className="truncate font-mono text-sm text-fg-soft" title={row.label}>
                {row.label}
              </span>
              <span className="tabular text-right font-mono text-sm text-fg-muted">
                {formatNumber(row.count)}
              </span>
              <span className="flex items-center gap-2.5">
                <Progress value={row.percent} size="xs" barClassName="bg-failed" />
                <span className="tabular w-10 shrink-0 text-right font-mono text-xs text-fg-faint">
                  {formatPercent(row.percent)}
                </span>
              </span>
              <span
                className={cn(
                  'tabular text-right font-mono text-sm',
                  trendClass(row.trend.startsWith('↑') ? 'up' : 'down', row.trend_is_good),
                )}
              >
                {row.trend}
              </span>
            </div>
          ))}
        </>
      )}
    </Card>
  )
}
