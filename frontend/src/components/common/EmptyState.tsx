import { cn } from '@/lib/utils/cn'

/**
 * Bo'sh holat — dizaynda oddiy matn (`No jobs match your filters.`), lekin
 * foydali bo'lishi uchun ikonka va harakat tugmasi qo'shilgan.
 */
export interface EmptyStateProps {
  /** SVG `path` ning `d` atributi (24×24). */
  icon?: string
  title: string
  description?: string
  action?: React.ReactNode
  /** Ijobiy bo'sh holat (DLQ bo'sh = yaxshi xabar). */
  tone?: 'neutral' | 'positive'
  className?: string
}

export function EmptyState({
  icon,
  title,
  description,
  action,
  tone = 'neutral',
  className,
}: EmptyStateProps) {
  return (
    <div className={cn('flex flex-col items-center gap-3 px-4 py-14 text-center', className)}>
      {icon ? (
        <div
          className={cn(
            'flex h-11 w-11 items-center justify-center rounded-xl border',
            tone === 'positive'
              ? 'border-success/25 bg-success/[0.08]'
              : 'border-line bg-surface-2',
          )}
        >
          <svg
            width="20"
            height="20"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.7"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={tone === 'positive' ? 'text-success' : 'text-fg-faint'}
            aria-hidden
          >
            <path d={icon} />
          </svg>
        </div>
      ) : null}
      <div>
        <div className="text-base font-medium text-fg-soft">{title}</div>
        {description ? (
          <div className="mx-auto mt-1 max-w-[380px] text-sm text-fg-faint">{description}</div>
        ) : null}
      </div>
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  )
}
