/**
 * Sidebar navigatsiyasi — `design-reference/Durabl Dashboard.dc.html` dagi
 * `navSections` ro'yxatidan AYNAN olingan (bo'lim sarlavhalari, tartib,
 * SVG ikonka yo'llari).
 *
 * Ikonkalar `lucide-react` emas, dizayndagi XOM SVG `path` lari — chunki
 * dizaynda maxsus chizilgan va lucide ekvivalentlari boshqacha ko'rinadi.
 */

export interface NavItem {
  /** Ko'rinadigan nom. */
  name: string
  /** Yo'l (Next.js route). */
  href: string
  /** SVG `path` ning `d` atributi (24×24 viewBox). */
  icon: string
  /** Nishon kaliti — qiymat ish vaqtida (DLQ chuqurligi) qo'yiladi. */
  badgeKey?: 'dlq'
}

export interface NavSection {
  title: string
  items: NavItem[]
}

/** Mijoz paneli navigatsiyasi. */
export const NAV_SECTIONS: readonly NavSection[] = [
  {
    title: 'OVERVIEW',
    items: [
      { name: 'Dashboard', href: '/dashboard', icon: 'M4 4h7v7H4zM13 4h7v4h-7zM13 11h7v9h-7zM4 14h7v6H4z' },
      { name: 'Jobs', href: '/jobs', icon: 'M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01' },
      { name: 'Executions', href: '/executions', icon: 'M4 12h4l2 6 4-15 2 9h4' },
    ],
  },
  {
    title: 'AUTOMATION',
    items: [
      {
        name: 'Schedules',
        href: '/schedules',
        icon: 'M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z',
      },
      {
        name: 'Templates',
        href: '/templates',
        icon: 'M4 5h16v4H4zM4 12h7v7H4zM13 12h7v7h-7z',
      },
    ],
  },
  {
    title: 'RELIABILITY',
    items: [
      {
        name: 'Dead Letter Queue',
        href: '/dlq',
        icon: 'M12 3 2 20h20zM12 10v4M12 17h.01',
        badgeKey: 'dlq',
      },
      { name: 'Webhooks', href: '/webhooks', icon: 'M13 3 4 14h7l-1 7 9-11h-7z' },
    ],
  },
  {
    title: 'INSIGHTS',
    items: [
      { name: 'Analytics', href: '/analytics', icon: 'M4 4v16h16M8 16V11M13 16V7M18 16v-5' },
      { name: 'Usage', href: '/usage', icon: 'M12 3a9 9 0 1 0 9 9h-9z' },
    ],
  },
  {
    title: 'SETTINGS',
    items: [
      { name: 'API Keys', href: '/api-keys', icon: 'M10 14a5 5 0 1 1 5-5l6 6-2 2-2-2-2 2-2-2z' },
      {
        name: 'Billing',
        href: '/billing',
        icon: 'M3 7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 11h18',
      },
      {
        name: 'Settings',
        href: '/settings',
        icon: 'M12 9a3 3 0 1 0 0 6 3 3 0 0 0 0-6zM12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1',
      },
    ],
  },
] as const

/**
 * Admin paneli navigatsiyasi.
 *
 * Guruhlar ISH turiga qarab ajratilgan, obyekt turiga emas:
 *
 * - **PLATFORM** — umumiy manzara, kundalik birinchi qarash
 * - **OPERATIONS** — hodisa paytida ochiladigan sahifalar
 * - **CUSTOMERS** — foydalanuvchi va pul bilan bog'liq ishlar
 * - **CONFIGURATION** — tizim xatti-harakatini o'zgartirish
 * - **INSIGHTS** — tahlil va iz
 *
 * Hodisa paytida kerakli sahifani topish eng muhim mezon, shuning uchun
 * OPERATIONS yuqorida va unda aynan "nima buzildi" sahifalari turadi.
 */
