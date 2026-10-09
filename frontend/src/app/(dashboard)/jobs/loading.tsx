import { Skeleton } from '@/components/ui/skeleton'
import { SkeletonRows } from '@/components/ui/skeleton'

/** Jobs sahifasi skeleton'i — filtr paneli + jadval. */
export default function JobsLoading() {
  return (
    <>
      <div className="flex items-center gap-3">
        <Skeleton className="h-7 w-24" />
        <Skeleton className="h-6 w-16" />
        <Skeleton className="ml-auto h-8 w-32" />
      </div>

      <div className="flex flex-wrap items-center gap-2.5">
        <Skeleton className="h-8 w-[272px]" />
        <Skeleton className="h-8 w-28" />
        <Skeleton className="h-8 w-28" />
        <Skeleton className="h-8 w-28" />
      </div>

      <div className="overflow-hidden rounded-2xl border border-line bg-surface">
        <SkeletonRows
          rows={14}
          columns="36px minmax(96px,1.3fr) minmax(70px,1fr) 78px 104px 58px 78px 86px 44px"
        />
      </div>
    </>
  )
}
