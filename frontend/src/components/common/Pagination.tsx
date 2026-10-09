'use client'

import { SingleSelect } from '@/components/ui/filter-select'
import { cn } from '@/lib/utils/cn'
import { formatNumber } from '@/lib/utils/format'
import type { PaginationMeta } from '@/types'

/**
 * Sahifalash — dizayndagi ko'rinish:
 * chapda "Showing 1–25 of 12,847", o'ngda "Rows" tanlagichi va
 * o'q tugmalari + "Page 1 of 857".
 */
export interface PaginationProps {
  pagination: PaginationMeta
  onPageChange: (page: number) => void
  onPageSizeChange?: (size: number) => void
  className?: string
}

const PAGE_SIZES = [
  { value: '25', label: '25' },
  { value: '50', label: '50' },
  { value: '100', label: '100' },
] as const

export function Pagination({
  pagination,
  onPageChange,
  onPageSizeChange,
  className,
}: PaginationProps) {
  const { page, page_size, total, total_pages, has_next, has_prev } = pagination
  const from = total === 0 ? 0 : (page - 1) * page_size + 1
  const to = Math.min(page * page_size, total)

  const navButton = (
    glyph: string,
    label: string,
    target: number,
    enabled: boolean,
  ): React.ReactNode => (
    <button
      type="button"
      aria-label={label}
      disabled={!enabled}
      onClick={() => onPageChange(target)}
      className={cn(
        'flex h-7 w-7 items-center justify-center rounded-md border border-line bg-surface font-mono text-base transition-colors',
        enabled ? 'text-fg-soft hover:border-line-hover hover:text-fg' : 'cursor-not-allowed text-fg-ghost',
      )}
    >
      {glyph}
    </button>
  )

  return (
    <div className={cn('flex flex-wrap items-center gap-4 pb-1.5', className)}>
      <span className="text-sm text-fg-dim">
        Showing{' '}
        <span className="tabular font-mono text-fg-muted">
          {formatNumber(from)}–{formatNumber(to)}
        </span>{' '}
        of <span className="tabular font-mono text-fg-muted">{formatNumber(total)}</span>
      </span>

      {onPageSizeChange ? (
        <div className="ml-auto flex items-center gap-2">
          <span className="text-sm text-fg-dim">Rows</span>
          <SingleSelect
            mono
            openUpward
            options={PAGE_SIZES}
            value={String(page_size)}
            onChange={(value) => onPageSizeChange(Number(value))}
          />
        </div>
      ) : null}

      <div className={cn('flex items-center gap-1', onPageSizeChange ? '' : 'ml-auto')}>
        {navButton('«', 'First page', 1, has_prev)}
        {navButton('‹', 'Previous page', page - 1, has_prev)}
        <span className="px-2 text-sm text-fg-muted">
          Page <span className="tabular font-mono text-fg">{page}</span> of{' '}
          <span className="tabular font-mono text-fg-muted">{formatNumber(total_pages)}</span>
        </span>
        {navButton('›', 'Next page', page + 1, has_next)}
        {navButton('»', 'Last page', total_pages, has_next)}
      </div>
    </div>
  )
}
