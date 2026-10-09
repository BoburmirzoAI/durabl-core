'use client'

import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useState } from 'react'

import { CopyButton } from '@/components/common/CopyButton'
import { ErrorState } from '@/components/common/ErrorState'
import { LoadingState } from '@/components/common/LoadingState'
import { StatusBadge } from '@/components/common/StatusBadge'
import { CodeBlock } from '@/components/jobs/CodeBlock'
import { JobAttemptsTable } from '@/components/jobs/JobAttemptsTable'
import { JobLogViewer } from '@/components/jobs/JobLogViewer'
import { IdempotencyPanel } from '@/components/jobs/IdempotencyPanel'
import { JobResultPanel } from '@/components/jobs/JobResultPanel'
import { JsonViewer } from '@/components/common/JsonViewer'
import { LeaseTimeline } from '@/components/jobs/LeaseTimeline'
import { RetryChain } from '@/components/executions/RetryChain'
import { JobTimeline } from '@/components/jobs/JobTimeline'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Tabs } from '@/components/ui/tabs'
import {
  useCancelJob,
  useJob,
  useJobExecutions,
  useJobIdempotency,
  useJobLeaseHistory,
  useJobLogs,
  useJobTimeline,
  useRetryJob,
} from '@/lib/hooks/useJobs'
import { cn } from '@/lib/utils/cn'
import { formatDuration, humanize } from '@/lib/utils/format'
import { formatTimestamp } from '@/lib/utils/time'
import { jobStatusStyle, runtimeStyle } from '@/lib/utils/status'
import { ICON_COPY, ICON_LINK } from '@/lib/constants/icons'
import { useCopy } from '@/lib/hooks/useCopy'
import { failureReasonLabel } from '@/lib/utils/status'

type TabValue =
  | 'logs'
  | 'result'
  | 'attempts'
  | 'lease'
  | 'idempotency'
  | 'code'
  | 'payload'

/**
 * Job detali — dizayndagi eng boy sahifa.
 *
 * Tuzilma: sarlavha (ID + holat + amallar) / meta panel / hayot sikli
 * stepper / tablar (Logs | Result | Code | Attempts | Payload).
 */
