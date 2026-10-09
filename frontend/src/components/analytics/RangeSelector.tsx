'use client'

import { useState } from 'react'

import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Tabs } from '@/components/ui/tabs'
import { customRange, parseRange, rangeLabel } from '@/lib/utils/time'
import { cn } from '@/lib/utils/cn'

const PRESETS = [
  { value: '1h', label: '1h' },
  { value: '24h', label: '24h' },
  { value: '7d', label: '7d' },
  { value: '30d', label: '30d' },
] as const

/** `<input type="date">` uchun `YYYY-MM-DD`. */
function toInputDate(ms: number): string {
  return new Date(ms).toISOString().slice(0, 10)
}

/**
 * Vaqt oralig'i tanlagichi — tayyor variantlar + ixtiyoriy sana.
 *
 * ## Nega dialog, popover emas
 *
 * Ikki sana maydoni va tekshiruv xabari popoverga sig'maydi; dialog esa
 * loyihada allaqachon bor va mobil ekranda ham to'g'ri joylashadi.
 *
 * ## Tekshiruv
 *
 * Kelajakdagi sana va teskari oraliq (`to < from`) qabul qilinmaydi —
 * aks holda grafik bo'sh chiqadi va foydalanuvchi sababini bilmaydi.
 */
export function RangeSelector({
  value,
  onChange,
}: {
  value: string
  onChange: (range: string) => void
}) {
  const [open, setOpen] = useState(false)
  const spec = parseRange(value)
  const isCustom = spec.isCustom

  const [from, setFrom] = useState(() => toInputDate(spec.from))
  const [to, setTo] = useState(() => toInputDate(spec.to))

  const today = toInputDate(Date.now())
  const fromMs = new Date(`${from}T00:00:00.000Z`).getTime()
  const toMs = new Date(`${to}T23:59:59.999Z`).getTime()
  const invalid =
    Number.isNaN(fromMs) || Number.isNaN(toMs)
      ? 'Pick both dates.'
      : toMs <= fromMs
        ? 'The end date must be after the start date.'
        : fromMs > Date.now()
          ? 'The start date is in the future.'
          : null

  return (
    <>
      <div className="flex items-center gap-2">
        <Tabs
          aria-label="Time range"
          items={PRESETS}
          value={isCustom ? '' : value}
          onChange={onChange}
        />
        <button
          type="button"
          onClick={() => setOpen(true)}
          className={cn(
            'inline-flex h-[30px] items-center gap-1.5 rounded-lg border px-2.5 text-sm transition-colors',
            isCustom
              ? 'border-accent-edge bg-accent-bar-2 text-fg-soft'
              : 'border-line bg-surface text-fg-dim hover:border-line-hover hover:text-fg',
          )}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden>
            <rect x="3" y="5" width="18" height="16" rx="2" />
            <path d="M3 10h18M8 3v4M16 3v4" />
          </svg>
          {isCustom ? rangeLabel(value) : 'Custom'}
        </button>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent width="sm">
          <DialogHeader>
            <div>
              <DialogTitle>Custom date range</DialogTitle>
              <DialogDescription>
                Both dates are inclusive and interpreted in UTC.
              </DialogDescription>
            </div>
          </DialogHeader>

          <DialogBody className="space-y-3.5">
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="From" value={from} max={today} onChange={setFrom} />
              <Field label="To" value={to} max={today} onChange={setTo} />
            </div>
            {invalid ? (
              <p className="text-sm text-failed-text">{invalid}</p>
            ) : (
              <p className="text-sm text-fg-dim">
                {Math.round((toMs - fromMs) / 86_400_000)} day
                {Math.round((toMs - fromMs) / 86_400_000) === 1 ? '' : 's'} selected.
              </p>
            )}
          </DialogBody>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="md"
              disabled={invalid !== null}
              onClick={() => {
                onChange(customRange(new Date(fromMs), new Date(toMs)))
                setOpen(false)
              }}
            >
              Apply range
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}

function Field({
  label,
  value,
  max,
  onChange,
}: {
  label: string
  value: string
  max: string
  onChange: (value: string) => void
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
        {label}
      </span>
      <input
        type="date"
        value={value}
        max={max}
        onChange={(event) => onChange(event.target.value)}
        className="h-[34px] w-full rounded-lg border border-line bg-canvas-deep px-2.5 font-mono text-sm text-fg-soft outline-none transition-colors focus:border-accent-edge-2"
      />
    </label>
  )
}
