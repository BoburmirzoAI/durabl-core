/**
 * Mock qatlami uchun sahifalash, tartiblash va filtrlash yordamchilari.
 *
 * Backend bu ishni SQL'da bajaradi; mock rejimida biz ayni mantiqni
 * xotirada takrorlaymiz, shuning uchun javob SHAKLI bir xil
 * (`{items, pagination}`) va komponentlar farqni sezmaydi.
 */

import { parseRange } from '@/lib/utils/time'
import type { Paginated, PaginationMeta, SortOrder } from '@/types'

export const DEFAULT_PAGE_SIZE = 25

/** Ro'yxatni sahifalab `Paginated<T>` qaytaradi. */
export function paginate<T>(items: T[], page = 1, pageSize = DEFAULT_PAGE_SIZE): Paginated<T> {
  const total = items.length
  const totalPages = Math.max(1, Math.ceil(total / pageSize))
  const safePage = Math.min(Math.max(1, page), totalPages)
  const start = (safePage - 1) * pageSize

  const pagination: PaginationMeta = {
    page: safePage,
    page_size: pageSize,
    total,
    total_pages: totalPages,
    has_next: safePage < totalPages,
    has_prev: safePage > 1,
  }

  return { items: items.slice(start, start + pageSize), pagination }
}

/**
 * Ro'yxatni maydon bo'yicha tartiblaydi.
 *
 * `null`/`undefined` qiymatlar HAR DOIM oxirida turadi (tartib yo'nalishidan
 * qat'i nazar) — aks holda bo'sh davomiylikli job'lar ro'yxat boshini egallab
 * oladi va foydalanuvchi uchun shovqin bo'ladi.
 */
export function sortBy<T>(items: T[], field: keyof T | string, order: SortOrder = 'desc'): T[] {
  const dir = order === 'asc' ? 1 : -1
  return [...items].sort((a, b) => {
    const av = (a as Record<string, unknown>)[field as string]
    const bv = (b as Record<string, unknown>)[field as string]

    const aEmpty = av === null || av === undefined
    const bEmpty = bv === null || bv === undefined
    if (aEmpty && bEmpty) return 0
    if (aEmpty) return 1
    if (bEmpty) return -1

    if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir
    if (typeof av === 'boolean' && typeof bv === 'boolean') {
      return (Number(av) - Number(bv)) * dir
    }
    return String(av).localeCompare(String(bv)) * dir
  })
}

/** Matn qidiruvi — bir nechta maydon bo'yicha (registrga sezgir emas). */
export function searchIn<T>(items: T[], query: string | undefined, fields: (keyof T)[]): T[] {
  const q = query?.trim().toLowerCase()
  if (!q) return items
  return items.filter((item) =>
    fields.some((field) => {
      const value = item[field]
      if (value === null || value === undefined) return false
      if (Array.isArray(value)) return value.some((v) => String(v).toLowerCase().includes(q))
      return String(value).toLowerCase().includes(q)
    }),
  )
}

/** Ko'p tanlovli filtr — ro'yxat bo'sh bo'lsa filtr qo'llanmaydi. */
export function filterByAny<T, V>(items: T[], values: V[] | undefined, pick: (item: T) => V): T[] {
  if (!values || values.length === 0) return items
  const set = new Set(values)
  return items.filter((item) => set.has(pick(item)))
}

/** Nisbiy vaqt oralig'i bo'yicha filtr (`24h`, `7d`, `30d`, `all`). */
export function filterByRange<T>(items: T[], range: string | undefined, pick: (item: T) => string): T[] {
  if (!range || range === 'all') return items
  // `custom:<from>|<to>` ham qo'llanadi — analitikadan drill-down qilganda
  // aniq vaqt oynasi uzatiladi
  const { from, to } = parseRange(range)
  return items.filter((item) => {
    const t = new Date(pick(item)).getTime()
    return t >= from && t <= to
  })
}
