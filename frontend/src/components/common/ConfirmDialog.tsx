'use client'

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'

/**
 * Tasdiqlash dialogi — xavfli amallar uchun (o'chirish, bekor qilish).
 *
 * Dizaynda yo'q, lekin Section 6 talab qiladi: har bir qaytarilmas amal
 * tasdiqlanishi kerak.
 */
export interface ConfirmDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  confirmLabel?: string
  cancelLabel?: string
  destructive?: boolean
  pending?: boolean
  onConfirm: () => void
  /**
   * Dialog ichidagi qo'shimcha maydon (masalan "DEACTIVATE deb yozing").
   *
   * Bu propsiz qolganda chaqiruvchi tomon maydonni dialog USTIGA `fixed`
   * qatlam qilib qo'yishga majbur bo'lardi — u esa pastki tugmalarni
   * bekitib qo'yardi.
   */
  children?: React.ReactNode
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  destructive = false,
  pending = false,
  onConfirm,
  children,
}: ConfirmDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent width="sm">
        <DialogHeader>
          <div
            className={
              destructive
                ? 'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-failed/25 bg-failed/[0.08]'
                : 'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-line bg-surface-2'
            }
          >
            <svg
              width="17"
              height="17"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              className={destructive ? 'text-failed' : 'text-fg-muted'}
              aria-hidden
            >
              <path d="M12 3 2 20h20zM12 10v4M12 17h.01" />
            </svg>
          </div>
          <div className="min-w-0">
            <DialogTitle>{title}</DialogTitle>
            {description ? <DialogDescription>{description}</DialogDescription> : null}
          </div>
        </DialogHeader>

        {children ? <DialogBody>{children}</DialogBody> : <DialogBody className="py-0" />}

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {cancelLabel}
          </Button>
          <Button
            variant={destructive ? 'danger' : 'primary'}
            size="md"
            disabled={pending}
            onClick={onConfirm}
          >
            {pending ? 'Working…' : confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
