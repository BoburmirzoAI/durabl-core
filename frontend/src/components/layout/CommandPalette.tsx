'use client'

import { Command } from 'cmdk'
import { useRouter } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'

import { KbdGroup } from '@/components/common/KbdHint'
import { Dialog, DialogContent, DialogTitle } from '@/components/ui/dialog'
import { ADMIN_NAV_SECTIONS, NAV_SECTIONS, flattenNav } from '@/lib/constants/nav'
import { SHORTCUTS } from '@/lib/constants/shortcuts'
import { useJobs } from '@/lib/hooks/useJobs'
import { useShortcut } from '@/lib/hooks/useKeyboard'
import { cn } from '@/lib/utils/cn'
import { jobStatusStyle } from '@/lib/utils/status'
import { useCommandStore } from '@/stores/commandStore'

import { NavIcon } from './NavIcon'

/**
 * Command palette (⌘K) — dizayndagi ko'rinish:
 * 600px panel, 14vh yuqoridan, guruhlangan ro'yxat (Navigation / Actions /
 * Recent Jobs), pastda klaviatura yorliqlari qatori.
 *
 * `cmdk` kutubxonasi ishlatiladi: u fuzzy qidiruv va klaviatura
 * navigatsiyasini (↑/↓/Enter) o'zi boshqaradi.
 */
export function CommandPalette() {
  const router = useRouter()
  const open = useCommandStore((s) => s.open)
  const initialQuery = useCommandStore((s) => s.initialQuery)
  const setOpen = useCommandStore((s) => s.setOpen)
  const close = useCommandStore((s) => s.close)
  const toggle = useCommandStore((s) => s.toggle)

  const [query, setQuery] = useState('')

  // Ochilganda oldindan yozilgan so'rovni qo'yamiz
  useEffect(() => {
    if (open) setQuery(initialQuery)
  }, [open, initialQuery])

  useShortcut(SHORTCUTS.commandPalette, toggle)

  // Oxirgi job'lar — palette ochiq bo'lgandagina so'raladi
  const { data: recentJobs } = useJobs(
    { page: 1, page_size: 6, sort_by: 'created_at', sort_order: 'desc' },
    { autoRefresh: false },
  )

  const go = useCallback(
    (href: string) => {
      close()
      router.push(href)
    },
    [close, router],
  )

  const navItems = [...flattenNav(NAV_SECTIONS), ...flattenNav(ADMIN_NAV_SECTIONS)]

  const actions = [
    {
      label: 'Submit new job',
      hint: SHORTCUTS.newJob.display,
      icon: 'M12 5v14M5 12h14',
      run: () => go('/jobs?new=1'),
    },
    {
      label: 'Retry all DLQ entries',
      icon: 'M3 12a9 9 0 1 0 3-6.7M3 3v4h4',
      run: () => go('/dlq'),
    },
    {
      label: 'Create API key',
      icon: 'M10 14a5 5 0 1 1 5-5l6 6-2 2-2-2-2 2-2-2z',
      run: () => go('/api-keys?new=1'),
    },
    {
      label: 'Add webhook',
      icon: 'M13 3 4 14h7l-1 7 9-11h-7z',
      run: () => go('/webhooks?new=1'),
    },
    {
      label: 'View documentation',
      icon: 'M4 5a2 2 0 0 1 2-2h9l5 5v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2zM14 3v6h6',
      run: () => go('/docs'),
    },
  ]

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent
        align="top"
        width="lg"
        className="max-w-[600px] p-0"
        onOpenAutoFocus={(event) => {
          // cmdk o'zi inputga fokus beradi
          event.preventDefault()
        }}
      >
        <DialogTitle className="sr-only">Command palette</DialogTitle>
        <Command
          loop
          // Qidiruvni cmdk o'zi filtrlaydi
          className="flex flex-col"
        >
          <div className="flex items-center gap-3 border-b border-line-inner px-[18px] py-4">
            <NavIcon
              path="M10 4a6 6 0 1 0 0 12 6 6 0 0 0 0-12zM20 20l-4.3-4.3"
              size={18}
              strokeWidth={1.9}
              className="text-fg-faint"
            />
            <Command.Input
              autoFocus
              value={query}
              onValueChange={setQuery}
              placeholder="Type a command or search…"
              className="input-bare text-md"
            />
            <span className="kbd shrink-0">ESC</span>
          </div>

          <Command.List className="max-h-[384px] overflow-y-auto p-2">
            <Command.Empty className="px-4 py-10 text-center text-md text-fg-faint">
              No results for &quot;<span className="text-fg-muted">{query}</span>&quot;
            </Command.Empty>

            <Command.Group
              heading="Navigation"
              className="mb-1.5 [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1.5 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:text-2xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[.09em] [&_[cmdk-group-heading]]:text-fg-faint"
            >
              {navItems.map((item) => (
                <PaletteItem
                  key={item.href}
                  icon={item.icon}
                  label={item.name}
                  onSelect={() => go(item.href)}
                />
              ))}
            </Command.Group>

            <Command.Group
              heading="Actions"
              className="mb-1.5 [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1.5 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:text-2xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[.09em] [&_[cmdk-group-heading]]:text-fg-faint"
            >
              {actions.map((action) => (
                <PaletteItem
                  key={action.label}
                  icon={action.icon}
                  label={action.label}
                  hint={action.hint}
                  onSelect={action.run}
                />
              ))}
            </Command.Group>

            {recentJobs && recentJobs.items.length > 0 ? (
              <Command.Group
                heading="Recent Jobs"
                className="[&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:pb-1.5 [&_[cmdk-group-heading]]:pt-2 [&_[cmdk-group-heading]]:text-2xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-[.09em] [&_[cmdk-group-heading]]:text-fg-faint"
              >
                {recentJobs.items.map((job) => {
                  const style = jobStatusStyle(job.status)
                  return (
                    <PaletteItem
                      key={job.id}
                      label={job.id}
                      mono
                      dotClassName={style.dot}
                      hint={style.label}
                      onSelect={() => go(`/jobs/${job.id}`)}
                    />
                  )
                })}
              </Command.Group>
            ) : null}
          </Command.List>

          <div className="flex items-center gap-4 border-t border-line-inner bg-canvas-raised px-4 py-2.5">
            <KbdGroup keys={['↑', '↓']} label="navigate" />
            <KbdGroup keys={['↵']} label="select" />
            <KbdGroup keys={['esc']} label="close" />
            <span className="ml-auto flex items-center gap-[7px] text-xs text-fg-faint">
              <span className="flex h-3.5 w-3.5 items-center justify-center rounded-sm bg-accent-solid text-[9px] font-bold text-white">
                D
              </span>
              Durabl
            </span>
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  )
}

function PaletteItem({
  icon,
  label,
  hint,
  mono = false,
  dotClassName,
  onSelect,
}: {
  icon?: string
  label: string
  hint?: string
  mono?: boolean
  dotClassName?: string
  onSelect: () => void
}) {
  return (
    <Command.Item
      value={label}
      onSelect={onSelect}
      className="flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2.5 data-[selected=true]:bg-surface-3"
    >
      <span className="flex w-[18px] shrink-0 justify-center">
        {dotClassName ? (
          <span className={cn('h-2 w-2 rounded-full', dotClassName)} />
        ) : icon ? (
          <NavIcon path={icon} size={16} className="text-fg-dim" />
        ) : null}
      </span>
      <span
        className={cn('min-w-0 flex-1 truncate text-md text-fg-soft', mono && 'font-mono text-base')}
      >
        {label}
      </span>
      {hint ? <span className="kbd shrink-0">{hint}</span> : null}
    </Command.Item>
  )
}
