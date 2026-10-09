'use client'

import { useState } from 'react'

import { useRouter } from 'next/navigation'

import { ActivityFeed } from '@/components/admin/ActivityFeed'
import { SystemHealth } from '@/components/admin/SystemHealth'
import { WorkerFleetTable } from '@/components/admin/WorkerFleetTable'
import { QueueDepthPanel } from '@/components/dashboard/QueueDepthPanel'
import { StatCard } from '@/components/analytics/KpiCard'
import { ThroughputChart } from '@/components/analytics/ThroughputChart'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { SectionHeader } from '@/components/common/SectionHeader'
import { Button } from '@/components/ui/button'
import { useClearDlq, useSetQueuePause, useSystemControls } from '@/lib/hooks/useWorkers'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { useActivityFeed, useAdminStats } from '@/lib/hooks/useAdmin'
import { useThroughput } from '@/lib/hooks/useAnalytics'
import { useQueueDepths, useSystemStatus, useWorkers } from '@/lib/hooks/useWorkers'
import { formatCurrency, formatDuration, formatNumber, formatPercent, humanize } from '@/lib/utils/format'
import { jobStatusStyle } from '@/lib/utils/status'
import type { JobStatus, StatCardData } from '@/types'

/**
 * Admin bosh sahifasi — butun platforma kesimi.
 *
 * Dizaynda yo'q; mijoz dashboard'ining AYNI uslubida qurilgan, lekin
 * ko'rsatkichlar platforma darajasida (foydalanuvchilar, MRR, fleet).
 */
