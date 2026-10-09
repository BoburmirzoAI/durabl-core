import { cn } from '@/lib/utils/cn'

/** Yuklanish bloki — `globals.css` dagi `.skeleton` shimmer bilan. */
export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('skeleton h-4 w-full', className)} {...props} />
}

/** Jadval uchun skeleton qatorlar. */
export function SkeletonRows({
  rows = 8,
  columns,
  className,
}: {
  rows?: number
  /** Ustun kengliklari (grid-template-columns) — jadval bilan bir xil. */
  columns: string
  className?: string
}) {
  return (
    <div className={className} aria-busy="true" aria-live="polite">
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          className="grid h-10 items-center gap-3 border-b border-line-subtle px-3.5"
          style={{ gridTemplateColumns: columns }}
        >
          {columns.split(' ').map((_col, c) => (
            <Skeleton key={c} className="h-3" />
          ))}
        </div>
      ))}
    </div>
  )
}