export const ADMIN_NAV_SECTIONS: readonly NavSection[] = [
  {
    title: 'PLATFORM',
    items: [
      {
        name: 'Overview',
        href: '/admin',
        icon: 'M4 4h7v7H4zM13 4h7v4h-7zM13 11h7v9h-7zM4 14h7v6H4z',
      },
      {
        name: 'Workers',
        href: '/admin/workers',
        icon: 'M4 5h16v6H4zM4 13h16v6H4zM8 8h.01M8 16h.01',
      },
    ],
  },
  {
    title: 'OPERATIONS',
    items: [
      { name: 'All Jobs', href: '/admin/jobs', icon: 'M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01' },
      { name: 'Executions', href: '/admin/executions', icon: 'M4 12h4l2 6 4-15 2 9h4' },
      {
        name: 'Dead Letters',
        href: '/admin/dlq',
        icon: 'M12 3 2 20h20zM12 10v4M12 17h.01',
        badgeKey: 'dlq',
      },
      { name: 'Webhooks', href: '/admin/webhooks', icon: 'M13 3 4 14h7l-1 7 9-11h-7z' },
    ],
  },
  {
    title: 'CUSTOMERS',
    items: [
      { name: 'Users', href: '/admin/users', icon: 'M16 19v-2a4 4 0 0 0-8 0v2M12 7a3 3 0 1 0 0 6 3 3 0 0 0 0-6z' },
      {
        name: 'Billing',
        href: '/admin/billing',
        icon: 'M3 7a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2zM3 11h18',
      },
      {
        name: 'Support',
        href: '/admin/support',
        icon: 'M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z',
      },
      {
        name: 'Announcements',
        href: '/admin/announcements',
        icon: 'M3 11v2a1 1 0 0 0 1 1h3l5 4V6L7 10H4a1 1 0 0 0-1 1zM16 9a4 4 0 0 1 0 6',
      },
    ],
  },
  {
    title: 'CONFIGURATION',
    items: [
      {
        name: 'System',
        href: '/admin/system',
        icon: 'M12 3a9 9 0 1 0 9 9h-9zM12 3v9h9a9 9 0 0 0-9-9z',
      },
    ],
  },
  {
    title: 'INSIGHTS',
    items: [
      { name: 'Analytics', href: '/admin/analytics', icon: 'M4 4v16h16M8 16V11M13 16V7M18 16v-5' },
      {
        name: 'Audit Log',
        href: '/admin/audit',
        icon: 'M9 5h6a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM10 9h4M10 13h4M10 17h2',
      },
    ],
  },
] as const

/** Breadcrumb uchun yo'l -> sarlavha jadvali. */
export const ROUTE_TITLES: Record<string, string> = {
  '/dashboard': 'Dashboard',
  '/jobs': 'Jobs',
  '/executions': 'Executions',
  '/schedules': 'Schedules',
  '/templates': 'Templates',
  '/jobs/new': 'New Job',
  '/notifications': 'Notifications',
  '/docs': 'Docs',
  '/dlq': 'Dead Letter Queue',
  '/webhooks': 'Webhooks',
  '/analytics': 'Analytics',
  '/usage': 'Usage',
  '/api-keys': 'API Keys',
  '/billing': 'Billing & Usage',
  '/settings': 'Settings',
  '/admin': 'Admin',
  '/admin/users': 'Users',
  '/admin/jobs': 'All Jobs',
  '/admin/workers': 'Workers',
  '/admin/system': 'System',
  '/admin/executions': 'Executions',
  '/admin/dlq': 'Dead Letters',
  '/admin/webhooks': 'Webhooks',
  '/admin/billing': 'Billing',
  '/admin/support': 'Support',
  '/admin/announcements': 'Announcements',
  '/admin/analytics': 'Analytics',
  '/admin/audit': 'Audit Log',
}

/** Barcha nav elementlarini yassi ro'yxat qilib qaytaradi (⌘K uchun). */
export function flattenNav(sections: readonly NavSection[]): NavItem[] {
  return sections.flatMap((s) => s.items)
}
