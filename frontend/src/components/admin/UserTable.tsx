'use client'

import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { EmptyState } from '@/components/common/EmptyState'
import { RelativeTime } from '@/components/common/RelativeTime'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { SkeletonRows } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils/cn'
import type { CsvColumn } from '@/lib/utils/csv'
import { formatNumber } from '@/lib/utils/format'
import { Checkbox } from '@/components/ui/checkbox'
import {
  useReactivateUser,
  useResetUserKeys,
  useSuspendUser,
  useUpdateAdminUser,
} from '@/lib/hooks/useAdmin'
import { PLAN_TYPES, type AdminUser, type PlanType } from '@/types'

/**
 * Admin foydalanuvchilar jadvali.
 *
 * HIMOYA: admin O'ZINING huquqini yoki faolligini o'zgartira olmaydi —
 * aks holda oxirgi admin o'zini o'chirib tizimni qulflab qo'yishi mumkin.
 * Backend ham shu qoidani tekshiradi (403), UI esa tugmani o'chiradi.
 */
const GRID_BASE = 'minmax(160px,1.6fr) 100px 90px 90px 80px minmax(90px,1fr) 44px'
const GRID_SELECT = `34px ${GRID_BASE}`

const PLAN_BADGE: Record<PlanType, string> = {
  free: 'bg-surface-3 text-fg-muted',
  starter: 'bg-running/[0.12] text-running',
  pro: 'bg-accent/[0.14] text-accent-light',
  enterprise: 'bg-success/[0.12] text-success',
}

