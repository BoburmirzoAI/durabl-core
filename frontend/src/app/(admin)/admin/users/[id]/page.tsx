'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { ErrorState } from '@/components/common/ErrorState'
import { SectionHeader } from '@/components/common/SectionHeader'
import { RelativeTime } from '@/components/common/RelativeTime'
import { CreditAdjustDialog } from '@/components/admin/CreditAdjustDialog'
import { DrilldownChart } from '@/components/common/DrilldownChart'
import { JobStatusBadge } from '@/components/jobs/JobStatusBadge'
import { StatCard } from '@/components/analytics/KpiCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs } from '@/components/ui/tabs'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  useAdminUserDetail,
  useChangeUserPlan,
  useReactivateUser,
  useResetUserKeys,
  useSetAdminUserNote,
  useSuspendUser,
} from '@/lib/hooks/useAdmin'
import { useImpersonationStore } from '@/stores/impersonationStore'
import { cn } from '@/lib/utils/cn'
import { formatCurrency, formatDuration, formatNumber } from '@/lib/utils/format'
import { customRange, formatDate, formatTimestamp } from '@/lib/utils/time'
import { PLAN_TYPES, type AdminUserDetail, type PlanType, type StatCardData } from '@/types'

type TabValue = 'overview' | 'jobs' | 'dlq' | 'keys' | 'webhooks' | 'billing' | 'activity'

const TABS = [
  { value: 'overview' as TabValue, label: 'Overview' },
  { value: 'jobs' as TabValue, label: 'Jobs' },
  { value: 'dlq' as TabValue, label: 'Dead letters' },
  { value: 'keys' as TabValue, label: 'API keys' },
  { value: 'webhooks' as TabValue, label: 'Webhooks' },
  { value: 'billing' as TabValue, label: 'Billing' },
  { value: 'activity' as TabValue, label: 'Activity' },
]

const PLAN_BADGE: Record<PlanType, string> = {
  free: 'bg-surface-3 text-fg-muted',
  starter: 'bg-running/[0.12] text-running',
  pro: 'bg-accent/[0.14] text-accent-light',
  enterprise: 'bg-success/[0.12] text-success',
}

/**
 * Admin — bitta foydalanuvchining TO'LIQ ko'rinishi.
 *
 * ═══════════════════════════════════════════════════════════════════
 * NEGA SLIDE-OVER YETARLI EMAS
 * ═══════════════════════════════════════════════════════════════════
 *
 * `UserDetailSheet` "bu kim?" degan savolga javob beradi — tezkor
 * ko'rinish, jadval kontekstini yo'qotmasdan.
 *
 * Lekin qo'llab-quvvatlash chaqiruvi kelganda savol boshqacha: "nega
 * uning job'lari yiqilyapti?", "qaysi kaliti ishlatilgan?", "o'tgan oy
 * nega bu qadar pul to'lagan?". Bularga javob berish uchun BARCHA
 * ma'lumot bir joyda, tablar bilan ajratilgan holda bo'lishi kerak —
 * va havolasini hamkasbga yuborish mumkin bo'lishi kerak.
 *
 * Shuning uchun bu alohida sahifa, URL'i bor.
 */
