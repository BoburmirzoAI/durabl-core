'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'

import { ADMIN_NAV_SECTIONS, NAV_SECTIONS, type NavSection } from '@/lib/constants/nav'
import { useDlqStats } from '@/lib/hooks/useDlq'
import { cn } from '@/lib/utils/cn'
import { useUiStore } from '@/stores/uiStore'

import { NavIcon } from './NavIcon'
import { UserMenu } from './UserMenu'

/**
 * Chap panel — dizayndagi 240px ustun.
 *
 * Tuzilma: logotip + versiya nishoni / bo'limlarga ajratilgan navigatsiya /
 * pastda foydalanuvchi bloki. Faol element chap tomonida 2px aksent
 * chizig'i va `#18181B` fon oladi.
 */
export interface SidebarProps {
  variant?: 'customer' | 'admin'
  /** Mobil sheet ichida ko'rsatilayotganda chegara kerak emas. */
  embedded?: boolean
  onNavigate?: () => void
}

export function Sidebar({ variant = 'customer', embedded = false, onNavigate }: SidebarProps) {
  const pathname = usePathname()
  const collapsed = useUiStore((s) => s.sidebarCollapsed)
  const { data: dlqStats } = useDlqStats()

  const isAdmin = variant === 'admin'
  const sections: readonly NavSection[] = isAdmin ? ADMIN_NAV_SECTIONS : NAV_SECTIONS
  const isCollapsed = collapsed && !embedded

  return (
    <aside
      className={cn(
        'flex min-h-0 flex-col bg-canvas transition-[width] duration-200',
        !embedded && 'border-r border-line',
        isCollapsed ? 'w-[60px]' : 'w-[240px]',
      )}
    >
      {/* Logotip */}
      <div
        className={cn(
          'flex items-center gap-[9px] border-b border-line-subtle px-4 pb-3.5 pt-4',
          isCollapsed && 'justify-center px-0',
        )}
      >
        <Link
          href={isAdmin ? '/admin' : '/dashboard'}
          className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-accent-solid text-md font-bold tracking-[-.02em] text-white hover:text-white"
          aria-label="Durabl home"
        >
          D
        </Link>
        {!isCollapsed ? (
          <>
            <span className="text-lg font-semibold tracking-[-.01em] text-fg">Durabl</span>
            {isAdmin ? (
              <span className="ml-auto rounded-sm border border-failed/30 bg-failed/[0.13] px-1.5 py-px font-mono text-2xs font-semibold text-failed">
                ADMIN
              </span>
            ) : (
              <span className="ml-auto rounded-sm border border-line px-1.5 py-px font-mono text-2xs text-fg-faint">
                v2.4
              </span>
            )}
          </>
        ) : null}
      </div>

      {/* Navigatsiya */}
      <nav
        aria-label={isAdmin ? 'Admin navigation' : 'Main navigation'}
        className="flex flex-1 flex-col gap-3.5 overflow-y-auto px-2.5 py-3"
      >
        {sections.map((section) => (
          <div key={section.title} className="flex flex-col gap-0.5">
            {!isCollapsed ? (
              <div className="px-2.5 py-1 text-2xs font-semibold tracking-[.09em] text-fg-faint">
                {section.title}
              </div>
            ) : null}
            {section.items.map((item) => {
              // `/jobs` `/jobs/abc` da ham faol bo'lishi kerak, lekin
              // `/admin` `/admin/users` da faol BO'LMASLIGI kerak
              const active =
                pathname === item.href ||
                (item.href !== '/admin' && pathname.startsWith(`${item.href}/`))
              const badge = item.badgeKey === 'dlq' ? dlqStats?.depth : undefined

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  onClick={onNavigate}
                  aria-current={active ? 'page' : undefined}
                  title={isCollapsed ? item.name : undefined}
                  className={cn(
                    'relative flex items-center gap-[9px] rounded-md px-2.5 py-1.5 leading-none transition-colors',
                    isCollapsed && 'justify-center px-0',
                    active
                      ? 'bg-surface-3 text-fg hover:text-fg'
                      : 'text-fg-muted hover:bg-surface-2 hover:text-fg',
                  )}
                >
                  <span
                    className={cn(
                      'absolute -left-2.5 top-1/2 h-[15px] w-0.5 -translate-y-1/2 rounded-r-sm',
                      active ? 'bg-accent' : 'bg-transparent',
                    )}
                  />
                  <NavIcon path={item.icon} className={active ? 'text-accent' : 'text-fg-dim'} />
                  {!isCollapsed ? (
                    <>
                      <span className="flex-1 text-base">{item.name}</span>
                      {badge !== undefined && badge > 0 ? (
                        <span className="tabular rounded-[5px] bg-failed/[0.14] px-1.5 py-px font-mono text-2xs font-medium text-failed">
                          {badge}
                        </span>
                      ) : null}
                    </>
                  ) : null}
                </Link>
              )
            })}
          </div>
        ))}

        {/* Admin <-> mijoz paneli o'tish havolasi */}
        <div className="mt-auto pt-2">
          <Link
            href={isAdmin ? '/dashboard' : '/admin'}
            onClick={onNavigate}
            className={cn(
              'flex items-center gap-[9px] rounded-md px-2.5 py-1.5 text-base text-fg-dim transition-colors hover:bg-surface-2 hover:text-fg-muted',
              isCollapsed && 'justify-center px-0',
            )}
            title={isCollapsed ? (isAdmin ? 'Back to app' : 'Admin panel') : undefined}
          >
            <NavIcon
              path={isAdmin ? 'M19 12H5M11 6l-6 6 6 6' : 'M12 3l9 4.5v5c0 4.5-3.8 7.9-9 9-5.2-1.1-9-4.5-9-9v-5z'}
            />
            {!isCollapsed ? (isAdmin ? 'Back to app' : 'Admin panel') : null}
          </Link>
        </div>
      </nav>

      <UserMenu collapsed={isCollapsed} />
    </aside>
  )
}
