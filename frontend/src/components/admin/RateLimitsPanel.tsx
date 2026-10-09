'use client'

import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { SkeletonRows } from '@/components/ui/skeleton'
import { Tabs } from '@/components/ui/tabs'
import { useRateLimits, useUpdateRateLimit } from '@/lib/hooks/usePlatform'
import type { RateLimitRule } from '@/types'

const GRID = 'minmax(90px,.8fr) 110px 100px 110px 120px 130px 92px'

/**
 * Tarif bo'yicha tezlik chegaralari.
 *
 * ## Nega "burst" alohida
 *
 * Daqiqalik chegara o'rtacha yuklamani ushlaydi, lekin haqiqiy trafik
 * tekis emas: mijoz soat boshida 200 ta job yuborib, keyin jim bo'ladi.
 * Token bucket hajmi (`burst`) aynan shunga ruxsat beradi — chegarani
 * ko'tarmasdan.
 *
 * Shuning uchun `burst < requests_per_minute` — mantiqiy xato: bunday
 * chelak hech qachon to'lmaydi. Backend buni rad etadi.
 *
 * ## Nega "on exceed" muhim
 *
 * Bepul tarifda ortiqcha so'rov RAD ETILADI (429) — aks holda bitta
 * bepul hisob navbatni to'ldirib qo'yishi mumkin. Pulli tariflarda esa
 * NAVBATGA turadi: mijoz pul to'lagan, ishi yo'qolmasligi kerak.
 */
export function RateLimitsPanel() {
  const query = useRateLimits()
  const update = useUpdateRateLimit()
  const [drafts, setDrafts] = useState<Record<string, RateLimitRule>>({})

  useEffect(() => {
    if (!query.data) return
    setDrafts(Object.fromEntries(query.data.map((rule) => [rule.plan, rule])))
  }, [query.data])

  const set = (plan: string, patch: Partial<RateLimitRule>): void =>
    setDrafts((current) => {
      const row = current[plan]
      return row ? { ...current, [plan]: { ...row, ...patch } } : current
    })

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">Rate limits</CardTitle>
        <CardDescription>
          Per plan. Burst is the token bucket size — it must be at least the per-minute rate, or it
          never fills.
        </CardDescription>
      </CardHeader>

      <div className="overflow-x-auto">
        <div className="min-w-[820px]">
          <div className="table-head grid items-center gap-3 px-4" style={{ gridTemplateColumns: GRID }}>
            <span>Plan</span>
            <span className="text-right">Req / min</span>
            <span className="text-right">Burst</span>
            <span className="text-right">Concurrency</span>
            <span className="text-right">Daily cap</span>
            <span>On exceed</span>
            <span className="sr-only">Save</span>
          </div>

          {query.isLoading && !query.data ? (
            <SkeletonRows rows={4} columns={GRID} />
          ) : (
            (query.data ?? []).map((rule) => {
              const draft = drafts[rule.plan] ?? rule
              const dirty = JSON.stringify(draft) !== JSON.stringify(rule)
              return (
                <div
                  key={rule.plan}
                  className="grid min-h-[52px] items-center gap-3 border-b border-line-subtle px-4 py-2 last:border-b-0"
                  style={{ gridTemplateColumns: GRID }}
                >
                  <span className="text-base capitalize text-fg-soft">{rule.plan}</span>
                  <NumberCell
                    value={draft.requests_per_minute}
                    label={`${rule.plan} requests per minute`}
                    onChange={(value) => set(rule.plan, { requests_per_minute: value })}
                  />
                  <NumberCell
                    value={draft.burst}
                    label={`${rule.plan} burst`}
                    invalid={draft.burst < draft.requests_per_minute}
                    onChange={(value) => set(rule.plan, { burst: value })}
                  />
                  <NumberCell
                    value={draft.max_concurrent_jobs}
                    label={`${rule.plan} concurrency`}
                    onChange={(value) => set(rule.plan, { max_concurrent_jobs: value })}
                  />
                  <NumberCell
                    value={draft.daily_submit_cap}
                    label={`${rule.plan} daily cap`}
                    nullable
                    onChange={(value) => set(rule.plan, { daily_submit_cap: value })}
                  />
                  <Tabs
                    aria-label={`${rule.plan} behaviour when exceeded`}
                    items={[
                      { value: 'reject' as const, label: 'Reject' },
                      { value: 'queue' as const, label: 'Queue' },
                    ]}
                    value={draft.on_exceed}
                    onChange={(value) => set(rule.plan, { on_exceed: value })}
                  />
                  <span className="flex justify-end">
                    <Button
                      variant={dirty ? 'primary' : 'ghost'}
                      size="sm"
                      disabled={!dirty || update.isPending}
                      onClick={() => update.mutate({ plan: rule.plan, patch: draft })}
                    >
                      {dirty ? 'Save' : 'Saved'}
                    </Button>
                  </span>
                </div>
              )
            })
          )}
        </div>
      </div>
    </Card>
  )
}

/**
 * Raqamli katak.
 *
 * `nullable` — "limitsiz" holatini ifodalaydi: bo'sh maydon `null` ga
 * aylanadi va UI'da "none" ko'rsatiladi.
 */
function NumberCell({
  value,
  label,
  onChange,
  nullable = false,
  invalid = false,
}: {
  value: number | null
  label: string
  onChange: (value: never) => void
  nullable?: boolean
  invalid?: boolean
}) {
  return (
    <Input
      value={value === null ? '' : String(value)}
      placeholder={nullable ? 'none' : '0'}
      aria-label={label}
      aria-invalid={invalid}
      inputMode="numeric"
      onChange={(event) => {
        const raw = event.target.value.replace(/\D/g, '')
        if (raw === '') {
          onChange((nullable ? null : 0) as never)
          return
        }
        onChange(Number(raw) as never)
      }}
      className={`tabular h-8 text-right font-mono text-xs ${invalid ? 'border-failed/50' : ''}`}
    />
  )
}
