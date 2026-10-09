'use client'

import { formatNumber, formatPercent } from '@/lib/utils/format'
import { cn } from '@/lib/utils/cn'
import { runtimeStyle } from '@/lib/utils/status'
import type { RuntimeShare } from '@/types'

import { ChartFrame } from './ChartFrame'

/**
 * Runtime ulushi — donut.
 *
 * Qo'lda SVG: faqat ikki segment bor va `stroke-dasharray` bilan
 * aniq boshqarish osonroq (Recharts `PieChart` qo'shimcha 40KB olib
 * keladi va bir xil ko'rinish uchun ko'p sozlash kerak).
 */
export function RuntimeDonut({
  data,
  loading,
  error,
  onRetry,
}: {
  data: RuntimeShare[] | undefined
  loading?: boolean
  error?: unknown
  onRetry?: () => void
}) {
  const total = (data ?? []).reduce((sum, d) => sum + d.count, 0)
  const radius = 54
  const circumference = 2 * Math.PI * radius

  let offset = 0
  const segments = (data ?? []).map((share) => {
    const length = (share.percent / 100) * circumference
    const segment = {
      runtime: share.runtime,
      length,
      offset,
      color:
        share.runtime === 'python' ? 'hsl(var(--running))' : 'hsl(var(--success))',
    }
    offset += length
    return segment
  })

  return (
    <ChartFrame
      compact
      title="Jobs by Runtime"
      description="Share of total executions"
      height={200}
      loading={loading}
      error={error}
      onRetry={onRetry}
      isEmpty={total === 0}
    >
      <div className="flex items-center gap-6">
        <svg viewBox="0 0 140 140" className="h-[140px] w-[140px] shrink-0 -rotate-90" aria-hidden>
          <circle
            cx="70"
            cy="70"
            r={radius}
            fill="none"
            stroke="hsl(var(--line-inner))"
            strokeWidth="14"
          />
          {segments.map((segment) => (
            <circle
              key={segment.runtime}
              cx="70"
              cy="70"
              r={radius}
              fill="none"
              stroke={segment.color}
              strokeWidth="14"
              strokeDasharray={`${segment.length} ${circumference - segment.length}`}
              strokeDashoffset={-segment.offset}
              strokeLinecap="butt"
            />
          ))}
        </svg>

        <div className="flex min-w-0 flex-1 flex-col gap-3">
          {(data ?? []).map((share) => {
            const style = runtimeStyle(share.runtime)
            return (
              <div key={share.runtime} className="flex items-center gap-2.5">
                <span className={cn('h-2.5 w-2.5 shrink-0 rounded-sm', style.dot)} />
                <span className="flex-1 text-base text-fg-soft">{style.label}</span>
                <span className="tabular font-mono text-md font-semibold text-fg">
                  {formatPercent(share.percent)}
                </span>
                <span className="tabular w-14 shrink-0 text-right font-mono text-xs text-fg-faint">
                  {formatNumber(share.count)}
                </span>
              </div>
            )
          })}
        </div>
      </div>
    </ChartFrame>
  )
}
