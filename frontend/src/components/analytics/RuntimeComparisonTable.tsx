'use client'

import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { SkeletonRows } from '@/components/ui/skeleton'
import { formatDuration, formatNumber } from '@/lib/utils/format'
import type { RuntimeComparisonRow } from '@/types'

const GRID = 'minmax(96px,1fr) 70px 78px 78px 78px 80px 86px 82px'

/**
 * Runtime'larni yonma-yon solishtirish.
 *
 * ## Nega jadval, grafik emas
 *
 * Bu yerda 8 ta har xil o'lchov birligi bor (soni, foiz, ms, MB, dollar).
 * Ularni bitta grafikka solishtirib bo'lmaydi. Jadval esa "Python mi,
 * Node mi?" degan savolga qator-ma-qator javob beradi.
 *
 * Har bir ustunda ENG YAXSHI qiymat ajratib ko'rsatiladi — aks holda
 * foydalanuvchi raqamlarni o'zi solishtirishga majbur bo'ladi.
 */
export function RuntimeComparisonTable({
  rows,
  loading,
}: {
  rows: RuntimeComparisonRow[] | undefined
  loading?: boolean
}) {
  const data = rows ?? []
  // Har bir ustunning g'olibi — faqat 2+ runtime bo'lsa ma'noli
  const best = {
    success: Math.max(...data.map((r) => r.success_rate), 0),
    p50: Math.min(...data.map((r) => r.p50_ms), Number.POSITIVE_INFINITY),
    p95: Math.min(...data.map((r) => r.p95_ms), Number.POSITIVE_INFINITY),
    memory: Math.min(...data.map((r) => r.avg_memory_mb), Number.POSITIVE_INFINITY),
    cost: Math.min(...data.map((r) => r.cost_per_1k), Number.POSITIVE_INFINITY),
    cold: Math.min(...data.map((r) => r.cold_start_ms), Number.POSITIVE_INFINITY),
  }
  const compare = data.length > 1

  const win = (isBest: boolean): string =>
    compare && isBest ? 'text-success' : 'text-fg-muted'

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">Runtime comparison</CardTitle>
        <CardDescription>
          Same workload, different runtimes — green marks the better number
        </CardDescription>
      </CardHeader>

      <div className="overflow-x-auto">
        <div className="min-w-[760px]">
          <div className="table-head grid items-center gap-3 px-4" style={{ gridTemplateColumns: GRID }}>
            <span>Runtime</span>
            <span className="text-right">Jobs</span>
            <span className="text-right">Success</span>
            <span className="text-right">p50</span>
            <span className="text-right">p95</span>
            <span className="text-right">Memory</span>
            <span className="text-right">Cold start</span>
            <span className="text-right">$ / 1k</span>
          </div>

          {loading && data.length === 0 ? (
            <SkeletonRows rows={2} columns={GRID} />
          ) : (
            data.map((row) => (
              <div
                key={row.runtime}
                className="grid h-11 items-center gap-3 border-b border-line-subtle px-4 last:border-b-0 hover:bg-surface-3"
                style={{ gridTemplateColumns: GRID }}
              >
                <span className="flex items-center gap-2">
                  <span className="text-base capitalize text-fg-soft">{row.runtime}</span>
                  <span className="tabular font-mono text-2xs text-fg-faint">{row.share}%</span>
                </span>
                <span className="tabular text-right font-mono text-sm text-fg-muted">
                  {formatNumber(row.jobs)}
                </span>
                <span
                  className={`tabular text-right font-mono text-sm ${win(row.success_rate === best.success)}`}
                >
                  {row.success_rate}%
                </span>
                <span className={`tabular text-right font-mono text-sm ${win(row.p50_ms === best.p50)}`}>
                  {formatDuration(row.p50_ms)}
                </span>
                <span className={`tabular text-right font-mono text-sm ${win(row.p95_ms === best.p95)}`}>
                  {formatDuration(row.p95_ms)}
                </span>
                <span
                  className={`tabular text-right font-mono text-sm ${win(row.avg_memory_mb === best.memory)}`}
                >
                  {row.avg_memory_mb} MB
                </span>
                <span
                  className={`tabular text-right font-mono text-sm ${win(row.cold_start_ms === best.cold)}`}
                >
                  {row.cold_start_ms} ms
                </span>
                <span
                  className={`tabular text-right font-mono text-sm ${win(row.cost_per_1k === best.cost)}`}
                >
                  ${row.cost_per_1k.toFixed(4)}
                </span>
              </div>
            ))
          )}
        </div>
      </div>
    </Card>
  )
}
