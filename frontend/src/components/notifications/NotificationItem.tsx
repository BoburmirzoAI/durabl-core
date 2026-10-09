'use client'

import Link from 'next/link'

import { RelativeTime } from '@/components/common/RelativeTime'
import { cn } from '@/lib/utils/cn'
import type { AppNotification, NotificationKind, NotificationSeverity } from '@/types'

/**
 * Bitta bildirishnoma qatori.
 *
 * Havolasi bo'lsa `<Link>`, bo'lmasa oddiy `<div>` — bosib bo'lmaydigan
 * elementni havola qilib ko'rsatish foydalanuvchini chalg'itadi.
 */

/** Tur -> ikonka yo'li (bitta `path` ichida). */
const KIND_ICON: Record<NotificationKind, string> = {
  job_failed:
    'M12 8v5M12 16h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z',
  job_succeeded: 'M20 6 9 17l-5-5',
  dlq_entry: 'M3 6h18M8 6V4h8v2M6 6l1 14h10l1-14',
  webhook_failed: 'M13 2 3 14h9l-1 8 10-12h-9l1-8z',
  worker_down: 'M4 5h16v10H4zM8 19h8M12 15v4',
  quota_warning: 'M12 3v9l6 3M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18z',
  api_key_created: 'M10 13a5 5 0 1 1 5-5l6 6-2 2-2-2-2 2-2-2z',
  system: 'M12 16v-4M12 8h.01M12 21a9 9 0 1 1 0-18 9 9 0 0 1 0 18z',
}

/** Muhimlik -> rang. Dizayndagi status ranglari bilan bir xil oila. */
const SEVERITY_STYLE: Record<NotificationSeverity, { icon: string; ring: string }> = {
  critical: { icon: 'text-failed', ring: 'border-failed/25 bg-failed/[0.08]' },
  warning: { icon: 'text-pending', ring: 'border-pending/25 bg-pending/[0.08]' },
  info: { icon: 'text-accent-light', ring: 'border-accent/25 bg-accent/[0.08]' },
}

export function NotificationItem({
  notification,
  onOpen,
  compact = false,
}: {
  notification: AppNotification
  onOpen?: (id: string) => void
  /** Qo'ng'iroq panelida zichroq ko'rinish. */
  compact?: boolean
}) {
  const severity = SEVERITY_STYLE[notification.severity]

  const inner = (
    <>
      <span
        className={cn(
          'flex shrink-0 items-center justify-center rounded-lg border',
          compact ? 'h-7 w-7' : 'h-9 w-9',
          severity.ring,
        )}
      >
        <svg
          width={compact ? 14 : 16}
          height={compact ? 14 : 16}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
          className={severity.icon}
          aria-hidden
        >
          <path d={KIND_ICON[notification.kind]} />
        </svg>
      </span>

      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          <span
            className={cn(
              'truncate font-medium',
              compact ? 'text-sm' : 'text-base',
              notification.read ? 'text-fg-soft' : 'text-fg',
            )}
          >
            {notification.title}
          </span>
          {!notification.read ? (
            <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-accent" aria-label="Unread" />
          ) : null}
        </span>
        <span
          className={cn('mt-0.5 block text-fg-dim', compact ? 'line-clamp-2 text-xs' : 'text-sm')}
        >
          {notification.body}
        </span>
        <RelativeTime
          value={notification.created_at}
          className="mt-1 block text-xs text-fg-faint"
        />
      </span>
    </>
  )

  const base = cn(
    'flex w-full items-start gap-3 text-left transition-colors',
    compact ? 'rounded-lg px-2.5 py-2' : 'rounded-xl border border-line bg-surface px-3.5 py-3',
    !notification.read && !compact && 'border-accent/20 bg-accent/[0.03]',
    notification.href && 'hover:bg-surface-3',
  )

  if (!notification.href) {
    return <div className={base}>{inner}</div>
  }

  return (
    <Link href={notification.href} className={base} onClick={() => onOpen?.(notification.id)}>
      {inner}
    </Link>
  )
}
