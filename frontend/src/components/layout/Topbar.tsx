'use client'

import { usePathname } from 'next/navigation'

import { KbdHint } from '@/components/common/KbdHint'
import { ROUTE_TITLES } from '@/lib/constants/nav'
import { cn } from '@/lib/utils/cn'
import { useCommandStore } from '@/stores/commandStore'
import { useUiStore } from '@/stores/uiStore'

import { NavIcon } from './NavIcon'
import { NotificationBell } from '@/components/notifications/NotificationBell'

/**
 * Yuqori panel — dizaynda 52px balandlik:
 * chapda breadcrumb, markazda qidiruv (⌘K ni ochadi), o'ngda
 * bildirishnoma va avatar.
 */
export interface TopbarProps {
  /** Admin paneli uchun breadcrumb ildizi. */
  rootLabel?: string
  className?: string
}

export function Topbar({ rootLabel = 'Durabl', className }: TopbarProps) {
  const pathname = usePathname()
  const openPalette = useCommandStore((s) => s.openWith)
  const toggleSidebar = useUiStore((s) => s.toggleSidebar)
  const setMobileNavOpen = useUiStore((s) => s.setMobileNavOpen)

  // Yo'ldan breadcrumb yasaymiz: `/admin/users` -> Durabl › Admin › Users
  const segments = pathname.split('/').filter(Boolean)
  const crumbs: { label: string; href: string }[] = []
  let acc = ''
  for (const segment of segments) {
    acc += `/${segment}`
    const title = ROUTE_TITLES[acc]
    // Dinamik segment (`[id]`) sarlavhada yo'q — uni monospace ID sifatida ko'rsatamiz
    crumbs.push({ label: title ?? segment, href: acc })
  }

  return (
    <header
      className={cn(
        'flex h-[52px] shrink-0 items-center gap-4 border-b border-line bg-canvas px-5',
        className,
      )}
    >
      {/* Mobil menyu tugmasi */}
      <button
        type="button"
        aria-label="Open navigation"
        onClick={() => setMobileNavOpen(true)}
        className="flex h-8 w-8 items-center justify-center rounded-md text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg lg:hidden"
      >
        <NavIcon path="M4 6h16M4 12h16M4 18h16" size={17} strokeWidth={2} />
      </button>

      {/* Sidebar yig'ish (faqat katta ekranda) */}
      <button
        type="button"
        aria-label="Toggle sidebar"
        onClick={toggleSidebar}
        className="hidden h-8 w-8 items-center justify-center rounded-md text-fg-faint transition-colors hover:bg-surface-2 hover:text-fg lg:flex"
      >
        <NavIcon path="M4 5h16M4 12h10M4 19h16" size={16} strokeWidth={2} />
      </button>

      <nav aria-label="Breadcrumb" className="flex min-w-0 items-center gap-[7px] text-base">
        <span className="shrink-0 text-fg-dim">{rootLabel}</span>
        {crumbs.map((crumb, i) => {
          const isLast = i === crumbs.length - 1
          const isId = !ROUTE_TITLES[crumb.href]
          return (
            <span key={crumb.href} className="flex min-w-0 items-center gap-[7px]">
              <NavIcon path="M9 6l6 6-6 6" size={14} strokeWidth={2} className="shrink-0 text-fg-ghost" />
              <span
                className={cn(
                  'truncate',
                  isLast ? 'font-medium text-fg' : 'text-fg-dim',
                  isId && 'font-mono text-sm',
                )}
              >
                {crumb.label}
              </span>
            </span>
          )
        })}
      </nav>

      {/* Qidiruv — bosilganda ⌘K paletteni ochadi */}
      <div className="hidden flex-1 justify-center md:flex">
        <button
          type="button"
          onClick={() => openPalette()}
          className="flex w-full max-w-[400px] cursor-text items-center gap-2 rounded-lg border border-line bg-surface px-2.5 py-1.5 text-left transition-colors hover:border-line-hover"
        >
          <NavIcon
            path="M10 4a6 6 0 1 0 0 12 6 6 0 0 0 0-12zM20 20l-4.3-4.3"
            size={14}
            className="text-fg-faint"
          />
          <span className="flex-1 text-sm text-fg-faint">
            Search jobs, executions, workers…
          </span>
          <KbdHint>⌘K</KbdHint>
        </button>
      </div>

      <div className="ml-auto flex items-center gap-1.5 md:ml-0">
        <button
          type="button"
          aria-label="Search"
          onClick={() => openPalette()}
          className="flex h-8 w-8 items-center justify-center rounded-md text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg md:hidden"
        >
          <NavIcon path="M10 4a6 6 0 1 0 0 12 6 6 0 0 0 0-12zM20 20l-4.3-4.3" size={16} />
        </button>

        <NotificationBell />
      </div>
    </header>
  )
}
