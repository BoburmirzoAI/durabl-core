'use client'

import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { RelativeTime } from '@/components/common/RelativeTime'
import { formatNumber } from '@/lib/utils/format'
import type { DlqStats } from '@/types'

/**
 * DLQ statistikasi — dizayndagi uch karta:
 * "Total in DLQ", "Added Today", "Most Common Error".
 *
 * Qo'shimcha to'rtinchi karta (eng qadimgi yozuv) kiritilgan: operator
 * uchun "qancha vaqt kutib turibdi" eng muhim signal.
 */
export function DlqStatsCards({
  stats,
  loading = false,
}: {
  stats: DlqStats | undefined
  loading?: boolean
}) {
  if (loading && !stats) {
    return (
      <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <Card key={i} radius="xl" className="px-4 py-[15px]">
            <Skeleton className="h-3 w-28" />
            <Skeleton className="mt-3 h-6 w-20" />
          </Card>
        ))}
      </div>
    )
  }

  if (!stats) return null

  return (
    <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
      <Tile label="Total in DLQ" value={formatNumber(stats.total)} />
      <Tile
        label="Added Today"
        value={formatNumber(stats.added_last_24h)}
        valueClassName={stats.added_last_24h > 0 ? 'text-failed' : undefined}
      />
      <Card radius="xl" className="px-4 py-[15px]">
        <div className="text-xs font-semibold uppercase tracking-[.05em] text-fg-dim">
          Most Common Error
        </div>
        {stats.top_error ? (
          <div className="mt-[11px] flex items-baseline gap-2.5">
            <span className="font-mono text-xl font-semibold text-pending">
              {stats.top_error.type}
            </span>
            <span className="tabular font-mono text-base text-fg-dim">
              ×{stats.top_error.count}
            </span>
          </div>
        ) : (
          <div className="mt-[11px] font-mono text-xl font-semibold text-fg-faint">—</div>
        )}
      </Card>
      <Card radius="xl" className="px-4 py-[15px]">
        <div className="text-xs font-semibold uppercase tracking-[.05em] text-fg-dim">
          Oldest Unresolved
        </div>
        <div className="mt-[11px] font-mono text-xl font-semibold text-fg">
          {stats.oldest_failed_at ? (
            <RelativeTime value={stats.oldest_failed_at} />
          ) : (
            <span className="text-fg-faint">—</span>
          )}
        </div>
      </Card>
    </div>
  )
}

function Tile({
  label,
  value,
  valueClassName,
}: {
  label: string
  value: string
  valueClassName?: string
}) {
  return (
    <Card radius="xl" className="px-4 py-[15px]">
      <div className="text-xs font-semibold uppercase tracking-[.05em] text-fg-dim">{label}</div>
      <div
        className={`tabular mt-[11px] font-mono text-4xl font-semibold tracking-[-.02em] ${
          valueClassName ?? 'text-fg'
        }`}
      >
        {value}
      </div>
    </Card>
  )
}
