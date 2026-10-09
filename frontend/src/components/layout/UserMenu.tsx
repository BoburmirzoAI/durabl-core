'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { currentUser, logout } from '@/lib/auth'
import { cn } from '@/lib/utils/cn'
import { useUiStore } from '@/stores/uiStore'

import { NavIcon } from './NavIcon'

/**
 * Sidebar pastidagi foydalanuvchi bloki — dizaynda avatar + ism + email,
 * o'ngda sozlamalar ikonkasi.
 */
/**
 * Avatar ranglari.
 *
 * Sinf nomlari TO'LIQ yozilgan: Tailwind JIT `bg-${token}/[0.18]` kabi
 * qurilgan satrlarni ko'rmaydi va sinfni chiqarmaydi.
 */
const AVATAR_CLASS: Record<string, string> = {
  accent: 'bg-accent/[0.18] text-accent-light',
  success: 'bg-success/[0.16] text-success',
  pending: 'bg-pending/[0.16] text-pending',
  failed: 'bg-failed/[0.16] text-failed',
  neutral: 'bg-surface-4 text-fg-soft',
}

export function UserMenu({ collapsed = false }: { collapsed?: boolean }) {
  const router = useRouter()
  const user = currentUser()
  const avatarColor = useUiStore((s) => s.preferences.avatar_color)

  const onLogout = (): void => {
    logout()
    router.push('/login')
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={cn(
            'flex items-center gap-[9px] border-t border-line-subtle p-2.5 text-left transition-colors hover:bg-canvas-raised',
            collapsed && 'justify-center',
          )}
        >
          <span
            className={cn(
              'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold',
              // Rang Settings → Profile da tanlanadi
              AVATAR_CLASS[avatarColor] ?? AVATAR_CLASS.accent,
            )}
          >
            {user.initials}
          </span>
          {!collapsed ? (
            <>
              <span className="min-w-0 flex-1 leading-[1.25]">
                <span className="block truncate text-sm font-medium text-fg">
                  {user.full_name ?? user.email}
                </span>
                <span className="block truncate text-xs text-fg-faint">{user.email}</span>
              </span>
              <NavIcon
                path="M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"
                className="text-fg-faint"
              />
            </>
          ) : null}
        </button>
      </DropdownMenuTrigger>

      <DropdownMenuContent side="top" align="start" className="min-w-[200px]">
        <DropdownMenuLabel>{user.email}</DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/settings" className="text-fg-soft hover:text-fg">
            <NavIcon path="M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1" size={13} />
            Settings
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href="/billing" className="text-fg-soft hover:text-fg">
            <NavIcon path="M3 7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 11h18" size={13} />
            Billing
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem asChild>
          <Link href="/docs" className="text-fg-soft hover:text-fg">
            <NavIcon path="M4 5a2 2 0 0 1 2-2h9l5 5v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2zM14 3v6h6" size={13} />
            Documentation
          </Link>
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem danger onSelect={onLogout}>
          <NavIcon path="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9" size={13} />
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