export default function AdminUserPage({ params }: { params: { id: string } }) {
  const id = params.id
  const router = useRouter()
  const query = useAdminUserDetail(id)
  const [tab, setTab] = useState<TabValue>('overview')
  const [creditFor, setCreditFor] = useState(false)
  const [confirmSuspend, setConfirmSuspend] = useState(false)
  const [confirmResetKeys, setConfirmResetKeys] = useState(false)

  const suspend = useSuspendUser()
  const reactivate = useReactivateUser()
  const changePlan = useChangeUserPlan()
  const resetKeys = useResetUserKeys()
  const startImpersonation = useImpersonationStore((s) => s.start)

  const detail = query.data
  const user = detail?.user

  if (query.error) {
    return (
      <>
        <SectionHeader title="User" description={id} />
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      </>
    )
  }

  const cards: StatCardData[] = detail
    ? [
        {
          label: 'Jobs this period',
          value: formatNumber(detail.user.jobs_this_period),
          trend: `${formatNumber(detail.user.job_count)} all time`,
          trend_direction: 'flat',
          trend_is_good: true,
          sub: 'counted against the plan',
        },
        {
          label: 'Dead letters',
          value: String(detail.user.dlq_depth),
          trend: detail.user.dlq_depth > 0 ? 'needs attention' : 'clean',
          trend_direction: detail.user.dlq_depth > 0 ? 'up' : 'flat',
          trend_is_good: detail.user.dlq_depth === 0,
          sub: 'unresolved failures',
          is_alert: detail.user.dlq_depth > 0,
        },
        {
          label: 'Balance',
          value: formatCurrency(detail.balance_usd),
          trend:
            detail.credit_balance_usd > 0
              ? `${formatCurrency(detail.credit_balance_usd)} credit`
              : 'no credit',
          trend_direction: 'flat',
          trend_is_good: true,
          sub: 'current period',
        },
        {
          label: 'API keys',
          value: String(detail.keys.filter((k) => k.is_active).length),
          trend: `${detail.keys.length} total`,
          trend_direction: 'flat',
          trend_is_good: true,
          sub: 'active credentials',
        },
      ]
    : []

  return (
    <>
      <SectionHeader
        title={user?.email ?? 'Loading…'}
        count={
          user ? (
            <span className="flex flex-wrap items-center gap-2">
              <Badge className={PLAN_BADGE[user.plan]}>{user.plan}</Badge>
              {user.is_admin ? <Badge variant="danger">admin</Badge> : null}
              {!user.is_active ? <Badge variant="danger">suspended</Badge> : null}
            </span>
          ) : null
        }
        description={
          user
            ? `${user.full_name ?? 'No name set'} · joined ${formatDate(user.created_at)} · ${user.id}`
            : id
        }
        actions={
          <>
            <Button variant="ghost" asChild>
              <Link href="/admin/users">← All users</Link>
            </Button>
            <Button variant="secondary" disabled={!user} onClick={() => setCreditFor(true)}>
              Adjust balance
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="secondary" disabled={!user}>
                  Actions ▾
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuItem
                  disabled={!user || user.is_admin}
                  onSelect={() => {
                    if (!user) return
                    startImpersonation(user)
                    router.push('/dashboard')
                  }}
                >
                  View as this user
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => router.push(`/admin/jobs?user=${encodeURIComponent(user?.email ?? '')}`)}
                >
                  Open their jobs in admin
                </DropdownMenuItem>
                {PLAN_TYPES.filter((plan) => plan !== user?.plan).map((plan) => (
                  <DropdownMenuItem
                    key={plan}
                    disabled={changePlan.isPending}
                    onSelect={() => user && changePlan.mutate({ id: user.id, plan })}
                  >
                    Move to {plan}
                  </DropdownMenuItem>
                ))}
                <DropdownMenuItem
                  danger
                  disabled={!user || user.api_key_count === 0}
                  onSelect={() => setConfirmResetKeys(true)}
                >
                  Revoke all API keys
                </DropdownMenuItem>
                <DropdownMenuItem
                  danger
                  disabled={!user || user.is_admin}
                  onSelect={() => {
                    if (!user) return
                    if (user.is_active) setConfirmSuspend(true)
                    else reactivate.mutate(user.id)
                  }}
                >
                  {user?.is_active ? 'Suspend account' : 'Reactivate account'}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        }
      />

      {!user ? (
        <>
          <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <Card key={i} className="p-4">
                <Skeleton className="h-3 w-24" />
                <Skeleton className="mt-3 h-6 w-20" />
              </Card>
            ))}
          </div>
          <Card className="p-4">
            <Skeleton className="h-64 w-full" />
          </Card>
        </>
      ) : (
        <>
          {!user.is_active ? (
            <div className="rounded-xl border border-failed/25 bg-failed/[0.07] px-4 py-3 text-sm leading-[1.55] text-failed-text">
              This account is suspended. Job submissions are rejected and every API key returns 401.
              Existing data is retained.
            </div>
          ) : null}

          <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
            {cards.map((card) => (
              <StatCard key={card.label} data={card} />
            ))}
          </div>

          <Tabs aria-label="User sections" items={TABS} value={tab} onChange={setTab} />

          {tab === 'overview' ? <OverviewTab detail={detail as AdminUserDetail} /> : null}
          {tab === 'jobs' ? <JobsTab detail={detail as AdminUserDetail} /> : null}
          {tab === 'dlq' ? <DlqTab detail={detail as AdminUserDetail} /> : null}
          {tab === 'keys' ? <KeysTab detail={detail as AdminUserDetail} /> : null}
          {tab === 'webhooks' ? <WebhooksTab detail={detail as AdminUserDetail} /> : null}
          {tab === 'billing' ? (
            <BillingTab detail={detail as AdminUserDetail} onAdjust={() => setCreditFor(true)} />
          ) : null}
          {tab === 'activity' ? <ActivityTab detail={detail as AdminUserDetail} /> : null}
        </>
      )}

      <CreditAdjustDialog
        user={creditFor && user ? user : null}
        onOpenChange={(open) => {
          if (!open) setCreditFor(false)
        }}
      />

      <ConfirmDialog
        open={confirmSuspend}
        onOpenChange={setConfirmSuspend}
        title="Suspend this account?"
        description={`${user?.email} can no longer submit jobs and every API key starts returning 401. Running jobs are allowed to finish. This is reversible.`}
        confirmLabel="Suspend account"
        destructive
        pending={suspend.isPending}
        onConfirm={() => {
          if (user) suspend.mutate(user.id)
          setConfirmSuspend(false)
        }}
      />

      <ConfirmDialog
        open={confirmResetKeys}
        onOpenChange={setConfirmResetKeys}
        title="Revoke every API key?"
        description={`All ${user?.api_key_count ?? 0} keys for ${user?.email} stop working immediately. Any integration using them breaks until new keys are issued. Use this when a key has leaked.`}
        confirmLabel="Revoke all keys"
        destructive
        pending={resetKeys.isPending}
        onConfirm={() => {
          if (user) resetKeys.mutate(user.id)
          setConfirmResetKeys(false)
        }}
      />
    </>
  )
}

