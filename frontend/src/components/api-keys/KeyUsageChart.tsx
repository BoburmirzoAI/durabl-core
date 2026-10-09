'use client'

import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { ChartFrame } from '@/components/analytics/ChartFrame'
import {
  AXIS_TICK,
  ChartTooltip,
  DASHED_CURSOR,
  type RechartsTooltipProps,
} from '@/components/analytics/ChartTooltip'
import { formatNumber } from '@/lib/utils/format'
import type { ApiKeyUsagePoint } from '@/types'

/**
 * Kalitning 30 kunlik so'rov grafigi.
 *
 * ## Nega so'rov + xato bitta grafikda
 *
 * "Kalit ishlayaptimi?" va "kalit xato qaytaryaptimi?" — bir savolning
 * ikki yarmi. Ularni ajratsa, foydalanuvchi ikki grafikni ko'z bilan
 * solishtirishga majbur bo'ladi. Shuning uchun so'rovlar maydon, xatolar
 * esa ustun sifatida ustiga qo'yilgan: xato cho'qqisi darhol ko'rinadi.
 *
 * Grafik kalit yaratilishidan oldingi kunlarda nol bo'ladi — bu mock
 * generatorda ataylab shunday, chunki yangi kalit 30 kunlik tarixga ega
 * bo'lishi mumkin emas.
 */
interface Point extends ApiKeyUsagePoint {
  label: string
}

function TooltipContent({ active, payload }: RechartsTooltipProps<Point>) {
  if (!active || !payload?.length) return null
  const point = payload[0]?.payload
  if (!point) return null
  const errorRate = point.requests === 0 ? 0 : (point.errors / point.requests) * 100
  return (
    <ChartTooltip
      heading={point.date}
      rows={[
        { label: 'Requests', value: formatNumber(point.requests), dotClassName: 'bg-accent' },
        { label: 'Errors', value: formatNumber(point.errors), dotClassName: 'bg-failed' },
        { label: 'Error rate', value: `${errorRate.toFixed(1)}%`, dotClassName: 'bg-fg-ghost' },
      ]}
    />
  )
}

export function KeyUsageChart({
  daily,
  loading,
  error,
  onRetry,
}: {
  daily: ApiKeyUsagePoint[] | undefined
  loading?: boolean
  error?: unknown
  onRetry?: () => void
}) {
  const points: Point[] = (daily ?? []).map((p) => ({ ...p, label: p.date.slice(5) }))
  const total = points.reduce((sum, p) => sum + p.requests, 0)

  return (
    <ChartFrame
      compact
      title="Requests — last 30 days"
      description="Requests authenticated with this key, with 4xx/5xx overlaid"
      height={170}
      loading={loading}
      error={error}
      onRetry={onRetry}
      isEmpty={total === 0}
      emptyLabel="This key has never been used"
    >
      <ResponsiveContainer width="100%" height={170}>
        <ComposedChart data={points} margin={{ top: 6, right: 4, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="keyUsageFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(var(--accent))" stopOpacity={0.3} />
              <stop offset="100%" stopColor="hsl(var(--accent))" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="hsl(var(--surface-4))" />
          <XAxis
            dataKey="label"
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            minTickGap={24}
          />
          <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={44} />
          <Tooltip content={<TooltipContent />} cursor={DASHED_CURSOR} animationDuration={120} />
          <Area
            type="monotone"
            dataKey="requests"
            stroke="hsl(var(--accent))"
            strokeWidth={1.6}
            fill="url(#keyUsageFill)"
            isAnimationActive={false}
          />
          <Bar
            dataKey="errors"
            fill="hsl(var(--failed))"
            radius={[2, 2, 0, 0]}
            isAnimationActive={false}
            maxBarSize={7}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartFrame>
  )
}
