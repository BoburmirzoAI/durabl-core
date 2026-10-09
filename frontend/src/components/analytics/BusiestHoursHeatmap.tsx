'use client'

import { ChartFrame } from './ChartFrame'
import { cn } from '@/lib/utils/cn'
import { formatNumber } from '@/lib/utils/format'
import type { BusiestHours } from '@/types'

/**
 * Kun × soat yuklama issiqlik xaritasi.
 *
 * Nega jadval emas: 168 ta qiymatni raqam bilan ko'rsatish o'qib bo'lmas
 * bo'ladi. Rang intensivligi naqshni (ish soatlari, dam olish kunlari)
 * bir qarashda ko'rsatadi.
 *
 * Ranglar DISKRET 5 pog'onaga bo'lingan — uzluksiz gradient qorong'u
 * mavzuda qo'shni darajalarni ajratib bo'lmaydigan qiladi.
 */
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

/** Intensivlik darajalari — eng past (bo'sh) dan eng yuqorigacha. */
const LEVELS = [
  'bg-surface-3',
  'bg-accent/[0.18]',
  'bg-accent/[0.38]',
  'bg-accent/[0.62]',
  'bg-accent',
]

function levelFor(count: number, max: number): number {
  if (max === 0 || count === 0) return 0
  const ratio = count / max
  if (ratio < 0.25) return 1
  if (ratio < 0.5) return 2
  if (ratio < 0.75) return 3
  return 4
}

export function BusiestHoursHeatmap({
  data,
  loading,
  error,
  onRetry,
}: {
  data: BusiestHours | undefined
  loading?: boolean
  error?: unknown
  onRetry?: () => void
}) {
  const byDay = DAYS.map((_, day) => (data?.cells ?? []).filter((c) => c.day === day))

  return (
    <ChartFrame
      title="Busiest hours"
      description="When jobs are submitted, by day and hour"
      height={210}
      loading={loading}
      error={error}
      onRetry={onRetry}
      isEmpty={!data}
      aside={
        data ? (
          <span className="text-xs text-fg-dim">
            peak <span className="font-medium text-fg-soft">{data.peak_label}</span>
          </span>
        ) : null
      }
    >
      <div className="flex flex-col gap-1">
        {/* Soat yorliqlari — har 4 soatda bittadan */}
        <div className="flex gap-[3px] pl-9">
          {Array.from({ length: 24 }, (_, hour) => (
            <span
              key={hour}
              className="flex-1 text-center text-[9px] leading-none text-fg-faint"
              aria-hidden
            >
              {hour % 4 === 0 ? hour : ''}
            </span>
          ))}
        </div>

        {byDay.map((cells, day) => (
          <div key={day} className="flex items-center gap-[3px]">
            <span className="w-9 shrink-0 text-[10px] text-fg-faint">{DAYS[day]}</span>
            {cells.map((cell) => (
              <span
                key={cell.hour}
                className={cn(
                  'h-4 flex-1 rounded-[2px] transition-colors',
                  LEVELS[levelFor(cell.count, data?.max ?? 1)],
                )}
                title={`${DAYS[day]} ${String(cell.hour).padStart(2, '0')}:00 — ${formatNumber(cell.count)} jobs`}
              />
            ))}
          </div>
        ))}

        <div className="mt-1 flex items-center justify-end gap-1.5 text-[10px] text-fg-faint">
          <span>Less</span>
          {LEVELS.map((level) => (
            <span key={level} className={cn('h-2.5 w-2.5 rounded-[2px]', level)} aria-hidden />
          ))}
          <span>More</span>
        </div>
      </div>
    </ChartFrame>
  )
}
