'use client'

import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatDate } from '@/lib/utils/time'
import { formatPercent } from '@/lib/utils/format'
import type { SuccessRateSeries } from '@/types'

import { AXIS_TICK, ChartTooltip, DASHED_CURSOR, type RechartsTooltipProps } from './ChartTooltip'
import { ChartFrame } from './ChartFrame'

/**
 * Muvaffaqiyat foizi tendensiyasi.
 *
 * Dizaynda maqsad chizig'i (99%) uzuq-uzuq sariq chiziq bilan ko'rsatilgan —
 * `ReferenceLine` shuni beradi. Y o'qi 100% dan boshlanmaydi: farqlar
 * 98–100% orasida bo'lgani uchun to'liq shkala tekis chiziq ko'rsatardi.
 */
interface Point {
  label: string
  full: string
  value: number
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
          label: 'Success rate',
          value: formatPercent(point.value),
          dotClassName: 'bg-accent',
        },
      ]}
    />
  )
}

export function SuccessRateChart({
  data,
  loading,
  error,
  onRetry,
}: {
  data: SuccessRateSeries | undefined
  loading?: boolean
  error?: unknown
  onRetry?: () => void
}) {
  const points: Point[] = (data?.points ?? []).map((p) => ({
    label: new Date(p.timestamp).toISOString().slice(5, 10),
    full: formatDate(p.timestamp),
    value: p.value,
  }))

  const values = points.map((p) => p.value)
  const floor = values.length ? Math.floor(Math.min(...values, data?.target ?? 99) * 2) / 2 - 0.5 : 97

  return (
    <ChartFrame
      compact
      title="Success Rate Trend"
      description={`Daily success % vs ${data?.target ?? 99}% target`}
      height={200}
      loading={loading}
      error={error}
      onRetry={onRetry}
      isEmpty={points.length === 0}
      aside={
        data ? (
          <span className="tabular font-mono text-md font-semibold text-fg">
            {formatPercent(data.current)}
          </span>
        ) : null
      }
    >
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="hsl(var(--surface-4))" />
          <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={20} />
          <YAxis
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={42}
            domain={[floor, 100]}
            tickFormatter={(value: number) => `${value}%`}
          />
          <Tooltip content={<TooltipContent />} cursor={DASHED_CURSOR} animationDuration={120} />
          {data ? (
            <ReferenceLine
              y={data.target}
              stroke="hsl(var(--pending))"
              strokeDasharray="4 4"
              strokeWidth={1.5}
            />
          ) : null}
          <Line
            type="monotone"
            dataKey="value"
            stroke="hsl(var(--accent))"
            strokeWidth={2}
            dot={{ r: 2.6, fill: 'hsl(var(--accent))', strokeWidth: 0 }}
            activeDot={{ r: 4.5, fill: 'hsl(var(--accent))', stroke: 'hsl(var(--canvas))', strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </ChartFrame>
  )
}
