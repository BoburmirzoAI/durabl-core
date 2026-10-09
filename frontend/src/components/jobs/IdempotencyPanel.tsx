'use client'

import { Card } from '@/components/ui/card'
import { CopyButton } from '@/components/common/CopyButton'
import { EmptyState } from '@/components/common/EmptyState'
import { RelativeTime } from '@/components/common/RelativeTime'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils/cn'
import { formatLogTime } from '@/lib/utils/time'
import type { IdempotencyRequest, JobIdempotency } from '@/types'

/**
 * Idempotency paneli.
 *
 * ## Nega bu ko'rinishi kerak
 *
 * "Job aynan bir marta bajariladi" — bizning ikkinchi asosiy va'damiz.
 * Mijoz tarmoq uzilganda so'rovni qayta yuboradi va "ikkita job yaratdimmi?"
 * deb hayron bo'ladi. Bu panel aniq javob beradi: qaysi kalit, qaysi
 * so'rovlar kelgan va ularning har biri NIMA bilan tugagan.
 *
 * Uch natija bor va ularning farqi muhim:
 *
 * * `created`       — birinchi so'rov, job yaratildi (201);
 * * `deduplicated`  — ayni kalit + ayni tana, MAVJUD job qaytarildi (200);
 * * `conflict`      — ayni kalit, BOSHQA tana — rad etildi (409). Bu mijoz
 *   xatosi: kalitni qayta ishlatib, boshqa kod yuborgan.
 */
const OUTCOME_STYLE: Record<
  IdempotencyRequest['outcome'],
  { label: string; badge: string; note: string }
> = {
  created: {
    label: 'Created',
    badge: 'bg-success/[0.12] text-success border-success/25',
    note: 'First request — the job was created',
  },
  deduplicated: {
    label: 'Deduplicated',
    badge: 'bg-accent/[0.14] text-accent-light border-accent/25',
    note: 'Repeat request — the existing job was returned, no new job created',
  },
  conflict: {
    label: 'Conflict',
    badge: 'bg-failed/[0.12] text-failed border-failed/25',
    note: 'Same key, DIFFERENT request body — rejected',
  },
}

