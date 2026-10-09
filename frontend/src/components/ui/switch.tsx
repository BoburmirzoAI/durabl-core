'use client'

import { cn } from '@/lib/utils/cn'

/**
 * Toggle — dizayndagi auto-scroll tugmasi:
 * 30×17px trek, 13px dumaloq, 150ms tranzitsiya.
 */
export interface SwitchProps {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  'aria-label': string
  disabled?: boolean
  className?: string
}

export function Switch({
  checked,
  onCheckedChange,
  disabled = false,
  className,
  'aria-label': ariaLabel,
}: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={() => onCheckedChange(!checked)}
      className={cn(
        'relative h-[17px] w-[30px] shrink-0 rounded-full transition-colors',
        checked ? 'bg-accent' : 'bg-line',
        disabled && 'cursor-not-allowed opacity-40',
        className,
      )}
    >
      <span
        className={cn(
          'absolute top-0.5 h-[13px] w-[13px] rounded-full bg-white transition-[left]',
          checked ? 'left-[15px]' : 'left-0.5',
        )}
      />
    </button>
  )
}
