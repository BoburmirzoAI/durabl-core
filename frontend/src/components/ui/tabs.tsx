'use client'

import { cn } from '@/lib/utils/cn'

/**
 * Segment tablar — dizaynda ikki xil:
 *
 * 1. `pill` — konteyner `#141416` + chegara, faol element `#26262B`
 *    (dashboard'dagi 24h/7d/30d va DLQ guruhlash tablari).
 * 2. `underline` — pastdan aksent chizig'i (job detalidagi Logs/Attempts).
 */
export interface TabItem<T extends string> {
  value: T
  label: string
  /** O'ng tomonda kichik son nishoni (`Attempts 3`). */
  count?: number
}

export interface TabsProps<T extends string> {
  items: readonly TabItem<T>[]
  value: T
  onChange: (value: T) => void
  variant?: 'pill' | 'underline'
  className?: string
  'aria-label': string
}

export function Tabs<T extends string>({
  items,
  value,
  onChange,
  variant = 'pill',
  className,
  'aria-label': ariaLabel,
}: TabsProps<T>) {
  if (variant === 'underline') {
    return (
      <div role="tablist" aria-label={ariaLabel} className={cn('flex items-center gap-1 px-1.5', className)}>
        {items.map((item) => {
          const active = item.value === value
          return (
            <button
              key={item.value}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => onChange(item.value)}
              className={cn(
                'relative flex items-center gap-[7px] px-3.5 pb-3 pt-[13px] text-base font-medium transition-colors',
                active ? 'text-fg' : 'text-fg-muted hover:text-fg-soft',
              )}
            >
              {item.label}
              {item.count !== undefined ? (
                <span
                  className={cn(
                    'rounded-[5px] px-1.5 py-px font-mono text-2xs font-semibold',
                    active ? 'bg-accent/[0.16] text-accent-light' : 'bg-surface-3 text-fg-faint',
                  )}
                >
                  {item.count}
                </span>
              ) : null}
              <span
                className={cn(
                  'absolute inset-x-2 -bottom-px h-0.5 rounded-sm transition-colors',
                  active ? 'bg-accent' : 'bg-transparent',
                )}
              />
            </button>
          )
        })}
      </div>
    )
  }

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      className={cn(
        'flex items-center gap-0.5 rounded-lg border border-line bg-surface p-[3px]',
        className,
      )}
    >
      {items.map((item) => {
        const active = item.value === value
        return (
          <button
            key={item.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(item.value)}
            className={cn(
              'rounded px-[11px] py-[5px] text-sm font-medium transition-colors',
              active ? 'bg-surface-5 text-fg' : 'text-fg-muted hover:text-fg-soft',
            )}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}
