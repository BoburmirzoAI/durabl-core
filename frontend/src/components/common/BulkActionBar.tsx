'use client'

import { cn } from '@/lib/utils/cn'
import { useSelectionStore } from '@/stores/selectionStore'

/**
 * Bo'sh tanlov uchun BARQAROR havola.
 *
 * Zustand selektor natijasini `Object.is` bilan solishtiradi. `?? []` yozilsa
 * har chaqiriqda YANGI massiv qaytadi — store o'zgarmagan bo'lsa ham "o'zgardi"
 * deb hisoblanadi va cheksiz qayta render boshlanadi
 * ("Maximum update depth exceeded").
 */
const EMPTY_IDS: string[] = []


/**
 * Ommaviy amallar paneli — dizaynda jadval USTIDA paydo bo'ladi
 * (`position:absolute; background:#17141F; border-bottom:#2E2640`),
 * `dbar` animatsiyasi bilan.
 */
export interface BulkAction {
  label: string
  /** SVG `path` ning `d` atributi. */
  icon: string
  onClick: (ids: string[]) => void
  /** Ikonka rangi klassi (xavfli amallar qizil). */
  iconClassName?: string
  disabled?: boolean
}

export interface BulkActionBarProps {
  scope: string
  actions: BulkAction[]
  className?: string
}

export function BulkActionBar({ scope, actions, className }: BulkActionBarProps) {
  const selected = useSelectionStore((s) => s.selected[scope] ?? EMPTY_IDS)
  const clear = useSelectionStore((s) => s.clear)

  if (selected.length === 0) return null

  return (
    <div
      className={cn(
        'absolute inset-x-0 top-0 z-[15] flex h-[42px] animate-slide-down items-center gap-3 border-b border-accent-edge bg-accent-bar px-4',
        className,
      )}
    >
      <span className="text-sm font-medium text-accent-pale">
        <span className="tabular font-mono font-semibold text-accent-light">{selected.length}</span>{' '}
        selected
      </span>
      <div className="h-[18px] w-px bg-accent-edge" />

      {actions.map((action) => (
        <button
          key={action.label}
          type="button"
          disabled={action.disabled}
          onClick={() => action.onClick(selected)}
          className="flex items-center gap-1.5 rounded-md border border-accent-edge bg-accent-bar-2 px-2.5 py-[5px] text-sm font-medium text-fg-soft transition-colors hover:border-accent-edge-2 hover:bg-accent-bar-3 disabled:pointer-events-none disabled:opacity-50"
        >
          <svg
            width="13"
            height="13"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.9"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={action.iconClassName ?? 'text-accent-light'}
            aria-hidden
          >
            <path d={action.icon} />
          </svg>
          {action.label}
        </button>
      ))}

      <button
        type="button"
        onClick={() => clear(scope)}
        className="ml-auto text-sm text-fg-dim transition-colors hover:text-fg"
      >
        Clear selection
      </button>
    </div>
  )
}

/** Keng tarqalgan bulk amallari uchun ikonkalar. */
export const BULK_ICONS = {
  retry: 'M3 12a9 9 0 1 0 3-6.7M3 3v4h4',
  cancel: 'M18 6 6 18M6 6l12 12',
  delete: 'M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6',
  export: 'M12 3v12M7 10l5 5 5-5M4 19h16',
} as const
