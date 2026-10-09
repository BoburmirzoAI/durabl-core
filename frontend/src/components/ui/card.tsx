import { forwardRef } from 'react'

import { cn } from '@/lib/utils/cn'

/**
 * Karta — dizaynda `background:#141416; border:1px solid #242428;
 * border-radius:12px`. Statistika kartalari 10px radius ishlatadi,
 * shuning uchun `radius` prop bor.
 */
export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
  radius?: 'xl' | '2xl'
  /** Hover'da chegara yorishadi (dizaynda statistika kartalarida bor). */
  interactive?: boolean
}

export const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ className, radius = '2xl', interactive = false, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        'border border-line bg-surface',
        radius === 'xl' ? 'rounded-xl' : 'rounded-2xl',
        interactive && 'transition-colors hover:border-line-hover',
        className,
      )}
      {...props}
    />
  ),
)
Card.displayName = 'Card'

/** Karta sarlavhasi — pastda ichki ajratgich chizig'i bilan. */
export const CardHeader = forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn('flex items-center gap-2.5 border-b border-line-inner px-4 py-3.5', className)}
      {...props}
    />
  ),
)
CardHeader.displayName = 'CardHeader'

export const CardTitle = forwardRef<HTMLSpanElement, React.HTMLAttributes<HTMLSpanElement>>(
  ({ className, ...props }, ref) => (
    <span
      ref={ref}
      className={cn('text-lg font-semibold tracking-[-.01em] text-fg', className)}
      {...props}
    />
  ),
)
CardTitle.displayName = 'CardTitle'

export const CardDescription = forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn('mt-[3px] text-sm text-fg-dim', className)} {...props} />
  ),
)
CardDescription.displayName = 'CardDescription'

export const CardContent = forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => <div ref={ref} className={cn('p-4', className)} {...props} />,
)
CardContent.displayName = 'CardContent'
