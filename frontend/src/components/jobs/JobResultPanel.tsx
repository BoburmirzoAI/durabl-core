'use client'

import { EmptyState } from '@/components/common/EmptyState'
import { cn } from '@/lib/utils/cn'
import type { Job } from '@/types'

/**
 * Job natijasi — qaytgan qiymat, stdout, stderr.
 *
 * Dizaynda alohida panel yo'q (loglar tabi bor), lekin `/jobs/{id}/result`
 * endpointi bor va foydalanuvchi natijani loglardan AJRATIB ko'rishi
 * kerak — shuning uchun alohida tab sifatida qo'shilgan.
 */
export function JobResultPanel({ job }: { job: Job }) {
  const resultValue = job.result?.value

  if (!job.is_terminal) {
    return (
      <EmptyState
        icon="M12 7v5l3 3M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z"
        title="Result not ready"
        description={`Job is ${job.status}. The result appears once it reaches a terminal state.`}
      />
    )
  }

  return (
    <div className="flex flex-col gap-4 p-4">
      <Block
        label="Return value"
        empty="This job returned nothing."
        value={resultValue === undefined || resultValue === null ? null : JSON.stringify(resultValue, null, 2)}
      />
      <Block label="stdout" empty="No stdout captured." value={job.stdout} />
      <Block
        label="stderr"
        empty="No stderr captured."
        value={job.stderr}
        tone="error"
      />
      {job.error ? <Block label="Error" value={job.error} tone="error" /> : null}
    </div>
  )
}

function Block({
  label,
  value,
  empty,
  tone = 'neutral',
}: {
  label: string
  value: string | null | undefined
  empty?: string
  tone?: 'neutral' | 'error'
}) {
  return (
    <div>
      <div className="mb-1.5 text-xs font-semibold uppercase tracking-[.05em] text-fg-faint">
        {label}
      </div>
      {value ? (
        <pre
          className={cn(
            'm-0 max-h-[280px] overflow-auto whitespace-pre-wrap break-words rounded-lg border px-3.5 py-3 font-mono text-xs leading-[1.65]',
            tone === 'error'
              ? 'border-failed/[0.18] bg-failed/[0.06] text-failed-text'
              : 'border-line-inner bg-canvas-deep text-fg-soft',
          )}
        >
          {value}
        </pre>
      ) : (
        <div className="rounded-lg border border-line-inner bg-canvas-deep px-3.5 py-3 font-mono text-xs text-fg-faint">
          {empty ?? '—'}
        </div>
      )}
    </div>
  )
}
