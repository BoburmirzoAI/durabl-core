'use client'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { cn } from '@/lib/utils/cn'
import { formatCurrency } from '@/lib/utils/format'
import type { PlanInfo } from '@/types'

/**
 * Reja kartasi — narx jadvalida va billing sahifasida ishlatiladi.
 *
 * `is_popular` bo'lsa aksent chegara va "Most popular" nishoni
 * (dizaynda Pro reja shunday ajratilgan).
 */
export function PlanCard({
  plan,
  onSelect,
  pending = false,
}: {
  plan: PlanInfo
  onSelect?: (plan: PlanInfo) => void
  pending?: boolean
}) {
  return (
    <Card
      className={cn(
        'relative flex flex-col p-5',
        plan.is_popular && 'border-accent/40',
        plan.is_current && 'border-accent/60 ring-1 ring-accent/20',
      )}
    >
      {plan.is_popular && !plan.is_current ? (
        <Badge variant="accent" className="absolute -top-2.5 left-5">
          Most popular
        </Badge>
      ) : null}
      {plan.is_current ? (
        <Badge variant="accent" className="absolute -top-2.5 left-5">
          Current plan
        </Badge>
      ) : null}

      <div className="text-xl font-semibold text-fg">{plan.name}</div>
      <div className="mt-1 min-h-[36px] text-sm text-fg-dim">{plan.description}</div>

      <div className="mt-4 flex items-baseline gap-1.5">
        <span className="tabular font-mono text-4xl font-semibold tracking-[-.02em] text-fg">
          {plan.price_usd_month === 0 ? '$0' : formatCurrency(plan.price_usd_month)}
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

      {onSelect ? (
        <Button
          variant={plan.is_current ? 'secondary' : plan.is_popular ? 'primary' : 'secondary'}
          size="md"
          disabled={plan.is_current || pending}
          onClick={() => onSelect(plan)}
          className="mt-5 justify-center"
        >
          {plan.is_current ? 'Current plan' : `Switch to ${plan.name}`}
        </Button>
      ) : null}
    </Card>
  )
}
