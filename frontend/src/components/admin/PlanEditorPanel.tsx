'use client'

import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Skeleton } from '@/components/ui/skeleton'
import { usePlanConfigs, useUpdatePlanConfig } from '@/lib/hooks/usePlatform'
import { formatCompact, formatCurrency } from '@/lib/utils/format'
import type { PlanConfig } from '@/types'

/**
 * Tarif va narx muharriri.
 *
 * ## Nega har bir tarif alohida kartada
 *
 * Tarifda 9 ta maydon bor. Jadval ko'rinishida ular 9 ta tor ustun
 * bo'lib, hech biri o'qilmaydi. Karta esa har bir tarifni bir butun
 * sifatida ko'rsatadi — narx tanlashda aynan shunday qaraladi.
 *
 * ## Mavjud mijozlarga ta'siri
 *
 * Narx o'zgarishi joriy obunalarni DARHOL o'zgartirmaydi — ular keyingi
 * davrda ko'chadi. Buni UI aniq aytadi, chunki "narxni ko'tardim, mijoz
 * darhol ko'proq to'laydi" degan taxmin xato va qimmatga tushadi.
 */
export function PlanEditorPanel() {
  const query = usePlanConfigs()
  const update = useUpdatePlanConfig()
  const [drafts, setDrafts] = useState<Record<string, PlanConfig>>({})

  useEffect(() => {
    if (!query.data) return
    setDrafts(Object.fromEntries(query.data.map((config) => [config.plan, config])))
  }, [query.data])

  const set = (plan: string, patch: Partial<PlanConfig>): void =>
    setDrafts((current) => {
      const row = current[plan]
      return row ? { ...current, [plan]: { ...row, ...patch } } : current
    })

  if (query.isLoading && !query.data) {
    return (
      <Card className="p-4">
        <Skeleton className="h-56 w-full" />
      </Card>
    )
  }

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">Plans &amp; pricing</CardTitle>
        <CardDescription>
          New subscriptions use these immediately. Existing customers move at their next renewal.
        </CardDescription>
      </CardHeader>

      <div className="grid gap-px bg-line-subtle lg:grid-cols-2 2xl:grid-cols-4">
        {(query.data ?? []).map((config) => {
          const draft = drafts[config.plan] ?? config
          const dirty = JSON.stringify(draft) !== JSON.stringify(config)
          return (
            <div key={config.plan} className="bg-surface p-4">
              <div className="flex items-center gap-2">
                <span className="text-md font-semibold capitalize text-fg">{config.plan}</span>
                {!draft.is_public ? (
                  <span className="rounded border border-line px-1.5 py-px text-2xs text-fg-faint">
                    hidden
                  </span>
                ) : null}
                <span className="tabular ml-auto font-mono text-sm text-fg-muted">
                  {formatCurrency(draft.price_usd_month)}/mo
                </span>
              </div>

              <div className="mt-3 space-y-2.5">
                <Field
                  label="Price (USD / month)"
                  value={draft.price_usd_month}
                  onChange={(value) => set(config.plan, { price_usd_month: value })}
                />
                <Field
                  label="Monthly jobs"
                  value={draft.monthly_jobs}
                  hint={formatCompact(draft.monthly_jobs)}
                  onChange={(value) => set(config.plan, { monthly_jobs: value })}
                />
                <Field
                  label="Overage per 1k (USD)"
                  value={draft.overage_per_1k_usd}
                  decimal
                  onChange={(value) => set(config.plan, { overage_per_1k_usd: value })}
                />
                <Field
                  label="Max timeout (s)"
                  value={draft.max_timeout_seconds}
                  onChange={(value) => set(config.plan, { max_timeout_seconds: value })}
                />
                <Field
                  label="Max memory (MB)"
                  value={draft.max_memory_mb}
                  onChange={(value) => set(config.plan, { max_memory_mb: value })}
                />
                <Field
                  label="Log retention (days)"
                  value={draft.log_retention_days}
                  onChange={(value) => set(config.plan, { log_retention_days: value })}
                />

                <Toggle
                  label="Outbound network"
                  checked={draft.allow_network}
                  onChange={(value) => set(config.plan, { allow_network: value })}
                />
                <Toggle
                  label="Listed publicly"
                  checked={draft.is_public}
                  onChange={(value) => set(config.plan, { is_public: value })}
                />
              </div>

              <Button
                variant={dirty ? 'primary' : 'ghost'}
                size="sm"
                className="mt-3 w-full"
                disabled={!dirty || update.isPending}
                onClick={() => update.mutate({ plan: config.plan, patch: draft })}
              >
                {dirty ? `Save ${config.plan}` : 'Saved'}
              </Button>
            </div>
          )
        })}
      </div>
    </Card>
  )
}

function Field({
  label,
  value,
  hint,
  decimal = false,
  onChange,
}: {
  label: string
  value: number
  hint?: string
  decimal?: boolean
  onChange: (value: number) => void
}) {
  return (
    <label className="flex items-center justify-between gap-3">
      <span className="min-w-0 flex-1 text-sm text-fg-dim">
        {label}
        {hint ? <span className="ml-1.5 text-xs text-fg-ghost">{hint}</span> : null}
      </span>
      <Input
        value={String(value)}
        inputMode="decimal"
        aria-label={label}
        onChange={(event) => {
          const raw = event.target.value.replace(decimal ? /[^\d.]/g : /\D/g, '')
          onChange(raw === '' ? 0 : Number(raw))
        }}
        className="tabular h-8 w-[96px] shrink-0 text-right font-mono text-xs"
      />
    </label>
  )
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string
  checked: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-sm text-fg-dim">{label}</span>
      <Switch checked={checked} onCheckedChange={onChange} aria-label={label} />
    </div>
  )
}
