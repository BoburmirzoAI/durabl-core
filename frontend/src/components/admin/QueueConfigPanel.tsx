'use client'

import { useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs } from '@/components/ui/tabs'
import { useQueueConfig, useUpdateQueueConfig } from '@/lib/hooks/usePlatform'
import { cn } from '@/lib/utils/cn'
import type { QueueConfig } from '@/types'

const BACKOFF_TABS = [
  { value: 'fixed' as const, label: 'Fixed' },
  { value: 'linear' as const, label: 'Linear' },
  { value: 'exponential' as const, label: 'Exponential' },
]

/**
 * Navbat va lease konfiguratsiyasi.
 *
 * ═══════════════════════════════════════════════════════════════════
 * ENG MUHIM MUNOSABAT
 * ═══════════════════════════════════════════════════════════════════
 *
 *     lease_ttl  ≥  2 × heartbeat_interval
 *
 * Durabl'ning "job yo'qolmaydi" va'dasi aynan shunga tayanadi: worker
 * `heartbeat_interval` da bir marta lease'ni uzaytiradi. Agar TTL
 * oraliqqa teng bo'lsa, bitta sekinroq tarmoq paketi job'ni "o'lgan"
 * deb belgilaydi va u BOSHQA worker'ga beriladi — ya'ni ikki marta
 * bajariladi.
 *
 * Shuning uchun bu panel munosabatni GRAFIK ko'rinishda ham ko'rsatadi
 * va buzilganda saqlashga yo'l qo'ymaydi.
 */
