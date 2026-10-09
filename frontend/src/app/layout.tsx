import type { Metadata, Viewport } from 'next'
import { Inter, JetBrains_Mono } from 'next/font/google'

import { Providers } from '@/components/providers'

import './globals.css'

/**
 * Shriftlar — dizaynda Inter (UI) va JetBrains Mono (ID, raqam, kod).
 * `next/font` ularni o'zi joylashtiradi (tashqi so'rov yo'q, CLS yo'q).
 */
const inter = Inter({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-inter',
  display: 'swap',
})

const mono = JetBrains_Mono({
  subsets: ['latin'],
  weight: ['400', '500', '600'],
  variable: '--font-mono',
  display: 'swap',
})

export const metadata: Metadata = {
  title: {
    default: 'Durabl — Reliable background jobs',
    template: '%s · Durabl',
  },
  description:
    'Durabl runs your background jobs reliably: durable queues, idempotency, gVisor isolation, automatic retries and a dead letter queue you can actually act on.',
  applicationName: 'Durabl',
  openGraph: {
    title: 'Durabl — Reliable background jobs',
    description: 'Durable queues, idempotency, gVisor isolation and a DLQ you can act on.',
    type: 'website',
  },
}

export const viewport: Viewport = {
  // Faqat qorong'u mavzu — brauzer UI ham moslashadi
  colorScheme: 'dark',
  themeColor: '#0A0A0B',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${mono.variable}`} suppressHydrationWarning>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  )
}
