'use client'

import { useState } from 'react'

import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { EmptyState } from '@/components/common/EmptyState'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { useDrainWorker, useRestartWorker, useResumeWorker } from '@/lib/hooks/useWorkers'
import { Progress } from '@/components/ui/progress'
import { RelativeTime } from '@/components/common/RelativeTime'
import { StatusBadge } from '@/components/common/StatusBadge'
import { SkeletonRows } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils/cn'
import { formatNumber, formatUptime } from '@/lib/utils/format'
import { cpuColorClass, cpuTextClass, workerStateStyle } from '@/lib/utils/status'
import type { Worker } from '@/types'

/** Worker fleet jadvali (admin) — CPU/xotira/heartbeat bilan. */
const GRID = '92px 110px 96px 70px minmax(110px,1fr) minmax(110px,1fr) 80px 96px 44px'

export function WorkerFleetTable({
  workers,
  loading = false,
  onOpenDetail,
}: {
  workers: Worker[] | undefined
  loading?: boolean
  onOpenDetail?: (worker: Worker) => void
}) {
  const drain = useDrainWorker()
  const resume = useResumeWorker()
  const restart = useRestartWorker()
  const [confirm, setConfirm] = useState<{ worker: Worker; action: 'restart' | 'drain' } | null>(
    null,
  )
  return (
    <>
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">Worker Fleet</CardTitle>
        {workers ? (
          <span className="ml-auto text-sm text-fg-dim">
            <span className="tabular font-mono text-fg-muted">
              {workers.filter((w) => w.state !== 'dead').length}
            </span>{' '}
            / {workers.length} online
          </span>
        ) : null}
      </CardHeader>

      <div className="overflow-x-auto">
        <div className="min-w-[940px]">
          <div className="table-head grid items-center px-3.5" style={{ gridTemplateColumns: GRID }}>
            <span>Worker</span>
            <span>Region</span>
            <span>State</span>
            <span>Jobs</span>
            <span>CPU</span>
            <span>Memory</span>
            <span className="text-right">Uptime</span>
            <span className="text-right">Heartbeat</span>
            <span className="sr-only">Actions</span>
          </div>

          {loading && !workers ? (
            <SkeletonRows rows={6} columns={GRID} />
          ) : !workers || workers.length === 0 ? (
            <EmptyState
              icon="M4 5h16v6H4zM4 13h16v6H4zM8 8h.01M8 16h.01"
              title="No workers registered"
              description="Start a worker pool to begin consuming the queue."
            />
          ) : (
            workers.map((worker) => {
              const state = workerStateStyle(worker.state)
              const isDead = worker.state === 'dead'
              const memoryPercent = (worker.memory_mb / worker.memory_limit_mb) * 100
              return (
                <div
                  key={worker.id}
                  className="grid h-12 items-center border-b border-line-subtle px-3.5 last:border-b-0 transition-colors hover:bg-surface-3"
                  style={{ gridTemplateColumns: GRID }}
                >
                  <span className="font-mono text-sm font-medium text-fg">{worker.id}</span>
                  <span className="font-mono text-sm text-fg-faint">{worker.region}</span>
                  <span>
                    <StatusBadge style={state} />
                  </span>
                  <span className="tabular font-mono text-sm text-fg-muted">
                    {worker.active_jobs}/{worker.concurrency}
                  </span>

                  <span className="flex items-center gap-2.5 pr-3">
                    <Progress
                      value={worker.cpu}
                      size="xs"
                      barClassName={cpuColorClass(worker.cpu)}
                      aria-label={`${worker.id} CPU`}
                    />
                    <span className={cn('tabular w-9 shrink-0 text-right font-mono text-xs', cpuTextClass(worker.cpu))}>
                      {worker.cpu}%
                    </span>
                  </span>

                  <span className="flex items-center gap-2.5 pr-3">
                    <Progress
                      value={memoryPercent}
                      size="xs"
                      barClassName={cpuColorClass(memoryPercent)}
                      aria-label={`${worker.id} memory`}
                    />
                    <span className="tabular w-16 shrink-0 text-right font-mono text-xs text-fg-faint">
                      {worker.memory_mb}M
                    </span>
                  </span>

                  <span className="tabular text-right font-mono text-sm text-fg-faint">
                    {isDead ? '—' : formatUptime(worker.uptime_seconds)}
                  </span>

                  <RelativeTime
                    value={worker.last_heartbeat_at}
                    refreshMs={5_000}
                    className={cn(
                      'tabular text-right font-mono text-sm',
                      isDead ? 'text-failed' : 'text-fg-faint',
                    )}
                  />
                
                  <span className="flex justify-end">
                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <button
                          type="button"
                          aria-label={`Actions for ${worker.id}`}
                          className="inline-flex h-[26px] w-[26px] items-center justify-center rounded-md text-fg-dim transition-colors hover:bg-line hover:text-fg"
                        >
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                            <circle cx="12" cy="5" r="1.6" />
                            <circle cx="12" cy="12" r="1.6" />
                            <circle cx="12" cy="19" r="1.6" />
                          </svg>
                        </button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent className="min-w-[170px]">
                        {onOpenDetail ? (
                          <DropdownMenuItem onSelect={() => onOpenDetail(worker)}>
                            View details
                          </DropdownMenuItem>
                        ) : null}
                        {worker.state === 'draining' ? (
                          <DropdownMenuItem onSelect={() => resume.mutate(worker.id)}>
                            Resume
                          </DropdownMenuItem>
                        ) : (
                          <DropdownMenuItem
                            disabled={isDead}
                            onSelect={() => setConfirm({ worker, action: 'drain' })}
                          >
                            Drain
                            {isDead ? (
                              <span className="ml-auto text-xs text-fg-faint">dead</span>
                            ) : null}
                          </DropdownMenuItem>
                        )}
                        <DropdownMenuItem
                          danger
                          onSelect={() => setConfirm({ worker, action: 'restart' })}
                        >
                          Restart
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </span>
</div>
              )
            })
          )}
        </div>
      </div>

      {workers ? (
        <div className="border-t border-line-inner px-3.5 py-2.5 text-xs text-fg-faint">
          Total processed:{' '}
          <span className="tabular font-mono text-fg-muted">
            {formatNumber(workers.reduce((sum, w) => sum + w.jobs_processed, 0))}
          </span>{' '}
          jobs
        </div>
      ) : null}
    </Card>

      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(open) => {
          if (!open) setConfirm(null)
        }}
        title={confirm?.action === 'restart' ? 'Restart worker?' : 'Drain worker?'}
        description={
          confirm
            ? confirm.action === 'restart'
              ? `${confirm.worker.id} is killed and restarted. Its ${confirm.worker.active_jobs} running job(s) lose their lease and are re-queued on another worker.`
              : `${confirm.worker.id} finishes its current jobs but stops accepting new ones. Running work is NOT interrupted.`
            : ''
        }
        confirmLabel={confirm?.action === 'restart' ? 'Restart' : 'Drain'}
        destructive={confirm?.action === 'restart'}
        pending={drain.isPending || restart.isPending}
        onConfirm={() => {
          if (!confirm) return
          if (confirm.action === 'restart') restart.mutate(confirm.worker.id)
          else drain.mutate(confirm.worker.id)
          setConfirm(null)
        }}
      />
    </>
  )
}