export function QueueConfigPanel() {
  const query = useQueueConfig()
  const update = useUpdateQueueConfig()
  const [draft, setDraft] = useState<QueueConfig | null>(null)

  useEffect(() => {
    if (query.data) setDraft(query.data)
  }, [query.data])

  const problems = useMemo(() => {
    if (!draft) return []
    const list: string[] = []
    if (draft.heartbeat_interval_seconds >= draft.lease_ttl_seconds) {
      list.push(
        'The heartbeat interval must be shorter than the lease TTL, otherwise even a healthy worker loses its lease.',
      )
    } else if (draft.heartbeat_interval_seconds * 2 > draft.lease_ttl_seconds) {
      list.push(
        'The lease TTL should be at least twice the heartbeat interval. With less headroom, a single missed heartbeat hands the job to another worker — and it runs twice.',
      )
    }
    if (draft.reaper_interval_seconds > draft.lease_ttl_seconds) {
      list.push(
        'The reaper runs less often than leases expire, so a dead worker’s jobs sit idle longer than they need to.',
      )
    }
    if (draft.retry_base_delay_seconds > draft.retry_max_delay_seconds) {
      list.push('The base retry delay is larger than the maximum delay.')
    }
    return list
  }, [draft])

  if (!draft) {
    return (
      <Card className="p-4">
        <Skeleton className="h-56 w-full" />
      </Card>
    )
  }

  const dirty = JSON.stringify(draft) !== JSON.stringify(query.data)
  const blocked = problems.length > 0
  const set = <K extends keyof QueueConfig>(key: K, value: QueueConfig[K]): void =>
    setDraft((current) => (current ? { ...current, [key]: value } : current))

  // Munosabatni ko'rsatadigan sodda chiziq
  const ratio = draft.lease_ttl_seconds / Math.max(1, draft.heartbeat_interval_seconds)

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">Queue &amp; leases</CardTitle>
        <CardDescription>
          These values are the mechanism behind “a job is never lost and never runs twice”.
        </CardDescription>
      </CardHeader>

      <div className="border-b border-line-inner px-4 py-3.5">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="text-sm text-fg-dim">Safety margin</span>
          <span
            className={cn(
              'tabular font-mono text-lg',
              ratio >= 2 ? 'text-success' : ratio > 1 ? 'text-pending' : 'text-failed',
            )}
          >
            {ratio.toFixed(1)}×
          </span>
          <span className="text-xs text-fg-faint">
            lease TTL ÷ heartbeat interval — a worker may miss {Math.max(0, Math.floor(ratio) - 1)}{' '}
            heartbeat{Math.max(0, Math.floor(ratio) - 1) === 1 ? '' : 's'} before losing its jobs
          </span>
        </div>
        <div className="mt-2.5 flex h-2 overflow-hidden rounded-full bg-line">
          {Array.from({ length: Math.max(1, Math.min(8, Math.round(ratio))) }, (_, i) => (
            <span
              key={i}
              className={cn(
                'h-full flex-1 border-r border-canvas last:border-r-0',
                ratio >= 2 ? 'bg-success' : ratio > 1 ? 'bg-pending' : 'bg-failed',
              )}
            />
          ))}
        </div>
      </div>

      {problems.length > 0 ? (
        <div className="space-y-2 px-4 pt-3">
          {problems.map((problem) => (
            <div
              key={problem}
              className="rounded-lg border border-failed/25 bg-failed/[0.07] px-3.5 py-2.5 text-sm leading-[1.55] text-failed-text"
            >
              {problem}
            </div>
          ))}
        </div>
      ) : null}

      <div className="divide-y divide-line-subtle">
        <Slider
          label="Lease TTL"
          hint="How long a worker owns a job before the lease expires."
          value={draft.lease_ttl_seconds}
          min={5}
          max={120}
          step={1}
          suffix="s"
          onChange={(value) => set('lease_ttl_seconds', value)}
        />
        <Slider
          label="Heartbeat interval"
          hint="How often a healthy worker renews its leases."
          value={draft.heartbeat_interval_seconds}
          min={1}
          max={60}
          step={1}
          suffix="s"
          onChange={(value) => set('heartbeat_interval_seconds', value)}
        />
        <Slider
          label="Reaper interval"
          hint="How often expired leases are swept back into the queue."
          value={draft.reaper_interval_seconds}
          min={1}
          max={60}
          step={1}
          suffix="s"
          onChange={(value) => set('reaper_interval_seconds', value)}
        />
        <Slider
          label="Prefetch per worker"
          hint="More prefetch means better throughput but slower rebalancing."
          value={draft.prefetch_count}
          min={1}
          max={16}
          step={1}
          onChange={(value) => set('prefetch_count', value)}
        />
        <Slider
          label="Default max retries"
          hint="After this many failures a job moves to the dead letter queue."
          value={draft.default_max_retries}
          min={0}
          max={10}
          step={1}
          onChange={(value) => set('default_max_retries', value)}
        />
        <div className="flex flex-wrap items-center gap-4 px-4 py-3">
          <div className="min-w-[200px] flex-1">
            <div className="text-base text-fg-soft">Retry backoff</div>
            <div className="mt-0.5 text-sm leading-[1.5] text-fg-faint">
              Exponential is the safe default — it stops a failing dependency from being hammered.
            </div>
          </div>
          <Tabs
            aria-label="Retry backoff"
            items={BACKOFF_TABS}
            value={draft.retry_backoff}
            onChange={(value) => set('retry_backoff', value)}
          />
        </div>
        <Slider
          label="Base retry delay"
          value={draft.retry_base_delay_seconds}
          min={1}
          max={120}
          step={1}
          suffix="s"
          onChange={(value) => set('retry_base_delay_seconds', value)}
        />
        <Slider
          label="Max retry delay"
          value={draft.retry_max_delay_seconds}
          min={10}
          max={3_600}
          step={10}
          suffix="s"
          onChange={(value) => set('retry_max_delay_seconds', value)}
        />
        <Slider
          label="DLQ alert threshold"
          hint="An alert fires when the dead letter queue grows past this."
          value={draft.dlq_alert_threshold}
          min={1}
          max={500}
          step={1}
          onChange={(value) => set('dlq_alert_threshold', value)}
        />
      </div>

      <div className="flex items-center gap-2 border-t border-line-inner px-4 py-3">
        <span className="min-w-0 flex-1 text-sm text-fg-faint">
          {blocked
            ? 'Fix the problems above before saving.'
            : dirty
              ? 'Unsaved changes.'
              : 'Queue configuration is up to date.'}
        </span>
        {dirty ? (
          <Button variant="ghost" onClick={() => setDraft(query.data ?? draft)}>
            Reset
          </Button>
        ) : null}
        <Button
          variant="primary"
          disabled={!dirty || blocked || update.isPending}
          onClick={() => update.mutate(draft)}
        >
          {update.isPending ? 'Saving…' : 'Save queue config'}
        </Button>
      </div>
    </Card>
  )
}

function Slider({
  label,
  hint,
  value,
  min,
  max,
  step,
  suffix = '',
  onChange,
}: {
  label: string
  hint?: string
  value: number
  min: number
  max: number
  step: number
  suffix?: string
  onChange: (value: number) => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-4 px-4 py-3">
      <div className="min-w-[200px] flex-1">
        <div className="text-base text-fg-soft">{label}</div>
        {hint ? <div className="mt-0.5 text-sm leading-[1.5] text-fg-faint">{hint}</div> : null}
      </div>
      <span className="tabular w-[72px] shrink-0 text-right font-mono text-sm text-fg">
        {value}
        {suffix}
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        aria-label={label}
        className="h-1.5 w-[220px] shrink-0 cursor-pointer appearance-none rounded-full bg-line accent-[hsl(var(--accent))]"
      />
    </div>
  )
}
