/** Bildirishnoma endpointlari. */

import type { AppNotification, NotificationFilters, Paginated } from '@/types'
import { allNotifications } from '@/lib/mock/notifications'

import { mockResponse } from './client'
import { paginate } from './paginate'

/** `GET /api/v1/notifications` */
export async function listNotifications(
  filters: NotificationFilters = {},
): Promise<Paginated<AppNotification>> {
  return mockResponse(() => {
    let items = allNotifications()
    if (filters.unread) items = items.filter((n) => !n.read)
    if (filters.severity) items = items.filter((n) => n.severity === filters.severity)
    return paginate(items, filters.page ?? 1, filters.page_size ?? 20)
  })
}

/** `GET /api/v1/notifications/unread-count` — qo'ng'iroq nishoni uchun. */
export async function getUnreadCount(): Promise<{ count: number }> {
  return mockResponse(() => ({ count: allNotifications().filter((n) => !n.read).length }), 120)
}

/** `POST /api/v1/notifications/{id}/read` */
export async function markRead(id: string): Promise<{ id: string; read: boolean }> {
  return mockResponse(() => ({ id, read: true }), 180)
}

/** `POST /api/v1/notifications/read-all` */
export async function markAllRead(): Promise<{ updated: number }> {
  return mockResponse(() => ({ updated: allNotifications().filter((n) => !n.read).length }), 260)
}
