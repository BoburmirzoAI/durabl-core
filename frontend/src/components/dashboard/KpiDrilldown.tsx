'use client'

import { useRouter } from 'next/navigation'

import { DetailDrawer, DrawerRow, DrawerSection } from '@/components/common/DetailDrawer'
import { DrilldownChart, type DrilldownPoint } from '@/components/common/DrilldownChart'
import { Button } from '@/components/ui/button'
import { useJobs } from '@/lib/hooks/useJobs'
import { formatDuration, formatNumber, formatPercent } from '@/lib/utils/format'
import { jobStatusStyle, runtimeStyle } from '@/lib/utils/status'
import type { JobStatus, JobSummary, Runtime } from '@/types'

/**
 * KPI kartasining drill-down paneli.
 *
 * ## Nega kerak
 *
 * "Jobs Today: 1 284" raqamining o'zi savol tug'diradi: qaysilari? qaysi
 * runtime'da? qaysi soatda? Drill-down shu savollarga javob beradi va
 * foydalanuvchini kerakli filtrga olib boradi — raqamdan harakatgacha
 * bir necha bosish.
 *
 * Har bir KPI uchun taqsimot boshqacha, shuning uchun `kind` bo'yicha
 * mazmun almashadi.
 */
export type KpiKind = 'jobs' | 'success' | 'latency' | 'dlq'

const TITLES: Record<KpiKind, { title: string; description: string }> = {
  jobs: { title: 'Jobs', description: "How today's jobs break down" },
  success: { title: 'Success rate', description: 'Success versus failure' },
  latency: { title: 'Latency', description: 'Execution duration distribution' },
  dlq: { title: 'Dead letter queue', description: 'Unresolved entries' },
}

export function KpiDrilldown({
  kind,
  onOpenChange,
}: {
  kind: KpiKind | null
  onOpenChange: (open: boolean) => void
}) {
  const router = useRouter()
  // Drill-down uchun kengroq namuna — faqat panel ochiq bo'lganda
  const query = useJobs(
    { page: 1, page_size: 200, sort_by: 'created_at', sort_order: 'desc' },
    { autoRefresh: false },
  )
  const rows = query.data?.items ?? []

  const meta = kind ? TITLES[kind] : null

  const byStatus = countBy(rows, (j) => j.status)
  const byRuntime = countBy(rows, (j) => j.runtime)
  const byHour = hourHistogram(rows)
  const durations = rows.map((j) => j.duration_ms).filter((d): d is number => d !== null)

  const statusPoints: DrilldownPoint[] = [...byStatus.entries()].map(([status, count]) => ({
    label: jobStatusStyle(status as JobStatus).label,
    value: count,
    key: status,
    tone:
      status === 'success'
        ? 'success'
        : status === 'failed' || status === 'dead_letter'
          ? 'failed'
          : status === 'running'
            ? 'running'
            : 'accent',
  }))

  const runtimePoints: DrilldownPoint[] = [...byRuntime.entries()].map(([runtime, count]) => ({
    label: runtimeStyle(runtime as Runtime).label,
    value: count,
    key: runtime,
    tone: 'accent',
  }))

  return (
    <DetailDrawer
      open={kind !== null}
      onOpenChange={onOpenChange}
      width="lg"
      title={meta?.title ?? ''}
      description={meta?.description}
      loading={query.isLoading}
      error={query.error}
      onRetry={() => void query.refetch()}
      stats={
        kind === 'latency'
          ? [
              { label: 'p50', value: formatDuration(percentile(durations, 50)) },
              { label: 'p90', value: formatDuration(percentile(durations, 90)), tone: 'warn' },
              { label: 'p99', value: formatDuration(percentile(durations, 99)), tone: 'bad' },
              { label: 'Sample', value: formatNumber(durations.length) },
            ]
          : [
              { label: 'Total', value: formatNumber(rows.length) },
              {
                label: 'Succeeded',
                value: formatNumber(byStatus.get('success') ?? 0),
                tone: 'good',
              },
              {
                label: 'Failed',
                value: formatNumber((byStatus.get('failed') ?? 0) + (byStatus.get('dead_letter') ?? 0)),
                tone: 'bad',
              },
              {
                label: 'Rate',
                value: formatPercent(
                  rows.length ? ((byStatus.get('success') ?? 0) / rows.length) * 100 : 100,
                ),
              },
            ]
      }
      footer={
        <Button
          variant="primary"
          onClick={() => {
            onOpenChange(false)
            router.push(kind === 'dlq' ? '/dlq' : '/jobs')
          }}
        >
          {kind === 'dlq' ? 'Open DLQ' : 'All jobs'} →
        </Button>
      }
    >
      <DrilldownChart
        title="By status"
        description="Click a bar to open the filtered list"
        points={statusPoints}
        valueLabel="Jobs"
        height={180}
        onSelect={(point) => {
          onOpenChange(false)
          router.push(`/jobs?status=${point.key}`)
        }}
      />

      <DrilldownChart
        title="By hour"
        description="Last 24 hours — busiest times"
        points={byHour}
        valueLabel="Jobs"
        height={160}
        onSelect={() => {
          onOpenChange(false)
          router.push('/analytics')
        }}
      />

      <DrilldownChart
        title="By runtime"
        points={runtimePoints}
        valueLabel="Jobs"
        height={150}
        onSelect={(point) => {
          onOpenChange(false)
          router.push(`/jobs?runtime=${point.key}`)
        }}
      />

      <DrawerSection title="Summary">
        <DrawerRow label="Jobs in sample" value={formatNumber(rows.length)} />
        <DrawerRow
          label="Average duration"
          value={formatDuration(
            durations.length ? Math.round(durations.reduce((a, b) => a + b, 0) / durations.length) : null,
          )}
        />
        <DrawerRow label="Longest" value={formatDuration(durations.length ? Math.max(...durations) : null)} />
        <DrawerRow
          label="Retried"
          value={formatNumber(rows.filter((j) => j.attempts_used > 1).length)}
        />
      </DrawerSection>
    </DetailDrawer>
  )
}

/** Kalit bo'yicha sanoq. */
function countBy<T, K>(rows: T[], pick: (row: T) => K): Map<K, number> {
  const map = new Map<K, number>()
  for (const row of rows) {
    const key = pick(row)
    map.set(key, (map.get(key) ?? 0) + 1)
  }
  return map
}

/** Oxirgi 24 soat bo'yicha taqsimot. */
function hourHistogram(rows: JobSummary[]): DrilldownPoint[] {
  const buckets = new Map<number, number>()
  for (const row of rows) {
    const hour = new Date(row.created_at).getHours()
    buckets.set(hour, (buckets.get(hour) ?? 0) + 1)
  }
  return [...buckets.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([hour, count]) => ({
      label: `${String(hour).padStart(2, '0')}:00`,
      value: count,
      key: String(hour),
      tone: 'accent' as const,
    }))
}

/**
 * Persentil.
 *
 * Interpolatsiyasiz "nearest-rank" usuli — namuna kichik bo'lganda
 * interpolatsiya mavjud bo'lmagan qiymatlarni to'qib chiqaradi.
 */
function percentile(values: number[], p: number): number | null {
  if (values.length === 0) return null
  const sorted = [...values].sort((a, b) => a - b)
  const index = Math.min(sorted.length - 1, Math.ceil((p / 100) * sorted.length) - 1)
  return sorted[Math.max(0, index)] ?? null
}
