'use client'

import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils/cn'
import { formatCompact, formatNumber } from '@/lib/utils/format'
import { runtimeStyle } from '@/lib/utils/status'
import type { RuntimeCost } from '@/types'

/**
 * Runtime bo'yicha XARAJAT taqsimoti.
 *
 * Nega donut emas: bu yerda muhimi ulush emas, balki aniq raqamlar —
 * qancha job, qancha compute-sekund va qancha dollar. Donut faqat
 * foizni ko'rsatadi, raqamlarni esa yonidagi afsonaga surib qo'yadi.
 */
export function RuntimeCostTable({
  rows,
  loading,
}: {
  rows: RuntimeCost[] | undefined
  loading?: boolean
}) {
  const total = (rows ?? []).reduce((sum, r) => sum + r.cost_usd, 0)

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">Cost by runtime</CardTitle>
        <span className="text-xs text-fg-dim">Compute is billed per second, not per job</span>
      </CardHeader>

      <div className="flex flex-col gap-3.5 p-4">
        {loading || !rows ? (
          <Skeleton className="h-28 w-full" />
        ) : (
          <>
            {rows.map((row) => {
              const style = runtimeStyle(row.runtime)
              return (
                <div key={row.runtime}>
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="flex items-center gap-2">
                      <span className={cn('h-2 w-2 rounded-full', style.dot)} aria-hidden />
                      <span className="text-base text-fg-soft">{row.runtime}</span>
                      <span className="text-xs text-fg-faint">
                        {formatNumber(row.jobs)} jobs · {formatCompact(row.compute_seconds)}s
                      </span>
                    </span>
                    <span className="tabular shrink-0 font-mono text-base text-fg">
                      ${row.cost_usd.toFixed(2)}
                    </span>
                  </div>
                  <div className="mt-2 h-1.5 overflow-hidden rounded-sm bg-line">
                    <div
                      className={cn('h-full rounded-sm transition-[width] duration-500', style.dot)}
                      style={{ width: `${row.percent}%` }}
                    />
                  </div>
                </div>
              )
            })}

            <div className="flex items-center justify-between border-t border-line-subtle pt-3 text-sm">
              <span className="text-fg-dim">Compute total</span>
              <span className="tabular font-mono text-fg">${total.toFixed(2)}</span>
            </div>
          </>
        )}
      </div>
    </Card>
  )
}
