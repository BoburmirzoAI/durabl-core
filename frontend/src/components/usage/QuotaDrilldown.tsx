'use client'

import { useRouter } from 'next/navigation'

import { DetailDrawer, DrawerRow, DrawerSection } from '@/components/common/DetailDrawer'
import { DrilldownChart } from '@/components/common/DrilldownChart'
import { formatNumber } from '@/lib/utils/format'
import { customRange, formatTimestamp } from '@/lib/utils/time'
import { useQuotaBreakdown } from '@/lib/hooks/useBilling'
import type { QuotaSlice } from '@/types'

/**
 * Kvota tafsiloti paneli.
 *
 * ## Nega o'lchagich yetarli emas
 *
 * "82% ishlatilgan" degan son foydali, lekin u bilan HECH NARSA qilib
 * bo'lmaydi. Harakat qilish uchun uchta narsa kerak:
 *
 * 1. **Nima hisoblanadi** — "qayta urinishlar ham sanaladimi?" degan
 *    savolga javob. Noaniqlik qo'rquv tug'diradi.
 * 2. **Kim sarflayapti** — runtime va API kalit bo'yicha taqsimot. CI
 *    kaliti kvotaning yarmini yeb qo'yganini ko'rish — aniq harakat.
 * 3. **Limitga yetganda nima bo'ladi** — rad etiladimi yoki navbatga
 *    turadimi. Bu ikki holat butunlay boshqacha oqibatga ega.
 */
export function QuotaDrilldown({
  quotaKey,
  onOpenChange,
}: {
  quotaKey: string | null
  onOpenChange: (open: boolean) => void
}) {
  const router = useRouter()
  const query = useQuotaBreakdown(quotaKey)
  const data = query.data

  return (
    <DetailDrawer
      open={quotaKey !== null}
      onOpenChange={onOpenChange}
      width="lg"
      title={data ? `${data.label} quota` : 'Quota'}
      description={data ? `Resets ${formatTimestamp(data.resets_at)}` : undefined}
      stats={
        data
          ? [
              { label: 'Used', value: data.current_label },
              { label: 'Limit', value: data.limit_label },
              {
                label: 'Consumed',
                value: `${data.percent}%`,
                tone: data.percent >= 100 ? 'bad' : data.percent >= 80 ? 'warn' : 'good',
              },
              {
                label: 'Remaining',
                value: formatNumber(Math.max(0, data.limit - data.current)),
              },
            ]
          : undefined
      }
      loading={query.isLoading}
      error={query.error}
      onRetry={() => void query.refetch()}
    >
      {data ? (
        <div className="space-y-3.5">
          <DrawerSection title="What counts">
            <p className="text-sm leading-[1.6] text-fg-dim">{data.counted}</p>
          </DrawerSection>

          <DrilldownChart
            title="Daily consumption"
            description="Click a day to open that day's jobs"
            points={data.daily.map((d) => ({ label: d.label, value: d.value, key: d.date }))}
            valueLabel={data.label}
            height={170}
            // Kun bosilganda `/jobs` o'sha sutkaga filtrlanadi — aks holda
            // grafik ostidagi tugmalar qatori o'lik bo'lib qolardi
            onSelect={(point) => {
              if (!point.key) return
              const start = new Date(point.key)
              start.setUTCHours(0, 0, 0, 0)
              const end = new Date(start.getTime() + 86_400_000 - 1)
              router.push(`/jobs?range=${encodeURIComponent(customRange(start, end))}`)
            }}
          />

          <div className="grid gap-3.5 sm:grid-cols-2">
            <DrawerSection title="By runtime">
              <SliceList slices={data.by_runtime} />
            </DrawerSection>
            <DrawerSection title="By API key">
              <SliceList slices={data.by_api_key} />
            </DrawerSection>
          </div>

          <DrawerSection title="At the limit">
            <p className="text-sm leading-[1.6] text-fg-dim">{data.at_limit}</p>
            <div className="mt-3">
              <DrawerRow
                label="Overage pricing"
                value={data.overage_label ?? 'Not available — the limit is hard'}
              />
              <DrawerRow label="Resets" value={formatTimestamp(data.resets_at)} />
            </div>
          </DrawerSection>

          {data.tips.length > 0 ? (
            <DrawerSection title="Reduce consumption">
              <ul className="space-y-2">
                {data.tips.map((tip) => (
                  <li key={tip} className="flex gap-2.5 text-sm leading-[1.55] text-fg-dim">
                    <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-accent" aria-hidden />
                    {tip}
                  </li>
                ))}
              </ul>
            </DrawerSection>
          ) : null}
        </div>
      ) : null}
    </DetailDrawer>
  )
}

/** Ulushlar ro'yxati — ustun orqa fonda, raqam o'ngda. */
function SliceList({ slices }: { slices: QuotaSlice[] }) {
  if (slices.length === 0) {
    return <p className="text-sm text-fg-dim">No data for this period.</p>
  }
  const max = Math.max(...slices.map((s) => s.percent), 1)
  return (
    <div className="space-y-px">
      {slices.map((slice) => (
        <div key={slice.label} className="relative overflow-hidden rounded-md px-2 py-1.5">
          <div
            className="absolute inset-y-0 left-0 bg-accent/[0.07]"
            style={{ width: `${(slice.percent / max) * 100}%` }}
            aria-hidden
          />
          <div className="relative flex items-center gap-2.5">
            <span className="min-w-0 flex-1 truncate text-sm capitalize text-fg-soft" title={slice.label}>
              {slice.label}
            </span>
            <span className="tabular shrink-0 font-mono text-xs text-fg-muted">
              {slice.value_label}
            </span>
            <span className="tabular w-11 shrink-0 text-right font-mono text-2xs text-fg-faint">
              {slice.percent}%
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}
