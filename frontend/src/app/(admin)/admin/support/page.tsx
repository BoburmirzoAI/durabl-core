'use client'

import Link from 'next/link'
import { useMemo, useState } from 'react'

import { DetailDrawer, DrawerRow, DrawerSection } from '@/components/common/DetailDrawer'
import { ErrorState } from '@/components/common/ErrorState'
import { RelativeTime } from '@/components/common/RelativeTime'
import { CountPill, SectionHeader } from '@/components/common/SectionHeader'
import { StatCard } from '@/components/analytics/KpiCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { SearchField } from '@/components/ui/input'
import { SkeletonRows } from '@/components/ui/skeleton'
import { Tabs } from '@/components/ui/tabs'
import { useReplyToTicket, useTickets, useUpdateTicket } from '@/lib/hooks/useAdminOps'
import { useDebounce } from '@/lib/hooks/useDebounce'
import { useSearchFocus } from '@/lib/hooks/useKeyboard'
import { cn } from '@/lib/utils/cn'
import { formatNumber } from '@/lib/utils/format'
import { formatTimestamp } from '@/lib/utils/time'
import type { StatCardData, SupportTicket, TicketPriority, TicketStatus } from '@/types'

const GRID = 'minmax(220px,1.8fr) minmax(170px,1.1fr) 90px 92px 110px 110px'

/** Barqaror bo'sh ro'yxat — `useMemo` bog'liqligi beqaror bo'lmasligi uchun. */
const EMPTY_TICKETS: SupportTicket[] = []

const PRIORITY_CLASS: Record<TicketPriority, string> = {
  urgent: 'bg-failed/[0.14] text-failed',
  high: 'bg-pending/[0.14] text-pending',
  normal: 'bg-surface-4 text-fg-muted',
  low: 'bg-surface-3 text-fg-faint',
}

const STATUS_CLASS: Record<TicketStatus, string> = {
  open: 'bg-failed/[0.12] text-failed',
  pending: 'bg-pending/[0.12] text-pending',
  resolved: 'bg-success/[0.12] text-success',
  closed: 'bg-surface-4 text-fg-faint',
}

/** Birinchi javob maqsadi (daqiqa) — prioritetga bog'liq. */
const RESPONSE_TARGET: Record<TicketPriority, number> = {
  urgent: 30,
  high: 120,
  normal: 480,
  low: 1_440,
}

/**
 * Qo'llab-quvvatlash navbati.
 *
 * ## Nega "birinchi javob vaqti" asosiy ko'rsatkich
 *
 * Mijoz muammoning darhol hal bo'lishini kutmaydi — u JAVOBSIZLIKdan
 * asabiylashadi. Shuning uchun jadvalda tiketning umumiy yoshi emas,
 * birinchi javobgacha o'tgan vaqt ko'rsatiladi, va u prioritet
 * maqsadidan oshsa qizil bo'ladi.
 *
 * ## Nega job havolasi bor
 *
 * Shikoyatlarning yarmi aniq bir job haqida. Tiketdan to'g'ridan-to'g'ri
 * o'sha job'ning loglariga o'tish — javob berish vaqtini eng ko'p
 * qisqartiradigan narsa.
 */
