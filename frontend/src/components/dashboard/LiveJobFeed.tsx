'use client'

import Link from 'next/link'
import { useEffect, useRef, useState } from 'react'

import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { RelativeTime } from '@/components/common/RelativeTime'
import { Skeleton } from '@/components/ui/skeleton'
import { StatusDot } from '@/components/common/StatusDot'
import { cn } from '@/lib/utils/cn'
import { formatDuration } from '@/lib/utils/format'
import { jobStatusStyle } from '@/lib/utils/status'
import type { JobSummary } from '@/types'

/**
 * Jonli job tasmasi — dashboard'ning "hozir nima bo'layapti" qismi.
 *
 * `RecentJobs` jadvalidan farqi: bu yerda SO'NGGI O'ZGARISHLAR ko'rsatiladi,
 * ya'ni holati yangi o'zgargan job'lar tepaga kiradi. Jadval esa yaratilish
 * vaqti bo'yicha tartiblangan statik ro'yxat.
 *
 * Yangi element qo'shilganda `animate-slide-down` bilan kiradi va qisqa
 * vaqt yoritiladi — ko'z o'zgarishni ilg'ab olishi uchun.
 */
export function LiveJobFeed({
  jobs,
  loading = false,
  limit = 8,
}: {
  jobs: JobSummary[] | undefined
  loading?: boolean
  limit?: number
}) {
  const [paused, setPaused] = useState(false)
  const [feed, setFeed] = useState<JobSummary[]>([])
  const seen = useRef(new Map<string, string>())

  useEffect(() => {
    if (paused || !jobs) return

    // Holati O'ZGARGAN yoki birinchi marta ko'rilgan job'larni topamiz
    const changed: JobSummary[] = []
    for (const job of jobs) {
      const previous = seen.current.get(job.id)
      if (previous !== job.status) {
        if (previous !== undefined) changed.push(job)
        seen.current.set(job.id, job.status)
      }
    }
    if (changed.length === 0) return

    setFeed((current) => {
      // Ayni job ikki marta turmasligi uchun eskisini olib tashlaymiz
      const ids = new Set(changed.map((j) => j.id))
      return [...changed, ...current.filter((j) => !ids.has(j.id))].slice(0, limit)
    })
  }, [jobs, paused, limit])

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">Live feed</CardTitle>
        <button
          type="button"
          onClick={() => setPaused((p) => !p)}
          className={cn(
            'ml-auto flex items-center gap-1.5 rounded-md px-2 py-1 text-xs transition-colors',
            paused ? 'text-fg-dim hover:bg-surface-2 hover:text-fg' : 'text-success hover:bg-surface-2',
          )}
          aria-label={paused ? 'Resume live feed' : 'Pause live feed'}
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
              live
            </>
          )}
        </button>
      </CardHeader>

      <div className="min-h-[180px]">
        {loading && !jobs ? (
          Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="border-b border-line-subtle px-4 py-2.5">
              <Skeleton className="h-3 w-full" />
            </div>
          ))
        ) : feed.length === 0 ? (
          <div className="flex min-h-[180px] flex-col items-center justify-center gap-1.5 px-4 text-center">
            <StatusDot className="bg-success" pulseToken="success" live />
            <span className="text-sm text-fg-dim">Watching for job state changes…</span>
            <span className="text-xs text-fg-faint">
              Jobs appear here the moment they move between states.
            </span>
          </div>
        ) : (
          feed.map((job) => {
            const status = jobStatusStyle(job.status)
            return (
              <Link
                key={`${job.id}-${job.status}`}
                href={`/jobs/${job.id}`}
                className="flex animate-slide-down items-center gap-2.5 border-b border-line-subtle px-4 py-2.5 transition-colors last:border-b-0 hover:bg-surface-3"
              >
                <StatusDot className={status.dot} live={status.live} pulseToken={status.pulseToken} />
                <span className="truncate font-mono text-sm text-fg-bright">{job.id}</span>
                <span className={cn('shrink-0 text-xs', status.text)}>{status.label}</span>
                {job.duration_ms !== null ? (
                  <span className="tabular shrink-0 font-mono text-xs text-fg-faint">
                    {formatDuration(job.duration_ms)}
                  </span>
                ) : null}
                <RelativeTime
                  value={job.finished_at ?? job.started_at ?? job.created_at}
                  refreshMs={2_000}
                  className="tabular ml-auto shrink-0 font-mono text-xs text-fg-faint"
                />
              </Link>
            )
          })
        )}
      </div>
    </Card>
  )
}
