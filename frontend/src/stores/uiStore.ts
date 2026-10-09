'use client'

import { create } from 'zustand'
import { persist } from 'zustand/middleware'

import type { UserPreferences } from '@/types'

/**
 * Interfeys holati — sidebar, sozlamalar.
 *
 * `persist` bilan `localStorage` ga saqlanadi, lekin `skipHydration` YO'Q:
 * Zustand `persist` SSR'da bo'sh boshlanadi va hydration'dan keyin
 * to'ldiriladi, shuning uchun sidebar holati birinchi renderda standart
 * bo'ladi (sakrashni oldini olish uchun CSS tranzitsiyasi ishlatiladi).
 */
interface UiState {
  sidebarCollapsed: boolean
  toggleSidebar: () => void
  setSidebarCollapsed: (collapsed: boolean) => void

  /** Mobil menyu (sheet) ochiqmi. */
  mobileNavOpen: boolean
  setMobileNavOpen: (open: boolean) => void

  preferences: UserPreferences
  setPreference: <K extends keyof UserPreferences>(key: K, value: UserPreferences[K]) => void
}

export const DEFAULT_PREFERENCES: UserPreferences = {
  density: 'compact',
  auto_refresh: true,
  notify_dlq_threshold: true,
  notify_job_failed: false,
  show_log_timestamps: true,
  avatar_color: 'accent',
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      sidebarCollapsed: false,
      toggleSidebar: () => set((s) => ({ sidebarCollapsed: !s.sidebarCollapsed })),
      setSidebarCollapsed: (collapsed) => set({ sidebarCollapsed: collapsed }),

      mobileNavOpen: false,
      setMobileNavOpen: (open) => set({ mobileNavOpen: open }),

      preferences: DEFAULT_PREFERENCES,
      setPreference: (key, value) =>
        set((s) => ({ preferences: { ...s.preferences, [key]: value } })),
    }),
    {
      name: 'durabl-ui',
      // Mobil menyu holati saqlanmaydi (har safar yopiq boshlanishi kerak)
      partialize: (state) => ({
        sidebarCollapsed: state.sidebarCollapsed,
        preferences: state.preferences,
      }),
    },
  ),
)
