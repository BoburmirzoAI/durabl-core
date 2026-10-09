import { Skeleton } from '@/components/ui/skeleton'

/**
 * Dashboard yuklanish skeleton'i.
 *
 * Sahifa tuzilmasini TAQLID qiladi (sarlavha + kartalar + panel), shunda
 * haqiqiy kontent kelganda layout sakramaydi.
 */
export default function DashboardLoading() {
  return (
    <>
      <div className="flex items-center gap-4">
        <Skeleton className="h-7 w-40" />
        <Skeleton className="ml-auto h-8 w-32" />
      </div>

      <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="rounded-xl border border-line bg-surface px-4 py-[15px]">
            <Skeleton className="h-3 w-24" />
            <Skeleton className="mt-3 h-7 w-28" />
            <Skeleton className="mt-2.5 h-3 w-32" />
          </div>
        ))}
      </div>

      <div className="rounded-2xl border border-line bg-surface p-[18px]">
        <Skeleton className="h-4 w-28" />
        <Skeleton className="mt-4 h-[260px] w-full" />
      </div>
    </>
  )
}
