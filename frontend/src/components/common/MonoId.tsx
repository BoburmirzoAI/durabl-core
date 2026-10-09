import { cn } from '@/lib/utils/cn'

import { CopyButton } from './CopyButton'

/**
 * Monospace identifikator + nusxalash tugmasi.
 *
 * Dizaynda jadvallardagi job ID aynan shunday: `JetBrains Mono 12px`,
 * `#E4E4E7` rang, uzun bo'lsa `…` bilan kesiladi, yonida copy ikonkasi.
 */
export interface MonoIdProps {
  value: string
  /** Ko'rinadigan qisqa shakl (berilmasa to'liq qiymat). */
  display?: string
  copyable?: boolean
  copyLabel?: string
  className?: string
}

export function MonoId({
  value,
  display,
  copyable = true,
  copyLabel = 'Job ID',
  className,
}: MonoIdProps) {
  return (
    <span className={cn('flex min-w-0 items-center gap-[7px]', className)}>
      <span className="truncate font-mono text-sm text-fg-bright" title={value}>
        {display ?? value}
      </span>
      {copyable ? <CopyButton value={value} label={copyLabel} silent /> : null}
    </span>
  )
}
