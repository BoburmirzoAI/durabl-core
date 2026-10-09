'use client'

import { useState } from 'react'

import { CopyButton } from '@/components/common/CopyButton'
import { cn } from '@/lib/utils/cn'

/**
 * Yig'iladigan JSON daraxti.
 *
 * Nega `<pre>{JSON.stringify(x, null, 2)}</pre>` yetmaydi: payload yoki
 * natija chuqur bo'lsa, tekis matn o'qib bo'lmaydigan bo'ladi. Daraxt
 * ko'rinishida foydalanuvchi faqat kerakli shoxni ochadi.
 *
 * Katta massivlar (>50 element) sukut bo'yicha YIG'ILGAN holda ochiladi —
 * aks holda 10 000 elementli ro'yxat brauzerni qotirib qo'yadi.
 */

/** Qiymat turi — rang va ko'rinish shunga qarab tanlanadi. */
type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue }

const TYPE_CLASS = {
  string: 'text-success',
  number: 'text-pending',
  boolean: 'text-accent-light',
  null: 'text-fg-faint italic',
} as const

/** Shu chuqurlikkacha avtomatik ochiladi. */
const DEFAULT_OPEN_DEPTH = 2
/** Shundan katta ro'yxat yig'ilgan holda boshlanadi. */
const LARGE_COLLECTION = 50

export function JsonViewer({
  data,
  rootLabel,
  className,
  maxHeight = 420,
  copyable = true,
}: {
  data: unknown
  /** Ildiz tugun yorlig'i (`payload`, `result`). */
  rootLabel?: string
  className?: string
  maxHeight?: number
  copyable?: boolean
}) {
  if (data === undefined) {
    return (
      <div className={cn('rounded-lg border border-line-inner bg-canvas-deep px-3.5 py-3', className)}>
        <span className="font-mono text-xs text-fg-faint">—</span>
      </div>
    )
  }

  const raw = JSON.stringify(data, null, 2)

  return (
    <div
      className={cn(
        'relative overflow-auto rounded-lg border border-line-inner bg-canvas-deep px-3.5 py-3 font-mono text-xs leading-[1.75]',
        className,
      )}
      style={{ maxHeight }}
    >
      {copyable ? (
        <div className="absolute right-2 top-2 z-10">
          <CopyButton value={raw} label={rootLabel ?? 'JSON'} size="md" />
        </div>
      ) : null}
      <Node value={data as JsonValue} name={rootLabel} depth={0} isLast />
    </div>
  )
}

function Node({
  value,
  name,
  depth,
  isLast,
}: {
  value: JsonValue
  name?: string
  depth: number
  isLast: boolean
}) {
  const isArray = Array.isArray(value)
  const isObject = value !== null && typeof value === 'object' && !isArray
  const entries: [string, JsonValue][] = isArray
    ? (value as JsonValue[]).map((v, i) => [String(i), v])
    : isObject
      ? Object.entries(value as Record<string, JsonValue>)
      : []

  const big = entries.length > LARGE_COLLECTION
  const [open, setOpen] = useState(depth < DEFAULT_OPEN_DEPTH && !big)

  // --- Oddiy qiymat (barg) ---
  if (!isArray && !isObject) {
    // `isArray`/`isObject` tekshiruvidan keyin TS turni o'zi toraytirmaydi
    const leaf = value as string | number | boolean | null
    return (
      <div style={{ paddingLeft: depth * 14 }}>
        {name !== undefined ? <span className="text-fg-dim">{name}: </span> : null}
        <Leaf value={leaf} />
        {!isLast ? <span className="text-fg-ghost">,</span> : null}
      </div>
    )
  }

  const open_br = isArray ? '[' : '{'
  const close_br = isArray ? ']' : '}'
  const count = entries.length

  return (
    <div style={{ paddingLeft: depth * 14 }}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="group inline-flex items-center gap-1 text-left hover:text-fg"
        aria-expanded={open}
      >
        <span
          className={cn(
            'inline-block w-2.5 shrink-0 text-fg-faint transition-transform',
            open && 'rotate-90',
          )}
          aria-hidden
        >
          ›
        </span>
        {name !== undefined ? <span className="text-fg-dim">{name}: </span> : null}
        <span className="text-fg-muted">{open_br}</span>
        {!open ? (
          <>
            <span className="px-1 text-fg-faint">
              {count} {isArray ? (count === 1 ? 'item' : 'items') : count === 1 ? 'key' : 'keys'}
            </span>
            <span className="text-fg-muted">{close_br}</span>
            {!isLast ? <span className="text-fg-ghost">,</span> : null}
          </>
        ) : null}
      </button>

      {open ? (
        <>
          {entries.map(([key, child], index) => (
            <Node
              key={key}
              name={isArray ? undefined : key}
              value={child}
              depth={depth + 1}
              isLast={index === entries.length - 1}
            />
          ))}
          <div style={{ paddingLeft: 0 }}>
            <span className="text-fg-muted">{close_br}</span>
            {!isLast ? <span className="text-fg-ghost">,</span> : null}
          </div>
        </>
      ) : null}
    </div>
  )
}

function Leaf({ value }: { value: string | number | boolean | null }) {
  if (value === null) return <span className={TYPE_CLASS.null}>null</span>
  if (typeof value === 'string') return <span className={TYPE_CLASS.string}>&quot;{value}&quot;</span>
  if (typeof value === 'number') return <span className={TYPE_CLASS.number}>{value}</span>
  return <span className={TYPE_CLASS.boolean}>{String(value)}</span>
}
