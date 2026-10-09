'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { RelativeTime } from '@/components/common/RelativeTime'
import { Sheet, SheetBody, SheetContent, SheetFooter, SheetHeader } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { useAdminUser } from '@/lib/hooks/useAdmin'
import { formatNumber } from '@/lib/utils/format'
import { formatTimestamp } from '@/lib/utils/time'
import { cn } from '@/lib/utils/cn'
import type { AdminUser, PlanType } from '@/types'

const PLAN_BADGE: Record<PlanType, string> = {
  free: 'bg-surface-3 text-fg-muted',
  starter: 'bg-running/[0.12] text-running',
  pro: 'bg-accent/[0.14] text-accent-light',
  enterprise: 'bg-success/[0.12] text-success',
}

/** Foydalanuvchi tafsiloti — jadval kontekstini yo'qotmasdan ko'rish uchun. */
export function UserDetailSheet({
  userId,
  onOpenChange,
  onViewJobs,
  onImpersonate,
  onOpenFullPage,
}: {
  userId: string | null
  onOpenChange: (open: boolean) => void
  onViewJobs: (user: AdminUser) => void
  onImpersonate: (user: AdminUser) => void
  /**
   * To'liq profil sahifasiga o'tish.
   *
   * Bu panel TEZKOR ko'rinish: "bu kim?" degan savolga javob beradi.
   * Qolgan hamma narsa — job'lar, DLQ, kalitlar, hisob tarixi — alohida
   * sahifada, chunki ularni panelga sig'dirib bo'lmaydi va havolasini
   * hamkasbga yuborish kerak bo'ladi.
   */
  onOpenFullPage?: (user: AdminUser) => void
}) {
  const query = useAdminUser(userId)
  const user = query.data

  return (
    <Sheet open={userId !== null} onOpenChange={onOpenChange}>
      <SheetContent aria-describedby={undefined}>
        <SheetHeader
          title={user?.email ?? 'Loading…'}
          description={user ? (user.full_name ?? 'No name set') : undefined}
        />

        <SheetBody>
          {query.isLoading || !user ? (
            <div className="space-y-3">
              {Array.from({ length: 5 }, (_, i) => (
                <Skeleton key={i} className="h-16 w-full" />
              ))}
            </div>
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Badge className={PLAN_BADGE[user.plan]}>{user.plan}</Badge>
                {user.is_admin ? <Badge variant="danger">admin</Badge> : null}
                <Badge variant={user.is_active ? 'outline' : 'danger'}>
                  {user.is_active ? 'active' : 'suspended'}
                </Badge>
              </div>

              <Section title="Usage this period">
                <Stat label="Jobs" value={formatNumber(user.jobs_this_period)} />
                <Stat label="Jobs all-time" value={formatNumber(user.job_count)} />
                <Stat
                  label="DLQ depth"
                  value={String(user.dlq_depth)}
                  tone={user.dlq_depth > 0 ? 'bad' : 'neutral'}
                />
                <Stat label="API keys" value={String(user.api_key_count)} />
              </Section>

              <Section title="Account">
                <Row label="User ID" value={<code className="font-mono text-xs">{user.id}</code>} />
                <Row label="Email" value={user.email} />
                <Row label="Name" value={user.full_name ?? '—'} />
                <Row
                  label="Created"
                  value={formatTimestamp(user.created_at)}
                />
                <Row
                  label="Last login"
                  value={
                    user.last_login_at ? (
                      <RelativeTime value={user.last_login_at} />
                    ) : (
                      <span className="text-fg-faint">never</span>
                    )
                  }
                />
              </Section>
            </>
          )}
        </SheetBody>

        <SheetFooter>
          {onOpenFullPage ? (
            <Button
              variant="secondary"
              disabled={!user}
              onClick={() => user && onOpenFullPage(user)}
            >
              Full profile →
            </Button>
          ) : null}
          <Button
            variant="secondary"
            disabled={!user}
            onClick={() => user && onViewJobs(user)}
          >
            View their jobs
          </Button>
          <Button
            variant="primary"
            disabled={!user || user.is_admin}
            onClick={() => user && onImpersonate(user)}
          >
            View as user
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">{title}</div>
      <div className="mt-3 space-y-2.5">{children}</div>
    </div>
  )
}

function Stat({
  label,
  value,
  tone = 'neutral',
}: {
  label: string
  value: string
  tone?: 'neutral' | 'bad'
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-sm text-fg-dim">{label}</span>
      <span
        className={cn(
          'tabular font-mono text-base',
          tone === 'bad' ? 'text-failed' : 'text-fg-soft',
        )}
      >
        {value}
      </span>
    </div>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="shrink-0 text-sm text-fg-dim">{label}</span>
      <span className="min-w-0 truncate text-right text-sm text-fg-soft">{value}</span>
    </div>
  )
}
