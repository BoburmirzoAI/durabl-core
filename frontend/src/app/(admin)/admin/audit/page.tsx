'use client'

import { useState } from 'react'

import { ErrorState } from '@/components/common/ErrorState'
import { Pagination } from '@/components/common/Pagination'
import { CountPill, SectionHeader } from '@/components/common/SectionHeader'
import { useToast } from '@/components/common/ToastProvider'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { FilterSelect } from '@/components/ui/filter-select'
import { SearchField } from '@/components/ui/input'
import { SkeletonRows } from '@/components/ui/skeleton'
import { Tabs } from '@/components/ui/tabs'
import { useAuditLog } from '@/lib/hooks/useAdminOps'
import { useDebounce } from '@/lib/hooks/useDebounce'
import { useSearchFocus } from '@/lib/hooks/useKeyboard'
import { cn } from '@/lib/utils/cn'
import { downloadCsv, timestampedName, toCsv } from '@/lib/utils/csv'
import { formatNumber } from '@/lib/utils/format'
import { formatTimestamp } from '@/lib/utils/time'
import type { AuditCategory, AuditEntry } from '@/types'

const GRID = 'minmax(140px,.9fr) 92px minmax(160px,1.1fr) minmax(200px,1.6fr) minmax(130px,1fr) 84px'

const CATEGORY_OPTIONS = [
  { value: 'user', label: 'User' },
  { value: 'billing', label: 'Billing' },
  { value: 'security', label: 'Security' },
  { value: 'config', label: 'Config' },
  { value: 'job', label: 'Job' },
  { value: 'system', label: 'System' },
]

const CATEGORY_CLASS: Record<AuditCategory, string> = {
  user: 'bg-accent/[0.12] text-accent-light',
  billing: 'bg-success/[0.12] text-success',
  security: 'bg-failed/[0.12] text-failed',
  config: 'bg-pending/[0.12] text-pending',
  job: 'bg-running/[0.12] text-running',
  system: 'bg-surface-4 text-fg-muted',
}

const AUDIT_CSV_COLUMNS = [
  { header: 'at', value: (e: AuditEntry) => e.at },
  { header: 'category', value: (e: AuditEntry) => e.category },
  { header: 'action', value: (e: AuditEntry) => e.action },
  { header: 'actor', value: (e: AuditEntry) => e.actor },
  { header: 'target', value: (e: AuditEntry) => e.target },
  { header: 'summary', value: (e: AuditEntry) => e.summary },
  { header: 'before', value: (e: AuditEntry) => e.before ?? '' },
  { header: 'after', value: (e: AuditEntry) => e.after ?? '' },
  { header: 'ip', value: (e: AuditEntry) => e.ip },
  { header: 'result', value: (e: AuditEntry) => e.result },
]

/**
 * Audit jurnali.
 *
 * ═══════════════════════════════════════════════════════════════════
 * NEGA FAOLLIK OQIMIDAN ALOHIDA
 * ═══════════════════════════════════════════════════════════════════
 *
 * `/admin` dagi faollik lentasi — JONLI oqim: "hozir nima bo'layapti".
 * U tez eskiradi va saqlanmaydi.
 *
 * Audit esa IZ: "kim, qachon, nimani o'zgartirdi va qaysi qiymatdan
 * qaysi qiymatga". Bu savol xavfsizlik tekshiruvida, mijoz shikoyatida
 * va "bu sozlamani kim buzdi?" holatida chiqadi.
 *
 * Shuning uchun bu yerda `before → after` ustuni bor va RAD ETILGAN
 * urinishlar ham yoziladi: kimdir nimadir qilmoqchi bo'lganini bilish
 * ba'zan qilganini bilishdan muhimroq.
 */
