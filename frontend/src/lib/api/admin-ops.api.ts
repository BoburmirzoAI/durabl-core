/** Admin operatsion endpointlari: audit, billing, e'lonlar, tiketlar. */

import type {
  Announcement,
  AnnouncementInput,
  AuditEntry,
  AuditFilters,
  Paginated,
  PlanWorkload,
  PlatformBilling,
  PlatformDlq,
  PlatformExecutions,
  PlatformWebhooks,
  SupportTicket,
  TicketFilters,
  TicketPriority,
  TicketStatus,
} from '@/types'
import {
  allAnnouncements,
  allAuditEntries,
  allTickets,
  announcementStore,
  planWorkload,
  platformBilling,
  platformDlq,
  platformExecutions,
  platformWebhooks,
  ticketStore,
} from '@/lib/mock/admin-ops'
import { Rng } from '@/lib/mock/seed'

import { ApiError, mockResponse, notFound } from './client'
import { DEFAULT_PAGE_SIZE, filterByAny, paginate, searchIn, sortBy } from './paginate'

// ───────────────────────────────────────────────────────────────────────────
// Audit
// ───────────────────────────────────────────────────────────────────────────

/** `GET /api/v1/admin/audit` */
export async function getAuditLog(filters: AuditFilters = {}): Promise<Paginated<AuditEntry>> {
  return mockResponse(() => {
    let rows = allAuditEntries()
    rows = searchIn(rows, filters.search, ['action', 'actor', 'target', 'summary'])
    rows = filterByAny(rows, filters.category, (e) => e.category)
    rows = filterByAny(rows, filters.result, (e) => e.result)
    if (filters.actor) rows = rows.filter((e) => e.actor === filters.actor)
    rows = sortBy(rows, filters.sort_by ?? 'at', filters.sort_order ?? 'desc')
    return paginate(rows, filters.page ?? 1, filters.page_size ?? DEFAULT_PAGE_SIZE)
  }, 340)
}

// ───────────────────────────────────────────────────────────────────────────
// Billing
// ───────────────────────────────────────────────────────────────────────────

/** `GET /api/v1/admin/billing` */
export async function getPlatformBilling(): Promise<PlatformBilling> {
  return mockResponse(() => platformBilling(), 420)
}

// ───────────────────────────────────────────────────────────────────────────
// E'lonlar
// ───────────────────────────────────────────────────────────────────────────

/** `GET /api/v1/admin/announcements` */
export async function getAnnouncements(): Promise<Announcement[]> {
  return mockResponse(() => allAnnouncements(), 300)
}

/** `POST /api/v1/admin/announcements` */
export async function createAnnouncement(input: AnnouncementInput): Promise<Announcement> {
  return mockResponse(() => {
    if (input.title.trim().length === 0) {
      throw new ApiError({ status: 422, code: 'TITLE_REQUIRED', message: 'A title is required' })
    }
    if (input.body.trim().length === 0) {
      throw new ApiError({ status: 422, code: 'BODY_REQUIRED', message: 'A message is required' })
    }
    if (input.ends_at && new Date(input.ends_at) <= new Date(input.starts_at)) {
      throw new ApiError({
        status: 422,
        code: 'INVALID_WINDOW',
        message: 'The end time must be after the start time',
      })
    }
    const rng = new Rng(Date.now() % 800_011)
    const starts = new Date(input.starts_at).getTime()
    const announcement: Announcement = {
      id: `ann_${rng.hex(10)}`,
      ...input,
      title: input.title.trim(),
      body: input.body.trim(),
      // Boshlanish vaqti o'tib ketgan bo'lsa darhol jonli bo'ladi
      status: starts <= Date.now() ? 'live' : 'scheduled',
      created_by: 'admin@durabl.dev',
      created_at: new Date().toISOString(),
      seen_by: 0,
    }
    announcementStore.insert(announcement)
    return announcement
  }, 520)
}

/**
 * `PUT /api/v1/admin/announcements/{id}/status`
 *
 * E'lonni to'xtatish — hodisa tugaganda eng ko'p ishlatiladigan amal.
 * Shuning uchun u alohida endpoint, to'liq tahrirlashdan ajratilgan.
 */
