'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Suspense, useMemo, useState } from 'react'

import { ErrorState } from '@/components/common/ErrorState'
import { Pagination } from '@/components/common/Pagination'
import { SectionHeader } from '@/components/common/SectionHeader'
import { DlqAlertBanner } from '@/components/dlq/DlqAlertBanner'
import { DlqStatsCards } from '@/components/dlq/DlqStatsCards'
import { DLQ_CSV_COLUMNS, DlqTable } from '@/components/dlq/DlqTable'
import { DrilldownChart } from '@/components/common/DrilldownChart'
import { EditAndRetryModal } from '@/components/dlq/EditAndRetryModal'
import { Button } from '@/components/ui/button'
import { SearchField } from '@/components/ui/input'
import { Tabs } from '@/components/ui/tabs'
import { useDlqEntries, useDlqStats, useRetryAllDlq } from '@/lib/hooks/useDlq'
import { useToast } from '@/components/common/ToastProvider'
import { downloadCsv, timestampedName, toCsv } from '@/lib/utils/csv'
import { failureReasonLabel } from '@/lib/utils/status'
import { useFilterStore } from '@/stores/filterStore'
import { FAILURE_REASONS, type DlqEntry, type DlqGroupBy, type FailureReason } from '@/types'
import { useSearchFocus } from '@/lib/hooks/useKeyboard'

/**
 * Dead Letter Queue — Durabl'ning raqobatchilardan ajralib turadigan sahifasi.
 *
 * Dizayndagi tuzilma: sarlavha + qizil son nishoni / alert bayrog'i /
 * statistika kartalari / guruhlash tablari / jadval (ochiladigan traceback).
 *
 * "By Error / By User / By Runtime" guruhlari dizaynda faqat tab sifatida
 * ko'rsatilgan — guruhlash MANTIG'I shu yerda amalga oshirilgan.
 */
const GROUP_TABS = [
  { value: 'all' as DlqGroupBy, label: 'All' },
  { value: 'error' as DlqGroupBy, label: 'By Error' },
  { value: 'user' as DlqGroupBy, label: 'By User' },
  { value: 'runtime' as DlqGroupBy, label: 'By Runtime' },
] as const

export default function DlqPage() {
  return (
    <Suspense fallback={null}>
      <DlqPageContent />
    </Suspense>
  )
}

