'use client'

import { useState } from 'react'

import { ActivityFeed } from '@/components/admin/ActivityFeed'
import { WorkerDetailSheet } from '@/components/admin/WorkerDetailSheet'
import { WorkerFleetTable } from '@/components/admin/WorkerFleetTable'
import { QueueDepthPanel } from '@/components/dashboard/QueueDepthPanel'
import { SectionHeader } from '@/components/common/SectionHeader'
import { StatCard } from '@/components/analytics/KpiCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ErrorState } from '@/components/common/ErrorState'
import { useActivityFeed } from '@/lib/hooks/useAdmin'
import { useAddWorker, useQueueDepths, useSystemStatus, useWorkers } from '@/lib/hooks/useWorkers'
import { formatNumber } from '@/lib/utils/format'
import type { StatCardData, Worker } from '@/types'

/**
 * Admin — worker fleet.
 *
 * Bu sahifa "lease/heartbeat" mexanizmini ko'rinadigan qiladi: o'lgan
 * worker darhol qizil bo'lib ajralib turadi va uning job'lari qayta
 * taqsimlanganini navbat chuqurligidan ko'rish mumkin.
 */
export default function AdminWorkersPage() {
  const [detail, setDetail] = useState<Worker | null>(null)
  const addWorker = useAddWorker()

  const workers = useWorkers()
  const queues = useQueueDepths()
  const system = useSystemStatus()
  const activity = useActivityFeed()

  const online = (workers.data ?? []).filter((w) => w.state !== 'dead')
  const dead = (workers.data ?? []).filter((w) => w.state === 'dead')
  const activeJobs = online.reduce((sum, w) => sum + w.active_jobs, 0)
  const capacity = online.reduce((sum, w) => sum + w.concurrency, 0)
  const processed = (workers.data ?? []).reduce((sum, w) => sum + w.jobs_processed, 0)

  const cards: StatCardData[] = workers.data
    ? [
        {
          label: 'Workers online',
          value: `${online.length}/${workers.data.length}`,
          trend: dead.length > 0 ? `${dead.length} dead` : 'all healthy',
          trend_direction: dead.length > 0 ? 'down' : 'flat',
          trend_is_good: dead.length === 0,
          sub: 'heartbeat within 30s',
          is_alert: dead.length > 0,
        },
        {
          label: 'Slots in use',
          value: `${activeJobs}/${capacity}`,
          trend: capacity ? `${Math.round((activeJobs / capacity) * 100)}%` : '0%',
          trend_direction: 'up',
          trend_is_good: true,
          sub: 'concurrency utilisation',
        },
        {
          label: 'Jobs processed',
          value: formatNumber(processed),
          trend: 'lifetime',
          trend_direction: 'flat',
          trend_is_good: true,
          sub: 'across the fleet',
        },
        {
          label: 'Delayed jobs',
          value: formatNumber(system.data?.delayed_jobs ?? 0),
          trend: `${system.data?.dlq_depth ?? 0} in DLQ`,
          trend_direction: 'up',
          trend_is_good: (system.data?.dlq_depth ?? 0) === 0,
          sub: 'scheduled or retrying',
        },
      ]
    : []

  return (
    <>
      <SectionHeader
        title="Workers"
        description="Lease and heartbeat state for every worker process"
        count={<Badge variant="danger">ADMIN</Badge>}
        actions={
          <Button
            variant="primary"
            onClick={() => addWorker.mutate()}
            disabled={addWorker.isPending}
          >
            {addWorker.isPending ? 'Starting…' : '+ Add worker'}
          </Button>
        }
      />

      {workers.error ? (
        <ErrorState error={workers.error} onRetry={() => void workers.refetch()} />
      ) : (
        <>
          <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
            {workers.data
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

          {dead.length > 0 ? (
            <div className="flex flex-wrap items-center gap-3 rounded-xl border border-failed/20 bg-failed/[0.07] px-4 py-3">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-failed" aria-hidden>
                <path d="M12 3 2 20h20zM12 10v4M12 17h.01" />
              </svg>
              <span className="text-base text-failed-text">
                <span className="font-semibold text-failed-bright">
                  {dead.length} {dead.length === 1 ? 'worker is' : 'workers are'} not sending
                  heartbeats.
                </span>{' '}
                Their leases expire after 15s and the jobs are automatically re-queued.
              </span>
            </div>
          ) : null}

          <WorkerFleetTable
            workers={workers.data}
            loading={workers.isLoading}
            onOpenDetail={setDetail}
          />

          <div className="grid items-start gap-4 xl:grid-cols-2">
            <QueueDepthPanel
              queues={queues.data}
              delayed={system.data?.delayed_jobs}
              loading={queues.isLoading}
            />
            <ActivityFeed events={activity.data} loading={activity.isLoading} />
          </div>
        </>
      )}

      <WorkerDetailSheet
        worker={detail}
        onOpenChange={(open) => {
          if (!open) setDetail(null)
        }}
      />
    </>
  )
}
