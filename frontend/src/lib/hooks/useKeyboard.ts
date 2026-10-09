'use client'

import { useEffect, useState } from 'react'

import { SHORTCUTS, type Shortcut, isTypingTarget, matchesShortcut } from '@/lib/constants/shortcuts'

/**
 * Global klaviatura yorlig'ini tinglaydi.
 *
 * `allowWhileTyping` — sukut bo'yicha `false`: foydalanuvchi matn yozayotganda
 * harfli yorliqlar ishlamaydi. Faqat `Esc` va meta-yorliqlar (⌘K) istisno
 * bo'lishi mumkin.
 */
export function useShortcut(
  shortcut: Shortcut,
  handler: (event: KeyboardEvent) => void,
  options?: { enabled?: boolean; allowWhileTyping?: boolean },
): void {
  const enabled = options?.enabled ?? true
  const allowWhileTyping = options?.allowWhileTyping ?? Boolean(shortcut.meta)

  useEffect(() => {
    if (!enabled) return
    const onKeyDown = (event: KeyboardEvent): void => {
      if (!allowWhileTyping && isTypingTarget(event.target)) return
      if (!matchesShortcut(event, shortcut)) return
      event.preventDefault()
      handler(event)
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [shortcut, handler, enabled, allowWhileTyping])
}

/** Bir nechta yorliqni birdan ro'yxatdan o'tkazadi. */
export function useShortcuts(
  entries: { shortcut: Shortcut; handler: (event: KeyboardEvent) => void }[],
  enabled = true,
): void {
  useEffect(() => {
    if (!enabled) return
    const onKeyDown = (event: KeyboardEvent): void => {
      for (const { shortcut, handler } of entries) {
        const allowWhileTyping = Boolean(shortcut.meta) || shortcut.key === 'escape'
        if (!allowWhileTyping && isTypingTarget(event.target)) continue
        if (!matchesShortcut(event, shortcut)) continue
        event.preventDefault()
        handler(event)
        return
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [entries, enabled])
}

/**
 * Sahifa ichidagi qidiruv maydoniga `/` bilan fokus beradi.
 *
 * Qaytaradigan qiymat — `ref` callback'i, uni to'g'ridan-to'g'ri
 * `<SearchField ref={...} />` ga berish mumkin. Matn yozilayotganda yorliq
 * ishlamaydi (`isTypingTarget`), ya'ni qidiruv ichida `/` yozish mumkin.
 */
export function useSearchFocus(): (node: HTMLInputElement | null) => void {
  const [node, setNode] = useState<HTMLInputElement | null>(null)
  useShortcut(SHORTCUTS.search, () => {
    node?.focus()
    node?.select()
  })
  return setNode
}
