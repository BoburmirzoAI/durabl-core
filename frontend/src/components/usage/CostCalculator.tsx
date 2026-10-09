'use client'

import { useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { useCostEstimate } from '@/lib/hooks/useBilling'
import { formatCompact, formatCurrency } from '@/lib/utils/format'
import { cn } from '@/lib/utils/cn'
import type { PlanType } from '@/types'

/**
 * "Nima bo'lardi" narx kalkulyatori.
 *
 * ## Nima uchun kerak
 *
 * Reja tanlash — eng ko'p savol tug'diradigan qaror. Narxlar jadvali
 * "pro $99" deydi, lekin foydalanuvchining savoli boshqacha: "oyiga
 * 800 ming job yuborsam, menga qancha tushadi?". Bu kalkulyator aynan
 * shu savolga javob beradi va eng arzon MOS rejani tavsiya qiladi.
 *
 * ## Nega slayder, maydon emas
 *
 * Hajm logarifmik: 1K dan 10M gacha. Oddiy slayder 1K atrofida ishlamaydi,
 * shuning uchun qiymat logarifmik shkalada o'zgaradi va yonida aniq raqam
 * ham ko'rsatiladi.
 */
const MIN_JOBS = 1_000
const MAX_JOBS = 20_000_000

/** Slayder pozitsiyasini (0..100) job soniga o'giradi. */
function toJobs(position: number): number {
  const min = Math.log10(MIN_JOBS)
  const max = Math.log10(MAX_JOBS)
  const raw = 10 ** (min + ((max - min) * position) / 100)
  // Yaxlitlash: ko'rsatiladigan raqam "1,043,217" emas, "1,000,000" bo'lsin
  const magnitude = 10 ** Math.max(2, Math.floor(Math.log10(raw)) - 1)
  return Math.round(raw / magnitude) * magnitude
}

function toPosition(jobs: number): number {
  const min = Math.log10(MIN_JOBS)
  const max = Math.log10(MAX_JOBS)
  return ((Math.log10(Math.max(MIN_JOBS, jobs)) - min) / (max - min)) * 100
}

const PLAN_ORDER: readonly PlanType[] = ['free', 'starter', 'pro', 'enterprise']

export function CostCalculator({ currentPlan }: { currentPlan: PlanType }) {
  const [position, setPosition] = useState(() => toPosition(300_000))
  const [durationMs, setDurationMs] = useState(1_500)

  const jobs = toJobs(position)
  const estimate = useCostEstimate(jobs, durationMs)
  const data = estimate.data

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">What would it cost?</CardTitle>
        <CardDescription>
          Try a volume and see every plan priced — the cheapest one that fits is highlighted
        </CardDescription>
      </CardHeader>

      <div className="grid gap-4 border-b border-line-inner p-4 sm:grid-cols-2">
        <label className="block">
          <span className="flex items-baseline justify-between">
            <span className="text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
              Jobs per month
            </span>
            <span className="tabular font-mono text-sm text-fg">{formatCompact(jobs)}</span>
          </span>
          <input
            type="range"
            min={0}
            max={100}
            step={0.5}
            value={position}
            onChange={(event) => setPosition(Number(event.target.value))}
            aria-label="Jobs per month"
            className="mt-2.5 h-1.5 w-full cursor-pointer appearance-none rounded-full bg-line accent-[hsl(var(--accent))]"
          />
          <span className="mt-1 flex justify-between text-2xs text-fg-ghost">
            <span>1K</span>
            <span>20M</span>
          </span>
        </label>

        <label className="block">
          <span className="flex items-baseline justify-between">
            <span className="text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
              Average job duration
            </span>
            <span className="tabular font-mono text-sm text-fg">
              {(durationMs / 1_000).toFixed(1)}s
            </span>
          </span>
          <input
            type="range"
            min={100}
            max={30_000}
            step={100}
            value={durationMs}
            onChange={(event) => setDurationMs(Number(event.target.value))}
            aria-label="Average job duration in milliseconds"
            className="mt-2.5 h-1.5 w-full cursor-pointer appearance-none rounded-full bg-line accent-[hsl(var(--accent))]"
          />
          <span className="mt-1 flex justify-between text-2xs text-fg-ghost">
            <span>0.1s</span>
            <span>30s</span>
          </span>
        </label>
      </div>

      {!data ? (
        <div className="p-4">
          <Skeleton className="h-36 w-full" />
        </div>
      ) : (
        <>
          <div className="grid gap-px bg-line-subtle sm:grid-cols-4">
            {PLAN_ORDER.map((plan) => {
              const row = data.plans.find((p) => p.plan === plan)
              if (!row) return null
              const recommended = data.recommended === plan
              return (
                <div
                  key={plan}
                  className={cn(
                    'bg-surface px-4 py-3.5',
                    recommended && 'bg-accent/[0.05]',
                  )}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium capitalize text-fg-soft">{plan}</span>
                    {plan === currentPlan ? (
                      <Badge size="sm" variant="outline">
                        Current
                      </Badge>
                    ) : null}
                    {recommended ? (
                      <Badge size="sm" variant="success">
                        Best fit
                      </Badge>
                    ) : null}
                  </div>

                  <div className="tabular mt-2 font-mono text-lg text-fg">
                    {formatCurrency(row.total_usd)}
                    <span className="text-xs font-normal text-fg-faint">/mo</span>
                  </div>

                  <div className="mt-1.5 text-xs leading-[1.5] text-fg-dim">
                    {row.fits ? (
                      <>Base {formatCurrency(row.base_usd)} · within allowance</>
                    ) : (
                      <span className="text-pending">
                        {row.over_by}× over allowance · {formatCurrency(row.overage_usd)} overage
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

          <div className="flex flex-wrap items-center gap-x-5 gap-y-1.5 border-t border-line-inner px-4 py-3 text-sm">
            <span className="text-fg-dim">
              {formatCompact(jobs)} jobs × {(durationMs / 1_000).toFixed(1)}s ={' '}
              <span className="tabular font-mono text-fg-soft">
                {formatCompact(data.compute_seconds)}s
              </span>{' '}
              of compute
            </span>
            {data.recommended === currentPlan ? (
              <span className="ml-auto text-success">
                Your current plan is already the cheapest fit for this volume.
              </span>
            ) : data.savings_usd > 0 ? (
              <span className="ml-auto text-success">
                Switching to {data.recommended} would save{' '}
                <span className="tabular font-mono">{formatCurrency(data.savings_usd)}</span>/mo.
              </span>
            ) : (
              <span className="ml-auto text-pending">
                This volume needs {data.recommended} —{' '}
                <span className="tabular font-mono">
                  {formatCurrency(Math.abs(data.savings_usd))}
                </span>
                /mo more than today.
              </span>
            )}
          </div>
        </>
      )}
    </Card>
  )
}
