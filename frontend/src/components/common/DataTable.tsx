'use client'

import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { Checkbox } from '@/components/ui/checkbox'
import { cn } from '@/lib/utils/cn'
import { isTypingTarget } from '@/lib/constants/shortcuts'
import { useSelectionStore } from '@/stores/selectionStore'
import type { SortOrder } from '@/types'

/**
 * Bo'sh tanlov uchun BARQAROR havola.
 *
 * Zustand selektor natijasini `Object.is` bilan solishtiradi. `?? []` yozilsa
 * har chaqiriqda YANGI massiv qaytadi — store o'zgarmagan bo'lsa ham "o'zgardi"
 * deb hisoblanadi va cheksiz qayta render boshlanadi
 * ("Maximum update depth exceeded").
 */
const EMPTY_IDS: string[] = []


/**
 * Qayta ishlatiladigan, klaviatura bilan boshqariladigan jadval.
 *
 * Dizaynda jadvallar CSS Grid bilan qurilgan (`grid-template-columns`),
 * `<table>` emas — shuning uchun bu komponent ham grid ishlatadi, lekin
 * ARIA rollari (`table`/`row`/`cell`) bilan skrinrider uchun to'g'ri
 * qoladi.
 *
 * Klaviatura: ↑/↓ fokusni ko'chiradi, Enter ochadi, Space tanlaydi,
 * Esc tanlovni tozalaydi — dizayndagi fokus halqasi shundan.
 */

export interface Column<T> {
  key: string
  header: string
  /** Yacheyka ko'rinishi. */
  cell: (row: T) => React.ReactNode
  /** Ustun bo'yicha tartiblash mumkinmi. */
  sortable?: boolean
  /** Matnni o'ngga tekislash (raqamlar uchun). */
  align?: 'left' | 'right' | 'center'
  /** Sarlavhani yashirish (amallar ustuni). */
  srOnlyHeader?: boolean
}

export interface DataTableProps<T> {
  /** Tanlov holati uchun noyob nom (`jobs`, `dlq`). */
  scope: string
  rows: T[]
  columns: Column<T>[]
  /** CSS `grid-template-columns` qiymati — dizayndan aynan olinadi. */
  gridTemplate: string
  rowId: (row: T) => string
  onRowClick?: (row: T) => void
  /**
   * Qator ichida ochiladigan ko'rinish.
   *
   * Berilsa, har bir qatorga kengaytirish tugmasi qo'shiladi va bosilganda
   * shu funksiya qaytargan JSX qator OSTIDA ochiladi. Sahifadan chiqmasdan
   * "tez ko'z tashlash" uchun — detal sahifasiga o'tish shart emas.
   */
  renderExpanded?: (row: T) => React.ReactNode
  /** Ko'p tanlash yoqilganmi. */
  selectable?: boolean
  sort?: { field: string; order: SortOrder }
  onSortChange?: (field: string) => void
  /** Jadval ustidagi qatlam (bulk amallar paneli). */
  overlay?: React.ReactNode
  emptyState?: React.ReactNode
  loading?: boolean
  loadingState?: React.ReactNode
  className?: string
  'aria-label': string
}

