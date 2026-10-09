'use client'

import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils/cn'
import { trendClass } from '@/lib/utils/status'
import type { KpiData, StatCardData } from '@/types'

/**
 * Statistika kartasi — dizayndagi ko'rinish:
 * yuqorida kichik katta-harfli yorliq, pastda 28px mono qiymat,
 * eng pastda trend + izoh.
 *
 * `is_alert` bo'lsa qiymat qizil (DLQ Depth > 0 holati).
 */
export interface StatCardProps {
  data: StatCardData
  loading?: boolean
  /** Bosilganda o'tish (DLQ kartasi DLQ sahifasiga olib boradi). */
  onClick?: () => void
  className?: string
}

export function StatCard({ data, loading = false, onClick, className }: StatCardProps) {
  if (loading) {
    return (
      <Card radius="xl" className="px-4 py-[15px]">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="mt-3 h-7 w-28" />
        <Skeleton className="mt-2.5 h-3 w-32" />
      </Card>
    )
  }

  const body = (
    <>
      <div className="text-xs font-semibold uppercase tracking-[.05em] text-fg-dim">
        {data.label}
      </div>
      <div
        className={cn(
          'tabular mt-3 font-mono text-5xl font-semibold tracking-[-.02em]',
          data.is_alert ? 'text-failed' : 'text-fg',
        )}
      >
        {data.value}
      </div>
      <div className="mt-2.5 flex items-center gap-1.5 text-sm">
        <span
          className={cn(
            'tabular font-mono font-medium',
            trendClass(data.trend_direction, data.trend_is_good),
          )}
        >
          {data.trend}
        </span>
        <span className="text-fg-faint">{data.sub}</span>
      </div>
    </>
  )

  // Bosiladigan karta `button` bo'ladi (klaviatura va skrinrider uchun),
  // oddiy karta esa `div` — ortiqcha interaktiv element yasamaymiz.
  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={cn(
          'rounded-xl border border-line bg-surface px-4 py-[15px] text-left transition-colors hover:border-line-hover',
          className,
        )}
      >
        {body}
      </button>
    )
  }

  return (
    <Card radius="xl" interactive className={cn('px-4 py-[15px]', className)}>
      {body}
    </Card>
  )
}

/**
 * KPI kartasi — statistika kartasi + sparkline (analitika sahifasi).
 *
 * Sparkline Recharts'siz: oddiy `polyline` yetarli va 10 baravar yengil
 * (sahifada to'rtta karta bor).
 */
export function KpiCard({ data, loading = false }: { data: KpiData; loading?: boolean }) {
  if (loading) {
    return (
      <Card radius="xl" className="px-4 py-[15px]">
        <Skeleton className="h-3 w-24" />
        <Skeleton className="mt-3 h-7 w-28" />
        <Skeleton className="mt-3 h-8 w-full" />
      </Card>
    )
  }

  const values = data.sparkline
  const max = Math.max(...values, 1)
  const min = Math.min(...values, 0)
  const span = max - min || 1
  const points = values
    .map((value, i) => {
      const x = (i / Math.max(1, values.length - 1)) * 100
      const y = 28 - ((value - min) / span) * 24
      return `${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')

  return (
    <Card radius="xl" interactive className="px-4 py-[15px]">
      <div className="text-xs font-semibold uppercase tracking-[.05em] text-fg-dim">
        {data.label}
      </div>
      <div
        className={cn(
          'tabular mt-3 font-mono text-4xl font-semibold tracking-[-.02em]',
          data.is_alert ? 'text-failed' : 'text-fg',
        )}
      >
        {data.value}
      </div>
      <div className="mt-2 flex items-end justify-between gap-3">
        <span className="flex items-center gap-1.5 text-sm">
          <span
            className={cn(
              'tabular font-mono font-medium',
              trendClass(data.trend_direction, data.trend_is_good),
            )}
          >
            {data.trend}
          </span>
          <span className="text-fg-faint">{data.sub}</span>
        </span>
        <svg
          viewBox="0 0 100 32"
          preserveAspectRatio="none"
          className="h-8 w-[88px] shrink-0"
          aria-hidden
        >
          <polyline
            points={points}
            fill="none"
            stroke={data.is_alert ? 'hsl(var(--failed))' : 'hsl(var(--accent))'}
            strokeWidth="1.6"
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        </svg>
      </div>
    </Card>
  )
}
