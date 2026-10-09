'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { CountPill, SectionHeader } from '@/components/common/SectionHeader'
import { ErrorState } from '@/components/common/ErrorState'
import { Pagination } from '@/components/common/Pagination'
import { BULK_ICONS, BulkActionBar } from '@/components/common/BulkActionBar'
import { CreateUserDialog } from '@/components/admin/CreateUserDialog'
import { UserDetailSheet } from '@/components/admin/UserDetailSheet'
import { USER_CSV_COLUMNS, UserTable } from '@/components/admin/UserTable'
import { Button } from '@/components/ui/button'
import { FilterSelect } from '@/components/ui/filter-select'
import { SearchField } from '@/components/ui/input'
import { Tabs } from '@/components/ui/tabs'
import { useAdminUsers, useBulkChangePlan, useBulkSuspendUsers } from '@/lib/hooks/useAdmin'
import { useDebounce } from '@/lib/hooks/useDebounce'
import { currentUser } from '@/lib/auth'
import { formatNumber } from '@/lib/utils/format'
import { PLAN_TYPES, type AdminUser, type PlanType } from '@/types'
import { useToast } from '@/components/common/ToastProvider'
import { downloadCsv, timestampedName, toCsv } from '@/lib/utils/csv'
import { useImpersonationStore } from '@/stores/impersonationStore'
import { useSelectionStore } from '@/stores/selectionStore'
import { useSearchFocus } from '@/lib/hooks/useKeyboard'

const PLAN_OPTIONS = PLAN_TYPES.map((plan) => ({ value: plan, label: plan }))

/** Tanlov doirasi — boshqa jadvallar bilan aralashmasligi uchun. */
const SCOPE = 'admin-users'

/** Barqaror bo'sh massiv — Zustand selektori uchun (cheksiz render oldini oladi). */
const EMPTY_IDS: string[] = []

