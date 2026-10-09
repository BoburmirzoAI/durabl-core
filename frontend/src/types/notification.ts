/** Bildirishnomalar — panel qo'ng'irog'i va `/notifications` sahifasi uchun. */

import type { Id, IsoDateTime } from './common'

/** Bildirishnoma turi — ikonka va rangni belgilaydi. */
export type NotificationKind =
  | 'job_failed'
  | 'job_succeeded'
  | 'dlq_entry'
  | 'webhook_failed'
  | 'worker_down'
  | 'quota_warning'
  | 'api_key_created'
  | 'system'

/** Muhimlik darajasi — ro'yxatda filtrlash uchun. */
export type NotificationSeverity = 'info' | 'warning' | 'critical'

export interface AppNotification {
  id: Id
  kind: NotificationKind
  severity: NotificationSeverity
  title: string
  body: string
  created_at: IsoDateTime
  read: boolean
  /** Bosilganda qayerga olib boradi (`/jobs/job_0042`). Yo'q bo'lsa — havolasiz. */
  href: string | null
}

export interface NotificationFilters {
  /** Faqat o'qilmaganlar. */
  unread?: boolean
  severity?: NotificationSeverity
  page?: number
  page_size?: number
}
