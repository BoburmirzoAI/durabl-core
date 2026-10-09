'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'

import { EmptyState } from '@/components/common/EmptyState'
import { MonoId } from '@/components/common/MonoId'
import { RelativeTime } from '@/components/common/RelativeTime'
import { StatusBadge } from '@/components/common/StatusBadge'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { KbdHint } from '@/components/common/KbdHint'
import { SkeletonRows } from '@/components/ui/skeleton'
import { formatDuration } from '@/lib/utils/format'
import { jobStatusStyle, runtimeStyle } from '@/lib/utils/status'
import { StatusDot } from '@/components/common/StatusDot'
import type { JobSummary } from '@/types'

/**
 * Oxirgi job'lar — dizayndagi chap panel.
 *
 * Ustunlar dizayndan aynan:
 * `minmax(60px,1.4fr) 74px 92px 58px 64px`
 */
const GRID = 'minmax(60px,1.4fr) 74px 92px 58px 64px'

export function RecentJobs({
  jobs,
  loading = false,
}: {
  jobs: JobSummary[] | undefined
  loading?: boolean
}) {
  const router = useRouter()

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle>Recent Jobs</CardTitle>
        <KbdHint className="text-2xs">⌘J</KbdHint>
      </CardHeader>

      <div className="table-head grid items-center" style={{ gridTemplateColumns: GRID }}>
        <span>Job ID</span>
        <span>Runtime</span>
        <span>Status</span>
        <span>Duration</span>
        <span className="text-right">Created</span>
      </div>

      {loading && !jobs ? (
        <SkeletonRows rows={8} columns={GRID} />
      ) : !jobs || jobs.length === 0 ? (
        <EmptyState
          icon="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01"
          title="No jobs yet"
          description="Submit your first job to see it here."
        />
      ) : (
        jobs.map((job) => {
          const status = jobStatusStyle(job.status)
          const runtime = runtimeStyle(job.runtime)
          return (
            <div
              key={job.id}
              role="button"
              tabIndex={0}
              onClick={() => router.push(`/jobs/${job.id}`)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') router.push(`/jobs/${job.id}`)
              }}
              className="grid cursor-pointer items-center border-b border-line-subtle px-4 py-[9px] transition-colors hover:bg-surface-3"
              style={{ gridTemplateColumns: GRID }}
            >
              <MonoId value={job.id} />
              <span className="inline-flex items-center gap-1.5 text-xs text-fg-muted">
                <StatusDot className={runtime.dot} size="sm" />
                {runtime.label}
              </span>
              <span>
                <StatusBadge style={status} />
              </span>
              <span className="tabular font-mono text-sm text-fg-muted">
                {formatDuration(job.duration_ms)}
              </span>
              <RelativeTime
                value={job.created_at}
                className="tabular text-right font-mono text-sm text-fg-faint"
              />
            </div>
          )
        })
      )}

      <div className="px-4 py-[11px] text-center">
        <Link href="/jobs" className="text-sm font-medium">
          View all jobs →
        </Link>
      </div>
    </Card>
  )
}
