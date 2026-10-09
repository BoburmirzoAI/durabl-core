'use client'

import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { RelativeTime } from '@/components/common/RelativeTime'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils/cn'
import { formatPercent } from '@/lib/utils/format'
import { useDeleteWebhook, useTestWebhook, useUpdateWebhook } from '@/lib/hooks/useWebhooks'
import type { Webhook } from '@/types'

/**
 * Webhook kartasi — dizayndagi ko'rinish:
 * URL (mono), hodisa nishonlari, faol/nofaol switch, pastda
 * "Last delivery" va "Success rate", eng pastda Test / Edit tugmalari.
 *
 * Ketma-ket xatolar bo'lsa qizil ogohlantirish chiqadi — webhook
 * avtomatik o'chib qolishidan oldin operator ko'rishi kerak.
 */
export function WebhookCard({
  webhook,
  onEdit,
  onRotateSecret,
}: {
  webhook: Webhook
  onEdit: (webhook: Webhook) => void
  /** Imzolash kalitini almashtirish oqimini ochadi. */
  onRotateSecret?: (webhook: Webhook) => void,
}) {
  const update = useUpdateWebhook()
  const remove = useDeleteWebhook()
  const test = useTestWebhook()
  const [confirmDelete, setConfirmDelete] = useState(false)

  const failing = webhook.consecutive_failures > 0
  const rateClass =
    webhook.success_rate >= 97
      ? 'text-success'
      : webhook.success_rate >= 85
        ? 'text-pending'
        : 'text-failed'

  return (
    <>
      <Card className="flex flex-col">
        <div className="flex items-start gap-3 border-b border-line-inner px-4 py-3.5">
          <div className="min-w-0 flex-1">
            <div className="break-all font-mono text-sm text-fg" title={webhook.url}>
              {webhook.url}
            </div>
            {webhook.description ? (
              <div className="mt-1 text-sm text-fg-dim">{webhook.description}</div>
            ) : null}
          </div>
          <Switch
            checked={webhook.is_active}
            onCheckedChange={(checked) =>
              update.mutate({ id: webhook.id, patch: { is_active: checked } })
            }
            aria-label={`${webhook.is_active ? 'Disable' : 'Enable'} webhook ${webhook.url}`}
          />
        </div>

        <div className="flex flex-wrap gap-1.5 px-4 py-3">
          {webhook.events.map((event) => (
            <Badge key={event} size="sm" variant="outline" className="font-mono">
              {event}
            </Badge>
          ))}
        </div>

        {failing ? (
          <div className="mx-4 mb-3 flex items-center gap-2.5 rounded-lg border border-failed/20 bg-failed/[0.07] px-3 py-2">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="shrink-0 text-failed" aria-hidden>
              <path d="M12 3 2 20h20zM12 10v4M12 17h.01" />
            </svg>
            <span className="text-xs text-failed-text">
              {webhook.consecutive_failures} consecutive failures — auto-disabled after 10
            </span>
          </div>
        ) : null}

        <div className="grid grid-cols-2 gap-4 border-t border-line-inner px-4 py-3">
          <div>
            <div className="text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
              Last delivery
            </div>
            <div className="mt-1 font-mono text-sm text-fg-muted">
              <RelativeTime value={webhook.last_triggered_at} />
            </div>
          </div>
          <div>
            <div className="text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
              Success rate
            </div>
            <div className={cn('tabular mt-1 font-mono text-sm font-semibold', rateClass)}>
              {formatPercent(webhook.success_rate, 0)}
            </div>
          </div>
        </div>

        <div className="flex gap-2 border-t border-line-inner px-4 py-3">
          <Button
            variant="secondary"
            size="sm"
            className="flex-1 justify-center bg-canvas"
            disabled={test.isPending}
            onClick={() => test.mutate(webhook.id)}
          >
            {test.isPending ? 'Sending…' : 'Test'}
          </Button>
          <Button
            variant="secondary"
            size="sm"
            className="flex-1 justify-center bg-canvas"
            onClick={() => onEdit(webhook)}
          >
            Edit
          </Button>
          {onRotateSecret ? (
            <Button
              variant="secondary"
              size="icon-sm"
              aria-label={`Rotate signing secret for ${webhook.url}`}
              title="Rotate signing secret"
              className="bg-canvas"
              onClick={() => onRotateSecret(webhook)}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
                <path d="M4 4v6h6M20 20v-6h-6M20 9a8 8 0 0 0-14-3M4 15a8 8 0 0 0 14 3" />
              </svg>
            </Button>
          ) : null}
          <Button
            variant="secondary"
            size="icon-sm"
            aria-label={`Delete webhook ${webhook.url}`}
            className="bg-canvas hover:text-failed"
            onClick={() => setConfirmDelete(true)}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6M10 11v6M14 11v6" />
            </svg>
          </Button>
        </div>
      </Card>

      <ConfirmDialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title="Delete webhook?"
        description={`Durabl will stop sending events to ${webhook.url}. Delivery history is kept.`}
        confirmLabel="Delete webhook"
        destructive
        pending={remove.isPending}
        onConfirm={() => {
          remove.mutate(webhook.id)
          setConfirmDelete(false)
        }}
      />
    </>
  )
}
