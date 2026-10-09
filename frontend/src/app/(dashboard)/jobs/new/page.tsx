'use client'

import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useMemo, useState } from 'react'

import { CodeEditor } from '@/components/common/CodeEditor'
import { JsonViewer } from '@/components/common/JsonViewer'
import { SectionHeader } from '@/components/common/SectionHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Tabs } from '@/components/ui/tabs'
import { useApiDefaults } from '@/lib/hooks/useAccount'
import { useSubmitJob } from '@/lib/hooks/useJobs'
import { useCreateTemplate, useMarkTemplateUsed, useTemplates } from '@/lib/hooks/useSchedules'
import { cn } from '@/lib/utils/cn'
import type { JobTemplate, Priority, Runtime } from '@/types'

const RUNTIME_TABS = [
  { value: 'python' as Runtime, label: 'Python' },
  { value: 'node' as Runtime, label: 'Node' },
]

const PRIORITY_TABS = [
  { value: 'low' as Priority, label: 'Low' },
  { value: 'normal' as Priority, label: 'Normal' },
  { value: 'high' as Priority, label: 'High' },
]

const STARTER: Record<Runtime, string> = {
  python: `def main(payload):
    """Entry point. The worker calls this with the submitted payload.

    Whatever you return is stored as the job result and shown on the
    job page.
    """
    return {"ok": True, "received": payload}
`,
  node: `export default async function main(payload) {
  // Entry point. Whatever you return is stored as the job result.
  return { ok: true, received: payload }
}
`,
}

/**
 * Yangi job — TO'LIQ sahifa.
 *
 * ═══════════════════════════════════════════════════════════════════
 * NEGA DIALOG EMAS
 * ═══════════════════════════════════════════════════════════════════
 *
 * `JobSubmitDialog` tez yuborish uchun qoladi (⌘N). Lekin jiddiy job
 * yozish — kod yozish demak: 40 qator kod, payload, timeout, idempotency
 * kaliti. Buni 500px modal ichida qilish qiynoq.
 *
 * To'liq sahifa yana ikki narsani beradi:
 *
 * - **Sinov ishga tushirish** — yuborishdan OLDIN kod va payload
 *   tekshiriladi. Bu mock rejimida ham ma'noli, chunki JSON tahlili va
 *   maydon tekshiruvi haqiqiy.
 * - **Shablon sifatida saqlash** — ishlagan narsani qayta yozmaslik.
 */
export default function NewJobPage() {
  return (
    <Suspense fallback={null}>
      <NewJobContent />
    </Suspense>
  )
}

