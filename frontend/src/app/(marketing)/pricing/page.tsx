import Link from 'next/link'

import type { Metadata } from 'next'

import { PLAN_LIMITS, allPlans } from '@/lib/mock/billing'
import { formatCompact } from '@/lib/utils/format'
import { PLAN_TYPES } from '@/types'

export const metadata: Metadata = {
  title: 'Pricing',
  description: 'Durabl pricing — from a free tier to dedicated capacity.',
}

/**
 * Narxlar sahifasi.
 *
 * Limitlar `lib/mock/billing.ts` dagi `PLAN_LIMITS` dan keladi, u esa
 * backend `app/constants.py` dagi `PLAN_LIMITS` bilan AYNI. Shu tufayli
 * marketing sahifasi hech qachon haqiqatdan chetga chiqmaydi.
 *
 * Bu SERVER komponent — interaktivlik yo'q, shuning uchun JS yubormaydi.
 */
const COMPARE_ROWS = [
  { label: 'Jobs per month', value: (p: typeof PLAN_LIMITS.free) => formatCompact(p.monthly_jobs) },
  { label: 'Max runtime', value: (p: typeof PLAN_LIMITS.free) => `${p.max_timeout_seconds}s` },
  { label: 'Concurrent jobs', value: (p: typeof PLAN_LIMITS.free) => String(p.max_concurrent_jobs) },
  { label: 'Memory per job', value: (p: typeof PLAN_LIMITS.free) => `${p.max_memory_mb} MB` },
  { label: 'vCPU per job', value: (p: typeof PLAN_LIMITS.free) => String(p.max_cpus) },
  { label: 'Log retention', value: (p: typeof PLAN_LIMITS.free) => `${p.log_retention_days} days` },
  { label: 'Requests / minute', value: (p: typeof PLAN_LIMITS.free) => formatCompact(p.requests_per_minute) },
  { label: 'Outbound network', value: (p: typeof PLAN_LIMITS.free) => (p.allow_network ? 'Yes' : 'No') },
] as const

export default function PricingPage() {
  // Marketing sahifasida "joriy reja" tushunchasi yo'q
  const plans = allPlans('free').map((plan) => ({ ...plan, is_current: false }))

  return (
    <div className="mx-auto max-w-[1100px] px-5 py-16">
      <h1 className="m-0 text-[36px] font-semibold tracking-[-.03em] text-fg">Pricing</h1>
      <p className="mt-3 max-w-[560px] text-lg text-fg-muted">
        Every plan includes gVisor isolation, idempotency, automatic retries and the dead letter
        queue. You only pay for volume and capacity.
      </p>

      <div className="mt-10 grid gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
        {plans.map((plan) => (
          <div
            key={plan.plan}
            className={`relative flex flex-col rounded-2xl border bg-surface p-5 ${
              plan.is_popular ? 'border-accent/40' : 'border-line'
            }`}
          >
            {plan.is_popular ? (
              <span className="absolute -top-2.5 left-5 rounded border border-accent/30 bg-accent/[0.14] px-2 py-0.5 text-xs font-medium text-accent-light">
                Most popular
              </span>
            ) : null}

            <div className="text-xl font-semibold text-fg">{plan.name}</div>
            <div className="mt-1 min-h-[36px] text-sm text-fg-dim">{plan.description}</div>

            <div className="mt-4 flex items-baseline gap-1.5">
              <span className="tabular font-mono text-4xl font-semibold tracking-[-.02em] text-fg">
                ${plan.price_usd_month}
              </span>
              <span className="text-sm text-fg-faint">/ month</span>
            </div>

            <ul className="mt-5 flex flex-1 flex-col gap-2">
              {plan.features.map((feature) => (
                <li key={feature} className="flex items-start gap-2.5 text-base text-fg-soft">
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.6"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="mt-1 shrink-0 text-accent"
                    aria-hidden
                  >
                    <path d="M5 12l5 5 9-11" />
                  </svg>
                  {feature}
                </li>
              ))}
            </ul>

            <Link
              href="/register"
              className={`mt-5 flex items-center justify-center rounded-lg px-4 py-2 text-base font-medium ${
                plan.is_popular
                  ? 'bg-accent-solid text-white hover:bg-accent-hover hover:text-white'
                  : 'border border-line bg-canvas text-fg-soft hover:border-line-hover hover:text-fg'
              }`}
            >
              {plan.plan === 'enterprise' ? 'Contact sales' : 'Get started'}
            </Link>
          </div>
        ))}
      </div>

      {/* Taqqoslash jadvali */}
      <div className="mt-14 overflow-hidden rounded-2xl border border-line bg-surface">
        <div className="border-b border-line-inner px-5 py-3.5 text-md font-semibold text-fg">
          Compare every limit
        </div>
        <div className="overflow-x-auto">
          <div className="min-w-[680px]">
            <div
              className="grid border-b border-line-inner"
              style={{ gridTemplateColumns: 'minmax(170px,1.4fr) repeat(4, 1fr)' }}
            >
              <div className="px-5 py-3 text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint">
                Limit
              </div>
              {PLAN_TYPES.map((plan) => (
                <div key={plan} className="px-4 py-3 text-center text-base font-semibold text-fg">
                  {PLAN_LIMITS[plan].plan.charAt(0).toUpperCase() + PLAN_LIMITS[plan].plan.slice(1)}
                </div>
              ))}
            </div>

            {COMPARE_ROWS.map((row) => (
              <div
                key={row.label}
                className="grid border-b border-line-subtle last:border-b-0"
                style={{ gridTemplateColumns: 'minmax(170px,1.4fr) repeat(4, 1fr)' }}
              >
                <div className="px-5 py-2.5 text-sm text-fg-muted">{row.label}</div>
                {PLAN_TYPES.map((plan) => (
                  <div
                    key={plan}
                    className="tabular px-4 py-2.5 text-center font-mono text-sm text-fg-soft"
                  >
                    {row.value(PLAN_LIMITS[plan])}
                  </div>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-10 rounded-2xl border border-line bg-surface px-5 py-6 text-center">
        <div className="text-lg font-semibold text-fg">Need something else?</div>
        <p className="mx-auto mt-2 max-w-[520px] text-base text-fg-muted">
          Dedicated workers, self-hosted gVisor nodes, SSO and audit logs are available on
          Enterprise.
        </p>
        <Link
          href="/register"
          className="mt-4 inline-flex rounded-lg bg-accent-solid px-5 py-2.5 text-base font-medium text-white hover:bg-accent-hover hover:text-white"
        >
          Talk to us
        </Link>
      </div>
    </div>
  )
}
