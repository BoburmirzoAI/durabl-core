'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { BULK_ICONS, BulkActionBar } from '@/components/common/BulkActionBar'
import { Checkbox } from '@/components/ui/checkbox'
import { CopyButton } from '@/components/common/CopyButton'
import { EmptyState } from '@/components/common/EmptyState'
import { RelativeTime } from '@/components/common/RelativeTime'
import { Skeleton, SkeletonRows } from '@/components/ui/skeleton'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils/cn'
import type { CsvColumn } from '@/lib/utils/csv'
import { truncate } from '@/lib/utils/format'
import { runtimeStyle } from '@/lib/utils/status'
import {
  useBulkDeleteDlq,
  useBulkRetryDlq,
  useDeleteDlqEntry,
  useRetryDlqEntry,
} from '@/lib/hooks/useDlq'
import { useSelectionStore } from '@/stores/selectionStore'
import { CodeBlock } from '@/components/jobs/CodeBlock'
import { DlqFixHint } from '@/components/dlq/DlqFixHint'
import { JsonViewer } from '@/components/common/JsonViewer'
import { useJob } from '@/lib/hooks/useJobs'
import type { DlqEntry } from '@/types'
import { failureReasonLabel } from '@/lib/utils/status'

/**
 * Bo'sh tanlov uchun BARQAROR havola.
 *
 * Zustand selektor natijasini `Object.is` bilan solishtiradi. `?? []` yozilsa
 * har chaqiriqda YANGI massiv qaytadi — store o'zgarmagan bo'lsa ham "o'zgardi"
 * deb hisoblanadi va cheksiz qayta render boshlanadi
 * ("Maximum update depth exceeded").
 */
const EMPTY_IDS: string[] = []


/**
 * DLQ jadvali — dizayndagi ustunlar:
 * `36px minmax(96px,1.1fr) 128px minmax(120px,1.6fr) 58px 92px 70px 44px`
 *
 * Qator bosilganda TRACEBACK ochiladi (dizayndagi asosiy xususiyat) —
 * operator xatoni ko'rib, tuzatib, qayta urinishi kerak.
 */
const GRID =
  '36px minmax(96px,1.1fr) 128px minmax(120px,1.6fr) 58px 92px 88px 76px'

export const DLQ_SCOPE = 'dlq'