function NewJobContent() {
  const router = useRouter()
  const searchParams = useSearchParams()

  const defaults = useApiDefaults()
  const templates = useTemplates()
  const submit = useSubmitJob()
  const saveTemplate = useCreateTemplate()
  const markUsed = useMarkTemplateUsed()

  const [runtime, setRuntime] = useState<Runtime>('python')
  const [code, setCode] = useState(STARTER.python)
  const [payloadText, setPayloadText] = useState('{\n  "example": true\n}')
  const [priority, setPriority] = useState<Priority>('normal')
  const [timeout, setTimeoutSeconds] = useState(300)
  const [maxRetries, setMaxRetries] = useState(3)
  const [idempotencyKey, setIdempotencyKey] = useState('')
  const [tags, setTags] = useState('')
  const [useIdempotency, setUseIdempotency] = useState(true)
  const [appliedTemplate, setAppliedTemplate] = useState<JobTemplate | null>(null)
  const [testResult, setTestResult] = useState<{ ok: boolean; lines: string[] } | null>(null)
  const [templateName, setTemplateName] = useState('')

  // Hisob standartlari kelganda to'ldiriladi (shablon ularni ustidan yozadi)
  useEffect(() => {
    if (!defaults.data || appliedTemplate) return
    setRuntime(defaults.data.runtime)
    setCode(STARTER[defaults.data.runtime])
    setPriority(defaults.data.priority)
    setTimeoutSeconds(defaults.data.timeout_seconds)
    setMaxRetries(defaults.data.max_retries)
    setUseIdempotency(defaults.data.auto_idempotency)
  }, [defaults.data, appliedTemplate])

  // `?template=<id>` bilan kelinsa, shablondan to'ldiriladi
  const templateId = searchParams.get('template')
  useEffect(() => {
    if (!templateId || !templates.data) return
    const template = templates.data.find((t) => t.id === templateId)
    if (!template || appliedTemplate?.id === template.id) return
    setAppliedTemplate(template)
    setRuntime(template.runtime)
    setCode(template.code)
    setPayloadText(template.payload)
    setPriority(template.priority)
    setTimeoutSeconds(template.timeout_seconds)
    setMaxRetries(template.max_retries)
  }, [templateId, templates.data, appliedTemplate])

  const payload = useMemo(() => {
    const text = payloadText.trim()
    if (text === '') return { value: null as Record<string, unknown> | null, error: null }
    try {
      const parsed: unknown = JSON.parse(text)
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return { value: null, error: 'The payload must be a JSON object, not an array or scalar.' }
      }
      return { value: parsed as Record<string, unknown>, error: null }
    } catch (error) {
      return { value: null, error: error instanceof Error ? error.message : 'Invalid JSON' }
    }
  }, [payloadText])

  const codeEmpty = code.trim().length === 0
  const canSubmit = !codeEmpty && payload.error === null && !submit.isPending

  /**
   * Sinov ishga tushirish.
   *
   * Mock rejimida kod HAQIQATAN bajarilmaydi — buni yashirmaymiz.
   * Lekin tekshiradigan narsa hali ham bor: JSON tahlili, kirish
   * nuqtasining mavjudligi, limitlar. Aynan shular yuborishdan keyin
   * `validation_error` beradi, shuning uchun ularni oldin tutib olish
   * foydali.
   */
  function dryRun(): void {
    const lines: string[] = []
    let ok = true

    lines.push(`runtime: ${runtime}`)
    if (codeEmpty) {
      ok = false
      lines.push('✗ code is empty')
    } else {
      const entry =
        runtime === 'python' ? /def\s+main\s*\(/.test(code) : /function\s+main|export\s+default/.test(code)
      lines.push(entry ? '✓ entry point found' : '✗ no main() entry point — the worker calls main(payload)')
      if (!entry) ok = false
      lines.push(`✓ ${code.split('\n').length} lines, ${new Blob([code]).size} bytes`)
    }

    if (payload.error) {
      ok = false
      lines.push(`✗ payload: ${payload.error}`)
    } else if (payload.value === null) {
      lines.push('• payload: empty (main receives None)')
    } else {
      const keys = Object.keys(payload.value)
      lines.push(`✓ payload: valid JSON object, ${keys.length} key${keys.length === 1 ? '' : 's'}`)
    }

    if (timeout < 10) {
      ok = false
      lines.push('✗ timeout below the 10s minimum')
    } else {
      lines.push(`✓ timeout ${timeout}s, up to ${maxRetries} ${maxRetries === 1 ? 'retry' : 'retries'}`)
    }

    const key = idempotencyKey.trim()
    if (key.length > 0) {
      lines.push(`✓ idempotency key "${key}" — a repeat submit returns the same job`)
    } else if (useIdempotency) {
      lines.push('• no explicit key — one is derived from the payload hash')
    } else {
      lines.push('• no idempotency — a repeat submit creates a second job')
    }

    lines.push('')
    lines.push(
      ok
        ? 'Checks passed. The sandbox is not executed in this preview — submit to run it.'
        : 'Fix the items above before submitting.',
    )
    setTestResult({ ok, lines })
  }

  function onSubmit(): void {
    const key = idempotencyKey.trim()
    submit.mutate(
      {
        code,
        runtime,
        priority,
        payload: payload.value,
        timeout_seconds: timeout,
        max_retries: maxRetries,
        tags: tags
          .split(',')
          .map((t) => t.trim())
          .filter(Boolean),
        idempotency_key: key.length > 0 ? key : null,
      },
      {
        onSuccess: (job) => {
          if (appliedTemplate) markUsed.mutate(appliedTemplate.id)
          router.push(`/jobs/${job.id}`)
        },
      },
    )
  }

  function onSaveTemplate(): void {
    const name = templateName.trim()
    if (name.length === 0) return
    saveTemplate.mutate({
      name,
      description: `Saved from the new-job page on ${new Date().toISOString().slice(0, 10)}.`,
      category: 'saved',
      runtime,
      code,
      payload: payloadText,
      timeout_seconds: timeout,
      memory_mb: 512,
      max_retries: maxRetries,
      priority,
    })
    setTemplateName('')
  }

  return (
    <>
      <SectionHeader
        title="New job"
        description={
          appliedTemplate
            ? `Started from the "${appliedTemplate.name}" template`
            : 'Write the code, attach a payload, submit'
        }
        actions={
          <>
            <Button variant="ghost" asChild>
              <Link href="/templates">Browse templates</Link>
            </Button>
            <Button variant="secondary" onClick={dryRun}>
              Test run
            </Button>
            <Button variant="primary" size="md" disabled={!canSubmit} onClick={onSubmit}>
              {submit.isPending ? 'Submitting…' : 'Submit job'}
            </Button>
          </>
        }
      />

      <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.55fr)_minmax(320px,1fr)]">
        {/* Chap ustun — kod va payload */}
        <div className="space-y-4">
          <Card className="overflow-hidden">
            <CardHeader>
              <div className="flex flex-wrap items-center gap-4">
                <div>
                  <CardTitle className="text-md">Code</CardTitle>
                  <CardDescription>
                    The worker calls <code className="font-mono">main(payload)</code> and stores
                    whatever it returns.
                  </CardDescription>
                </div>
                <div className="ml-auto flex items-center gap-2">
                  {appliedTemplate ? (
                    <Badge variant="outline" size="sm">
                      {appliedTemplate.name}
                    </Badge>
                  ) : null}
                  <Tabs
                    aria-label="Runtime"
                    items={RUNTIME_TABS}
                    value={runtime}
                    onChange={(value) => {
                      setRuntime(value)
                      // Faqat tegilmagan boshlang'ich kod almashtiriladi —
                      // yozilgan kodni yo'qotib qo'yish mumkin emas
                      if (code.trim() === STARTER[runtime].trim() || code.trim() === '') {
                        setCode(STARTER[value])
                      }
                    }}
                  />
                </div>
              </div>
            </CardHeader>
            <div className="p-4">
              <CodeEditor
                value={code}
                onChange={setCode}
                runtime={runtime}
                label=""
                minRows={18}
                maxHeight={520}
                error={codeEmpty ? 'The job needs some code.' : null}
              />
            </div>
          </Card>

          <Card className="overflow-hidden">
            <CardHeader>
              <div className="flex flex-wrap items-center gap-4">
                <div>
                  <CardTitle className="text-md">Payload</CardTitle>
                  <CardDescription>
                    A JSON object passed to <code className="font-mono">main()</code>. Leave empty
                    for none.
                  </CardDescription>
                </div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="ml-auto"
                  onClick={() => {
                    if (payload.error) return
                    setPayloadText(JSON.stringify(payload.value ?? {}, null, 2))
                  }}
                  disabled={payload.error !== null}
                >
                  Format
                </Button>
              </div>
            </CardHeader>
            <div className="grid gap-4 p-4 lg:grid-cols-2">
              <div>
                <textarea
                  value={payloadText}
                  onChange={(event) => setPayloadText(event.target.value)}
                  spellCheck={false}
                  aria-label="Job payload as JSON"
                  aria-invalid={payload.error !== null}
                  rows={10}
                  className={cn(
                    'w-full resize-y rounded-lg border bg-canvas-deep px-3 py-2.5 font-mono text-xs leading-[1.7] text-fg-soft outline-none transition-colors',
                    payload.error ? 'border-failed/50' : 'border-line focus:border-accent-edge-2',
                  )}
                />
                {payload.error ? (
                  <p className="mt-1.5 text-xs text-failed-text">{payload.error}</p>
                ) : null}
              </div>
              <div className="min-w-0">
                <div className="mb-1.5 text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                  Parsed
                </div>
                {payload.error ? (
                  <div className="rounded-lg border border-line-inner bg-canvas-deep px-3 py-2.5 text-xs text-fg-faint">
                    Fix the JSON to see the parsed tree.
                  </div>
                ) : (
                  <JsonViewer data={payload.value ?? {}} maxHeight={240} />
                )}
              </div>
            </div>
          </Card>

          {testResult ? (
            <Card className="overflow-hidden">
              <CardHeader>
                <div className="flex items-center gap-2.5">
                  <CardTitle className="text-md">Test run</CardTitle>
                  <Badge
                    size="sm"
                    className={
                      testResult.ok
                        ? 'bg-success/[0.12] text-success'
                        : 'bg-failed/[0.12] text-failed'
                    }
                  >
                    {testResult.ok ? 'Passed' : 'Problems found'}
                  </Badge>
                </div>
              </CardHeader>
              <pre className="m-0 whitespace-pre-wrap px-4 pb-4 font-mono text-xs leading-[1.75] text-fg-muted">
                {testResult.lines.join('\n')}
              </pre>
            </Card>
          ) : null}
        </div>

        {/* O'ng ustun — sozlamalar */}
        <div className="space-y-4">
          <Card className="overflow-hidden">
            <CardHeader>
              <CardTitle className="text-md">Execution</CardTitle>
            </CardHeader>
            <div className="divide-y divide-line-subtle">
              <Row label="Priority">
                <Tabs
                  aria-label="Priority"
                  items={PRIORITY_TABS}
                  value={priority}
                  onChange={setPriority}
                />
              </Row>
              <Row label="Timeout" value={`${timeout}s`}>
                <input
                  type="range"
                  min={10}
                  max={900}
                  step={10}
                  value={timeout}
                  onChange={(event) => setTimeoutSeconds(Number(event.target.value))}
                  aria-label="Timeout in seconds"
                  className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-line accent-[hsl(var(--accent))]"
                />
              </Row>
              <Row label="Max retries" value={String(maxRetries)}>
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
              </Row>
            </div>
          </Card>

          <Card className="overflow-hidden">
            <CardHeader>
              <CardTitle className="text-md">Idempotency</CardTitle>
              <CardDescription>
                Durabl stores the key for 24 hours. Submitting the same key again returns the
                original job instead of running the work twice.
              </CardDescription>
            </CardHeader>
            <div className="space-y-3 p-4">
              <Input
                value={idempotencyKey}
                onChange={(event) => setIdempotencyKey(event.target.value)}
                placeholder="order-12345"
                aria-label="Idempotency key"
                className="font-mono"
              />
              <div className="flex items-start justify-between gap-4">
                <span className="min-w-0 text-sm leading-[1.5] text-fg-dim">
                  Derive a key from the payload when none is given
                </span>
                <Switch
                  checked={useIdempotency}
                  onCheckedChange={setUseIdempotency}
                  aria-label="Automatic idempotency"
                />
              </div>
            </div>
          </Card>

          <Card className="overflow-hidden">
            <CardHeader>
              <CardTitle className="text-md">Tags</CardTitle>
              <CardDescription>Comma separated. Useful for filtering later.</CardDescription>
            </CardHeader>
            <div className="p-4">
              <Input
                value={tags}
                onChange={(event) => setTags(event.target.value)}
                placeholder="etl, nightly"
                aria-label="Tags"
              />
            </div>
          </Card>

          <Card className="p-4">
            <div className="text-base text-fg-soft">Save as template</div>
            <p className="mt-1 text-sm leading-[1.5] text-fg-dim">
              Keeps the code together with these settings so the next run is identical.
            </p>
            <Input
              value={templateName}
              onChange={(event) => setTemplateName(event.target.value)}
              placeholder={appliedTemplate ? `${appliedTemplate.name} (copy)` : 'Template name'}
              aria-label="Template name"
              className="mt-3"
            />
            <Button
              variant="secondary"
              className="mt-2.5"
              disabled={codeEmpty || templateName.trim().length === 0 || saveTemplate.isPending}
              onClick={onSaveTemplate}
            >
              {saveTemplate.isPending ? 'Saving…' : 'Save as template'}
            </Button>
          </Card>

          <Button
            variant="primary"
            size="lg"
            className="w-full"
            disabled={!canSubmit}
            onClick={onSubmit}
          >
            {submit.isPending ? 'Submitting…' : 'Submit job'}
          </Button>
          {!canSubmit && !submit.isPending ? (
            <p className="text-center text-xs text-fg-faint">
              {codeEmpty ? 'Add some code first.' : 'Fix the payload JSON first.'}
            </p>
          ) : null}
        </div>
      </div>
    </>
  )
}

function Row({
  label,
  value,
  children,
}: {
  label: string
  value?: string
  children: React.ReactNode
}) {
  return (
    <div className="px-4 py-3.5">
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <span className="text-base text-fg-soft">{label}</span>
        {value ? <span className="tabular font-mono text-sm text-fg">{value}</span> : null}
      </div>
      {children}
    </div>
  )
}