export async function setAnnouncementStatus(
  id: string,
  status: Announcement['status'],
): Promise<Announcement> {
  return mockResponse(() => {
    const announcement = allAnnouncements().find((a) => a.id === id)
    if (!announcement) throw notFound('Announcement', id)
    return (
      announcementStore.update(id, {
        status,
        ends_at: status === 'ended' ? new Date().toISOString() : announcement.ends_at,
      }) ?? announcement
    )
  }, 380)
}

/** `DELETE /api/v1/admin/announcements/{id}` */
export async function deleteAnnouncement(id: string): Promise<{ deleted: boolean }> {
  return mockResponse(() => {
    const announcement = allAnnouncements().find((a) => a.id === id)
    if (!announcement) throw notFound('Announcement', id)
    if (announcement.status === 'live') {
      throw new ApiError({
        status: 409,
        code: 'ANNOUNCEMENT_LIVE',
        message: 'End the announcement before deleting it',
      })
    }
    announcementStore.remove(id)
    return { deleted: true }
  }, 380)
}

// ───────────────────────────────────────────────────────────────────────────
// Tiketlar
// ───────────────────────────────────────────────────────────────────────────

/** `GET /api/v1/admin/tickets` */
export async function getTickets(filters: TicketFilters = {}): Promise<Paginated<SupportTicket>> {
  return mockResponse(() => {
    let rows = allTickets()
    rows = searchIn(rows, filters.search, ['subject', 'user_email'])
    rows = filterByAny(rows, filters.status, (t) => t.status)
    rows = filterByAny(rows, filters.priority, (t) => t.priority)
    rows = sortBy(rows, filters.sort_by ?? 'updated_at', filters.sort_order ?? 'desc')
    return paginate(rows, filters.page ?? 1, filters.page_size ?? DEFAULT_PAGE_SIZE)
  }, 340)
}

/** `POST /api/v1/admin/tickets/{id}/reply` */
export async function replyToTicket(id: string, body: string): Promise<SupportTicket> {
  return mockResponse(() => {
    const ticket = allTickets().find((t) => t.id === id)
    if (!ticket) throw notFound('Ticket', id)
    if (body.trim().length === 0) {
      throw new ApiError({ status: 422, code: 'EMPTY_REPLY', message: 'The reply cannot be empty' })
    }
    const rng = new Rng(Date.now() % 700_001)
    const now = new Date()
    const messages = [
      ...ticket.messages,
      {
        id: `msg_${rng.hex(8)}`,
        at: now.toISOString(),
        author: 'admin@durabl.dev',
        from_staff: true,
        body: body.trim(),
      },
    ]
    return (
      ticketStore.update(id, {
        messages,
        // Birinchi javob vaqti FAQAT bir marta yoziladi
        first_response_minutes:
          ticket.first_response_minutes ??
          Math.round((now.getTime() - new Date(ticket.created_at).getTime()) / 60_000),
        status: ticket.status === 'open' ? 'pending' : ticket.status,
        assignee: ticket.assignee ?? 'admin@durabl.dev',
        updated_at: now.toISOString(),
      }) ?? ticket
    )
  }, 480)
}

/** `PUT /api/v1/admin/tickets/{id}` */
export async function updateTicket(
  id: string,
  patch: { status?: TicketStatus; priority?: TicketPriority; assignee?: string | null },
): Promise<SupportTicket> {
  return mockResponse(() => {
    const ticket = allTickets().find((t) => t.id === id)
    if (!ticket) throw notFound('Ticket', id)
    return ticketStore.update(id, { ...patch, updated_at: new Date().toISOString() }) ?? ticket
  }, 360)
}

// ───────────────────────────────────────────────────────────────────────────
// Platforma agregatlari
// ───────────────────────────────────────────────────────────────────────────

/** `GET /api/v1/admin/executions/health` */
export async function getPlatformExecutions(): Promise<PlatformExecutions> {
  return mockResponse(() => platformExecutions(), 380)
}

/** `GET /api/v1/admin/dlq/summary` */
export async function getPlatformDlq(): Promise<PlatformDlq> {
  return mockResponse(() => platformDlq(), 360)
}

/** `GET /api/v1/admin/webhooks` */
export async function getPlatformWebhooks(): Promise<PlatformWebhooks> {
  return mockResponse(() => platformWebhooks(), 380)
}

/** `GET /api/v1/admin/analytics/by-plan` */
export async function getPlanWorkload(): Promise<PlanWorkload[]> {
  return mockResponse(() => planWorkload(), 320)
}
