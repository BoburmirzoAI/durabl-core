import { cn } from '@/lib/utils/cn'

/**
 * Navigatsiya ikonkasi — dizayndagi XOM SVG `path` lari bilan.
 *
 * `lucide-react` emas: dizaynda ikonkalar maxsus chizilgan (masalan
 * Dashboard — to'rt blokli grid, Webhooks — chaqmoq), lucide
 * ekvivalentlari boshqa proporsiyada.
 */
export function NavIcon({
  path,
  size = 15,
  className,
  strokeWidth = 1.8,
}: {
  path: string
  size?: number
  className?: string
  strokeWidth?: number
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={cn('shrink-0', className)}
      aria-hidden
    >
      <path d={path} />
    </svg>
  )
}
