import Link from 'next/link'

import { RelativeTime } from '@/components/common/RelativeTime'
import type { DlqStats } from '@/types'

/**
 * DLQ ogohlantirish bayrog'i — dizayndagi qizil panel.
 *
 * Chuqurlik 0 bo'lsa KO'RSATILMAYDI (ijobiy holat uchun bo'sh holat bor).
 */
export function DlqAlertBanner({ stats }: { stats: DlqStats | undefined }) {
  if (!stats || stats.depth === 0) return null

  return (
    <div className="flex shrink-0 flex-wrap items-center gap-3 rounded-xl border border-failed/20 bg-failed/[0.07] px-[15px] py-3">
      <svg
        width="18"
        height="18"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="shrink-0 text-failed"
        aria-hidden
      >
        <path d="M12 3 2 20h20zM12 10v4M12 17h.01" />
      </svg>
      <span className="text-base text-failed-text">
        <span className="font-semibold text-failed-bright">
          {stats.depth} {stats.depth === 1 ? 'job needs' : 'jobs need'} attention.
        </span>{' '}
        {stats.oldest_failed_at ? (
          <>
            Oldest has been waiting{' '}
            <span className="font-mono">
              <RelativeTime value={stats.oldest_failed_at} refreshMs={60_000} />
            </span>
            .
          </>
        ) : null}
      </span>
      <Link href="/settings" className="ml-auto shrink-0 text-sm font-medium">
        Configure alerts →
      </Link>
    </div>
  )
}
