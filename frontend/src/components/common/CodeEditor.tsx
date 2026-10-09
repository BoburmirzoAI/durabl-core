'use client'

import { useId, useMemo, useRef, useState } from 'react'

import { Badge } from '@/components/ui/badge'
import { CopyButton } from '@/components/common/CopyButton'
import { StatusDot } from '@/components/common/StatusDot'
import { cn } from '@/lib/utils/cn'
import { runtimeStyle } from '@/lib/utils/status'
import type { Runtime } from '@/types'

/**
 * Tahrirlanadigan kod maydoni — qator raqamlari bilan.
 *
 * ## Nega `<textarea>` ustiga qurilgan
 *
 * To'liq muharrir (CodeMirror/Monaco) 300KB+ olib keladi va bu yerda kerak
 * emas: foydalanuvchi 20–50 qatorlik funksiya yozadi. `<textarea>` esa
 * klaviatura, nusxalash, bekor qilish (⌘Z) va ekran o'quvchilarni BEPUL
 * beradi — ularni qo'lda qayta yozish xato manbai bo'lardi.
 *
 * Qator raqamlari alohida ustunda, `scrollTop` sinxronlanadi.
 *
 * ## Sintaksis bo'yash
 *
 * Tahrirlash rejimida bo'yash YO'Q: `<textarea>` ustiga rangli qatlam
 * qo'yish kursor joylashuvini buzadi (har bir brauzerda boshqacha).
 * Faqat o'qish rejimida `CodeBlock` ishlatiladi — u to'liq bo'yaydi.
 */
export function CodeEditor({
  value,
  onChange,
  runtime,
  label = 'Code',
  placeholder,
  minRows = 12,
  maxHeight = 420,
  error,
  className,
}: {
  value: string
  onChange: (next: string) => void
  runtime: Runtime
  label?: string
  placeholder?: string
  minRows?: number
  maxHeight?: number
  /** Validatsiya xatosi — maydon ostida qizil matn. */
  error?: string | null
  className?: string
}) {
  const id = useId()
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const gutterRef = useRef<HTMLDivElement>(null)
  const [focused, setFocused] = useState(false)

  const lines = useMemo(() => value.split('\n').length, [value])
  const style = runtimeStyle(runtime)

  /** Raqamlar ustunini matn bilan birga siljitadi. */
  const syncScroll = (): void => {
    if (gutterRef.current && textareaRef.current) {
      gutterRef.current.scrollTop = textareaRef.current.scrollTop
    }
  }

  /**
   * Tab tugmasi fokusni ko'chirmasdan 4 bo'shliq qo'shsin.
   *
   * Esc bosilsa fokus chiqadi — aks holda klaviatura bilan ishlaydigan
   * foydalanuvchi maydondan chiqa olmay qoladi (a11y tuzog'i).
   */
  const onKeyDown = (event: React.KeyboardEvent<HTMLTextAreaElement>): void => {
    if (event.key === 'Escape') {
      textareaRef.current?.blur()
      return
    }
    if (event.key !== 'Tab' || event.shiftKey) return
    event.preventDefault()
    const el = event.currentTarget
    const start = el.selectionStart
    const end = el.selectionEnd
    const next = `${value.slice(0, start)}    ${value.slice(end)}`
    onChange(next)
    requestAnimationFrame(() => {
      el.selectionStart = el.selectionEnd = start + 4
    })
  }

  return (
    <div className={className}>
      <div
        className={cn(
          'overflow-hidden rounded-xl border bg-surface transition-colors',
          error ? 'border-failed/40' : focused ? 'border-accent' : 'border-line',
        )}
      >
        {/* Sarlavha */}
        <div className="flex items-center gap-2.5 border-b border-line-inner px-3.5 py-2.5">
          <label htmlFor={id} className="text-sm font-medium text-fg-soft">
            {label}
          </label>
          <Badge className={cn(style.bg, style.text)}>
            <StatusDot className={style.dot} size="xs" />
            {runtime === 'python' ? 'Python 3.12' : 'Node 22'}
          </Badge>
          <span className="tabular ml-auto font-mono text-xs text-fg-faint">
            {lines} {lines === 1 ? 'line' : 'lines'}
          </span>
          <CopyButton value={value} label="Code" size="md" />
        </div>

        {/* Raqamlar + maydon */}
        <div className="flex bg-canvas-deep" style={{ maxHeight }}>
          <div
            ref={gutterRef}
            aria-hidden
            className="w-[46px] shrink-0 select-none overflow-hidden py-2.5 pr-3 text-right font-mono text-sm leading-[1.7] text-fg-ghost"
          >
            {Array.from({ length: Math.max(lines, minRows) }, (_, i) => (
              <div key={i}>{i + 1}</div>
            ))}
          </div>

          <textarea
            id={id}
            ref={textareaRef}
            value={value}
            onChange={(event) => onChange(event.target.value)}
            onScroll={syncScroll}
            onKeyDown={onKeyDown}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            placeholder={placeholder}
            spellCheck={false}
            autoCapitalize="off"
            autoCorrect="off"
            rows={minRows}
            aria-invalid={Boolean(error)}
            className={cn(
              'min-w-0 flex-1 resize-none border-none bg-transparent py-2.5 pr-4',
              'font-mono text-sm leading-[1.7] text-fg-soft outline-none',
              'placeholder:text-fg-ghost',
            )}
            style={{ maxHeight }}
          />
        </div>
      </div>

      {error ? <p className="mt-1.5 text-xs text-failed">{error}</p> : null}
      <p className="mt-1.5 text-xs text-fg-faint">
        <kbd className="kbd">Tab</kbd> inserts 4 spaces · <kbd className="kbd">Esc</kbd> leaves the
        field
      </p>
    </div>
  )
}
