'use client'

import { useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Tabs } from '@/components/ui/tabs'
import { useApiDefaults, useUpdateApiDefaults } from '@/lib/hooks/useAccount'
import type { ApiDefaults } from '@/types'

/**
 * Job yuborishdagi standart qiymatlar.
 *
 * ## Nega sozlamalar sahifasida
 *
 * Bu qiymatlar SDK chaqiruvida har safar yozilmasa ishlatiladi. Ularni
 * bitta joyda belgilash — har bir `client.submit(...)` da `timeout=300,
 * memory=512, retries=3` takrorlashdan ko'ra ishonchliroq.
 *
 * O'zgarish "Save" bosilgandan keyin kuchga kiradi: timeout yoki xotirani
 * tasodifan o'zgartirib qo'yish ishlab turgan job'larni buzishi mumkin.
 */
const BACKOFF_TABS = [
  { value: 'fixed' as const, label: 'Fixed' },
  { value: 'linear' as const, label: 'Linear' },
  { value: 'exponential' as const, label: 'Exponential' },
]

const RUNTIME_TABS = [
  { value: 'python' as const, label: 'Python' },
  { value: 'node' as const, label: 'Node' },
]

const PRIORITY_TABS = [
  { value: 'low' as const, label: 'Low' },
  { value: 'normal' as const, label: 'Normal' },
  { value: 'high' as const, label: 'High' },
]

export function ApiDefaultsPanel() {
  const query = useApiDefaults()
  const update = useUpdateApiDefaults()
  const [draft, setDraft] = useState<ApiDefaults | null>(null)

  // Server qiymati kelganda yoki saqlangandan keyin qoralama yangilanadi
  useEffect(() => {
    if (query.data) setDraft(query.data)
  }, [query.data])

  const dirty = useMemo(
    () => Boolean(draft && query.data && JSON.stringify(draft) !== JSON.stringify(query.data)),
    [draft, query.data],
  )

  if (!draft) {
    return (
      <Card className="p-4">
        <Skeleton className="h-48 w-full" />
      </Card>
    )
  }

  const set = <K extends keyof ApiDefaults>(key: K, value: ApiDefaults[K]): void =>
    setDraft((current) => (current ? { ...current, [key]: value } : current))

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">Job defaults</CardTitle>
        <CardDescription>
          Applied when a submission does not set the field. Equivalent to the arguments you would
          pass to <code className="font-mono text-fg-muted">client.submit(...)</code>.
        </CardDescription>
      </CardHeader>

      <div className="divide-y divide-line-subtle">
        <Row label="Runtime" hint="Which sandbox image runs the code.">
          <Tabs
            aria-label="Default runtime"
            items={RUNTIME_TABS}
            value={draft.runtime}
            onChange={(value) => set('runtime', value)}
          />
        </Row>

        <Row label="Priority" hint="Higher priority jobs are leased first when the queue backs up.">
          <Tabs
            aria-label="Default priority"
            items={PRIORITY_TABS}
            value={draft.priority}
            onChange={(value) => set('priority', value)}
          />
        </Row>

        <Row
          label="Timeout"
          hint="A job past this is killed and counted as a timeout failure."
          value={`${draft.timeout_seconds}s`}
        >
          <input
            type="range"
            min={10}
            max={900}
            step={10}
            value={draft.timeout_seconds}
            onChange={(event) => set('timeout_seconds', Number(event.target.value))}
            aria-label="Default timeout in seconds"
            className="h-1.5 w-[220px] cursor-pointer appearance-none rounded-full bg-line accent-[hsl(var(--accent))]"
          />
        </Row>

        <Row
          label="Memory"
          hint="The sandbox is killed with an OOM failure above this."
          value={`${draft.memory_mb} MB`}
        >
          <input
            type="range"
            min={128}
            max={4_096}
            step={128}
            value={draft.memory_mb}
            onChange={(event) => set('memory_mb', Number(event.target.value))}
            aria-label="Default memory in megabytes"
            className="h-1.5 w-[220px] cursor-pointer appearance-none rounded-full bg-line accent-[hsl(var(--accent))]"
          />
        </Row>

        <Row
          label="Max retries"
          hint="After this many failures the job moves to the dead letter queue."
          value={String(draft.max_retries)}
        >
          <input
            type="range"
            min={0}
            max={10}
            step={1}
            value={draft.max_retries}
            onChange={(event) => set('max_retries', Number(event.target.value))}
            aria-label="Default maximum retries"
            className="h-1.5 w-[220px] cursor-pointer appearance-none rounded-full bg-line accent-[hsl(var(--accent))]"
          />
        </Row>

        <Row label="Retry backoff" hint="How long to wait between attempts.">
          <Tabs
            aria-label="Retry backoff"
            items={BACKOFF_TABS}
            value={draft.retry_backoff}
            onChange={(value) => set('retry_backoff', value)}
          />
        </Row>

        <Row
          label="Automatic idempotency"
          hint="Hash the payload into an idempotency key when the caller does not send one."
        >
          <Switch
            checked={draft.auto_idempotency}
            onCheckedChange={(value) => set('auto_idempotency', value)}
            aria-label="Automatic idempotency"
          />
        </Row>
      </div>

      <div className="flex items-center gap-2 border-t border-line-inner px-4 py-3">
        <span className="min-w-0 flex-1 text-sm text-fg-faint">
          {dirty ? 'Unsaved changes.' : 'Defaults are up to date.'}
        </span>
        {dirty ? (
          <Button variant="ghost" onClick={() => setDraft(query.data ?? draft)}>
            Reset
          </Button>
        ) : null}
        <Button
          variant="primary"
          disabled={!dirty || update.isPending}
          onClick={() => update.mutate(draft)}
        >
          {update.isPending ? 'Saving…' : 'Save defaults'}
        </Button>
      </div>
    </Card>
  )
}

function Row({
  label,
  hint,
  value,
  children,
}: {
  label: string
  hint: string
  value?: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-wrap items-center gap-4 px-4 py-3.5">
      <div className="min-w-[200px] flex-1">
        <div className="text-base text-fg-soft">{label}</div>
        <div className="mt-0.5 text-sm leading-[1.5] text-fg-faint">{hint}</div>
      </div>
      {value ? (
        <span className="tabular w-[72px] shrink-0 text-right font-mono text-sm text-fg">
          {value}
        </span>
      ) : null}
      <div className="shrink-0">{children}</div>
    </div>
  )
}
