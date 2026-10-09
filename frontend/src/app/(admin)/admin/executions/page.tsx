'use client'

import { ErrorState } from '@/components/common/ErrorState'
import { SectionHeader } from '@/components/common/SectionHeader'
import { StatCard } from '@/components/analytics/KpiCard'
import { Badge } from '@/components/ui/badge'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { SkeletonRows } from '@/components/ui/skeleton'
import { usePlatformExecutions } from '@/lib/hooks/useAdminOps'
import { cn } from '@/lib/utils/cn'
import { formatDuration, formatNumber } from '@/lib/utils/format'
import type { StatCardData } from '@/types'

const GRID = 'minmax(130px,1fr) 86px 96px 86px 86px 86px 96px minmax(150px,1.1fr)'

/**
 * Admin — bajarish urinishlari, WORKER bo'yicha.
 *
 * ═══════════════════════════════════════════════════════════════════
 * MIJOZNING `/executions` SAHIFASIDAN FARQI
 * ═══════════════════════════════════════════════════════════════════
 *
 * Mijoz "mening urinishlarim qanday ketdi?" deb so'raydi va javobni
 * job bo'yicha oladi.
 *
 * Admin uchun savol butunlay boshqacha: "QAYSI MASHINA ishni
 * yo'qotayapti?". Shuning uchun bu yerda agregat worker bo'yicha va
 * `lost` ustuni (lease yo'qolgani sababli uzilgan urinish) birinchi
 * tartiblash mezoni — aynan u nosog'lom mashinani ochib beradi.
 *
 * `lost` noldan farq qilsa, bu job YO'QOLDI degani emas: lease
 * tugagach u qayta navbatga tushadi. Lekin bu kechikish va ikki marta
 * hisob vaqti — ya'ni pul va mijoz sabri.
 */
export default function AdminExecutionsPage() {
  const query = usePlatformExecutions()
  const data = query.data

  const cards: StatCardData[] = data
    ? [
        {
          label: 'Executions',
          value: formatNumber(data.total),
          trend: 'lifetime, all workers',
          trend_direction: 'flat',
          trend_is_good: true,
          sub: 'every attempt, not every job',
        },
        {
          label: 'Lost to lease expiry',
          value: formatNumber(data.lost),
          trend: `${data.lost_rate}% of attempts`,
          trend_direction: data.lost > 0 ? 'up' : 'flat',
          trend_is_good: data.lost === 0,
          sub: 'requeued automatically',
          is_alert: data.lost_rate > 0.5,
        },
        {
          label: 'Timeouts',
          value: formatNumber(data.timeout),
          trend: 'killed at the limit',
          trend_direction: 'flat',
          trend_is_good: data.timeout === 0,
          sub: 'customer code, usually',
        },
        {
          label: 'Workers with losses',
          value: String(data.by_worker.filter((w) => w.lost > 0).length),
          trend: `${data.by_worker.length} in the fleet`,
          trend_direction: 'flat',
          trend_is_good: data.by_worker.every((w) => w.lost === 0),
          sub: 'check these first',
          is_alert: data.by_worker.some((w) => w.lost > 3),
        },
      ]
    : []

  return (
    <>
      <SectionHeader
        title="Executions"
        description="Attempt health per worker — who is losing work"
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

          <Card className="overflow-hidden">
            <CardHeader>
              <CardTitle className="text-md">Per worker</CardTitle>
              <CardDescription>
                Sorted by lost attempts. A worker losing leases is either overloaded, paused by the
                host, or on a bad network path.
              </CardDescription>
            </CardHeader>

            <div className="overflow-x-auto">
              <div className="min-w-[880px]">
                <div
                  className="table-head grid items-center gap-3 px-4"
                  style={{ gridTemplateColumns: GRID }}
                >
                  <span>Worker</span>
                  <span className="text-right">Attempts</span>
                  <span className="text-right">Succeeded</span>
                  <span className="text-right">Failed</span>
                  <span className="text-right">Lost</span>
                  <span className="text-right">Timeout</span>
                  <span className="text-right">Avg time</span>
                  <span>Top exit codes</span>
                </div>

                {query.isLoading && !data ? (
                  <SkeletonRows rows={5} columns={GRID} />
                ) : (
                  (data?.by_worker ?? []).map((worker) => (
                    <div
                      key={worker.worker_id}
                      className="grid min-h-[48px] items-center gap-3 border-b border-line-subtle px-4 py-2 last:border-b-0 hover:bg-surface-3"
                      style={{ gridTemplateColumns: GRID }}
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        <span className="min-w-0">
                          <span className="block truncate font-mono text-xs text-fg-soft">
                            {worker.region}
                          </span>
                          <span className="block truncate font-mono text-2xs text-fg-ghost">
                            {worker.worker_id}
                          </span>
                        </span>
                        {worker.state === 'dead' ? (
                          <Badge size="sm" variant="danger">
                            dead
                          </Badge>
                        ) : null}
                      </span>

                      <span className="tabular text-right font-mono text-sm text-fg-muted">
                        {formatNumber(worker.executions)}
                      </span>
                      <span className="tabular text-right font-mono text-sm text-success">
                        {formatNumber(worker.succeeded)}
                      </span>
                      <span className="tabular text-right font-mono text-sm text-fg-faint">
                        {formatNumber(worker.failed)}
                      </span>
                      <span
                        className={cn(
                          'tabular text-right font-mono text-sm',
                          worker.lost > 3
                            ? 'text-failed'
                            : worker.lost > 0
                              ? 'text-pending'
                              : 'text-fg-ghost',
                        )}
                      >
                        {worker.lost}
                      </span>
                      <span className="tabular text-right font-mono text-sm text-fg-faint">
                        {worker.timeout}
                      </span>
                      <span className="tabular text-right font-mono text-sm text-fg-faint">
                        {formatDuration(worker.avg_duration_ms)}
                      </span>

                      <span className="flex flex-wrap gap-1.5">
                        {worker.top_exit_codes.map((row) => (
                          <span
                            key={row.code}
                            className={cn(
                              'tabular rounded px-1.5 py-px font-mono text-2xs',
                              row.code === 0
                                ? 'bg-success/[0.12] text-success'
                                : row.code === 137
                                  ? 'bg-failed/[0.12] text-failed'
                                  : 'bg-surface-3 text-fg-faint',
                            )}
                            title={
                              row.code === 0
                                ? 'Exited cleanly'
                                : row.code === 137
                                  ? 'Killed (SIGKILL) — usually the memory limit'
                                  : row.code === 124
                                    ? 'Timed out'
                                    : `Exit code ${row.code}`
                            }
                          >
                            {row.code}×{formatNumber(row.count)}
                          </span>
                        ))}
                      </span>
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
