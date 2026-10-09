'use client'

import { cn } from '@/lib/utils/cn'

/**
 * Faol filtrlar chiplari — dizaynda `#18181B` fon, `#2A2A30` chegara,
 * chapda kulrang tur nomi, o'ngda × tugmasi.
 */
export interface FilterChip {
  /** Filtr turi (`Status`, `Runtime`). */
  kind: string
  label: string
  onRemove: () => void
}

export interface FilterChipsProps {
  chips: FilterChip[]
  onClearAll?: () => void
  className?: string
}

export function FilterChips({ chips, onClearAll, className }: FilterChipsProps) {
  if (chips.length === 0) return null

  return (
    <div className={cn('flex flex-wrap items-center gap-2', className)}>
      {chips.map((chip) => (
        <span
          key={`${chip.kind}-${chip.label}`}
          className="inline-flex items-center gap-[7px] rounded-md border border-line-strong bg-surface-3 py-1 pl-2.5 pr-[7px] text-sm text-fg-soft"
        >
          <span className="text-fg-faint">{chip.kind}</span>
          {chip.label}
          <button
            type="button"
            aria-label={`Remove ${chip.kind} ${chip.label} filter`}
            onClick={chip.onRemove}
            className="inline-flex h-4 w-4 items-center justify-center rounded-sm text-fg-dim transition-colors hover:bg-line-strong hover:text-fg"
          >
            <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden>
              <path d="M5 5l14 14M19 5L5 19" />
            </svg>
          </button>
        </span>
      ))}
      {onClearAll && chips.length > 1 ? (
        <button
          type="button"
          onClick={onClearAll}
          className="text-sm font-medium text-fg-dim transition-colors hover:text-fg-muted"
        >
          Clear all
        </button>
      ) : null}
    </div>
  )
}
