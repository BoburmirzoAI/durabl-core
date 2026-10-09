'use client'

import { useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useState } from 'react'

import { CountPill, SectionHeader } from '@/components/common/SectionHeader'
import { JOB_CSV_COLUMNS } from '@/components/jobs/JobsTable'
import { useToast } from '@/components/common/ToastProvider'
import { downloadCsv, timestampedName, toCsv } from '@/lib/utils/csv'
import { ErrorState } from '@/components/common/ErrorState'
import { Pagination } from '@/components/common/Pagination'
import { JobFilters } from '@/components/jobs/JobFilters'
import { JobSubmitDialog } from '@/components/jobs/JobSubmitDialog'
import { JobsTable } from '@/components/jobs/JobsTable'
import { Button } from '@/components/ui/button'
import { KbdHint } from '@/components/common/KbdHint'
import { SHORTCUTS } from '@/lib/constants/shortcuts'
import { useJobs } from '@/lib/hooks/useJobs'
import { useShortcut } from '@/lib/hooks/useKeyboard'
import { formatNumber } from '@/lib/utils/format'
import { useFilterStore } from '@/stores/filterStore'

/** Job'lar ro'yxati — dizayndagi Jobs sahifasi. */
export default function JobsPage() {
  return (
    // `useSearchParams` Suspense talab qiladi (Next.js App Router)
    <Suspense fallback={null}>
      <JobsPageContent />
    </Suspense>
  )
}

function JobsPageContent() {
  const searchParams = useSearchParams()
  const [submitOpen, setSubmitOpen] = useState(false)
  const { toast } = useToast()

  const filters = useFilterStore((s) => s.jobs)
  const setFilter = useFilterStore((s) => s.setJobFilter)

  // ⌘K palette'dan `?new=1` bilan kelsa dialog darhol ochiladi
  useEffect(() => {
    if (searchParams.get('new') === '1') setSubmitOpen(true)
  }, [searchParams])

  // Analitikadagi grafik nuqtasidan "View in Jobs" bosilganda aniq vaqt
  // oynasi `?range=custom:<from>|<to>` sifatida keladi
  useEffect(() => {
    const range = searchParams.get('range')
    if (range) setFilter('range', range)
    // `setFilter` store'dan — havolasi barqaror, qayta ishga tushirmaydi
  }, [searchParams, setFilter])

  useShortcut(SHORTCUTS.newJob, () => setSubmitOpen(true))

  const query = useJobs({
    search: filters.search || undefined,
    status: filters.status.length ? filters.status : undefined,
    runtime: filters.runtime.length ? filters.runtime : undefined,
    priority: filters.priority.length ? filters.priority : undefined,
    range: filters.range,
    page: filters.page,
    page_size: filters.pageSize,
    sort_by: filters.sortBy,
    sort_order: filters.sortOrder,
  })

  return (
    <>
      <SectionHeader
        title="Jobs"
        count={
          query.data ? <CountPill>{formatNumber(query.data.pagination.total)}</CountPill> : null
        }
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              onClick={() => {
                const rows = query.data?.items ?? []
                if (rows.length === 0) {
                  toast({ title: 'Nothing to export' })
                  return
                }
                downloadCsv(timestampedName('durabl-jobs'), toCsv(rows, JOB_CSV_COLUMNS))
                toast({
                  title: `Exported ${rows.length} jobs`,
                  description: 'Current page. Select rows to export just those.',
                  variant: 'success',
                })
              }}
            >
              Export CSV
            </Button>
          <Button variant="primary" size="md" onClick={() => setSubmitOpen(true)}>
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden>
              <path d="M12 5v14M5 12h14" />
            </svg>
            New Job
            <KbdHint className="border-white/20 bg-white/[0.18] text-white">⌘N</KbdHint>
          </Button>
          </div>
        }
      />

      <JobFilters />

      {query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          <JobsTable
            jobs={query.data?.items}
            loading={query.isLoading}
            onNewJob={() => setSubmitOpen(true)}
          />
          {query.data ? (
            <Pagination
              pagination={query.data.pagination}
              onPageChange={(page) => setFilter('page', page)}
              onPageSizeChange={(size) => setFilter('pageSize', size)}
            />
          ) : null}
        </>
      )}

      <JobSubmitDialog open={submitOpen} onOpenChange={setSubmitOpen} />
    </>
  )
}
