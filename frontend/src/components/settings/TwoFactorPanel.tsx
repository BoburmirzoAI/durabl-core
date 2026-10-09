'use client'

import { useState } from 'react'

import { ConfirmDialog } from '@/components/common/ConfirmDialog'
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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import {
  useDisableTwoFactor,
  useRegenerateRecoveryCodes,
  useSetupTwoFactor,
  useTwoFactorStatus,
  useVerifyTwoFactor,
} from '@/lib/hooks/useAccount'
import { formatTimestamp } from '@/lib/utils/time'
import type { TwoFactorSetup } from '@/types'

import { QrCode } from './QrCode'

/**
 * Ikki bosqichli tasdiqlash.
 *
 * ## Oqim
 *
 * `setup` → QR + tiklash kodlari → foydalanuvchi ilovadan kelgan kodni
 * kiritadi → `verify` → yoqildi.
 *
 * Tasdiqlash bosqichi SHART: QR'ni skanerlamasdan yoki noto'g'ri
 * skanerlab yoqib qo'yilsa, foydalanuvchi o'z hisobidan chiqib qoladi.
 * Shuning uchun "yoqish" tugmasi emas, "tasdiqlash" tugmasi yoqadi.
 *
 * Tiklash kodlari AVVAL ko'rsatiladi — telefonni yo'qotgan odam uchun
 * yagona yo'l shular, va ularni keyin qayta ko'rish mumkin emas.
 */
