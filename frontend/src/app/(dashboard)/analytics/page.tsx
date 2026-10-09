'use client'

import { useRouter } from 'next/navigation'
import { useMemo, useState } from 'react'

import { BusiestHoursHeatmap } from '@/components/analytics/BusiestHoursHeatmap'
import { ComparisonStrip } from '@/components/analytics/ComparisonStrip'
import { CostEfficiencyChart } from '@/components/analytics/CostEfficiencyChart'
import { DlqDepthChart } from '@/components/analytics/DlqDepthChart'
import { FailureReasonsTable } from '@/components/analytics/FailureReasonsTable'
import { KpiCard } from '@/components/analytics/KpiCard'
import { LatencyHistogram } from '@/components/analytics/LatencyHistogram'
import { LatencyPercentileChart } from '@/components/analytics/LatencyPercentileChart'
import { RangeSelector } from '@/components/analytics/RangeSelector'
import { RetryRateChart } from '@/components/analytics/RetryRateChart'
import { RuntimeComparisonTable } from '@/components/analytics/RuntimeComparisonTable'
import { SlowestJobsTable } from '@/components/analytics/SlowestJobsTable'
import { SuccessRateChart } from '@/components/analytics/SuccessRateChart'
import { ThroughputChart } from '@/components/analytics/ThroughputChart'
import { WindowDrilldown } from '@/components/analytics/WindowDrilldown'
import { WorkerEfficiencyTable } from '@/components/analytics/WorkerEfficiencyTable'
import { DrilldownChart, type DrilldownPoint } from '@/components/common/DrilldownChart'
import { SectionHeader } from '@/components/common/SectionHeader'
import { useToast } from '@/components/common/ToastProvider'
import { Button } from '@/components/ui/button'
import { Tabs } from '@/components/ui/tabs'
import {
  useAnalyticsOverview,
  useBusiestHours,
  useCostEfficiency,
  useLatencyPercentiles,
  usePeriodComparison,
  useRetryRate,
  useRuntimeComparison,
  useSlowestJobs,
  useWorkerEfficiency,
} from '@/lib/hooks/useAnalytics'
import { downloadCsv, timestampedName, toCsv } from '@/lib/utils/csv'
import { rangeLabel } from '@/lib/utils/time'
import type { ThroughputPoint } from '@/types'

type Section = 'performance' | 'reliability' | 'efficiency'

const SECTION_TABS = [
  { value: 'performance' as Section, label: 'Performance' },
  { value: 'reliability' as Section, label: 'Reliability' },
  { value: 'efficiency' as Section, label: 'Efficiency' },
] as const

/**
 * Analitika — TARIXIY ish samaradorligi tahlili.
 *
 * ═══════════════════════════════════════════════════════════════════
 * BU SAHIFANING VAZIFASI
 * ═══════════════════════════════════════════════════════════════════
 *
 * "Tizim vaqt o'tishi bilan QANDAY ishlayapti?"
 *
 * Joriy holat (hozir nima bo'layotgani) `/dashboard` da, hisob va kvota
 * `/usage` da. Bu yerda faqat TENDENSIYA va SOLISHTIRISH.
 *
 * ## Nega uchta bo'lim
 *
 * To'liq tahlil ~14 ta panel beradi; ularni bitta uzun sahifaga tizish
 * foydalanuvchini aylantirib charchatadi. Bo'limlar savolga qarab
 * ajratilgan:
 *
 * - **Performance** — tezmi? (o'tkazuvchanlik, kechikish, band soatlar)
 * - **Reliability** — ishonchlimi? (muvaffaqiyat, qayta urinish, DLQ, xatolar)
 * - **Efficiency** — arzonmi? (runtime, worker, job narxi)
 *
 * KPI qatori va davrlar solishtiruvi bo'limlardan YUQORIDA turadi,
 * chunki ular uchala savolga ham tegishli.
 *
 * Vaqt oralig'i BUTUN sahifani boshqaradi va ixtiyoriy sana bo'lishi
 * mumkin (`custom:<from>|<to>`).
 */
