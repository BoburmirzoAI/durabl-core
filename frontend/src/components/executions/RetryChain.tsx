'use client'

import Link from 'next/link'

import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils/cn'
import { formatDuration } from '@/lib/utils/format'
import { useJobExecutions } from '@/lib/hooks/useJobs'
import { executionStatusStyle } from '@/lib/utils/status'
import type { ExecutionStatus } from '@/types'

/**
 * Retry chain: `1 → 2 → 3 → DLQ`.
 *
 * ## Nega bu kerak
 *
 * Bitta urinishga qarab "nega bu job yiqildi?" degan savolga javob topib
 * bo'lmaydi. Zanjir butun hikoyani bir qatorda ko'rsatadi: nechta urinish
 * bo'lgan, qaysi worker'da, har biri qancha davom etgan va oxiri nima
 * bilan tugagan.
 *
 * Joriy urinish ajratib ko'rsatiladi — foydalanuvchi o'zi qayerda
 * turganini yo'qotmasligi uchun.
 */
export function RetryChain({
  jobId,
  currentExecutionId,
  jobStatus,
}: {
  jobId: string
  /** Shu urinish ajratib ko'rsatiladi. */
  currentExecutionId?: string
  /** Job'ning yakuniy holati — zanjir oxiriga DLQ tuguni qo'shish uchun. */
  jobStatus?: string
}) {
  const query = useJobExecutions(jobId)
  const attempts = [...(query.data ?? [])].sort((a, b) => a.attempt_number - b.attempt_number)

  if (query.isLoading) return <Skeleton className="h-14 w-full" />
  if (attempts.length === 0) return null

  const endedInDlq = jobStatus === 'dead_letter'

  return (
    <div>
      <div className="mb-2 text-xs font-semibold text-fg-dim">
        Retry chain
        <span className="ml-1.5 font-normal text-fg-faint">
          {attempts.length} attempt{attempts.length === 1 ? '' : 's'}{endedInDlq ? ' → DLQ' : ''}
        </span>
      </div>

      <div className="flex flex-wrap items-stretch gap-1.5">
        {attempts.map((execution, index) => {
          const style = executionStatusStyle(execution.status as ExecutionStatus)
          const isCurrent = execution.id === currentExecutionId
          return (
            <div key={execution.id} className="flex items-stretch gap-1.5">
              <div
                className={cn(
                  'min-w-[108px] rounded-lg border px-2.5 py-2 transition-colors',
                  isCurrent
                    ? 'border-accent/45 bg-accent/[0.08]'
                    : 'border-line bg-surface hover:border-line-hover',
                )}
              >
                <div className="flex items-center gap-1.5">
                  <span className={cn('h-1.5 w-1.5 shrink-0 rounded-full', style.dot)} aria-hidden />
                  <span className="text-xs font-medium text-fg-soft">
                    #{execution.attempt_number}
                  </span>
                  {isCurrent ? (
                    <span className="ml-auto text-2xs text-accent-light">current</span>
                  ) : null}
                </div>
                <div className={cn('mt-1 text-2xs', style.text)}>{style.label}</div>
                <div className="tabular mt-0.5 font-mono text-2xs text-fg-faint">
                  {execution.worker_id ?? '—'} · {formatDuration(execution.duration_ms)}
                </div>
              </div>

              {index < attempts.length - 1 || endedInDlq ? (
                <span className="flex items-center text-fg-ghost" aria-hidden>
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                    <path d="M5 12h14M13 6l6 6-6 6" />
                  </svg>
                </span>
              ) : null}
            </div>
          )
        })}

        {endedInDlq ? (
          <Link
            href="/dlq"
            className="flex min-w-[108px] flex-col justify-center rounded-lg border border-failed/30 bg-failed/[0.07] px-2.5 py-2 transition-colors hover:border-failed/50"
          >
            <div className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-failed" aria-hidden />
              <span className="text-xs font-medium text-failed">DLQ</span>
            </div>
            <div className="mt-1 text-2xs text-fg-dim">all attempts exhausted</div>
          </Link>
        ) : null}
      </div>
    </div>
  )
}
