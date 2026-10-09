'use client'

import Link from 'next/link'
import { useState } from 'react'

import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { DrilldownChart } from '@/components/common/DrilldownChart'
import { ErrorState } from '@/components/common/ErrorState'
import { RelativeTime } from '@/components/common/RelativeTime'
import { SectionHeader } from '@/components/common/SectionHeader'
import { useToast } from '@/components/common/ToastProvider'
import { StatCard } from '@/components/analytics/KpiCard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { SkeletonRows } from '@/components/ui/skeleton'
import { usePlatformDlq } from '@/lib/hooks/useAdminOps'
import { usePurgeDlq } from '@/lib/hooks/useDlq'
import { cn } from '@/lib/utils/cn'
import { formatNumber } from '@/lib/utils/format'
import { formatTimestamp } from '@/lib/utils/time'
import type { StatCardData } from '@/types'

const GRID = 'minmax(200px,1.6fr) 90px 86px 92px minmax(130px,1fr) 110px'

/**
 * Admin — platforma DLQ'si, FOYDALANUVCHI bo'yicha.
 *
 * ═══════════════════════════════════════════════════════════════════
 * NEGA FOYDALANUVCHI BO'YICHA
 * ═══════════════════════════════════════════════════════════════════
 *
 * "Platformada 87 ta dead letter bor" — bu bilan hech narsa qilib
 * bo'lmaydi. Harakat qilish uchun kerakli savol: "qaysi MIJOZda
 * muammo?".
 *
 * Javob qarorni belgilaydi: bitta mijozda 60 ta bo'lsa — qo'ng'iroq
 * qilish kerak; 20 ta mijozda bittadan bo'lsa — bu normal shovqin.
 *
 * Admin DLQ'dan job'larni O'ZI qayta urinmaydi: bu mijozning kodi va
 * uning qarori. Shuning uchun bu yerda faqat HAL QILINGANLARNI tozalash
 * bor — ya'ni faqat axlatni yig'ish.
 */
