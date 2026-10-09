'use client'

import { Progress } from '@/components/ui/progress'
import { formatDurationShort, formatNumber } from '@/lib/utils/format'
import type { LatencyHistogram as LatencyData } from '@/types'

import { ChartFrame } from './ChartFrame'

/**
 * Latency taqsimoti — gorizontal ustunlar.
 *
 * Recharts ISHLATILMAYDI: bu aslida gorizontal bar ro'yxati, HTML
 * progress bar bilan aniqroq va yengilroq chiqadi (dizaynda ham
 * shunday ko'rinadi). Pastda p50/p95/p99 ko'rsatkichlari.
 */
export function LatencyHistogram({
  data,
  loading,
  error,
  onRetry,
}: {
  data: LatencyData | undefined
  loading?: boolean
  error?: unknown
  onRetry?: () => void
}) {
  return (
    <ChartFrame
      compact
      title="Latency Distribution"
      description="Execution duration buckets"
      height={200}
      loading={loading}
      error={error}
      onRetry={onRetry}
      isEmpty={!data || data.buckets.every((b) => b.count === 0)}
    >
      <div className="flex flex-col gap-2.5">
        {data?.buckets.map((bucket) => (
          <div key={bucket.label} className="flex items-center gap-3">
            <span className="tabular w-[72px] shrink-0 font-mono text-xs text-fg-faint">
              {bucket.label}
            </span>
            <Progress
              value={bucket.ratio * 100}
              size="md"
              barClassName="bg-accent"
              aria-label={`${bucket.label}: ${bucket.count} jobs`}
            />
            <span className="tabular w-11 shrink-0 text-right font-mono text-xs text-fg-muted">
              {formatNumber(bucket.count)}
            </span>
          </div>
        ))}
      </div>

      {data ? (
        <div className="mt-4 grid grid-cols-4 gap-2 border-t border-line-inner pt-3">
          {(
            [
              ['p50', data.p50_ms],
              ['p90', data.p90_ms],
              ['p95', data.p95_ms],
              ['p99', data.p99_ms],
            ] as const
          ).map(([label, value]) => (
            <div key={label}>
              <div className="text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                {label}
              </div>
              <div className="tabular mt-1 font-mono text-base font-semibold text-fg">
                {formatDurationShort(value)}
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </ChartFrame>
  )
}
