import { cn } from '@/lib/utils/cn'
import { pulseStyle } from '@/lib/utils/status'

/**
 * Holat nuqtasi — dizaynda 6px dumaloq, jonli holatda `dpulse`
 * animatsiyasi bilan.
 */
export interface StatusDotProps {
  /** Rang klassi (`bg-success`). */
  className: string
  /** Pulsatsiya rangi tokeni (`success`) — `live` bo'lsa kerak. */
  pulseToken?: string
  live?: boolean
  size?: 'xs' | 'sm' | 'md'
}

const SIZES = { xs: 'h-[5px] w-[5px]', sm: 'h-1.5 w-1.5', md: 'h-2 w-2' } as const

export function StatusDot({ className, pulseToken, live = false, size = 'sm' }: StatusDotProps) {
  return (
    <span
      aria-hidden
      style={live && pulseToken ? pulseStyle(pulseToken) : undefined}
      className={cn(
        'shrink-0 rounded-full',
        SIZES[size],
        className,
        live && 'animate-pulse-dot',
      )}
    />
  )
}
