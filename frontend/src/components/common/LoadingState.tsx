import { cn } from '@/lib/utils/cn'

/** Aylanuvchi indikator. */
export function Spinner({ className, size = 16 }: { className?: string; size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      className={cn('animate-spin text-fg-faint', className)}
      aria-hidden
    >
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="2.5" opacity="0.2" />
      <path
        d="M21 12a9 9 0 0 0-9-9"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  )
}

/** Markazlashgan yuklanish holati (panel ichida). */
export function LoadingState({
  label = 'Loading…',
  className,
}: {
  label?: string
  className?: string
}) {
  return (
    <div
      className={cn('flex items-center justify-center gap-2.5 px-4 py-14', className)}
      aria-busy="true"
      aria-live="polite"
    >
      <Spinner />
      <span className="text-sm text-fg-faint">{label}</span>
    </div>
  )
}
