/** Ildiz yuklanish holati — sahifalar almashganda ko'rinadi. */
export default function Loading() {
  return (
    <div className="flex min-h-dvh items-center justify-center bg-canvas">
      <div className="flex items-center gap-2.5 text-sm text-fg-faint">
        <span className="h-3 w-3 animate-spin rounded-full border-2 border-line border-t-accent" />
        Loading…
      </div>
    </div>
  )
}
