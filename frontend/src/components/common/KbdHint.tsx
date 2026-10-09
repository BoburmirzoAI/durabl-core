import { cn } from '@/lib/utils/cn'

/** Klaviatura yorlig'i nishoni (`⌘K`). */
export function KbdHint({ children, className }: { children: React.ReactNode; className?: string }) {
  return <span className={cn('kbd shrink-0', className)}>{children}</span>
}

/** Bir nechta tugma ketma-ketligi (`↑ ↓ navigate`). */
export function KbdGroup({
  keys,
  label,
  className,
}: {
  keys: string[]
  label: string
  className?: string
}) {
  return (
    <span className={cn('flex items-center gap-1.5 text-xs text-fg-faint', className)}>
      {keys.map((key) => (
        <span key={key} className="rounded-sm border border-line px-1.5 py-px font-mono text-fg-dim">
          {key}
        </span>
      ))}
      {label}
    </span>
  )
}
