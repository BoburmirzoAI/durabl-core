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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { SkeletonRows } from '@/components/ui/skeleton'
import { useSecrets, useUpdateSecret } from '@/lib/hooks/usePlatform'
import { formatDate } from '@/lib/utils/time'
import type { PlatformSecret } from '@/types'

const GRID = 'minmax(170px,1fr) minmax(180px,1.2fr) 120px 120px 92px'

/**
 * Platforma sirlari.
 *
 * ═══════════════════════════════════════════════════════════════════
 * ASOSIY QOIDA: SIR O'QILMAYDI
 * ═══════════════════════════════════════════════════════════════════
 *
 * Bu panelda "ko'rsatish" tugmasi YO'Q va bo'lmaydi. Sirni admin
 * panelida ko'rsatish — uni brauzer tarixiga, skrinshotga va ekran
 * ulashuviga chiqarish demak. Qiymatni faqat ALMASHTIRISH mumkin.
 *
 * Shu sababli har bir qatorda "qayerda ishlatiladi" ustuni bor:
 * almashtirgandan keyin qaysi xizmatni qayta ishga tushirish kerakligi
 * darhol ko'rinadi.
 */
export function SecretsPanel() {
  const query = useSecrets()
  const update = useUpdateSecret()
  const [editing, setEditing] = useState<PlatformSecret | null>(null)
  const [value, setValue] = useState('')

  const close = (): void => {
    setEditing(null)
    setValue('')
  }

  return (
    <>
      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle className="text-md">Secrets</CardTitle>
          <CardDescription>
            Values are write-only. There is no way to read a secret back — rotate it if it was lost.
          </CardDescription>
        </CardHeader>

        <div className="overflow-x-auto">
          <div className="min-w-[760px]">
            <div className="table-head grid items-center gap-3 px-4" style={{ gridTemplateColumns: GRID }}>
              <span>Key</span>
              <span>Value</span>
              <span>Used by</span>
              <span>Updated</span>
              <span className="sr-only">Actions</span>
            </div>

            {query.isLoading && !query.data ? (
              <SkeletonRows rows={5} columns={GRID} />
            ) : (
              (query.data ?? []).map((secret) => (
                <div
                  key={secret.key}
                  className="grid min-h-[54px] items-center gap-3 border-b border-line-subtle px-4 py-2 last:border-b-0 hover:bg-surface-3"
                  style={{ gridTemplateColumns: GRID }}
                >
                  <span className="min-w-0">
                    <span className="flex items-center gap-2">
                      <code className="truncate font-mono text-xs text-fg-soft">{secret.key}</code>
                      {secret.required ? (
                        <Badge size="sm" variant="outline">
                          required
                        </Badge>
                      ) : null}
                    </span>
                    <span className="mt-0.5 block truncate text-xs text-fg-faint" title={secret.description}>
                      {secret.description}
                    </span>
                  </span>

                  <code className="truncate font-mono text-xs text-fg-muted">
                    {secret.masked_value}
                  </code>

                  <span className="truncate font-mono text-2xs text-fg-faint">
                    {secret.used_by}
                  </span>

                  <span className="min-w-0">
                    <span className="block text-xs text-fg-muted">
                      {formatDate(secret.updated_at)}
                    </span>
                    <span className="block truncate text-2xs text-fg-ghost">
                      {secret.updated_by}
                    </span>
                  </span>

                  <span className="flex justify-end">
                    <Button
                      variant="secondary"
                      size="sm"
                      onClick={() => {
                        setEditing(secret)
                        setValue('')
                      }}
                    >
                      Rotate
                    </Button>
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </Card>

      <Dialog
        open={editing !== null}
        onOpenChange={(open) => {
          if (!open) close()
        }}
      >
        <DialogContent width="md">
          <DialogHeader>
            <div className="min-w-0">
              <DialogTitle>Rotate {editing?.key}</DialogTitle>
              <DialogDescription>{editing?.description}</DialogDescription>
            </div>
          </DialogHeader>

          <DialogBody className="space-y-3.5">
            <div className="rounded-lg border border-pending/25 bg-pending/[0.07] px-3.5 py-3 text-sm leading-[1.55] text-pending">
              {editing?.key === 'JWT_SECRET'
                ? 'Rotating this invalidates every access token — all users are signed out immediately.'
                : editing?.key === 'WEBHOOK_SIGNING_KEY'
                  ? 'Every webhook endpoint gets a new derived secret. Customers must update their verification before the next delivery.'
                  : `Restart ${editing?.used_by} after saving — the running processes keep the old value until then.`}
            </div>

            <label className="block">
              <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                New value
              </span>
              <Input
                autoFocus
                type="password"
                value={value}
                onChange={(event) => setValue(event.target.value)}
                placeholder="Paste the new value"
                className="font-mono"
                aria-label="New secret value"
              />
              <span className="mt-1.5 block text-xs text-fg-faint">
                Only the last 4 characters are ever shown again.
              </span>
            </label>
          </DialogBody>

          <DialogFooter>
            <Button variant="ghost" onClick={close}>
              Cancel
            </Button>
            <Button
              variant="danger"
              size="md"
              disabled={value.trim().length < 8 || update.isPending}
              onClick={() => {
                if (!editing) return
                update.mutate({ key: editing.key, value }, { onSuccess: close })
              }}
            >
              {update.isPending ? 'Rotating…' : 'Rotate secret'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