export function DlqTable({
  entries,
  loading = false,
  onEditRetry,
}: {
  entries: DlqEntry[] | undefined
  loading?: boolean
  /** 'Edit & retry' bosilganda — kodni tuzatib yangi job yuborish. */
  onEditRetry?: (entry: DlqEntry) => void,
}) {
  const router = useRouter()
  const [openIds, setOpenIds] = useState<string[]>([])

  const selected = useSelectionStore((s) => s.selected[DLQ_SCOPE] ?? EMPTY_IDS)
  const toggleSelect = useSelectionStore((s) => s.toggle)
  const setMany = useSelectionStore((s) => s.setMany)

  const retry = useRetryDlqEntry()
  const remove = useDeleteDlqEntry()
  const bulkRetry = useBulkRetryDlq()
  const bulkDelete = useBulkDeleteDlq()

  const rows = entries ?? []
  const ids = rows.map((r) => r.id)
  const allSelected = ids.length > 0 && ids.every((id) => selected.includes(id))
  const someSelected = !allSelected && ids.some((id) => selected.includes(id))

  const toggleOpen = (id: string): void => {
    setOpenIds((current) =>
      current.includes(id) ? current.filter((v) => v !== id) : [...current, id],
    )
  }

  return (
    <div className="relative overflow-hidden rounded-2xl border border-line bg-surface">
      <BulkActionBar
        scope={DLQ_SCOPE}
        actions={[
          { label: 'Retry', icon: BULK_ICONS.retry, onClick: (sel) => bulkRetry.mutate(sel) },
          {
            label: 'Delete',
            icon: BULK_ICONS.delete,
            iconClassName: 'text-failed',
            onClick: (sel) => bulkDelete.mutate(sel),
          },
          { label: 'Export', icon: BULK_ICONS.export, onClick: () => undefined },
        ]}
      />

      <div className="table-head grid items-center" style={{ gridTemplateColumns: GRID }}>
        <span className="flex items-center">
          <Checkbox
            checked={allSelected}
            indeterminate={someSelected}
            onToggle={() => setMany(DLQ_SCOPE, allSelected ? [] : ids)}
            aria-label={allSelected ? 'Deselect all entries' : 'Select all entries'}
          />
        </span>
        <span>Job ID</span>
        <span>Error</span>
        <span>Message</span>
        <span>Tries</span>
        <span>Failed</span>
        <span>Status</span>
        <span className="text-right">Actions</span>
      </div>

      {loading && rows.length === 0 ? (
        <SkeletonRows rows={10} columns={GRID} />
      ) : rows.length === 0 ? (
        <EmptyState
          tone="positive"
          icon="M5 12l5 5 9-11"
          title="Dead letter queue is empty"
          description="Every job either succeeded or is still being retried. Nothing needs your attention."
        />
      ) : (
        rows.map((entry) => {
          const isOpen = openIds.includes(entry.id)
          const runtime = runtimeStyle(entry.runtime)
          return (
            <div key={entry.id}>
              <div
                role="button"
                tabIndex={0}
                aria-expanded={isOpen}
                onClick={() => toggleOpen(entry.id)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault()
                    toggleOpen(entry.id)
                  }
                }}
                className={cn(
                  'grid h-10 cursor-pointer items-center px-3.5 transition-colors',
                  selected.includes(entry.id) ? 'bg-accent/[0.06]' : 'hover:bg-surface-3',
                )}
                style={{ gridTemplateColumns: GRID }}
              >
                <span className="flex items-center">
                  <Checkbox
                    checked={selected.includes(entry.id)}
                    onToggle={() => toggleSelect(DLQ_SCOPE, entry.id)}
                    aria-label={`Select entry ${entry.job_id}`}
                  />
                </span>

                <span className="flex min-w-0 items-center gap-[7px]">
                  <span className="truncate font-mono text-sm text-fg-bright" title={entry.job_id}>
                    {entry.job_id}
                  </span>
                  <CopyButton value={entry.job_id} label="Job ID" silent />
                </span>

                <span className="truncate font-mono text-sm text-pending" title={entry.error_type}>
                  {entry.error_type}
                </span>

                <span className="truncate text-sm text-fg-muted" title={entry.last_error}>
                  {truncate(entry.last_error, 70)}
                </span>

                <span className="tabular font-mono text-sm text-failed">{entry.retry_count}</span>

                <RelativeTime
                  value={entry.failed_at}
                  className="tabular font-mono text-sm text-fg-faint"
                />

                <span>
                  {entry.resolved ? (
                    <span className="inline-flex items-center gap-1.5 rounded bg-success/[0.12] px-2 py-0.5 text-xs font-medium text-success">
                      <span className="h-1.5 w-1.5 rounded-full bg-success" />
                      Resolved
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 rounded bg-failed/[0.12] px-2 py-0.5 text-xs font-medium text-failed">
                      <span className="h-1.5 w-1.5 rounded-full bg-failed" />
                      Open
                    </span>
                  )}
                </span>

                <span
                  className="flex items-center justify-end gap-1"
                  onClick={(event) => event.stopPropagation()}
                >
                  <button
                    type="button"
                    aria-label={`Retry ${entry.job_id}`}
                    title="Retry"
                    disabled={entry.resolved || retry.isPending}
                    onClick={() => retry.mutate(entry.id)}
                    className="inline-flex h-[26px] w-[26px] items-center justify-center rounded-md text-fg-dim transition-colors hover:bg-line hover:text-accent-light disabled:pointer-events-none disabled:opacity-30"
                  >
                    <Icon path={BULK_ICONS.retry} />
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete ${entry.job_id}`}
                    title="Delete"
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(entry.id)}
                    className="inline-flex h-[26px] w-[26px] items-center justify-center rounded-md text-fg-dim transition-colors hover:bg-line hover:text-failed disabled:pointer-events-none disabled:opacity-30"
                  >
                    <Icon path={BULK_ICONS.delete} />
                  </button>
                </span>
              </div>

              <div className="border-b border-line-subtle" />

              {isOpen ? (
                <div className="animate-slide-down border-b border-line-subtle bg-canvas-sunken px-4 pb-4 pt-3">
                  <div className="mb-3 flex flex-wrap items-center gap-4 text-sm">
                    <span className="text-fg-dim">
                      Reason{' '}
                      <span className="font-mono text-failed">
                        {failureReasonLabel(entry.failure_reason)}
                      </span>
                    </span>
                    <span className="text-fg-dim">
                      Runtime <span className={cn('font-mono', runtime.text)}>{runtime.label}</span>
                    </span>
                    <span className="text-fg-dim">
                      User <span className="font-mono text-fg-muted">{entry.user_email}</span>
                    </span>
                    {entry.manual_retry_count > 0 ? (
                      <span className="text-fg-dim">
                        Manual retries{' '}
                        <span className="font-mono text-fg-muted">{entry.manual_retry_count}</span>
                      </span>
                    ) : null}
                    <Button
                      variant="secondary"
                      size="sm"
                      className="ml-auto bg-surface"
                      onClick={() => router.push(`/jobs/${entry.job_id}`)}
                    >
                      Open job →
                    </Button>
                  </div>

                  {/* Nima qilish kerakligi — traceback'dan OLDIN, chunki
                      foydalanuvchiga eng kerakli narsa shu */}
                  <DlqFixHint reason={entry.failure_reason} className="mb-3" />

                  <div className="mb-1.5 text-xs font-semibold text-fg-dim">Traceback</div>
                  <pre className="m-0 max-h-[320px] overflow-auto whitespace-pre rounded-lg border border-failed/[0.18] bg-failed/[0.06] px-3.5 py-3 font-mono text-[11.5px] leading-[1.65] text-failed-text">
                    {entry.traceback}
                  </pre>

                  {entry.notes ? (
                    <div className="mt-3 rounded-lg border border-line-inner bg-surface px-3.5 py-2.5 text-sm text-fg-muted">
                      <span className="font-semibold text-fg-soft">Note: </span>
                      {entry.notes}
                    </div>
                  ) : null}

                  {/* Asl kod va payload — xatoni tahlil qilish uchun shu
                      yerda kerak, boshqa sahifaga o'tmasdan */}
                  <DlqOriginal jobId={entry.job_id} />

                  {onEditRetry ? (
                    <div className="mt-3 flex justify-end">
                      <Button variant="primary" size="sm" onClick={() => onEditRetry(entry)}>
                        Edit &amp; retry
                      </Button>
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          )
        })
      )}
    </div>
  )
}

function Icon({ path }: { path: string }) {
  return (
    <svg
      width="13"
      height="13"
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

/**
 * DLQ yozuvining asl kodi va payload'i.
 *
 * Job alohida so'raladi, chunki `DlqEntry` da kod yo'q (ro'yxat yengil
 * bo'lishi uchun) — va faqat yozuv OCHILGANDA so'raladi, aks holda 15 ta
 * yopiq qator 15 ta keraksiz so'rov yasaydi.
 */
function DlqOriginal({ jobId }: { jobId: string }) {
  const job = useJob(jobId)

  if (job.isLoading) {
    return <Skeleton className="mt-3 h-24 w-full" />
  }
  if (!job.data) return null

  return (
    <div className="mt-3 grid gap-3 xl:grid-cols-2">
      <div>
        <div className="mb-1.5 text-xs font-semibold text-fg-dim">Submitted code</div>
        <CodeBlock
          code={job.data.code}
          runtime={job.data.runtime}
          collapsible={false}
          defaultOpen
          maxHeight={220}
        />
      </div>
      <div>
        <div className="mb-1.5 text-xs font-semibold text-fg-dim">Payload</div>
        <JsonViewer data={job.data.payload ?? null} rootLabel="payload" maxHeight={220} />
      </div>
    </div>
  )
}

/** DLQ eksporti uchun ustunlar — traceback QO'SHILMAYDI (CSV o'qilmay qoladi). */
export const DLQ_CSV_COLUMNS: CsvColumn<DlqEntry>[] = [
  { header: 'id', value: (e) => e.id },
  { header: 'job_id', value: (e) => e.job_id },
  { header: 'user_email', value: (e) => e.user_email },
  { header: 'runtime', value: (e) => e.runtime },
  { header: 'failure_reason', value: (e) => e.failure_reason },
  { header: 'error_type', value: (e) => e.error_type },
  { header: 'last_error', value: (e) => e.last_error },
  { header: 'failed_at', value: (e) => e.failed_at },
  { header: 'retry_count', value: (e) => e.retry_count },
  { header: 'manual_retry_count', value: (e) => e.manual_retry_count },
  { header: 'resolved', value: (e) => e.resolved },
]
