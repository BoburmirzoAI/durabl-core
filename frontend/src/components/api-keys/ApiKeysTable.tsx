'use client'

import { useState } from 'react'

import { CopyButton } from '@/components/common/CopyButton'
import { EmptyState } from '@/components/common/EmptyState'
import { RelativeTime } from '@/components/common/RelativeTime'
import { Badge } from '@/components/ui/badge'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { SkeletonRows } from '@/components/ui/skeleton'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { useRevokeApiKey } from '@/lib/hooks/useApiKeys'
import { cn } from '@/lib/utils/cn'
import { formatDate } from '@/lib/utils/time'
import type { ApiKey } from '@/types'
import { useCopy } from '@/lib/hooks/useCopy'

/**
 * API kalitlar jadvali — dizayndagi ustunlar:
 * `minmax(80px,1fr) minmax(140px,1.2fr) 80px 84px 92px 84px 40px`
 */
const GRID = 'minmax(80px,1fr) minmax(150px,1.2fr) 86px 92px 110px 90px 44px'

export function ApiKeysTable({
  keys,
  loading = false,
  onCreate,
  onOpenDetail,
  onRotate,
}: {
  keys: ApiKey[] | undefined
  loading?: boolean
  onCreate?: () => void
  /** Qator bosilganda tafsilot panelini ochadi. */
  onOpenDetail?: (key: ApiKey) => void
  onRotate?: (key: ApiKey) => void
}) {
  const revoke = useRevokeApiKey()
  const copy = useCopy()
  const [confirmKey, setConfirmKey] = useState<ApiKey | null>(null)

  return (
    <>
      <div className="overflow-hidden rounded-2xl border border-line bg-surface">
        <div className="table-head grid items-center px-4" style={{ gridTemplateColumns: GRID }}>
          <span>Name</span>
          <span>Key</span>
          <span>Created</span>
          <span>Last Used</span>
          <span>Permissions</span>
          <span>Status</span>
          <span className="sr-only">Actions</span>
        </div>

        {loading && !keys ? (
          <SkeletonRows rows={4} columns={GRID} />
        ) : !keys || keys.length === 0 ? (
          <EmptyState
            icon="M10 14a5 5 0 1 1 5-5l6 6-2 2-2-2-2 2-2-2z"
            title="No API keys yet"
            description="Create a key to authenticate SDK and HTTP requests."
            action={
              onCreate ? (
                <button
                  type="button"
                  onClick={onCreate}
                  className="text-sm font-medium text-accent hover:text-accent-light"
                >
                  Create your first key →
                </button>
              ) : null
            }
          />
        ) : (
          keys.map((key) => {
            const expired = Boolean(key.expires_at && new Date(key.expires_at) < new Date())
            return (
              <div
                key={key.id}
                role={onOpenDetail ? 'button' : undefined}
                tabIndex={onOpenDetail ? 0 : undefined}
                onClick={onOpenDetail ? () => onOpenDetail(key) : undefined}
                onKeyDown={
                  onOpenDetail
                    ? (event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                          event.preventDefault()
                          onOpenDetail(key)
                        }
                      }
                    : undefined
                }
                className={cn(
                  'grid h-12 items-center border-b border-line-subtle px-4 last:border-b-0 transition-colors hover:bg-surface-3',
                  onOpenDetail &&
                    'cursor-pointer focus-visible:bg-surface-3 focus-visible:outline-none',
                )}
                style={{ gridTemplateColumns: GRID }}
              >
                <span className="truncate text-base text-fg-soft" title={key.name}>
                  {key.name}
                </span>

                <span className="flex min-w-0 items-center gap-[7px]">
                  <span className="truncate font-mono text-sm text-fg-muted" title={key.masked_key}>
                    {key.masked_key}
                  </span>
                  <span onClick={(event) => event.stopPropagation()}>
                    <CopyButton value={key.key_prefix} label="Key prefix" silent />
                  </span>
                </span>

                <span className="tabular font-mono text-sm text-fg-faint">
                  {formatDate(key.created_at)}
                </span>

                <RelativeTime
                  value={key.last_used_at}
                  className="tabular font-mono text-sm text-fg-faint"
                />

                <span className="flex flex-wrap gap-1">
                  {key.scopes.slice(0, 2).map((scope) => (
                    <Badge key={scope} size="sm" variant="outline" className="font-mono">
                      {scope.split(':')[1] ?? scope}
                    </Badge>
                  ))}
                  {key.scopes.length > 2 ? (
                    <Badge size="sm" variant="outline" title={key.scopes.join(', ')}>
                      +{key.scopes.length - 2}
                    </Badge>
                  ) : null}
                </span>

                <span>
                  {key.revoked_at ? (
                    <Badge variant="danger">Revoked</Badge>
                  ) : expired ? (
                    <Badge className="bg-pending/[0.12] text-pending">Expired</Badge>
                  ) : (
                    <Badge variant="success">Active</Badge>
                  )}
                </span>

                <span className="flex justify-end">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button
                        type="button"
                        aria-label={`Actions for ${key.name}`}
                        // Menyu qator bosilishini ochib yubormasligi kerak
                        onClick={(event) => event.stopPropagation()}
                        className="inline-flex h-[26px] w-[26px] items-center justify-center rounded-md text-fg-dim transition-colors hover:bg-line hover:text-fg"
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                          <circle cx="12" cy="5" r="1.6" />
                          <circle cx="12" cy="12" r="1.6" />
                          <circle cx="12" cy="19" r="1.6" />
                        </svg>
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent>
                      {onOpenDetail ? (
                        <DropdownMenuItem onSelect={() => onOpenDetail(key)}>
                          View usage & permissions
                        </DropdownMenuItem>
                      ) : null}
                      <DropdownMenuItem
                        onSelect={() => void copy(key.key_prefix, 'Key prefix copied')}
                      >
                        Copy prefix
                      </DropdownMenuItem>
                      {onRotate ? (
                        <DropdownMenuItem
                          disabled={Boolean(key.revoked_at)}
                          onSelect={() => onRotate(key)}
                        >
                          Rotate key
                        </DropdownMenuItem>
                      ) : null}
                      <DropdownMenuItem
                        danger
                        disabled={Boolean(key.revoked_at)}
                        onSelect={() => setConfirmKey(key)}
                      >
                        Revoke
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
        open={confirmKey !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmKey(null)
        }}
        title="Revoke API key?"
        description={
          confirmKey
            ? `Any client using "${confirmKey.name}" will immediately start receiving 401 responses. This cannot be undone.`
            : ''
        }
        confirmLabel="Revoke key"
        destructive
        pending={revoke.isPending}
        onConfirm={() => {
          if (confirmKey) revoke.mutate(confirmKey.id)
          setConfirmKey(null)
        }}
      />
    </>
  )
}
