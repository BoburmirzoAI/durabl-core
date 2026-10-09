'use client'

import { useState } from 'react'

import { CopyButton } from '@/components/common/CopyButton'
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
import { useRotateWebhookSecret } from '@/lib/hooks/useWebhooks'
import { formatTimestamp } from '@/lib/utils/time'
import type { Webhook, WebhookSecretRotation } from '@/types'

/**
 * Imzolash kalitini almashtirish oqimi.
 *
 * ## Nega ikki bosqich
 *
 * Rotatsiya mijozning ishlab turgan integratsiyasini buzishi mumkin —
 * shuning uchun avval OQIBAT aytiladi, keyin tasdiqlanadi. Yangi kalit
 * esa FAQAT bir marta ko'rsatiladi (backend uni xeshlab saqlaydi), shuning
 * uchun ikkinchi bosqich uni nusxalashga majburlaydi.
 */
export function RotateSecretModal({
  webhook,
  onOpenChange,
}: {
  webhook: Webhook | null
  onOpenChange: (open: boolean) => void
}) {
  const rotate = useRotateWebhookSecret()
  const [result, setResult] = useState<WebhookSecretRotation | null>(null)

  const close = (): void => {
    setResult(null)
    onOpenChange(false)
  }

  return (
    <Dialog
      open={webhook !== null}
      onOpenChange={(open) => {
        if (!open) close()
      }}
    >
      <DialogContent width="md">
        <DialogHeader>
          <div className="min-w-0">
            <DialogTitle>{result ? 'New signing secret' : 'Rotate signing secret?'}</DialogTitle>
            <DialogDescription>
              {result
                ? 'Copy it now — it will not be shown again.'
                : webhook?.url}
            </DialogDescription>
          </div>
        </DialogHeader>

        <DialogBody className="space-y-3.5">
          {result ? (
            <>
              <div className="rounded-lg border border-line-inner bg-canvas-deep px-3.5 py-3">
                <div className="flex items-start gap-2">
                  <code className="min-w-0 flex-1 break-all font-mono text-sm text-fg-bright">
                    {result.secret}
                  </code>
                  <CopyButton value={result.secret} label="Signing secret" size="md" />
                </div>
              </div>

              <div className="rounded-lg border border-pending/25 bg-pending/[0.07] px-3.5 py-3 text-sm">
                <div className="font-medium text-fg">The old secret still works until</div>
                <div className="mt-0.5 font-mono text-xs text-fg-soft">
                  {formatTimestamp(result.old_secret_valid_until)}
                </div>
                <div className="mt-1.5 text-fg-dim">
                  Update your endpoint before then. After that, deliveries signed with the old
                  secret will fail verification on your side.
                </div>
              </div>
            </>
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-fg-soft">
                A new secret is generated immediately. Your endpoint must be updated to verify
                signatures with it.
              </p>
              <ul className="space-y-1.5 text-sm text-fg-dim">
                <li className="flex gap-2">
                  <span className="text-fg-faint">•</span>
                  The old secret keeps working for 24 hours, so nothing breaks instantly.
                </li>
                <li className="flex gap-2">
                  <span className="text-fg-faint">•</span>
                  The new secret is shown <span className="text-fg-soft">once</span> — we only
                  store its hash.
                </li>
                <li className="flex gap-2">
                  <span className="text-fg-faint">•</span>
                  Deliveries already queued keep the old signature.
                </li>
              </ul>
            </div>
          )}
        </DialogBody>

        <DialogFooter>
          {result ? (
            <Button variant="primary" size="md" onClick={close}>
              I saved it
            </Button>
          ) : (
            <>
              <Button variant="ghost" onClick={close}>
                Cancel
              </Button>
              <Button
                variant="danger"
                size="md"
                disabled={rotate.isPending || !webhook}
                onClick={() => {
                  if (!webhook) return
                  rotate.mutate(webhook.id, { onSuccess: setResult })
                }}
              >
                {rotate.isPending ? 'Rotating…' : 'Rotate secret'}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
