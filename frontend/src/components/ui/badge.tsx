import { type VariantProps, cva } from 'class-variance-authority'
import { forwardRef } from 'react'

import { cn } from '@/lib/utils/cn'

/**
 * Nishon — dizaynda `padding:2px 8px; border-radius:6px; font-size:11px`.
 * Holat ranglari `StatusBadge` orqali beriladi, bu esa neytral asos.
 */
const badgeVariants = cva(
  'inline-flex items-center gap-1.5 rounded font-medium leading-none whitespace-nowrap',
  {
    variants: {
      variant: {
        neutral: 'bg-surface-3 text-fg-muted',
        outline: 'border border-line bg-transparent text-fg-muted',
        accent: 'border border-accent/30 bg-accent/[0.14] text-accent-light',
        danger: 'border border-failed/25 bg-failed/[0.13] text-failed',
        success: 'bg-success/[0.12] text-success',
      },
      size: {
        sm: 'px-1.5 py-px text-2xs',
        md: 'px-2 py-0.5 text-xs',
        lg: 'px-2.5 py-1 text-sm',
      },
    },
    defaultVariants: { variant: 'neutral', size: 'md' },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export const Badge = forwardRef<HTMLSpanElement, BadgeProps>(
  ({ className, variant, size, ...props }, ref) => (
    <span ref={ref} className={cn(badgeVariants({ variant, size }), className)} {...props} />
  ),
)
Badge.displayName = 'Badge'

export { badgeVariants }
