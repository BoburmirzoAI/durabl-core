'use client'

import { useEffect } from 'react'

import { useUiStore } from '@/stores/uiStore'

import { Sidebar } from './Sidebar'

/**
 * Mobil navigatsiya — kichik ekranda sidebar yashiriladi va shu
 * "sheet" ichida ochiladi.
 *
 * Radix Dialog ISHLATILMAYDI: bizga sidebar'ning AYNI nusxasi kerak
 * (nav holati, DLQ nishoni), shunchaki boshqa joylashuvda.
 */
export function MobileNav({ variant = 'customer' }: { variant?: 'customer' | 'admin' }) {
  const open = useUiStore((s) => s.mobileNavOpen)
  const setOpen = useUiStore((s) => s.setMobileNavOpen)

  // Esc bilan yopilishi va ochiq paytda sahifa aylanmasligi
  useEffect(() => {
    if (!open) return
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('keydown', onKeyDown)
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previousOverflow
    }
  }, [open, setOpen])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 lg:hidden">
      <button
        type="button"
        aria-label="Close navigation"
        onClick={() => setOpen(false)}
        className="absolute inset-0 animate-overlay-in bg-black/55 backdrop-blur-[4px]"
      />
      <div className="absolute inset-y-0 left-0 flex w-[260px] animate-slide-down border-r border-line bg-canvas shadow-modal">
        <Sidebar variant={variant} embedded onNavigate={() => setOpen(false)} />
      </div>
    </div>
  )
}