export default function AdminDlqPage() {
  const query = usePlatformDlq()
  const purge = usePurgeDlq()
  const { toast } = useToast()
  const [confirmPurge, setConfirmPurge] = useState(false)
  const [errorFilter, setErrorFilter] = useState<string | null>(null)

  const data = query.data
  const rows = (data?.by_user ?? []).filter(
    (row) => errorFilter === null || row.top_error === errorFilter,
  )

  const cards: StatCardData[] = data
    ? [
        {
          label: 'Platform DLQ depth',
          value: formatNumber(data.depth),
          trend: `${data.by_user.length} account${data.by_user.length === 1 ? '' : 's'} affected`,
          trend_direction: 'flat',
          trend_is_good: data.depth === 0,
          sub: 'unresolved dead letters',
          is_alert: data.depth > 50,
        },
        {
          label: 'Added (24h)',
          value: formatNumber(data.added_24h),
          trend: `${formatNumber(data.resolved_24h)} resolved`,
          trend_direction: data.added_24h > data.resolved_24h ? 'up' : 'down',
          trend_is_good: data.added_24h <= data.resolved_24h,
          sub: 'growing or shrinking',
          is_alert: data.added_24h > data.resolved_24h * 2,
        },
        {
          label: 'Oldest entry',
          value: data.oldest_at
            ? `${Math.round((Date.now() - new Date(data.oldest_at).getTime()) / 86_400_000)}d`
            : '—',
          trend: data.oldest_at ? formatTimestamp(data.oldest_at).replace(' UTC', '') : 'none',
          trend_direction: 'flat',
          trend_is_good: !data.oldest_at,
          sub: 'nobody has looked at it',
        },
        {
          label: 'Worst account',
          value: formatNumber(data.by_user[0]?.depth ?? 0),
          trend: data.by_user[0]?.email ?? 'none',
          trend_direction: 'flat',
          trend_is_good: (data.by_user[0]?.depth ?? 0) === 0,
          sub: 'single largest backlog',
        },
      ]
    : []

  return (
    <>
      <SectionHeader
        title="Dead letters"
        description="Which customers are accumulating failures"
        count={<Badge variant="danger">ADMIN</Badge>}
        actions={
          <Button variant="secondary" onClick={() => setConfirmPurge(true)}>
            Purge resolved
          </Button>
        }
      />

      {query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
            {data
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

          {(data?.by_error.length ?? 0) > 0 ? (
            <DrilldownChart
              title="Error types across the platform"
              description={
                errorFilter
                  ? `Filtered: ${errorFilter} — click again to clear`
                  : 'Click a bar to filter the accounts below'
              }
              points={(data?.by_error ?? []).map((row) => ({
                label: row.error_type,
                value: row.count,
                key: row.error_type,
                tone: 'failed' as const,
              }))}
              valueLabel="Entries"
              height={180}
              selectedKey={errorFilter}
              loading={query.isLoading}
              onSelect={(point) =>
                setErrorFilter((current) => (current === point.key ? null : (point.key ?? null)))
              }
            />
          ) : null}

          <Card className="overflow-hidden">
            <CardHeader>
              <CardTitle className="text-md">By account</CardTitle>
              <CardDescription>
                Open an account to see the actual entries. Replaying is the customer&apos;s call —
                their code decides whether a retry is safe.
              </CardDescription>
            </CardHeader>

            <div className="overflow-x-auto">
              <div className="min-w-[800px]">
                <div
                  className="table-head grid items-center gap-3 px-4"
                  style={{ gridTemplateColumns: GRID }}
                >
                  <span>Account</span>
                  <span className="text-right">Depth</span>
                  <span className="text-right">New 24h</span>
                  <span>Plan</span>
                  <span>Top error</span>
                  <span>Oldest</span>
                </div>

                {query.isLoading && !data ? (
                  <SkeletonRows rows={6} columns={GRID} />
                ) : rows.length === 0 ? (
                  <p className="px-4 py-6 text-center text-sm text-fg-dim">
                    {errorFilter
                      ? 'No accounts match that error type.'
                      : 'No account has dead letters right now.'}
                  </p>
                ) : (
                  rows.map((row) => (
                    <Link
                      key={row.user_id}
                      href={`/admin/users/${row.user_id}`}
                      className="grid min-h-[48px] items-center gap-3 border-b border-line-subtle px-4 py-2 last:border-b-0 transition-colors hover:bg-surface-3"
                      style={{ gridTemplateColumns: GRID }}
                    >
                      <span className="truncate text-sm text-fg-soft">{row.email}</span>
                      <span
                        className={cn(
                          'tabular text-right font-mono text-sm',
                          row.depth > 8 ? 'text-failed' : 'text-fg-muted',
                        )}
                      >
                        {row.depth}
                      </span>
                      <span
                        className={cn(
                          'tabular text-right font-mono text-sm',
                          row.added_24h > 0 ? 'text-pending' : 'text-fg-ghost',
                        )}
                      >
                        {row.added_24h > 0 ? `+${row.added_24h}` : '—'}
                      </span>
                      <span>
                        <Badge size="sm" variant="outline" className="capitalize">
                          {row.plan}
                        </Badge>
                      </span>
                      <span className="truncate font-mono text-xs text-failed-text">
                        {row.top_error}
                      </span>
                      <RelativeTime value={row.oldest_at} className="text-xs text-fg-faint" />
                    </Link>
                  ))
                )}
              </div>
            </div>
          </Card>
        </>
      )}

      <ConfirmDialog
        open={confirmPurge}
        onOpenChange={setConfirmPurge}
        title="Purge resolved dead letters?"
        description="Only entries a customer already marked resolved are deleted. Unresolved entries are untouched — nobody loses a failure they have not looked at yet."
        confirmLabel="Purge resolved"
        destructive
        pending={purge.isPending}
        onConfirm={() => {
          purge.mutate(undefined, {
            onSuccess: () => {
              void query.refetch()
              toast({ title: 'Resolved dead letters purged' })
            },
          })
          setConfirmPurge(false)
        }}
      />
    </>
  )
}
