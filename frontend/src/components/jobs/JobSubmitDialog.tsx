'use client'

import { useState } from 'react'

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
import { Input, Textarea } from '@/components/ui/input'
import { SingleSelect } from '@/components/ui/filter-select'
import { cn } from '@/lib/utils/cn'
import { useSubmitJob } from '@/lib/hooks/useJobs'
import type { JobCreateInput, Priority, Runtime } from '@/types'

/**
 * Yangi job yuborish dialogi (dizaynda yo'q — ayni uslubda qurilgan).
 *
 * Namuna kodlar KO'CHIRIB ISHLATISH UCHUN to'g'ri bo'lishi shart:
 * payload sandbox ichida `payload.json` fayli sifatida paydo bo'ladi
 * (backend `runtime_base.prepare_files` shunday yozadi), shuning uchun
 * namunalar aynan shu faylni o'qiydi — muhit o'zgaruvchisini emas.
 */
const RUNTIME_OPTIONS = [
  { value: 'python' as Runtime, label: 'Python 3.12' },
  { value: 'node' as Runtime, label: 'Node 22' },
] as const

const PRIORITY_OPTIONS = [
  { value: 'normal' as Priority, label: 'Normal' },
  { value: 'high' as Priority, label: 'High' },
  { value: 'low' as Priority, label: 'Low' },
] as const

interface Sample {
  label: string
  runtime: Runtime
  code: string
  payload?: string
}

const SAMPLES: readonly Sample[] = [
  {
    label: 'Hello world',
    runtime: 'python',
    code: "print('Hello from Durabl')\n",
  },
  {
    label: 'With payload',
    runtime: 'python',
    code: `import json
from pathlib import Path

# Payload sandbox ichida 'payload.json' fayli sifatida beriladi
payload = json.loads(Path("payload.json").read_text())

def main(n):
    print(f"doubling {n}")
    return n * 2
`,
    payload: '{\n  "args": [21]\n}',
  },
  {
    label: 'Raise an error',
    runtime: 'python',
    code: "raise RuntimeError('intentional failure for testing retries')\n",
  },
  {
    label: 'Long running',
    runtime: 'python',
    code: 'import time\n\ntime.sleep(45)  # timeout dan oshadi\nprint("never reached")\n',
  },
  {
    label: 'Node with payload',
    runtime: 'node',
    code: `const fs = require('fs')

// Payload sandbox ichida 'payload.json' fayli sifatida beriladi
const payload = JSON.parse(fs.readFileSync('payload.json', 'utf8'))

module.exports.main = (n) => {
  console.log('tripling', n)
  return n * 3
}
`,
    payload: '{\n  "args": [14]\n}',
  },
]

