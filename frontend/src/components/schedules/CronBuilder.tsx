'use client'

import { Input } from '@/components/ui/input'
import { useCronValidation } from '@/lib/hooks/useSchedules'
import { CRON_PRESETS } from '@/lib/utils/cron'
import { cn } from '@/lib/utils/cn'
import { formatTimestamp } from '@/lib/utils/time'

/**
 * Cron muharriri — yozayotganda darhol tushuntiradi.
 *
 * ## Nega shunday
 *
 * Cron yozish — xato qilish eng oson joy. `0 0 * * 0` haftalikmi yoki
 * kunlikmi? Shuning uchun uchta narsa DARHOL ko'rsatiladi:
 *
 * 1. **Tavsif** — "At 00:00 on Sunday". Noto'g'ri ifoda yozilganini
 *    shu yerda, saqlashdan OLDIN ko'rish mumkin.
 * 2. **Keyingi 5 ta ishga tushish** — tavsif ham chalg'itishi mumkin,
 *    aniq sanalar esa yo'q.
 * 3. **Sutkalik soni** — `*` yozib qo'yib, kuniga 1440 ta job
 *    yuborishning oldini oladi.
 *
 * Tayyor variantlar esa ko'pchilik holatni cron yozmasdan qoplaydi.
 */
export function CronBuilder({
  value,
  onChange,
  label = 'Schedule',
}: {
  value: string
  onChange: (cron: string) => void
  label?: string
}) {
  const check = useCronValidation(value)
  const result = check.data
  const invalid = result !== undefined && !result.valid
  // Kuniga 100 dan ortiq ishga tushish — ehtimol xato
  const heavy = (result?.runs_per_day ?? 0) > 100

  return (
    <div className="space-y-2.5">
      <label className="block">
        <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
          {label}
        </span>
        <Input
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder="0 2 * * *"
          spellCheck={false}
          aria-label="Cron expression"
          aria-invalid={invalid}
          className={cn('font-mono', invalid && 'border-failed/50')}
        />
      </label>

      <div className="flex flex-wrap gap-1.5">
        {CRON_PRESETS.map((preset) => (
          <button
            key={preset.cron}
            type="button"
            onClick={() => onChange(preset.cron)}
            className={cn(
              'rounded-md border px-2 py-1 text-xs transition-colors',
              value.trim() === preset.cron
                ? 'border-accent-edge bg-accent-bar-2 text-fg-soft'
                : 'border-line bg-surface text-fg-dim hover:border-line-hover hover:text-fg',
            )}
          >
            {preset.label}
          </button>
        ))}
      </div>

      <div className="rounded-lg border border-line-inner bg-canvas-deep px-3.5 py-3">
        {value.trim().length === 0 ? (
          <p className="text-sm text-fg-faint">
            Enter a 5-field cron expression, or pick one above.
          </p>
        ) : invalid ? (
          <p className="text-sm text-failed-text">{result?.error}</p>
        ) : result ? (
          <>
            <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="text-base text-fg-soft">{result.description}</span>
              <span
                className={cn(
                  'tabular font-mono text-xs',
                  heavy ? 'text-pending' : 'text-fg-faint',
                )}
              >
                {result.runs_per_day >= 200
                  ? '200+ runs/day'
                  : `${result.runs_per_day} run${result.runs_per_day === 1 ? '' : 's'}/day`}
              </span>
            </div>
            {heavy ? (
              <p className="mt-1.5 text-sm text-pending">
                That is a lot of runs. Each one counts against your monthly job quota.
              </p>
            ) : null}
            <div className="mt-2.5 border-t border-line-subtle pt-2.5">
              <div className="text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                Next runs (UTC)
              </div>
              <div className="mt-1.5 space-y-0.5">
                {result.next_runs.map((run) => (
                  <div key={run} className="tabular font-mono text-xs text-fg-muted">
                    {formatTimestamp(run)}
                  </div>
                ))}
              </div>
            </div>
          </>
        ) : (
          <p className="text-sm text-fg-faint">Checking…</p>
        )}
      </div>
    </div>
  )
}
