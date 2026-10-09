'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

import { cn } from '@/lib/utils/cn'
import { useToast } from './ToastProvider'

/**
 * Nusxalash tugmasi — dizaynda jadval qatorlaridagi ID yonida.
 * Bosilgandan keyin 1.5s davomida yashil ✓ ko'rinadi.
 */
export interface CopyButtonProps {
  value: string
  /** Toast xabari uchun nom (`Job ID`). */
  label?: string
  /** Toast ko'rsatilmasin (jadvalda ko'p qator bo'lsa shovqin bo'ladi). */
  silent?: boolean
  size?: 'sm' | 'md'
  className?: string
}

export function CopyButton({
  value,
  label = 'ID',
  silent = false,
  size = 'sm',
  className,
}: CopyButtonProps) {
  const [copied, setCopied] = useState(false)
  const { toast } = useToast()
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current)
  }, [])

  const onCopy = useCallback(
    async (event: React.MouseEvent) => {
      // Jadval qatorida bosilsa detal sahifasi ochilmasligi kerak
      event.stopPropagation()
      try {
        await navigator.clipboard.writeText(value)
        setCopied(true)
        if (!silent) toast({ title: `${label} copied`, description: value })
        if (timer.current) clearTimeout(timer.current)
        timer.current = setTimeout(() => setCopied(false), 1_500)
      } catch {
        // Clipboard API HTTPS yoki localhost'da ishlaydi; aks holda xabar beramiz
        toast({ title: 'Copy failed', description: 'Clipboard unavailable', variant: 'destructive' })
      }
    },
    [value, label, silent, toast],
  )

  const dimension = size === 'md' ? 'h-7 w-7' : 'h-[18px] w-[18px]'
  const icon = size === 'md' ? 14 : 12

  return (
    <button
      type="button"
      title={`Copy ${label}`}
      aria-label={`Copy ${label}`}
      onClick={onCopy}
      className={cn(
        'inline-flex shrink-0 items-center justify-center rounded-sm transition-colors',
        dimension,
        copied ? 'text-success' : 'text-fg-ghost hover:bg-line hover:text-fg-muted',
        size === 'md' && 'rounded-md border border-line bg-surface hover:border-line-hover',
        className,
      )}
    >
      {copied ? (
        <svg width={icon} height={icon} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <path d="M5 12l5 5 9-11" />
        </svg>
      ) : (
        <svg width={icon} height={icon} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
          <rect x="9" y="9" width="11" height="11" rx="2" />
          <path d="M5 15V5a2 2 0 0 1 2-2h10" />
        </svg>
      )}
    </button>
  )
}
