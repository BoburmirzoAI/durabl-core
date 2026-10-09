import type { Config } from 'tailwindcss'

/**
 * Durabl dizayn tizimi — `design-reference/*.dc.html` dan chiqarilgan.
 *
 * Har bir rang CSS o'zgaruvchisi sifatida `globals.css` da e'lon qilinadi va
 * shu yerda Tailwind nomiga bog'lanadi. Komponentlarda XOM hex yozilmaydi —
 * faqat `bg-surface`, `text-fg-muted`, `border-line` kabi tokenlar.
 */
const config: Config = {
  darkMode: ['class', '[data-theme="dark"]'],
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // --- Yuzalar (eng qorong'udan yorug'iga) ---
        canvas: 'hsl(var(--canvas))', //        #0A0A0B — sahifa foni
        'canvas-deep': 'hsl(var(--canvas-deep))', // #09090A — log/kod foni
        'canvas-sunken': 'hsl(var(--canvas-sunken))', // #0D0D0E — ochilgan qator
        'canvas-raised': 'hsl(var(--canvas-raised))', // #0F0F10 — kbd, input
        surface: 'hsl(var(--surface))', //      #141416 — kartalar, jadvallar
        'surface-2': 'hsl(var(--surface-2))', // #161619 — menyu, hover
        'surface-3': 'hsl(var(--surface-3))', // #18181B — qator hover
        'surface-4': 'hsl(var(--surface-4))', // #1C1C20 — tooltip, grid chizig'i
        'surface-5': 'hsl(var(--surface-5))', // #1F1F24 — menyu element hover

        // --- Chegaralar ---
        'line-subtle': 'hsl(var(--line-subtle))', // #161619 — eng yengil ajratgich
        'line-inner': 'hsl(var(--line-inner))', //  #1E1E22 — karta ichidagi ajratgich
        line: 'hsl(var(--line))', //                #242428 — standart chegara
        'line-strong': 'hsl(var(--line-strong))', // #2A2A30 — menyu chegarasi
        'line-hover': 'hsl(var(--line-hover))', //  #33333A — hover chegarasi

        // --- Matn ---
        fg: 'hsl(var(--fg))', //                 #FAFAFA — asosiy
        'fg-bright': 'hsl(var(--fg-bright))', // #E4E4E7 — mono ID
        'fg-soft': 'hsl(var(--fg-soft))', //     #D4D4D8 — tugma matni
        'fg-muted': 'hsl(var(--fg-muted))', //   #A1A1AA — ikkilamchi
        'fg-dim': 'hsl(var(--fg-dim))', //       #919199 — uchlamchi
        'fg-faint': 'hsl(var(--fg-faint))', //   #81818D — yorliq, placeholder
        'fg-ghost': 'hsl(var(--fg-ghost))', //   #656570 — qator raqami, o'chirilgan

        // --- Aksent (binafsha) ---
        accent: 'hsl(var(--accent))', //               #9166F7 — matn, chegara, grafik
        'accent-solid': 'hsl(var(--accent-solid))', // #7843F5 — oq matnli to'ldirish
        'accent-hover': 'hsl(var(--accent-hover))', // #682DF3 — to'ldirish hover
        'accent-light': 'hsl(var(--accent-light))', // #A78BFA — havola hover
        'accent-pale': 'hsl(var(--accent-pale))', //   #C4B5FD — bulk panel matni
        'accent-bar': 'hsl(var(--accent-bar))', //     #17141F — bulk panel foni
        'accent-bar-2': 'hsl(var(--accent-bar-2))', // #1C1826 — bulk tugma
        'accent-bar-3': 'hsl(var(--accent-bar-3))', // #231D33 — bulk tugma hover
        'accent-edge': 'hsl(var(--accent-edge))', //   #2E2640 — bulk chegara
        'accent-edge-2': 'hsl(var(--accent-edge-2))', // #3A2F52

        // --- Holat ranglari (job statuslari) ---
        success: 'hsl(var(--success))', // #22C55E
        running: 'hsl(var(--running))', // #3B82F6
        failed: 'hsl(var(--failed))', //   #EF4444
        pending: 'hsl(var(--pending))', // #EAB308
        queued: 'hsl(var(--queued))', //   #A1A1AA
        // Xato matni uchun yorug' qizil (traceback, alert)
        'failed-text': 'hsl(var(--failed-text))', // #FCA5A5
        'failed-bright': 'hsl(var(--failed-bright))', // #FECACA
      },
      fontFamily: {
        sans: ['var(--font-inter)', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'JetBrains Mono', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        // Dizayn 13px bazaga qurilgan — shkala shunga moslangan
        '2xs': ['10px', { lineHeight: '1.3' }],
        xs: ['11px', { lineHeight: '1.4' }],
        sm: ['12px', { lineHeight: '1.45' }],
        base: ['13px', { lineHeight: '1.5' }],
        md: ['14px', { lineHeight: '1.5' }],
        lg: ['15px', { lineHeight: '1.45' }],
        xl: ['17px', { lineHeight: '1.35' }],
        '2xl': ['20px', { lineHeight: '1.3' }],
        '3xl': ['22px', { lineHeight: '1.25' }],
        '4xl': ['26px', { lineHeight: '1.1' }],
        '5xl': ['28px', { lineHeight: '1' }],
      },
      borderRadius: {
        sm: '4px',
        DEFAULT: '6px',
        md: '7px',
        lg: '8px',
        xl: '10px',
        '2xl': '12px',
        '3xl': '14px',
      },
      boxShadow: {
        menu: '0 12px 32px rgba(0,0,0,.6)',
        tooltip: '0 8px 24px rgba(0,0,0,.5)',
        modal: '0 32px 80px rgba(0,0,0,.7)',
        'focus-row': 'inset 0 0 0 1px hsl(var(--accent))',
      },
      keyframes: {
        // Dizayndagi `dpulse` — jonli holat nuqtasi
        'pulse-dot': {
          '0%': { boxShadow: '0 0 0 0 hsl(var(--pulse-color) / 0.45)' },
          '70%': { boxShadow: '0 0 0 5px hsl(var(--pulse-color) / 0)' },
          '100%': { boxShadow: '0 0 0 0 hsl(var(--pulse-color) / 0)' },
        },
        // Dizayndagi `dbar` — panel/menyu ochilishi
        'slide-down': {
          from: { opacity: '0', transform: 'translateY(-4px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        // Dizayndagi `dolay` / `dpop` — modal
        'overlay-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        'pop-in': {
          from: { opacity: '0', transform: 'translateY(-8px) scale(.98)' },
          to: { opacity: '1', transform: 'translateY(0) scale(1)' },
        },
        // DIQQAT: modal `left-1/2 top-1/2` bilan joylashadi va markazga
        // `-translate-x-1/2 -translate-y-1/2` orqali tortiladi. Animatsiya
        // `transform` ni to'liq QAYTA YOZADI, shuning uchun markazlashtiruvchi
        // siljish keyframe ICHIDA bo'lishi shart — aks holda modal chetda
        // ochilib, animatsiya tugagach markazga "sakraydi".
        'dialog-in': {
          from: { opacity: '0', transform: 'translate(-50%, calc(-50% - 8px)) scale(.98)' },
          to: { opacity: '1', transform: 'translate(-50%, -50%) scale(1)' },
        },
        // `align="top"` uchun (⌘K paneli) — vertikal markazlashuv yo'q
        'dialog-in-top': {
          from: { opacity: '0', transform: 'translate(-50%, -8px) scale(.98)' },
          to: { opacity: '1', transform: 'translate(-50%, 0) scale(1)' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
        // Slide-over: faqat gorizontal siljish, markazlashuv yo'q
        'sheet-in': {
          from: { opacity: '0', transform: 'translateX(16px)' },
          to: { opacity: '1', transform: 'translateX(0)' },
        },
      },
      animation: {
        'pulse-dot': 'pulse-dot 2s infinite',
        'pulse-dot-slow': 'pulse-dot 2.4s infinite',
        'slide-down': 'slide-down .14s ease-out',
        'menu-in': 'slide-down .12s ease-out',
        'overlay-in': 'overlay-in .14s ease-out',
        'pop-in': 'pop-in .16s cubic-bezier(.2,.8,.3,1)',
        'dialog-in': 'dialog-in .16s cubic-bezier(.2,.8,.3,1)',
        'dialog-in-top': 'dialog-in-top .16s cubic-bezier(.2,.8,.3,1)',
        shimmer: 'shimmer 1.6s infinite',
        'sheet-in': 'sheet-in .18s cubic-bezier(.2,.8,.3,1)',
      },
    },
  },
  plugins: [require('tailwindcss-animate')],
}

export default config