export default function AdminAuditPage() {
  const [search, setSearch] = useState('')
  const [categories, setCategories] = useState<AuditCategory[]>([])
  const [result, setResult] = useState<'all' | AuditEntry['result']>('all')
  const [page, setPage] = useState(1)
  const searchRef = useSearchFocus()
  const { toast } = useToast()

  const debounced = useDebounce(search, 300)
  const query = useAuditLog({
    search: debounced || undefined,
    category: categories.length ? categories : undefined,
    result: result === 'all' ? undefined : [result],
    page,
    page_size: 25,
  })

  const rows = query.data?.items ?? []
  const denied = rows.filter((e) => e.result !== 'success').length

  return (
    <>
      <SectionHeader
        title="Audit log"
        description="Who changed what, and what the value was before"
        count={
          query.data ? <CountPill>{formatNumber(query.data.pagination.total)}</CountPill> : null
        }
        actions={
          <Button
            variant="secondary"
            onClick={() => {
              if (rows.length === 0) {
                toast({ title: 'Nothing to export' })
                return
              }
              downloadCsv(timestampedName('durabl-audit'), toCsv(rows, AUDIT_CSV_COLUMNS))
              toast({
                title: `Exported ${rows.length} entries`,
                description: 'Current page, with the active filters applied.',
              })
            }}
          >
            Export CSV
          </Button>
        }
      />

      {denied > 0 && result === 'all' ? (
        <div className="rounded-xl border border-pending/25 bg-pending/[0.07] px-4 py-2.5 text-sm text-pending">
          {denied} of the entries on this page were denied or errored. Those are usually the
          interesting ones.
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2.5">
        <SearchField
          ref={searchRef}
          shortcut="/"
          placeholder="Search action, actor, target…"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
            setPage(1)
          }}
          containerClassName="w-[300px]"
          aria-label="Search the audit log"
        />
        <FilterSelect
          prefix="Category:"
          options={CATEGORY_OPTIONS}
          value={categories}
          onToggle={(value) => {
            const category = value as AuditCategory
            setCategories((current) =>
              current.includes(category)
                ? current.filter((c) => c !== category)
                : [...current, category],
            )
            setPage(1)
          }}
          onClear={() => setCategories([])}
        />
        <Tabs
          aria-label="Result"
          items={[
            { value: 'all' as const, label: 'All' },
            { value: 'success' as const, label: 'Succeeded' },
            { value: 'denied' as const, label: 'Denied' },
            { value: 'error' as const, label: 'Errored' },
          ]}
          value={result}
          onChange={(value) => {
            setResult(value)
            setPage(1)
          }}
        />
      </div>

      {query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          <div className="overflow-hidden rounded-2xl border border-line bg-surface">
            <div className="overflow-x-auto">
              <div className="min-w-[900px]">
                <div
                  className="table-head grid items-center gap-3 px-4"
                  style={{ gridTemplateColumns: GRID }}
                >
                  <span>When</span>
                  <span>Category</span>
                  <span>Actor</span>
                  <span>What happened</span>
                  <span>Change</span>
                  <span>Result</span>
                </div>

                {query.isLoading && !query.data ? (
                  <SkeletonRows rows={8} columns={GRID} />
                ) : (
                  rows.map((entry) => (
                    <div
                      key={entry.id}
                      className="grid min-h-[52px] items-center gap-3 border-b border-line-subtle px-4 py-2 last:border-b-0 hover:bg-surface-3"
                      style={{ gridTemplateColumns: GRID }}
                    >
                      <span className="tabular truncate font-mono text-xs text-fg-muted">
                        {formatTimestamp(entry.at).replace(' UTC', '')}
                      </span>

                      <span>
                        <Badge size="sm" className={CATEGORY_CLASS[entry.category]}>
                          {entry.category}
                        </Badge>
                      </span>

                      <span className="min-w-0">
                        <span className="block truncate text-sm text-fg-soft">{entry.actor}</span>
                        <span className="tabular block truncate font-mono text-2xs text-fg-ghost">
                          {entry.ip}
                        </span>
                      </span>

                      <span className="min-w-0">
                        <span className="block truncate text-sm text-fg-soft">{entry.summary}</span>
                        <span className="flex items-center gap-1.5 text-2xs text-fg-faint">
                          <code className="font-mono">{entry.action}</code>
                          <span className="text-fg-ghost">·</span>
                          <span className="truncate font-mono">{entry.target}</span>
                        </span>
                      </span>

                      <span className="min-w-0 truncate text-xs">
                        {entry.before === null && entry.after === null ? (
                          <span className="text-fg-ghost">—</span>
                        ) : (
                          <>
                            <span className="font-mono text-fg-faint line-through">
                              {entry.before ?? '∅'}
                            </span>
                            <span className="mx-1.5 text-fg-ghost">→</span>
                            <span className="font-mono text-fg-soft">{entry.after ?? '∅'}</span>
                          </>
                        )}
                      </span>

                      <span>
                        <span
                          className={cn(
                            'text-xs',
                            entry.result === 'success'
                              ? 'text-success'
                              : entry.result === 'denied'
                                ? 'text-pending'
                                : 'text-failed-text',
                          )}
                        >
                          {entry.result}
                        </span>
                      </span>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          {query.data ? (
            <Pagination pagination={query.data.pagination} onPageChange={setPage} />
          ) : null}
        </>
      )}
    </>
  )
}
