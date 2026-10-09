'use client'

import { useEffect, useState } from 'react'

import { cn } from '@/lib/utils/cn'
import { formatTimestamp, relativeTime } from '@/lib/utils/time'

/**
 * Nisbiy vaqt (`2m ago`), hover'da to'liq vaqt belgisi.
 *
 * HYDRATION: server "2m ago" ni render qilsa, mijoz esa (bir necha soniya
 * keyin) "3m ago" ni render qilishi mumkin — bu hydration xatosi beradi.
 * Shuning uchun birinchi render SERVER va MIJOZDA bir xil bo'ladi
 * (to'liq sanani ko'rsatmaydi, balki `suppressHydrationWarning` bilan
 * nisbiy vaqtni beradi) va keyin har 30 soniyada yangilanadi.
 */
export interface RelativeTimeProps {
  value: string | null | undefined
  className?: string
  /** Yangilanish davri (ms). `0` — yangilanmaydi. */
  refreshMs?: number
}

export function RelativeTime({ value, className, refreshMs = 30_000 }: RelativeTimeProps) {
  const [, setTick] = useState(0)

  useEffect(() => {
    if (refreshMs <= 0) return
    const timer = setInterval(() => setTick((t) => t + 1), refreshMs)
    return () => clearInterval(timer)
  }, [refreshMs])

  if (!value) return <span className={cn('text-fg-faint', className)}>—</span>

  return (
    <span className={className} title={formatTimestamp(value)} suppressHydrationWarning>
      {relativeTime(value)}
    </span>
  )
}