/** Admin — foydalanuvchilar boshqaruvi. */
export default function AdminUsersPage() {
  const router = useRouter()
  const me = currentUser()

  const [search, setSearch] = useState('')
  const searchRef = useSearchFocus()
  const { toast } = useToast()
  const [plans, setPlans] = useState<PlanType[]>([])
  const [state, setState] = useState<'all' | 'active' | 'inactive' | 'admin'>('all')
  const [page, setPage] = useState(1)
  const [sort, setSort] = useState<{ field: string; order: 'asc' | 'desc' }>({
    field: 'jobs_this_period',
    order: 'desc',
  })
  const selected = useSelectionStore((s) => s.selected[SCOPE] ?? EMPTY_IDS)
  const setMany = useSelectionStore((s) => s.setMany)
  const toggleSelect = useSelectionStore((s) => s.toggle)
  const clearSelection = useSelectionStore((s) => s.clear)
  const [detailId, setDetailId] = useState<string | null>(null)

  const startImpersonation = useImpersonationStore((s) => s.start)
  const bulkSuspend = useBulkSuspendUsers()
  const bulkPlan = useBulkChangePlan()

  const debouncedSearch = useDebounce(search, 300)
  const query = useAdminUsers({
    search: debouncedSearch || undefined,
    plan: plans.length ? plans : undefined,
    is_active: state === 'active' ? true : state === 'inactive' ? false : undefined,
    is_admin: state === 'admin' ? true : undefined,
    sort_by: sort.field,
    sort_order: sort.order,
    page,
    page_size: 25,
  })

  const rows = query.data?.items ?? []

  /** Ustun bosilganda: ayni ustun bo'lsa yo'nalish almashadi. */
  const toggleSort = (field: string) => {
    setSort((current) =>
      current.field === field
        ? { field, order: current.order === 'desc' ? 'asc' : 'desc' }
        : { field, order: 'desc' },
    )
    setPage(1)
  }

  const [createOpen, setCreateOpen] = useState(false)

  const impersonate = (user: AdminUser) => {
    startImpersonation(user)
    setDetailId(null)
    router.push('/dashboard')
  }

  return (
    <>
      <SectionHeader
        title="Users"
        description="Every account on this deployment"
        count={query.data ? <CountPill>{formatNumber(query.data.pagination.total)}</CountPill> : null}
        actions={
          <>
            <Button
              variant="secondary"
              onClick={() => {
                if (rows.length === 0) {
                  toast({ title: 'Nothing to export' })
                  return
                }
                downloadCsv(timestampedName('durabl-users'), toCsv(rows, USER_CSV_COLUMNS))
                toast({
                  title: `Exported ${rows.length} users`,
                  description: 'Current page, with the active filters applied.',
                })
              }}
            >
              Export CSV
            </Button>
            <Button variant="primary" size="md" onClick={() => setCreateOpen(true)}>
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" aria-hidden>
                <path d="M12 5v14M5 12h14" />
              </svg>
              Create user
            </Button>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2.5">
        <SearchField
          ref={searchRef}
          shortcut="/"
          placeholder="Search email or name…"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value)
            setPage(1)
          }}
          containerClassName="w-[280px]"
          aria-label="Search users"
        />
        <FilterSelect
          prefix="Plan:"
          options={PLAN_OPTIONS}
          value={plans}
          onToggle={(value) => {
            const plan = value as PlanType
            setPlans((current) =>
              current.includes(plan) ? current.filter((p) => p !== plan) : [...current, plan],
            )
            setPage(1)
          }}
          onClear={() => setPlans([])}
        />
        <Tabs
          aria-label="Account state"
          items={[
            { value: 'all' as const, label: 'All' },
            { value: 'active' as const, label: 'Active' },
            { value: 'inactive' as const, label: 'Inactive' },
            { value: 'admin' as const, label: 'Admins' },
          ]}
          value={state}
          onChange={(value) => {
            setState(value)
            setPage(1)
          }}
        />
      </div>

      {query.error ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : (
        <>
          {/* Bulk panel jadval sarlavhasi USTIDA paydo bo'ladi */}
          <div className="relative">
            <BulkActionBar
              scope={SCOPE}
              actions={[
                {
                  label: 'Suspend',
                  icon: BULK_ICONS.cancel,
                  iconClassName: 'text-failed',
                  disabled: bulkSuspend.isPending,
                  onClick: (ids) => {
                    bulkSuspend.mutate(ids)
                    clearSelection(SCOPE)
                  },
                },
                {
                  label: 'Move to pro',
                  icon: BULK_ICONS.retry,
                  disabled: bulkPlan.isPending,
                  onClick: (ids) => {
                    bulkPlan.mutate({ ids, plan: 'pro' })
                    clearSelection(SCOPE)
                  },
                },
                {
                  label: 'Move to free',
                  icon: BULK_ICONS.retry,
                  disabled: bulkPlan.isPending,
                  onClick: (ids) => {
                    bulkPlan.mutate({ ids, plan: 'free' })
                    clearSelection(SCOPE)
                  },
                },
              ]}
            />
            <UserTable
            users={rows}
            loading={query.isLoading}
            currentUserId={me.id}
            onViewJobs={(user) => router.push(`/admin/jobs?user=${encodeURIComponent(user.email)}`)}
            onOpenDetail={(user) => setDetailId(user.id)}
            onOpenFullPage={(user) => router.push(`/admin/users/${user.id}`)}
            onImpersonate={impersonate}
            selected={selected}
            onToggleSelect={(id) => toggleSelect(SCOPE, id)}
            onToggleAll={() =>
              setMany(SCOPE, selected.length === rows.length ? [] : rows.map((u) => u.id))
            }
            sort={sort}
            onSort={toggleSort}
            />
          </div>
          {query.data ? (
            <Pagination pagination={query.data.pagination} onPageChange={setPage} />
          ) : null}
        </>
      )}

      <UserDetailSheet
        userId={detailId}
        onOpenChange={(open) => {
          if (!open) setDetailId(null)
        }}
        onViewJobs={(user) => {
          setDetailId(null)
          router.push(`/admin/jobs?user=${encodeURIComponent(user.email)}`)
        }}
        onImpersonate={impersonate}
        onOpenFullPage={(user) => {
          setDetailId(null)
          router.push(`/admin/users/${user.id}`)
        }}
      />

      <CreateUserDialog open={createOpen} onOpenChange={setCreateOpen} />
    </>
  )
}
