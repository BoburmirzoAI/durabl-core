'use client'

import Link from 'next/link'
import { useState } from 'react'

import { ErrorState } from '@/components/common/ErrorState'
import { RelativeTime } from '@/components/common/RelativeTime'
import { SectionHeader } from '@/components/common/SectionHeader'
import { StatCard } from '@/components/analytics/KpiCard'
import { Badge } from '@/components/ui/badge'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { SearchField } from '@/components/ui/input'
import { SkeletonRows } from '@/components/ui/skeleton'
import { Tabs } from '@/components/ui/tabs'
import { usePlatformWebhooks } from '@/lib/hooks/useAdminOps'
import { useSearchFocus } from '@/lib/hooks/useKeyboard'
import { cn } from '@/lib/utils/cn'
import { formatNumber } from '@/lib/utils/format'
import type { StatCardData } from '@/types'

const GRID = 'minmax(220px,1.8fr) minmax(160px,1fr) 86px 96px 110px 110px'

/**
 * Admin — platformadagi barcha webhook endpointlari.
 *
 * ═══════════════════════════════════════════════════════════════════
 * NEGA BU SAHIFA QO'LLAB-QUVVATLASH UCHUN
 * ═══════════════════════════════════════════════════════════════════
 *
 * Yiqilgan webhook — bu KELAYOTGAN tiket. Mijoz hodisani olmaydi,
 * bir-ikki kundan keyin "nega bildirishnoma kelmadi?" deb yozadi.
 *
 * Bu ro'yxat nosoz endpointlarni TEPADA ko'rsatadi, shuning uchun
 * mijoz yozishidan oldin unga xabar berish mumkin. Ko'p hollarda
 * sabab mijoz tomonida (sertifikat tugagan, URL o'zgargan) va buni
 * aytish — eng foydali qo'llab-quvvatlash.
 */
