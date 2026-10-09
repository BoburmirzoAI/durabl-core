'use client'

import { useState } from 'react'

import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { ErrorState } from '@/components/common/ErrorState'
import { SectionHeader } from '@/components/common/SectionHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Tabs } from '@/components/ui/tabs'
import {
  useAnnouncements,
  useCreateAnnouncement,
  useDeleteAnnouncement,
  useSetAnnouncementStatus,
} from '@/lib/hooks/useAdminOps'
import { cn } from '@/lib/utils/cn'
import { formatNumber } from '@/lib/utils/format'
import { formatTimestamp } from '@/lib/utils/time'
import { PLAN_TYPES, type Announcement, type AnnouncementLevel, type PlanType } from '@/types'

const LEVEL_CLASS: Record<AnnouncementLevel, string> = {
  info: 'border-accent-edge bg-accent-bar-2 text-fg-soft',
  warning: 'border-pending/25 bg-pending/[0.07] text-pending',
  critical: 'border-failed/25 bg-failed/[0.07] text-failed-text',
}

const STATUS_CLASS: Record<Announcement['status'], string> = {
  draft: 'bg-surface-4 text-fg-faint',
  scheduled: 'bg-running/[0.12] text-running',
  live: 'bg-success/[0.12] text-success',
  ended: 'bg-surface-3 text-fg-ghost',
}

/** `<input type="datetime-local">` uchun qiymat. */
function toLocalInput(ms: number): string {
  return new Date(ms - new Date().getTimezoneOffset() * 60_000).toISOString().slice(0, 16)
}

/**
 * Platforma e'lonlari.
 *
 * ═══════════════════════════════════════════════════════════════════
 * NEGA BANNER, EMAIL EMAS
 * ═══════════════════════════════════════════════════════════════════
 *
 * Hodisa paytida email eng yomon kanal: u kechikadi, spam'ga tushadi va
 * odam uni ertasi kuni o'qiydi. Banner esa mijoz MUAMMONI ko'rgan
 * daqiqada, aynan muammo ko'rinadigan joyda turadi.
 *
 * Shuning uchun `critical` darajadagi e'lon YOPILMAYDI: hodisa haqidagi
 * xabarni tasodifan yopib qo'yib, keyin qo'llab-quvvatlashga yozish —
 * ikkala tomon uchun ham vaqt yo'qotish.
 */
