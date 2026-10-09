'use client'

import { useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Tabs } from '@/components/ui/tabs'
import { useSandboxConfig, useUpdateSandboxConfig } from '@/lib/hooks/usePlatform'
import { formatBytes } from '@/lib/utils/format'
import type { SandboxConfig } from '@/types'

/**
 * Sandbox konfiguratsiyasi.
 *
 * ## Nega bu sahifaning eng xavfli qismi
 *
 * Bu yerdagi har bir sozlama mijozning IXTIYORIY KODI ishlaydigan
 * muhitni belgilaydi. `read_only_rootfs` ni o'chirish yoki `run_as_uid`
 * ni 0 ga qo'yish — sandbox'dan chiqish yo'lini ochadi.
 *
 * Shuning uchun xavfli qiymatlar DARHOL ogohlantirish beradi, va
 * `runc` + tarmoq birikmasini backend butunlay rad etadi.
 */
const RUNTIME_TABS = [
  { value: 'runsc' as const, label: 'gVisor (runsc)' },
  { value: 'runc' as const, label: 'runc' },
]

export function SandboxConfigPanel() {
  const query = useSandboxConfig()
  const update = useUpdateSandboxConfig()
  const [draft, setDraft] = useState<SandboxConfig | null>(null)

  useEffect(() => {
    if (query.data) setDraft(query.data)
  }, [query.data])

  const warnings = useMemo(() => {
    if (!draft) return []
    const list: string[] = []
    if (draft.runtime === 'runc') {
      list.push(
        'runc shares the host kernel. A kernel exploit in customer code reaches the host. gVisor intercepts syscalls in userspace and is the safer default.',
      )
    }
    if (draft.allow_network) {
      list.push(
        'Outbound network lets customer code reach your internal services and exfiltrate data. Keep it off unless a plan explicitly needs it.',
      )
    }
    if (!draft.read_only_rootfs) {
      list.push(
        'A writable root filesystem lets code modify the image at runtime, which makes an execution impossible to reproduce.',
      )
    }
    if (draft.run_as_uid === 0) {
      list.push('UID 0 means customer code runs as root inside the sandbox. Use a high UID.')
    }
    return list
  }, [draft])

  if (!draft) {
    return (
      <Card className="p-4">
        <Skeleton className="h-64 w-full" />
      </Card>
    )
  }

  const dirty = JSON.stringify(draft) !== JSON.stringify(query.data)
  const set = <K extends keyof SandboxConfig>(key: K, value: SandboxConfig[K]): void =>
    setDraft((current) => (current ? { ...current, [key]: value } : current))

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">Sandbox</CardTitle>
        <CardDescription>
          The environment every customer job runs inside. Changes apply to jobs started from now on.
        </CardDescription>
      </CardHeader>

      {warnings.length > 0 ? (
        <div className="space-y-2 px-4 pb-1">
          {warnings.map((warning) => (
            <div
              key={warning}
              className="rounded-lg border border-pending/25 bg-pending/[0.07] px-3.5 py-2.5 text-sm leading-[1.55] text-pending"
            >
              {warning}
            </div>
          ))}
        </div>
      ) : null}

      <div className="divide-y divide-line-subtle">
        <Row
          label="Isolation runtime"
          hint="gVisor runs a userspace kernel between the job and the host."
        >
          <Tabs
            aria-label="Isolation runtime"
            items={RUNTIME_TABS}
            value={draft.runtime}
            onChange={(value) => set('runtime', value)}
          />
        </Row>

        <Row label="Default timeout" hint="Capped by the plan limit." value={`${draft.default_timeout_seconds}s`}>
          <input
            type="range"
            min={10}
            max={900}
            step={10}
            value={draft.default_timeout_seconds}
            onChange={(event) => set('default_timeout_seconds', Number(event.target.value))}
            aria-label="Default timeout"
            className="h-1.5 w-[220px] cursor-pointer appearance-none rounded-full bg-line accent-[hsl(var(--accent))]"
          />
        </Row>

        <Row label="Default memory" hint="Exceeding this kills the sandbox with an OOM failure." value={`${draft.default_memory_mb} MB`}>
          <input
            type="range"
            min={128}
            max={4_096}
            step={128}
            value={draft.default_memory_mb}
            onChange={(event) => set('default_memory_mb', Number(event.target.value))}
            aria-label="Default memory"
            className="h-1.5 w-[220px] cursor-pointer appearance-none rounded-full bg-line accent-[hsl(var(--accent))]"
          />
        </Row>

        <Row label="Default CPUs" value={String(draft.default_cpus)}>
          <input
            type="range"
            min={1}
            max={8}
            step={1}
            value={draft.default_cpus}
            onChange={(event) => set('default_cpus', Number(event.target.value))}
            aria-label="Default CPUs"
            className="h-1.5 w-[220px] cursor-pointer appearance-none rounded-full bg-line accent-[hsl(var(--accent))]"
          />
        </Row>

        <Row label="Outbound network" hint="Off means the sandbox has no route out at all.">
          <Switch
            checked={draft.allow_network}
            onCheckedChange={(value) => set('allow_network', value)}
            aria-label="Outbound network"
          />
        </Row>

        <Row label="Read-only root filesystem" hint="Only /tmp stays writable.">
          <Switch
            checked={draft.read_only_rootfs}
            onCheckedChange={(value) => set('read_only_rootfs', value)}
            aria-label="Read-only root filesystem"
          />
        </Row>

        <Row label="Run as UID" hint="A non-root, high UID with no matching host user.">
          <Input
            value={String(draft.run_as_uid)}
            inputMode="numeric"
            aria-label="Run as UID"
            onChange={(event) => set('run_as_uid', Number(event.target.value.replace(/\D/g, '') || 0))}
            className="tabular h-8 w-[110px] text-right font-mono text-xs"
          />
        </Row>

        <Row label="Python image">
          <Input
            value={draft.python_image}
            aria-label="Python sandbox image"
            onChange={(event) => set('python_image', event.target.value)}
            className="h-8 w-[260px] font-mono text-xs"
          />
        </Row>

        <Row label="Node image">
          <Input
            value={draft.node_image}
            aria-label="Node sandbox image"
            onChange={(event) => set('node_image', event.target.value)}
            className="h-8 w-[260px] font-mono text-xs"
          />
        </Row>

        <Row
          label="Max output size"
          hint="Larger results fail with output_too_large instead of filling the database."
          value={formatBytes(draft.max_output_bytes)}
        >
          <input
            type="range"
            min={65_536}
            max={16_777_216}
            step={65_536}
            value={draft.max_output_bytes}
            onChange={(event) => set('max_output_bytes', Number(event.target.value))}
            aria-label="Max output size"
            className="h-1.5 w-[220px] cursor-pointer appearance-none rounded-full bg-line accent-[hsl(var(--accent))]"
          />
        </Row>

        <Row
          label="Clean up after"
          hint="How long a finished container is kept for log collection."
          value={`${draft.cleanup_after_seconds}s`}
        >
          <input
            type="range"
            min={0}
            max={600}
            step={10}
            value={draft.cleanup_after_seconds}
            onChange={(event) => set('cleanup_after_seconds', Number(event.target.value))}
            aria-label="Clean up after"
            className="h-1.5 w-[220px] cursor-pointer appearance-none rounded-full bg-line accent-[hsl(var(--accent))]"
          />
        </Row>
      </div>

      <div className="flex items-center gap-2 border-t border-line-inner px-4 py-3">
        <span className="min-w-0 flex-1 text-sm text-fg-faint">
          {dirty ? 'Unsaved changes.' : 'Sandbox configuration is up to date.'}
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
          {update.isPending ? 'Saving…' : 'Save sandbox config'}
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
  hint?: string
  value?: string
  children: React.ReactNode
}) {
  return (
    <div className="flex flex-wrap items-center gap-4 px-4 py-3">
      <div className="min-w-[200px] flex-1">
        <div className="text-base text-fg-soft">{label}</div>
        {hint ? <div className="mt-0.5 text-sm leading-[1.5] text-fg-faint">{hint}</div> : null}
      </div>
      {value ? (
        <span className="tabular w-[92px] shrink-0 text-right font-mono text-sm text-fg">
          {value}
        </span>
      ) : null}
      <div className="shrink-0">{children}</div>
    </div>
  )
}
