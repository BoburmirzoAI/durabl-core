'use client'

import { useEffect, useState } from 'react'

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
import { Checkbox } from '@/components/ui/checkbox'
import { CopyButton } from '@/components/common/CopyButton'
import { Input } from '@/components/ui/input'
import { useCreateWebhook, useUpdateWebhook } from '@/lib/hooks/useWebhooks'
import { WEBHOOK_EVENTS, type Webhook, type WebhookEventName } from '@/types'

/**
 * Webhook qo'shish / tahrirlash dialogi.
 *
 * URL validatsiyasi MIJOZDA ham qilinadi: backend `localhost` va ichki
 * IP'larni SSRF himoyasi sababli rad etadi, shuning uchun foydalanuvchini
 * so'rov yuborishdan OLDIN ogohlantiramiz.
 */
const BLOCKED_HOSTS = /^(localhost|127\.|0\.0\.0\.0|10\.|192\.168\.|169\.254\.|\[::1\])/i

function validateUrl(value: string): string | null {
  if (!value.trim()) return null
  let url: URL
  try {
    url = new URL(value)
  } catch {
    return 'Enter a full URL including https://'
  }
  if (url.protocol !== 'https:' && url.protocol !== 'http:') {
    return 'Only http:// and https:// are supported'
  }
  if (BLOCKED_HOSTS.test(url.hostname)) {
    return 'Private and loopback addresses are blocked (SSRF protection)'
  }
  if (url.protocol === 'http:') {
    return 'warn:Durabl will send signed payloads over plain HTTP — use https:// in production'
  }
  return null
}

export function AddWebhookModal({
  open,
  onOpenChange,
  editing,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  editing?: Webhook | null
}) {
  const create = useCreateWebhook()
  const update = useUpdateWebhook()

  const [url, setUrl] = useState('')
  const [description, setDescription] = useState('')
  const [events, setEvents] = useState<WebhookEventName[]>(['job.succeeded', 'job.failed'])
  const [secret, setSecret] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      setUrl('')
      setDescription('')
      setEvents(['job.succeeded', 'job.failed'])
      setSecret(null)
      create.reset()
      return
    }
    if (editing) {
      setUrl(editing.url)
      setDescription(editing.description ?? '')
      setEvents(editing.events)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, editing])

  const validation = validateUrl(url)
  const isWarning = validation?.startsWith('warn:') ?? false
  const errorText = validation && !isWarning ? validation : null
  const warnText = isWarning ? validation?.slice(5) : null

  const canSave = url.trim().length > 0 && !errorText && events.length > 0

  const toggleEvent = (event: WebhookEventName): void => {
    setEvents((current) =>
      current.includes(event) ? current.filter((e) => e !== event) : [...current, event],
    )
  }

  const onSave = (): void => {
    if (editing) {
      update.mutate(
        { id: editing.id, patch: { url, events, description } },
        { onSuccess: () => onOpenChange(false) },
      )
      return
    }
    create.mutate(
      { url, events, description: description || undefined },
      {
        onSuccess: (hook) => {
          // Secret bir marta ko'rsatiladi
          if (hook.secret) setSecret(hook.secret)
          else onOpenChange(false)
        },
      },
    )
  }

  const pending = create.isPending || update.isPending

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent width="md">
        {secret ? (
          <>
            <DialogHeader>
              <div>
                <DialogTitle>Webhook created</DialogTitle>
                <DialogDescription>
                  Save the signing secret — it is shown only once.
                </DialogDescription>
              </div>
            </DialogHeader>
            <DialogBody className="flex flex-col gap-4">
              <div className="flex items-center gap-2 rounded-lg border border-line bg-canvas-deep px-3 py-2.5">
                <code className="min-w-0 flex-1 break-all font-mono text-sm text-fg">{secret}</code>
                <CopyButton value={secret} label="Signing secret" size="md" />
              </div>
              <div className="rounded-lg border border-line-inner bg-canvas-deep px-3.5 py-3">
                <div className="mb-1.5 text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                  Verify the signature
                </div>
                <pre className="m-0 overflow-x-auto whitespace-pre font-mono text-xs leading-[1.7] text-fg-muted">
{`# header: X-Durabl-Signature: t=<unix>,v1=<hex>
import hmac, hashlib

def verify(body: bytes, header: str, secret: str) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    signed = f"{parts['t']}.".encode() + body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])`}
                </pre>
              </div>
            </DialogBody>
            <DialogFooter>
              <Button variant="primary" size="md" onClick={() => onOpenChange(false)}>
                Done
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader>
              <div>
                <DialogTitle>{editing ? 'Edit webhook' : 'Add webhook'}</DialogTitle>
                <DialogDescription>
                  Durabl POSTs signed JSON events to this URL with retries and backoff.
                </DialogDescription>
              </div>
            </DialogHeader>

            <DialogBody className="flex flex-col gap-4">
              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                  Endpoint URL
                </span>
                <Input
                  autoFocus
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                  placeholder="https://api.example.com/durabl/events"
                  className="font-mono"
                  aria-invalid={Boolean(errorText)}
                />
                {errorText ? (
                  <span className="text-xs text-failed">{errorText}</span>
                ) : warnText ? (
                  <span className="text-xs text-pending">{warnText}</span>
                ) : null}
              </label>

              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                  Description
                </span>
                <Input
                  value={description}
                  onChange={(event) => setDescription(event.target.value)}
                  placeholder="Production event sink"
                />
              </label>

              <div className="flex flex-col gap-2">
                <span className="text-xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                  Events
                </span>
                <div className="grid gap-2 sm:grid-cols-2">
                  {WEBHOOK_EVENTS.map((event) => (
                    <label
                      key={event}
                      className="flex cursor-pointer items-center gap-2.5 rounded-lg border border-line-inner bg-canvas-deep px-3 py-2"
                    >
                      <Checkbox
                        checked={events.includes(event)}
                        onToggle={() => toggleEvent(event)}
                        aria-label={event}
                      />
                      <span className="font-mono text-sm text-fg-soft">{event}</span>
                    </label>
                  ))}
                </div>
                {events.length === 0 ? (
                  <span className="text-xs text-failed">Select at least one event</span>
                ) : null}
              </div>
            </DialogBody>

            <DialogFooter>
              <Button variant="ghost" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button variant="primary" size="md" disabled={!canSave || pending} onClick={onSave}>
                {pending ? 'Saving…' : editing ? 'Save changes' : 'Create webhook'}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
