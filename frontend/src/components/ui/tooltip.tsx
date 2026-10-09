'use client'

import * as Primitive from '@radix-ui/react-tooltip'
import { forwardRef } from 'react'

import { cn } from '@/lib/utils/cn'

export const TooltipProvider = Primitive.Provider
export const Tooltip = Primitive.Root
export const TooltipTrigger = Primitive.Trigger

export const TooltipContent = forwardRef<
  React.ElementRef<typeof Primitive.Content>,
  React.ComponentPropsWithoutRef<typeof Primitive.Content>
>(({ className, sideOffset = 6, ...props }, ref) => (
  <Primitive.Portal>
    <Primitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        'z-50 max-w-[280px] rounded-lg border border-line-hover bg-surface-4 px-2.5 py-2 text-sm text-fg-soft shadow-tooltip',
        className,
      )}
      {...props}
    />
  </Primitive.Portal>
))
TooltipContent.displayName = 'TooltipContent'
