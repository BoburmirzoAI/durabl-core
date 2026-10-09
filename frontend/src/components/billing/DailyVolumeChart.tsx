'use client'

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { ChartFrame } from '@/components/analytics/ChartFrame'
import { AXIS_TICK, ChartTooltip, type RechartsTooltipProps } from '@/components/analytics/ChartTooltip'
import { formatCompact } from '@/lib/utils/format'
import { formatDate } from '@/lib/utils/time'
import type { DailyVolumePoint } from '@/types'

/**
 * Kunlik hajm ustunlari — dizayndagi billing grafigi.
 *
 * Kunlik limit uzuq-uzuq sariq chiziq bilan ko'rsatiladi; limitdan
 * oshgan kunlar qizil ustun bo'ladi.
 */
interface Point {
  label: string
  full: string
  count: number
  over: boolean
}

function TooltipContent({ active, payload }: RechartsTooltipProps<Point>) {
  if (!active || !payload?.length) return null
  const point = payload[0]?.payload
  if (!point) return null
  return (
    <ChartTooltip
      heading={point.full}
      rows={[
        {
          label: 'Jobs',
          value: point.count,
          dotClassName: point.over ? 'bg-failed' : 'bg-accent',
        },
      ]}
    />
  )
}

export function DailyVolumeChart({
  data,
  dailyLimit,
  loading,
  error,
  onRetry,
}: {
  data: DailyVolumePoint[] | undefined
  dailyLimit: number
  loading?: boolean
  error?: unknown
  onRetry?: () => void
}) {
  const points: Point[] = (data ?? []).map((p) => ({
    label: p.label,
    full: formatDate(p.date),
    count: p.count,
    over: p.over_limit,
  }))

  return (
    <ChartFrame
      compact
      title="Daily Job Volume"
      description="This month · dashed line = daily plan allowance"
      height={220}
      loading={loading}
      error={error}
      onRetry={onRetry}
      isEmpty={points.length === 0}
      aside={
        <span className="flex items-center gap-[7px] text-xs text-fg-dim">
          <span className="h-0 w-3.5 border-t-[1.5px] border-dashed border-pending" />
          Daily limit
        </span>
      }
    >
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="hsl(var(--surface-4))" />
          <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={8} />
          <YAxis
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={44}
            tickFormatter={(value: number) => formatCompact(value)}
          />
          <Tooltip
            content={<TooltipContent />}
            cursor={{ fill: 'hsl(var(--surface-3))' }}
            animationDuration={120}
          />
          <ReferenceLine
            y={dailyLimit}
            stroke="hsl(var(--pending))"
            strokeDasharray="4 4"
            strokeWidth={1.5}
          />
          <Bar dataKey="count" radius={[3, 3, 0, 0]} isAnimationActive={false}>
            {points.map((point, index) => (
              <Cell key={index} fill={point.over ? 'hsl(var(--failed))' : 'hsl(var(--accent))'} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  )
}
