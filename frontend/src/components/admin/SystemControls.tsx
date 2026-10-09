'use client'

import { useState } from 'react'

import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { Skeleton } from '@/components/ui/skeleton'
import {
  useClearDlq,
  useFlushCache,
  useRebuildIndex,
  useRestartSubsystem,
  useSetFeatureFlag,
  useSetMaintenance,
  useSetQueuePause,
  useSystemControls,
} from '@/lib/hooks/useWorkers'
import { cn } from '@/lib/utils/cn'

type Danger =
  | { kind: 'maintenance'; enable: boolean }
  | { kind: 'queue'; pause: boolean }
  | { kind: 'restart'; subsystem: 'database' | 'redis' | 'sandbox' }
  | { kind: 'flush' }
  | { kind: 'reindex' }
  | { kind: 'clear-dlq' }
  | { kind: 'flag'; key: string; label: string; enable: boolean }

/**
 * Tizim boshqaruvi — texnik xizmat, kesh va funksiya bayroqlari.
 *
 * HAR BIR amal tasdiqlash so'raydi. Bu yerdagi tugmalar butun platformaga
 * ta'sir qiladi (masalan navbatni to'xtatish — hamma mijozning job'lari
 * kutib qoladi), shuning uchun tasodifiy bosish qimmatga tushadi.
 */
export function SystemControls() {
  const controls = useSystemControls()
  const [danger, setDanger] = useState<Danger | null>(null)

  const maintenance = useSetMaintenance()
  const queuePause = useSetQueuePause()
  const restart = useRestartSubsystem()
  const flush = useFlushCache()
  const reindex = useRebuildIndex()
  const clearDlq = useClearDlq()
  const setFlag = useSetFeatureFlag()

  const data = controls.data
  const pending =
    maintenance.isPending ||
    queuePause.isPending ||
    restart.isPending ||
    flush.isPending ||
    reindex.isPending ||
    clearDlq.isPending

  const run = (action: Danger): void => {
    switch (action.kind) {
      case 'maintenance':
        maintenance.mutate(action.enable)
        break
      case 'queue':
        queuePause.mutate(action.pause)
        break
      case 'restart':
        restart.mutate(action.subsystem)
        break
      case 'flush':
        flush.mutate()
        break
      case 'reindex':
        reindex.mutate()
        break
      case 'clear-dlq':
        clearDlq.mutate()
        break
      case 'flag':
        setFlag.mutate({ key: action.key, enabled: action.enable })
        break
    }
  }

  return (
    <>
      <div className="grid gap-4 xl:grid-cols-2">
        {/* ---- Platforma rejimi ---- */}
        <Card className="overflow-hidden">
          <div className="border-b border-line-inner px-4 py-[15px]">
            <div className="text-md font-semibold text-fg">Platform mode</div>
            <span className="text-xs text-fg-dim">Affects every tenant immediately</span>
          </div>

          <div className="divide-y divide-line-subtle">
            {controls.isLoading || !data ? (
              <div className="p-4">
                <Skeleton className="h-20 w-full" />
              </div>
            ) : (
              <>
                <ToggleRow
                  label="Maintenance mode"
                  description="Reject new job submissions with 503. Running jobs finish."
                  checked={data.maintenance_mode}
                  danger
                  onToggle={(enable) => setDanger({ kind: 'maintenance', enable })}
                />
                <ToggleRow
                  label="Pause queue"
                  description="Workers finish current jobs but take no new ones."
                  checked={data.queue_paused}
                  danger
                  onToggle={(pause) => setDanger({ kind: 'queue', pause })}
                />
              </>
            )}
          </div>
        </Card>

        {/* ---- Texnik amallar ---- */}
        <Card className="overflow-hidden">
          <div className="border-b border-line-inner px-4 py-[15px]">
            <div className="text-md font-semibold text-fg">Maintenance actions</div>
            <span className="text-xs text-fg-dim">One-off operations</span>
          </div>

          <div className="grid gap-2.5 p-4 sm:grid-cols-2">
            <Button variant="secondary" disabled={pending} onClick={() => setDanger({ kind: 'flush' })}>
              {flush.isPending ? 'Flushing…' : 'Flush Redis cache'}
            </Button>
            <Button variant="secondary" disabled={pending} onClick={() => setDanger({ kind: 'reindex' })}>
              {reindex.isPending ? 'Rebuilding…' : 'Rebuild search index'}
            </Button>
            <Button variant="danger" disabled={pending} onClick={() => setDanger({ kind: 'clear-dlq' })}>
              {clearDlq.isPending ? 'Clearing…' : 'Clear DLQ'}
            </Button>
          </div>

          <div className="border-t border-line-inner px-4 py-3">
            <div className="text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">
              Restart subsystem
            </div>
            <div className="mt-2.5 flex flex-wrap gap-2">
              {(['database', 'redis', 'sandbox'] as const).map((subsystem) => (
                <Button
                  key={subsystem}
                  variant="outline"
                  size="sm"
                  disabled={pending}
                  onClick={() => setDanger({ kind: 'restart', subsystem })}
                >
                  {subsystem}
                </Button>
              ))}
            </div>
          </div>
        </Card>
      </div>

      {/* ---- Funksiya bayroqlari ---- */}
      <Card className="overflow-hidden">
        <div className="border-b border-line-inner px-4 py-[15px]">
          <div className="text-md font-semibold text-fg">Feature flags</div>
          <span className="text-xs text-fg-dim">Runtime switches — no deploy needed</span>
        </div>

        <div className="divide-y divide-line-subtle">
          {controls.isLoading || !data ? (
            <div className="p-4">
              <Skeleton className="h-32 w-full" />
            </div>
          ) : (
            data.flags.map((flag) => (
              <ToggleRow
                key={flag.key}
                label={flag.label}
                description={flag.description}
                checked={flag.enabled}
                danger={flag.risky}
                onToggle={(enable) =>
                  flag.risky
                    ? setDanger({ kind: 'flag', key: flag.key, label: flag.label, enable })
                    : setFlag.mutate({ key: flag.key, enabled: enable })
                }
              />
            ))
          )}
        </div>
      </Card>

      <ConfirmDialog
        open={danger !== null}
        onOpenChange={(open) => {
          if (!open) setDanger(null)
        }}
        title={titleFor(danger)}
        description={descriptionFor(danger)}
        confirmLabel={confirmLabelFor(danger)}
        destructive
        pending={pending}
        onConfirm={() => {
          if (!danger) return
          run(danger)
          setDanger(null)
        }}
      />
    </>
  )
}