export function UserTable({
  users,
  loading = false,
  currentUserId,
  onViewJobs,
  onOpenDetail,
  onImpersonate,
  onOpenFullPage,
  selected,
  onToggleSelect,
  onToggleAll,
  sort,
  onSort,
}: {
  users: AdminUser[] | undefined
  loading?: boolean
  currentUserId: string
  onViewJobs?: (user: AdminUser) => void
  onOpenDetail?: (user: AdminUser) => void
  onImpersonate?: (user: AdminUser) => void
  /** To'liq foydalanuvchi sahifasiga o'tish (`/admin/users/{id}`). */
  onOpenFullPage?: (user: AdminUser) => void
  selected?: string[]
  onToggleSelect?: (id: string) => void
  onToggleAll?: () => void
  sort?: { field: string; order: 'asc' | 'desc' }
  onSort?: (field: string) => void
}) {
  const update = useUpdateAdminUser()
  const suspend = useSuspendUser()
  const reactivate = useReactivateUser()
  const resetKeys = useResetUserKeys()
  const [confirm, setConfirm] = useState<{
    user: AdminUser
    action: 'deactivate' | 'demote' | 'reset-keys'
  } | null>(null)

  const activeAdmins = (users ?? []).filter((u) => u.is_admin && u.is_active).length
  const selectable = selected !== undefined && onToggleSelect !== undefined
  const allSelected =
    selectable && (users?.length ?? 0) > 0 && users!.every((u) => selected!.includes(u.id))

  return (
    <>
      <div className="overflow-hidden rounded-2xl border border-line bg-surface">
        <div
          className="table-head grid items-center px-3.5"
          style={{ gridTemplateColumns: selectable ? GRID_SELECT : GRID_BASE }}
        >
          {selectable ? (
            <Checkbox
              checked={allSelected}
              indeterminate={!allSelected && selected!.length > 0}
              onToggle={() => onToggleAll?.()}
              aria-label="Select all users on this page"
            />
          ) : null}
          <span>User</span>
          <span>Plan</span>
          <SortHeader field="jobs_this_period" label="Jobs" sort={sort} onSort={onSort} align="right" />
          <SortHeader field="dlq_depth" label="DLQ" sort={sort} onSort={onSort} align="right" />
          <SortHeader field="api_key_count" label="Keys" sort={sort} onSort={onSort} />
          <SortHeader field="last_login_at" label="Last login" sort={sort} onSort={onSort} />
          <span className="sr-only">Actions</span>
        </div>

        {loading && !users ? (
          <SkeletonRows rows={12} columns={selectable ? GRID_SELECT : GRID_BASE} />
        ) : !users || users.length === 0 ? (
          <EmptyState
            icon="M16 19v-2a4 4 0 0 0-8 0v2M12 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"
            title="No users match your filters"
          />
        ) : (
          users.map((user) => {
            const isSelf = user.id === currentUserId
            // Oxirgi faol adminni tushirish taqiqlanadi
            const isLastAdmin = user.is_admin && user.is_active && activeAdmins <= 1

            return (
              <div
                key={user.id}
                className={cn(
                  'grid h-12 items-center border-b border-line-subtle px-3.5 last:border-b-0 transition-colors',
                  selected?.includes(user.id) ? 'bg-accent/[0.06]' : 'hover:bg-surface-3',
                  !user.is_active && 'opacity-60',
                )}
                style={{ gridTemplateColumns: selectable ? GRID_SELECT : GRID_BASE }}
              >
                {selectable ? (
                  <Checkbox
                    checked={selected!.includes(user.id)}
                    onToggle={() => onToggleSelect!(user.id)}
                    aria-label={`Select ${user.email}`}
                  />
                ) : null}
                <span className="flex min-w-0 items-center gap-2.5">
                  <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-line text-xs font-semibold text-fg-soft">
                    {user.initials}
                  </span>
                  <span className="min-w-0">
                    <span className="flex items-center gap-1.5">
                      {onOpenDetail ? (
                        <button
                          type="button"
                          onClick={() => onOpenDetail(user)}
                          className="truncate text-left text-base text-fg-soft transition-colors hover:text-accent-light"
                          title={user.email}
                        >
                          {user.email}
                        </button>
                      ) : (
                        <span className="truncate text-base text-fg-soft" title={user.email}>
                          {user.email}
                        </span>
                      )}
                      {user.is_admin ? (
                        <Badge size="sm" variant="danger" className="shrink-0">
                          admin
                        </Badge>
                      ) : null}
                      {!user.is_active ? (
                        <Badge size="sm" variant="outline" className="shrink-0">
                          inactive
                        </Badge>
                      ) : null}
                    </span>
                    <span className="block truncate text-xs text-fg-faint">
                      {user.full_name ?? '—'}
                    </span>
                  </span>
                </span>

                <span>
                  <Badge className={PLAN_BADGE[user.plan]}>{user.plan}</Badge>
                </span>

                <span className="tabular text-right font-mono text-sm text-fg-muted">
                  {formatNumber(user.jobs_this_period)}
                </span>

                <span
                  className={cn(
                    'tabular text-right font-mono text-sm',
                    user.dlq_depth > 0 ? 'text-failed' : 'text-fg-faint',
                  )}
                >
                  {user.dlq_depth}
                </span>

                <span className="tabular font-mono text-sm text-fg-faint">
                  {user.api_key_count}
                </span>

                <RelativeTime
                  value={user.last_login_at}
                  className="tabular font-mono text-sm text-fg-faint"
                />

                <span className="flex justify-end">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button
                        type="button"
                        aria-label={`Actions for ${user.email}`}
                        className="inline-flex h-[26px] w-[26px] items-center justify-center rounded-md text-fg-dim transition-colors hover:bg-line hover:text-fg"
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                          <circle cx="12" cy="5" r="1.6" />
                          <circle cx="12" cy="12" r="1.6" />
                          <circle cx="12" cy="19" r="1.6" />
                        </svg>
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent className="min-w-[190px]">
                      {onOpenDetail ? (
                        <DropdownMenuItem onSelect={() => onOpenDetail(user)}>
                          Quick look
                        </DropdownMenuItem>
                      ) : null}
                      {onOpenFullPage ? (
                        <DropdownMenuItem onSelect={() => onOpenFullPage(user)}>
                          Open full profile
                        </DropdownMenuItem>
                      ) : null}
                      {onViewJobs ? (
                        <DropdownMenuItem onSelect={() => onViewJobs(user)}>
                          View their jobs
                        </DropdownMenuItem>
                      ) : null}
                      {onImpersonate ? (
                        <DropdownMenuItem
                          disabled={user.is_admin || !user.is_active}
                          onSelect={() => onImpersonate(user)}
                        >
                          View as user
                          {user.is_admin ? (
                            <span className="ml-auto text-xs text-fg-faint">admin</span>
                          ) : null}
                        </DropdownMenuItem>
                      ) : null}

                      <DropdownMenuSeparator />
                      <DropdownMenuLabel>Change plan</DropdownMenuLabel>
                      {PLAN_TYPES.map((plan) => (
                        <DropdownMenuItem
                          key={plan}
                          disabled={user.plan === plan}
                          onSelect={() => update.mutate({ id: user.id, patch: { plan } })}
                        >
                          {plan}
                          {user.plan === plan ? (
                            <span className="ml-auto text-xs text-fg-faint">current</span>
                          ) : null}
                        </DropdownMenuItem>
                      ))}

                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        disabled={isSelf || isLastAdmin}
                        onSelect={() => {
                          if (user.is_admin) setConfirm({ user, action: 'demote' })
                          else update.mutate({ id: user.id, patch: { is_admin: true } })
                        }}
                      >
                        {user.is_admin ? 'Remove admin' : 'Make admin'}
                        {isSelf ? (
                          <span className="ml-auto text-xs text-fg-faint">you</span>
                        ) : isLastAdmin ? (
                          <span className="ml-auto text-xs text-fg-faint">last</span>
                        ) : null}
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        danger={user.is_active}
                        disabled={isSelf}
                        onSelect={() => {
                          if (user.is_active) setConfirm({ user, action: 'deactivate' })
                          else reactivate.mutate(user.id)
                        }}
                      >
                        {user.is_active ? 'Suspend' : 'Reactivate'}
                        {isSelf ? <span className="ml-auto text-xs text-fg-faint">you</span> : null}
                      </DropdownMenuItem>
                      <DropdownMenuItem
                        danger
                        disabled={user.api_key_count === 0}
                        onSelect={() => setConfirm({ user, action: 'reset-keys' })}
                      >
                        Reset API keys
                        <span className="ml-auto text-xs text-fg-faint">{user.api_key_count}</span>
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </span>
              </div>
            )
          })
        )}
      </div>

      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(open) => {
          if (!open) setConfirm(null)
        }}
        title={
          confirm?.action === 'demote'
            ? 'Remove admin access?'
            : confirm?.action === 'reset-keys'
              ? 'Reset all API keys?'
              : 'Suspend user?'
        }
        description={
          confirm
            ? confirm.action === 'demote'
              ? `${confirm.user.email} will lose access to the admin panel.`
              : confirm.action === 'reset-keys'
                ? `All ${confirm.user.api_key_count} API keys for ${confirm.user.email} are revoked immediately. Any integration using them stops working.`
                : `${confirm.user.email} will be signed out, their API keys stop working and running jobs are cancelled.`
            : ''
        }
        confirmLabel={
          confirm?.action === 'demote'
            ? 'Remove admin'
            : confirm?.action === 'reset-keys'
              ? 'Revoke keys'
              : 'Suspend'
        }
        destructive
        pending={update.isPending || suspend.isPending || resetKeys.isPending}
        onConfirm={() => {
          if (!confirm) return
          if (confirm.action === 'demote') {
            update.mutate({ id: confirm.user.id, patch: { is_admin: false } })
          } else if (confirm.action === 'reset-keys') {
            resetKeys.mutate(confirm.user.id)
          } else {
            suspend.mutate(confirm.user.id)
          }
          setConfirm(null)
        }}
      />
    </>
  )
}