export default function AdminWebhooksPage() {
  const query = usePlatformWebhooks()
  const [search, setSearch] = useState('')
  const [filter, setFilter] = useState<'all' | 'failing' | 'disabled'>('failing')
  const searchRef = useSearchFocus()

  const data = query.data
  const term = search.trim().toLowerCase()
  const rows = (data?.rows ?? [])
    .filter((row) =>
      filter === 'all'
        ? true
        : filter === 'failing'
          ? row.consecutive_failures > 0
          : !row.is_active,
    )
    .filter(
      (row) =>
        term === '' || row.email.toLowerCase().includes(term) || row.url.toLowerCase().includes(term),
    )

  const cards: StatCardData[] = data
    ? [
        {
          label: 'Endpoints',
          value: formatNumber(data.endpoints),
          trend: 'across all accounts',
          trend_direction: 'flat',
          trend_is_good: true,
          sub: 'configured by customers',
        },
        {
          label: 'Failing now',
          value: formatNumber(data.failing),
          trend: data.failing > 0 ? 'customers not being notified' : 'all delivering',
          trend_direction: data.failing > 0 ? 'up' : 'flat',
          trend_is_good: data.failing === 0,
          sub: 'consecutive failures > 0',
          is_alert: data.failing > 0,
        },
        {
          label: 'Deliveries (24h)',
          value: formatNumber(data.deliveries_24h),
          trend: `${data.success_rate_24h}% delivered`,
          trend_direction: 'flat',
          trend_is_good: data.success_rate_24h >= 98,
          sub: 'attempts, including retries',
        },
        {
          label: 'Failed (24h)',
          value: formatNumber(
            (data.rows ?? []).reduce((sum, row) => sum + row.failed_24h, 0),
          ),
          trend: data.success_rate_24h >= 98 ? 'within normal range' : 'elevated',
          trend_direction: data.success_rate_24h >= 98 ? 'flat' : 'up',
          trend_is_good: data.success_rate_24h >= 98,
          sub: 'retried automatically',
          is_alert: data.success_rate_24h < 95,
        },
      ]
    : []

  return (
    <>
      <SectionHeader
        title="Webhooks"
        description="Every customer endpoint, failing ones first"
        count={<Badge variant="danger">ADMIN</Badge>}
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

          <div className="flex flex-wrap items-center gap-3">
            <Tabs
              aria-label="Endpoint filter"
              items={[
                { value: 'failing' as const, label: 'Failing' },
                { value: 'disabled' as const, label: 'Disabled' },
                { value: 'all' as const, label: 'All' },
              ]}
              value={filter}
              onChange={setFilter}
            />
            <SearchField
              ref={searchRef}
              shortcut="/"
              placeholder="Search account or URL…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              containerClassName="w-[300px]"
              aria-label="Search webhook endpoints"
            />
          </div>

          <Card className="overflow-hidden">
            <CardHeader>
              <CardTitle className="text-md">Endpoints</CardTitle>
              <CardDescription>
                Durabl retries with exponential backoff. An endpoint failing repeatedly is almost
                always broken on the customer side — tell them before they open a ticket.
              </CardDescription>
            </CardHeader>

            <div className="overflow-x-auto">
              <div className="min-w-[840px]">
                <div
                  className="table-head grid items-center gap-3 px-4"
                  style={{ gridTemplateColumns: GRID }}
                >
                  <span>Endpoint</span>
                  <span>Account</span>
                  <span className="text-right">Success</span>
                  <span className="text-right">Failures</span>
                  <span className="text-right">24h</span>
                  <span>Last delivery</span>
                </div>

                {query.isLoading && !data ? (
                  <SkeletonRows rows={6} columns={GRID} />
                ) : rows.length === 0 ? (
                  <p className="px-4 py-6 text-center text-sm text-fg-dim">
                    {filter === 'failing'
                      ? 'No endpoint is failing right now.'
                      : filter === 'disabled'
                        ? 'No endpoint is disabled.'
                        : 'No endpoints match that search.'}
                  </p>
                ) : (
                  rows.map((row) => (
                    <div
                      key={row.id}
                      className="grid min-h-[50px] items-center gap-3 border-b border-line-subtle px-4 py-2 last:border-b-0 hover:bg-surface-3"
                      style={{ gridTemplateColumns: GRID }}
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        <code className="truncate font-mono text-xs text-fg-soft" title={row.url}>
                          {row.url}
                        </code>
                        {!row.is_active ? (
                          <Badge size="sm" variant="danger">
                            disabled
                          </Badge>
                        ) : null}
                      </span>

                      <Link
                        href={`/admin/users/${row.user_id}`}
                        className="min-w-0 truncate text-sm text-fg-muted transition-colors hover:text-accent-light"
                      >
                        {row.email}
                      </Link>

                      <span
                        className={cn(
                          'tabular text-right font-mono text-sm',
                          row.success_rate >= 95 ? 'text-fg-muted' : 'text-failed-text',
                        )}
                      >
                        {row.success_rate}%
                      </span>

                      <span
                        className={cn(
                          'tabular text-right font-mono text-sm',
                          row.consecutive_failures > 5
                            ? 'text-failed'
                            : row.consecutive_failures > 0
                              ? 'text-pending'
                              : 'text-fg-ghost',
                        )}
                      >
                        {row.consecutive_failures > 0 ? `${row.consecutive_failures} in a row` : '—'}
                      </span>

                      <span className="tabular text-right font-mono text-xs text-fg-faint">
                        {formatNumber(row.deliveries_24h)}
                        {row.failed_24h > 0 ? (
                          <span className="text-failed-text"> / {row.failed_24h} failed</span>
                        ) : null}
                      </span>

                      <RelativeTime
                        value={row.last_triggered_at}
                        className="text-xs text-fg-ghost"
                      />
                    </div>
                  ))
                )}
              </div>
            </div>
          </Card>
        </>
      )}
    </>
  )
}
