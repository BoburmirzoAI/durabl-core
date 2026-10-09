import Link from 'next/link'

/**
 * Auth qobig'i — markazlashgan panel, chap tomonda brend.
 *
 * Dizaynda auth sahifalari yo'q, shuning uchun dashboard uslubidan
 * olingan: ayni qorong'u fon, `#141416` panel, aksent tugma.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <header className="flex h-[52px] shrink-0 items-center px-5">
        <Link href="/" className="flex items-center gap-[9px] hover:text-fg">
          <span className="flex h-6 w-6 items-center justify-center rounded-md bg-accent-solid text-md font-bold text-white">
            D
          </span>
          <span className="text-lg font-semibold tracking-[-.01em] text-fg">Durabl</span>
        </Link>
      </header>

      <main className="flex flex-1 items-start justify-center px-4 pb-16 pt-[6vh]">
        <div className="w-full max-w-[420px]">{children}</div>
      </main>

      <footer className="flex shrink-0 flex-wrap items-center justify-center gap-5 px-4 pb-6 text-sm text-fg-faint">
        <Link href="/docs">Docs</Link>
        <Link href="/pricing">Pricing</Link>
        <span>© {new Date().getFullYear()} Durabl</span>
      </footer>
    </div>
  )
}