export default function AdminOverviewPage() {
  const router = useRouter()
  const stats = useAdminStats()
  const throughput = useThroughput('24h')
  const workers = useWorkers()
  const queues = useQueueDepths()
  const system = useSystemStatus()
  const activity = useActivityFeed()
  const controls = useSystemControls()
  const queuePause = useSetQueuePause()
  const clearDlq = useClearDlq()
  const [danger, setDanger] = useState<'pause-queue' | 'resume-queue' | 'clear-dlq' | null>(null)

  const cards: StatCardData[] = stats.data
    ? [
        {
          label: 'Total users',
          value: formatNumber(stats.data.total_users),
          trend: `+${stats.data.new_users_7d}`,
          trend_direction: 'up',
          trend_is_good: true,
          sub: 'new in 7 days',
        },
        {
          label: 'Jobs (24h)',
          value: formatNumber(stats.data.jobs_24h),
          trend: formatPercent(stats.data.success_rate),
          trend_direction: 'up',
          trend_is_good: stats.data.success_rate >= 99,
          sub: 'success rate',
        },
        {
          label: 'DLQ depth',
          value: formatNumber(stats.data.dlq_depth),
          trend: `${stats.data.active_workers} workers`,
          trend_direction: 'up',
          trend_is_good: false,
          sub: stats.data.dlq_depth > 0 ? 'needs attention' : 'all clear',
          is_alert: stats.data.dlq_depth > 0,
        },
        {
          label: 'MRR',
          value: formatCurrency(stats.data.mrr_usd),
          trend: `${stats.data.active_users} active`,
          trend_direction: 'up',
          trend_is_good: true,
          sub: 'paying + free',
        },
      ]
    : []

  return (
    <>
      <SectionHeader
        title="Platform overview"
        description="Every user, job and worker across the Durabl deployment"
        count={<Badge variant="danger">ADMIN</Badge>}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={queuePause.isPending || !controls.data}
              onClick={() =>
                setDanger(controls.data?.queue_paused ? 'resume-queue' : 'pause-queue')
              }
            >
              {controls.data?.queue_paused ? 'Resume queue' : 'Pause queue'}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => router.push('/admin/workers')}
            >
              Manage workers
            </Button>
            <Button
              variant="danger"
              size="sm"
              disabled={clearDlq.isPending}
              onClick={() => setDanger('clear-dlq')}
            >
              {clearDlq.isPending ? 'Clearing…' : 'Clear DLQ'}
            </Button>
          </div>
        }
      />

      {controls.data?.maintenance_mode ? (
        <div className="flex items-center gap-2.5 rounded-xl border border-failed/25 bg-failed/[0.07] px-4 py-3">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-failed" aria-hidden>
            <path d="M12 3 2 20h20zM12 10v4M12 17h.01" />
          </svg>
          <span className="text-base text-failed-text">
            <span className="font-semibold text-failed-bright">Maintenance mode is on.</span>{' '}
            New job submissions are being rejected.
          </span>
        </div>
      ) : null}
      {controls.data?.queue_paused ? (
        <div className="flex items-center gap-2.5 rounded-xl border border-pending/25 bg-pending/[0.07] px-4 py-3">
          <svg width="17" height="17" viewBox="0 0 24 24" fill="currentColor" className="shrink-0 text-pending" aria-hidden>
            <rect x="6" y="5" width="4" height="14" rx="1" />
            <rect x="14" y="5" width="4" height="14" rx="1" />
          </svg>
          <span className="text-base text-fg-soft">
            <span className="font-semibold text-fg">Queue is paused.</span> Workers finish current
            jobs but claim no new ones.
          </span>
        </div>
      ) : null}

      <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
        {stats.data
          ? cards.map((card) => (
              <StatCard
                key={card.label}
                data={card}
                onClick={card.label === 'DLQ depth' ? () => router.push('/dlq') : undefined}
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
        title="Platform throughput"
        description="All users · last 24h"
        data={throughput.data}
        loading={throughput.isLoading}
        error={throughput.error}
        onRetry={() => void throughput.refetch()}
      />

      <WorkerFleetTable workers={workers.data} loading={workers.isLoading} />

      <div className="grid items-start gap-4 xl:grid-cols-3">
        <SystemHealth status={system.data} loading={system.isLoading} />
        <QueueDepthPanel
          queues={queues.data}
          delayed={system.data?.delayed_jobs}
          loading={queues.isLoading}
        />
        <ActivityFeed events={activity.data} loading={activity.isLoading} streaming />
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle className="text-md">Jobs by status</CardTitle>
            {stats.data ? (
              <span className="tabular ml-auto font-mono text-sm text-fg-muted">
                avg {formatDuration(stats.data.avg_duration_ms)}
              </span>
            ) : null}
          </CardHeader>
          <div className="flex flex-col gap-3 p-4">
            {stats.data
              ? Object.entries(stats.data.jobs_by_status)
                  .sort((a, b) => b[1] - a[1])
                  .map(([status, count]) => {
                    const style = jobStatusStyle(status as JobStatus)
                    const total = Object.values(stats.data.jobs_by_status).reduce(
                      (sum, v) => sum + v,
                      0,
                    )
                    return (
                      <div key={status} className="flex items-center gap-3">
                        <span className="w-24 shrink-0 text-sm text-fg-soft">{style.label}</span>
                        <Progress
                          value={total ? (count / total) * 100 : 0}
                          size="xs"
                          barClassName={style.dot}
                          aria-label={`${style.label}: ${count}`}
                        />
                        <span className="tabular w-12 shrink-0 text-right font-mono text-sm text-fg-muted">
                          {formatNumber(count)}
                        </span>
                      </div>
                    )
                  })
              : <Skeleton className="h-32 w-full" />}
          </div>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle className="text-md">Users by plan</CardTitle>
          </CardHeader>
          <div className="flex flex-col gap-3 p-4">
            {stats.data ? (
              Object.entries(stats.data.users_by_plan)
                .sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))
                .map(([plan, count]) => (
                  <div key={plan} className="flex items-center gap-3">
                    <span className="w-24 shrink-0 text-sm text-fg-soft">{humanize(plan)}</span>
                    <Progress
                      value={stats.data.total_users ? ((count ?? 0) / stats.data.total_users) * 100 : 0}
                      size="xs"
                      barClassName="bg-accent"
                      aria-label={`${plan}: ${count}`}
                    />
                    <span className="tabular w-12 shrink-0 text-right font-mono text-sm text-fg-muted">
                      {formatNumber(count ?? 0)}
                    </span>
                  </div>
                ))
            ) : (
              <Skeleton className="h-32 w-full" />
            )}
          </div>
        </Card>
      </div>

      <ConfirmDialog
        open={danger !== null}
        onOpenChange={(open) => {
          if (!open) setDanger(null)
        }}
        title={
          danger === 'clear-dlq'
            ? 'Clear the dead letter queue?'
            : danger === 'pause-queue'
              ? 'Pause the queue?'
              : 'Resume the queue?'
        }
        description={
          danger === 'clear-dlq'
            ? 'Every dead letter entry is deleted permanently. Those jobs can no longer be inspected or retried. This cannot be undone.'
            : danger === 'pause-queue'
              ? 'Workers finish what they are running but stop claiming new jobs. The queue keeps growing while paused.'
              : 'Workers start claiming queued jobs again.'
        }
        confirmLabel={
          danger === 'clear-dlq' ? 'Delete all' : danger === 'pause-queue' ? 'Pause' : 'Resume'
        }
        destructive
        pending={queuePause.isPending || clearDlq.isPending}
        onConfirm={() => {
          if (danger === 'clear-dlq') clearDlq.mutate()
          else if (danger === 'pause-queue') queuePause.mutate(true)
          else if (danger === 'resume-queue') queuePause.mutate(false)
          setDanger(null)
        }}
      />
    </>
  )
}
