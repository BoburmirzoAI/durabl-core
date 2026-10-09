/**
 * Mock ma'lumot qatlamining yagona kirish nuqtasi.
 *
 * DIQQAT: komponentlar bu moduldan TO'G'RIDAN-TO'G'RI foydalanmaydi.
 * Oqim quyidagicha:
 *
 *   komponent -> `lib/hooks/*` -> `lib/api/*.api.ts` -> `lib/mock/*`
 *
 * Backend ulanganda faqat `lib/api/*.api.ts` ning ICHI o'zgaradi
 * (mock chaqiruvi `fetch` ga almashadi) — komponent va hook'lar
 * TEGILMAYDI.
 */

export * from './seed'
export * from './fixtures'
export * from './jobs'
export * from './dlq'
export * from './workers'
export * from './analytics'
export * from './webhooks'
export * from './api-keys'
export * from './billing'
export * from './users'
