'use client'

import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { StatusDot } from '@/components/common/StatusDot'
import { cn } from '@/lib/utils/cn'
import { formatUptime, humanize } from '@/lib/utils/format'
import type { SystemStatus } from '@/types'

/**
 * Tizim sog'ligi — pastki tizimlar holati.
 *
 * Bitta tekshiruv ham yiqilsa umumiy holat `degraded` bo'ladi:
 * "hammasi joyida" degan yolg'on signal berish xavfli.
 */
export function SystemHealth({
  status,
  loading = false,
}: {
  status: SystemStatus | undefined
  loading?: boolean
}) {
  const overall = status?.status ?? 'ok'
  const tone =
    overall === 'ok'
      ? { dot: 'bg-success', text: 'text-success', label: 'Operational' }
      : overall === 'degraded'
        ? { dot: 'bg-pending', text: 'text-pending', label: 'Degraded' }
        : { dot: 'bg-failed', text: 'text-failed', label: 'Down' }

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">System Health</CardTitle>
        {status ? (
          <span className={cn('ml-auto flex items-center gap-2 text-sm font-medium', tone.text)}>
            <StatusDot className={tone.dot} pulseToken={overall === 'ok' ? 'success' : 'pending'} live />
            {tone.label}
          </span>
        ) : null}
      </CardHeader>

      <div className="flex flex-col gap-1 p-4">
        {loading && !status ? (
          Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-8" />)
        ) : status ? (
          <>
            {Object.entries(status.checks).map(([name, ok]) => (
              <div
                key={name}
                className="flex items-center gap-2.5 border-b border-line-subtle py-2.5 last:border-b-0"
              >
                <StatusDot className={ok ? 'bg-success' : 'bg-failed'} />
                <span className="flex-1 text-base text-fg-soft">{humanize(name)}</span>
                <span className={cn('text-sm font-medium', ok ? 'text-success' : 'text-failed')}>
                  {ok ? 'Healthy' : 'Unavailable'}
                </span>
              </div>
            ))}

            <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-3 border-t border-line-inner pt-3.5">
              <Meta label="Version" value={status.version} mono />
              <Meta label="Environment" value={status.environment} />
              <Meta label="Uptime" value={formatUptime(status.uptime_seconds)} mono />
              <Meta
                label="Sandbox"
                value={status.sandbox_available ? 'gVisor ready' : 'Unavailable'}
                tone={status.sandbox_available ? undefined : 'alert'}
              />
              <Meta label="Active workers" value={String(status.active_workers)} mono />
              <Meta label="Delayed jobs" value={String(status.delayed_jobs)} mono />
              <Meta
                label="DLQ depth"
                value={String(status.dlq_depth)}
                mono
                tone={status.dlq_depth > 0 ? 'alert' : undefined}
              />
              <Meta label="Webhook queue" value={String(status.webhook_queue_depth)} mono />
            </dl>
          </>
        ) : null}
      </div>
    </Card>
  )
}

function Meta({
  label,
  value,
  mono = false,
  tone,
}: {
  label: string
  value: string
  mono?: boolean
  tone?: 'alert'
}) {
  return (
    <div>
      <dt className="text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">{label}</dt>
      <dd
        className={cn(
          'mt-0.5 text-base',
          mono && 'font-mono text-sm',
          tone === 'alert' ? 'text-failed' : 'text-fg-soft',
        )}
      >
        {value}
      </dd>
    </div>
  )
}
