'use client'

import { Button } from '@/components/ui/button'
import { Progress } from '@/components/ui/progress'
import { RelativeTime } from '@/components/common/RelativeTime'
import { Sheet, SheetBody, SheetContent, SheetFooter, SheetHeader } from '@/components/ui/sheet'
import { StatusBadge } from '@/components/common/StatusBadge'
import { cn } from '@/lib/utils/cn'
import { formatNumber, formatUptime } from '@/lib/utils/format'
import { cpuColorClass, workerStateStyle } from '@/lib/utils/status'
import { useDrainWorker, useRestartWorker, useResumeWorker } from '@/lib/hooks/useWorkers'
import type { Worker } from '@/types'

/** Worker tafsiloti — joriy yuk, resurslar va boshqaruv tugmalari. */
export function WorkerDetailSheet({
  worker,
  onOpenChange,
}: {
  worker: Worker | null
  onOpenChange: (open: boolean) => void
}) {
  const drain = useDrainWorker()
  const resume = useResumeWorker()
  const restart = useRestartWorker()

  const memoryPercent = worker ? (worker.memory_mb / worker.memory_limit_mb) * 100 : 0

  return (
    <Sheet open={worker !== null} onOpenChange={onOpenChange}>
      <SheetContent aria-describedby={undefined}>
        <SheetHeader
          title={<span className="font-mono">{worker?.id ?? ''}</span>}
          description={worker ? `${worker.region} · v${worker.version}` : undefined}
          actions={worker ? <StatusBadge style={workerStateStyle(worker.state)} /> : null}
        />

        <SheetBody>
          {worker ? (
            <>
              <div className="rounded-xl border border-line bg-surface p-4">
                <div className="text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">
                  Resources
                </div>
                <div className="mt-3.5 space-y-3.5">
                  <Meter
                    label="CPU"
                    value={`${worker.cpu}%`}
                    percent={worker.cpu}
                    barClassName={cpuColorClass(worker.cpu)}
                  />
                  <Meter
                    label="Memory"
                    value={`${worker.memory_mb}M / ${worker.memory_limit_mb}M`}
                    percent={memoryPercent}
                    barClassName={cpuColorClass(memoryPercent)}
                  />
                  <Meter
                    label="Slots"
                    value={`${worker.active_jobs} / ${worker.concurrency}`}
                    percent={(worker.active_jobs / worker.concurrency) * 100}
                    barClassName="bg-accent"
                  />
                </div>
              </div>

              <div className="rounded-xl border border-line bg-surface p-4">
                <div className="text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">
                  Lease & heartbeat
                </div>
                <div className="mt-3 space-y-2.5">
                  <Row
                    label="Last heartbeat"
                    value={<RelativeTime value={worker.last_heartbeat_at} refreshMs={2_000} />}
                  />
                  <Row label="Uptime" value={worker.state === 'dead' ? '—' : formatUptime(worker.uptime_seconds)} />
                  <Row
                    label="Current job"
                    value={
                      worker.current_job_id ? (
                        <span className="font-mono text-xs">{worker.current_job_id}</span>
                      ) : (
                        <span className="text-fg-faint">idle</span>
                      )
                    }
                  />
                  <Row label="Jobs processed" value={formatNumber(worker.jobs_processed)} />
                </div>
              </div>

              {worker.state === 'draining' ? (
                <div className="rounded-lg border border-pending/25 bg-pending/[0.07] px-3.5 py-2.5 text-sm text-fg-soft">
                  Draining — finishing {worker.active_jobs} job(s), accepting no new work.
                </div>
              ) : null}
              {worker.state === 'dead' ? (
                <div className="rounded-lg border border-failed/25 bg-failed/[0.07] px-3.5 py-2.5 text-sm text-failed-text">
                  No heartbeat. Its lease expired and the jobs were re-queued elsewhere.
                </div>
              ) : null}
            </>
          ) : null}
        </SheetBody>

        <SheetFooter>
          {worker?.state === 'draining' ? (
            <Button variant="secondary" onClick={() => worker && resume.mutate(worker.id)}>
              Resume
            </Button>
          ) : (
            <Button
              variant="secondary"
              disabled={!worker || worker.state === 'dead'}
              onClick={() => worker && drain.mutate(worker.id)}
            >
              Drain
            </Button>
          )}
          <Button
            variant="danger"
            disabled={!worker || restart.isPending}
            onClick={() => worker && restart.mutate(worker.id)}
          >
            {restart.isPending ? 'Restarting…' : 'Restart'}
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}

function Meter({
  label,
  value,
  percent,
  barClassName,
}: {
  label: string
  value: string
  percent: number
  barClassName: string
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between text-sm">
        <span className="text-fg-dim">{label}</span>
        <span className="tabular font-mono text-fg-soft">{value}</span>
      </div>
      <Progress value={percent} size="sm" barClassName={barClassName} className="mt-1.5" aria-label={label} />
    </div>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="shrink-0 text-sm text-fg-dim">{label}</span>
      <span className={cn('min-w-0 truncate text-right text-sm text-fg-soft')}>{value}</span>
    </div>
  )
}
