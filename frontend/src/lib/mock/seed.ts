/**
 * Deterministik tasodifiylik — mock ma'lumot generatori uchun poydevor.
 *
 * NEGA DETERMINISTIK: `Math.random()` server va brauzerda boshqa natija
 * beradi, natijada Next.js hydration xatosi chiqadi ("Text content did not
 * match"). Shuning uchun hamma qiymat urug'dan (seed) hisoblanadi — ayni
 * urug' har doim ayni ma'lumotni beradi.
 *
 * Usul dizayn faylidagi yondashuvdan olingan:
 *   `Math.abs(Math.sin(s) * 43758.5453) % 1`
 * — bu klassik GPU shader hash'i, tez va tarqalishi yaxshi.
 */

/** Urug'dan 0..1 oralig'idagi son. */
export function hash(seed: number): number {
  return Math.abs(Math.sin(seed) * 43758.5453) % 1
}

/** Deterministik generator — ketma-ket chaqiruvlar turli qiymat beradi. */
export class Rng {
  private cursor: number

  constructor(seed = 1) {
    this.cursor = seed
  }

  /** 0..1 */
  next(): number {
    this.cursor += 1
    return hash(this.cursor * 12.9898 + 78.233)
  }

  /** `min`..`max` oralig'idagi butun son (ikki chegara ham kiradi). */
  int(min: number, max: number): number {
    return min + Math.floor(this.next() * (max - min + 1))
  }

  /** `min`..`max` oralig'idagi kasr son. */
  float(min: number, max: number): number {
    return min + this.next() * (max - min)
  }

  /** Ro'yxatdan bitta element. */
  pick<T>(items: readonly T[]): T {
    if (items.length === 0) throw new Error('Rng.pick: bo\'sh ro\'yxat')
    return items[Math.floor(this.next() * items.length)] as T
  }

  /**
   * Og'irlikli tanlov — holatlar realistik taqsimlanishi uchun
   * (masalan job'larning 80% muvaffaqiyatli bo'ladi).
   */
  weighted<T>(entries: readonly (readonly [T, number])[]): T {
    const total = entries.reduce((sum, [, w]) => sum + w, 0)
    let roll = this.next() * total
    for (const [value, weight] of entries) {
      roll -= weight
      if (roll <= 0) return value
    }
    return entries[entries.length - 1]![0]
  }

  /** `true` ehtimolligi `probability` (0..1). */
  bool(probability = 0.5): boolean {
    return this.next() < probability
  }

  /** Belgilangan uzunlikdagi hex matn (ID uchun). */
  hex(length: number): string {
    let out = ''
    while (out.length < length) {
      out += Math.floor(this.next() * 16).toString(16)
    }
    return out.slice(0, length)
  }

  /** Ro'yxatni deterministik aralashtiradi. */
  shuffle<T>(items: readonly T[]): T[] {
    const copy = [...items]
    for (let i = copy.length - 1; i > 0; i -= 1) {
      const j = Math.floor(this.next() * (i + 1))
      const a = copy[i] as T
      const b = copy[j] as T
      copy[i] = b
      copy[j] = a
    }
    return copy
  }
}

/**
 * Ma'lumot generatsiyasi uchun yagona vaqt langari.
 *
 * Modul birinchi yuklanganda bir marta olinadi va BARCHA mock qiymatlar
 * shunga nisbatan hisoblanadi. Shu tufayli bitta sahifa ichida "2m ago"
 * va "5m ago" o'zaro mantiqiy bo'lib qoladi.
 */
export const NOW = Date.now()

/** `NOW` dan N daqiqa oldingi ISO vaqt. */
export function minutesAgo(minutes: number): string {
  return new Date(NOW - minutes * 60_000).toISOString()
}

/** `NOW` dan N soat oldingi ISO vaqt. */
export function hoursAgo(hours: number): string {
  return new Date(NOW - hours * 3_600_000).toISOString()
}

/** `NOW` dan N kun oldingi ISO vaqt. */
export function daysAgo(days: number): string {
  return new Date(NOW - days * 86_400_000).toISOString()
}

/** `NOW` dan N daqiqa keyingi ISO vaqt (rejalashtirilgan job uchun). */
export function minutesFromNow(minutes: number): string {
  return new Date(NOW + minutes * 60_000).toISOString()
}

/** Millisekundni ISO vaqtga qo'shadi. */
export function addMs(iso: string, ms: number): string {
  return new Date(new Date(iso).getTime() + ms).toISOString()
}
