'use client'

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatNumber } from '@/lib/utils/format'
import type { RetryRateSeries } from '@/types'

import { AXIS_TICK, ChartTooltip, DASHED_CURSOR, type RechartsTooltipProps } from './ChartTooltip'
import { ChartFrame } from './ChartFrame'

/**
 * Qayta urinish tendensiyasi.
 *
 * ## Nega bu grafik muvaffaqiyat foizidan muhimroq
 *
 * Muvaffaqiyat foizi 99.5% bo'lishi mumkin — lekin agar shuning yarmi
 * 3-urinishdan kelayotgan bo'lsa, foydalanuvchi kechikishni his qiladi
 * va siz hisob vaqtini ikki marta to'laysiz. Shuning uchun BIRINCHI
 * urinishdagi muvaffaqiyat alohida chiziq sifatida ko'rsatiladi: ikki
 * chiziq orasidagi masofa — aynan "yashirin xarajat".
 */
function TooltipContent({ active, payload }: RechartsTooltipProps<RetryRateSeries['points'][number]>) {
  if (!active || !payload?.length) return null
  const point = payload[0]?.payload
  if (!point) return null
  return (
    <ChartTooltip
      heading={point.label}
      rows={[
        {
          label: 'First-attempt success',
          value: `${point.first_attempt_success}%`,
          dotClassName: 'bg-success',
        },
        { label: 'Retry rate', value: `${point.retry_rate}%`, dotClassName: 'bg-pending' },
        { label: 'Retried jobs', value: formatNumber(point.retried), dotClassName: 'bg-fg-ghost' },
      ]}
    />
  )
}

export function RetryRateChart({
  data,
  loading,
  error,
  onRetry,
}: {
  data: RetryRateSeries | undefined
  loading?: boolean
  error?: unknown
  onRetry?: () => void
}) {
  return (
    <ChartFrame
      compact
      title="Retry rate"
      description="How often work has to be done twice"
      height={210}
      loading={loading}
      error={error}
      onRetry={onRetry}
      isEmpty={(data?.points.length ?? 0) === 0}
      aside={
        data ? (
          <div className="flex items-center gap-5 text-xs">
            <Stat label="Avg attempts" value={data.avg_attempts.toFixed(2)} />
            <Stat
              label="Wasted compute"
              value={`${formatNumber(Math.round(data.wasted_compute_seconds / 60))}m`}
              tone="warn"
            />
          </div>
        ) : null
      }
    >
      <ResponsiveContainer width="100%" height={210}>
        <ComposedChart data={data?.points ?? []} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="retryFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(var(--pending))" stopOpacity={0.26} />
              <stop offset="100%" stopColor="hsl(var(--pending))" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="hsl(var(--surface-4))" />
          <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={28} />
          <YAxis
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={44}
            domain={[0, 100]}
            tickFormatter={(v: number) => `${v}%`}
          />
          <Tooltip content={<TooltipContent />} cursor={DASHED_CURSOR} animationDuration={120} />
          <Area
            type="monotone"
            dataKey="retry_rate"
            stroke="hsl(var(--pending))"
            strokeWidth={1.6}
            fill="url(#retryFill)"
            isAnimationActive={false}
          />
          <Line
            type="monotone"
            dataKey="first_attempt_success"
            stroke="hsl(var(--success))"
            strokeWidth={1.6}
            dot={false}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartFrame>
  )
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: 'warn' }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="text-fg-faint">{label}</span>
      <span className={`tabular font-mono ${tone === 'warn' ? 'text-pending' : 'text-fg-soft'}`}>
        {value}
      </span>
    </span>
  )
}