function DlqPageContent() {
  const searchParams = useSearchParams()
  const { toast } = useToast()
  const groupBy = useFilterStore((s) => s.dlqGroupBy)
  const search = useFilterStore((s) => s.dlqSearch)
  const resolved = useFilterStore((s) => s.dlqResolved)
  const page = useFilterStore((s) => s.dlqPage)
  const setGroupBy = useFilterStore((s) => s.setDlqGroupBy)
  const setSearch = useFilterStore((s) => s.setDlqSearch)
  const setResolved = useFilterStore((s) => s.setDlqResolved)
  const setPage = useFilterStore((s) => s.setDlqPage)
  const searchRef = useSearchFocus()

  const stats = useDlqStats()
  const retryAll = useRetryAllDlq()

  /**
   * Analitikadagi "Error breakdown" grafigidan `?reason=timeout` bilan
   * kelish mumkin. Yaroqsiz qiymat jim e'tiborsiz qoldiriladi — buzuq
   * havola sahifani bo'shatib qo'ymasligi kerak.
   */
  const reasonParam = searchParams.get('reason')
  const reason = FAILURE_REASONS.includes(reasonParam as FailureReason)
    ? (reasonParam as FailureReason)
    : null

  const query = useDlqEntries({
    search: search || undefined,
    resolved,
    failure_reason: reason ? [reason] : undefined,
    page,
    page_size: 25,
    sort_by: 'failed_at',
    sort_order: 'desc',
  })

  /**
   * Xato turlari taqsimoti — bosiladigan grafik uchun.
   *
   * Bu "nima eng ko'p yiqilyapti?" degan savolga bir qarashda javob beradi;
   * ustunga bosilsa jadval o'sha turga filtrlanadi.
   */
  const errorBreakdown = useMemo(() => {
    const counts = new Map<string, number>()
    for (const entry of query.data?.items ?? []) {
      counts.set(entry.error_type, (counts.get(entry.error_type) ?? 0) + 1)
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 8)
      .map(([type, count]) => ({ label: type, value: count, key: type, tone: 'failed' as const }))
  }, [query.data?.items])

  // Guruhlash: sahifadagi yozuvlarni tanlangan kalit bo'yicha bo'lamiz
  const [editEntry, setEditEntry] = useState<DlqEntry | null>(null)
  //: Grafikda tanlangan xato turi — jadvalni ham filtrlaydi
  const [errorFilter, setErrorFilter] = useState<string | null>(null)

  const groups = useMemo(() => {
    const all = query.data?.items ?? []
    //: Grafikdan tanlangan xato turi butun jadvalni toraytiradi
    const rows = errorFilter ? all.filter((e) => e.error_type === errorFilter) : all
    if (groupBy === 'all') return [{ key: null as string | null, rows }]

    const pick = (entry: DlqEntry): string =>
      groupBy === 'error'
        ? entry.error_type
        : groupBy === 'user'
          ? entry.user_email
          : entry.runtime

    const map = new Map<string, DlqEntry[]>()
    for (const row of rows) {
      const key = pick(row)
      const list = map.get(key)
      if (list) list.push(row)
      else map.set(key, [row])
    }
    return [...map.entries()]
      .sort((a, b) => b[1].length - a[1].length)
      .map(([key, rows]) => ({ key, rows }))
  }, [query.data?.items, groupBy, errorFilter])

  return (
    <>
      <SectionHeader
        title="Dead Letter Queue"
        description="Jobs that failed after all retry attempts"
        count={
          stats.data && stats.data.depth > 0 ? (
            <span className="tabular rounded-md border border-failed/25 bg-failed/[0.13] px-2.5 py-[3px] font-mono text-sm font-semibold text-failed">
              {stats.data.depth}
            </span>
          ) : null
        }
        actions={
          <>
            <Button
              variant="secondary"
              size="md"
              onClick={() => {
                const rows = query.data?.items ?? []
                if (rows.length === 0) {
                  toast({ title: 'Nothing to export' })
                  return
                }
                downloadCsv(timestampedName('durabl-dlq'), toCsv(rows, DLQ_CSV_COLUMNS))
                toast({
                  title: `Exported ${rows.length} entries`,
                  description: 'Current page, with the active filters applied.',
                })
              }}
            >
              <Icon path="M12 3v12M7 10l5 5 5-5M4 19h16" />
              Export
            </Button>
            <Button
              variant="primary"
              size="md"
              disabled={!stats.data || stats.data.depth === 0 || retryAll.isPending}
              onClick={() => retryAll.mutate()}
            >
              <Icon path="M3 12a9 9 0 1 0 3-6.7M3 3v4h4" />
              {retryAll.isPending ? 'Retrying…' : 'Retry All'}
            </Button>
          </>
        }
      />

      {reason ? (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-accent-edge bg-accent-bar-2 px-4 py-2.5">
          <span className="text-base text-fg-soft">
            Filtered to failures caused by{' '}
            <span className="font-medium text-fg">{failureReasonLabel(reason)}</span>.
          </span>
          <Link
            href="/dlq"
            className="ml-auto text-sm font-medium text-accent hover:text-accent-light"
          >
            Clear filter
          </Link>
        </div>
      ) : null}

      <DlqAlertBanner stats={stats.data} />
      <DlqStatsCards stats={stats.data} loading={stats.isLoading} />

      <div className="flex flex-wrap items-center gap-3">
        <Tabs aria-label="Group entries by" items={GROUP_TABS} value={groupBy} onChange={setGroupBy} />
        <SearchField
          ref={searchRef}
          shortcut="/"
          placeholder="Search job ID, error, user…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          containerClassName="w-[280px]"
          aria-label="Search DLQ entries"
        />
        <Tabs
          aria-label="Resolution state"
          items={[
            { value: 'open', label: 'Open' },
            { value: 'resolved', label: 'Resolved' },
            { value: 'any', label: 'All' },
          ]}
          value={resolved === false ? 'open' : resolved === true ? 'resolved' : 'any'}
          onChange={(value) =>
            setResolved(value === 'open' ? false : value === 'resolved' ? true : undefined)
          }
        />
      </div>
      {/* Xato turlari — bosiladigan taqsimot. "Nima eng ko'p yiqilyapti?" */}
      {errorBreakdown.length > 0 ? (
        <DrilldownChart
          title="Error types"
          description={
            errorFilter
              ? `Filtered: ${errorFilter} — click again to clear`
              : 'Click a bar to filter the table'
          }
          points={errorBreakdown}
          valueLabel="Entries"
          height={180}
          selectedKey={errorFilter}
          loading={query.isLoading}
          onSelect={(point) =>
            setErrorFilter((current) => (current === point.key ? null : (point.key ?? null)))
          }
        />
      ) : null}


      {query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          {groups.map((group) => (
            <div key={group.key ?? 'all'} className="flex flex-col gap-2">
              {group.key ? (
                <div className="flex items-center gap-2.5 pt-1">
                  <span className="font-mono text-base font-semibold text-fg-soft">
                    {group.key}
                  </span>
                  <span className="tabular rounded border border-line bg-surface-2 px-2 py-px font-mono text-xs text-fg-muted">
                    {group.rows.length}
                  </span>
                </div>
              ) : null}
              <DlqTable entries={group.rows} loading={query.isLoading} onEditRetry={setEditEntry} />
            </div>
          ))}

          {query.data ? (
            <Pagination pagination={query.data.pagination} onPageChange={setPage} />
          ) : null}
        </>
      )}

      <EditAndRetryModal
        entry={editEntry}
        onOpenChange={(open) => {
          if (!open) setEditEntry(null)
        }}
      />
    </>
  )
}

function Icon({ path }: { path: string }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d={path} />
    </svg>
  )
}
