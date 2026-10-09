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
import { Switch } from '@/components/ui/switch'
import { Tabs } from '@/components/ui/tabs'
import { useCreateAdminUser } from '@/lib/hooks/useAdmin'
import { PLAN_TYPES, type PlanType } from '@/types'

const PLAN_TABS = PLAN_TYPES.map((plan) => ({ value: plan, label: plan }))

/**
 * Admin qo'lda hisob ochadi.
 *
 * ## Nega kerak
 *
 * Korporativ mijoz shartnoma imzolaydi, lekin ro'yxatdan o'tish
 * formasidan o'tishni xohlamaydi; yoki qo'llab-quvvatlash jamoasi
 * sinov hisobini tayyorlaydi. Ikkala holatda ham hisob ADMIN tomonidan
 * ochiladi va darhol kerakli tarifga qo'yiladi.
 *
 * Parol so'ralmaydi: hisob "taklif" holatida yaratiladi va foydalanuvchi
 * o'zi parol o'rnatadi — admin boshqa odamning parolini bilmasligi kerak.
 */
export function CreateUserDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
}) {
  const create = useCreateAdminUser()
  const [email, setEmail] = useState('')
  const [fullName, setFullName] = useState('')
  const [plan, setPlan] = useState<PlanType>('starter')
  const [isAdmin, setIsAdmin] = useState(false)
  const [credit, setCredit] = useState('0')

  const creditValue = Number(credit)
  const canSubmit = email.trim().length > 0 && !create.isPending

  const close = (): void => {
    setEmail('')
    setFullName('')
    setPlan('starter')
    setIsAdmin(false)
    setCredit('0')
    onOpenChange(false)
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) close()
      }}
    >
      <DialogContent width="md">
        <DialogHeader>
          <div>
            <DialogTitle>Create an account</DialogTitle>
            <DialogDescription>
              The user receives an invitation and sets their own password.
            </DialogDescription>
          </div>
        </DialogHeader>

        <DialogBody className="space-y-4">
          <label className="block">
            <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
              Email
            </span>
            <Input
              autoFocus
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="ops@customer.com"
            />
          </label>

          <label className="block">
            <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
              Full name (optional)
            </span>
            <Input
              value={fullName}
              onChange={(event) => setFullName(event.target.value)}
              placeholder="Alex Carter"
            />
          </label>

          <div>
            <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
              Plan
            </span>
            <Tabs aria-label="Plan" items={PLAN_TABS} value={plan} onChange={setPlan} />
          </div>

          <label className="block">
            <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
              Starting credit (USD)
            </span>
            <Input
              value={credit}
              onChange={(event) => setCredit(event.target.value.replace(/[^\d.]/g, ''))}
              inputMode="decimal"
              className="font-mono"
              aria-label="Starting credit in US dollars"
            />
          </label>

          <div className="flex items-start justify-between gap-4 rounded-lg border border-failed/20 bg-failed/[0.05] px-3.5 py-3">
            <div className="min-w-0">
              <div className="text-base text-fg-soft">Make this an admin</div>
              <div className="mt-0.5 text-sm leading-[1.5] text-fg-dim">
                Admins can see and change every account on the platform. Grant sparingly.
              </div>
            </div>
            <Switch checked={isAdmin} onCheckedChange={setIsAdmin} aria-label="Admin account" />
          </div>
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={close}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="md"
            disabled={!canSubmit}
            onClick={() =>
              create.mutate(
                {
                  email,
                  full_name: fullName,
                  plan,
                  is_admin: isAdmin,
                  starting_credit_usd: Number.isFinite(creditValue) ? creditValue : 0,
                },
                { onSuccess: close },
              )
            }
          >
            {create.isPending ? 'Creating…' : 'Create account'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
