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

import { formatDuration } from '@/lib/utils/format'
import type { LatencyPercentileSeries } from '@/types'

import { AXIS_TICK, ChartTooltip, DASHED_CURSOR, type RechartsTooltipProps } from './ChartTooltip'
import { ChartFrame } from './ChartFrame'

/**
 * Kechikish persentillari vaqt bo'ylab.
 *
 * Nega gistogramma yetmaydi: gistogramma BIR LAHZADAGI taqsimotni beradi,
 * bu grafik esa "p99 qachon yomonlashdi" degan savolga javob beradi.
 * p99 alohida chiziq bo'lishi muhim — o'rtacha kechikish yaxshi ko'rinib
 * turganda ham dumdagi foydalanuvchilar azob chekayotgan bo'lishi mumkin.
 */
interface Point {
  t: string
  p50: number
  p90: number
  p99: number
}

const SERIES = [
  { key: 'p50' as const, label: 'p50 (median)', color: 'var(--success)', dot: 'bg-success' },
  { key: 'p90' as const, label: 'p90', color: 'var(--pending)', dot: 'bg-pending' },
  { key: 'p99' as const, label: 'p99 (tail)', color: 'var(--failed)', dot: 'bg-failed' },
]

function TooltipContent({ active, payload }: RechartsTooltipProps<Point>) {
  if (!active || !payload?.length) return null
  const point = payload[0]?.payload
  if (!point) return null
  return (
    <ChartTooltip
      heading={point.t}
      rows={SERIES.map((s) => ({
        label: s.label,
        value: formatDuration(point[s.key]),
        dotClassName: s.dot,
      }))}
    />
  )
}

export function LatencyPercentileChart({
  data,
  loading,
  error,
  onRetry,
}: {
  data: LatencyPercentileSeries | undefined
  loading?: boolean
  error?: unknown
  onRetry?: () => void
}) {
  const points = data?.points ?? []

  return (
    <ChartFrame
      title="Latency percentiles"
      description="p50 / p90 / p99 over time — the tail is what users feel"
      height={260}
      loading={loading}
      error={error}
      onRetry={onRetry}
      isEmpty={points.length === 0}
      aside={
        <div className="flex items-center gap-3">
          {SERIES.map((s) => (
            <span key={s.key} className="flex items-center gap-1.5 text-xs text-fg-dim">
              <span className={`h-1.5 w-1.5 rounded-full ${s.dot}`} aria-hidden />
              {s.key}
            </span>
          ))}
        </div>
      }
    >
      <ResponsiveContainer width="100%" height={260}>
        <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="hsl(var(--surface-4))" />
          <XAxis dataKey="t" tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={28} />
          <YAxis
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={52}
            tickFormatter={(value: number) => (value >= 1000 ? `${(value / 1000).toFixed(1)}s` : `${value}ms`)}
          />
          <Tooltip content={<TooltipContent />} cursor={DASHED_CURSOR} animationDuration={120} />
          {data ? (
            <ReferenceLine
              y={data.sla_ms}
              stroke="hsl(var(--fg-faint))"
              strokeDasharray="4 4"
              strokeWidth={1.4}
              label={{
                value: `SLA ${formatDuration(data.sla_ms)}`,
                position: 'insideTopRight',
                fill: 'hsl(var(--fg-faint))',
                fontSize: 10,
              }}
            />
          ) : null}
          {SERIES.map((s) => (
            <Line
              key={s.key}
              type="monotone"
              dataKey={s.key}
              stroke={`hsl(${s.color})`}
              strokeWidth={s.key === 'p99' ? 2 : 1.6}
              dot={false}
              activeDot={{ r: 3.5, strokeWidth: 0 }}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </ChartFrame>
  )
}
