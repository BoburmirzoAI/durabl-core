'use client'

import { create } from 'zustand'

/**
 * Command palette (⌘K) holati.
 *
 * Alohida store — chunki paletteni ilovaning har joyidan ochish kerak
 * (topbar qidiruvi, klaviatura, bo'sh holatdagi tugma).
 */
interface CommandState {
  open: boolean
  /** Ochilganda oldindan yoziladigan so'rov (masalan "job " prefiksi). */
  initialQuery: string
  setOpen: (open: boolean) => void
  openWith: (query?: string) => void
  close: () => void
  toggle: () => void
}

export const useCommandStore = create<CommandState>((set) => ({
  open: false,
  initialQuery: '',
  setOpen: (open) => set({ open }),
  openWith: (query = '') => set({ open: true, initialQuery: query }),
  close: () => set({ open: false, initialQuery: '' }),
  toggle: () => set((s) => ({ open: !s.open, initialQuery: '' })),
}))
