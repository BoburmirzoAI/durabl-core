'use client'

import { useEffect } from 'react'

/**
 * Global xato chegarasi.
 *
 * Next.js render paytidagi istalgan xatoda shu komponent ko'rsatiladi.
 * `reset()` — qayta render urinishi (sahifani to'liq yangilamasdan).
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    // Development'da xatoni konsolda ko'rish qulay; production'da bu
    // yerga Sentry kabi xizmat ulanadi
    console.error('Unhandled UI error:', error)
  }, [error])

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-canvas px-4 text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-failed/25 bg-failed/[0.08]">
        <svg
          width="22"
          height="22"
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
        <div className="text-xl font-semibold text-fg">Something broke</div>
        <p className="mx-auto mt-2 max-w-[460px] text-base text-fg-muted">
          {error.message || 'An unexpected error occurred while rendering this page.'}
        </p>
        {error.digest ? (
          <p className="mt-2 font-mono text-xs text-fg-ghost">digest {error.digest}</p>
        ) : null}
      </div>
      <button
        type="button"
        onClick={reset}
        className="rounded-lg bg-accent-solid px-4 py-2 text-base font-medium text-white hover:bg-accent-hover"
      >
        Try again
      </button>
    </div>
  )
}
