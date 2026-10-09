'use client'

import * as DialogPrimitive from '@radix-ui/react-dialog'
import { forwardRef } from 'react'

import { cn } from '@/lib/utils/cn'

/**
 * Slide-over panel (sheet) — detal ko'rinishlari uchun.
 *
 * Nega modal emas: foydalanuvchi/worker tafsiloti uzun ro'yxat bo'ladi va
 * sahifa kontekstini yo'qotmasdan ko'rilishi kerak. Modal markazda turib
 * ortidagi jadvalni butunlay bekitadi.
 *
 * DIQQAT: siljish animatsiyasi `transform` ni qayta yozadi, shuning uchun
 * panel markazlashtiruvchi sinflarga TAYANMAYDI — u o'ngga `right-0` bilan
 * yopishtiriladi va faqat gorizontal siljiydi. Shu sababli dialoglardagi
 * "chetda ochilib markazga sakrash" muammosi bu yerda umuman yuzaga kelmaydi.
 */
export const Sheet = DialogPrimitive.Root
export const SheetTrigger = DialogPrimitive.Trigger
export const SheetClose = DialogPrimitive.Close

export const SheetContent = forwardRef<
  React.ElementRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content> & {
    /** Panel kengligi. */
    width?: 'md' | 'lg'
  }
>(({ className, children, width = 'md', ...props }, ref) => (
  <DialogPrimitive.Portal>
    <DialogPrimitive.Overlay className="fixed inset-0 z-50 animate-overlay-in bg-black/55 backdrop-blur-[4px]" />
    <DialogPrimitive.Content
      ref={ref}
      className={cn(
        'fixed right-0 top-0 z-50 flex h-dvh w-full flex-col',
        'animate-sheet-in border-l border-line-strong bg-canvas shadow-modal',
        'focus:outline-none',
        width === 'lg' ? 'max-w-[680px]' : 'max-w-[520px]',
        className,
      )}
      {...props}
    >
      {children}
    </DialogPrimitive.Content>
  </DialogPrimitive.Portal>
))
SheetContent.displayName = 'SheetContent'

export function SheetHeader({
  title,
  description,
  actions,
}: {
  title: React.ReactNode
  description?: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <div className="flex shrink-0 items-start gap-3 border-b border-line-inner px-5 py-4">
      <div className="min-w-0 flex-1">
        <DialogPrimitive.Title className="truncate text-lg font-semibold tracking-[-.01em] text-fg">
          {title}
        </DialogPrimitive.Title>
        {description ? (
          <DialogPrimitive.Description className="mt-0.5 text-sm text-fg-dim">
            {description}
          </DialogPrimitive.Description>
        ) : null}
      </div>
      {actions}
      <SheetClose
        aria-label="Close panel"
        className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-fg-faint transition-colors hover:bg-surface-2 hover:text-fg"
      >
        <svg
          width="15"
          height="15"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          aria-hidden
        >
          <path d="M6 6l12 12M18 6 6 18" />
        </svg>
      </SheetClose>
    </div>
  )
}

/** Panel tanasi — O'Z ichida siljiydi, sahifa emas. */
export function SheetBody({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('min-h-0 flex-1 space-y-4 overflow-y-auto px-5 py-4', className)} {...props} />
}

export function SheetFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'flex shrink-0 items-center justify-end gap-2 border-t border-line-inner px-5 py-3.5',
        className,
      )}
      {...props}
    />
  )
}
