'use client'

import { Slot } from '@radix-ui/react-slot'
import { type VariantProps, cva } from 'class-variance-authority'
import { forwardRef } from 'react'

import { cn } from '@/lib/utils/cn'

/**
 * Tugma variantlari — dizayndan olingan:
 *   primary   -> `background:#8B5CF6`, hover `#7C4DF0`
 *   secondary -> `background:#141416; border:1px solid #242428`, hover chegarasi `#33333A`
 *   ghost     -> shaffof, hover `#161619`
 *   bulk      -> bulk panel ichidagi tugma (`#1C1826` / `#2E2640`)
 */
const buttonVariants = cva(
  'inline-flex items-center justify-center gap-[7px] whitespace-nowrap rounded-lg font-sans font-medium transition-colors disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        primary: 'bg-accent-solid text-white hover:bg-accent-hover',
        secondary: 'border border-line bg-surface text-fg-soft hover:border-line-hover hover:text-fg',
        ghost: 'text-fg-muted hover:bg-surface-2 hover:text-fg',
        outline: 'border border-line bg-transparent text-fg-soft hover:border-line-hover hover:text-fg',
        danger: 'border border-failed/30 bg-failed/[0.08] text-failed hover:bg-failed/[0.14]',
        bulk: 'border border-accent-edge bg-accent-bar-2 text-fg-soft hover:border-accent-edge-2 hover:bg-accent-bar-3',
        link: 'text-accent hover:text-accent-light',
      },
      size: {
        sm: 'h-[30px] px-[11px] text-sm',
        md: 'h-[34px] px-3 text-base',
        lg: 'h-[38px] px-4 text-base',
        icon: 'h-8 w-8 p-0',
        'icon-sm': 'h-[26px] w-[26px] rounded-md p-0',
        'icon-lg': 'h-[34px] w-[34px] p-0',
      },
    },
    defaultVariants: { variant: 'secondary', size: 'sm' },
  },
)

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, type = 'button', ...props }, ref) => {
    const Comp = asChild ? Slot : 'button'
    return (
      <Comp
        ref={ref}
        // `asChild` da `type` bola elementga tegishli emas
        {...(asChild ? {} : { type })}
        className={cn(buttonVariants({ variant, size }), className)}
        {...props}
      />
    )
  },
)
Button.displayName = 'Button'

export { buttonVariants }