export function DataTable<T>({
  scope,
  rows,
  columns,
  gridTemplate,
  rowId,
  onRowClick,
  renderExpanded,
  selectable = false,
  sort,
  onSortChange,
  overlay,
  emptyState,
  loading = false,
  loadingState,
  className,
  'aria-label': ariaLabel,
}: DataTableProps<T>) {
  const containerRef = useRef<HTMLDivElement>(null)
  const selected = useSelectionStore((s) => s.selected[scope] ?? EMPTY_IDS)
  const focusIndex = useSelectionStore((s) => s.focusIndex[scope] ?? -1)
  const toggle = useSelectionStore((s) => s.toggle)
  const setMany = useSelectionStore((s) => s.setMany)
  const clear = useSelectionStore((s) => s.clear)
  const setFocus = useSelectionStore((s) => s.setFocus)
  const moveFocus = useSelectionStore((s) => s.moveFocus)

  const ids = useMemo(() => rows.map(rowId), [rows, rowId])

  //: Ochilgan qatorlar — bir vaqtda bir nechtasi ochiq turishi mumkin
  const [expanded, setExpanded] = useState<string[]>([])
  const toggleExpanded = useCallback((id: string) => {
    setExpanded((current) =>
      current.includes(id) ? current.filter((v) => v !== id) : [...current, id],
    )
  }, [])
  const allSelected = ids.length > 0 && ids.every((id) => selected.includes(id))
  const someSelected = !allSelected && ids.some((id) => selected.includes(id))

  const toggleAll = useCallback(() => {
    setMany(scope, allSelected ? [] : ids)
  }, [allSelected, ids, scope, setMany])

  // Qatorlar o'zgarsa (filtr/sahifa) fokus chegaradan chiqib ketmasligi kerak
  useEffect(() => {
    if (focusIndex >= rows.length) setFocus(scope, rows.length - 1)
  }, [rows.length, focusIndex, scope, setFocus])

  /** Fokusdagi qatorni ko'rinish maydoniga suradi. */
  const scrollIntoView = useCallback((index: number) => {
    const node = containerRef.current?.querySelector<HTMLElement>(`[data-row-index="${index}"]`)
    node?.scrollIntoView({ block: 'nearest' })
  }, [])

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent): void => {
      if (isTypingTarget(event.target)) return
      if (rows.length === 0) return

      // Vim uslubidagi `j`/`k`/`x` — faqat matn yozilmayotganda
      const key = event.key
      if ((key === 'j' || key === 'k' || key === 'x') && !isTypingTarget(event.target)) {
        event.preventDefault()
        if (key === 'j') {
          scrollIntoView(moveFocus(scope, focusIndex < 0 ? 0 : 1, rows.length))
        } else if (key === 'k') {
          scrollIntoView(moveFocus(scope, -1, rows.length))
        } else if (selectable && focusIndex >= 0) {
          const id = ids[focusIndex]
          if (id) toggle(scope, id)
        }
        return
      }

      if (event.key === 'ArrowDown') {
        event.preventDefault()
        scrollIntoView(moveFocus(scope, focusIndex < 0 ? 0 : 1, rows.length))
      } else if (event.key === 'ArrowUp') {
        event.preventDefault()
        scrollIntoView(moveFocus(scope, -1, rows.length))
      } else if (event.key === 'Enter' && focusIndex >= 0) {
        const row = rows[focusIndex]
        if (row && onRowClick) {
          event.preventDefault()
          onRowClick(row)
        }
      } else if (event.key === ' ' && focusIndex >= 0 && selectable) {
        const id = ids[focusIndex]
        if (id) {
          event.preventDefault()
          toggle(scope, id)
        }
      } else if (event.key === 'Escape') {
        if (selected.length > 0) {
          event.preventDefault()
          clear(scope)
        }
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [
    rows,
    ids,
    focusIndex,
    scope,
    selectable,
    selected.length,
    moveFocus,
    toggle,
    clear,
    onRowClick,
    scrollIntoView,
  ])

  const template = selectable ? `36px ${gridTemplate}` : gridTemplate
  //: Kengaytirish tugmasi uchun qo'shimcha ustun
  const fullTemplate = renderExpanded ? `${template} 34px` : template

  return (
    <div
      ref={containerRef}
      role="table"
      aria-label={ariaLabel}
      aria-rowcount={rows.length}
      className={cn('relative overflow-hidden rounded-2xl border border-line bg-surface', className)}
    >
      {overlay}

      {/* Sarlavha qatori */}
      <div role="row" className="table-head grid items-center" style={{ gridTemplateColumns: template }}>
        {selectable ? (
          <span role="columnheader" className="flex items-center">
            <Checkbox
              checked={allSelected}
              indeterminate={someSelected}
              onToggle={toggleAll}
              aria-label={allSelected ? 'Deselect all rows' : 'Select all rows'}
            />
          </span>
        ) : null}
        {columns.map((column) => {
          const isSorted = sort?.field === column.key
          return (
            <span
              key={column.key}
              role="columnheader"
              aria-sort={isSorted ? (sort.order === 'asc' ? 'ascending' : 'descending') : undefined}
              className={cn(
                column.align === 'right' && 'text-right',
                column.align === 'center' && 'text-center',
              )}
            >
              {column.srOnlyHeader ? (
                <span className="sr-only">{column.header}</span>
              ) : column.sortable && onSortChange ? (
                <button
                  type="button"
                  onClick={() => onSortChange(column.key)}
                  className={cn(
                    'inline-flex items-center gap-1 uppercase tracking-[.06em] transition-colors hover:text-fg-muted',
                    isSorted && 'text-fg-muted',
                  )}
                >
                  {column.header}
                  {isSorted ? (
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" aria-hidden>
                      <path d={sort.order === 'asc' ? 'M6 15l6-6 6 6' : 'M6 9l6 6 6-6'} />
                    </svg>
                  ) : null}
                </button>
              ) : (
                column.header
              )}
            </span>
          )
        })}
        {renderExpanded ? <span role="columnheader" className="sr-only">Expand</span> : null}
      </div>

      {/* Tana */}
      {loading && rows.length === 0 ? (
        (loadingState ?? null)
      ) : rows.length === 0 ? (
        (emptyState ?? null)
      ) : (
        rows.map((row, index) => {
          const id = rowId(row)
          const isSelected = selected.includes(id)
          const isFocused = index === focusIndex
          const isExpanded = expanded.includes(id)
          return (
            <Fragment key={id}>
            <div
              role="row"
              data-row-index={index}
              aria-selected={isSelected}
              aria-rowindex={index + 1}
              tabIndex={-1}
              onClick={() => {
                setFocus(scope, index)
                onRowClick?.(row)
              }}
              className={cn(
                'grid h-10 items-center border-b border-line-subtle px-3.5 transition-colors',
                onRowClick && 'cursor-pointer',
                isSelected ? 'bg-accent/[0.06]' : 'hover:bg-surface-3',
                isFocused && 'shadow-focus-row',
              )}
              style={{ gridTemplateColumns: fullTemplate }}
            >
              {selectable ? (
                <span role="cell" className="flex items-center">
                  <Checkbox
                    checked={isSelected}
                    onToggle={() => toggle(scope, id)}
                    aria-label={`Select row ${id}`}
                  />
                </span>
              ) : null}
              {columns.map((column) => (
                <span
                  key={column.key}
                  role="cell"
                  className={cn(
                    'min-w-0',
                    column.align === 'right' && 'text-right',
                    column.align === 'center' && 'text-center',
                  )}
                >
                  {column.cell(row)}
                </span>
              ))}

              {renderExpanded ? (
                <span role="cell" className="flex justify-end">
                  <button
                    type="button"
                    aria-expanded={isExpanded}
                    aria-label={isExpanded ? `Collapse ${id}` : `Expand ${id}`}
                    onClick={(event) => {
                      // Qator bosilishi (detal sahifasiga o'tish) ishlamasin
                      event.stopPropagation()
                      toggleExpanded(id)
                    }}
                    className="inline-flex h-[22px] w-[22px] items-center justify-center rounded text-fg-faint transition-colors hover:bg-line hover:text-fg"
                  >
                    <svg
                      width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"
                      className={cn('transition-transform', isExpanded && 'rotate-90')}
                      aria-hidden
                    >
                      <path d="M9 6l6 6-6 6" />
                    </svg>
                  </button>
                </span>
              ) : null}
            </div>

            {isExpanded ? (
              <div className="animate-slide-down border-b border-line-subtle bg-canvas-sunken px-4 py-3.5">
                {renderExpanded?.(row)}
              </div>
            ) : null}
            </Fragment>
          )
        })
      )}
    </div>
  )
}
