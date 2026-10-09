import { cn } from '@/lib/utils/cn'

/**
 * Sahifa sarlavhasi qatori — dizaynda `h1` 20px/600, o'ng tomonda
 * amal tugmalari va tanlagichlar.
 */
export interface SectionHeaderProps {
  title: string
  /** Sarlavha yonidagi son nishoni (`12,847`). */
  count?: React.ReactNode
  description?: string
  actions?: React.ReactNode
  className?: string
}

export function SectionHeader({
  title,
  count,
  description,
  actions,
  className,
}: SectionHeaderProps) {
  return (
    <div className={cn('flex flex-wrap items-start gap-4', className)}>
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="m-0 text-2xl font-semibold tracking-[-.02em] text-fg">{title}</h1>
          {count}
        </div>
        {description ? <div className="mt-[5px] text-base text-fg-dim">{description}</div> : null}
      </div>
      {actions ? <div className="ml-auto flex flex-wrap items-center gap-3">{actions}</div> : null}
    </div>
  )
}

/** Sarlavha yonidagi neytral son nishoni. */
export function CountPill({ children }: { children: React.ReactNode }) {
  return (
    <span className="tabular rounded-md border border-line bg-surface-2 px-2.5 py-[3px] font-mono text-sm font-medium text-fg-muted">
      {children}
    </span>
  )
}
