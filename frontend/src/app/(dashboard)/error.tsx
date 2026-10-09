'use client'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'

/** Dashboard bo'limidagi xato chegarasi — qobiq (sidebar) saqlanadi. */
export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <Card className="flex flex-col items-center gap-3 px-4 py-14 text-center">
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
        <div className="text-base font-medium text-fg-soft">This page failed to render</div>
        <div className="mx-auto mt-1 max-w-[420px] text-sm text-fg-faint">
          {error.message || 'An unexpected error occurred.'}
        </div>
      </div>
      <Button variant="secondary" size="sm" onClick={reset} className="mt-1">
        Try again
      </Button>
    </Card>
  )
}
