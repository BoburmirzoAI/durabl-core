'use client'

import { create } from 'zustand'

/**
 * Jadval qatorlarini tanlash holati.
 *
 * Nega alohida store: Jobs va DLQ jadvallari ikkisi ham ko'p tanlash +
 * bulk amallarini qo'llaydi, mantiq esa bir xil. Har bir jadval o'z
 * "scope" nomi bilan ishlaydi, shunda biridan ikkinchisiga o'tganda
 * tanlov aralashmaydi.
 */
interface SelectionState {
  /** scope -> tanlangan ID'lar. */
  selected: Record<string, string[]>
  /** scope -> klaviatura fokusidagi qator indeksi. */
  focusIndex: Record<string, number>

  toggle: (scope: string, id: string) => void
  setMany: (scope: string, ids: string[]) => void
  clear: (scope: string) => void
  isSelected: (scope: string, id: string) => boolean
  count: (scope: string) => number
  ids: (scope: string) => string[]

  setFocus: (scope: string, index: number) => void
  moveFocus: (scope: string, delta: number, max: number) => number
}

export const useSelectionStore = create<SelectionState>((set, get) => ({
  selected: {},
  focusIndex: {},

  toggle: (scope, id) =>
    set((s) => {
      const current = s.selected[scope] ?? []
      const next = current.includes(id) ? current.filter((v) => v !== id) : [...current, id]
      return { selected: { ...s.selected, [scope]: next } }
    }),

  setMany: (scope, ids) => set((s) => ({ selected: { ...s.selected, [scope]: ids } })),

  clear: (scope) => set((s) => ({ selected: { ...s.selected, [scope]: [] } })),

  isSelected: (scope, id) => (get().selected[scope] ?? []).includes(id),

  count: (scope) => (get().selected[scope] ?? []).length,

  ids: (scope) => get().selected[scope] ?? [],

  setFocus: (scope, index) => set((s) => ({ focusIndex: { ...s.focusIndex, [scope]: index } })),

  moveFocus: (scope, delta, max) => {
    const current = get().focusIndex[scope] ?? -1
    // Chegaralarda to'xtaydi (aylanmaydi) — uzun jadvalda ataylab
    const next = Math.max(0, Math.min(max - 1, current + delta))
    set((s) => ({ focusIndex: { ...s.focusIndex, [scope]: next } }))
    return next
  },
}))
