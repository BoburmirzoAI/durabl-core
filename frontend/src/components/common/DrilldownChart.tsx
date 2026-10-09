'use client'

import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { ChartFrame } from '@/components/analytics/ChartFrame'
import {
  AXIS_TICK,
  ChartTooltip,
  type RechartsTooltipProps,
} from '@/components/analytics/ChartTooltip'
import { cn } from '@/lib/utils/cn'
import { formatNumber } from '@/lib/utils/format'

/**
 * Bosiladigan ustunli grafik — nuqta ortidagi ma'lumotga olib boradi.
 *
 * ## Nega alohida komponent
 *
 * Loyihadagi boshqa grafiklar (`ThroughputChart`, `LatencyHistogram`) faqat
 * KO'RSATADI. Bu esa drill-down uchun: har bir ustun bosiladi va chaqiruvchi
 * `onSelect(point)` orqali kerakli sahifaga yoki panelga o'tadi.
 *
 * Bosiladigan grafik ikki narsani talab qiladi:
 *
 * 1. **Ko'rinadigan belgi** — kursor `pointer`, hover'da ustun yorishadi.
 *    Aks holda foydalanuvchi bosish mumkinligini bilmaydi.
 * 2. **Klaviatura** — faqat sichqoncha bilan ishlaydigan drill-down
 *    klaviaturachi foydalanuvchini to'sib qo'yadi. Shuning uchun ustunlar
 *    ostida `Tab` bilan o'tiladigan yashirin tugmalar qatori bor.
 */
export interface DrilldownPoint {
  /** O'q yorlig'i. */
  label: string
  value: number
  /** Chaqiruvchi uchun ixtiyoriy kalit (status, runtime, soat…). */
  key?: string
  /** Ustun rangi (Tailwind sinf emas — CSS o'zgaruvchi nomi). */
  tone?: 'accent' | 'success' | 'failed' | 'pending' | 'running'
}

const TONE_VAR: Record<NonNullable<DrilldownPoint['tone']>, string> = {
  accent: 'var(--accent)',
  success: 'var(--success)',
  failed: 'var(--failed)',
  pending: 'var(--pending)',
  running: 'var(--running)',
}

function TooltipContent({
  active,
  payload,
  valueLabel,
}: RechartsTooltipProps<DrilldownPoint> & { valueLabel: string }) {
  if (!active || !payload?.length) return null
  const point = payload[0]?.payload
  if (!point) return null
  return (
    <ChartTooltip
      heading={point.label}
      rows={[
        { label: valueLabel, value: formatNumber(point.value), dotClassName: 'bg-accent' },
        // Drill-down mumkinligini bildiramiz — aks holda bosish mumkinligi bilinmaydi
        { label: 'Click', value: 'to drill in', dotClassName: 'bg-fg-ghost' },
      ]}
    />
  )
}

export function DrilldownChart({
  title,
  description,
  points,
  onSelect,
  valueLabel = 'Jobs',
  height = 220,
  loading,
  error,
  onRetry,
  selectedKey,
}: {
  title: string
  description?: string
  points: DrilldownPoint[] | undefined
  /** Ustun bosilganda chaqiriladi. */
  onSelect: (point: DrilldownPoint) => void
  valueLabel?: string
  height?: number
  loading?: boolean
  error?: unknown
  onRetry?: () => void
  /** Tanlangan ustun ajralib tursin. */
  selectedKey?: string | null
}) {
  const data = points ?? []

  return (
    <ChartFrame
      compact
      title={title}
      description={description}
      height={height}
      loading={loading}
      error={error}
      onRetry={onRetry}
      isEmpty={data.length === 0}
    >
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="hsl(var(--surface-4))" />
          <XAxis dataKey="label" tick={AXIS_TICK} tickLine={false} axisLine={false} minTickGap={16} />
          <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} width={42} />
          <Tooltip
            content={<TooltipContent valueLabel={valueLabel} />}
            cursor={{ fill: 'hsl(var(--surface-3))' }}
            animationDuration={120}
          />
          <Bar
            dataKey="value"
            radius={[3, 3, 0, 0]}
            isAnimationActive={false}
            cursor="pointer"
            onClick={(_, index) => {
              const point = data[index]
              if (point) onSelect(point)
            }}
          >
            {data.map((point, index) => {
              const active = selectedKey != null && point.key === selectedKey
              return (
                <Cell
                  key={index}
                  fill={`hsl(${TONE_VAR[point.tone ?? 'accent']})`}
                  fillOpacity={selectedKey == null ? 0.85 : active ? 1 : 0.35}
                />
              )
            })}
          </Bar>
        </BarChart>
      </ResponsiveContainer>

      {/* Klaviatura uchun: ustunlar bilan bir xil tartibdagi tugmalar */}
      <div className="mt-2 flex flex-wrap gap-1">
        {data.map((point) => (
          <button
            key={point.key ?? point.label}
            type="button"
            onClick={() => onSelect(point)}
            className={cn(
              'rounded px-1.5 py-0.5 text-2xs transition-colors',
              selectedKey === point.key
                ? 'bg-accent/[0.16] text-accent-light'
                : 'text-fg-faint hover:bg-surface-3 hover:text-fg-dim',
            )}
          >
            {point.label}
          </button>
        ))}
      </div>
    </ChartFrame>
  )
}
