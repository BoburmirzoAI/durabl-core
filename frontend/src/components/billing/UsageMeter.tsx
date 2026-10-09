'use client'

import { Progress } from '@/components/ui/progress'
import { cn } from '@/lib/utils/cn'
import { formatPercent } from '@/lib/utils/format'
import { usageLevelClass } from '@/lib/utils/status'
import type { UsageMeterData } from '@/types'

/**
 * Foydalanish o'lchagichi — dizayndagi ko'rinish:
 * yorliq, `284K / 500K` qiymati, progress bar.
 *
 * 80% dan oshsa sariq, 100% da qizil — foydalanuvchi limitga
 * yetayotganini OLDIN bilishi kerak.
 */
export function UsageMeter({
  meter,
  onOpenDetail,
}: {
  meter: UsageMeterData
  /** Berilsa karta bosiladigan bo'ladi va kvota tafsilotini ochadi. */
  onOpenDetail?: (meter: UsageMeterData) => void
}) {
  const Tag = onOpenDetail ? 'button' : 'div'
  return (
    <Tag
      {...(onOpenDetail
        ? {
            type: 'button' as const,
            onClick: () => onOpenDetail(meter),
            'aria-label': `${meter.label} usage details`,
          }
        : {})}
      className={cn(
        'rounded-xl border border-line bg-surface px-4 py-[15px] text-left',
        onOpenDetail &&
          'w-full cursor-pointer transition-colors hover:border-line-hover hover:bg-surface-2 focus-visible:border-accent-edge-2 focus-visible:outline-none',
      )}
    >
      <div className="flex items-baseline gap-2">
        <span className="text-xs font-semibold uppercase tracking-[.05em] text-fg-dim">
          {meter.label}
        </span>
        <span
          className={cn(
            'tabular ml-auto font-mono text-xs',
            meter.level === 'over'
              ? 'text-failed'
              : meter.level === 'warn'
                ? 'text-pending'
                : 'text-fg-faint',
          )}
        >
          {formatPercent(meter.percent)}
        </span>
      </div>

      <div className="tabular mt-2.5 font-mono text-lg font-semibold text-fg">
        {meter.current_label}{' '}
        <span className="font-normal text-fg-faint">/ {meter.limit_label}</span>
      </div>

      <Progress
        value={meter.percent}
        size="md"
        barClassName={usageLevelClass(meter.level)}
        className="mt-3"
        aria-label={`${meter.label}: ${meter.current_label} of ${meter.limit_label}`}
      />

      {meter.level === 'over' ? (
        <div className="mt-2 text-xs text-failed">Limit reached — new jobs are rejected</div>
      ) : meter.level === 'warn' ? (
        <div className="mt-2 text-xs text-pending">Approaching your plan limit</div>
      ) : null}

      {onOpenDetail ? (
        <div className="mt-2 text-xs text-fg-ghost">Click for breakdown →</div>
      ) : null}
    </Tag>
  )
}
