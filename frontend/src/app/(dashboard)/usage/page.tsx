'use client'

import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { DailyVolumeChart } from '@/components/billing/DailyVolumeChart'
import { ErrorState } from '@/components/common/ErrorState'
import { SectionHeader } from '@/components/common/SectionHeader'
import { UsageMeter } from '@/components/billing/UsageMeter'
import { CostCalculator } from '@/components/usage/CostCalculator'
import { CostProjectionCard } from '@/components/usage/CostProjectionCard'
import { PlanChangeDialog } from '@/components/usage/PlanChangeDialog'
import { QuotaDrilldown } from '@/components/usage/QuotaDrilldown'
import { RuntimeCostTable } from '@/components/usage/RuntimeCostTable'
import { Skeleton } from '@/components/ui/skeleton'
import { useCostProjection, useDailyVolume, useRuntimeCosts, useUsage } from '@/lib/hooks/useBilling'
import { useToast } from '@/components/common/ToastProvider'
import { cn } from '@/lib/utils/cn'
import { downloadCsv, timestampedName, toCsv } from '@/lib/utils/csv'
import { formatNumber } from '@/lib/utils/format'
import { formatDate } from '@/lib/utils/time'
import { PLAN_TYPES, type PlanType } from '@/types'

/**
 * Usage — REJA KVOTASI va XARAJAT.
 *
 * ═══════════════════════════════════════════════════════════════════
 * BU SAHIFANING VAZIFASI
 * ═══════════════════════════════════════════════════════════════════
 *
 * "Rejamning qanchasini ishlatdim va bu qancha turadi?"
 *
 * Bu yerda ish samaradorligi ko'rsatkichlari (p99, success rate,
 * throughput tendensiyasi) YO'Q — ular `/analytics` sahifasida.
 * Ilgari bu sahifa analitikaning aynan KPI kartalarini va runtime
 * donutini takrorlardi; endi runtime taqsimoti XARAJAT nuqtai
 * nazaridan ko'rsatiladi (dollar, compute-sekund), ulush sifatida emas.
 */
export default function UsagePage() {
  const usage = useUsage()
  const volume = useDailyVolume()
  const projection = useCostProjection()
  const runtimeCosts = useRuntimeCosts()
  const { toast } = useToast()

  const [quotaKey, setQuotaKey] = useState<string | null>(null)
  const [targetPlan, setTargetPlan] = useState<PlanType | null>(null)

  const dailyLimit = usage.data ? Math.round(usage.data.monthly_limit / 30) : 0

  /**
   * Hisobga ilovaga tayyor eksport.
   *
   * Moliya bo'limiga "ekrandan ko'chirib oling" deb bo'lmaydi — kunlik
   * qatorlar + davr xulosasi bitta CSV'da beriladi.
   */
  function exportPeriod(): void {
    const summary = usage.data
    const days = volume.data
    if (!summary || !days) {
      toast({ title: 'Usage data is still loading' })
      return
    }
    const rows: { date: string; jobs: number; note: string }[] = days.map((d) => ({
      date: d.date.slice(0, 10),
      jobs: d.count,
      note: d.over_limit ? 'over daily pace' : '',
    }))
    rows.push({ date: 'TOTAL', jobs: summary.job_count, note: `plan ${summary.plan}` })
    rows.push({
      date: 'ALLOWANCE',
      jobs: summary.monthly_limit,
      note: `${summary.usage_percent}% consumed`,
    })
    downloadCsv(
      timestampedName(`durabl-usage-${summary.period}`),
      toCsv(rows, [
        { header: 'date', value: (r) => r.date },
        { header: 'jobs', value: (r) => r.jobs },
        { header: 'note', value: (r) => r.note },
      ]),
    )
    toast({
      title: 'Usage exported',
      description: `${days.length} daily rows plus period totals.`,
    })
  }

  return (
    <>
      <SectionHeader
        title="Usage & billing"
        description={
          usage.data
            ? `Billing period ${formatDate(usage.data.period_start)} — ${formatDate(usage.data.period_end)}`
            : 'Current billing period'
        }
        actions={
          <Button variant="secondary" onClick={exportPeriod}>
            Export period
          </Button>
        }
      />

      {usage.error ? (
        <ErrorState error={usage.error} onRetry={() => void usage.refetch()} />
      ) : (
        <>
          {/* Limitdan oshish ogohlantirishi — eng tepada, e'tiborni tortadigan joyda */}
          {usage.data?.is_over_limit ? (
            <OverageBanner
              tone="critical"
              title="Monthly allowance exceeded"
              body={
                <>
                  New submissions are rejected with{' '}
                  <span className="font-mono">402 QUOTA_EXCEEDED</span>. Upgrade the plan or wait
                  for the period to reset.
                </>
              }
            />
          ) : projection.data?.will_exceed ? (
            <OverageBanner
              tone="warning"
              title="On track to exceed the plan"
              body={
                <>
                  At the current rate you will use more than{' '}
                  {formatNumber(usage.data?.monthly_limit ?? 0)} jobs this period — about{' '}
                  <span className="font-mono">${projection.data.overage_usd.toFixed(2)}</span> in
                  overage.
                </>
              }
            />
          ) : null}

          {/* Kvota o'lchagichlari + xarajat prognozi */}
          <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
            {usage.data
              ? usage.data.meters.map((meter) => (
                  <UsageMeter
                    key={meter.key}
                    meter={meter}
                    onOpenDetail={(m) => setQuotaKey(m.key)}
                  />
                ))
              : Array.from({ length: 3 }, (_, i) => (
                  <Card key={i} radius="xl" className="px-4 py-[15px]">
                    <Skeleton className="h-3 w-20" />
                    <Skeleton className="mt-3 h-5 w-28" />
                    <Skeleton className="mt-3 h-2 w-full" />
                  </Card>
                ))}
            <CostProjectionCard data={projection.data} loading={projection.isLoading} />
          </div>
        </>
      )}

      <DailyVolumeChart
        data={volume.data}
        dailyLimit={dailyLimit}
        loading={volume.isLoading}
        error={volume.error}
        onRetry={() => void volume.refetch()}
      />

      <CostCalculator currentPlan={usage.data?.plan ?? 'pro'} />

      <PlanSwitcher
        currentPlan={usage.data?.plan ?? null}
        onPick={setTargetPlan}
      />

      <div className="grid gap-4 xl:grid-cols-2">
        <RuntimeCostTable rows={runtimeCosts.data} loading={runtimeCosts.isLoading} />

        <Card className="overflow-hidden">
          <div className="border-b border-line-inner px-4 py-[15px]">
            <div className="text-md font-semibold text-fg">Quota breakdown</div>
            <span className="text-xs text-fg-dim">Jobs counted against this period</span>
          </div>
          <div className="flex flex-col gap-4 p-4">
            {usage.data ? (
              <>
                <QuotaRow
                  label="Used"
                  value={formatNumber(usage.data.job_count)}
                  percent={usage.data.usage_percent}
                />
                <QuotaRow
                  label="Remaining"
                  value={formatNumber(usage.data.remaining)}
                  percent={100 - usage.data.usage_percent}
                  barClassName="bg-success"
                />
                <div className="flex items-center justify-between border-t border-line-subtle pt-3 text-sm">
                  <span className="text-fg-dim">Monthly allowance</span>
                  <span className="tabular font-mono text-fg">
                    {formatNumber(usage.data.monthly_limit)}
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-fg-dim">Plan</span>
                  <span className="font-mono text-fg-soft">{usage.data.plan}</span>
                </div>
              </>
            ) : (
              <Skeleton className="h-24 w-full" />
            )}
          </div>
        </Card>
      </div>

      <QuotaDrilldown
        quotaKey={quotaKey}
        onOpenChange={(open) => {
          if (!open) setQuotaKey(null)
        }}
      />

      <PlanChangeDialog
        plan={targetPlan}
        onOpenChange={(open) => {
          if (!open) setTargetPlan(null)
        }}
      />
    </>
  )
}

