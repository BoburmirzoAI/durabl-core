'use client'

import { useState } from 'react'

import { BusiestHoursHeatmap } from '@/components/analytics/BusiestHoursHeatmap'
import { CostEfficiencyChart } from '@/components/analytics/CostEfficiencyChart'
import { DlqDepthChart } from '@/components/analytics/DlqDepthChart'
import { LatencyPercentileChart } from '@/components/analytics/LatencyPercentileChart'
import { RetryRateChart } from '@/components/analytics/RetryRateChart'
import { SuccessRateChart } from '@/components/analytics/SuccessRateChart'
import { ThroughputChart } from '@/components/analytics/ThroughputChart'
import { WorkerEfficiencyTable } from '@/components/analytics/WorkerEfficiencyTable'
import { RangeSelector } from '@/components/analytics/RangeSelector'
import { SectionHeader } from '@/components/common/SectionHeader'
import { StatCard } from '@/components/analytics/KpiCard'
import { Badge } from '@/components/ui/badge'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { SkeletonRows } from '@/components/ui/skeleton'
import {
  useAnalyticsOverview,
  useCostEfficiency,
  useLatencyPercentiles,
  useBusiestHours,
  useRetryRate,
  useWorkerEfficiency,
} from '@/lib/hooks/useAnalytics'
import { usePlanWorkload } from '@/lib/hooks/useAdminOps'
import { cn } from '@/lib/utils/cn'
import { formatCurrency, formatDuration, formatNumber } from '@/lib/utils/format'
import { rangeLabel } from '@/lib/utils/time'
import type { StatCardData } from '@/types'

const PLAN_GRID = 'minmax(100px,1fr) 90px 100px 96px 96px 90px 86px'

/**
 * Admin — platforma analitikasi.
 *
 * ═══════════════════════════════════════════════════════════════════
 * MIJOZNING `/analytics` SAHIFASIDAN FARQI
 * ═══════════════════════════════════════════════════════════════════
 *
 * Grafiklar bir xil ko'rinadi, lekin savol boshqa: mijoz O'Z ishini
 * ko'radi, admin esa BUTUN platformani va uni TARIF bo'yicha ajratib
 * ko'radi.
 *
 * "Tarif bo'yicha ish hajmi" jadvali aynan shu farqni beradi: bepul
 * tarif resurslarning qanchasini yeyapti, enterprise mijozlar va'da
 * qilingan sifatni olyaptimi — bularning ikkalasi ham biznes qarori.
 */
