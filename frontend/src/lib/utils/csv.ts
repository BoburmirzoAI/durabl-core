/**
 * CSV eksport — mock rejimida brauzer ichida yasaladi.
 *
 * Backend ulanganda bu `GET /api/v1/jobs/export?format=csv` ga almashadi
 * (server tomoni katta hajmni oqim bilan beradi). Hozircha ko'rinadigan
 * sahifa yoki tanlangan qatorlar eksport qilinadi.
 */

/**
 * Qiymatni CSV katagiga aylantiradi.
 *
 * Vergul, qo'shtirnoq yoki yangi qator bo'lsa — qo'shtirnoqqa olinadi va
 * ichidagi qo'shtirnoq ikkilantiriladi (RFC 4180). Bu qoidasiz Excel
 * ustunlarni noto'g'ri bo'lib yuboradi.
 */
function cell(value: unknown): string {
  if (value === null || value === undefined) return ''
  const text =
    typeof value === 'object' ? JSON.stringify(value) : String(value)
  return /[",\n\r]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

export interface CsvColumn<T> {
  header: string
  value: (row: T) => unknown
}

/** Qatorlardan CSV matni yasaydi. */
export function toCsv<T>(rows: T[], columns: CsvColumn<T>[]): string {
  const head = columns.map((c) => cell(c.header)).join(',')
  const body = rows.map((row) => columns.map((c) => cell(c.value(row))).join(',')).join('\n')
  return `${head}\n${body}`
}

/**
 * Faylni yuklab olishni boshlaydi.
 *
 * `URL.revokeObjectURL` MAJBURIY: aks holda har bir eksport xotirada blob
 * qoldirib ketadi va uzoq sessiyada bu sezilarli bo'ladi.
 */
export function downloadCsv(filename: string, csv: string): void {
  // BOM — Excel UTF-8 ni to'g'ri o'qishi uchun
  const blob = new Blob([`﻿${csv}`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

/** Fayl nomi uchun sana qo'shimchasi: `jobs-20261005-1432.csv`. */
export function timestampedName(prefix: string, extension = 'csv'): string {
  const now = new Date()
  const pad = (n: number): string => String(n).padStart(2, '0')
  return (
    `${prefix}-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}` +
    `-${pad(now.getHours())}${pad(now.getMinutes())}.${extension}`
  )
}