/**
 * Reja tanlagich — bosilganda to'liq solishtiruv dialogini ochadi.
 *
 * Narxlar sahifasi (`/billing`) rejalarni SOTADI; bu yerda esa qaror
 * joriy foydalanish kontekstida qabul qilinadi, shuning uchun tanlagich
 * ixcham va dialog hamma tafsilotni o'zi ko'rsatadi.
 */
function PlanSwitcher({
  currentPlan,
  onPick,
}: {
  currentPlan: PlanType | null
  onPick: (plan: PlanType) => void
}) {
  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-center gap-3 px-4 py-3.5">
        <div className="min-w-0">
          <div className="text-md font-semibold text-fg">Change plan</div>
          <span className="text-xs text-fg-dim">
            See exactly which limits change before you commit
          </span>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {PLAN_TYPES.map((plan) => (
            <Button
              key={plan}
              variant={plan === currentPlan ? 'bulk' : 'outline'}
              disabled={plan === currentPlan}
              onClick={() => onPick(plan)}
              className="capitalize"
            >
              {plan === currentPlan ? `${plan} · current` : plan}
            </Button>
          ))}
        </div>
      </div>
    </Card>
  )
}

function OverageBanner({
  tone,
  title,
  body,
}: {
  tone: 'warning' | 'critical'
  title: string
  body: React.ReactNode
}) {
  return (
    <div
      className={cn(
        'flex items-start gap-3 rounded-xl border px-4 py-3',
        tone === 'critical'
          ? 'border-failed/25 bg-failed/[0.07]'
          : 'border-pending/25 bg-pending/[0.07]',
      )}
    >
      <svg
        width="17"
        height="17"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.9"
        strokeLinecap="round"
        strokeLinejoin="round"
        className={cn('mt-0.5 shrink-0', tone === 'critical' ? 'text-failed' : 'text-pending')}
        aria-hidden
      >
        <path d="M12 3 2 20h20zM12 10v4M12 17h.01" />
      </svg>
      <div className="min-w-0">
        <div className={cn('text-base font-medium', tone === 'critical' ? 'text-failed-bright' : 'text-fg')}>
          {title}
        </div>
        <div className="mt-0.5 text-sm text-fg-dim">{body}</div>
      </div>
    </div>
  )
}

function QuotaRow({
  label,
  value,
  percent,
  barClassName = 'bg-accent',
}: {
  label: string
  value: string
  percent: number
  barClassName?: string
}) {
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="text-fg-soft">{label}</span>
        <span className="tabular font-mono text-fg">{value}</span>
      </div>
      <div className="mt-2 h-1.5 overflow-hidden rounded-sm bg-line">
        <div
          className={cn('h-full rounded-sm transition-[width] duration-500', barClassName)}
          style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
        />
      </div>
    </div>
  )
}
