import { redirect } from 'next/navigation'

/**
 * Ildiz yo'li.
 *
 * Landing page `(marketing)` guruhida `/home` sifatida turadi (u hozircha
 * placeholder — premium versiya alohida quriladi), shuning uchun `/`
 * to'g'ridan-to'g'ri dashboard'ga yo'naltiradi. Autentifikatsiya
 * tekshiruvini `middleware.ts` bajaradi va kerak bo'lsa `/login` ga oladi.
 */
export default function RootPage() {
  redirect('/dashboard')
}