export default function AdminSupportPage() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<'all' | TicketStatus>('all')
  const [detail, setDetail] = useState<SupportTicket | null>(null)
  const [reply, setReply] = useState('')
  const searchRef = useSearchFocus()

  const debounced = useDebounce(search, 300)
  const query = useTickets({
    search: debounced || undefined,
    status: status === 'all' ? undefined : [status],
    page: 1,
    page_size: 50,
  })

  const sendReply = useReplyToTicket()
  const update = useUpdateTicket()

  // Bo'sh massiv har renderde yangi havola bo'ladi va quyidagi `useMemo`
  // ni foydasiz qilib qo'yadi — modul darajasidagi doimiy ishlatiladi
  const rows = query.data?.items ?? EMPTY_TICKETS
  // Panel jadvaldagi joriy nusxani ko'rsatishi kerak
  const current = detail ? (rows.find((t) => t.id === detail.id) ?? detail) : null

  const cards: StatCardData[] = useMemo(() => {
    const open = rows.filter((t) => t.status === 'open')
    const awaiting = open.filter((t) => t.first_response_minutes === null)
    const breached = rows.filter(
      (t) =>
        t.first_response_minutes !== null &&
        t.first_response_minutes > RESPONSE_TARGET[t.priority],
    )
    const answered = rows.filter((t) => t.first_response_minutes !== null)
    const avg =
      answered.length === 0
        ? 0
        : Math.round(
            answered.reduce((sum, t) => sum + (t.first_response_minutes ?? 0), 0) / answered.length,
          )

    return [
      {
        label: 'Open tickets',
        value: String(open.length),
        trend: `${rows.length} total`,
        trend_direction: 'flat',
        trend_is_good: open.length === 0,
        sub: 'need an answer',
        is_alert: open.length > 3,
      },
      {
        label: 'Waiting for first reply',
        value: String(awaiting.length),
        trend: awaiting.length > 0 ? 'nobody has answered' : 'all answered',
        trend_direction: awaiting.length > 0 ? 'up' : 'flat',
        trend_is_good: awaiting.length === 0,
        sub: 'the metric customers feel',
        is_alert: awaiting.length > 0,
      },
      {
        label: 'Avg first response',
        value: avg >= 60 ? `${Math.round(avg / 60)}h` : `${avg}m`,
        trend: `${answered.length} answered`,
        trend_direction: 'flat',
        trend_is_good: true,
        sub: 'across answered tickets',
      },
      {
        label: 'Past target',
        value: String(breached.length),
        trend: breached.length > 0 ? 'response target missed' : 'within target',
        trend_direction: breached.length > 0 ? 'up' : 'flat',
        trend_is_good: breached.length === 0,
        sub: 'by priority target',
        is_alert: breached.length > 0,
      },
    ]
  }, [rows])

  return (
    <>
      <SectionHeader
        title="Support"
        description="Customer tickets, newest activity first"
        count={
          query.data ? <CountPill>{formatNumber(query.data.pagination.total)}</CountPill> : null
        }
      />

      <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
        {query.data
          ? cards.map((card) => <StatCard key={card.label} data={card} />)
          : Array.from({ length: 4 }, (_, i) => (
              <StatCard
                key={i}
                loading
                data={{
                  label: '',
                  value: '',
                  trend: '',
                  trend_direction: 'flat',
                  trend_is_good: true,
                  sub: '',
                }}
              />
            ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Tabs
          aria-label="Ticket status"
          items={[
            { value: 'all' as const, label: 'All' },
            { value: 'open' as const, label: 'Open' },
            { value: 'pending' as const, label: 'Pending' },
            { value: 'resolved' as const, label: 'Resolved' },
            { value: 'closed' as const, label: 'Closed' },
          ]}
          value={status}
          onChange={setStatus}
        />
        <SearchField
          ref={searchRef}
          shortcut="/"
          placeholder="Search subject or customer…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          containerClassName="w-[300px]"
          aria-label="Search tickets"
        />
      </div>

      {query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <div className="overflow-hidden rounded-2xl border border-line bg-surface">
          <div className="overflow-x-auto">
            <div className="min-w-[860px]">
              <div
                className="table-head grid items-center gap-3 px-4"
                style={{ gridTemplateColumns: GRID }}
              >
                <span>Subject</span>
                <span>Customer</span>
                <span>Priority</span>
                <span>Status</span>
                <span>First reply</span>
                <span>Updated</span>
              </div>

              {query.isLoading && !query.data ? (
                <SkeletonRows rows={6} columns={GRID} />
              ) : (
                rows.map((ticket) => {
                  const target = RESPONSE_TARGET[ticket.priority]
                  const breached =
                    ticket.first_response_minutes !== null && ticket.first_response_minutes > target
                  const waiting = ticket.first_response_minutes === null
                  return (
                    <div
                      key={ticket.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => {
                        setDetail(ticket)
                        setReply('')
                      }}
                      onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault()
                          setDetail(ticket)
                          setReply('')
                        }
                      }}
                      className="grid min-h-[52px] cursor-pointer items-center gap-3 border-b border-line-subtle px-4 py-2 last:border-b-0 transition-colors hover:bg-surface-3 focus-visible:bg-surface-3 focus-visible:outline-none"
                      style={{ gridTemplateColumns: GRID }}
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-base text-fg-soft">
                          {ticket.subject}
                        </span>
                        <span className="block truncate text-2xs text-fg-faint">
                          {ticket.messages.length} message
                          {ticket.messages.length === 1 ? '' : 's'}
                          {ticket.related_job_id ? ' · linked to a job' : ''}
                        </span>
                      </span>

                      <span className="min-w-0">
                        <span className="block truncate text-sm text-fg-muted">
                          {ticket.user_email}
                        </span>
                        <span className="block truncate text-2xs text-fg-ghost">{ticket.plan}</span>
                      </span>

                      <span>
                        <Badge size="sm" className={PRIORITY_CLASS[ticket.priority]}>
                          {ticket.priority}
                        </Badge>
                      </span>

                      <span>
                        <Badge size="sm" className={STATUS_CLASS[ticket.status]}>
                          {ticket.status}
                        </Badge>
                      </span>

                      <span
                        className={cn(
                          'tabular font-mono text-xs',
                          waiting ? 'text-failed-text' : breached ? 'text-pending' : 'text-fg-faint',
                        )}
                      >
                        {waiting
                          ? 'no reply yet'
                          : (ticket.first_response_minutes as number) >= 60
                            ? `${Math.round((ticket.first_response_minutes as number) / 60)}h`
                            : `${ticket.first_response_minutes}m`}
                      </span>

                      <RelativeTime
                        value={ticket.updated_at}
                        className="truncate text-xs text-fg-ghost"
                      />
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </div>
      )}

      <DetailDrawer
        open={current !== null}
        onOpenChange={(open) => {
          if (!open) setDetail(null)
        }}
        width="lg"
        title={current?.subject ?? ''}
        description={current ? `${current.user_email} · ${current.plan}` : undefined}
        stats={
          current
            ? [
                { label: 'Status', value: current.status },
                { label: 'Priority', value: current.priority },
                {
                  label: 'First reply',
                  value:
                    current.first_response_minutes === null
                      ? 'none'
                      : `${current.first_response_minutes}m`,
                  tone:
                    current.first_response_minutes === null
                      ? 'bad'
                      : current.first_response_minutes > RESPONSE_TARGET[current.priority]
                        ? 'warn'
                        : 'good',
                },
                { label: 'Assignee', value: current.assignee ?? 'unassigned' },
              ]
            : undefined
        }
        footer={
          current ? (
            <div className="flex w-full flex-wrap items-center gap-2">
              <Button
                variant="ghost"
                disabled={update.isPending}
                onClick={() =>
                  update.mutate({
                    id: current.id,
                    patch: { status: current.status === 'resolved' ? 'open' : 'resolved' },
                  })
                }
              >
                {current.status === 'resolved' ? 'Reopen' : 'Mark resolved'}
              </Button>
              <Button
                variant="ghost"
                disabled={update.isPending}
                onClick={() =>
                  update.mutate({
                    id: current.id,
                    patch: { priority: current.priority === 'urgent' ? 'normal' : 'urgent' },
                  })
                }
              >
                {current.priority === 'urgent' ? 'Lower priority' : 'Mark urgent'}
              </Button>
              <Button
                variant="primary"
                className="ml-auto"
                disabled={reply.trim().length === 0 || sendReply.isPending}
                onClick={() =>
                  sendReply.mutate({ id: current.id, body: reply }, { onSuccess: () => setReply('') })
                }
              >
                {sendReply.isPending ? 'Sending…' : 'Send reply'}
              </Button>
            </div>
          ) : null
        }
      >
        {current ? (
          <div className="space-y-3.5">
            {current.related_job_id ? (
              <DrawerSection title="Linked job">
                <Link
                  href={`/jobs/${current.related_job_id}`}
                  className="font-mono text-sm text-accent hover:text-accent-light"
                >
                  {current.related_job_id} →
                </Link>
                <p className="mt-1.5 text-sm text-fg-dim">
                  Open the job to read its logs and attempts before replying.
                </p>
              </DrawerSection>
            ) : null}

            <DrawerSection title="Conversation">
              <div className="space-y-3">
                {current.messages.map((message) => (
                  <div
                    key={message.id}
                    className={cn(
                      'rounded-lg border px-3.5 py-3',
                      message.from_staff
                        ? 'border-accent-edge bg-accent-bar-2'
                        : 'border-line-inner bg-canvas-deep',
                    )}
                  >
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="text-sm font-medium text-fg-soft">{message.author}</span>
                      {message.from_staff ? (
                        <Badge size="sm" variant="outline">
                          staff
                        </Badge>
                      ) : null}
                      <span className="tabular ml-auto font-mono text-2xs text-fg-ghost">
                        {formatTimestamp(message.at).replace(' UTC', '')}
                      </span>
                    </div>
                    <p className="mt-1.5 text-sm leading-[1.6] text-fg-dim">{message.body}</p>
                  </div>
                ))}
              </div>
            </DrawerSection>

            <DrawerSection title="Reply">
              <textarea
                value={reply}
                onChange={(event) => setReply(event.target.value)}
                rows={5}
                placeholder="Answer the customer…"
                aria-label="Reply to the ticket"
                className="w-full resize-y rounded-lg border border-line bg-canvas-deep px-3 py-2.5 text-sm leading-[1.6] text-fg-soft outline-none transition-colors focus:border-accent-edge-2"
              />
              <p className="mt-1.5 text-xs text-fg-faint">
                Sending a reply moves an open ticket to pending and assigns it to you.
              </p>
            </DrawerSection>

            <DrawerSection title="Details">
              <DrawerRow label="Ticket" value={current.id} mono />
              <DrawerRow label="Customer" value={current.user_email} />
              <DrawerRow label="Plan" value={current.plan} />
              <DrawerRow label="Opened" value={formatTimestamp(current.created_at)} />
              <DrawerRow
                label="Response target"
                value={`${RESPONSE_TARGET[current.priority]} minutes (${current.priority})`}
              />
            </DrawerSection>
          </div>
        ) : null}
      </DetailDrawer>
    </>
  )
}
