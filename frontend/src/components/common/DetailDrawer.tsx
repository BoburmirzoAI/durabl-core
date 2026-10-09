'use client'

import { Sheet, SheetBody, SheetContent, SheetFooter, SheetHeader } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/common/ErrorState'
import { cn } from '@/lib/utils/cn'

/**
 * Drill-down paneli — raqam yoki grafik ustiga bosilganda ochiladi.
 *
 * `Sheet` ustiga qurilgan yupqa qatlam: har safar `SheetHeader`/`SheetBody`
 * ni qo'lda yig'ish o'rniga, bu komponent yuklanish/xato/bo'sh holatlarini
 * ham o'zi boshqaradi. Shuning uchun chaqiruvchi faqat MAZMUN beradi.
 *
 * Nega modal emas: drill-down kontekstni yo'qotmasligi kerak — foydalanuvchi
 * ortidagi jadvalni yoki grafikni ko'rib turishi muhim.
 */
export interface DrawerStat {
  label: string
  value: React.ReactNode
  /** Qiymat rangi (xato/ogohlantirish ajralib tursin). */
  tone?: 'default' | 'good' | 'warn' | 'bad'
}

const TONE_CLASS = {
  default: 'text-fg',
  good: 'text-success',
  warn: 'text-pending',
  bad: 'text-failed',
} as const

export function DetailDrawer({
  open,
  onOpenChange,
  title,
  description,
  stats,
  loading = false,
  error,
  onRetry,
  width = 'md',
  footer,
  children,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: React.ReactNode
  description?: React.ReactNode
  /** Sarlavha ostidagi qisqa ko'rsatkichlar qatori. */
  stats?: DrawerStat[]
  loading?: boolean
  error?: unknown
  onRetry?: () => void
  width?: 'md' | 'lg'
  footer?: React.ReactNode
  children?: React.ReactNode
}) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent width={width} aria-describedby={undefined}>
        <SheetHeader title={title} description={description} />

        {stats && stats.length > 0 ? (
          <div className="grid shrink-0 grid-cols-2 gap-px border-b border-line-inner bg-line-subtle sm:grid-cols-4">
            {stats.map((stat) => (
              <div key={stat.label} className="bg-canvas px-4 py-3">
                <div className="text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">
                  {stat.label}
                </div>
                <div
                  className={cn(
                    'tabular mt-1.5 font-mono text-lg',
                    TONE_CLASS[stat.tone ?? 'default'],
                  )}
                >
                  {stat.value}
                </div>
              </div>
            ))}
          </div>
        ) : null}

        <SheetBody>
          {error ? (
            <ErrorState error={error} onRetry={onRetry} />
          ) : loading ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }, (_, i) => (
                <Skeleton key={i} className="h-14 w-full" />
              ))}
            </div>
          ) : (
            children
          )}
        </SheetBody>

        {footer ? <SheetFooter>{footer}</SheetFooter> : null}
      </SheetContent>
    </Sheet>
  )
}

/**
 * Drawer ichidagi bo'lim — izchil sarlavha + ramka.
 *
 * Har bir drill-down bir xil ko'rinishi uchun: sarlavha kichik, katta harfli,
 * mazmun esa karta ichida.
 */
export function DrawerSection({
  title,
  action,
  children,
  className,
}: {
  title: string
  action?: React.ReactNode
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('rounded-xl border border-line bg-surface', className)}>
      <div className="flex items-center gap-2 border-b border-line-inner px-4 py-2.5">
        <span className="text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">
          {title}
        </span>
        {action ? <span className="ml-auto">{action}</span> : null}
      </div>
      <div className="p-4">{children}</div>
    </div>
  )
}

/** Drawer ichidagi `yorliq: qiymat` qatori. */
export function DrawerRow({
  label,
  value,
  mono = false,
}: {
  label: string
  value: React.ReactNode
  mono?: boolean
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line-subtle py-2 last:border-b-0">
      <span className="shrink-0 text-sm text-fg-dim">{label}</span>
      <span className={cn('min-w-0 truncate text-right text-sm text-fg-soft', mono && 'font-mono text-xs')}>
        {value}
      </span>
    </div>
  )
}
