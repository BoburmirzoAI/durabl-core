'use client'

import Link from 'next/link'

import { ErrorState } from '@/components/common/ErrorState'
import { SectionHeader } from '@/components/common/SectionHeader'
import { StatCard } from '@/components/analytics/KpiCard'
import { ChartFrame } from '@/components/analytics/ChartFrame'
import {
  AXIS_TICK,
  ChartTooltip,
  DASHED_CURSOR,
  type RechartsTooltipProps,
} from '@/components/analytics/ChartTooltip'
import { Badge } from '@/components/ui/badge'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { RelativeTime } from '@/components/common/RelativeTime'
import { usePlatformBilling } from '@/lib/hooks/useAdminOps'
import { cn } from '@/lib/utils/cn'
import { formatCurrency, formatNumber } from '@/lib/utils/format'
import type { RevenuePoint, StatCardData } from '@/types'
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

function RevenueTooltip({ active, payload }: RechartsTooltipProps<RevenuePoint>) {
  if (!active || !payload?.length) return null
  const point = payload[0]?.payload
  if (!point) return null
  return (
    <ChartTooltip
      heading={point.month}
      rows={[
        { label: 'MRR', value: formatCurrency(point.mrr_usd), dotClassName: 'bg-accent' },
        { label: 'New', value: formatCurrency(point.new_usd), dotClassName: 'bg-success' },
        { label: 'Churned', value: formatCurrency(point.churned_usd), dotClassName: 'bg-failed' },
      ]}
    />
  )
}

/**
 * Admin — platforma daromadi.
 *
 * ═══════════════════════════════════════════════════════════════════
 * MIJOZNING `/usage` SAHIFASIDAN FARQI
 * ═══════════════════════════════════════════════════════════════════
 *
 * Mijoz "men qancha to'layman?" deb so'raydi. Bu yerda savol boshqacha:
 * "biznes qanday ketyapti va kim to'lamayapti?".
 *
 * MRR raqami TASODIFIY emas — u `Users` sahifasidagi haqiqiy hisoblardan
 * hisoblanadi (faol hisoblar × tarif narxi). Shuning uchun ikki sahifa
 * bir-biriga zid kelmaydi: 40 ta hisobni sanab chiqib, MRR'ni qo'lda
 * tekshirib ko'rish mumkin.
 */
