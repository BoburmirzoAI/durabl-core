'use client'

import { cn } from '@/lib/utils/cn'
import { formatNumber } from '@/lib/utils/format'

/**
 * Grafik tooltip'i — dizayndagi ko'rinish:
 * `#1C1C20` fon, `#33333A` chegara, 8px radius, katta soya,
 * yuqorida mono vaqt, pastda rangli nuqta + nom + qiymat.
 */
export interface TooltipRow {
  label: string
  value: number | string
  /** Nuqta rangi klassi. */
  dotClassName: string
  /** Qiymatga qo'shiladigan birlik (`ms`, `%`). */
  suffix?: string
}

export interface ChartTooltipProps {
  /** Yuqoridagi sarlavha (odatda vaqt). */
  heading?: string
  rows: TooltipRow[]
  className?: string
}

export function ChartTooltip({ heading, rows, className }: ChartTooltipProps) {
  return (
    <div
      className={cn(
        'pointer-events-none min-w-[132px] rounded-lg border border-line-hover bg-surface-4 px-2.5 py-2 shadow-tooltip',
        className,
      )}
    >
      {heading ? (
        <div className="mb-1.5 font-mono text-xs text-fg-dim">{heading}</div>
      ) : null}
      {rows.map((row) => (
        <div key={row.label} className="flex items-center gap-[7px] text-sm last:mb-0 [&:not(:last-child)]:mb-1">
          <span className={cn('h-[7px] w-[7px] rounded-sm', row.dotClassName)} />
          <span className="flex-1 text-fg-muted">{row.label}</span>
          <span className="tabular font-mono font-semibold text-fg">
            {typeof row.value === 'number' ? formatNumber(row.value) : row.value}
            {row.suffix ?? ''}
          </span>
        </div>
      ))}
    </div>
  )
}

/** Recharts `Tooltip` uchun umumiy o'ram turi. */
export interface RechartsTooltipProps<T> {
  active?: boolean
  payload?: { payload: T }[]
  label?: string | number
}

/** Dizayndagi uzuq-uzuq vertikal kursor chizig'i. */
export const DASHED_CURSOR = {
  stroke: 'hsl(var(--fg-faint))',
  strokeWidth: 1,
  strokeDasharray: '3 3',
} as const

/** O'q yorliqlari uslubi (mono, 11px, kulrang). */
export const AXIS_TICK = {
  fill: 'hsl(var(--fg-faint))',
  fontSize: 11,
  fontFamily: 'var(--font-mono), monospace',
} as const
