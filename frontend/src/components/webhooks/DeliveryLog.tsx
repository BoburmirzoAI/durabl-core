'use client'

import { useState } from 'react'

import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/common/EmptyState'
import { RelativeTime } from '@/components/common/RelativeTime'
import { StatusBadge } from '@/components/common/StatusBadge'
import { SkeletonRows } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils/cn'
import { formatDuration, truncate } from '@/lib/utils/format'
import { deliveryStatusStyle } from '@/lib/utils/status'
import { useResendDelivery } from '@/lib/hooks/useWebhooks'
import type { WebhookDelivery } from '@/types'

/**
 * Yuborish tarixi — dizayndagi ustunlar:
 * `minmax(120px,1.5fr) 118px 78px 58px 58px 90px 68px`
 *
 * Qator ochilganda so'rov va javob tanasi yonma-yon ko'rinadi — bu
 * webhook'ni debug qilishning eng tez yo'li.
 */
const GRID = 'minmax(120px,1.5fr) 128px 94px 58px 58px 96px 76px'

export function DeliveryLog({
  deliveries,
  loading = false,
  onOpenDetail,
}: {
  deliveries: WebhookDelivery[] | undefined
  loading?: boolean
  /** 'Details' bosilganda to'liq tafsilot panelini ochadi. */
  onOpenDetail?: (delivery: WebhookDelivery) => void,
}) {
  const [openIds, setOpenIds] = useState<string[]>([])
  const resend = useResendDelivery()

  const toggle = (id: string): void => {
    setOpenIds((current) =>
      current.includes(id) ? current.filter((v) => v !== id) : [...current, id],
    )
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">Recent Deliveries</CardTitle>
      </CardHeader>

      <div className="table-head grid items-center px-4" style={{ gridTemplateColumns: GRID }}>
        <span>Webhook</span>
        <span>Event</span>
        <span>Status</span>
        <span>Code</span>
        <span>Try</span>
        <span>Delivered</span>
        <span className="text-right">Actions</span>
      </div>

      {loading && !deliveries ? (
        <SkeletonRows rows={8} columns={GRID} />
      ) : !deliveries || deliveries.length === 0 ? (
        <EmptyState
          icon="M13 3 4 14h7l-1 7 9-11h-7z"
          title="No deliveries yet"
          description="Events appear here as soon as your jobs start finishing."
        />
      ) : (
        deliveries.map((delivery) => {
          const style = deliveryStatusStyle(delivery.status)
          const isOpen = openIds.includes(delivery.id)
          const codeClass =
            delivery.response_code === null
              ? 'text-fg-faint'
              : delivery.response_code < 300
                ? 'text-success'
                : 'text-failed'

          return (
            <div key={delivery.id}>
              <div
                role="button"
                tabIndex={0}
                aria-expanded={isOpen}
                onClick={() => toggle(delivery.id)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    toggle(delivery.id)
                  }
                }}
                className="grid h-10 cursor-pointer items-center px-4 transition-colors hover:bg-surface-3"
                style={{ gridTemplateColumns: GRID }}
              >
                <span className="truncate font-mono text-sm text-fg-muted" title={delivery.webhook_url}>
                  {truncate(delivery.webhook_url.replace(/^https?:\/\//, ''), 40)}
                </span>
                <span className="truncate font-mono text-sm text-fg-soft">{delivery.event}</span>
                <span>
                  <StatusBadge style={style} />
                </span>
                <span className={cn('tabular font-mono text-sm', codeClass)}>
                  {delivery.response_code ?? '—'}
                </span>
                <span className="tabular font-mono text-sm text-fg-muted">{delivery.attempt}</span>
                <RelativeTime
                  value={delivery.delivered_at ?? delivery.created_at}
                  className="tabular font-mono text-sm text-fg-faint"
                />
                <span
                  className="flex justify-end gap-1.5"
                  onClick={(event) => event.stopPropagation()}
                >
                  {onOpenDetail ? (
                    <button
                      type="button"
                      onClick={() => onOpenDetail(delivery)}
                      className="rounded border border-line bg-canvas px-2.5 py-[3px] text-xs text-fg-muted transition-colors hover:border-line-hover hover:text-fg"
                      title="Full request, response, headers and signature"
                    >
                      Details
                    </button>
                  ) : null}
                  <button
                    type="button"
                    disabled={resend.isPending}
                    onClick={() => resend.mutate(delivery.id)}
                    className="rounded border border-line bg-canvas px-2.5 py-[3px] text-xs text-fg-muted transition-colors hover:border-line-hover hover:text-fg disabled:opacity-40"
                  >
                    Resend
                  </button>
                </span>
              </div>

              <div className="border-b border-line-subtle" />

              {isOpen ? (
                <div className="grid animate-slide-down gap-3.5 border-b border-line-subtle bg-canvas-sunken px-4 pb-3.5 pt-3 lg:grid-cols-2">
                  <Pane label="Request" body={delivery.request_body} />
                  <Pane
                    label="Response"
                    body={delivery.response_body}
                    tone={delivery.status === 'success' ? 'neutral' : 'error'}
                  />
                  {delivery.error_message ? (
                    <div className="lg:col-span-2">
                      <div className="mb-1.5 text-xs font-semibold text-fg-dim">Error</div>
                      <div className="rounded-lg border border-failed/[0.18] bg-failed/[0.06] px-3 py-2 font-mono text-xs text-failed-text">
                        {delivery.error_message}
                        {delivery.duration_ms !== null
                          ? ` · ${formatDuration(delivery.duration_ms)}`
                          : ''}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          )
        })
      )}
    </Card>
  )
}

function Pane({
  label,
  body,
  tone = 'neutral',
}: {
  label: string
  body: string
  tone?: 'neutral' | 'error'
}) {
  return (
    <div className="min-w-0">
      <div className="mb-[7px] text-xs font-semibold text-fg-dim">{label}</div>
      <pre
        className={cn(
          'm-0 max-h-[220px] overflow-auto whitespace-pre rounded-lg border px-3 py-2.5 font-mono text-xs leading-[1.6]',
          tone === 'error'
            ? 'border-failed/[0.18] bg-failed/[0.06] text-failed-text'
            : 'border-line-inner bg-canvas-deep text-fg-muted',
        )}
      >
        {body}
      </pre>
    </div>
  )
}
