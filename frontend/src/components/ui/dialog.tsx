'use client'

import * as DialogPrimitive from '@radix-ui/react-dialog'
import { forwardRef } from 'react'

import { cn } from '@/lib/utils/cn'

/**
 * Modal — dizayndagi command palette'dan olingan ko'rinish:
 * fon `rgba(0,0,0,.55)` + `backdrop-filter:blur(4px)`,
 * panel `#141416` / `#2A2A30` chegara / 14px radius / katta soya.
 */
export const Dialog = DialogPrimitive.Root
export const DialogTrigger = DialogPrimitive.Trigger
export const DialogClose = DialogPrimitive.Close
export const DialogPortal = DialogPrimitive.Portal

export const DialogOverlay = forwardRef<
  React.ElementRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      'fixed inset-0 z-50 animate-overlay-in bg-black/55 backdrop-blur-[4px]',
      className,
    )}
    {...props}
  />
))
DialogOverlay.displayName = 'DialogOverlay'

export interface DialogContentProps
  extends React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> {
  /** Panel kengligi. */
  width?: 'sm' | 'md' | 'lg'
  /** Yuqoridan joylashuv (palette 14vh dan boshlanadi). */
  align?: 'center' | 'top'
}

const WIDTHS = { sm: 'max-w-[420px]', md: 'max-w-[560px]', lg: 'max-w-[680px]' } as const

export const DialogContent = forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  DialogContentProps
>(({ className, children, width = 'md', align = 'center', ...props }, ref) => (
  <DialogPortal>
    <DialogOverlay />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        'fixed left-1/2 z-50 w-[calc(100%-32px)] -translate-x-1/2',
        'overflow-hidden rounded-3xl border border-line-strong bg-surface shadow-modal',
        'focus:outline-none',
        // Markazlashuv animatsiya keyframe'i ichida — `animate-pop-in` ishlatilsa
        // transform qayta yoziladi va modal chetda ochiladi.
        align === 'top'
          ? 'top-[14vh] animate-dialog-in-top'
          : 'top-1/2 -translate-y-1/2 animate-dialog-in',
        WIDTHS[width],
        className,
      )}
      {...props}
    >
      {children}
    </DialogPrimitive.Content>
  </DialogPortal>
))
DialogContent.displayName = 'DialogContent'

export function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('flex items-start gap-3 border-b border-line-inner px-[18px] py-4', className)}
      {...props}
    />
  )
}

export const DialogTitle = forwardRef<
  React.ElementRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn('text-lg font-semibold tracking-[-.01em] text-fg', className)}
    {...props}
  />
))
DialogTitle.displayName = 'DialogTitle'

export const DialogDescription = forwardRef<
  React.ElementRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn('mt-1 text-sm text-fg-dim', className)}
    {...props}
  />
))
DialogDescription.displayName = 'DialogDescription'

export function DialogBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('max-h-[62vh] overflow-y-auto px-[18px] py-4', className)} {...props} />
}

export function DialogFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'flex items-center justify-end gap-2 border-t border-line-inner bg-canvas-raised px-[18px] py-3',
        className,
      )}
      {...props}
    />
  )
}
