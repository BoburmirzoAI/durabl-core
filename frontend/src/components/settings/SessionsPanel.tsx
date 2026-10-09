'use client'

import { useState } from 'react'

import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { RelativeTime } from '@/components/common/RelativeTime'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { SkeletonRows } from '@/components/ui/skeleton'
import { useRevokeOtherSessions, useRevokeSession, useSessions } from '@/lib/hooks/useAccount'
import { formatDate } from '@/lib/utils/time'
import type { UserSession } from '@/types'

const GRID = 'minmax(150px,1.4fr) minmax(130px,1fr) 120px 110px 92px'

const DEVICE_ICON: Record<UserSession['device_type'], string> = {
  desktop: 'M3 5h18v11H3zM8 20h8M12 16v4',
  mobile: 'M8 3h8a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM11 18h2',
  tablet: 'M6 3h12a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zM11 18h2',
  api: 'M8 6 3 12l5 6M16 6l5 6-5 6',
}

/**
 * Faol sessiyalar.
 *
 * ## Nega "boshqalarini chiqarish" alohida tugma
 *
 * Parol o'g'irlanganiga shubha qilgan odam BIR harakat qilishi kerak:
 * hamma joydan chiqarish. Sessiyalarni bittalab bekor qilish — bu
 * holatda juda sekin va bittasini o'tkazib yuborish mumkin.
 *
 * Joriy sessiya ataylab bekor qilinmaydi: aks holda foydalanuvchi o'zini
 * tizimdan chiqarib, muammoni hal qila olmay qoladi.
 */
export function SessionsPanel() {
  const sessions = useSessions()
  const revoke = useRevokeSession()
  const revokeOthers = useRevokeOtherSessions()
  const [confirmAll, setConfirmAll] = useState(false)

  const others = (sessions.data ?? []).filter((s) => !s.is_current)

  return (
    <>
      <Card className="overflow-hidden">
        <CardHeader>
          <div className="flex flex-wrap items-start gap-4">
            <div>
              <CardTitle className="text-md">Active sessions</CardTitle>
              <CardDescription>Where your account is currently signed in</CardDescription>
            </div>
            <Button
              variant="danger"
              className="ml-auto"
              disabled={others.length === 0 || revokeOthers.isPending}
              onClick={() => setConfirmAll(true)}
            >
              {revokeOthers.isPending
                ? 'Signing out…'
                : `Sign out ${others.length} other${others.length === 1 ? '' : 's'}`}
            </Button>
          </div>
        </CardHeader>

        <div className="table-head grid items-center gap-3 px-4" style={{ gridTemplateColumns: GRID }}>
          <span>Device</span>
          <span>Location</span>
          <span>IP</span>
          <span>Last active</span>
          <span className="sr-only">Actions</span>
        </div>

        {sessions.isLoading && !sessions.data ? (
          <SkeletonRows rows={3} columns={GRID} />
        ) : (
          (sessions.data ?? []).map((session) => (
            <div
              key={session.id}
              className="grid h-12 items-center gap-3 border-b border-line-subtle px-4 last:border-b-0 hover:bg-surface-3"
              style={{ gridTemplateColumns: GRID }}
            >
              <span className="flex min-w-0 items-center gap-2.5">
                <svg
                  width="15"
                  height="15"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.7"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="shrink-0 text-fg-faint"
                  aria-hidden
                >
                  <path d={DEVICE_ICON[session.device_type]} />
                </svg>
                <span className="min-w-0">
                  <span className="block truncate text-base text-fg-soft">{session.browser}</span>
                  <span className="block truncate text-xs text-fg-faint">{session.os}</span>
                </span>
                {session.is_current ? <Badge variant="success" size="sm">This device</Badge> : null}
              </span>

              <span className="truncate text-sm text-fg-muted">{session.location}</span>
              <span className="tabular truncate font-mono text-xs text-fg-faint">{session.ip}</span>
              <span className="min-w-0">
                <RelativeTime
                  value={session.last_active_at}
                  className="block truncate text-sm text-fg-muted"
                />
                <span className="block truncate text-2xs text-fg-ghost">
                  since {formatDate(session.created_at)}
                </span>
              </span>

              <span className="flex justify-end">
                {session.is_current ? (
                  <span className="text-xs text-fg-ghost">—</span>
                ) : (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={revoke.isPending}
                    onClick={() => revoke.mutate(session.id)}
                  >
                    Sign out
                  </Button>
                )}
              </span>
            </div>
          ))
        )}
      </Card>

      <ConfirmDialog
        open={confirmAll}
        onOpenChange={setConfirmAll}
        title="Sign out every other session?"
        description={`${others.length} session${others.length === 1 ? '' : 's'} will be ended immediately. This device stays signed in. API keys are not affected — revoke them separately if a key leaked.`}
        confirmLabel="Sign them out"
        destructive
        pending={revokeOthers.isPending}
        onConfirm={() => {
          revokeOthers.mutate()
          setConfirmAll(false)
        }}
      />
    </>
  )
}
