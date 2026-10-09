'use client'

import * as Primitive from '@radix-ui/react-dropdown-menu'
import { forwardRef } from 'react'

import { cn } from '@/lib/utils/cn'

/**
 * Dropdown menyu — dizaynda `#161619` fon, `#2A2A30` chegara, 9px radius,
 * element hover'i `#1F1F24`.
 */
export const DropdownMenu = Primitive.Root
export const DropdownMenuTrigger = Primitive.Trigger
export const DropdownMenuGroup = Primitive.Group

export const DropdownMenuContent = forwardRef<
  React.ElementRef<typeof Primitive.Content>,
  React.ComponentPropsWithoutRef<typeof Primitive.Content>
>(({ className, sideOffset = 6, align = 'end', ...props }, ref) => (
  <Primitive.Portal>
    <Primitive.Content
      ref={ref}
      sideOffset={sideOffset}
      align={align}
      className={cn(
        'z-50 min-w-[150px] animate-menu-in rounded-[9px] border border-line-strong bg-surface-2 p-[5px] shadow-menu',
        className,
      )}
      {...props}
    />
  </Primitive.Portal>
))
DropdownMenuContent.displayName = 'DropdownMenuContent'

export interface DropdownMenuItemProps
  extends React.ComponentPropsWithoutRef<typeof Primitive.Item> {
  /** Xavfli amal (o'chirish, bekor qilish) — qizil matn. */
  danger?: boolean
}

export const DropdownMenuItem = forwardRef<
  React.ElementRef<typeof Primitive.Item>,
  DropdownMenuItemProps
>(({ className, danger = false, ...props }, ref) => (
  <Primitive.Item
    ref={ref}
    className={cn(
      'flex cursor-pointer select-none items-center gap-2.5 rounded px-2.5 py-1.5 text-sm outline-none',
      // Fon o'zgarishi qo'shni fonga nisbatan 1.3:1 — holatni aniqlash uchun
      // yetarli emas, shuning uchun dizayndagi ichki aksent halqa qo'shiladi.
      'data-[highlighted]:bg-surface-5 data-[highlighted]:shadow-focus-row',
      'data-[disabled]:pointer-events-none data-[disabled]:opacity-40',
      danger ? 'text-failed' : 'text-fg-soft',
      className,
    )}
    {...props}
  />
))
DropdownMenuItem.displayName = 'DropdownMenuItem'

export const DropdownMenuSeparator = forwardRef<
  React.ElementRef<typeof Primitive.Separator>,
  React.ComponentPropsWithoutRef<typeof Primitive.Separator>
>(({ className, ...props }, ref) => (
  <Primitive.Separator
    ref={ref}
    className={cn('-mx-[5px] my-[5px] h-px bg-line-inner', className)}
    {...props}
  />
))
DropdownMenuSeparator.displayName = 'DropdownMenuSeparator'

export function DropdownMenuLabel({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        'px-2.5 py-1.5 text-2xs font-semibold uppercase tracking-[.09em] text-fg-faint',
        className,
      )}
      {...props}
    />
  )
}
