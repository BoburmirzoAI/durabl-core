'use client'

import { useEffect, useState } from 'react'

import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { RelativeTime } from '@/components/common/RelativeTime'
import { Skeleton } from '@/components/ui/skeleton'
import { StatusDot } from '@/components/common/StatusDot'
import { cn } from '@/lib/utils/cn'
import { nextActivityEvent } from '@/lib/mock/users'
import type { ActivityEvent } from '@/types'

/**
 * Jonli faollik oqimi (admin).
 *
 * Yangi yozuvlar yuqoridan kiradi (`animate-slide-down`), daraja bo'yicha
 * rang: `error` qizil, `warn` sariq, `info` neytral.
 */
const SEVERITY = {
  info: { dot: 'bg-queued', text: 'text-fg-soft' },
  warn: { dot: 'bg-pending', text: 'text-pending' },
  error: { dot: 'bg-failed', text: 'text-failed-text' },
} as const

export function ActivityFeed({
  events,
  loading = false,
  streaming = false,
}: {
  events: ActivityEvent[] | undefined
  loading?: boolean
  /** Yangi hodisalar vaqt o'tishi bilan qo'shilsinmi. */
  streaming?: boolean
}) {
  const [paused, setPaused] = useState(false)
  const [live, setLive] = useState<ActivityEvent[]>([])

  // Oqim: har 2.5 soniyada yangi hodisa tepaga qo'shiladi
  useEffect(() => {
    if (!streaming || paused) return
    const timer = setInterval(() => {
      // Ro'yxat cheksiz o'smasligi uchun 40 ta bilan cheklaymiz
      setLive((current) => [nextActivityEvent(), ...current].slice(0, 40))
    }, 2_500)
    return () => clearInterval(timer)
  }, [streaming, paused])

  const rows = streaming ? [...live, ...(events ?? [])] : (events ?? [])

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">Live Activity</CardTitle>
        {streaming ? (
          <button
            type="button"
            onClick={() => setPaused((p) => !p)}
            className={cn(
              'ml-auto flex items-center gap-1.5 rounded-md px-2 py-1 text-xs transition-colors',
              paused
                ? 'text-fg-dim hover:bg-surface-2 hover:text-fg'
                : 'text-success hover:bg-surface-2',
            )}
            aria-label={paused ? 'Resume live activity' : 'Pause live activity'}
          >
            {paused ? (
              <>
                <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                  <path d="M6 4l14 8-14 8z" />
                </svg>
                paused
              </>
            ) : (
              <>
                <StatusDot className="bg-success" pulseToken="success" live />
                streaming
              </>
            )}
          </button>
        ) : (
          <span className="ml-auto flex items-center gap-1.5 text-xs text-success">
            <StatusDot className="bg-success" pulseToken="success" live />
            streaming
          </span>
        )}
      </CardHeader>

      <div className="max-h-[420px] overflow-y-auto">
        {loading && !events
          ? Array.from({ length: 8 }, (_, i) => (
              <div key={i} className="border-b border-line-subtle px-4 py-2.5">
                <Skeleton className="h-3 w-full" />
              </div>
            ))
          : rows.map((event) => {
              const tone = SEVERITY[event.severity]
              return (
                <div
                  key={event.id}
                  className="flex animate-slide-down items-start gap-2.5 border-b border-line-subtle px-4 py-2.5 last:border-b-0"
                >
                  <StatusDot className={cn('mt-1.5', tone.dot)} />
                  <span className="min-w-0 flex-1">
                    <span className={cn('block break-words font-mono text-sm', tone.text)}>
                      {event.message}
                    </span>
                    {event.actor ? (
                      <span className="mt-0.5 block text-xs text-fg-faint">{event.actor}</span>
                    ) : null}
                  </span>
                  <RelativeTime
                    value={event.at}
                    refreshMs={10_000}
                    className="tabular shrink-0 font-mono text-xs text-fg-faint"
                  />
                </div>
              )
            })}
      </div>
    </Card>
  )
}
