import { type NextRequest, NextResponse } from 'next/server'

/**
 * Yo'l himoyasi.
 *
 * Mock autentifikatsiya tokenni `durabl_token` cookie'siga yozadi
 * (`lib/auth.ts`), shuning uchun middleware uni o'qib himoyalangan
 * yo'llarni filtrlaydi. Mijoz tomonidagi `AuthGuard` ikkinchi qatlam:
 * middleware faqat cookie borligini, `AuthGuard` esa admin huquqini ham
 * tekshiradi.
 */

const COOKIE_NAME = 'durabl_token'

/** Autentifikatsiya talab qiladigan yo'llar. */
const PROTECTED_PREFIXES = [
  '/dashboard',
  '/jobs',
  '/executions',
  '/dlq',
  '/webhooks',
  '/analytics',
  '/usage',
  '/api-keys',
  '/billing',
  '/settings',
  '/admin',
]

/** Kirgan foydalanuvchi ko'rishi kerak bo'lmagan yo'llar. */
const AUTH_PAGES = ['/login', '/register']

export function middleware(request: NextRequest): NextResponse {
  const { pathname } = request.nextUrl
  const hasToken = Boolean(request.cookies.get(COOKIE_NAME)?.value)

  const isProtected = PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  )

  if (isProtected && !hasToken) {
    const url = request.nextUrl.clone()
    url.pathname = '/login'
    // Kirgandan keyin foydalanuvchi xohlagan sahifaga qaytadi
    url.searchParams.set('next', pathname)
    return NextResponse.redirect(url)
  }

  if (hasToken && AUTH_PAGES.includes(pathname)) {
    const url = request.nextUrl.clone()
    url.pathname = '/dashboard'
    url.search = ''
    return NextResponse.redirect(url)
  }

  return NextResponse.next()
}

export const config = {
  /**
   * Statik fayllar va Next.js ichki yo'llari chetlab o'tiladi —
   * aks holda har bir rasm/skript uchun middleware ishlaydi.
   */
  matcher: ['/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp|ico)$).*)'],
}
