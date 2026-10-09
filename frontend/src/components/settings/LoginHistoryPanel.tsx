'use client'

import { Badge } from '@/components/ui/badge'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { SkeletonRows } from '@/components/ui/skeleton'
import { useLoginHistory } from '@/lib/hooks/useAccount'
import { formatTimestamp } from '@/lib/utils/time'
import type { LoginResult } from '@/types'

const GRID = 'minmax(150px,1.2fr) 118px minmax(120px,1fr) 118px minmax(110px,1fr)'

const RESULT: Record<LoginResult, { label: string; className: string }> = {
  success: { label: 'Success', className: 'bg-success/[0.12] text-success' },
  failed_password: { label: 'Wrong password', className: 'bg-failed/[0.12] text-failed' },
  failed_2fa: { label: 'Wrong 2FA code', className: 'bg-failed/[0.12] text-failed' },
  blocked: { label: 'Blocked', className: 'bg-pending/[0.12] text-pending' },
}

/**
 * Kirish tarixi.
 *
 * Muvaffaqiyatsiz urinishlar YASHIRILMAYDI — jurnalning butun maqsadi
 * "menikidan boshqa kirish urinishi bo'lganmi?" degan savolga javob
 * berish. Faqat muvaffaqiyatli qatorlar ko'rsatilsa, u foydasiz bo'lardi.
 */
export function LoginHistoryPanel() {
  const history = useLoginHistory()
  const failures = (history.data ?? []).filter((e) => e.result !== 'success').length

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <div className="flex flex-wrap items-start gap-4">
          <div>
            <CardTitle className="text-md">Sign-in history</CardTitle>
            <CardDescription>Recent attempts, successful or not</CardDescription>
          </div>
          {history.data && failures > 0 ? (
            <span className="ml-auto text-sm text-pending">
              {failures} failed attempt{failures === 1 ? '' : 's'} recently
            </span>
          ) : null}
        </div>
      </CardHeader>

      <div className="table-head grid items-center gap-3 px-4" style={{ gridTemplateColumns: GRID }}>
        <span>When</span>
        <span>Result</span>
        <span>Location</span>
        <span>IP</span>
        <span>Client</span>
      </div>

      {history.isLoading && !history.data ? (
        <SkeletonRows rows={5} columns={GRID} />
      ) : (
        (history.data ?? []).map((event) => (
          <div
            key={event.id}
            className="grid h-11 items-center gap-3 border-b border-line-subtle px-4 last:border-b-0 hover:bg-surface-3"
            style={{ gridTemplateColumns: GRID }}
          >
            <span className="tabular truncate font-mono text-xs text-fg-muted">
              {formatTimestamp(event.at)}
            </span>
            <span>
              <Badge size="sm" className={RESULT[event.result].className}>
                {RESULT[event.result].label}
              </Badge>
            </span>
            <span
              className={`truncate text-sm ${
                event.result === 'success' ? 'text-fg-muted' : 'text-failed-text'
              }`}
            >
              {event.location}
            </span>
            <span className="tabular truncate font-mono text-xs text-fg-faint">{event.ip}</span>
            <span className="truncate text-xs text-fg-faint" title={`${event.browser} · ${event.os}`}>
              {event.browser}
            </span>
          </div>
        ))
      )}
    </Card>
  )
}
