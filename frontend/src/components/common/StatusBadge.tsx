import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils/cn'
import type { StatusStyle } from '@/lib/utils/status'

import { StatusDot } from './StatusDot'

/**
 * Holat nishoni — nuqta + yorliq.
 *
 * MUHIM (qulaylik): ma'no FAQAT rangga tayanmaydi — har doim matnli
 * yorliq bor, shuning uchun rang ko'rligi muammo tug'dirmaydi.
 */
export interface StatusBadgeProps {
  style: StatusStyle
  size?: 'sm' | 'md' | 'lg'
  /** Nuqtani yashirish (runtime nishonlari uchun). */
  hideDot?: boolean
  className?: string
}

export function StatusBadge({ style, size = 'md', hideDot = false, className }: StatusBadgeProps) {
  return (
    <Badge
      size={size}
      className={cn(
        style.bg,
        style.text,
        size === 'lg' && cn('border font-semibold', style.border),
        className,
      )}
    >
      {hideDot ? null : (
        <StatusDot
          className={style.dot}
          pulseToken={style.pulseToken}
          live={style.live}
          size={size === 'lg' ? 'md' : size === 'sm' ? 'xs' : 'sm'}
        />
      )}
      {style.label}
    </Badge>
  )
}
