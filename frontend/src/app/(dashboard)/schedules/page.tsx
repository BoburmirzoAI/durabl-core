'use client'

import { useMemo, useState } from 'react'

import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { ErrorState } from '@/components/common/ErrorState'
import { Pagination } from '@/components/common/Pagination'
import { SectionHeader } from '@/components/common/SectionHeader'
import { ScheduleDetailDrawer } from '@/components/schedules/ScheduleDetailDrawer'
import { ScheduleFormDialog } from '@/components/schedules/ScheduleFormDialog'
import { SchedulesTable } from '@/components/schedules/SchedulesTable'
import { StatCard } from '@/components/analytics/KpiCard'
import { Button } from '@/components/ui/button'
import { SearchField } from '@/components/ui/input'
import { Tabs } from '@/components/ui/tabs'
import { useDeleteSchedule, useSchedules } from '@/lib/hooks/useSchedules'
import { useSearchFocus } from '@/lib/hooks/useKeyboard'
import { formatNumber } from '@/lib/utils/format'
import { relativeTime } from '@/lib/utils/time'
import type { Schedule, ScheduleStatus, StatCardData } from '@/types'

const STATUS_TABS = [
  { value: 'all' as const, label: 'All' },
  { value: 'active' as const, label: 'Active' },
  { value: 'paused' as const, label: 'Paused' },
  { value: 'errored' as const, label: 'Failing' },
]

/**
 * Jadvallar — cron bo'yicha takrorlanadigan job'lar.
 *
 * ═══════════════════════════════════════════════════════════════════
 * NEGA BU SAHIFA KERAK
 * ═══════════════════════════════════════════════════════════════════
 *
 * Takroriy ishni ishga tushirishning odatiy yo'li — o'z serveringizda
 * cron yozib, u yerdan Durabl API'sini chaqirish. Lekin o'sha cron
 * server o'chsa, ish ham to'xtaydi va buni hech kim bilmaydi.
 *
 * Shuning uchun jadval Durabl ichida: ishga tushirish ham, qayta urinish
 * ham, "ishlamay qoldi" ogohlantirishi ham bitta joyda.
 *
 * Sahifa uchta savolga javob beradi: nima rejalashtirilgan, keyingi
 * safar qachon, va nima buzilgan.
 */
export default function SchedulesPage() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<'all' | ScheduleStatus>('all')
  const [page, setPage] = useState(1)
  const [detail, setDetail] = useState<Schedule | null>(null)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<Schedule | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<Schedule | null>(null)

  const searchRef = useSearchFocus()
  const remove = useDeleteSchedule()

  const query = useSchedules({
    search: search || undefined,
    status: status === 'all' ? undefined : [status],
    page,
    page_size: 20,
  })

  // Jadvaldagi joriy nusxa — tahrirlangandan keyin panel eskirmasligi uchun
  const detailRow = detail
    ? (query.data?.items.find((s) => s.id === detail.id) ?? detail)
    : null

  const cards: StatCardData[] = useMemo(() => {
    const rows = query.data?.items ?? []
    const active = rows.filter((s) => s.status === 'active')
    const failing = rows.filter((s) => s.status === 'errored')
    const paused = rows.filter((s) => s.status === 'paused')
    const soonest = active
      .filter((s) => s.next_run_at)
      .sort(
        (a, b) =>
          new Date(a.next_run_at as string).getTime() - new Date(b.next_run_at as string).getTime(),
      )[0]
    const totalRuns = rows.reduce((sum, s) => sum + s.total_runs, 0)
    const failedRuns = rows.reduce((sum, s) => sum + s.failed_runs, 0)

    return [
      {
        label: 'Active schedules',
        value: `${active.length}/${rows.length}`,
        trend: paused.length > 0 ? `${paused.length} paused` : 'none paused',
        trend_direction: 'flat',
        trend_is_good: true,
        sub: 'running on their cron',
      },
      {
        label: 'Next run',
        value: soonest?.next_run_at ? relativeTime(soonest.next_run_at) : '—',
        trend: soonest?.name ?? 'nothing scheduled',
        trend_direction: 'flat',
        trend_is_good: true,
        sub: 'soonest across all schedules',
      },
      {
        label: 'Runs recorded',
        value: formatNumber(totalRuns),
        trend: `${formatNumber(failedRuns)} failed`,
        trend_direction: 'flat',
        trend_is_good: failedRuns === 0,
        sub: 'lifetime, all schedules',
      },
      {
        label: 'Failing',
        value: String(failing.length),
        trend: failing.length > 0 ? 'needs attention' : 'all healthy',
        trend_direction: failing.length > 0 ? 'up' : 'flat',
        trend_is_good: failing.length === 0,
        sub: 'three failures in a row',
        is_alert: failing.length > 0,
      },
    ]
  }, [query.data])

  return (
    <>
      <SectionHeader
        title="Schedules"
        description="Recurring jobs, run on a cron by Durabl"
        actions={
          <Button
            variant="primary"
            size="md"
            onClick={() => {
              setEditing(null)
              setFormOpen(true)
            }}
          >
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden>
              <path d="M12 5v14M5 12h14" />
            </svg>
            New schedule
          </Button>
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
          aria-label="Schedule status"
          items={STATUS_TABS}
          value={status}
          onChange={(value) => {
            setStatus(value)
            setPage(1)
          }}
        />
        <SearchField
          ref={searchRef}
          shortcut="/"
          placeholder="Search name, description, cron…"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
            setPage(1)
          }}
          containerClassName="w-[300px]"
          aria-label="Search schedules"
        />
      </div>

      {query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          <SchedulesTable
            schedules={query.data?.items}
            loading={query.isLoading}
            onOpenDetail={setDetail}
            onEdit={(schedule) => {
              setEditing(schedule)
              setFormOpen(true)
            }}
            onDelete={setConfirmDelete}
            onCreate={() => {
              setEditing(null)
              setFormOpen(true)
            }}
          />
          {query.data ? (
            <Pagination pagination={query.data.pagination} onPageChange={setPage} />
          ) : null}
        </>
      )}

      <ScheduleDetailDrawer
        schedule={detailRow}
        onOpenChange={(open) => {
          if (!open) setDetail(null)
        }}
        onEdit={(schedule) => {
          setDetail(null)
          setEditing(schedule)
          setFormOpen(true)
        }}
      />

      <ScheduleFormDialog open={formOpen} schedule={editing} onOpenChange={setFormOpen} />

      <ConfirmDialog
        open={confirmDelete !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmDelete(null)
        }}
        title="Delete schedule?"
        description={
          confirmDelete
            ? `"${confirmDelete.name}" stops running immediately. Jobs it already created are kept, and their history stays available.`
            : ''
        }
        confirmLabel="Delete schedule"
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
