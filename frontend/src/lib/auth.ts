/**
 * Mock autentifikatsiya.
 *
 * Backend YO'Q, shuning uchun istalgan email/parol ishlaydi: token
 * `localStorage` va cookie'ga yoziladi (cookie — Next.js middleware
 * yo'llarni himoya qilishi uchun).
 *
 * BACKEND ULANGANDA: faqat `login()`/`register()` ichidagi mock javob
 * `authApi.login(...)` ga almashadi. Token saqlash mantig'i o'zgarmaydi,
 * shuning uchun `client.ts` dagi `getAccessToken()` ham ishlashda davom etadi.
 */

import type { AuthSession, User } from '@/types'
import { CURRENT_USER } from '@/lib/mock/users'

const TOKEN_KEY = 'durabl_token'
const REFRESH_KEY = 'durabl_refresh'
const USER_KEY = 'durabl_user'
/** Middleware shu cookie'ni o'qiydi. */
export const COOKIE_NAME = 'durabl_token'

const isBrowser = (): boolean => typeof window !== 'undefined'

/** Cookie'dan token o'qish. */
function readCookieToken(): string | null {
  if (!isBrowser()) return null
  const match = document.cookie.match(new RegExp(`(?:^|;\\s*)${COOKIE_NAME}=([^;]*)`))
  return match?.[1] ? decodeURIComponent(match[1]) : null
}

/**
 * Joriy token.
 *
 * ═══════════════════════════════════════════════════════════════════════
 * NEGA IKKALA MANBA HAM O'QILADI
 * ═══════════════════════════════════════════════════════════════════════
 *
 * Sessiya ikki joyda saqlanadi: `localStorage` (mijoz qo'riqchisi uchun)
 * va cookie (`middleware.ts` uchun). Ularning qamrovi BIR XIL EMAS:
 *
 * - cookie **portni hisobga olmaydi** — `localhost:3000` va
 *   `localhost:3001` uni baham ko'radi;
 * - `localStorage` esa portni ham origin deb biladi — ikki portda ikkita
 *   alohida xotira.
 *
 * Shuning uchun bir portda kirib, boshqasida ochilganda cookie bor,
 * localStorage esa bo'sh bo'lib qolardi. Natijasi jim va chalg'ituvchi
 * edi: `AuthGuard` tokenni topa olmay `/login` ga yuborardi, middleware
 * esa cookie'ni ko'rib `/login` dan `/dashboard` ga qaytarardi — ya'ni
 * "Admin panel" bosilganda sahifa sababsiz dashboard'ga qaytardi.
 *
 * Endi cookie zaxira manba: ikkala qo'riqchi ham BIR XIL javob oladi.
 * Bu `localStorage` bloklangan shaxsiy rejimni ham tuzatadi.
 */
export function getAccessToken(): string | null {
  if (!isBrowser()) return null
  try {
    const stored = window.localStorage.getItem(TOKEN_KEY)
    if (stored) return stored
  } catch {
    // Shaxsiy rejimda localStorage bloklangan bo'lishi mumkin — cookie'ga tushamiz
  }
  return readCookieToken()
}

/**
 * Saqlangan foydalanuvchi.
 *
 * ## Nega qiymatlar `CURRENT_USER` ustiga QO'SHILADI
 *
 * `localStorage` ilovadan uzoqroq yashaydi: brauzerda ilovaning eski
 * versiyasidan qolgan yozuv turgan bo'lishi mumkin, va unda hozirgi
 * `User` turida bor maydon YO'Q bo'lishi mumkin.
 *
 * Yozuvni shundayligicha qaytarish jiddiy oqibat berardi: `is_admin`
 * yo'qolgan yozuv bilan admin paneli BUTUNLAY yopilib qolardi, va
 * foydalanuvchi buni faqat devtools orqali tuzata olardi.
 *
 * Shuning uchun saqlangan maydonlar standart qiymatlar USTIGA
 * qo'yiladi: yangi maydonlar standartdan to'ladi, saqlangan email va
 * ism esa o'z joyida qoladi.
 */
export function getStoredUser(): User | null {
  if (!isBrowser()) return null
  try {
    const raw = window.localStorage.getItem(USER_KEY)
    if (!raw) return null
    const parsed: unknown = JSON.parse(raw)
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) return null
    return { ...CURRENT_USER, ...(parsed as Partial<User>) }
  } catch {
    // Buzuq yozuv — standart foydalanuvchiga qaytamiz, yiqilmaymiz
    return null
  }
}

export function isAuthenticated(): boolean {
  return getAccessToken() !== null
}

function persist(session: AuthSession): void {
  if (!isBrowser()) return
  try {
    window.localStorage.setItem(TOKEN_KEY, session.access_token)
    window.localStorage.setItem(REFRESH_KEY, session.refresh_token)
    window.localStorage.setItem(USER_KEY, JSON.stringify(session.user))
  } catch {
    // localStorage ishlamasa ham cookie orqali sessiya saqlanadi
  }
  // `SameSite=Lax` — middleware o'qiy oladi, CSRF uchun ham xavfsiz
  document.cookie = `${COOKIE_NAME}=${session.access_token}; path=/; max-age=${session.expires_in}; SameSite=Lax`
}

export function clearSession(): void {
  if (!isBrowser()) return
  try {
    window.localStorage.removeItem(TOKEN_KEY)
    window.localStorage.removeItem(REFRESH_KEY)
    window.localStorage.removeItem(USER_KEY)
  } catch {
    // e'tiborsiz
  }
  document.cookie = `${COOKIE_NAME}=; path=/; max-age=0; SameSite=Lax`
}

function mockSession(email: string, fullName?: string): AuthSession {
  const user: User = {
    ...CURRENT_USER,
    email,
    full_name: fullName ?? CURRENT_USER.full_name,
  }
  return {
    access_token: `mock.${btoa(email).replace(/=/g, '')}.token`,
    refresh_token: 'mock.refresh.token',
    token_type: 'bearer',
    expires_in: 60 * 60 * 24 * 7,
    user,
  }
}

/** `POST /api/v1/auth/login` — mock rejimida istalgan parol ishlaydi. */
export async function login(email: string, _password: string): Promise<AuthSession> {
  await new Promise((r) => setTimeout(r, 420))
  const session = mockSession(email)
  persist(session)
  return session
}

/** `POST /api/v1/auth/register` */
export async function register(
  email: string,
  _password: string,
  fullName?: string,
): Promise<AuthSession> {
  await new Promise((r) => setTimeout(r, 520))
  const session = mockSession(email, fullName)
  persist(session)
  return session
}

export function logout(): void {
  clearSession()
}

/** Joriy foydalanuvchi — saqlangan bo'lsa undan, aks holda mock. */
export function currentUser(): User {
  return getStoredUser() ?? CURRENT_USER
}
