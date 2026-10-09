import { cn } from '@/lib/utils/cn'

/**
 * Progress bar — dizaynda ikki o'lcham:
 * worker CPU uchun 5px, billing o'lchagichi uchun 8px.
 */
export interface ProgressProps {
  /** 0..100 */
  value: number
  /** To'ldiruvchi rang klassi (`bg-success`, `bg-pending`...). */
  barClassName?: string
  size?: 'xs' | 'sm' | 'md'
  className?: string
  'aria-label'?: string
}

const HEIGHTS = { xs: 'h-[5px]', sm: 'h-1.5', md: 'h-2' } as const

export function Progress({
  value,
  barClassName = 'bg-accent',
  size = 'sm',
  className,
  'aria-label': ariaLabel,
}: ProgressProps) {
  const clamped = Math.max(0, Math.min(100, value))
  return (
    <div
      role="progressbar"
      aria-valuenow={Math.round(clamped)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={ariaLabel}
      className={cn('w-full overflow-hidden rounded-[3px] bg-line-inner', HEIGHTS[size], className)}
    >
      <div
        className={cn('h-full rounded-[3px] transition-[width] duration-300', barClassName)}
        style={{ width: `${clamped}%` }}
      />
    </div>
  )
}
