'use client'

import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { formatCurrency, formatNumber } from '@/lib/utils/format'
import type { PeriodComparison, PeriodMetric } from '@/types'

/**
 * Joriy davr vs oldingi teng davr.
 *
 * ## Nega "teng uzunlik" muhim
 *
 * 7 kunni 30 kun bilan solishtirish ma'nosiz — ikkinchisida ko'proq job
 * bo'lishi aniq. Shuning uchun oldingi oyna joriy oynadan AYNAN shuncha
 * oldin boshlanadi va bir xil uzunlikda bo'ladi.
 *
 * ## Nega yo'nalish rangi ko'rsatkichga bog'liq
 *
 * O'tkazuvchanlikning o'sishi — yaxshi. Kechikish yoki xarajatning
 * o'sishi — yomon. Bitta "yashil = o'sish" qoidasi noto'g'ri xulosa
 * beradi, shuning uchun har bir ko'rsatkichda `higher_is_better` bor.
 */
function formatValue(metric: PeriodMetric): string {
  switch (metric.unit) {
    case 'percent':
      return `${metric.current}%`
    case 'ms':
      return `${formatNumber(Math.round(metric.current))} ms`
    case 'usd':
      return metric.current < 0.01 ? `$${metric.current.toFixed(6)}` : formatCurrency(metric.current)
    default:
      return formatNumber(Math.round(metric.current))
  }
}

function formatPrevious(metric: PeriodMetric): string {
  switch (metric.unit) {
    case 'percent':
      return `${metric.previous}%`
    case 'ms':
      return `${formatNumber(Math.round(metric.previous))} ms`
    case 'usd':
      return metric.previous < 0.01
        ? `$${metric.previous.toFixed(6)}`
        : formatCurrency(metric.previous)
    default:
      return formatNumber(Math.round(metric.previous))
  }
}

export function ComparisonStrip({
  data,
  loading,
}: {
  data: PeriodComparison | undefined
  loading?: boolean
}) {
  if (loading && !data) {
    return (
      <Card className="p-4">
        <Skeleton className="h-[72px] w-full" />
      </Card>
    )
  }
  if (!data) return null

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center gap-2 border-b border-line-inner px-4 py-2.5">
        <span className="text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">
          {data.current_label} vs {data.previous_label}
        </span>
      </div>
      <div className="grid gap-px bg-line-subtle sm:grid-cols-3 xl:grid-cols-6">
        {data.metrics.map((metric) => {
          const delta = metric.change_percent
          const flat = delta === null || Math.abs(delta) < 0.1
          const good = delta !== null && (delta > 0) === metric.higher_is_better
          const tone = flat ? 'text-fg-dim' : good ? 'text-success' : 'text-failed-text'
          return (
            <div key={metric.key} className="bg-surface px-4 py-3">
              <div className="text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">
                {metric.label}
              </div>
              <div className="tabular mt-1.5 font-mono text-lg text-fg">{formatValue(metric)}</div>
              <div className="mt-1 flex items-baseline gap-1.5 text-xs">
                <span className={`tabular font-mono ${tone}`}>
                  {flat ? '—' : `${delta > 0 ? '↑' : '↓'} ${Math.abs(delta)}%`}
                </span>
                <span className="tabular font-mono text-fg-ghost">
                  from {formatPrevious(metric)}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}
