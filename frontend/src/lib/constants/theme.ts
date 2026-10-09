/**
 * Dizayn tokenlari TypeScript tomonida.
 *
 * Asosiy manba — `globals.css` dagi CSS o'zgaruvchilari. Bu fayl faqat
 * CSS'dan foydalanib bo'lmaydigan joylar uchun: SVG `stroke`/`fill`
 * atributlari va Recharts konfiguratsiyasi (ular `hsl(var(--x))` ni
 * qabul qiladi, shuning uchun shu yerda ham o'zgaruvchi ishlatiladi).
 */

/** SVG va grafiklar uchun rang havolalari. */
export const CHART_COLORS = {
  accent: 'hsl(var(--accent))',
  accentLight: 'hsl(var(--accent-light))',
  success: 'hsl(var(--success))',
  running: 'hsl(var(--running))',
  failed: 'hsl(var(--failed))',
  pending: 'hsl(var(--pending))',
  queued: 'hsl(var(--queued))',
  grid: 'hsl(var(--surface-4))',
  axis: 'hsl(var(--fg-faint))',
  tooltipBg: 'hsl(var(--surface-4))',
  tooltipBorder: 'hsl(var(--line-hover))',
  canvas: 'hsl(var(--canvas))',
} as const

/**
 * Throughput grafigining viewBox geometriyasi — dizayndagi qiymatlar.
 * `Durabl Dashboard.dc.html` dagi `VBW/VBH/padL/...` bilan AYNI.
 */
export const CHART_GEOMETRY = {
  width: 1000,
  height: 280,
  padLeft: 44,
  padRight: 14,
  padTop: 18,
  padBottom: 26,
} as const

/** Kichik grafiklar (analitika qatori) uchun geometriya. */
export const CHART_GEOMETRY_SM = {
  width: 1000,
  height: 200,
  padLeft: 40,
  padRight: 12,
  padTop: 14,
  padBottom: 24,
} as const

/** Sidebar kengligi (dizaynda `grid-template-columns:240px`). */
export const SIDEBAR_WIDTH = 240
export const SIDEBAR_WIDTH_COLLAPSED = 60

/** Topbar balandligi (dizaynda `height:52px`). */
export const TOPBAR_HEIGHT = 52
