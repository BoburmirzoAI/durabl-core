'use client'

import { Badge } from '@/components/ui/badge'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/common/EmptyState'
import { Progress } from '@/components/ui/progress'
import { RelativeTime } from '@/components/common/RelativeTime'
import { Skeleton } from '@/components/ui/skeleton'
import { StatusDot } from '@/components/common/StatusDot'
import { cn } from '@/lib/utils/cn'
import { cpuColorClass, cpuTextClass, workerStateStyle } from '@/lib/utils/status'
import type { Worker } from '@/types'

/**
 * Worker holati paneli — dizayndagi o'ng panel.
 *
 * Har bir worker: jonli nuqta + ID + region + job soni, pastda CPU
 * progress bar. Sarlavhada tizim sog'ligi nishoni.
 *
 * O'lgan worker (`dead`) qizil nuqta oladi va "System healthy" nishoni
 * "Degraded" ga o'zgaradi — yolg'on "hammasi joyida" ko'rsatmaymiz.
 */
export function WorkerStatus({
  workers,
  loading = false,
}: {
  workers: Worker[] | undefined
  loading?: boolean
}) {
  const hasDead = (workers ?? []).some((w) => w.state === 'dead')
  const healthy = workers !== undefined && !hasDead

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>Worker Status</CardTitle>
        {workers ? (
          <Badge
            size="md"
            className={cn(
              'ml-auto rounded-full px-2.5 py-[3px]',
              healthy ? 'bg-success/[0.12] text-success' : 'bg-pending/[0.12] text-pending',
            )}
          >
            <StatusDot
              className={healthy ? 'bg-success' : 'bg-pending'}
              pulseToken={healthy ? 'success' : 'pending'}
              live
            />
            {healthy ? 'System healthy' : 'Degraded'}
          </Badge>
        ) : null}
      </CardHeader>

      <div className="px-4 pb-2 pt-1">
        {loading && !workers ? (
          Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="border-b border-line-subtle py-3">
              <Skeleton className="h-3 w-40" />
              <Skeleton className="mt-2.5 h-[5px] w-full" />
            </div>
          ))
        ) : !workers || workers.length === 0 ? (
          <EmptyState
            icon="M4 5h16v6H4zM4 13h16v6H4zM8 8h.01M8 16h.01"
            title="No workers online"
            description="Start a worker process to begin consuming jobs."
          />
        ) : (
          workers.map((worker) => {
            const state = workerStateStyle(worker.state)
            const isDead = worker.state === 'dead'
            return (
              <div key={worker.id} className="border-b border-line-subtle py-3 last:border-b-0">
                <div className="flex items-center gap-[9px]">
                  <StatusDot
                    className={state.dot}
                    pulseToken={state.pulseToken}
                    live={state.live}
                  />
                  <span className="font-mono text-sm font-medium text-fg">{worker.id}</span>
                  <span className="font-mono text-xs text-fg-faint">{worker.region}</span>
                  <span className="ml-auto text-xs text-fg-dim">
                    {isDead ? (
                      <span className="text-failed">
                        no heartbeat · <RelativeTime value={worker.last_heartbeat_at} />
                      </span>
                    ) : (
                      <>
                        <span className="tabular font-mono font-medium text-fg-muted">
                          {worker.active_jobs}
                        </span>{' '}
                        jobs
                      </>
                    )}
                  </span>
                </div>
                <div className="mt-[9px] flex items-center gap-[9px]">
                  <span className="w-7 shrink-0 text-2xs font-semibold tracking-[.05em] text-fg-faint">
                    CPU
                  </span>
                  <Progress
                    value={worker.cpu}
                    size="xs"
                    barClassName={cpuColorClass(worker.cpu)}
                    aria-label={`${worker.id} CPU ${worker.cpu}%`}
                  />
                  <span
                    className={cn(
                      'tabular w-[34px] shrink-0 text-right font-mono text-xs',
                      cpuTextClass(worker.cpu),
                    )}
                  >
                    {worker.cpu}%
                  </span>
                </div>
              </div>
            )
          })
        )}
      </div>
    </Card>
  )
}
