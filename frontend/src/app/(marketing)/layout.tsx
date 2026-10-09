import Link from 'next/link'

/** Ommaviy sahifalar qobig'i — oddiy nav + footer. */
export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-canvas">
      <header className="sticky top-0 z-40 flex h-[52px] shrink-0 items-center gap-6 border-b border-line bg-canvas/90 px-5 backdrop-blur">
        <Link href="/home" className="flex items-center gap-[9px] hover:text-fg">
          <span className="flex h-6 w-6 items-center justify-center rounded-md bg-accent-solid text-md font-bold text-white">
            D
          </span>
          <span className="text-lg font-semibold tracking-[-.01em] text-fg">Durabl</span>
        </Link>

        <nav className="hidden items-center gap-5 text-base sm:flex">
          <Link href="/pricing" className="text-fg-muted hover:text-fg">
            Pricing
          </Link>
          <Link href="/docs" className="text-fg-muted hover:text-fg">
            Docs
          </Link>
        </nav>

        <div className="ml-auto flex items-center gap-2.5">
          <Link href="/login" className="text-base text-fg-muted hover:text-fg">
            Sign in
          </Link>
          <Link
            href="/register"
            className="rounded-lg bg-accent-solid px-3 py-1.5 text-base font-medium text-white hover:bg-accent-hover hover:text-white"
          >
            Get started
          </Link>
        </div>
      </header>

      <main className="flex-1">{children}</main>

      <footer className="border-t border-line px-5 py-8">
        <div className="mx-auto flex max-w-[1100px] flex-wrap items-center gap-6 text-sm text-fg-faint">
          <span className="flex items-center gap-2">
            <span className="flex h-4 w-4 items-center justify-center rounded-sm bg-accent-solid text-[9px] font-bold text-white">
              D
            </span>
            Durabl
          </span>
          <Link href="/docs">Docs</Link>
          <Link href="/pricing">Pricing</Link>
          <Link href="/dashboard">Dashboard</Link>
          <span className="ml-auto">© {new Date().getFullYear()} Durabl</span>
        </div>
      </footer>
    </div>
  )
}
