'use client'

import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/button'
import { currentUser, isAuthenticated, logout } from '@/lib/auth'

/**
 * Mock autentifikatsiya qo'riqchisi.
 *
 * Token `localStorage` da, shuning uchun tekshiruv FAQAT mijozda bo'ladi.
 * Server'da `middleware.ts` cookie bo'yicha yo'naltiradi — ikki qatlam
 * birgalikda ishlaydi.
 *
 * `checking` holati ikki xil ishlaydi (ataylab assimetrik):
 *
 * - Oddiy panel (`requireAdmin=false`) — darhol `children` ko'rsatiladi.
 *   Aks holda bu qo'riqchi butun qobiqni (sidebar + topbar) va sahifaning
 *   o'z skeleton holatini bosib, to'la ekranli spinner chiqaradi — ya'ni
 *   `(dashboard)/loading.tsx` HECH QACHON ko'rinmaydi. Server tomoni
 *   `middleware.ts` cookie bilan allaqachon yopilgan, bu esa ikkinchi
 *   qatlam — shuning uchun optimistik ko'rsatish xavfsiz.
 *
 * - Admin zonasi (`requireAdmin=true`) — spinner saqlanadi, chunki admin
 *   bo'lmagan foydalanuvchiga admin kontenti bir lahzaga ham ko'rinmasligi
 *   kerak.
 */
export function AuthGuard({
  children,
  requireAdmin = false,
}: {
  children: React.ReactNode
  requireAdmin?: boolean
}) {
  const router = useRouter()
  const [state, setState] = useState<'checking' | 'allowed' | 'denied'>('checking')

  useEffect(() => {
    if (!isAuthenticated()) {
      const next = encodeURIComponent(window.location.pathname)
      router.replace(`/login?next=${next}`)
      return
    }
    if (requireAdmin && !currentUser().is_admin) {
      setState('denied')
      return
    }
    setState('allowed')
  }, [router, requireAdmin])

  if (state === 'checking' && requireAdmin) {
    return (
      <div className="flex h-dvh items-center justify-center bg-canvas">
        <div className="flex items-center gap-2.5 text-sm text-fg-faint">
          <span className="h-3 w-3 animate-spin rounded-full border-2 border-line border-t-accent" />
          Checking permissions…
        </div>
      </div>
    )
  }

  if (state === 'denied') {
    return (
      <div className="flex h-dvh flex-col items-center justify-center gap-4 bg-canvas px-4 text-center">
        <div className="flex h-12 w-12 items-center justify-center rounded-xl border border-failed/25 bg-failed/[0.08]">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" className="text-failed" aria-hidden>
            <path d="M12 3 2 20h20zM12 10v4M12 17h.01" />
          </svg>
        </div>
        <div className="max-w-[420px]">
          <div className="text-xl font-semibold text-fg">Admin access required</div>
          <div className="mt-1 text-base leading-[1.6] text-fg-dim">
            This account is not an admin. In demo mode every sign-in creates an admin account, so
            if you expected access, the session stored in this browser is from an older build —
            sign out and back in to refresh it.
          </div>
        </div>
        <div className="flex flex-wrap items-center justify-center gap-2">
          <Button variant="secondary" onClick={() => router.push('/dashboard')}>
            Back to dashboard
          </Button>
          {/*
            Tupikdan chiqish yo'li.

            Eski sessiya bilan qolib ketgan foydalanuvchi uchun bu YAGONA
            yo'l: aks holda u devtools ochib `localStorage` ni qo'lda
            tozalashi kerak bo'lardi.
          */}
          <Button
            variant="primary"
            onClick={() => {
              logout()
              router.replace('/login?next=%2Fadmin')
            }}
          >
            Sign out and sign in again
          </Button>
        </div>
      </div>
    )
  }

  return <>{children}</>
}