export function JobSubmitDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const submit = useSubmitJob()

  const [runtime, setRuntime] = useState<Runtime>('python')
  const [priority, setPriority] = useState<Priority>('normal')
  const [code, setCode] = useState(SAMPLES[0]?.code ?? '')
  const [payload, setPayload] = useState('')
  const [timeout, setTimeoutSeconds] = useState('30')
  const [retries, setRetries] = useState('3')
  const [tags, setTags] = useState('')
  const [idempotencyKey, setIdempotencyKey] = useState('')

  // Payload JSON xatosini DARHOL ko'rsatamiz (yuborishni kutmasdan)
  const payloadError = (() => {
    if (!payload.trim()) return null
    try {
      JSON.parse(payload)
      return null
    } catch (error) {
      return error instanceof Error ? error.message : 'Invalid JSON'
    }
  })()

  const canSubmit = code.trim().length > 0 && !payloadError && !submit.isPending

  const applySample = (sample: Sample): void => {
    setRuntime(sample.runtime)
    setCode(sample.code)
    setPayload(sample.payload ?? '')
  }

  const onSubmit = (): void => {
    const input: JobCreateInput = {
      code,
      runtime,
      priority,
      payload: payload.trim() ? (JSON.parse(payload) as Record<string, unknown>) : null,
      timeout_seconds: Number(timeout) || 30,
      max_retries: Number(retries) || 0,
      tags: tags
        .split(',')
        .map((t) => t.trim())
        .filter(Boolean),
      idempotency_key: idempotencyKey.trim() || null,
    }
    submit.mutate(input, {
      onSuccess: () => {
        onOpenChange(false)
        // Keyingi ochilishda toza forma bo'lsin
        setIdempotencyKey('')
      },
    })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent width="lg" className="max-w-[720px]">
        <DialogHeader>
          <div>
            <DialogTitle>Submit a job</DialogTitle>
            <DialogDescription>
              Code runs inside an isolated gVisor sandbox with no network access by default.
            </DialogDescription>
          </div>
        </DialogHeader>

        <DialogBody className="flex flex-col gap-4">
          {/* Namunalar */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-[.05em] text-fg-faint">
              Samples
            </span>
            {SAMPLES.map((sample) => (
              <button
                key={sample.label}
                type="button"
                onClick={() => applySample(sample)}
                className="rounded-md border border-line bg-surface-2 px-2.5 py-1 text-sm text-fg-muted transition-colors hover:border-line-hover hover:text-fg"
              >
                {sample.label}
              </button>
            ))}
          </div>

          <Field label="Code" hint={`Runs as main.${runtime === 'python' ? 'py' : 'js'}`}>
            <Textarea
              mono
              rows={12}
              spellCheck={false}
              value={code}
              onChange={(event) => setCode(event.target.value)}
              onKeyDown={(event) => {
                // Tab kod maydonida 4 bo'sh joy kiritadi (fokusni ko'chirmaydi)
                if (event.key === 'Tab') {
                  event.preventDefault()
                  const target = event.currentTarget
                  const { selectionStart, selectionEnd, value } = target
                  const next = `${value.slice(0, selectionStart)}    ${value.slice(selectionEnd)}`
                  setCode(next)
                  requestAnimationFrame(() => {
                    target.selectionStart = selectionStart + 4
                    target.selectionEnd = selectionStart + 4
                  })
                }
              }}
              placeholder="print('hello')"
              aria-label="Job code"
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Runtime">
              <SingleSelect options={RUNTIME_OPTIONS} value={runtime} onChange={setRuntime} />
            </Field>
            <Field label="Priority">
              <SingleSelect options={PRIORITY_OPTIONS} value={priority} onChange={setPriority} />
            </Field>
          </div>

          <Field
            label="Payload (JSON)"
            hint="Appears as payload.json inside the sandbox"
            error={payloadError}
          >
            <Textarea
              mono
              rows={4}
              spellCheck={false}
              value={payload}
              onChange={(event) => setPayload(event.target.value)}
              placeholder='{ "args": [21] }'
              aria-label="Job payload"
              className={cn(payloadError && 'border-failed focus:border-failed')}
            />
          </Field>

          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Timeout (s)">
              <Input
                type="number"
                min={1}
                max={900}
                value={timeout}
                onChange={(event) => setTimeoutSeconds(event.target.value)}
              />
            </Field>
            <Field label="Max retries">
              <Input
                type="number"
                min={0}
                max={10}
                value={retries}
                onChange={(event) => setRetries(event.target.value)}
              />
            </Field>
            <Field label="Tags" hint="comma separated">
              <Input
                value={tags}
                onChange={(event) => setTags(event.target.value)}
                placeholder="prod, etl"
              />
            </Field>
          </div>

          <Field label="Idempotency key" hint="Prevents duplicate submissions">
            <div className="flex gap-2">
              <Input
                value={idempotencyKey}
                onChange={(event) => setIdempotencyKey(event.target.value)}
                placeholder="order-12345"
                className="font-mono"
              />
              <Button
                variant="secondary"
                onClick={() => setIdempotencyKey(crypto.randomUUID())}
                className="shrink-0"
              >
                Generate
              </Button>
            </div>
          </Field>
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button variant="primary" size="md" disabled={!canSubmit} onClick={onSubmit}>
            {submit.isPending ? 'Submitting…' : 'Submit job'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string
  hint?: string
  error?: string | null
  children: React.ReactNode
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="flex items-baseline gap-2">
        <span className="text-xs font-semibold uppercase tracking-[.05em] text-fg-faint">
          {label}
        </span>
        {hint ? <span className="text-xs text-fg-faint">{hint}</span> : null}
      </span>
      {children}
      {error ? <span className="font-mono text-xs text-failed">{error}</span> : null}
    </label>
  )
}