export default function JobDetailPage({ params }: { params: { id: string } }) {
  const router = useRouter()
  const copy = useCopy()
  const [tab, setTab] = useState<TabValue>('logs')

  const job = useJob(params.id)
  const timeline = useJobTimeline(params.id)
  const executions = useJobExecutions(params.id)
  // Ishonchlilik ma'lumoti faqat TEGISHLI tab ochilganda so'raladi
  const lease = useJobLeaseHistory(params.id, tab === 'lease')
  const idempotency = useJobIdempotency(params.id, tab === 'idempotency')
  const isLive = job.data ? !job.data.is_terminal : false
  const logs = useJobLogs(params.id, isLive)

  const cancelJob = useCancelJob()
  const retryJob = useRetryJob()

  if (job.isLoading && !job.data) return <LoadingState label="Loading job…" />
  if (job.error) return <ErrorState error={job.error} onRetry={() => void job.refetch()} />
  if (!job.data) return null

  const data = job.data
  const status = jobStatusStyle(data.status)
  const runtime = runtimeStyle(data.runtime)
  const isDlq = data.status === 'dead_letter'

  const meta: { key: string; value: string; mono?: boolean; className?: string }[] = [
    { key: 'Runtime', value: runtime.label },
    { key: 'Priority', value: humanize(data.priority) },
    { key: 'Attempts', value: `${data.attempts_used}/${data.max_retries + 1}`, mono: true },
    { key: 'Idempotency key', value: data.idempotency_key ?? '—', mono: true },
    { key: 'Worker', value: data.worker_id ?? '—', mono: true },
    { key: 'Timeout', value: `${data.timeout_seconds}s`, mono: true },
    { key: 'Exit code', value: data.exit_code === null ? '—' : String(data.exit_code), mono: true, className: data.exit_code === 0 ? undefined : 'text-failed' },
    { key: 'Duration', value: formatDuration(data.duration_ms), mono: true },
    { key: 'Created', value: formatTimestamp(data.created_at), mono: true },
    ...(data.failure_reason
      ? [{ key: 'Failure reason', value: failureReasonLabel(data.failure_reason), className: 'text-failed' }]
      : []),
  ]

  const tabs = [
    { value: 'logs' as const, label: 'Logs', count: logs.data?.length },
    { value: 'result' as const, label: 'Result' },
    { value: 'attempts' as const, label: 'Attempts', count: executions.data?.length },
    // Ishonchlilik tablari — bizning differensiatsiyamiz ko'rinadigan joyi
    { value: 'lease' as const, label: 'Lease & Heartbeat' },
    { value: 'idempotency' as const, label: 'Idempotency' },
    { value: 'code' as const, label: 'Code' },
    ...(data.payload ? [{ value: 'payload' as const, label: 'Payload' }] : []),
  ]

  return (
    <>
      {/* Sarlavha */}
      <div className="flex flex-wrap items-start gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="m-0 break-all font-mono text-3xl font-semibold tracking-[-.01em] text-fg">
              {data.id}
            </h1>
            <CopyButton value={data.id} label="Job ID" size="md" />
            <StatusBadge style={status} size="lg" />
          </div>
        </div>

        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="primary"
            size="md"
            disabled={!data.is_terminal || retryJob.isPending}
            onClick={() => retryJob.mutate(data.id)}
          >
            <Icon path="M3 12a9 9 0 1 0 3-6.7M3 3v4h4" size={14} />
            Retry
          </Button>
          <Button
            variant="secondary"
            size="md"
            disabled={data.is_terminal || cancelJob.isPending}
            onClick={() => cancelJob.mutate(data.id)}
          >
            <Icon path="M18 6 6 18M6 6l12 12" size={14} />
            Cancel
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="secondary" size="icon-lg" aria-label="More actions">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                  <circle cx="5" cy="12" r="1.6" />
                  <circle cx="12" cy="12" r="1.6" />
                  <circle cx="19" cy="12" r="1.6" />
                </svg>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <DropdownMenuItem onSelect={() => router.push('/jobs')}>
                <Icon path="M19 12H5M11 6l-6 6 6 6" />
                Back to jobs
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={() => void copy(data.code, 'Code copied')}>
                <Icon path={ICON_COPY} />
                Copy code
              </DropdownMenuItem>
              <DropdownMenuItem
                onSelect={() => void copy(data.correlation_id, 'Correlation ID copied')}
              >
                <Icon path={ICON_LINK} />
                Copy correlation ID
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>

      {/* DLQ ogohlantirishi — eng ko'zga tashlanadigan joyda */}
      {isDlq ? (
        <div className="flex flex-wrap items-center gap-3 rounded-xl border border-failed/20 bg-failed/[0.07] px-4 py-3">
          <Icon path="M12 3 2 20h20zM12 10v4M12 17h.01" size={18} className="shrink-0 text-failed" />
          <span className="text-base text-failed-text">
            <span className="font-semibold text-failed-bright">
              This job exhausted all {data.max_retries + 1} attempts.
            </span>{' '}
            {data.error ?? 'It is now in the dead letter queue.'}
          </span>
          <Link href="/dlq" className="ml-auto shrink-0 text-sm font-medium">
            View in DLQ →
          </Link>
        </div>
      ) : null}

      {/* Meta panel */}
      <Card radius="xl" className="flex flex-wrap overflow-hidden">
        {meta.map((item) => (
          <div
            key={item.key}
            className="min-w-[150px] flex-auto border-b border-r border-line-inner px-[15px] py-[11px]"
          >
            <div className="text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
              {item.key}
            </div>
            <div
              className={cn(
                'mt-[5px] break-all text-base text-fg-soft',
                item.mono && 'font-mono',
                item.className,
              )}
            >
              {item.value}
            </div>
          </div>
        ))}
      </Card>

      <JobTimeline timeline={timeline.data} loading={timeline.isLoading} />

      {/* Tablar */}
      <Card className="overflow-hidden">
        <div className="border-b border-line-inner">
          <Tabs aria-label="Job details" variant="underline" items={tabs} value={tab} onChange={setTab} />
        </div>

        {tab === 'logs' ? (
          <JobLogViewer logs={logs.data} loading={logs.isLoading} isLive={isLive} />
        ) : null}
        {tab === 'result' ? <JobResultPanel job={data} /> : null}
        {tab === 'attempts' ? (
          <>
            <div className="border-b border-line-inner px-4 py-3.5">
              <RetryChain jobId={data.id} jobStatus={data.status} />
            </div>
            <JobAttemptsTable
            executions={executions.data}
            loading={executions.isLoading}
            logs={logs.data}
            />
          </>
        ) : null}
        {tab === 'code' ? (
          <div className="p-4">
            <CodeBlock code={data.code} runtime={data.runtime} collapsible={false} defaultOpen />
          </div>
        ) : null}
        {tab === 'lease' ? (
          <div className="p-4">
            <LeaseTimeline data={lease.data} loading={lease.isLoading} />
          </div>
        ) : null}
        {tab === 'idempotency' ? (
          <div className="p-4">
            <IdempotencyPanel data={idempotency.data} loading={idempotency.isLoading} />
          </div>
        ) : null}
        {tab === 'payload' && data.payload ? (
          <div className="p-4">
            <JsonViewer data={data.payload} rootLabel="payload" maxHeight={420} />
          </div>
        ) : null}
      </Card>
    </>
  )
}

function Icon({
  path,
  size = 13,
  className,
}: {
  path: string
  size?: number
  className?: string
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.9"
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
    >
      <path d={path} />
    </svg>
  )
}