export default function AdminAnalyticsPage() {
  const [range, setRange] = useState<string>('24h')

  const overview = useAnalyticsOverview(range)
  const percentiles = useLatencyPercentiles(range)
  const retry = useRetryRate(range)
  const cost = useCostEfficiency(range)
  const busiest = useBusiestHours()
  const workers = useWorkerEfficiency()
  const byPlan = usePlanWorkload()

  const data = overview.data
  const total = data ? data.throughput.total_completed + data.throughput.total_failed : 0

  const cards: StatCardData[] = data
    ? [
        {
          label: 'Jobs processed',
          value: formatNumber(total),
          trend: `${formatNumber(data.throughput.peak)} peak`,
          trend_direction: 'flat',
          trend_is_good: true,
          sub: rangeLabel(range),
        },
        {
          label: 'Success rate',
          value: `${total === 0 ? 0 : Math.round((data.throughput.total_completed / total) * 1_000) / 10}%`,
          trend: `${formatNumber(data.throughput.total_failed)} failed`,
          trend_direction: 'flat',
          trend_is_good: data.throughput.total_failed / Math.max(1, total) < 0.02,
          sub: 'platform wide',
        },
        {
          label: 'p99 latency',
          value: formatDuration(percentiles.data?.p99 ?? 0),
          trend: `p50 ${formatDuration(percentiles.data?.p50 ?? 0)}`,
          trend_direction: 'flat',
          trend_is_good: (percentiles.data?.p99 ?? 0) < (percentiles.data?.sla_ms ?? 2_000),
          sub: 'the tail users feel',
          is_alert: (percentiles.data?.p99 ?? 0) > (percentiles.data?.sla_ms ?? 2_000),
        },
        {
          label: 'Compute spend',
          value: formatCurrency(cost.data?.total_usd ?? 0),
          trend: `${formatCurrency(cost.data?.wasted_usd ?? 0)} wasted`,
          trend_direction: 'flat',
          trend_is_good: (cost.data?.wasted_usd ?? 0) / Math.max(0.01, cost.data?.total_usd ?? 1) < 0.1,
          sub: 'failures and retries',
        },
      ]
    : []

  return (
    <>
      <SectionHeader
        title="Analytics"
        description={`Platform wide · ${rangeLabel(range)}`}
        count={<Badge variant="danger">ADMIN</Badge>}
        actions={<RangeSelector value={range} onChange={setRange} />}
      />

      <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
        {data
          ? cards.map((card) => <StatCard key={card.label} data={card} />)
          : Array.from({ length: 4 }, (_, i) => (
              <StatCard
                key={i}
                loading
                data={{
                  label: '',
                  value: '',
                  trend: '',
                  trend_direction: 'flat',
                  trend_is_good: true,
                  sub: '',
                }}
              />
            ))}
      </div>

      <ThroughputChart
        title="Platform throughput"
        description={`Every account combined · ${rangeLabel(range)}`}
        data={data?.throughput}
        loading={overview.isLoading}
        error={overview.error}
        onRetry={() => void overview.refetch()}
        height={280}
      />

      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle className="text-md">Workload by plan</CardTitle>
          <CardDescription>
            Who is consuming the platform, and whether the paying tiers are getting better service
          </CardDescription>
        </CardHeader>

        <div className="overflow-x-auto">
          <div className="min-w-[700px]">
            <div
              className="table-head grid items-center gap-3 px-4"
              style={{ gridTemplateColumns: PLAN_GRID }}
            >
              <span>Plan</span>
              <span className="text-right">Accounts</span>
              <span className="text-right">Jobs 24h</span>
              <span className="text-right">Share</span>
              <span className="text-right">Success</span>
              <span className="text-right">p95</span>
              <span className="text-right">DLQ</span>
            </div>

            {byPlan.isLoading && !byPlan.data ? (
              <SkeletonRows rows={4} columns={PLAN_GRID} />
            ) : (
              (byPlan.data ?? []).map((row) => (
                <div
                  key={row.plan}
                  className="grid h-11 items-center gap-3 border-b border-line-subtle px-4 last:border-b-0 hover:bg-surface-3"
                  style={{ gridTemplateColumns: PLAN_GRID }}
                >
                  <span className="text-base capitalize text-fg-soft">{row.plan}</span>
                  <span className="tabular text-right font-mono text-sm text-fg-muted">
                    {formatNumber(row.accounts)}
                  </span>
                  <span className="tabular text-right font-mono text-sm text-fg-muted">
                    {formatNumber(row.jobs_24h)}
                  </span>
                  <span className="tabular text-right font-mono text-sm text-fg-faint">
                    {row.share}%
                  </span>
                  <span
                    className={cn(
                      'tabular text-right font-mono text-sm',
                      row.success_rate >= 98 ? 'text-success' : 'text-pending',
                    )}
                  >
                    {row.success_rate}%
                  </span>
                  <span className="tabular text-right font-mono text-sm text-fg-faint">
                    {formatDuration(row.p95_ms)}
                  </span>
                  <span
                    className={cn(
                      'tabular text-right font-mono text-sm',
                      row.dlq_depth > 0 ? 'text-failed-text' : 'text-fg-ghost',
                    )}
                  >
                    {row.dlq_depth}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </Card>

      <LatencyPercentileChart
        data={percentiles.data}
        loading={percentiles.isLoading}
        error={percentiles.error}
        onRetry={() => void percentiles.refetch()}
      />

      <div className="grid gap-4 xl:grid-cols-2">
        <SuccessRateChart
          data={data?.success_rate}
          loading={overview.isLoading}
          error={overview.error}
        />
        <DlqDepthChart
          data={data?.dlq_depth}
          loading={overview.isLoading}
          error={overview.error}
        />
      </div>

      <RetryRateChart
        data={retry.data}
        loading={retry.isLoading}
        error={retry.error}
        onRetry={() => void retry.refetch()}
      />

      <CostEfficiencyChart
        data={cost.data}
        loading={cost.isLoading}
        error={cost.error}
        onRetry={() => void cost.refetch()}
      />

      <div className="grid items-start gap-4 xl:grid-cols-2">
        <BusiestHoursHeatmap
          data={busiest.data}
          loading={busiest.isLoading}
          error={busiest.error}
        />
        <WorkerEfficiencyTable data={workers.data} loading={workers.isLoading} />
      </div>
    </>
  )
}