export function IdempotencyPanel({
  data,
  loading = false,
}: {
  data: JobIdempotency | undefined
  loading?: boolean
}) {
  if (loading && !data) {
    return (
      <Card className="p-4">
        <Skeleton className="h-4 w-40" />
        <Skeleton className="mt-4 h-24 w-full" />
      </Card>
    )
  }

  if (!data) return null

  // --- Kalit berilmagan ---
  if (!data.key) {
    return (
      <div className="space-y-4">
        <EmptyState
          icon="M10 13a5 5 0 1 1 5-5l6 6-2 2-2-2-2 2-2-2z"
          title="No idempotency key was used"
          description="This job was submitted without an `Idempotency-Key` header — re-sending the same request would create a NEW job."
        />
        <Card className="p-4">
          <div className="text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">
            How to use it
          </div>
          <pre className="mt-3 overflow-x-auto rounded-lg border border-line-inner bg-canvas-deep px-3.5 py-3 font-mono text-xs leading-[1.7] text-fg-soft">
{`curl -X POST https://api.durabl.dev/api/v1/jobs \\
  -H "X-API-Key: durabl_…" \\
  -H "Idempotency-Key: order-4821-retry" \\
  -d '{"code": "...", "runtime": "python"}'`}
          </pre>
          <p className="mt-3 text-sm text-fg-dim">
            A repeated request with the same key does not create a new job — the existing one is
            returned. Keys are kept for 24 hours.
          </p>
        </Card>
      </div>
    )
  }

  const conflicts = data.requests.filter((r) => r.outcome === 'conflict').length
  const dedups = data.requests.filter((r) => r.outcome === 'deduplicated').length

  return (
    <div className="space-y-4">
      {/* Xulosa */}
      <div className="grid gap-px overflow-hidden rounded-xl border border-line bg-line-subtle sm:grid-cols-3">
        <Summary label="Requests" value={String(data.requests.length)} />
        <Summary
          label="Deduplicated"
          value={String(dedups)}
          tone={dedups > 0 ? 'accent' : 'default'}
        />
        <Summary label="Conflicts" value={String(conflicts)} tone={conflicts > 0 ? 'bad' : 'good'} />
      </div>

      {dedups > 0 ? (
        <div className="flex items-start gap-2.5 rounded-xl border border-accent/25 bg-accent/[0.06] px-4 py-3">
          <svg
            width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"
            className="mt-0.5 shrink-0 text-accent-light" aria-hidden
          >
            <path d="M5 12l5 5 9-11" />
          </svg>
          <div className="min-w-0 text-sm">
            <div className="font-medium text-fg">
              {dedups} repeated request{dedups === 1 ? '' : 's'} created no duplicate
            </div>
            <div className="mt-0.5 text-fg-dim">
              Requests carrying the same <span className="font-mono text-xs">Idempotency-Key</span>{' '}
              returned the existing job. The code ran{' '}
              <span className="font-medium text-fg-soft">exactly once</span>.
            </div>
          </div>
        </div>
      ) : null}

      {/* Kalit tafsilotlari */}
      <Card className="overflow-hidden">
        <div className="border-b border-line-inner px-4 py-2.5">
          <span className="text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">
            Key
          </span>
        </div>
        <div className="space-y-2.5 p-4">
          <Row
            label="Idempotency-Key"
            value={
              <span className="flex items-center gap-1.5">
                <span className="truncate font-mono text-xs text-fg-bright">{data.key}</span>
                <CopyButton value={data.key} label="Idempotency key" silent />
              </span>
            }
          />
          <Row
            label="Fingerprint"
            value={<span className="font-mono text-xs text-fg-dim">{data.fingerprint ?? '—'}</span>}
          />
          <Row
            label="Expires"
            value={
              data.expires_at ? (
                <RelativeTime value={data.expires_at} className="text-sm text-fg-soft" />
              ) : (
                '—'
              )
            }
          />
        </div>
      </Card>

      {/* So'rovlar tarixi */}
      <Card className="overflow-hidden">
        <div className="border-b border-line-inner px-4 py-2.5">
          <span className="text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">
            Requests with this key
          </span>
        </div>
        {data.requests.map((request, index) => {
          const style = OUTCOME_STYLE[request.outcome]
          return (
            <div
              key={request.request_id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line-subtle px-4 py-3 last:border-b-0"
            >
              <span className="tabular w-5 shrink-0 font-mono text-xs text-fg-ghost">
                {index + 1}
              </span>
              <span
                className={cn(
                  'shrink-0 rounded-md border px-2 py-0.5 text-2xs font-semibold',
                  style.badge,
                )}
              >
                {style.label}
              </span>
              <span className="tabular shrink-0 font-mono text-xs text-fg-muted">
                HTTP {request.status_code}
              </span>
              <span className="tabular shrink-0 font-mono text-xs text-fg-faint">
                {formatLogTime(request.at)}
              </span>
              <span className="truncate text-xs text-fg-dim">{request.source}</span>
              <span className="ml-auto shrink-0 font-mono text-2xs text-fg-ghost">
                {request.request_id}
              </span>
              <div className="w-full pl-8 text-xs text-fg-faint">{style.note}</div>
            </div>
          )
        })}
      </Card>
    </div>
  )
}

function Summary({
  label,
  value,
  tone = 'default',
}: {
  label: string
  value: string
  tone?: 'default' | 'good' | 'bad' | 'accent'
}) {
  return (
    <div className="bg-surface px-4 py-3">
      <div className="text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">{label}</div>
      <div
        className={cn(
          'tabular mt-1.5 font-mono text-lg',
          tone === 'bad' ? 'text-failed' : tone === 'good' ? 'text-success' : tone === 'accent' ? 'text-accent-light' : 'text-fg',
        )}
      >
        {value}
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="shrink-0 text-sm text-fg-dim">{label}</span>
      <span className="min-w-0 text-right">{value}</span>
    </div>
  )
}
