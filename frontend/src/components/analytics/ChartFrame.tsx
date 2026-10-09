'use client'

import { Card, CardDescription, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/common/ErrorState'
import { LoadingState } from '@/components/common/LoadingState'
import { EmptyState } from '@/components/common/EmptyState'
import { cn } from '@/lib/utils/cn'

/**
 * Grafik uchun umumiy o'ram — dizayndagi karta sarlavhasi:
 * chapda nom + izoh, o'ngda legenda yoki oraliq tanlagich.
 *
 * Yuklanish / xato / bo'sh holatlarini ham shu komponent boshqaradi,
 * shunda har bir grafikda takrorlanmaydi.
 */
export interface ChartFrameProps {
  title: string
  description?: string
  /** O'ng tomon (legenda, tanlagich). */
  aside?: React.ReactNode
  children: React.ReactNode
  loading?: boolean
  error?: unknown
  onRetry?: () => void
  isEmpty?: boolean
  emptyLabel?: string
  /** Grafik balandligi (px) — skeleton ham shu balandlikni oladi. */
  height?: number
  className?: string
  /** Kichik variant (14px sarlavha) — analitika qatorida ishlatiladi. */
  compact?: boolean
}

export function ChartFrame({
  title,
  description,
  aside,
  children,
  loading = false,
  error,
  onRetry,
  isEmpty = false,
  emptyLabel = 'No data for this range',
  height = 280,
  className,
  compact = false,
}: ChartFrameProps) {
  return (
    <Card className={cn('p-[18px] pb-3', className)}>
      <div className="flex flex-wrap items-start gap-4">
        <div>
          <CardTitle className={compact ? 'text-md' : undefined}>{title}</CardTitle>
          {description ? <CardDescription>{description}</CardDescription> : null}
        </div>
        {aside ? <div className="ml-auto flex items-center gap-4">{aside}</div> : null}
      </div>

      <div className="mt-3.5" style={{ minHeight: height }}>
        {error ? (
          <ErrorState error={error} onRetry={onRetry} className="py-10" />
        ) : loading ? (
          <LoadingState className="py-10" />
        ) : isEmpty ? (
          <EmptyState
            icon="M4 4v16h16M8 16V11M13 16V7M18 16v-5"
            title={emptyLabel}
            className="py-10"
          />
        ) : (
          children
        )}
      </div>
    </Card>
  )
}

/** Grafik legendasi — rangli kvadrat + nom (dizaynda 8px kvadrat). */
export function ChartLegend({
  items,
}: {
  items: { label: string; className: string }[]
}) {
  return (
    <>
      {items.map((item) => (
        <span key={item.label} className="flex items-center gap-[7px] text-sm text-fg-muted">
          <span className={cn('h-2 w-2 rounded-sm', item.className)} />
          {item.label}
        </span>
      ))}
    </>
  )
}