export function TwoFactorPanel({ email }: { email: string }) {
  const status = useTwoFactorStatus()
  const setup = useSetupTwoFactor()
  const verify = useVerifyTwoFactor()
  const disable = useDisableTwoFactor()
  const regenerate = useRegenerateRecoveryCodes()

  const [draft, setDraft] = useState<TwoFactorSetup | null>(null)
  const [code, setCode] = useState('')
  const [savedCodes, setSavedCodes] = useState(false)
  const [confirmDisable, setConfirmDisable] = useState(false)
  const [newCodes, setNewCodes] = useState<string[] | null>(null)

  const enabled = status.data?.enabled ?? false

  const closeSetup = (): void => {
    setDraft(null)
    setCode('')
    setSavedCodes(false)
  }

  return (
    <>
      <Card className="p-4">
        <div className="flex flex-wrap items-start gap-4">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2.5">
              <span className="text-base font-medium text-fg-soft">
                Two-factor authentication
              </span>
              {status.data ? (
                enabled ? (
                  <Badge variant="success">On</Badge>
                ) : (
                  <Badge className="bg-pending/[0.12] text-pending">Off</Badge>
                )
              ) : null}
            </div>
            <p className="mt-1 max-w-[520px] text-sm leading-[1.55] text-fg-dim">
              {enabled
                ? `Enabled ${status.data?.enabled_at ? formatTimestamp(status.data.enabled_at) : ''}. A code from your authenticator app is required at every sign-in.`
                : 'Require a time-based code in addition to your password. A stolen password alone is then not enough to sign in.'}
            </p>
            {enabled ? (
              <p className="mt-1.5 text-sm text-fg-faint">
                {status.data?.recovery_codes_left ?? 0} recovery codes remaining.
              </p>
            ) : null}
          </div>

          <div className="flex shrink-0 flex-wrap items-center gap-2">
            {enabled ? (
              <>
                <Button
                  variant="secondary"
                  disabled={regenerate.isPending}
                  onClick={() => regenerate.mutate(undefined, { onSuccess: setNewCodes })}
                >
                  {regenerate.isPending ? 'Generating…' : 'New recovery codes'}
                </Button>
                <Button variant="danger" onClick={() => setConfirmDisable(true)}>
                  Turn off
                </Button>
              </>
            ) : (
              <Button
                variant="primary"
                size="md"
                disabled={setup.isPending}
                onClick={() => setup.mutate(email, { onSuccess: setDraft })}
              >
                {setup.isPending ? 'Preparing…' : 'Set up 2FA'}
              </Button>
            )}
          </div>
        </div>
      </Card>

      {/* Sozlash oqimi */}
      <Dialog
        open={draft !== null}
        onOpenChange={(open) => {
          if (!open) closeSetup()
        }}
      >
        <DialogContent width="lg">
          <DialogHeader>
            <div>
              <DialogTitle>Set up two-factor authentication</DialogTitle>
              <DialogDescription>
                Scan the code, save the recovery codes, then confirm with a generated code.
              </DialogDescription>
            </div>
          </DialogHeader>

          <DialogBody className="space-y-4">
            {draft ? (
              <>
                <div className="flex flex-wrap gap-5">
                  <div className="shrink-0 rounded-lg bg-white p-2.5">
                    <QrCode value={draft.otpauth_url} size={176} />
                  </div>
                  <div className="min-w-0 flex-1 space-y-3">
                    <div>
                      <div className="text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                        Step 1 — scan
                      </div>
                      <p className="mt-1 text-sm leading-[1.55] text-fg-dim">
                        Open Google Authenticator, 1Password, Authy or any TOTP app and scan the
                        code.
                      </p>
                    </div>
                    <div>
                      <div className="text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                        Can&apos;t scan? Enter this key
                      </div>
                      <div className="mt-1.5 flex items-start gap-2 rounded-lg border border-line-inner bg-canvas-deep px-3 py-2">
                        <code className="min-w-0 flex-1 break-all font-mono text-xs text-fg-soft">
                          {draft.secret}
                        </code>
                        <CopyButton value={draft.secret} label="Setup key" />
                      </div>
                    </div>
                  </div>
                </div>

                <div className="rounded-lg border border-pending/25 bg-pending/[0.06] p-3.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-2xs font-semibold uppercase tracking-[.05em] text-pending">
                      Step 2 — save your recovery codes
                    </span>
                    <CopyButton
                      value={draft.recovery_codes.join('\n')}
                      label="Recovery codes"
                      className="ml-auto"
                    />
                  </div>
                  <p className="mt-1.5 text-sm text-fg-dim">
                    Each code works once. They are the only way back in if you lose the device —
                    they are not shown again.
                  </p>
                  <div className="mt-2.5 grid grid-cols-2 gap-x-4 gap-y-1 sm:grid-cols-3">
                    {draft.recovery_codes.map((recovery) => (
                      <code key={recovery} className="font-mono text-xs text-fg-soft">
                        {recovery}
                      </code>
                    ))}
                  </div>
                  <label className="mt-3 flex items-center gap-2 text-sm text-fg-soft">
                    <input
                      type="checkbox"
                      checked={savedCodes}
                      onChange={(event) => setSavedCodes(event.target.checked)}
                      className="h-3.5 w-3.5 accent-[hsl(var(--accent))]"
                    />
                    I have saved these codes somewhere safe
                  </label>
                </div>

                <div>
                  <div className="text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                    Step 3 — confirm
                  </div>
                  <div className="mt-1.5 flex flex-wrap items-center gap-2">
                    <Input
                      value={code}
                      onChange={(event) =>
                        setCode(event.target.value.replace(/\D/g, '').slice(0, 6))
                      }
                      placeholder="000000"
                      inputMode="numeric"
                      aria-label="Six digit code from your authenticator app"
                      className="w-[140px] text-center font-mono tracking-[.3em]"
                    />
                    <span className="text-sm text-fg-faint">
                      Enter the 6-digit code your app shows now.
                    </span>
                  </div>
                </div>
              </>
            ) : null}
          </DialogBody>

          <DialogFooter>
            <Button variant="ghost" onClick={closeSetup}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="md"
              disabled={!savedCodes || code.length !== 6 || verify.isPending}
              title={
                !savedCodes
                  ? 'Confirm you saved the recovery codes first'
                  : code.length !== 6
                    ? 'Enter the 6-digit code'
                    : undefined
              }
              onClick={() => verify.mutate(code, { onSuccess: closeSetup })}
            >
              {verify.isPending ? 'Verifying…' : 'Enable 2FA'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Yangi tiklash kodlari */}
      <Dialog
        open={newCodes !== null}
        onOpenChange={(open) => {
          if (!open) setNewCodes(null)
        }}
      >
        <DialogContent width="md">
          <DialogHeader>
            <div>
              <DialogTitle>New recovery codes</DialogTitle>
              <DialogDescription>
                The previous codes no longer work. Save these now.
              </DialogDescription>
            </div>
          </DialogHeader>
          <DialogBody>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 rounded-lg border border-line-inner bg-canvas-deep p-3.5">
              {(newCodes ?? []).map((recovery) => (
                <code key={recovery} className="font-mono text-xs text-fg-soft">
                  {recovery}
                </code>
              ))}
            </div>
          </DialogBody>
          <DialogFooter>
            <CopyButton value={(newCodes ?? []).join('\n')} label="Recovery codes" size="md" />
            <Button variant="primary" size="md" onClick={() => setNewCodes(null)}>
              I saved them
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={confirmDisable}
        onOpenChange={setConfirmDisable}
        title="Turn off two-factor authentication?"
        description="Your account will be protected by the password alone. Anyone who obtains it can sign in."
        confirmLabel="Turn off 2FA"
        destructive
        pending={disable.isPending}
        onConfirm={() => {
          disable.mutate()
          setConfirmDisable(false)
        }}
      />
    </>
  )
}
