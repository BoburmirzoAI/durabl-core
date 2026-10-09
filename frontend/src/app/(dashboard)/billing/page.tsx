'use client'

import { Badge } from '@/components/ui/badge'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { DailyVolumeChart } from '@/components/billing/DailyVolumeChart'
import { ErrorState } from '@/components/common/ErrorState'
import { InvoicesTable } from '@/components/billing/InvoicesTable'
import { PlanCard } from '@/components/billing/PlanCard'
import { SectionHeader } from '@/components/common/SectionHeader'
import { Skeleton } from '@/components/ui/skeleton'
import { UsageMeter } from '@/components/billing/UsageMeter'
import {
  useChangePlan,
  useDailyVolume,
  useInvoices,
  usePlanComparison,
  usePlans,
  useUsage,
} from '@/lib/hooks/useBilling'
import { cn } from '@/lib/utils/cn'
import { formatDate } from '@/lib/utils/time'
import { PLAN_TYPES, type PlanType } from '@/types'

/**
 * Billing — dizayndagi "Billing & Usage" sahifasi.
 *
 * Tuzilma: joriy reja kartasi + o'lchagichlar / kunlik hajm grafigi /
 * reja taqqoslash jadvali + kartalar / hisob-fakturalar.
 */
export default function BillingPage() {
  const usage = useUsage()
  const plans = usePlans()
  const volume = useDailyVolume()
  const invoices = useInvoices()
  const comparison = usePlanComparison()
  const changePlan = useChangePlan()

  const currentPlan = plans.data?.find((p) => p.is_current)
  const dailyLimit = usage.data ? Math.round(usage.data.monthly_limit / 30) : 0

  return (
    <>
      <SectionHeader
        title="Billing & Usage"
        count={
          currentPlan ? <Badge variant="accent">{currentPlan.name} Plan</Badge> : null
        }
        description={
          usage.data
            ? `Current period ${formatDate(usage.data.period_start)} — next invoice ${formatDate(usage.data.period_end)}`
            : undefined
        }
      />

      {usage.error ? (
        <ErrorState error={usage.error} onRetry={() => void usage.refetch()} />
      ) : (
        <div className="grid items-start gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)]">
          {currentPlan ? (
            <PlanCard plan={currentPlan} />
          ) : (
            <Card className="p-5">
              <Skeleton className="h-6 w-28" />
              <Skeleton className="mt-4 h-9 w-32" />
              <Skeleton className="mt-5 h-24 w-full" />
            </Card>
          )}

          <div className="grid gap-3.5 sm:grid-cols-3">
            {usage.data
              ? usage.data.meters.map((meter) => <UsageMeter key={meter.key} meter={meter} />)
              : Array.from({ length: 3 }, (_, i) => (
                  <Card key={i} radius="xl" className="px-4 py-[15px]">
                    <Skeleton className="h-3 w-20" />
                    <Skeleton className="mt-3 h-5 w-28" />
                    <Skeleton className="mt-3 h-2 w-full" />
                  </Card>
                ))}
          </div>
        </div>
      )}

      <DailyVolumeChart
        data={volume.data}
        dailyLimit={dailyLimit}
        loading={volume.isLoading}
        error={volume.error}
        onRetry={() => void volume.refetch()}
      />

      {/* Reja taqqoslash jadvali */}
      <Card className="overflow-hidden">
        <CardHeader>
          <CardTitle className="text-md">Compare plans</CardTitle>
        </CardHeader>

        <div className="overflow-x-auto">
          <div className="min-w-[640px]">
            <div
              className="grid border-b border-line-inner"
              style={{ gridTemplateColumns: 'minmax(160px,1.4fr) repeat(4, 1fr)' }}
            >
              <div className="px-4 py-3 text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">
                Feature
              </div>
              {PLAN_TYPES.map((plan) => {
                const info = plans.data?.find((p) => p.plan === plan)
                return (
                  <div
                    key={plan}
                    className={cn(
                      'px-4 py-3 text-center',
                      info?.is_current && 'bg-accent/[0.06]',
                    )}
                  >
                    <div className="text-base font-semibold text-fg">{info?.name ?? plan}</div>
                    <div className="tabular mt-0.5 font-mono text-xs text-fg-faint">
                      ${info?.price_usd_month ?? 0}/mo
                    </div>
                  </div>
                )
              })}
            </div>

            {(comparison.data ?? []).map((row) => (
              <div
                key={row.label}
                className="grid border-b border-line-subtle last:border-b-0"
                style={{ gridTemplateColumns: 'minmax(160px,1.4fr) repeat(4, 1fr)' }}
              >
                <div className="px-4 py-2.5 text-sm text-fg-muted">{row.label}</div>
                {PLAN_TYPES.map((plan) => {
                  const info = plans.data?.find((p) => p.plan === plan)
                  return (
                    <div
                      key={plan}
                      className={cn(
                        'tabular px-4 py-2.5 text-center font-mono text-sm text-fg-soft',
                        info?.is_current && 'bg-accent/[0.06]',
                      )}
                    >
                      {row.values[plan]}
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
        </div>
      </Card>

      <div className="grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
        {(plans.data ?? []).map((plan) => (
          <PlanCard
            key={plan.plan}
            plan={plan}
            pending={changePlan.isPending}
            onSelect={(selected) => changePlan.mutate(selected.plan as PlanType)}
          />
        ))}
      </div>

      <InvoicesTable invoices={invoices.data} />
    </>
  )
}
