'use client'

import { useEffect, useRef, useState } from 'react'

import { cn } from '@/lib/utils/cn'

/**
 * Filtr dropdown'i — dizayndagi ko'rinish:
 * tugmada `prefix` kulrang + tanlangan qiymat, ochilgan menyuda
 * belgi (✓) va ixtiyoriy rang nuqtasi.
 *
 * Radix `DropdownMenu` o'rniga qo'lda: bizga ko'p tanlovli holat va
 * nuqta ko'rsatkichlari kerak, Radix `CheckboxItem` esa boshqa ko'rinish beradi.
 */
export interface FilterOption<T extends string> {
  value: T
  label: string
  /** Yonidagi rang nuqtasi klassi (holat filtrlari uchun). */
  dotClassName?: string
}

export interface FilterSelectProps<T extends string> {
  /** Tugmadagi kulrang prefiks (`Status:`). */
  prefix: string
  options: readonly FilterOption<T>[]
  /** Tanlangan qiymatlar (ko'p tanlovli). */
  value: T[]
  onToggle: (value: T) => void
  onClear?: () => void
  /** Hech narsa tanlanmaganda ko'rsatiladigan matn. */
  emptyLabel?: string
  className?: string
}

export function FilterSelect<T extends string>({
  prefix,
  options,
  value,
  onToggle,
  onClear,
  emptyLabel = 'All',
  className,
}: FilterSelectProps<T>) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Tashqariga bosilganda yopiladi
  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent): void => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const label =
    value.length === 0
      ? emptyLabel
      : value.length === 1
        ? (options.find((o) => o.value === value[0])?.label ?? String(value[0]))
        : `${value.length} selected`

  const active = value.length > 0

  return (
    <div ref={ref} className={cn('relative', className)}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          'flex items-center gap-2 whitespace-nowrap rounded-lg border bg-surface px-[11px] py-[7px] text-sm font-medium transition-colors',
          active ? 'border-accent/40 text-fg' : 'border-line text-fg-soft hover:border-line-hover',
        )}
      >
        <span className="font-normal text-fg-faint">{prefix}</span>
        {label}
        <svg
          width="13"
          height="13"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          className="text-fg-faint"
          aria-hidden
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open ? (
        <div
          role="listbox"
          className="absolute left-0 top-[calc(100%+6px)] z-20 min-w-[180px] animate-menu-in rounded-[9px] border border-line-strong bg-surface-2 p-[5px] shadow-menu"
        >
          {options.map((option) => {
            const selected = value.includes(option.value)
            return (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={selected}
                onClick={() => onToggle(option.value)}
                className="flex w-full items-center gap-2 rounded px-2.5 py-1.5 text-left text-sm text-fg-soft transition-colors hover:bg-surface-5"
              >
                {option.dotClassName ? (
                  <span className={cn('h-[7px] w-[7px] shrink-0 rounded-full', option.dotClassName)} />
                ) : null}
                <span className="flex-1">{option.label}</span>
                {selected ? (
                  <svg
                    width="13"
                    height="13"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    className="shrink-0 text-accent"
                    aria-hidden
                  >
                    <path d="M5 12l5 5 9-11" />
                  </svg>
                ) : null}
              </button>
            )
          })}
          {onClear && value.length > 0 ? (
            <>
              <div className="-mx-[5px] my-[5px] h-px bg-line-inner" />
              <button
                type="button"
                onClick={() => {
                  onClear()
                  setOpen(false)
                }}
                className="w-full rounded px-2.5 py-1.5 text-left text-sm text-fg-dim transition-colors hover:bg-surface-5 hover:text-fg"
              >
                Clear
              </button>
            </>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

/**
 * Bitta qiymat tanlanadigan dropdown (vaqt oralig'i, sahifa hajmi).
 */
export interface SingleSelectProps<T extends string> {
  prefix?: string
  options: readonly FilterOption<T>[]
  value: T
  onChange: (value: T) => void
  className?: string
  /** Menyu yuqoriga ochiladi (sahifa pastidagi "Rows" tanlagichi). */
  openUpward?: boolean
  mono?: boolean
}

export function SingleSelect<T extends string>({
  prefix,
  options,
  value,
  onChange,
  className,
  openUpward = false,
  mono = false,
}: SingleSelectProps<T>) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onPointerDown = (event: MouseEvent): void => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false)
    }
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const current = options.find((o) => o.value === value)

  return (
    <div ref={ref} className={cn('relative', className)}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          'flex items-center gap-[7px] rounded-md border border-line bg-surface px-[9px] py-[5px] text-sm text-fg-soft transition-colors hover:border-line-hover',
          mono && 'font-mono',
        )}
      >
        {prefix ? <span className="font-sans font-normal text-fg-faint">{prefix}</span> : null}
        {current?.label ?? value}
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          className="text-fg-faint"
          aria-hidden
        >
          <path d="M6 9l6 6 6-6" />
        </svg>
      </button>

      {open ? (
        <div
          role="listbox"
          className={cn(
            'absolute left-0 z-20 min-w-[88px] animate-menu-in rounded-[9px] border border-line-strong bg-surface-2 p-[5px] shadow-menu',
            openUpward ? 'bottom-[calc(100%+6px)]' : 'top-[calc(100%+6px)]',
          )}
        >
          {options.map((option) => (
            <button
              key={option.value}
              type="button"
              role="option"
              aria-selected={option.value === value}
              onClick={() => {
                onChange(option.value)
                setOpen(false)
              }}
              className={cn(
                'w-full rounded px-2.5 py-1.5 text-left text-sm transition-colors hover:bg-surface-5',
                mono && 'font-mono',
                option.value === value ? 'text-fg' : 'text-fg-muted',
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  )
}
