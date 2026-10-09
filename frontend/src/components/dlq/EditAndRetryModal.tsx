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
import { Textarea } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs } from '@/components/ui/tabs'
import { useJob, useSubmitJob } from '@/lib/hooks/useJobs'
import { DlqFixHint } from '@/components/dlq/DlqFixHint'
import type { DlqEntry } from '@/types'

/**
 * "Edit & retry" — DLQ yozuvidagi kodni tuzatib, YANGI job sifatida yuborish.
 *
 * ## Nega oddiy "retry" yetmaydi
 *
 * `POST /dlq/{id}/retry` AYNI kodni qayta navbatga qo'yadi. Agar xato kodda
 * bo'lsa (`non_zero_exit`, `validation_error`), bu yana o'sha xato bilan
 * tugaydi — foydalanuvchi aylanib qoladi. Bu oyna sababni TUZATIB yuborish
 * imkonini beradi.
 *
 * Natija — YANGI job (yangi `id`), chunki eski job'ning tarixi o'zgarmasligi
 * kerak: DLQ yozuvi nima bo'lganining yozuvi bo'lib qoladi.
 */
type TabValue = 'code' | 'payload'

export function EditAndRetryModal({
  entry,
  onOpenChange,
}: {
  entry: DlqEntry | null
  onOpenChange: (open: boolean) => void
}) {
  const job = useJob(entry?.job_id ?? '')
  const submit = useSubmitJob()

  const [tab, setTab] = useState<TabValue>('code')
  const [code, setCode] = useState('')
  const [payloadText, setPayloadText] = useState('')
  const [payloadError, setPayloadError] = useState<string | null>(null)

  // Job yuklangach maydonlarni to'ldiramiz (foydalanuvchi tahrirlay boshlasa
  // qayta yozib yubormasligi uchun faqat job ID o'zgarganda)
  useEffect(() => {
    if (!job.data) return
    setCode(job.data.code)
    setPayloadText(job.data.payload ? JSON.stringify(job.data.payload, null, 2) : '')
    setPayloadError(null)
    setTab('code')
  }, [job.data?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const parsePayload = (): Record<string, unknown> | null | false => {
    const text = payloadText.trim()
    if (!text) return null
    try {
      const parsed: unknown = JSON.parse(text)
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        setPayloadError('Payload must be a JSON OBJECT (not an array or scalar).')
        return false
      }
      setPayloadError(null)
      return parsed as Record<string, unknown>
    } catch (error) {
      setPayloadError(`Invalid JSON: ${(error as Error).message}`)
      return false
    }
  }

  const onSubmit = (): void => {
    if (!job.data) return
    const payload = parsePayload()
    if (payload === false) {
      setTab('payload')
      return
    }
    submit.mutate(
      {
        code,
        runtime: job.data.runtime,
        payload,
        priority: job.data.priority,
        timeout_seconds: job.data.timeout_seconds,
        max_retries: job.data.max_retries,
        // Tuzatilgan kod — YANGI job, shuning uchun eski idempotency kaliti
        // ATAYLAB uzatilmaydi (aks holda 409 yoki eski job qaytardi).
      },
      { onSuccess: () => onOpenChange(false) },
    )
  }

  return (
    <Dialog open={entry !== null} onOpenChange={onOpenChange}>
      <DialogContent width="lg">
        <DialogHeader>
          <div className="min-w-0">
            <DialogTitle>Edit &amp; retry</DialogTitle>
            <DialogDescription>
              Fix the code and submit it as a NEW job. The original DLQ entry is left untouched.
            </DialogDescription>
          </div>
        </DialogHeader>

        <DialogBody className="space-y-3.5">
          {entry ? <DlqFixHint reason={entry.failure_reason} /> : null}

          {job.isLoading || !job.data ? (
            <Skeleton className="h-64 w-full" />
          ) : (
            <>
              <Tabs
                aria-label="What to edit"
                items={[
                  { value: 'code' as const, label: 'Code' },
                  { value: 'payload' as const, label: 'Payload' },
                ]}
                value={tab}
                onChange={setTab}
              />

              {tab === 'code' ? (
                <CodeEditor
                  value={code}
                  onChange={setCode}
                  runtime={job.data.runtime}
                  label="Fixed code"
                  minRows={14}
                  maxHeight={320}
                />
              ) : (
                <div>
                  <label className="mb-1.5 block text-sm font-medium text-fg-soft">
                    Payload (JSON object)
                  </label>
                  <Textarea
                    mono
                    rows={12}
                    value={payloadText}
                    onChange={(event) => {
                      setPayloadText(event.target.value)
                      setPayloadError(null)
                    }}
                    placeholder='{"args": [], "kwargs": {}}'
                    aria-invalid={Boolean(payloadError)}
                  />
                  {payloadError ? (
                    <p className="mt-1.5 text-xs text-failed">{payloadError}</p>
                  ) : (
                    <p className="mt-1.5 text-xs text-fg-faint">
                      Leave empty to send no payload.
                    </p>
                  )}
                </div>
              )}
            </>
          )}
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="md"
            disabled={!job.data || submit.isPending || code.trim().length === 0}
            onClick={onSubmit}
          >
            {submit.isPending ? 'Submitting…' : 'Submit as new job'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