function ToggleRow({
  label,
  description,
  checked,
  danger = false,
  onToggle,
}: {
  label: string
  description: string
  checked: boolean
  danger?: boolean
  onToggle: (next: boolean) => void
}) {
  return (
    <div className="flex items-start gap-3 px-4 py-3.5">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-base text-fg-soft">{label}</span>
          {checked && danger ? (
            <span className="rounded-full bg-failed/[0.14] px-1.5 py-px text-2xs font-semibold text-failed">
              on
            </span>
          ) : null}
        </div>
        <p className={cn('mt-0.5 text-sm text-fg-dim')}>{description}</p>
      </div>
      <Switch checked={checked} onCheckedChange={onToggle} aria-label={label} />
    </div>
  )
}

function titleFor(danger: Danger | null): string {
  if (!danger) return ''
  switch (danger.kind) {
    case 'maintenance':
      return danger.enable ? 'Enable maintenance mode?' : 'Disable maintenance mode?'
    case 'queue':
      return danger.pause ? 'Pause the queue?' : 'Resume the queue?'
    case 'restart':
      return `Restart ${danger.subsystem}?`
    case 'flush':
      return 'Flush the Redis cache?'
    case 'reindex':
      return 'Rebuild the search index?'
    case 'clear-dlq':
      return 'Clear the dead letter queue?'
    case 'flag':
      return `${danger.enable ? 'Enable' : 'Disable'} ${danger.label}?`
  }
}

function descriptionFor(danger: Danger | null): string {
  if (!danger) return ''
  switch (danger.kind) {
    case 'maintenance':
      return danger.enable
        ? 'Every new job submission is rejected with 503 until you turn this off. Running jobs are allowed to finish.'
        : 'Job submissions are accepted again.'
    case 'queue':
      return danger.pause
        ? 'Workers finish what they are running but stop claiming new jobs. The queue keeps growing while paused.'
        : 'Workers start claiming queued jobs again.'
    case 'restart':
      return `The ${danger.subsystem} subsystem is restarted. In-flight operations against it fail and are retried.`
    case 'flush':
      return 'All cached keys are removed. Idempotency records and rate-limit counters are rebuilt from the database — expect a short latency spike.'
    case 'reindex':
      return 'The search index is rebuilt from scratch. Search results are incomplete until it finishes.'
    case 'clear-dlq':
      return 'Every dead letter entry is deleted permanently. Jobs in the DLQ can no longer be inspected or retried. This cannot be undone.'
    case 'flag':
      return danger.key === 'gvisor_sandbox' && !danger.enable
        ? 'Job code will run WITHOUT gVisor isolation. Untrusted code would execute directly in the container. Only do this for debugging.'
        : 'This flag changes platform behaviour immediately for every tenant.'
  }
}

function confirmLabelFor(danger: Danger | null): string {
  if (!danger) return 'Confirm'
  switch (danger.kind) {
    case 'maintenance':
      return danger.enable ? 'Enable' : 'Disable'
    case 'queue':
      return danger.pause ? 'Pause' : 'Resume'
    case 'restart':
      return 'Restart'
    case 'flush':
      return 'Flush'
    case 'reindex':
      return 'Rebuild'
    case 'clear-dlq':
      return 'Delete all'
    case 'flag':
      return danger.enable ? 'Enable' : 'Disable'
  }
}