/** Sortlanadigan ustun sarlavhasi — bosilganda yo'nalish almashadi. */
function SortHeader({
  field,
  label,
  sort,
  onSort,
  align = 'left',
}: {
  field: string
  label: string
  sort?: { field: string; order: 'asc' | 'desc' }
  onSort?: (field: string) => void
  align?: 'left' | 'right'
}) {
  if (!onSort) {
    return <span className={align === 'right' ? 'text-right' : undefined}>{label}</span>
  }
  const active = sort?.field === field
  return (
    <button
      type="button"
      onClick={() => onSort(field)}
      className={cn(
        'flex items-center gap-1 transition-colors hover:text-fg-muted',
        align === 'right' && 'justify-end',
        active && 'text-fg-muted',
      )}
    >
      {label}
      <span
        className={cn(
          'text-[9px] leading-none transition-opacity',
          active ? 'opacity-100' : 'opacity-0',
        )}
        aria-hidden
      >
        {sort?.order === 'asc' ? '▲' : '▼'}
      </span>
    </button>
  )
}

/** Admin eksporti uchun ustunlar. */
export const USER_CSV_COLUMNS: CsvColumn<AdminUser>[] = [
  { header: 'id', value: (u) => u.id },
  { header: 'email', value: (u) => u.email },
  { header: 'full_name', value: (u) => u.full_name ?? '' },
  { header: 'plan', value: (u) => u.plan },
  { header: 'is_active', value: (u) => u.is_active },
  { header: 'is_admin', value: (u) => u.is_admin },
  { header: 'jobs_this_period', value: (u) => u.jobs_this_period },
  { header: 'job_count', value: (u) => u.job_count },
  { header: 'dlq_depth', value: (u) => u.dlq_depth },
  { header: 'api_key_count', value: (u) => u.api_key_count },
  { header: 'created_at', value: (u) => u.created_at },
  { header: 'last_login_at', value: (u) => u.last_login_at ?? '' },
]