// ───────────────────────────────────────────────────────────────────────────
// Tablar
// ───────────────────────────────────────────────────────────────────────────

function OverviewTab({ detail }: { detail: AdminUserDetail }) {
  const router = useRouter()
  const setNote = useSetAdminUserNote()
  const [note, setNote_] = useState(detail.note ?? '')

  // Boshqa foydalanuvchiga o'tilganda eslatma almashishi kerak
  useEffect(() => {
    setNote_(detail.note ?? '')
  }, [detail.note, detail.user.id])

  return (
    <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1.5fr)_minmax(300px,1fr)]">
      <div className="space-y-4">
        <DrilldownChart
          title="Jobs per day"
          description="Last 30 days · click a day to open that day in admin jobs"
          points={detail.usage.map((d) => ({ label: d.date.slice(5), value: d.jobs, key: d.date }))}
          valueLabel="Jobs"
          height={200}
          // Kun bosilganda shu foydalanuvchining o'sha sutkadagi job'lari
          // ochiladi — aks holda grafik ostidagi tugmalar o'lik bo'lardi
          onSelect={(point) => {
            if (!point.key) return
            const start = new Date(`${point.key}T00:00:00.000Z`)
            const end = new Date(start.getTime() + 86_400_000 - 1)
            router.push(
              `/admin/jobs?user=${encodeURIComponent(detail.user.email)}&range=${encodeURIComponent(customRange(start, end))}`,
            )
          }}
        />

        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle className="text-md">Recent jobs</CardTitle>
            <CardDescription>The 12 most recent submissions</CardDescription>
          </CardHeader>
          <JobRows detail={detail} limit={6} />
        </Card>
      </div>

      <div className="space-y-4">
        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle className="text-md">Account</CardTitle>
          </CardHeader>
          <div className="divide-y divide-line-subtle px-4">
            <Row label="User ID" value={detail.user.id} mono />
            <Row label="Email" value={detail.user.email} />
            <Row label="Name" value={detail.user.full_name ?? '—'} />
            <Row label="Plan" value={detail.user.plan} />
            <Row label="Created" value={formatDate(detail.user.created_at)} />
            <Row
              label="Last login"
              value={
                detail.user.last_login_at ? (
                  <RelativeTime value={detail.user.last_login_at} />
                ) : (
                  'never'
                )
              }
            />
          </div>
        </Card>

        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle className="text-md">Internal note</CardTitle>
            <CardDescription>
              Visible to admins only. Never shown to the customer.
            </CardDescription>
          </CardHeader>
          <div className="space-y-2.5 p-4">
            <textarea
              value={note}
              onChange={(event) => setNote_(event.target.value)}
              rows={4}
              placeholder="Context a colleague would need on the next support call…"
              aria-label="Internal note"
              className="w-full resize-y rounded-lg border border-line bg-canvas-deep px-3 py-2.5 text-sm leading-[1.6] text-fg-soft outline-none transition-colors focus:border-accent-edge-2"
            />
            <Button
              variant="secondary"
              disabled={note === (detail.note ?? '') || setNote.isPending}
              onClick={() => setNote.mutate({ id: detail.user.id, note })}
            >
              {setNote.isPending ? 'Saving…' : 'Save note'}
            </Button>
          </div>
        </Card>
      </div>
    </div>
  )
}

