'use client'

import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatDate } from '@/lib/utils/time'
import type { DlqDepthSeries } from '@/types'

import { AXIS_TICK, ChartTooltip, DASHED_CURSOR, type RechartsTooltipProps } from './ChartTooltip'
import { ChartFrame } from './ChartFrame'

/**
 * DLQ chuqurligi tendensiyasi — qizil maydon.
 *
 * Alert chegarasi (`threshold`) gorizontal chiziq bilan ko'rsatiladi:
 * operator chuqurlik chegaraga yaqinlashayotganini DARHOL ko'rishi kerak.
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
      rows={[{ label: 'DLQ depth', value: point.value, dotClassName: 'bg-failed' }]}
    />
  )
}

export function DlqDepthChart({
  data,
  loading,
  error,
  onRetry,
}: {
  data: DlqDepthSeries | undefined
  loading?: boolean
  error?: unknown
  onRetry?: () => void
}) {
  const points: Point[] = (data?.points ?? []).map((p) => ({
    label: new Date(p.timestamp).toISOString().slice(5, 10),
    full: formatDate(p.timestamp),
    value: p.value,
  }))

  // Chegara grafikda ko'rinishi uchun shkalani kengaytiramiz
  const showThreshold = Boolean(data && data.peak >= data.threshold * 0.5)

  return (
    <ChartFrame
      compact
      title="DLQ Depth Over Time"
      description="Unresolved entries waiting for action"
      height={200}
      loading={loading}
      error={error}
      onRetry={onRetry}
      isEmpty={points.length === 0}
      aside={
        data ? (
          <span className="tabular font-mono text-md font-semibold text-failed">{data.current}</span>
        ) : null
      }
    >
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="dlqGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(var(--failed))" stopOpacity={0.35} />
              <stop offset="100%" stopColor="hsl(var(--failed))" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="hsl(var(--surface-4))" />
          <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={20} />
          <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={42} allowDecimals={false} />
          <Tooltip content={<TooltipContent />} cursor={DASHED_CURSOR} animationDuration={120} />
          {showThreshold && data ? (
            <ReferenceLine
              y={data.threshold}
              stroke="hsl(var(--pending))"
              strokeDasharray="4 4"
              strokeWidth={1.5}
            />
          ) : null}
          <Area
            type="monotone"
            dataKey="value"
            stroke="hsl(var(--failed))"
            strokeWidth={1.8}
            fill="url(#dlqGradient)"
            activeDot={{ r: 4, fill: 'hsl(var(--failed))', stroke: 'hsl(var(--canvas))', strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </ChartFrame>
  )
}
