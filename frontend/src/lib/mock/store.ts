/**
 * O'zgaruvchan mock holati.
 *
 * ═══════════════════════════════════════════════════════════════════
 * NEGA KERAK
 * ═══════════════════════════════════════════════════════════════════
 *
 * Mock generatorlari deterministik: bir xil urug'dan har doim bir xil
 * ma'lumot chiqadi. Bu SSR uchun zarur (server va mijoz bir xil HTML
 * ko'rishi kerak), lekin amallar uchun yetarli emas — `cancelJob` faqat
 * o'zgartirilgan NUSXA qaytarsa, ro'yxat qayta so'ralganda job yana
 * eski holatda chiqadi va tugma "ishlamagandek" ko'rinadi.
 *
 * Shuning uchun har bir to'plam BIR MARTA urug'dan quriladi va keyin
 * xotirada o'zgartiriladi. Sahifa yangilanganda holat boshlang'ichga
 * qaytadi — backend ulanmaguncha bu kutilgan xulq.
 *
 * ═══════════════════════════════════════════════════════════════════
 * BACKEND ULANGANDA
 * ═══════════════════════════════════════════════════════════════════
 *
 * Bu fayl butunlay o'chiriladi. `*.api.ts` dagi funksiyalar imzosi
 * o'zgarmaydi, shuning uchun hook'lar va komponentlarga tegilmaydi.
 */

/** O'zgarishlarni kuzatuvchilar (jonli simulyatsiya uchun). */
type Listener = () => void

const listeners = new Set<Listener>()

/** O'zgarishga obuna bo'lish. Qaytaradigan funksiya obunani bekor qiladi. */
export function subscribe(listener: Listener): () => void {
  listeners.add(listener)
  return () => listeners.delete(listener)
}

/** Kuzatuvchilarni xabardor qilish. */
export function notifyChanged(): void {
  for (const listener of listeners) listener()
}

/**
 * Urug'dan bir marta quriladigan, keyin o'zgartiriladigan to'plam.
 *
 * `build()` FAQAT birinchi murojaatda chaqiriladi — shundan keyin
 * massiv o'z hayotini yashaydi.
 */
export class MockCollection<T> {
  private items: T[] | null = null

  constructor(
    private readonly build: () => T[],
    private readonly idOf: (item: T) => string,
  ) {}

  /** Barcha elementlar (ichki massivning O'ZI emas, nusxasi). */
  all(): T[] {
    return [...this.raw()]
  }

  /** Ichki massiv — faqat shu modul ichidagi o'qish uchun. */
  raw(): T[] {
    if (this.items === null) this.items = this.build()
    return this.items
  }

  find(id: string): T | undefined {
    return this.raw().find((item) => this.idOf(item) === id)
  }

  /** Elementni yangilaydi va YANGI holatini qaytaradi. */
  update(id: string, patch: Partial<T> | ((item: T) => Partial<T>)): T | undefined {
    const items = this.raw()
    const index = items.findIndex((item) => this.idOf(item) === id)
    if (index === -1) return undefined
    const current = items[index] as T
    const delta = typeof patch === 'function' ? patch(current) : patch
    const next = { ...current, ...delta }
    items[index] = next
    notifyChanged()
    return next
  }

  /** Bir nechta elementni birdan yangilaydi. Yangilanganlar sonini qaytaradi. */
  updateMany(ids: string[], patch: Partial<T> | ((item: T) => Partial<T>)): number {
    let count = 0
    for (const id of ids) {
      if (this.update(id, patch)) count += 1
    }
    return count
  }

  /** Yangi element qo'shadi (sukut bo'yicha boshiga — ro'yxatlar yangidan eskiga). */
  insert(item: T, position: 'start' | 'end' = 'start'): T {
    const items = this.raw()
    if (position === 'start') items.unshift(item)
    else items.push(item)
    notifyChanged()
    return item
  }

  /** Elementni o'chiradi. */
  remove(id: string): boolean {
    const items = this.raw()
    const index = items.findIndex((item) => this.idOf(item) === id)
    if (index === -1) return false
    items.splice(index, 1)
    notifyChanged()
    return true
  }

  /** Bir nechta elementni o'chiradi. O'chirilganlar sonini qaytaradi. */
  removeMany(ids: string[]): number {
    let count = 0
    for (const id of ids) {
      if (this.remove(id)) count += 1
    }
    return count
  }

  /** Shartga mos elementlarni o'chiradi. */
  removeWhere(predicate: (item: T) => boolean): number {
    const items = this.raw()
    const before = items.length
    const kept = items.filter((item) => !predicate(item))
    items.length = 0
    items.push(...kept)
    const removed = before - items.length
    if (removed > 0) notifyChanged()
    return removed
  }

  /** Holatni boshlang'ich urug'ga qaytaradi (testlar uchun). */
  reset(): void {
    this.items = null
    notifyChanged()
  }
}
