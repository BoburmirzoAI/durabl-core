import Link from 'next/link'

/** 404 — ilovaning istalgan joyida. */
export default function NotFound() {
  return (
    <div className="flex min-h-dvh flex-col items-center justify-center gap-4 bg-canvas px-4 text-center">
      <div className="font-mono text-5xl font-semibold tracking-[-.03em] text-fg-ghost">404</div>
      <div>
        <div className="text-xl font-semibold text-fg">Page not found</div>
        <p className="mx-auto mt-2 max-w-[400px] text-base text-fg-muted">
          The page you are looking for does not exist, or the job it pointed to was deleted.
        </p>
      </div>
      <div className="flex items-center gap-2.5">
        <Link
          href="/dashboard"
          className="rounded-lg bg-accent-solid px-4 py-2 text-base font-medium text-white hover:bg-accent-hover hover:text-white"
        >
          Go to dashboard
        </Link>
        <Link
          href="/jobs"
          className="rounded-lg border border-line bg-surface px-4 py-2 text-base font-medium text-fg-soft hover:border-line-hover hover:text-fg"
        >
          Browse jobs
        </Link>
      </div>
    </div>
  )
}
