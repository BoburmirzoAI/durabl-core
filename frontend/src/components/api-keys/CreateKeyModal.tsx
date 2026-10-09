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
import { Input } from '@/components/ui/input'
import { SingleSelect } from '@/components/ui/filter-select'
import { CopyButton } from '@/components/common/CopyButton'
import { useCreateApiKey } from '@/lib/hooks/useApiKeys'
import { API_KEY_SCOPES, type ApiKeyCreated, type ApiKeyScope } from '@/types'

/**
 * API kalit yaratish dialogi.
 *
 * IKKI HOLATLI: forma -> muvaffaqiyat. Muvaffaqiyat holatida XOM KALIT
 * bir marta ko'rsatiladi va foydalanuvchi "Saqlab oldim" tugmasini
 * bosmaguncha dialog yopilmaydi (kalit boshqa hech qayerda ko'rinmaydi).
 */
const EXPIRY_OPTIONS = [
  { value: 'never', label: 'Never expires' },
  { value: '30', label: '30 days' },
  { value: '90', label: '90 days' },
  { value: '365', label: '1 year' },
] as const

const SCOPE_LABELS: Record<ApiKeyScope, string> = {
  'jobs:read': 'Read jobs and executions',
  'jobs:write': 'Submit and cancel jobs',
  'dlq:read': 'Read the dead letter queue',
  'dlq:write': 'Retry and delete DLQ entries',
  admin: 'Full administrative access',
}

export function CreateKeyModal({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const create = useCreateApiKey()
  const [name, setName] = useState('')
  const [scopes, setScopes] = useState<ApiKeyScope[]>(['jobs:read', 'jobs:write'])
  const [expiry, setExpiry] = useState<string>('never')
  const [created, setCreated] = useState<ApiKeyCreated | null>(null)
  const [acknowledged, setAcknowledged] = useState(false)

  // Dialog yopilganda holatni tozalaymiz
  useEffect(() => {
    if (!open) {
      setName('')
      setScopes(['jobs:read', 'jobs:write'])
      setExpiry('never')
      setCreated(null)
      setAcknowledged(false)
      create.reset()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  const toggleScope = (scope: ApiKeyScope): void => {
    setScopes((current) =>
      current.includes(scope) ? current.filter((s) => s !== scope) : [...current, scope],
    )
  }

  const onCreate = (): void => {
    create.mutate(
      {
        name: name.trim(),
        scopes,
        expires_in_days: expiry === 'never' ? null : Number(expiry),
      },
      { onSuccess: (key) => setCreated(key) },
    )
  }

  const canCreate = name.trim().length > 0 && scopes.length > 0 && !create.isPending

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        // Kalit ko'rsatilganda tasdiqlanmaguncha yopilmaydi
        if (!next && created && !acknowledged) return
        onOpenChange(next)
      }}
    >
      <DialogContent width="md">
        {created ? (
          <>
            <DialogHeader>
              <div>
                <DialogTitle>API key created</DialogTitle>
                <DialogDescription>
                  Copy it now — this is the only time the full key is shown.
                </DialogDescription>
              </div>
            </DialogHeader>

            <DialogBody className="flex flex-col gap-4">
              <div className="flex items-start gap-3 rounded-xl border border-pending/25 bg-pending/[0.08] px-3.5 py-3">
                <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mt-px shrink-0 text-pending" aria-hidden>
                  <path d="M12 3 2 20h20zM12 10v4M12 17h.01" />
                </svg>
                <span className="text-sm text-fg-soft">
                  Durabl stores only a hash of this key. If you lose it you will need to create a
                  new one.
                </span>
              </div>

              <div className="flex items-center gap-2 rounded-lg border border-line bg-canvas-deep px-3 py-2.5">
                <code className="min-w-0 flex-1 break-all font-mono text-sm text-fg">
                  {created.key}
                </code>
                <CopyButton value={created.key} label="API key" size="md" />
              </div>

              <div className="rounded-lg border border-line-inner bg-canvas-deep px-3.5 py-3">
                <div className="mb-1.5 text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                  Try it
                </div>
                <pre className="m-0 overflow-x-auto whitespace-pre font-mono text-xs leading-[1.7] text-fg-muted">
{`curl -X POST https://api.durabl.dev/api/v1/jobs \\
  -H "X-API-Key: ${created.key.slice(0, 18)}…" \\
  -H "Content-Type: application/json" \\
  -d '{"code":"print(1)","runtime":"python"}'`}
                </pre>
              </div>

              <label className="flex cursor-pointer items-center gap-2.5 text-sm text-fg-soft">
                <Checkbox
                  checked={acknowledged}
                  onToggle={() => setAcknowledged((a) => !a)}
                  aria-label="I have saved this key"
                />
                I have saved this key somewhere safe
              </label>
            </DialogBody>

            <DialogFooter>
              <Button
                variant="primary"
                size="md"
                disabled={!acknowledged}
                onClick={() => onOpenChange(false)}
              >
                Done
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader>
              <div>
                <DialogTitle>Create API key</DialogTitle>
                <DialogDescription>
                  Keys authenticate SDK and HTTP requests via the X-API-Key header.
                </DialogDescription>
              </div>
            </DialogHeader>

            <DialogBody className="flex flex-col gap-4">
              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                  Name
                </span>
                <Input
                  autoFocus
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Production, CI, laptop…"
                />
              </label>

              <div className="flex flex-col gap-2">
                <span className="text-xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                  Permissions
                </span>
                {API_KEY_SCOPES.map((scope) => (
                  <label
                    key={scope}
                    className="flex cursor-pointer items-center gap-2.5 rounded-lg border border-line-inner bg-canvas-deep px-3 py-2"
                  >
                    <Checkbox
                      checked={scopes.includes(scope)}
                      onToggle={() => toggleScope(scope)}
                      aria-label={scope}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block font-mono text-sm text-fg-soft">{scope}</span>
                      <span className="block text-xs text-fg-faint">{SCOPE_LABELS[scope]}</span>
                    </span>
                  </label>
                ))}
                {scopes.includes('admin') ? (
                  <span className="text-xs text-pending">
                    Admin scope grants access to every user&apos;s data — use sparingly.
                  </span>
                ) : null}
              </div>

              <label className="flex flex-col gap-1.5">
                <span className="text-xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                  Expiry
                </span>
                <SingleSelect options={EXPIRY_OPTIONS} value={expiry} onChange={setExpiry} />
              </label>
            </DialogBody>

            <DialogFooter>
              <Button variant="ghost" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button variant="primary" size="md" disabled={!canCreate} onClick={onCreate}>
                {create.isPending ? 'Creating…' : 'Create key'}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