function JobRows({ detail, limit }: { detail: AdminUserDetail; limit?: number }) {
  const rows = limit ? detail.jobs.slice(0, limit) : detail.jobs
  if (rows.length === 0) {
    return <p className="px-4 pb-4 text-sm text-fg-dim">This account has never submitted a job.</p>
  }
  return (
    <div className="divide-y divide-line-subtle">
      {rows.map((job) => (
        <Link
          key={job.id}
          href={`/jobs/${job.id}`}
          className="flex items-center gap-3 px-4 py-2.5 transition-colors hover:bg-surface-3"
        >
          <JobStatusBadge status={job.status} size="sm" />
          <code className="shrink-0 font-mono text-xs text-fg-muted">{job.id}</code>
          <span className="min-w-0 flex-1 truncate text-xs text-fg-faint">{job.runtime}</span>
          {job.attempts > 1 ? (
            <span className="shrink-0 text-2xs text-pending">{job.attempts} attempts</span>
          ) : null}
          <span className="tabular shrink-0 font-mono text-xs text-fg-faint">
            {formatDuration(job.duration_ms)}
          </span>
          <RelativeTime value={job.created_at} className="w-16 shrink-0 text-right text-xs text-fg-ghost" />
        </Link>
      ))}
    </div>
  )
}

function JobsTab({ detail }: { detail: AdminUserDetail }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">Jobs</CardTitle>
        <CardDescription>
          Everything this account has submitted recently. Click through for logs and attempts.
        </CardDescription>
      </CardHeader>
      <JobRows detail={detail} />
    </Card>
  )
}

