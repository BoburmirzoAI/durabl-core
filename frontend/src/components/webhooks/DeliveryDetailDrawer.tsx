'use client'

import { CopyButton } from '@/components/common/CopyButton'
import { DetailDrawer, DrawerRow, DrawerSection } from '@/components/common/DetailDrawer'
import { JsonViewer } from '@/components/common/JsonViewer'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils/cn'
import { formatDuration } from '@/lib/utils/format'
import { formatTimestamp } from '@/lib/utils/time'
import { useResendDelivery } from '@/lib/hooks/useWebhooks'
import { deliveryStatusStyle } from '@/lib/utils/status'
import type { WebhookDelivery } from '@/types'

/**
 * Bitta yetkazishning to'liq tafsiloti.
 *
 * ## Nega kerak
 *
 * Webhook ishlamaganda savol har doim bir xil: "biz nima yubordik va ular
 * nima qaytardi?". Jadvaldagi `502` kodi bunga javob bermaydi. Bu panel
 * so'rov va javobning HAMMASINI ko'rsatadi — sarlavhalar, tana, vaqt va
 * imzo — ya'ni mijoz muammoni O'Z tomonida tekshira oladi.
 *
 * Imzo alohida ajratilgan, chunki eng ko'p uchraydigan xato — mijoz imzoni
 * noto'g'ri hisoblashi.
 */
export function DeliveryDetailDrawer({
  delivery,
  onOpenChange,
}: {
  delivery: WebhookDelivery | null
  onOpenChange: (open: boolean) => void
}) {
  const resend = useResendDelivery()
  const style = delivery ? deliveryStatusStyle(delivery.status) : null

  const parsed = (text: string): unknown => {
    try {
      return JSON.parse(text)
    } catch {
      return text
    }
  }

  return (
    <DetailDrawer
      open={delivery !== null}
      onOpenChange={onOpenChange}
      width="lg"
      title={delivery ? <span className="font-mono text-base">{delivery.event}</span> : ''}
      description={delivery?.webhook_url}
      stats={
        delivery
          ? [
              { label: 'Status', value: style?.label ?? '—', tone: delivery.status === 'success' ? 'good' : 'bad' },
              { label: 'HTTP', value: delivery.response_code ?? '—' },
              { label: 'Duration', value: formatDuration(delivery.duration_ms) },
              { label: 'Attempt', value: delivery.attempt },
            ]
          : undefined
      }
      footer={
        delivery ? (
          <Button
            variant="primary"
            disabled={resend.isPending}
            onClick={() => resend.mutate(delivery.id)}
          >
            {resend.isPending ? 'Resending…' : 'Resend delivery'}
          </Button>
        ) : null
      }
    >
      {delivery ? (
        <>
          {/* Imzo — eng ko'p muammo shu yerda, shuning uchun tepada */}
          <DrawerSection
            title="Signature"
            action={<CopyButton value={delivery.signature} label="Signature" size="md" />}
          >
            <div className="flex items-center gap-2">
              <span
                className={cn(
                  'shrink-0 rounded-md border px-2 py-0.5 text-2xs font-semibold',
                  delivery.signature_valid
                    ? 'border-success/25 bg-success/[0.12] text-success'
                    : 'border-failed/25 bg-failed/[0.12] text-failed',
                )}
              >
                {delivery.signature_valid ? 'Valid' : 'Invalid'}
              </span>
              <span className="text-xs text-fg-dim">HMAC-SHA256 over the raw body</span>
            </div>
            <pre className="mt-2.5 overflow-x-auto rounded-lg border border-line-inner bg-canvas-deep px-3 py-2 font-mono text-xs text-fg-soft">
              {delivery.signature}
            </pre>
            <p className="mt-2 text-xs text-fg-faint">
              Verify it as{' '}
              <span className="font-mono">HMAC_SHA256(secret, &quot;{'{t}'}.&quot; + body)</span> and
              compare with <span className="font-mono">v1</span>.
            </p>
          </DrawerSection>

          <DrawerSection title="Request">
            <HeaderTable headers={delivery.request_headers} />
            <div className="mt-3 text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">
              Body
            </div>
            <JsonViewer data={parsed(delivery.request_body)} maxHeight={220} className="mt-1.5" />
          </DrawerSection>

          <DrawerSection title="Response">
            {Object.keys(delivery.response_headers).length > 0 ? (
              <HeaderTable headers={delivery.response_headers} />
            ) : (
              <div className="text-sm text-fg-faint">No response received.</div>
            )}
            {delivery.response_body ? (
              <>
                <div className="mt-3 text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">
                  Body
                </div>
                <JsonViewer
                  data={parsed(delivery.response_body)}
                  maxHeight={220}
                  className="mt-1.5"
                />
              </>
            ) : null}
            {delivery.error_message ? (
              <div className="mt-3 rounded-lg border border-failed/20 bg-failed/[0.07] px-3 py-2.5 text-sm text-failed-text">
                {delivery.error_message}
              </div>
            ) : null}
          </DrawerSection>

          <DrawerSection title="Timing">
            <DrawerRow label="Queued" value={formatTimestamp(delivery.created_at)} />
            <DrawerRow
              label="Delivered"
              value={delivery.delivered_at ? formatTimestamp(delivery.delivered_at) : '—'}
            />
            <DrawerRow label="Round trip" value={formatDuration(delivery.duration_ms)} />
            <DrawerRow label="Attempt" value={String(delivery.attempt)} />
            {delivery.job_id ? (
              <DrawerRow label="Job" value={delivery.job_id} mono />
            ) : null}
          </DrawerSection>
        </>
      ) : null}
    </DetailDrawer>
  )
}

/** Sarlavhalar jadvali — kalit/qiymat, mono shrift. */
function HeaderTable({ headers }: { headers: Record<string, string> }) {
  const entries = Object.entries(headers)
  if (entries.length === 0) return <div className="text-sm text-fg-faint">—</div>
  return (
    <div className="overflow-hidden rounded-lg border border-line-inner">
      {entries.map(([key, value]) => (
        <div
          key={key}
          className="flex items-baseline gap-3 border-b border-line-subtle bg-canvas-deep px-3 py-1.5 last:border-b-0"
        >
          <span className="w-[150px] shrink-0 font-mono text-2xs text-fg-dim">{key}</span>
          <span className="min-w-0 flex-1 break-all font-mono text-xs text-fg-soft">{value}</span>
        </div>
      ))}
    </div>
  )
}
