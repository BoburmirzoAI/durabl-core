/** Vaqt bilan ishlash — nisbiy vaqt va formatlash. */

const MINUTE = 60
const HOUR = 3600
const DAY = 86400

/**
 * Nisbiy vaqt: `2m ago`, `3h ago`, `5d ago`.
 *
 * Dizaynda jadval ustunlari aynan shu qisqa shaklni ishlatadi, to'liq vaqt esa
 * `title` atributida ko'rinadi (`RelativeTime` komponenti ikkisini ham beradi).
 */
export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const diff = Math.round((now - then) / 1000)

  if (diff < 0) {
    // Kelajakdagi vaqt (rejalashtirilgan job)
    const ahead = Math.abs(diff)
    if (ahead < MINUTE) return `in ${ahead}s`
    if (ahead < HOUR) return `in ${Math.floor(ahead / MINUTE)}m`
    if (ahead < DAY) return `in ${Math.floor(ahead / HOUR)}h`
    return `in ${Math.floor(ahead / DAY)}d`
  }
  if (diff < 5) return 'just now'
  if (diff < MINUTE) return `${diff}s ago`
  if (diff < HOUR) return `${Math.floor(diff / MINUTE)}m ago`
  if (diff < DAY) return `${Math.floor(diff / HOUR)}h ago`
  if (diff < DAY * 30) return `${Math.floor(diff / DAY)}d ago`
  return `${Math.floor(diff / (DAY * 30))}mo ago`
}

/** To'liq vaqt belgisi (hover'da ko'rinadi): `Oct 4, 2026 14:32:07 UTC`. */
export function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return `${d.toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
    timeZone: 'UTC',
  })} UTC`
}

/** Faqat sana: `Oct 4, 2026`. */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone: 'UTC',
  })
}

/** Faqat soat:daqiqa (grafik o'qi va log qatorlari): `14:32`. */
export function formatClock(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toISOString().slice(11, 16)
}

/** Log qatori uchun aniq vaqt: `14:32:07.123`. */
export function formatLogTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toISOString().slice(11, 23)
}

/** Ikki vaqt orasidagi farq (ms). */
export function diffMs(from: string | null, to: string | null): number | null {
  if (!from || !to) return null
  const a = new Date(from).getTime()
  const b = new Date(to).getTime()
  if (Number.isNaN(a) || Number.isNaN(b)) return null
  return b - a
}

/**
 * Ixtiyoriy sana oralig'i uchun kodlash: `custom:<fromISO>:<toISO>`.
 *
 * Nega qator, obyekt emas: oraliq TanStack Query kalitiga, URL'ga va
 * API chaqiruviga bitta qiymat sifatida uzatiladi. Obyekt bo'lsa, har
 * uchala joyda alohida serializatsiya kerak bo'lardi.
 */
const CUSTOM_PREFIX = 'custom:'

export function customRange(from: Date | string, to: Date | string): string {
  const a = typeof from === 'string' ? from : from.toISOString()
  const b = typeof to === 'string' ? to : to.toISOString()
  return `${CUSTOM_PREFIX}${a}|${b}`
}

export interface RangeSpec {
  /** Boshlanish (ms). */
  from: number
  /** Tugash (ms). */
  to: number
  hours: number
  isCustom: boolean
}

/**
 * Oraliq qatorini aniq vaqt oynasiga aylantiradi.
 *
 * Yaroqsiz `custom:` qiymati jim 24 soatga qaytadi — foydalanuvchi buzuq
 * URL bilan kelganda sahifa yiqilmasligi kerak.
 */
export function parseRange(range: string, now: number = Date.now()): RangeSpec {
  if (range.startsWith(CUSTOM_PREFIX)) {
    const [fromRaw, toRaw] = range.slice(CUSTOM_PREFIX.length).split('|')
    const from = fromRaw ? new Date(fromRaw).getTime() : NaN
    const to = toRaw ? new Date(toRaw).getTime() : NaN
    if (!Number.isNaN(from) && !Number.isNaN(to) && to > from) {
      return { from, to, hours: (to - from) / 3_600_000, isCustom: true }
    }
  }
  if (range === 'all') {
    return { from: 0, to: now, hours: Number.POSITIVE_INFINITY, isCustom: false }
  }
  const hours = rangeToHours(range)
  return { from: now - hours * 3_600_000, to: now, hours, isCustom: false }
}

/** Nisbiy oraliqni soatga o'giradi (`24h` -> 24). */
export function rangeToHours(range: string): number {
  switch (range) {
    case '1h':
      return 1
    case '7d':
      return 24 * 7
    case '30d':
      return 24 * 30
    default:
      return 24
  }
}

/** Oraliq yorlig'i (`24h` -> `last 24h`). */
export function rangeLabel(range: string): string {
  if (range === 'all') return 'all time'
  if (range.startsWith(CUSTOM_PREFIX)) {
    const spec = parseRange(range)
    if (!spec.isCustom) return 'last 24h'
    const from = new Date(spec.from)
    const to = new Date(spec.to)
    const hhmm = (d: Date): string =>
      `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`
    // Bir kun ichidagi oyna uchun sanani ikki marta yozish ma'nosiz —
    // "Oct 5, 2026 – Oct 5, 2026" o'rniga vaqt ko'rsatiladi
    if (spec.hours < 24 && from.toISOString().slice(0, 10) === to.toISOString().slice(0, 10)) {
      return `${formatDate(from.toISOString())} ${hhmm(from)}–${hhmm(to)} UTC`
    }
    return `${formatDate(from.toISOString())} – ${formatDate(to.toISOString())}`
  }
  return range === '1h' ? 'last hour' : `last ${range}`
}

/**
 * Solishtirish uchun OLDINGI oraliq — joriy oynadan aynan shuncha
 * oldingi teng uzunlikdagi oyna.
 *
 * Teng uzunlik shart: 7 kunni 30 kun bilan solishtirish ma'nosiz.
 */
export function previousRange(range: string, now: number = Date.now()): string {
  const spec = parseRange(range, now)
  if (!Number.isFinite(spec.hours)) return range
  const span = spec.to - spec.from
  return customRange(new Date(spec.from - span), new Date(spec.from))
}
