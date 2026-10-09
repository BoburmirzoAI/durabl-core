'use client'

import { Button } from '@/components/ui/button'
import { ApiError } from '@/lib/api/client'
import { cn } from '@/lib/utils/cn'

/**
 * Xato holati — ma'lumot yuklanmaganda.
 *
 * `ApiError` bo'lsa backend kodi (`JOB_NOT_FOUND`) ham ko'rsatiladi:
 * dasturchi uchun bu eng foydali ma'lumot.
 */
export interface ErrorStateProps {
  error: unknown
  onRetry?: () => void
  className?: string
}

export function ErrorState({ error, onRetry, className }: ErrorStateProps) {
  const apiError = error instanceof ApiError ? error : null
  const message =
    apiError?.message ?? (error instanceof Error ? error.message : 'Something went wrong')

  return (
    <div className={cn('flex flex-col items-center gap-3 px-4 py-14 text-center', className)}>
      <div className="flex h-11 w-11 items-center justify-center rounded-xl border border-failed/25 bg-failed/[0.08]">
        <svg
          width="20"
          height="20"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          className="text-failed"
          aria-hidden
        >
          <path d="M12 3 2 20h20zM12 10v4M12 17h.01" />
        </svg>
      </div>
      <div>
        <div className="text-base font-medium text-fg-soft">Failed to load</div>
        <div className="mx-auto mt-1 max-w-[420px] text-sm text-fg-faint">{message}</div>
        {apiError ? (
          <div className="mt-2 font-mono text-xs text-fg-faint">
            {apiError.code}
            {apiError.requestId ? ` · ${apiError.requestId.slice(0, 12)}` : ''}
          </div>
        ) : null}
      </div>
      {onRetry ? (
        <Button variant="secondary" size="sm" onClick={onRetry} className="mt-1">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M3 12a9 9 0 1 0 3-6.7M3 3v4h4" />
          </svg>
          Try again
        </Button>
      ) : null}
    </div>
  )
}
