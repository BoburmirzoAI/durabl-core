'use client'

import { useEffect, useState } from 'react'

import { CodeEditor } from '@/components/common/CodeEditor'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Tabs } from '@/components/ui/tabs'
import { useCreateSchedule, useUpdateSchedule } from '@/lib/hooks/useSchedules'
import type { Priority, Runtime, Schedule } from '@/types'

import { CronBuilder } from './CronBuilder'

const RUNTIME_TABS = [
  { value: 'python' as Runtime, label: 'Python' },
  { value: 'node' as Runtime, label: 'Node' },
]

const PRIORITY_TABS = [
  { value: 'low' as Priority, label: 'Low' },
  { value: 'normal' as Priority, label: 'Normal' },
  { value: 'high' as Priority, label: 'High' },
]

const STARTER_CODE: Record<Runtime, string> = {
  python: `def main(payload):
    """Runs on the schedule you configure above."""
    return {"ok": True}
`,
  node: `export default async function main(payload) {
  // Runs on the schedule you configure above
  return { ok: true }
}
`,
}

/**
 * Jadval yaratish/tahrirlash.
 *
 * ## Nega kod faqat YARATISHDA so'raladi
 *
 * Tahrirlashda kod maydoni ko'rsatilmaydi: jadvalning kodi — bu aslida
 * job tanasi, va uni o'zgartirish keyingi barcha ishga tushishlarni
 * o'zgartiradi. Bu alohida, ataylab qilinadigan amal bo'lishi kerak,
 * tasodifan "nomni tahrirlayotganda" emas.
 */
export function ScheduleFormDialog({
  open,
  schedule,
  onOpenChange,
}: {
  open: boolean
  /** `null` — yangi jadval. */
  schedule: Schedule | null
  onOpenChange: (open: boolean) => void
}) {
  const create = useCreateSchedule()
  const update = useUpdateSchedule()
  const editing = schedule !== null

  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [cron, setCron] = useState('0 2 * * *')
  const [runtime, setRuntime] = useState<Runtime>('python')
  const [priority, setPriority] = useState<Priority>('normal')
  const [allowOverlap, setAllowOverlap] = useState(false)
  const [timeout, setTimeoutSeconds] = useState(300)
  const [maxRetries, setMaxRetries] = useState(3)
  const [code, setCode] = useState(STARTER_CODE.python)

  // Dialog ochilganda maydonlar tanlangan jadvaldan to'ldiriladi
  useEffect(() => {
    if (!open) return
    if (schedule) {
      setName(schedule.name)
      setDescription(schedule.description ?? '')
      setCron(schedule.cron)
      setRuntime(schedule.runtime)
      setPriority(schedule.priority)
      setAllowOverlap(schedule.allow_overlap)
      setTimeoutSeconds(schedule.timeout_seconds)
      setMaxRetries(schedule.max_retries)
    } else {
      setName('')
      setDescription('')
      setCron('0 2 * * *')
      setRuntime('python')
      setPriority('normal')
      setAllowOverlap(false)
      setTimeoutSeconds(300)
      setMaxRetries(3)
      setCode(STARTER_CODE.python)
    }
  }, [open, schedule])

  const pending = create.isPending || update.isPending
  const canSubmit = name.trim().length > 0 && cron.trim().length > 0 && !pending

  function submit(): void {
    if (editing && schedule) {
      update.mutate(
        {
          id: schedule.id,
          patch: {
            name,
            description: description.trim() || null,
            cron,
            priority,
            allow_overlap: allowOverlap,
            timeout_seconds: timeout,
            max_retries: maxRetries,
          },
        },
        { onSuccess: () => onOpenChange(false) },
      )
      return
    }
    create.mutate(
      {
        name,
        description,
        cron,
        timezone: 'UTC',
        code,
        runtime,
        priority,
        allow_overlap: allowOverlap,
        timeout_seconds: timeout,
        max_retries: maxRetries,
      },
      { onSuccess: () => onOpenChange(false) },
    )
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent width="lg">
        <DialogHeader>
          <div className="min-w-0">
            <DialogTitle>{editing ? 'Edit schedule' : 'New schedule'}</DialogTitle>
            <DialogDescription>
              {editing
                ? 'The code is not editable here — changing it affects every future run.'
                : 'Runs a job on a cron. Every run counts against your monthly quota.'}
            </DialogDescription>
          </div>
        </DialogHeader>

        <DialogBody className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                Name
              </span>
              <Input
                autoFocus
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Nightly warehouse sync"
              />
            </label>
            <label className="block">
              <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                Description
              </span>
              <Input
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="What this job does"
              />
            </label>
          </div>

          <CronBuilder value={cron} onChange={setCron} />

          <div className="grid gap-3 sm:grid-cols-2">
            {!editing ? (
              <Field label="Runtime">
                <Tabs
                  aria-label="Runtime"
                  items={RUNTIME_TABS}
                  value={runtime}
                  onChange={(value) => {
                    setRuntime(value)
                    setCode(STARTER_CODE[value])
                  }}
                />
              </Field>
            ) : null}
            <Field label="Priority">
              <Tabs
                aria-label="Priority"
                items={PRIORITY_TABS}
                value={priority}
                onChange={setPriority}
              />
            </Field>
            <Field label={`Timeout — ${timeout}s`}>
              <input
                type="range"
                min={30}
                max={900}
                step={30}
                value={timeout}
                onChange={(event) => setTimeoutSeconds(Number(event.target.value))}
                aria-label="Timeout in seconds"
                className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-line accent-[hsl(var(--accent))]"
              />
            </Field>
            <Field label={`Max retries — ${maxRetries}`}>
              <input
                type="range"
                min={0}
                max={10}
                step={1}
                value={maxRetries}
                onChange={(event) => setMaxRetries(Number(event.target.value))}
                aria-label="Maximum retries"
                className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-line accent-[hsl(var(--accent))]"
              />
            </Field>
          </div>

          <div className="flex items-start justify-between gap-6 rounded-lg border border-line-inner bg-canvas-deep px-3.5 py-3">
            <div className="min-w-0">
              <div className="text-base text-fg-soft">Allow overlapping runs</div>
              <div className="mt-0.5 text-sm leading-[1.5] text-fg-faint">
                Off is safer: if a run is still going when the next one is due, the new one is
                skipped instead of piling up.
              </div>
            </div>
            <Switch
              checked={allowOverlap}
              onCheckedChange={setAllowOverlap}
              aria-label="Allow overlapping runs"
            />
          </div>

          {!editing ? (
            <CodeEditor value={code} onChange={setCode} runtime={runtime} minRows={12} />
          ) : null}
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" size="md" disabled={!canSubmit} onClick={submit}>
            {pending ? 'Saving…' : editing ? 'Save changes' : 'Create schedule'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
        {label}
      </span>
      {children}
    </div>
  )
}
