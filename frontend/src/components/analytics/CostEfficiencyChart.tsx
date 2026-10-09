'use client'

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { formatCurrency, formatNumber } from '@/lib/utils/format'
import type { CostEfficiencySeries } from '@/types'

import { AXIS_TICK, ChartTooltip, DASHED_CURSOR, type RechartsTooltipProps } from './ChartTooltip'
import { ChartFrame } from './ChartFrame'

/**
 * Job narxi tendensiyasi.
 *
 * ## Nega `/usage` dan ajratilgan
 *
 * `/usage` — "hisobim qancha". Bu esa "bir xil ishni qilish
 * QIMMATLASHYAPTIMI". Umumiy xarajat o'sishi mumkin, chunki ish ko'paygan —
 * bu yomon emas. Yomoni: ish o'zgarmagani holda BIR JOB qimmatlashsa.
 *
 * Shuning uchun o'qda mutlaq dollar emas, job boshiga narx turadi.
 */
interface Point {
  label: string
  cost_per_job: number
  jobs: number
  cost_usd: number
  compute_seconds_per_job: number
}

function TooltipContent({ active, payload }: RechartsTooltipProps<Point>) {
  if (!active || !payload?.length) return null
  const point = payload[0]?.payload
  if (!point) return null
  return (
    <ChartTooltip
      heading={point.label}
      rows={[
        {
          label: 'Cost per job',
          value: `$${point.cost_per_job.toFixed(6)}`,
          dotClassName: 'bg-accent',
        },
        { label: 'Jobs', value: formatNumber(point.jobs), dotClassName: 'bg-fg-ghost' },
        {
          label: 'Compute / job',
          value: `${point.compute_seconds_per_job}s`,
          dotClassName: 'bg-fg-ghost',
        },
      ]}
    />
  )
}

export function CostEfficiencyChart({
  data,
  loading,
  error,
  onRetry,
}: {
  data: CostEfficiencySeries | undefined
  loading?: boolean
  error?: unknown
  onRetry?: () => void
}) {
  const worse = (data?.change_percent ?? 0) > 0
  const wastedShare =
    data && data.total_usd > 0 ? Math.round((data.wasted_usd / data.total_usd) * 100) : 0

  return (
    <ChartFrame
      compact
      title="Cost per job"
      description="Is the same unit of work getting more expensive?"
      height={200}
      loading={loading}
      error={error}
      onRetry={onRetry}
      isEmpty={(data?.points.length ?? 0) === 0}
      aside={
        data ? (
          <div className="flex items-center gap-5 text-xs">
            <span className="flex items-baseline gap-1.5">
              <span className="text-fg-faint">vs previous</span>
              <span className={`tabular font-mono ${worse ? 'text-failed-text' : 'text-success'}`}>
                {worse ? '↑' : '↓'} {Math.abs(data.change_percent)}%
              </span>
            </span>
            <span className="flex items-baseline gap-1.5">
              <span className="text-fg-faint">Wasted on failures</span>
              <span className="tabular font-mono text-pending">
                {formatCurrency(data.wasted_usd)} ({wastedShare}%)
              </span>
            </span>
          </div>
        ) : null
      }
    >
      <ResponsiveContainer width="100%" height={200}>
        <AreaChart data={data?.points ?? []} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="costFill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(var(--accent))" stopOpacity={0.28} />
              <stop offset="100%" stopColor="hsl(var(--accent))" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid vertical={false} stroke="hsl(var(--surface-4))" />
          <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={28} />
          <YAxis
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={62}
            tickFormatter={(v: number) => `$${v.toFixed(5)}`}
          />
          <Tooltip content={<TooltipContent />} cursor={DASHED_CURSOR} animationDuration={120} />
          <Area
            type="monotone"
            dataKey="cost_per_job"
            stroke="hsl(var(--accent))"
            strokeWidth={1.6}
            fill="url(#costFill)"
            isAnimationActive={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </ChartFrame>
  )
}
