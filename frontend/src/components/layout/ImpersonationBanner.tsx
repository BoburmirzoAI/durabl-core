'use client'

import { Button } from '@/components/ui/button'
import { useImpersonationStore } from '@/stores/impersonationStore'

/**
 * "Viewing as X" bannerı.
 *
 * Qobiqning eng tepasida, hamma narsadan baland turadi — admin boshqa
 * foydalanuvchi nomidan ishlayotganini bir qarashda ko'rishi SHART.
 */
export function ImpersonationBanner() {
  const target = useImpersonationStore((s) => s.target)
  const stop = useImpersonationStore((s) => s.stop)

  if (!target) return null

  return (
    <div className="flex shrink-0 items-center gap-2.5 border-b border-pending/30 bg-pending/[0.10] px-4 py-2">
      <svg
        width="15"
        height="15"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.9"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="shrink-0 text-pending"
        aria-hidden
      >
        <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
        <circle cx="12" cy="12" r="2.6" />
      </svg>
      <span className="min-w-0 flex-1 truncate text-sm text-fg-soft">
        Viewing as <span className="font-medium text-fg">{target.email}</span>
        <span className="text-fg-dim"> · {target.plan} plan · read-only</span>
      </span>
      <Button variant="secondary" size="sm" onClick={stop} className="shrink-0">
        Exit
      </Button>
    </div>
  )
}
