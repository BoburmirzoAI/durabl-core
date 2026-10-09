'use client'

import { useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useState } from 'react'

import { EmptyState } from '@/components/common/EmptyState'
import { ErrorState } from '@/components/common/ErrorState'
import { Pagination } from '@/components/common/Pagination'
import { SectionHeader } from '@/components/common/SectionHeader'
import { AddWebhookModal } from '@/components/webhooks/AddWebhookModal'
import { DeliveryLog } from '@/components/webhooks/DeliveryLog'
import { WebhookCard } from '@/components/webhooks/WebhookCard'
import { DeliveryDetailDrawer } from '@/components/webhooks/DeliveryDetailDrawer'
import { RotateSecretModal } from '@/components/webhooks/RotateSecretModal'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useDeliveries, useWebhooks } from '@/lib/hooks/useWebhooks'
import type { Webhook, WebhookDelivery } from '@/types'

/** Webhook'lar — dizayndagi kartalar + yuborish tarixi. */
export default function WebhooksPage() {
  return (
    <Suspense fallback={null}>
      <WebhooksContent />
    </Suspense>
  )
}

function WebhooksContent() {
  const searchParams = useSearchParams()
  const [modalOpen, setModalOpen] = useState(false)
  const [rotateHook, setRotateHook] = useState<Webhook | null>(null)
  const [detailDelivery, setDetailDelivery] = useState<WebhookDelivery | null>(null)
  const [editing, setEditing] = useState<Webhook | null>(null)
  const [page, setPage] = useState(1)

  const webhooks = useWebhooks()
  const deliveries = useDeliveries({ page, page_size: 15 })

  useEffect(() => {
    if (searchParams.get('new') === '1') setModalOpen(true)
  }, [searchParams])

  const openCreate = (): void => {
    setEditing(null)
    setModalOpen(true)
  }

  return (
    <>
      <SectionHeader
        title="Webhooks"
        description="Durabl POSTs signed events to your endpoints with automatic retries"
        actions={
          <Button variant="primary" size="md" onClick={openCreate}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden>
              <path d="M12 5v14M5 12h14" />
            </svg>
            Add webhook
          </Button>
        }
      />

      {webhooks.error ? (
        <ErrorState error={webhooks.error} onRetry={() => void webhooks.refetch()} />
      ) : webhooks.isLoading ? (
        <div className="grid gap-3.5 lg:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Card key={i} className="p-4">
              <Skeleton className="h-4 w-full" />
              <Skeleton className="mt-3 h-5 w-40" />
              <Skeleton className="mt-4 h-8 w-full" />
            </Card>
          ))}
        </div>
      ) : !webhooks.data || webhooks.data.length === 0 ? (
        <Card>
          <EmptyState
            icon="M13 3 4 14h7l-1 7 9-11h-7z"
            title="No webhooks configured"
            description="Add an endpoint and Durabl will notify it whenever a job finishes, fails or lands in the DLQ."
            action={
              <Button variant="primary" size="md" onClick={openCreate}>
                Add your first webhook
              </Button>
            }
          />
        </Card>
      ) : (
        <div className="grid gap-3.5 lg:grid-cols-2 xl:grid-cols-3">
          {webhooks.data.map((webhook) => (
            <WebhookCard
              onRotateSecret={setRotateHook}
              key={webhook.id}
              webhook={webhook}
              onEdit={(hook) => {
                setEditing(hook)
                setModalOpen(true)
              }}
            />
          ))}
        </div>
      )}

      <DeliveryLog
        deliveries={deliveries.data?.items}
        loading={deliveries.isLoading}
        onOpenDetail={setDetailDelivery}
      />
      {deliveries.data ? (
        <Pagination pagination={deliveries.data.pagination} onPageChange={setPage} />
      ) : null}

      <AddWebhookModal open={modalOpen} onOpenChange={setModalOpen} editing={editing} />

      <RotateSecretModal
        webhook={rotateHook}
        onOpenChange={(open) => {
          if (!open) setRotateHook(null)
        }}
      />

      <DeliveryDetailDrawer
        delivery={detailDelivery}
        onOpenChange={(open) => {
          if (!open) setDetailDelivery(null)
        }}
      />
    </>
  )
}
