'use client'

import Link from 'next/link'

import { NavIcon } from '@/components/layout/NavIcon'
import { NotificationItem } from '@/components/notifications/NotificationItem'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  useMarkAllRead,
  useMarkNotificationRead,
  useNotifications,
  useUnreadCount,
} from '@/lib/hooks/useNotifications'
import { cn } from '@/lib/utils/cn'

const PREVIEW_COUNT = 5

/**
 * Topbar qo'ng'irog'i.
 *
 * Ilgari bu tugmada `onClick` umuman yo'q edi — bosilganda hech narsa
 * bo'lmasdi. Endi oxirgi bildirishnomalarni ko'rsatadi va to'liq ro'yxatga
 * (`/notifications`) olib boradi.
 */
export function NotificationBell() {
  const unread = useUnreadCount()
  const recent = useNotifications({ page: 1, page_size: PREVIEW_COUNT })
  const markRead = useMarkNotificationRead()
  const markAll = useMarkAllRead()

  const count = unread.data?.count ?? 0
  const items = recent.data?.items ?? []

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={count > 0 ? `Notifications (${count} unread)` : 'Notifications'}
          className="relative flex h-8 w-8 items-center justify-center rounded-md border border-transparent text-fg-muted transition-colors hover:border-line hover:bg-surface-2 hover:text-fg"
        >
          <NavIcon
            path="M6 9a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6zM10 20a2 2 0 0 0 4 0"
            size={16}
            strokeWidth={1.7}
          />
          {count > 0 ? (
            <span
              className="absolute right-[7px] top-1.5 h-1.5 w-1.5 rounded-full border-[1.5px] border-canvas bg-failed"
              aria-hidden
            />
          ) : null}
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-[360px] max-w-[calc(100vw-24px)] p-0">
        <div className="flex items-center gap-2 border-b border-line-inner px-3 py-2.5">
          <span className="text-sm font-semibold text-fg">Notifications</span>
          {count > 0 ? (
            <span className="rounded-full bg-accent/[0.16] px-1.5 py-px font-mono text-2xs font-semibold text-accent-light">
              {count}
            </span>
          ) : null}
          <button
            type="button"
            onClick={() => markAll.mutate()}
            disabled={count === 0 || markAll.isPending}
            className={cn(
              'ml-auto text-xs transition-colors',
              count === 0 ? 'cursor-not-allowed text-fg-ghost' : 'text-fg-dim hover:text-fg',
            )}
          >
            Mark all read
          </button>
        </div>

        <div className="max-h-[340px] overflow-y-auto p-1.5">
          {recent.isLoading ? (
            <div className="px-2.5 py-6 text-center text-sm text-fg-faint">Loading…</div>
          ) : items.length === 0 ? (
            <div className="px-2.5 py-6 text-center text-sm text-fg-faint">
              You are all caught up.
            </div>
          ) : (
            items.map((notification) => (
              <NotificationItem
                key={notification.id}
                notification={notification}
                onOpen={(id) => markRead.mutate(id)}
                compact
              />
            ))
          )}
        </div>

        <div className="border-t border-line-inner px-3 py-2">
          <Link
            href="/notifications"
            className="block text-center text-sm text-accent-light transition-colors hover:text-accent-pale"
          >
            View all notifications
          </Link>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
