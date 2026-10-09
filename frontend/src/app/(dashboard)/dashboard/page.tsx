'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { StatCard } from '@/components/analytics/KpiCard'
import { KpiDrilldown, type KpiKind } from '@/components/dashboard/KpiDrilldown'
import { ThroughputChart } from '@/components/analytics/ThroughputChart'
import { QueueDepthPanel } from '@/components/dashboard/QueueDepthPanel'
import { LiveJobFeed } from '@/components/dashboard/LiveJobFeed'
import { RecentJobs } from '@/components/dashboard/RecentJobs'
import { WorkerStatus } from '@/components/dashboard/WorkerStatus'
import { SectionHeader } from '@/components/common/SectionHeader'
import { Button } from '@/components/ui/button'
import { KbdHint } from '@/components/common/KbdHint'
import { Tabs } from '@/components/ui/tabs'
import { JobSubmitDialog } from '@/components/jobs/JobSubmitDialog'
import { SHORTCUTS } from '@/lib/constants/shortcuts'
import { useDashboard } from '@/lib/hooks/useAnalytics'
import { useJobs } from '@/lib/hooks/useJobs'
import { useShortcut } from '@/lib/hooks/useKeyboard'
import { useQueueDepths, useSystemStatus, useWorkers } from '@/lib/hooks/useWorkers'
import type { TimeRange } from '@/types'

const RANGE_TABS = [
  { value: '24h' as TimeRange, label: '24h' },
  { value: '7d' as TimeRange, label: '7d' },
  { value: '30d' as TimeRange, label: '30d' },
] as const

/**
 * Dashboard — dizayndagi bosh sahifa.
 *
 * Tuzilma: sarlavha + oraliq tablari + "New Job" / 4 statistika kartasi /
 * throughput grafigi / oxirgi job'lar + worker holati.
 */
export default function DashboardPage() {
  const router = useRouter()
  const [range, setRange] = useState<TimeRange>('24h')
  const [submitOpen, setSubmitOpen] = useState(false)
  const [drilldown, setDrilldown] = useState<KpiKind | null>(null)

  const dashboard = useDashboard(range)
  const recent = useJobs({ page: 1, page_size: 8, sort_by: 'created_at', sort_order: 'desc' })

  // Jonli tasma uchun kengroq oyna: holat o'zgarishini ilg'ab olish uchun
  // faqat 8 ta eng yangi job yetarli emas — simulyatsiya ro'yxatning
  // istalgan joyidagi job'ni harakatlantiradi.
  const live = useJobs(
    { page: 1, page_size: 60, sort_by: 'created_at', sort_order: 'desc' },
    { autoRefresh: true },
  )
  const workers = useWorkers()
  const queues = useQueueDepths()
  const system = useSystemStatus()

  useShortcut(SHORTCUTS.newJob, () => setSubmitOpen(true))
  useShortcut(SHORTCUTS.goJobs, () => router.push('/jobs'))

  return (
    <>
      <SectionHeader
        title="Dashboard"
        actions={
          <>
            <Tabs
              aria-label="Time range"
              items={RANGE_TABS}
              value={range}
              onChange={setRange}
            />
            <Button variant="primary" size="md" onClick={() => setSubmitOpen(true)}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden>
                <path d="M12 5v14M5 12h14" />
              </svg>
              New Job
              <KbdHint className="border-white/20 bg-white/[0.18] text-white">⌘N</KbdHint>
            </Button>
          </>
        }
      />

      <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
        {dashboard.data
          ? dashboard.data.stats.map((stat) => (
              <StatCard
                key={stat.label}
                data={stat}
                // HAR BIR karta drill-down ochadi — ilgari faqat DLQ bosilardi
                onClick={() => setDrilldown(kpiKindFor(stat.label))}
              />
            ))
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
        data={dashboard.data?.throughput}
        loading={dashboard.isLoading}
        error={dashboard.error}
        onRetry={() => void dashboard.refetch()}
        description={`Jobs processed per minute · last ${range}`}
      />

      {/* Operatsion qator: holat o'zgarishlari oqimi + fleet sog'ligi */}
      <div className="grid items-start gap-4 xl:grid-cols-2">
        <LiveJobFeed jobs={live.data?.items} loading={live.isLoading} />
        <div className="flex flex-col gap-4">
          <WorkerStatus workers={workers.data} loading={workers.isLoading} />
          <QueueDepthPanel
            queues={queues.data}
            delayed={system.data?.delayed_jobs}
            loading={queues.isLoading}
          />
        </div>
      </div>

      <RecentJobs jobs={recent.data?.items} loading={recent.isLoading} />

      <JobSubmitDialog open={submitOpen} onOpenChange={setSubmitOpen} />

      <KpiDrilldown
        kind={drilldown}
        onOpenChange={(open) => {
          if (!open) setDrilldown(null)
        }}
      />
    </>
  )
}

/**
 * KPI yorlig'idan drill-down turini aniqlaydi.
 *
 * Yorliqlar `mock/analytics.dashboardStats()` da belgilangan; mos kelmasa
 * umumiy "jobs" ko'rinishi ochiladi — panel baribir foydali bo'ladi.
 */
function kpiKindFor(label: string): KpiKind {
  const key = label.toLowerCase()
  if (key.includes('dlq') || key.includes('dead')) return 'dlq'
  if (key.includes('success') || key.includes('rate')) return 'success'
  if (key.includes('latency') || key.includes('duration') || key.includes('p9')) return 'latency'
  return 'jobs'
}