export default function AdminAnnouncementsPage() {
  const query = useAnnouncements()
  const create = useCreateAnnouncement()
  const setStatus = useSetAnnouncementStatus()
  const remove = useDeleteAnnouncement()

  const [composeOpen, setComposeOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<Announcement | null>(null)

  const [title, setTitle] = useState('')
  const [body, setBody] = useState('')
  const [level, setLevel] = useState<AnnouncementLevel>('info')
  const [audience, setAudience] = useState<PlanType[]>([])
  const [dismissible, setDismissible] = useState(true)
  const [startsAt, setStartsAt] = useState(() => toLocalInput(Date.now()))
  const [endsAt, setEndsAt] = useState('')

  const live = (query.data ?? []).filter((a) => a.status === 'live')

  const resetForm = (): void => {
    setTitle('')
    setBody('')
    setLevel('info')
    setAudience([])
    setDismissible(true)
    setStartsAt(toLocalInput(Date.now()))
    setEndsAt('')
  }

  return (
    <>
      <SectionHeader
        title="Announcements"
        description="Banners shown inside the product to some or all customers"
        count={<Badge variant="danger">ADMIN</Badge>}
        actions={
          <Button
            variant="primary"
            size="md"
            onClick={() => {
              resetForm()
              setComposeOpen(true)
            }}
          >
            New announcement
          </Button>
        }
      />

      {live.length > 0 ? (
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle className="text-md">Live right now</CardTitle>
            <CardDescription>This is exactly what customers see</CardDescription>
          </CardHeader>
          <div className="space-y-2.5 p-4">
            {live.map((announcement) => (
              <div
                key={announcement.id}
                className={cn('rounded-xl border px-4 py-3', LEVEL_CLASS[announcement.level])}
              >
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-base font-medium">{announcement.title}</span>
                  {!announcement.dismissible ? (
                    <span className="rounded border border-current/25 px-1.5 py-px text-2xs opacity-80">
                      cannot be dismissed
                    </span>
                  ) : null}
                </div>
                <p className="mt-1 text-sm leading-[1.6] opacity-85">{announcement.body}</p>
              </div>
            ))}
          </div>
        </Card>
      ) : null}

      {query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : query.isLoading && !query.data ? (
        <Card className="p-4">
          <Skeleton className="h-48 w-full" />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle className="text-md">All announcements</CardTitle>
          </CardHeader>
          <div className="divide-y divide-line-subtle">
            {(query.data ?? []).map((announcement) => (
              <div key={announcement.id} className="flex flex-wrap items-start gap-4 px-4 py-3.5">
                <div className="min-w-[260px] flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge size="sm" className={STATUS_CLASS[announcement.status]}>
                      {announcement.status}
                    </Badge>
                    <Badge
                      size="sm"
                      variant={announcement.level === 'critical' ? 'danger' : 'outline'}
                    >
                      {announcement.level}
                    </Badge>
                    <span className="text-base text-fg-soft">{announcement.title}</span>
                  </div>
                  <p className="mt-1 text-sm leading-[1.55] text-fg-dim">{announcement.body}</p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-2xs text-fg-faint">
                    <span>
                      {announcement.audience.length === 0
                        ? 'everyone'
                        : announcement.audience.join(', ')}
                    </span>
                    <span>·</span>
                    <span>{formatTimestamp(announcement.starts_at).replace(' UTC', '')}</span>
                    {announcement.ends_at ? (
                      <>
                        <span>→</span>
                        <span>{formatTimestamp(announcement.ends_at).replace(' UTC', '')}</span>
                      </>
                    ) : (
                      <span className="text-pending">no end time</span>
                    )}
                    <span>·</span>
                    <span>seen by {formatNumber(announcement.seen_by)}</span>
                  </div>
                </div>

                <div className="flex shrink-0 flex-wrap items-center gap-2">
                  {announcement.status === 'live' ? (
                    <Button
                      variant="secondary"
                      size="sm"
                      disabled={setStatus.isPending}
                      onClick={() => setStatus.mutate({ id: announcement.id, status: 'ended' })}
                    >
                      End now
                    </Button>
                  ) : announcement.status === 'draft' || announcement.status === 'scheduled' ? (
                    <Button
                      variant="primary"
                      size="sm"
                      disabled={setStatus.isPending}
                      onClick={() => setStatus.mutate({ id: announcement.id, status: 'live' })}
                    >
                      Publish now
                    </Button>
                  ) : null}
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={announcement.status === 'live'}
                    title={
                      announcement.status === 'live' ? 'End the announcement first' : undefined
                    }
                    onClick={() => setConfirmDelete(announcement)}
                  >
                    Delete
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}

      <Dialog open={composeOpen} onOpenChange={setComposeOpen}>
        <DialogContent width="lg">
          <DialogHeader>
            <div>
              <DialogTitle>New announcement</DialogTitle>
              <DialogDescription>
                Shown as a banner inside the product. Keep it short and say what customers should do.
              </DialogDescription>
            </div>
          </DialogHeader>

          <DialogBody className="space-y-4">
            <label className="block">
              <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                Title
              </span>
              <Input
                autoFocus
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder="Scheduled maintenance on Sunday 02:00–04:00 UTC"
              />
            </label>

            <label className="block">
              <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                Message
              </span>
              <textarea
                value={body}
                onChange={(event) => setBody(event.target.value)}
                rows={4}
                placeholder="What is happening, what the impact is, and what the customer should do."
                aria-label="Announcement message"
                className="w-full resize-y rounded-lg border border-line bg-canvas-deep px-3 py-2.5 text-sm leading-[1.6] text-fg-soft outline-none transition-colors focus:border-accent-edge-2"
              />
            </label>

            <div>
              <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                Severity
              </span>
              <Tabs
                aria-label="Severity"
                items={[
                  { value: 'info' as AnnouncementLevel, label: 'Info' },
                  { value: 'warning' as AnnouncementLevel, label: 'Warning' },
                  { value: 'critical' as AnnouncementLevel, label: 'Critical' },
                ]}
                value={level}
                onChange={(value) => {
                  setLevel(value)
                  // Hodisa xabarini yopib bo'lmaydi — buni avtomatik qilamiz
                  if (value === 'critical') setDismissible(false)
                }}
              />
            </div>

            <div>
              <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                Audience
              </span>
              <div className="flex flex-wrap gap-3">
                {PLAN_TYPES.map((plan) => (
                  <label key={plan} className="flex cursor-pointer items-center gap-2">
                    <Checkbox
                      checked={audience.includes(plan)}
                      onToggle={() =>
                        setAudience((current) =>
                          current.includes(plan)
                            ? current.filter((p) => p !== plan)
                            : [...current, plan],
                        )
                      }
                      aria-label={plan}
                    />
                    <span className="text-sm capitalize text-fg-soft">{plan}</span>
                  </label>
                ))}
              </div>
              <p className="mt-1.5 text-xs text-fg-faint">
                {audience.length === 0
                  ? 'No plans selected — the announcement goes to everyone.'
                  : `Only ${audience.join(', ')} accounts see this.`}
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                  Starts
                </span>
                <input
                  type="datetime-local"
                  value={startsAt}
                  onChange={(event) => setStartsAt(event.target.value)}
                  aria-label="Start time"
                  className="h-[34px] w-full rounded-lg border border-line bg-canvas-deep px-2.5 font-mono text-sm text-fg-soft outline-none transition-colors focus:border-accent-edge-2"
                />
              </label>
              <label className="block">
                <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                  Ends (optional)
                </span>
                <input
                  type="datetime-local"
                  value={endsAt}
                  onChange={(event) => setEndsAt(event.target.value)}
                  aria-label="End time"
                  className="h-[34px] w-full rounded-lg border border-line bg-canvas-deep px-2.5 font-mono text-sm text-fg-soft outline-none transition-colors focus:border-accent-edge-2"
                />
              </label>
            </div>

            <div className="flex items-start justify-between gap-4 rounded-lg border border-line-inner bg-canvas-deep px-3.5 py-3">
              <div className="min-w-0">
                <div className="text-base text-fg-soft">Customers can dismiss it</div>
                <div className="mt-0.5 text-sm leading-[1.5] text-fg-faint">
                  Turn this off for incidents — a banner someone dismissed by accident becomes a
                  support ticket.
                </div>
              </div>
              <Switch
                checked={dismissible}
                onCheckedChange={setDismissible}
                aria-label="Dismissible"
              />
            </div>

            {/* Jonli ko'rinish — nashr qilishdan oldin aynan nimani ko'rishlari */}
            {title.trim() || body.trim() ? (
              <div>
                <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                  Preview
                </span>
                <div className={cn('rounded-xl border px-4 py-3', LEVEL_CLASS[level])}>
                  <div className="text-base font-medium">{title || 'Untitled announcement'}</div>
                  <p className="mt-1 text-sm leading-[1.6] opacity-85">
                    {body || 'The message body appears here.'}
                  </p>
                </div>
              </div>
            ) : null}
          </DialogBody>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setComposeOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="md"
              disabled={title.trim().length === 0 || body.trim().length === 0 || create.isPending}
              onClick={() =>
                create.mutate(
                  {
                    title,
                    body,
                    level,
                    audience,
                    dismissible,
                    starts_at: new Date(startsAt).toISOString(),
                    ends_at: endsAt ? new Date(endsAt).toISOString() : null,
                  },
                  { onSuccess: () => setComposeOpen(false) },
                )
              }
            >
              {create.isPending ? 'Publishing…' : 'Publish'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={confirmDelete !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmDelete(null)
        }}
        title="Delete announcement?"
        description={
          confirmDelete
            ? `"${confirmDelete.title}" is removed permanently. Customers who already saw it keep no record of it.`
            : ''
        }
        confirmLabel="Delete"
        destructive
        pending={remove.isPending}
        onConfirm={() => {
          if (confirmDelete) remove.mutate(confirmDelete.id)
          setConfirmDelete(null)
        }}
      />
    </>
  )
}
