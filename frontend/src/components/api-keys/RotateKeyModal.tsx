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
import { useRotateApiKey } from '@/lib/hooks/useApiKeys'
import { formatTimestamp } from '@/lib/utils/time'
import type { ApiKey, ApiKeyRotation } from '@/types'

/**
 * Kalitni almashtirish oqimi.
 *
 * ## Nega bekor qilish emas, almashtirish
 *
 * Buzilgan kalitni shunchaki bekor qilish ishlab turgan tizimni darhol
 * to'xtatadi. Almashtirish esa yangi kalit beradi va eskisiga 24 soat
 * muddat qoldiradi — deploy qilishga vaqt bo'ladi.
 *
 * Ikki bosqich (`RotateSecretModal` bilan bir xil naqsh): avval oqibat,
 * keyin bir martalik qiymat.
 */
export function RotateKeyModal({
  apiKey,
  onOpenChange,
}: {
  apiKey: ApiKey | null
  onOpenChange: (open: boolean) => void
}) {
  const rotate = useRotateApiKey()
  const [result, setResult] = useState<ApiKeyRotation | null>(null)

  const close = (): void => {
    setResult(null)
    onOpenChange(false)
  }

  return (
    <Dialog
      open={apiKey !== null}
      onOpenChange={(open) => {
        if (!open) close()
      }}
    >
      <DialogContent width="md">
        <DialogHeader>
          <div className="min-w-0">
            <DialogTitle>{result ? 'New API key' : 'Rotate API key?'}</DialogTitle>
            <DialogDescription>
              {result ? 'Copy it now — it will not be shown again.' : apiKey?.name}
            </DialogDescription>
          </div>
        </DialogHeader>

        <DialogBody className="space-y-3.5">
          {result ? (
            <>
              <div className="rounded-lg border border-line-inner bg-canvas-deep px-3.5 py-3">
                <div className="flex items-start gap-2">
                  <code className="min-w-0 flex-1 break-all font-mono text-sm text-fg-bright">
                    {result.key}
                  </code>
                  <CopyButton value={result.key} label="API key" size="md" />
                </div>
              </div>

              <div className="rounded-lg border border-pending/25 bg-pending/[0.07] px-3.5 py-3 text-sm">
                <div className="font-medium text-fg">The old key still works until</div>
                <div className="mt-0.5 font-mono text-xs text-fg-soft">
                  {formatTimestamp(result.old_key_valid_until)}
                </div>
                <div className="mt-1.5 text-fg-dim">
                  Deploy the new key before then. After that, requests using the old key get
                  401 Unauthorized.
                </div>
              </div>
            </>
          ) : (
            <div className="space-y-3">
              <p className="text-sm text-fg-soft">
                A new key is generated immediately. The key name, permissions and usage history
                stay with this entry — only the secret value changes.
              </p>
              <ul className="space-y-1.5 text-sm text-fg-dim">
                <li className="flex gap-2">
                  <span className="text-fg-faint">•</span>
                  The old key keeps working for 24 hours, so nothing breaks instantly.
                </li>
                <li className="flex gap-2">
                  <span className="text-fg-faint">•</span>
                  The new key is shown <span className="text-fg-soft">once</span> — we only store
                  its hash.
                </li>
                <li className="flex gap-2">
                  <span className="text-fg-faint">•</span>
                  In-flight requests are unaffected.
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
                disabled={rotate.isPending || !apiKey}
                onClick={() => {
                  if (!apiKey) return
                  rotate.mutate(apiKey.id, { onSuccess: setResult })
                }}
              >
                {rotate.isPending ? 'Rotating…' : 'Rotate key'}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
