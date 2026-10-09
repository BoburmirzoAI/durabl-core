'use client'

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'

import { cn } from '@/lib/utils/cn'

/**
 * Toast bildirishnomalari.
 *
 * Radix Toast ISHLATILMAYDI: bizga faqat oddiy "o'ngda pastda paydo bo'lib
 * yo'qoladigan" xabar kerak, Radix esa swipe/viewport boshqaruvi bilan
 * ortiqcha. Hook (`useToast`) mutatsiyalardan chaqiriladi.
 */

export type ToastVariant = 'default' | 'success' | 'destructive'

export interface ToastOptions {
  title: string
  description?: string
  variant?: ToastVariant
  /** ms; `0` — avtomatik yopilmaydi. */
  duration?: number
}

interface ToastRecord extends ToastOptions {
  id: number
}

interface ToastContextValue {
  toast: (options: ToastOptions) => void
  dismiss: (id: number) => void
}

const ToastContext = createContext<ToastContextValue | null>(null)

const DEFAULT_DURATION = 4_000
/** Bir vaqtda ko'rinadigan maksimal toast — ekranni to'ldirib yubormasligi uchun. */
const MAX_VISIBLE = 4

let nextId = 1

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastRecord[]>([])

  const dismiss = useCallback((id: number) => {
    setToasts((current) => current.filter((t) => t.id !== id))
  }, [])

  const toast = useCallback((options: ToastOptions) => {
    const id = nextId
    nextId += 1
    setToasts((current) => [...current, { ...options, id }].slice(-MAX_VISIBLE))
  }, [])

  const value = useMemo(() => ({ toast, dismiss }), [toast, dismiss])

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(360px,calc(100vw-32px))] flex-col gap-2"
      >
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={dismiss} />
        ))}
      </div>
    </ToastContext.Provider>
  )
}

const VARIANT_STYLES: Record<ToastVariant, { border: string; dot: string }> = {
  default: { border: 'border-line-strong', dot: 'bg-fg-muted' },
  success: { border: 'border-success/30', dot: 'bg-success' },
  destructive: { border: 'border-failed/30', dot: 'bg-failed' },
}

function ToastItem({ toast, onDismiss }: { toast: ToastRecord; onDismiss: (id: number) => void }) {
  const duration = toast.duration ?? DEFAULT_DURATION

  useEffect(() => {
    if (duration <= 0) return
    const timer = setTimeout(() => onDismiss(toast.id), duration)
    return () => clearTimeout(timer)
  }, [duration, toast.id, onDismiss])

  const style = VARIANT_STYLES[toast.variant ?? 'default']

  return (
    <div
      role="status"
      className={cn(
        'pointer-events-auto flex animate-slide-down items-start gap-2.5 rounded-xl border bg-surface-4 p-3 shadow-tooltip',
        style.border,
      )}
    >
      <span className={cn('mt-[5px] h-[7px] w-[7px] shrink-0 rounded-full', style.dot)} />
      <div className="min-w-0 flex-1">
        <div className="text-base font-medium text-fg">{toast.title}</div>
        {toast.description ? (
          <div className="mt-0.5 break-words font-mono text-xs text-fg-muted">
            {toast.description}
          </div>
        ) : null}
      </div>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={() => onDismiss(toast.id)}
        className="shrink-0 rounded p-0.5 text-fg-faint transition-colors hover:bg-line hover:text-fg"
      >
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden>
          <path d="M5 5l14 14M19 5L5 19" />
        </svg>
      </button>
    </div>
  )
}

/**
 * Toast chaqirish hook'i.
 *
 * Provider'dan tashqarida chaqirilsa XATO TASHLAMAYDI — "no-op" qaytaradi.
 * Sababi: hook'lar (`useJobs` va h.k.) toast'ni ishlatadi, lekin ularni
 * testda yoki Provider'siz ishlatish mumkin bo'lishi kerak.
 */
export function useToast(): ToastContextValue {
  const context = useContext(ToastContext)
  if (context) return context
  return {
    toast: () => undefined,
    dismiss: () => undefined,
  }
}
