'use client'

import { cn } from '@/lib/utils/cn'

/**
 * Jadval checkbox'i — dizaynda 15×15px, 4px radius, 1.5px chegara.
 * Tanlangan holatda aksent fon va oq belgi.
 *
 * Radix ISHLATILMAYDI: jadval qatorida checkbox qator bosilishini
 * to'sib qo'ymasligi kerak va `indeterminate` holati kerak — oddiy
 * `span` + ARIA bilan nazoratni to'liq saqlab qolamiz.
 */
export interface CheckboxProps {
  checked: boolean
  /** Qisman tanlangan (sarlavha checkbox'i uchun). */
  indeterminate?: boolean
  onToggle: () => void
  'aria-label': string
  className?: string
  disabled?: boolean
}

export function Checkbox({
  checked,
  indeterminate = false,
  onToggle,
  className,
  disabled = false,
  'aria-label': ariaLabel,
}: CheckboxProps) {
  const active = checked || indeterminate
  return (
    <button
      type="button"
      role="checkbox"
      aria-checked={indeterminate ? 'mixed' : checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={(event) => {
        // Qator bosilishini to'xtatamiz — aks holda detal sahifasi ochiladi
        event.stopPropagation()
        onToggle()
      }}
      className={cn(
        'flex h-[15px] w-[15px] shrink-0 items-center justify-center rounded-sm border-[1.5px] transition-colors',
        active ? 'border-accent bg-accent' : 'border-line-hover bg-transparent hover:border-fg-faint',
        disabled && 'cursor-not-allowed opacity-40',
        className,
      )}
    >
      {indeterminate ? (
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="4" strokeLinecap="round" aria-hidden>
          <path d="M6 12h12" />
        </svg>
      ) : checked ? (
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M5 12l5 5 9-11" />
        </svg>
      ) : null}
    </button>
  )
}
