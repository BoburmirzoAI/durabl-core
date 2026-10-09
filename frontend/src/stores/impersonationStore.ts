'use client'

import { create } from 'zustand'

import type { AdminUser } from '@/types'

/**
 * "View as user" holati.
 *
 * Admin boshqa foydalanuvchi ko'zi bilan ko'rishi mumkin. Bu XAVFLI rejim,
 * shuning uchun u butun ilova bo'ylab ko'rinadigan banner bilan belgilanadi —
 * admin o'zi kim nomidan ishlayotganini unutmasligi kerak.
 *
 * Backend ulanganda bu yerga impersonation tokeni qo'shiladi; hozircha
 * faqat UI holati.
 */
interface ImpersonationState {
  /** Kim nomidan ko'rilyapti (`null` — o'z hisobi). */
  target: Pick<AdminUser, 'id' | 'email' | 'full_name' | 'plan'> | null
  start: (user: AdminUser) => void
  stop: () => void
}

export const useImpersonationStore = create<ImpersonationState>((set) => ({
  target: null,
  start: (user) =>
    set({
      target: { id: user.id, email: user.email, full_name: user.full_name, plan: user.plan },
    }),
  stop: () => set({ target: null }),
}))