export default function AnalyticsPage() {
  const [range, setRange] = useState<string>('24h')
  const [section, setSection] = useState<Section>('performance')
  const [compare, setCompare] = useState(false)
  const [drilldown, setDrilldown] = useState<ThroughputPoint | null>(null)
  const { toast } = useToast()
  const router = useRouter()

  const query = useAnalyticsOverview(range)
  const comparison = usePeriodComparison(range, compare)
  const percentiles = useLatencyPercentiles(range)
  const busiest = useBusiestHours()
  const slowest = useSlowestJobs(8)
  const retry = useRetryRate(range)
  const cost = useCostEfficiency(range)
  const runtimes = useRuntimeComparison()
  const workers = useWorkerEfficiency()

  // Grafik qadami — drill-down oynasining uzunligini shu belgilaydi
  const stepMinutes = useMemo(() => {
    const points = query.data?.throughput.points
    if (!points || points.length < 2) return 30
    const a = new Date(points[0]!.timestamp).getTime()
    const b = new Date(points[1]!.timestamp).getTime()
    return Math.max(1, Math.round((b - a) / 60_000))
  }, [query.data])

  // Xatolar taqsimoti — bosilganda DLQ sahifasiga olib boradi
  const errorPoints: DrilldownPoint[] = useMemo(
    () =>
      (query.data?.top_failures ?? []).map((row) => ({
        label: row.label,
        value: row.count,
        key: row.reason,
        tone: 'failed' as const,
      })),
    [query.data],
  )

  function exportCsv(): void {
    const data = query.data
    if (!data) {
      toast({ title: 'Nothing to export yet' })
      return
    }
    if (section === 'performance') {
      downloadCsv(
        timestampedName('durabl-throughput'),
        toCsv(data.throughput.points, [
          { header: 'timestamp', value: (r) => r.timestamp },
          { header: 'label', value: (r) => r.label },
          { header: 'completed', value: (r) => r.completed },
          { header: 'failed', value: (r) => r.failed },
        ]),
      )
      toast({ title: `Exported ${data.throughput.points.length} throughput points` })
      return
    }
    if (section === 'reliability') {
      const points = retry.data?.points ?? []
      downloadCsv(
        timestampedName('durabl-retry-rate'),
        toCsv(points, [
          { header: 'timestamp', value: (r) => r.timestamp },
          { header: 'retry_rate_percent', value: (r) => r.retry_rate },
          { header: 'first_attempt_success_percent', value: (r) => r.first_attempt_success },
          { header: 'retried', value: (r) => r.retried },
          { header: 'total', value: (r) => r.total },
        ]),
      )
      toast({ title: `Exported ${points.length} reliability points` })
      return
    }
    const points = cost.data?.points ?? []
    downloadCsv(
      timestampedName('durabl-cost-per-job'),
      toCsv(points, [
        { header: 'timestamp', value: (r) => r.timestamp },
        { header: 'jobs', value: (r) => r.jobs },
        { header: 'cost_usd', value: (r) => r.cost_usd },
        { header: 'cost_per_job_usd', value: (r) => r.cost_per_job },
        { header: 'compute_seconds_per_job', value: (r) => r.compute_seconds_per_job },
      ]),
    )
    toast({ title: `Exported ${points.length} cost points` })
  }

  return (
    <>
      <SectionHeader
        title="Analytics"
        description={`Historical performance · ${rangeLabel(range)}`}
        actions={<RangeSelector value={range} onChange={setRange} />}
      />

      <div className="flex flex-wrap items-center gap-2">
        <Tabs aria-label="Analytics section" items={SECTION_TABS} value={section} onChange={setSection} />
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant={compare ? 'bulk' : 'secondary'}
            onClick={() => setCompare((on) => !on)}
            aria-pressed={compare}
          >
            {compare ? '✓ Comparing periods' : 'Compare periods'}
          </Button>
          <Button variant="secondary" onClick={exportCsv}>
            Export CSV
          </Button>
        </div>
      </div>

      {compare ? (
        <ComparisonStrip data={comparison.data} loading={comparison.isLoading} />
      ) : (
        <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
          {query.data
            ? query.data.kpis.map((kpi) => <KpiCard key={kpi.label} data={kpi} />)
            : Array.from({ length: 4 }, (_, i) => (
                <KpiCard
                  key={i}
                  loading
                  data={{
                    label: '',
                    value: '',
                    trend: '',
                    trend_direction: 'flat',
                    trend_is_good: true,
                    sub: '',
                    sparkline: [],
                  }}
                />
              ))}
        </div>
      )}

      {section === 'performance' ? (
        <>
          <ThroughputChart
            title="Throughput over time"
            description={`Completed vs failed · ${rangeLabel(range)} · click a point to drill in`}
            data={query.data?.throughput}
            loading={query.isLoading}
            error={query.error}
            onRetry={() => void query.refetch()}
            height={300}
            onSelectPoint={setDrilldown}
          />

          <LatencyPercentileChart
            data={percentiles.data}
            loading={percentiles.isLoading}
            error={percentiles.error}
            onRetry={() => void percentiles.refetch()}
          />

          <div className="grid gap-4 xl:grid-cols-2">
            <LatencyHistogram
              data={query.data?.latency}
              loading={query.isLoading}
              error={query.error}
              onRetry={() => void query.refetch()}
            />
            <BusiestHoursHeatmap
              data={busiest.data}
              loading={busiest.isLoading}
              error={busiest.error}
              onRetry={() => void busiest.refetch()}
            />
          </div>
        </>
      ) : null}

      {section === 'reliability' ? (
        <>
          <RetryRateChart
            data={retry.data}
            loading={retry.isLoading}
            error={retry.error}
            onRetry={() => void retry.refetch()}
          />

          <div className="grid gap-4 xl:grid-cols-2">
            <SuccessRateChart
              data={query.data?.success_rate}
              loading={query.isLoading}
              error={query.error}
              onRetry={() => void query.refetch()}
            />
            <DlqDepthChart
              data={query.data?.dlq_depth}
              loading={query.isLoading}
              error={query.error}
              onRetry={() => void query.refetch()}
            />
          </div>

          <div className="grid items-start gap-4 xl:grid-cols-2">
            <DrilldownChart
              title="Error breakdown"
              description="Click a bar to open the matching dead letters"
              points={errorPoints}
              valueLabel="Failures"
              loading={query.isLoading}
              error={query.error}
              onRetry={() => void query.refetch()}
              // DLQ sahifasi `?reason=` ni o'qiydi va jadvalni shu sababga
              // toraytiradi — grafikdan to'g'ridan-to'g'ri yozuvlarga o'tiladi
              onSelect={(point) => {
                if (point.key) router.push(`/dlq?reason=${encodeURIComponent(point.key)}`)
              }}
            />
            <FailureReasonsTable rows={query.data?.top_failures} />
          </div>
        </>
      ) : null}

      {section === 'efficiency' ? (
        <>
          <CostEfficiencyChart
            data={cost.data}
            loading={cost.isLoading}
            error={cost.error}
            onRetry={() => void cost.refetch()}
          />
          <RuntimeComparisonTable rows={runtimes.data} loading={runtimes.isLoading} />
          <WorkerEfficiencyTable data={workers.data} loading={workers.isLoading} />
          <SlowestJobsTable rows={slowest.data} loading={slowest.isLoading} />
        </>
      ) : null}

      <WindowDrilldown
        point={drilldown}
        stepMinutes={stepMinutes}
        onOpenChange={(open) => {
          if (!open) setDrilldown(null)
        }}
      />
    </>
  )
}
