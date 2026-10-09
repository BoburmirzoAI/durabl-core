/**
 * Klaviatura yorliqlari.
 *
 * Dizaynda ko'rsatilganlar: ⌘K (palette), ⌘N (yangi job), ⌘F (qidiruv),
 * ⌘J (job'lar). Jadval navigatsiyasi (↑/↓/Enter/Esc) dizaynda tasvirlangan
 * fokus halqasidan kelib chiqadi.
 */

export interface Shortcut {
  /** Ko'rsatiladigan belgi (`⌘K`). */
  display: string
  /** `event.key` qiymati (kichik harf). */
  key: string
  /** Cmd (mac) yoki Ctrl (boshqa) kerakmi. */
  meta?: boolean
  shift?: boolean
  description: string
}

export const SHORTCUTS = {
  commandPalette: { display: '⌘K', key: 'k', meta: true, description: 'Command palette' },
  newJob: { display: '⌘N', key: 'n', meta: true, description: 'Submit new job' },
  // `/` — sahifa ichidagi qidiruvga fokus. ⌘F emas, chunki uni brauzerning
  // o'z qidiruvi egallagan; `/` esa GitHub/Linear/Vercel'da shu vazifada.
  search: { display: '/', key: '/', description: 'Focus search' },
  goJobs: { display: '⌘J', key: 'j', meta: true, description: 'Go to jobs' },
  escape: { display: 'ESC', key: 'escape', description: 'Close / clear' },
  rowDown: { display: '↓', key: 'arrowdown', description: 'Next row' },
  rowUp: { display: '↑', key: 'arrowup', description: 'Previous row' },
  // Vim uslubidagi muqobil — jadval ustida qo'l klaviaturadan uzilmasligi uchun
  rowDownVim: { display: 'j', key: 'j', description: 'Next row (vim)' },
  rowUpVim: { display: 'k', key: 'k', description: 'Previous row (vim)' },
  selectRowVim: { display: 'x', key: 'x', description: 'Toggle selection (vim)' },
  open: { display: '↵', key: 'enter', description: 'Open selected' },
  selectRow: { display: 'Space', key: ' ', description: 'Toggle row selection' },
  refresh: { display: '⌘R', key: 'r', meta: true, description: 'Refresh data' },
} as const satisfies Record<string, Shortcut>

export type ShortcutName = keyof typeof SHORTCUTS

/** Hodisa berilgan yorliqqa mos keladimi. */
export function matchesShortcut(event: KeyboardEvent, shortcut: Shortcut): boolean {
  const key = event.key.toLowerCase()
  if (key !== shortcut.key) return false
  const metaPressed = event.metaKey || event.ctrlKey
  if (shortcut.meta && !metaPressed) return false
  if (!shortcut.meta && metaPressed) return false
  if (shortcut.shift && !event.shiftKey) return false
  return true
}

/**
 * Fokus matn kiritish maydonidami — bo'lsa, harfli yorliqlar ishlamasligi
 * kerak (foydalanuvchi yozayotgan bo'ladi).
 */
export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable
}
