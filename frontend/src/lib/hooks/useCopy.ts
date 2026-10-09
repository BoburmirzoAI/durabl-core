'use client'

import { useCallback } from 'react'

import { useToast } from '@/components/common/ToastProvider'

/**
 * Buferga nusxalash + foydalanuvchiga xabar.
 *
 * Nega alohida hook: `navigator.clipboard` ni to'g'ridan-to'g'ri chaqirish
 * JIM ishlaydi — foydalanuvchi tugma bosganini bilmaydi. Bundan tashqari
 * Clipboard API faqat HTTPS yoki `localhost` da ishlaydi va boshqa joyda
 * `throw` qiladi, ya'ni xatoni ushlamasa tugma umuman "o'lik" ko'rinadi.
 */
export function useCopy(): (value: string, label?: string) => Promise<boolean> {
  const { toast } = useToast()

  return useCallback(
    async (value: string, label = 'Copied') => {
      try {
        await navigator.clipboard.writeText(value)
        toast({
          title: label,
          // Uzun qiymat toast'ni cho'zmasligi uchun qisqartiramiz
          description: value.length > 60 ? `${value.slice(0, 60)}…` : value,
          variant: 'success',
        })
        return true
      } catch {
        toast({
          title: 'Copy failed',
          description: 'Clipboard is unavailable in this browser context.',
          variant: 'destructive',
        })
        return false
      }
    },
    [toast],
  )
}
