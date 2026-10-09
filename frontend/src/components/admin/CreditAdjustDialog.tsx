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
import { Input } from '@/components/ui/input'
import { Tabs } from '@/components/ui/tabs'
import { useAdjustUserCredit } from '@/lib/hooks/useAdmin'
import { formatCurrency } from '@/lib/utils/format'
import type { AdminUser } from '@/types'

type Kind = 'credit' | 'refund' | 'charge' | 'adjustment'

const KIND_TABS = [
  { value: 'credit' as Kind, label: 'Credit' },
  { value: 'refund' as Kind, label: 'Refund' },
  { value: 'charge' as Kind, label: 'Charge' },
  { value: 'adjustment' as Kind, label: 'Adjustment' },
]

const KIND_HELP: Record<Kind, string> = {
  credit: 'Adds balance the customer can spend. Use for goodwill or prepay discounts.',
  refund: 'Returns money for a charge that should not have happened.',
  charge: 'Takes money off the balance. Use for manual overage billing.',
  adjustment: 'A correction that is neither a credit nor a charge in spirit — explain it clearly.',
}

const PRESETS = [10, 25, 50, 100, 250]

/**
 * Hisobga qo'lda pul harakati.
 *
 * ## Nega sabab majburiy
 *
 * Pul harakati audit jurnaliga tushadi va keyinchalik "nega bu odamga
 * $250 berilgan?" degan savol albatta chiqadi. Sababsiz yozuv o'sha
 * savolga javob bera olmaydi, shuning uchun tugma sababsiz ishlamaydi.
 *
 * ## Nega "charge" ham bor
 *
 * Faqat kredit berish mumkin bo'lsa, xato bilan berilgan kreditni
 * qaytarib olishning yo'li qolmaydi.
 */
export function CreditAdjustDialog({
  user,
  onOpenChange,
}: {
  user: AdminUser | null
  onOpenChange: (open: boolean) => void
}) {
  const adjust = useAdjustUserCredit()
  const [kind, setKind] = useState<Kind>('credit')
  const [amount, setAmount] = useState('25')
  const [reason, setReason] = useState('')

  const parsed = Number(amount)
  const valid = Number.isFinite(parsed) && parsed > 0
  const signed = kind === 'charge' ? -parsed : parsed
  const canSubmit = valid && reason.trim().length > 0 && !adjust.isPending

  const close = (): void => {
    setReason('')
    setAmount('25')
    setKind('credit')
    onOpenChange(false)
  }

  return (
    <Dialog
      open={user !== null}
      onOpenChange={(open) => {
        if (!open) close()
      }}
    >
      <DialogContent width="md">
        <DialogHeader>
          <div className="min-w-0">
            <DialogTitle>Adjust balance</DialogTitle>
            <DialogDescription>{user?.email}</DialogDescription>
          </div>
        </DialogHeader>

        <DialogBody className="space-y-4">
          <div>
            <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
              Type
            </span>
            <Tabs aria-label="Adjustment type" items={KIND_TABS} value={kind} onChange={setKind} />
            <p className="mt-2 text-sm leading-[1.5] text-fg-dim">{KIND_HELP[kind]}</p>
          </div>

          <div>
            <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
              Amount (USD)
            </span>
            <Input
              value={amount}
              onChange={(event) => setAmount(event.target.value.replace(/[^\d.]/g, ''))}
              inputMode="decimal"
              aria-label="Amount in US dollars"
              className="font-mono"
            />
            <div className="mt-2 flex flex-wrap gap-1.5">
              {PRESETS.map((preset) => (
                <Button
                  key={preset}
                  variant="outline"
                  size="sm"
                  onClick={() => setAmount(String(preset))}
                >
                  ${preset}
                </Button>
              ))}
            </div>
          </div>

          <label className="block">
            <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
              Reason (required)
            </span>
            <Input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Goodwill credit after the October incident"
            />
            <span className="mt-1.5 block text-xs text-fg-faint">
              Written to the audit log next to your admin account.
            </span>
          </label>

          {valid ? (
            <div className="rounded-lg border border-line-inner bg-canvas-deep px-3.5 py-3 text-sm">
              <span className="text-fg-dim">This records </span>
              <span
                className={`tabular font-mono ${signed > 0 ? 'text-success' : 'text-failed-text'}`}
              >
                {signed > 0 ? '+' : ''}
                {formatCurrency(signed)}
              </span>
              <span className="text-fg-dim"> against {user?.email}.</span>
            </div>
          ) : null}
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={close}>
            Cancel
          </Button>
          <Button
            variant={kind === 'charge' ? 'danger' : 'primary'}
            size="md"
            disabled={!canSubmit}
            onClick={() => {
              if (!user) return
              adjust.mutate(
                { id: user.id, amountUsd: signed, reason, kind },
                { onSuccess: close },
              )
            }}
          >
            {adjust.isPending ? 'Recording…' : kind === 'charge' ? 'Charge account' : 'Apply'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
