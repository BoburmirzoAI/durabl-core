'use client'

import { useSimulation } from '@/lib/hooks/useSimulation'

import { Sidebar } from './Sidebar'
import { CommandPalette } from './CommandPalette'
import { MobileNav } from './MobileNav'
import { ImpersonationBanner } from './ImpersonationBanner'
import { Topbar } from './Topbar'

/**
 * Ilova qobig'i — dizayndagi tashqi grid:
 * `grid-template-columns: 240px minmax(0,1fr); height: 100vh`.
 *
 * Kichik ekranda sidebar yashiriladi (`MobileNav` sheet'i orqali ochiladi),
 * shuning uchun grid faqat `lg` dan boshlab ikki ustunli bo'ladi.
 */
export interface AppShellProps {
  children: React.ReactNode
  variant?: 'customer' | 'admin'
}

export function AppShell({ children, variant = 'customer' }: AppShellProps) {
  // Mock simulyatsiyasi — BIR MARTA, qobiq darajasida ishga tushadi
  useSimulation()

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-canvas text-fg">
      <div className="hidden lg:flex">
        <Sidebar variant={variant} />
      </div>
      <MobileNav variant={variant} />

      <main className="flex min-h-0 min-w-0 flex-1 flex-col">
        <ImpersonationBanner />
        <Topbar rootLabel={variant === 'admin' ? 'Durabl Admin' : 'Durabl'} />
        {/*
          Bu konteyner `flex flex-col` BO'LMASLIGI kerak: flex bolalari
          standart bo'yicha qisqaradi (`flex-shrink: 1`), shuning uchun uzun
          jadval to'lib oqish o'rniga siqilib ketadi va scroll umuman
          paydo bo'lmaydi. Blok tartibi + `space-y-5` to'g'ri ishlaydi.
        */}
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-6 py-[22px]">
          {children}
        </div>
      </main>

      <CommandPalette />
    </div>
  )
}