export default function AdminBillingPage() {
  const query = usePlatformBilling()
  const data = query.data

  const cards: StatCardData[] = data
    ? [
        {
          label: 'MRR',
          value: formatCurrency(data.mrr_usd),
          trend: `${data.mrr_change_percent >= 0 ? '↑' : '↓'} ${Math.abs(data.mrr_change_percent)}%`,
          trend_direction: data.mrr_change_percent >= 0 ? 'up' : 'down',
          trend_is_good: data.mrr_change_percent >= 0,
          sub: `${formatCurrency(data.arr_usd)} ARR`,
        },
        {
          label: 'Paying accounts',
          value: formatNumber(data.paying_accounts),
          trend: `${formatNumber(data.trial_accounts)} on free`,
          trend_direction: 'flat',
          trend_is_good: true,
          sub: 'active subscriptions',
        },
        {
          label: 'Monthly churn',
          value: `${data.churn_percent}%`,
          trend: data.churn_percent > 5 ? 'above target' : 'within target',
          trend_direction: data.churn_percent > 5 ? 'up' : 'flat',
          trend_is_good: data.churn_percent <= 5,
          sub: 'revenue lost vs MRR',
          is_alert: data.churn_percent > 5,
        },
        {
          label: 'Outstanding',
          value: formatCurrency(data.outstanding_usd),
          trend: `${data.overdue.length} account${data.overdue.length === 1 ? '' : 's'}`,
          trend_direction: data.overdue.length > 0 ? 'up' : 'flat',
          trend_is_good: data.overdue.length === 0,
          sub: 'payment failed',
          is_alert: data.overdue.length > 0,
        },
      ]
    : []

  return (
    <>
      <SectionHeader
        title="Billing"
        description="Revenue, plan mix and accounts that have not paid"
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

          <ChartFrame
            title="Revenue over time"
            description="MRR with new and churned revenue per month"
            height={260}
            loading={query.isLoading}
            isEmpty={(data?.history.length ?? 0) === 0}
          >
            <ResponsiveContainer width="100%" height={260}>
              <ComposedChart
                data={data?.history ?? []}
                margin={{ top: 8, right: 8, bottom: 0, left: 0 }}
              >
                <defs>
                  <linearGradient id="mrrFill" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="hsl(var(--accent))" stopOpacity={0.3} />
                    <stop offset="100%" stopColor="hsl(var(--accent))" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} stroke="hsl(var(--surface-4))" />
                <XAxis dataKey="month" tick={AXIS_TICK} tickLine={false} axisLine={false} />
                <YAxis
                  tick={AXIS_TICK}
                  tickLine={false}
                  axisLine={false}
                  width={60}
                  tickFormatter={(value: number) => `$${Math.round(value / 1_000)}k`}
                />
                <Tooltip content={<RevenueTooltip />} cursor={DASHED_CURSOR} animationDuration={120} />
                <Area
                  type="monotone"
                  dataKey="mrr_usd"
                  stroke="hsl(var(--accent))"
                  strokeWidth={2}
                  fill="url(#mrrFill)"
                  isAnimationActive={false}
                />
                <Bar dataKey="new_usd" fill="hsl(var(--success))" maxBarSize={10} isAnimationActive={false} />
                <Line
                  type="monotone"
                  dataKey="churned_usd"
                  stroke="hsl(var(--failed))"
                  strokeWidth={1.5}
                  dot={false}
                  isAnimationActive={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </ChartFrame>

          <div className="grid items-start gap-4 xl:grid-cols-2">
            <Card className="overflow-hidden">
              <CardHeader>
                <CardTitle className="text-md">Revenue by plan</CardTitle>
                <CardDescription>ARPA is the average revenue per account on that plan</CardDescription>
              </CardHeader>
              <div
                className="table-head grid items-center gap-3 px-4"
                style={{ gridTemplateColumns: 'minmax(90px,1fr) 80px 110px 90px 80px' }}
              >
                <span>Plan</span>
                <span className="text-right">Accounts</span>
                <span className="text-right">MRR</span>
                <span className="text-right">ARPA</span>
                <span className="text-right">Change</span>
              </div>
              {!data ? (
                <div className="p-4">
                  <Skeleton className="h-32 w-full" />
                </div>
              ) : (
                data.by_plan.map((row) => (
                  <div
                    key={row.plan}
                    className="grid h-11 items-center gap-3 border-b border-line-subtle px-4 last:border-b-0 hover:bg-surface-3"
                    style={{ gridTemplateColumns: 'minmax(90px,1fr) 80px 110px 90px 80px' }}
                  >
                    <span className="text-base capitalize text-fg-soft">{row.plan}</span>
                    <span className="tabular text-right font-mono text-sm text-fg-muted">
                      {formatNumber(row.accounts)}
                    </span>
                    <span className="tabular text-right font-mono text-sm text-fg">
                      {formatCurrency(row.mrr_usd)}
                    </span>
                    <span className="tabular text-right font-mono text-sm text-fg-faint">
                      {formatCurrency(row.arpa_usd)}
                    </span>
                    <span
                      className={cn(
                        'tabular text-right font-mono text-xs',
                        row.change_percent >= 0 ? 'text-success' : 'text-failed-text',
                      )}
                    >
                      {row.change_percent >= 0 ? '↑' : '↓'} {Math.abs(row.change_percent)}%
                    </span>
                  </div>
                ))
              )}
            </Card>

            <Card className="overflow-hidden">
              <CardHeader>
                <CardTitle className="text-md">Payment failures</CardTitle>
                <CardDescription>
                  These accounts are suspended until payment clears
                </CardDescription>
              </CardHeader>
              {!data ? (
                <div className="p-4">
                  <Skeleton className="h-32 w-full" />
                </div>
              ) : data.overdue.length === 0 ? (
                <p className="px-4 pb-4 text-sm text-fg-dim">Every account is paid up.</p>
              ) : (
                <div className="divide-y divide-line-subtle">
                  {data.overdue.map((account) => (
                    <Link
                      key={account.user_id}
                      href={`/admin/users/${account.user_id}`}
                      className="flex flex-wrap items-center gap-3 px-4 py-2.5 transition-colors hover:bg-surface-3"
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm text-fg-soft">
                          {account.email}
                        </span>
                        <span className="block truncate text-xs text-failed-text">
                          {account.failure_reason}
                        </span>
                      </span>
                      <Badge size="sm" variant="outline" className="capitalize">
                        {account.plan}
                      </Badge>
                      <span className="tabular w-16 shrink-0 text-right font-mono text-sm text-fg">
                        {formatCurrency(account.amount_usd)}
                      </span>
                      <span
                        className={cn(
                          'w-20 shrink-0 text-right text-xs',
                          account.days_overdue > 30 ? 'text-failed-text' : 'text-pending',
                        )}
                      >
                        {account.days_overdue}d overdue
                      </span>
                      <RelativeTime
                        value={account.last_attempt_at}
                        className="w-16 shrink-0 text-right text-2xs text-fg-ghost"
                      />
                    </Link>
                  ))}
                </div>
              )}
            </Card>
          </div>
        </>
      )}
    </>
  )
}
