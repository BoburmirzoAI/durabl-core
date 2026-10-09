/** Raqam va qiymatlarni ko'rsatish uchun formatlash. */

/**
 * Davomiylikni o'qishli ko'rinishga o'tkazadi.
 *
 * Dizaynda job davomiyligi `1.24s` ko'rinishida — ya'ni sekundgacha ikki
 * kasr. Millisekundlar `142ms`, daqiqadan oshsa `3m 4s`.
 */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${seconds.toFixed(2)}s`
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  if (m < 60) return `${m}m ${s}s`
  const h = Math.floor(m / 60)
  return `${h}h ${m % 60}m`
}

/** Qisqa davomiylik (grafik o'qi uchun): `1.2s`, `142ms`. */
export function formatDurationShort(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

/** Uptime: `3d 4h`, `4h 12m`, `12m`. */
export function formatUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}d ${h}h`
  if (h > 0) return `${h}h ${m}m`
  return `${m}m`
}

/** Katta sonlarni qisqartiradi: `12,847` -> `12.8K`, `1.2M`. */
export function formatCompact(n: number): string {
  if (Math.abs(n) < 1000) return String(n)
  if (Math.abs(n) < 1_000_000) {
    const v = n / 1000
    return `${v % 1 === 0 ? v : v.toFixed(1)}K`
  }
  const v = n / 1_000_000
  return `${v % 1 === 0 ? v : v.toFixed(1)}M`
}

/** Mingliklarni vergul bilan ajratadi: `12847` -> `12,847`. */
export function formatNumber(n: number): string {
  return n.toLocaleString('en-US')
}

/** Foiz: `99.2%`. Butun bo'lsa kasr ko'rsatilmaydi. */
export function formatPercent(value: number, digits = 1): string {
  return `${value % 1 === 0 ? value : value.toFixed(digits)}%`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MB`
  return `${(bytes / 1024 ** 3).toFixed(1)} GB`
}

/** Pul: `$99.00`. */
export function formatCurrency(usd: number): string {
  return `$${usd.toFixed(2)}`
}

/** Urinishlar: `1/3`. */
export function formatAttempts(used: number, max: number): string {
  return `${used}/${max + 1}`
}

/** Uzun matnni kesadi (`...` bilan). */
export function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`
}

/** Snake_case/kebab-case'ni o'qishli sarlavhaga: `out_of_memory` -> `Out of memory`. */
export function humanize(value: string): string {
  const spaced = value.replace(/[_-]+/g, ' ').trim()
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

/** Email'dan bosh harflar: `jordan@durabl.dev` -> `JO`. */
export function initialsFromEmail(email: string): string {
  const local = email.split('@')[0] ?? email
  return local.slice(0, 2).toUpperCase()
}

/** Ism'dan bosh harflar: `Jordan Diaz` -> `JD`. */
export function initialsFromName(name: string | null, fallbackEmail: string): string {
  if (!name) return initialsFromEmail(fallbackEmail)
  const parts = name.trim().split(/\s+/)
  if (parts.length === 1) return (parts[0] ?? '').slice(0, 2).toUpperCase()
  return `${(parts[0] ?? '')[0] ?? ''}${(parts[parts.length - 1] ?? '')[0] ?? ''}`.toUpperCase()
}
