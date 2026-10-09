'use client'

import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils/cn'
import type { CostProjection } from '@/types'

/**
 * Oy oxirigacha xarajat prognozi.
 *
 * Eng muhim savol: "shu sur'atda davom etsam, hisob qancha bo'ladi?"
 * Shuning uchun prognoz qiymati eng katta shrift bilan, sarflangan esa
 * yonida kichikroq ko'rsatiladi.
 */
export function CostProjectionCard({
  data,
  loading,
}: {
  data: CostProjection | undefined
  loading?: boolean
}) {
  if (loading || !data) {
    return (
      <Card radius="xl" className="px-4 py-[15px]">
        <Skeleton className="h-3 w-28" />
        <Skeleton className="mt-3 h-8 w-32" />
        <Skeleton className="mt-3 h-2 w-full" />
      </Card>
    )
  }

  const elapsed = data.days_total - data.days_remaining
  const progress = Math.min(100, Math.round((elapsed / data.days_total) * 100))

  return (
    <Card radius="xl" className="px-4 py-[15px]">
      <div className="flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-[.05em] text-fg-dim">
          Projected this month
        </span>
        {data.will_exceed ? (
          <span className="rounded-full bg-pending/[0.14] px-1.5 py-px text-2xs font-semibold text-pending">
            over plan
          </span>
        ) : null}
      </div>

      <div className="mt-3 flex items-baseline gap-2">
        <span
          className={cn(
            'tabular font-mono text-4xl font-semibold tracking-[-.02em]',
            data.will_exceed ? 'text-pending' : 'text-fg',
          )}
        >
          ${data.projected_usd.toFixed(2)}
        </span>
        <span className="text-sm text-fg-faint">
          ${data.spent_usd.toFixed(2)} so far
        </span>
      </div>

      {/* Davr qancha o'tgani */}
      <div className="mt-3.5 h-1 overflow-hidden rounded-sm bg-line">
        <div
          className="h-full rounded-sm bg-accent transition-[width] duration-500"
          style={{ width: `${progress}%` }}
        />
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-fg-faint">
        <span>
          Day {elapsed} of {data.days_total}
        </span>
        <span>
          {data.days_remaining === 0 ? 'resets today' : `resets in ${data.days_remaining}d`}
        </span>
      </div>

      <div className="mt-3.5 space-y-1.5 border-t border-line-subtle pt-3 text-sm">
        <div className="flex items-center justify-between">
          <span className="text-fg-dim">Plan base</span>
          <span className="tabular font-mono text-fg-soft">${data.base_usd.toFixed(2)}</span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-fg-dim">Projected overage</span>
          <span
            className={cn(
              'tabular font-mono',
              data.overage_usd > 0 ? 'text-pending' : 'text-fg-faint',
            )}
          >
            ${data.overage_usd.toFixed(2)}
          </span>
        </div>
      </div>
    </Card>
  )
}
