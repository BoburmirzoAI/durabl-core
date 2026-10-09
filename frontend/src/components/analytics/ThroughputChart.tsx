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

import { formatCompact } from '@/lib/utils/format'
import type { ThroughputPoint, ThroughputSeries } from '@/types'

import { AXIS_TICK, ChartTooltip, DASHED_CURSOR, type RechartsTooltipProps } from './ChartTooltip'
import { ChartFrame, ChartLegend } from './ChartFrame'

/**
 * Throughput grafigi — dizayndagi asosiy grafik.
 *
 * Ko'rinish dizayndan aynan: binafsha gradientli maydon + binafsha
 * "Completed" chizig'i + ingichka qizil "Failed" chizig'i, uzuq-uzuq
 * vertikal kursor va aniq qiymatlarni ko'rsatadigan tooltip.
 *
 * RANG QARORI: dizayn faylida yuqori legenda "Completed" ni YASHIL
 * kvadrat bilan ko'rsatadi, lekin chiziqning o'zi va tooltip BINAFSHA
 * (`#8B5CF6`). Uchtadan ikkitasi binafsha bo'lgani uchun legenda ham
 * binafsha qilindi — aks holda yashil nishon binafsha chiziqqa ishora
 * qilib, foydalanuvchini chalg'itardi.
 */
export interface ThroughputChartProps {
  data: ThroughputSeries | undefined
  loading?: boolean
  error?: unknown
  onRetry?: () => void
  /** Sarlavha yonidagi oraliq tanlagich. */
  aside?: React.ReactNode
  height?: number
  title?: string
  description?: string
  /**
   * Grafikdagi nuqta tanlanganda chaqiriladi (drill-down).
   *
   * Berilmasa grafik oddiy ko'rsatkich bo'lib qoladi — mavjud
   * chaqiruvlar o'zgarmaydi.
   */
  onSelectPoint?: (point: ThroughputPoint) => void
}

interface Point {
  label: string
  completed: number
  failed: number
}

function TooltipContent({ active, payload }: RechartsTooltipProps<Point>) {
  if (!active || !payload?.length) return null
  const point = payload[0]?.payload
  if (!point) return null
  return (
    <ChartTooltip
      heading={point.label}
      rows={[
        { label: 'Completed', value: point.completed, dotClassName: 'bg-accent' },
        { label: 'Failed', value: point.failed, dotClassName: 'bg-failed' },
      ]}
    />
  )
}

export function ThroughputChart({
  data,
  loading,
  error,
  onRetry,
  aside,
  height = 280,
  title = 'Throughput',
  description = 'Jobs processed per minute · last 24h',
  onSelectPoint,
}: ThroughputChartProps) {
  const points: Point[] = (data?.points ?? []).map((p) => ({
    label: p.label,
    completed: p.completed,
    failed: p.failed,
  }))

  const selectIndex = (index: number | undefined): void => {
    if (!onSelectPoint || index === undefined) return
    const point = data?.points[index]
    if (point) onSelectPoint(point)
  }

  return (
    <ChartFrame
      title={title}
      description={description}
      height={height}
      loading={loading}
      error={error}
      onRetry={onRetry}
      isEmpty={points.length === 0}
      aside={
        <>
          <ChartLegend
            items={[
              { label: 'Completed', className: 'bg-accent' },
              { label: 'Failed', className: 'bg-failed' },
            ]}
          />
          {aside}
        </>
      }
    >
      <ResponsiveContainer width="100%" height={height}>
        <ComposedChart
          data={points}
          margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
          style={onSelectPoint ? { cursor: 'pointer' } : undefined}
          onClick={
            onSelectPoint
              // Recharts butun grafik bo'yicha bitta `onClick` beradi —
              // qaysi nuqta ekanini `activeTooltipIndex` aytadi
              ? (state: { activeTooltipIndex?: number }) => selectIndex(state?.activeTooltipIndex)
              : undefined
          }
        >
          <defs>
            {/* Dizayndagi `thGrad`: 42% -> 12% -> 0% shaffoflik */}
            <linearGradient id="throughputGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="hsl(var(--accent))" stopOpacity={0.42} />
              <stop offset="55%" stopColor="hsl(var(--accent))" stopOpacity={0.12} />
              <stop offset="100%" stopColor="hsl(var(--accent))" stopOpacity={0} />
            </linearGradient>
          </defs>

          <CartesianGrid
            vertical={false}
            stroke="hsl(var(--surface-4))"
            strokeWidth={1}
          />
          <XAxis
            dataKey="label"
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            // Har 8-nuqtada yorliq (dizaynda ham shunday)
            interval={Math.max(0, Math.floor(points.length / 6) - 1)}
            minTickGap={16}
          />
          <YAxis
            tick={AXIS_TICK}
            tickLine={false}
            axisLine={false}
            width={44}
            tickFormatter={(value: number) => formatCompact(value)}
          />
          <Tooltip
            content={<TooltipContent />}
            cursor={DASHED_CURSOR}
            animationDuration={120}
          />

          <Area
            type="linear"
            dataKey="completed"
            stroke="none"
            fill="url(#throughputGradient)"
            isAnimationActive={false}
          />
          <Line
            type="linear"
            dataKey="completed"
            stroke="hsl(var(--accent))"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, fill: 'hsl(var(--accent))', stroke: 'hsl(var(--canvas))', strokeWidth: 2 }}
            isAnimationActive={false}
          />
          <Line
            type="linear"
            dataKey="failed"
            stroke="hsl(var(--failed))"
            strokeWidth={1.6}
            dot={false}
            activeDot={{ r: 3.5, fill: 'hsl(var(--failed))', stroke: 'hsl(var(--canvas))', strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </ComposedChart>
      </ResponsiveContainer>

      {/* Klaviatura uchun: sichqonchasiz ham har bir oynaga kirish mumkin */}
      {onSelectPoint && points.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1">
          {points.map((point, index) =>
            // 48 ta tugma juda ko'p — har 6-chisi ko'rinadi, qolganlari
            // faqat ekran o'quvchi va `Tab` uchun
            index % Math.max(1, Math.floor(points.length / 8)) === 0 ? (
              <button
                key={`${point.label}-${index}`}
                type="button"
                onClick={() => selectIndex(index)}
                className="rounded px-1.5 py-0.5 text-2xs text-fg-faint transition-colors hover:bg-surface-3 hover:text-fg-dim"
              >
                {point.label}
              </button>
            ) : (
              <button
                key={`${point.label}-${index}`}
                type="button"
                onClick={() => selectIndex(index)}
                className="sr-only focus:not-sr-only focus:rounded focus:bg-surface-3 focus:px-1.5 focus:py-0.5 focus:text-2xs focus:text-fg-dim"
              >
                {point.label}
              </button>
            ),
          )}
        </div>
      ) : null}
    </ChartFrame>
  )
}