function DlqTab({ detail }: { detail: AdminUserDetail }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">Dead letter queue</CardTitle>
        <CardDescription>
          Jobs that exhausted every retry. Replaying from here is the customer&apos;s call — do not
          retry on their behalf without asking.
        </CardDescription>
      </CardHeader>
      {detail.dlq.length === 0 ? (
        <p className="px-4 pb-4 text-sm text-fg-dim">Nothing in the dead letter queue.</p>
      ) : (
        <div className="divide-y divide-line-subtle">
          {detail.dlq.map((entry) => (
            <div key={entry.id} className="px-4 py-2.5">
              <div className="flex flex-wrap items-center gap-2.5">
                <Badge size="sm" variant="danger">
                  {entry.error_type}
                </Badge>
                <code className="font-mono text-xs text-fg-muted">{entry.job_id}</code>
                <span className="text-2xs text-fg-faint">{entry.retry_count} retries</span>
                <RelativeTime value={entry.failed_at} className="ml-auto text-xs text-fg-ghost" />
              </div>
              <p className="mt-1 font-mono text-xs leading-[1.6] text-fg-dim">{entry.last_error}</p>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

function KeysTab({ detail }: { detail: AdminUserDetail }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">API keys</CardTitle>
        <CardDescription>
          Admins never see the raw value — only the prefix. Revoking is done from the Actions menu.
        </CardDescription>
      </CardHeader>
      {detail.keys.length === 0 ? (
        <p className="px-4 pb-4 text-sm text-fg-dim">This account has no API keys.</p>
      ) : (
        <div className="divide-y divide-line-subtle">
          {detail.keys.map((key) => (
            <div key={key.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
              <span className="min-w-[120px] text-base text-fg-soft">{key.name}</span>
              <code className="font-mono text-xs text-fg-muted">{key.masked_key}</code>
              <Badge size="sm" variant={key.is_active ? 'success' : 'danger'}>
                {key.is_active ? 'active' : 'revoked'}
              </Badge>
              <span className="ml-auto text-xs text-fg-faint">
                created {formatDate(key.created_at)}
              </span>
              <RelativeTime
                value={key.last_used_at}
                className="w-20 text-right text-xs text-fg-ghost"
              />
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

function WebhooksTab({ detail }: { detail: AdminUserDetail }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">Webhooks</CardTitle>
        <CardDescription>
          A failing endpoint is the most common reason a customer says &quot;I never got
          notified&quot;.
        </CardDescription>
      </CardHeader>
      {detail.webhooks.length === 0 ? (
        <p className="px-4 pb-4 text-sm text-fg-dim">No webhook endpoints configured.</p>
      ) : (
        <div className="divide-y divide-line-subtle">
          {detail.webhooks.map((hook) => (
            <div key={hook.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
              <code className="min-w-0 flex-1 truncate font-mono text-xs text-fg-muted">
                {hook.url}
              </code>
              <Badge size="sm" variant={hook.is_active ? 'success' : 'danger'}>
                {hook.is_active ? 'active' : 'disabled'}
              </Badge>
              <span
                className={cn(
                  'tabular font-mono text-xs',
                  hook.success_rate >= 95 ? 'text-fg-muted' : 'text-failed-text',
                )}
              >
                {hook.success_rate}%
              </span>
              {hook.consecutive_failures > 0 ? (
                <span className="text-2xs text-failed-text">
                  {hook.consecutive_failures} failures in a row
                </span>
              ) : null}
              <RelativeTime
                value={hook.last_triggered_at}
                className="w-20 text-right text-xs text-fg-ghost"
              />
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

function BillingTab({
  detail,
  onAdjust,
}: {
  detail: AdminUserDetail
  onAdjust: () => void
}) {
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div className="flex flex-wrap items-start gap-4">
          <div>
            <CardTitle className="text-md">Balance history</CardTitle>
            <CardDescription>
              Every manual adjustment is attributed to the admin who made it.
            </CardDescription>
          </div>
          <Button variant="secondary" className="ml-auto" onClick={onAdjust}>
            Adjust balance
          </Button>
        </div>
      </CardHeader>

      <div className="flex flex-wrap gap-px bg-line-subtle">
        <div className="min-w-[160px] flex-1 bg-surface px-4 py-3">
          <div className="text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">
            Period balance
          </div>
          <div className="tabular mt-1.5 font-mono text-lg text-fg">
            {formatCurrency(detail.balance_usd)}
          </div>
        </div>
        <div className="min-w-[160px] flex-1 bg-surface px-4 py-3">
          <div className="text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">
            Credit on account
          </div>
          <div
            className={cn(
              'tabular mt-1.5 font-mono text-lg',
              detail.credit_balance_usd > 0 ? 'text-success' : 'text-fg',
            )}
          >
            {formatCurrency(detail.credit_balance_usd)}
          </div>
        </div>
      </div>

      <div className="divide-y divide-line-subtle">
        {detail.credits.map((entry) => (
          <div key={entry.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
            <span
              className={cn(
                'tabular w-20 shrink-0 font-mono text-sm',
                entry.amount_usd > 0 ? 'text-success' : 'text-failed-text',
              )}
            >
              {entry.amount_usd > 0 ? '+' : ''}
              {formatCurrency(entry.amount_usd)}
            </span>
            <Badge size="sm" variant="outline">
              {entry.kind}
            </Badge>
            <span className="min-w-0 flex-1 truncate text-sm text-fg-dim">{entry.reason}</span>
            <span className="shrink-0 text-xs text-fg-faint">{entry.actor}</span>
            <span className="tabular w-[150px] shrink-0 text-right font-mono text-xs text-fg-ghost">
              {formatTimestamp(entry.at).replace(' UTC', '')}
            </span>
          </div>
        ))}
      </div>
    </Card>
  )
}

function ActivityTab({ detail }: { detail: AdminUserDetail }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">Activity</CardTitle>
        <CardDescription>
          What happened on this account, and whether an admin or the customer did it.
        </CardDescription>
      </CardHeader>
      <div className="divide-y divide-line-subtle">
        {detail.activity.map((event) => (
          <div key={event.id} className="flex flex-wrap items-center gap-3 px-4 py-2.5">
            <span
              className={cn(
                'h-1.5 w-1.5 shrink-0 rounded-full',
                event.by_admin ? 'bg-failed' : 'bg-accent',
              )}
              aria-hidden
            />
            <code className="shrink-0 font-mono text-2xs text-fg-faint">{event.action}</code>
            <span className="min-w-0 flex-1 truncate text-sm text-fg-soft">{event.summary}</span>
            <span
              className={cn(
                'shrink-0 text-xs',
                event.by_admin ? 'text-failed-text' : 'text-fg-faint',
              )}
            >
              {event.actor}
            </span>
            <span className="tabular w-[150px] shrink-0 text-right font-mono text-xs text-fg-ghost">
              {formatTimestamp(event.at).replace(' UTC', '')}
            </span>
          </div>
        ))}
      </div>
    </Card>
  )
}

function Row({
  label,
  value,
  mono = false,
}: {
  label: string
  value: React.ReactNode
  mono?: boolean
}) {
  return (
    <div className="flex items-baseline justify-between gap-3 py-2.5">
      <span className="shrink-0 text-sm text-fg-dim">{label}</span>
      <span
        className={cn('min-w-0 truncate text-right text-sm text-fg-soft', mono && 'font-mono text-xs')}
      >
        {value}
      </span>
    </div>
  )
}
