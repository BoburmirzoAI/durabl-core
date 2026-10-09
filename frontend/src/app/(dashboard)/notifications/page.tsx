'use client'

import { useState } from 'react'

import { EmptyState } from '@/components/common/EmptyState'
import { ErrorState } from '@/components/common/ErrorState'
import { Pagination } from '@/components/common/Pagination'
import { CountPill, SectionHeader } from '@/components/common/SectionHeader'
import { NotificationItem } from '@/components/notifications/NotificationItem'
import { Button } from '@/components/ui/button'
import { Tabs } from '@/components/ui/tabs'
import { SkeletonRows } from '@/components/ui/skeleton'
import {
  useMarkAllRead,
  useMarkNotificationRead,
  useNotifications,
} from '@/lib/hooks/useNotifications'
import { formatNumber } from '@/lib/utils/format'
import type { NotificationSeverity } from '@/types'

type Filter = 'all' | 'unread' | NotificationSeverity

const TABS = [
  { value: 'all', label: 'All' },
  { value: 'unread', label: 'Unread' },
  { value: 'critical', label: 'Critical' },
  { value: 'warning', label: 'Warnings' },
] as const satisfies readonly { value: Filter; label: string }[]

/** Bildirishnomalar — qo'ng'iroq panelidagi "View all" shu yerga olib keladi. */
export default function NotificationsPage() {
  const [filter, setFilter] = useState<Filter>('all')
  const [page, setPage] = useState(1)

  const query = useNotifications({
    page,
    page_size: 20,
    ...(filter === 'unread' ? { unread: true } : {}),
    ...(filter === 'critical' || filter === 'warning' ? { severity: filter } : {}),
  })

  const markRead = useMarkNotificationRead()
  const markAll = useMarkAllRead()

  const items = query.data?.items ?? []
  const total = query.data?.pagination.total ?? 0

  return (
    <>
      <SectionHeader
        title="Notifications"
        count={query.data ? <CountPill>{formatNumber(total)}</CountPill> : undefined}
        description="Failures, dead letters, webhook problems and quota warnings."
        actions={
          <Button
            variant="secondary"
            onClick={() => markAll.mutate()}
            disabled={markAll.isPending}
          >
            Mark all as read
          </Button>
        }
      />

      <Tabs
        aria-label="Filter notifications"
        items={TABS}
        value={filter}
        onChange={(value) => {
          setFilter(value)
          setPage(1)
        }}
      />

      {query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.isLoading ? (
        <SkeletonRows rows={6} columns="36px 1fr" />
      ) : items.length === 0 ? (
        <EmptyState
          icon="M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6zM10 20a2 2 0 0 0 4 0"
          title={filter === 'unread' ? 'No unread notifications' : 'Nothing here yet'}
          description={
            filter === 'unread'
              ? 'You are all caught up.'
              : 'Durabl will tell you when a job fails, a webhook breaks or a worker goes down.'
          }
          tone="positive"
        />
      ) : (
        <div className="flex flex-col gap-2">
          {items.map((notification) => (
            <NotificationItem
              key={notification.id}
              notification={notification}
              onOpen={(id) => markRead.mutate(id)}
            />
          ))}
        </div>
      )}

      {query.data && query.data.pagination.total_pages > 1 ? (
        <Pagination pagination={query.data.pagination} onPageChange={setPage} />
      ) : null}
    </>
  )
}
