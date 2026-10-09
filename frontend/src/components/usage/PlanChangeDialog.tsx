'use client'

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
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/common/ErrorState'
import { useChangePlan, usePlanChangePreview } from '@/lib/hooks/useBilling'
import { formatCurrency } from '@/lib/utils/format'
import { formatTimestamp } from '@/lib/utils/time'
import type { PlanChangeRow, PlanType } from '@/types'

/**
 * Reja almashtirish — OLDINDAN ko'rsatish bilan.
 *
 * ## Nega oddiy tasdiq dialogi yetarli emas
 *
 * "Pro'dan Starter'ga o'tasizmi?" degan savolga "ha" deyish oson, lekin
 * oqibati og'ir: joriy sarf yangi limitdan oshgan bo'lsa, job yuborish
 * DARHOL `402` bilan rad etila boshlaydi. Buni keyin bilish — eng yomon
 * holat.
 *
 * Shuning uchun dialog uch narsani ko'rsatadi:
 *
 * - **Blockers** — qizil, tasdiqlash tugmasini o'chiradi.
 * - **Warnings** — sariq, to'sqinlik qilmaydi, lekin bilish kerak.
 * - **To'liq solishtiruv** — har bir limit `eski → yangi`, yaxshilanish
 *   yashil, yomonlashish qizil.
 */
const DIRECTION_CLASS: Record<PlanChangeRow['direction'], string> = {
  better: 'text-success',
  worse: 'text-failed-text',
  same: 'text-fg-dim',
}

export function PlanChangeDialog({
  plan,
  onOpenChange,
}: {
  plan: PlanType | null
  onOpenChange: (open: boolean) => void
}) {
  const preview = usePlanChangePreview(plan)
  const change = useChangePlan()
  const data = preview.data
  const blocked = (data?.blockers.length ?? 0) > 0

  return (
    <Dialog
      open={plan !== null}
      onOpenChange={(open) => {
        if (!open) onOpenChange(false)
      }}
    >
      <DialogContent width="lg">
        <DialogHeader>
          <div className="min-w-0">
            <DialogTitle>
              {data
                ? data.direction === 'downgrade'
                  ? `Downgrade to ${data.to}?`
                  : data.direction === 'upgrade'
                    ? `Upgrade to ${data.to}?`
                    : `Switch to ${data.to}?`
                : 'Change plan'}
            </DialogTitle>
            <DialogDescription>
              {data
                ? data.direction === 'downgrade'
                  ? `Takes effect ${formatTimestamp(data.effective_at)}, at the end of the current period.`
                  : 'Takes effect immediately.'
                : 'Loading the comparison…'}
            </DialogDescription>
          </div>
        </DialogHeader>

        <DialogBody className="space-y-3.5">
          {preview.error ? (
            <ErrorState error={preview.error} onRetry={() => void preview.refetch()} />
          ) : !data ? (
            <Skeleton className="h-64 w-full" />
          ) : (
            <>
              {data.blockers.map((text) => (
                <div
                  key={text}
                  className="rounded-lg border border-failed/25 bg-failed/[0.07] px-3.5 py-3 text-sm leading-[1.55] text-failed-text"
                >
                  {text}
                </div>
              ))}
              {data.warnings.map((text) => (
                <div
                  key={text}
                  className="rounded-lg border border-pending/25 bg-pending/[0.07] px-3.5 py-3 text-sm leading-[1.55] text-pending"
                >
                  {text}
                </div>
              ))}

              <div className="overflow-hidden rounded-xl border border-line">
                <div
                  className="table-head grid items-center px-4"
                  style={{ gridTemplateColumns: 'minmax(130px,1.3fr) 1fr 18px 1fr' }}
                >
                  <span>Limit</span>
                  <span className="text-right capitalize">{data.from}</span>
                  <span />
                  <span className="text-right capitalize">{data.to}</span>
                </div>
                {data.rows.map((row) => (
                  <div
                    key={row.label}
                    className="grid h-10 items-center border-b border-line-subtle px-4 last:border-b-0"
                    style={{ gridTemplateColumns: 'minmax(130px,1.3fr) 1fr 18px 1fr' }}
                  >
                    <span className="truncate text-sm text-fg-dim">{row.label}</span>
                    <span className="tabular text-right font-mono text-sm text-fg-faint">
                      {row.from}
                    </span>
                    <span className="text-center text-2xs text-fg-ghost">→</span>
                    <span
                      className={`tabular text-right font-mono text-sm ${DIRECTION_CLASS[row.direction]}`}
                    >
                      {row.to}
                    </span>
                  </div>
                ))}
              </div>

              {data.direction === 'upgrade' && data.prorated_usd > 0 ? (
                <p className="text-sm text-fg-dim">
                  You will be charged{' '}
                  <span className="tabular font-mono text-fg">
                    {formatCurrency(data.prorated_usd)}
                  </span>{' '}
                  today for the rest of this billing period, then{' '}
                  <span className="tabular font-mono text-fg">
                    {formatCurrency(data.price_delta_usd)}
                  </span>{' '}
                  more per month.
                </p>
              ) : data.direction === 'downgrade' ? (
                <p className="text-sm text-fg-dim">
                  No refund is issued for the current period. From{' '}
                  {formatTimestamp(data.effective_at)} you pay{' '}
                  <span className="tabular font-mono text-fg">
                    {formatCurrency(Math.abs(data.price_delta_usd))}
                  </span>{' '}
                  less per month.
                </p>
              ) : null}
            </>
          )}
        </DialogBody>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant={data?.direction === 'downgrade' ? 'danger' : 'primary'}
            size="md"
            disabled={!data || blocked || change.isPending}
            title={blocked ? 'Resolve the blocker above first' : undefined}
            onClick={() => {
              if (!plan) return
              change.mutate(plan, { onSuccess: () => onOpenChange(false) })
            }}
          >
            {change.isPending
              ? 'Switching…'
              : blocked
                ? 'Blocked'
                : data?.direction === 'downgrade'
                  ? `Downgrade to ${data.to}`
                  : `Switch to ${data?.to ?? ''}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
