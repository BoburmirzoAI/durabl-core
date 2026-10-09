'use client'

import { useState } from 'react'

import { BackupPanel } from '@/components/admin/BackupPanel'
import { PlanEditorPanel } from '@/components/admin/PlanEditorPanel'
import { QueueConfigPanel } from '@/components/admin/QueueConfigPanel'
import { RateLimitsPanel } from '@/components/admin/RateLimitsPanel'
import { SandboxConfigPanel } from '@/components/admin/SandboxConfigPanel'
import { SecretsPanel } from '@/components/admin/SecretsPanel'
import { SystemControls } from '@/components/admin/SystemControls'
import { SystemHealth } from '@/components/admin/SystemHealth'
import { QueueDepthPanel } from '@/components/dashboard/QueueDepthPanel'
import { WorkerStatus } from '@/components/dashboard/WorkerStatus'
import { DlqDepthChart } from '@/components/analytics/DlqDepthChart'
import { SectionHeader } from '@/components/common/SectionHeader'
import { ErrorState } from '@/components/common/ErrorState'
import { Badge } from '@/components/ui/badge'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs } from '@/components/ui/tabs'
import { useAnalyticsOverview } from '@/lib/hooks/useAnalytics'
import { useQueueDepths, useSystemStatus, useWorkers } from '@/lib/hooks/useWorkers'
import { formatNumber } from '@/lib/utils/format'

type TabValue = 'health' | 'limits' | 'runtime' | 'secrets' | 'backups'

const TABS = [
  { value: 'health' as TabValue, label: 'Health' },
  { value: 'limits' as TabValue, label: 'Limits & plans' },
  { value: 'runtime' as TabValue, label: 'Runtime' },
  { value: 'secrets' as TabValue, label: 'Secrets' },
  { value: 'backups' as TabValue, label: 'Backups' },
]

/**
 * Admin — tizim holati va KONFIGURATSIYASI.
 *
 * ## Nega tablar
 *
 * Sahifa ikki xil ishni bajaradi: KUZATISH ("nima buzildi?") va
 * SOZLASH ("qanday ishlashini o'zgartirish"). Ularni bitta uzun
 * ro'yxatga qo'ysa, hodisa paytida kerakli grafikni topish uchun
 * sozlamalar oralab aylantirish kerak bo'ladi.
 *
 * Shuning uchun `Health` birinchi va standart: hodisa paytida sahifa
 * ochilganda darhol kerakli narsa ko'rinadi.
 */
export default function AdminSystemPage() {
  const [tab, setTab] = useState<TabValue>('health')
  const system = useSystemStatus()
  const workers = useWorkers()
  const queues = useQueueDepths()
  const analytics = useAnalyticsOverview('7d')

  const leases = (workers.data ?? []).filter((w) => w.current_job_id !== null)

  return (
    <>
      <SectionHeader
        title="System"
        description="Health, limits, runtime configuration, secrets and backups"
        count={<Badge variant="danger">ADMIN</Badge>}
      />

      <Tabs aria-label="System sections" items={TABS} value={tab} onChange={setTab} />

      {tab === 'limits' ? (
        <>
          <RateLimitsPanel />
          <PlanEditorPanel />
        </>
      ) : null}

      {tab === 'runtime' ? (
        <>
          <SandboxConfigPanel />
          <QueueConfigPanel />
        </>
      ) : null}

      {tab === 'secrets' ? <SecretsPanel /> : null}
      {tab === 'backups' ? <BackupPanel /> : null}

      {tab !== 'health' ? null : (
        <>
      {/* Boshqaruv — sahifaning eng tepasida, chunki bu YAGONA amal qilish joyi */}
      <SystemControls />

      {system.error ? (
        <ErrorState error={system.error} onRetry={() => void system.refetch()} />
      ) : (
        <>
          <div className="grid items-start gap-4 xl:grid-cols-2">
            <SystemHealth status={system.data} loading={system.isLoading} />
            <QueueDepthPanel
              queues={queues.data}
              delayed={system.data?.delayed_jobs}
              loading={queues.isLoading}
            />
          </div>

          <DlqDepthChart
            data={analytics.data?.dlq_depth}
            loading={analytics.isLoading}
            error={analytics.error}
          />

          <div className="grid items-start gap-4 xl:grid-cols-2">
            <WorkerStatus workers={workers.data} loading={workers.isLoading} />

            <Card className="overflow-hidden">
              <CardHeader>
                <CardTitle className="text-md">Active leases</CardTitle>
                <span className="tabular ml-auto font-mono text-sm text-fg-muted">
                  {formatNumber(leases.length)}
                </span>
              </CardHeader>
              <div className="p-4">
                {leases.length === 0 ? (
                  <div className="py-6 text-center text-sm text-fg-faint">
                    No jobs are currently leased.
                  </div>
                ) : (
                  <div className="flex flex-col gap-2.5">
                    {leases.map((worker) => (
                      <div
                        key={worker.id}
                        className="flex items-center gap-3 border-b border-line-subtle pb-2.5 last:border-b-0 last:pb-0"
                      >
                        <span className="font-mono text-sm text-fg">{worker.id}</span>
                        <span className="font-mono text-xs text-fg-faint">{worker.region}</span>
                        <span className="ml-auto truncate font-mono text-sm text-fg-muted">
                          {worker.current_job_id}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
                <div className="mt-4 rounded-lg border border-line-inner bg-canvas-deep px-3.5 py-3 text-sm text-fg-faint">
                  Leases expire after{' '}
                  <span className="font-mono text-fg-muted">15s</span> without a heartbeat.
                  Expired leases are reaped by the scheduler and the job is re-queued — this is
                  what makes a worker crash survivable.
                </div>
              </div>
            </Card>
          </div>
        </>
      )}
        </>
      )}
    </>
  )
}
