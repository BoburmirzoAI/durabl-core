'use client'

import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils/cn'
import { formatNumber } from '@/lib/utils/format'
import type { QueueDepth } from '@/types'

/**
 * Navbat chuqurligi — ustuvorlik bo'yicha.
 *
 * Dizaynda alohida panel yo'q (worker paneli bor), lekin dashboard'da
 * navbat holatini ko'rsatish zarur: Durabl'ning asosiy qiymati —
 * navbat yo'qolmasligi, demak uning chuqurligi ko'rinishi kerak.
 * Uslub worker panelidan olingan.
 */
const PRIORITY_STYLES = {
  high: { label: 'High', bar: 'bg-failed' },
  normal: { label: 'Normal', bar: 'bg-accent' },
  low: { label: 'Low', bar: 'bg-queued' },
} as const

export function QueueDepthPanel({
  queues,
  delayed,
  loading = false,
}: {
  queues: QueueDepth[] | undefined
  delayed?: number
  loading?: boolean
}) {
  const max = Math.max(...(queues ?? []).map((q) => q.depth), 1)
  const total = (queues ?? []).reduce((sum, q) => sum + q.depth, 0)

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>Queue Depth</CardTitle>
        {queues ? (
          <span className="tabular ml-auto font-mono text-md font-semibold text-fg">
            {formatNumber(total)}
          </span>
        ) : null}
      </CardHeader>

      <div className="flex flex-col gap-3.5 px-4 py-4">
        {loading && !queues
          ? Array.from({ length: 3 }, (_, i) => <Skeleton key={i} className="h-[5px]" />)
          : (queues ?? []).map((queue) => {
              const style = PRIORITY_STYLES[queue.priority]
              return (
                <div key={queue.priority}>
                  <div className="flex items-center gap-2 text-sm">
                    <span className="text-fg-soft">{style.label}</span>
                    <span className="ml-auto tabular font-mono text-fg">
                      {formatNumber(queue.depth)}
                    </span>
                    <span className="text-xs text-fg-faint">
                      · {queue.processing} running
                    </span>
                  </div>
                  <Progress
                    value={(queue.depth / max) * 100}
                    size="xs"
                    barClassName={style.bar}
                    className="mt-2"
                    aria-label={`${style.label} queue: ${queue.depth} waiting`}
                  />
                </div>
              )
            })}

        {delayed !== undefined ? (
          <div className="flex items-center gap-2 border-t border-line-subtle pt-3 text-sm">
            <span className="text-fg-dim">Scheduled for later</span>
            <span className={cn('ml-auto tabular font-mono', delayed > 0 ? 'text-fg-muted' : 'text-fg-faint')}>
              {formatNumber(delayed)}
            </span>
          </div>
        ) : null}
      </div>
    </Card>
  )
}
