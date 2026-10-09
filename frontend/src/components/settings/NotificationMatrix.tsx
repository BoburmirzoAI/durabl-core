'use client'

import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Skeleton } from '@/components/ui/skeleton'
import { useNotificationSettings, useUpdateNotificationSetting } from '@/lib/hooks/useAccount'
import type { NotificationSetting } from '@/types'

const GRID = 'minmax(220px,1fr) 70px 70px 78px'

const CHANNELS = [
  { key: 'in_app' as const, label: 'In-app' },
  { key: 'email' as const, label: 'Email' },
  { key: 'webhook' as const, label: 'Webhook' },
]

/**
 * Hodisa × kanal matritsasi.
 *
 * ## Nega matritsa, ketma-ket almashtirgichlar emas
 *
 * Har bir hodisa uchun uchta kanal bor — bu 24 ta almashtirgich degani.
 * Ro'yxat ko'rinishida ular bir-biriga qo'shilib ketadi va "qaysi hodisa
 * emailga boradi?" degan savolga javob topish qiyin. Matritsa bir
 * qarashda butun sxemani ko'rsatadi.
 *
 * ## Nega darhol saqlanadi
 *
 * "Saqlash" tugmasi bu yerda keraksiz: har bir katak mustaqil va xato
 * qilsa darhol qaytarish mumkin. Sozlamalar sahifasida tasdiqlash
 * bosqichi faqat QAYTARIB BO'LMAYDIGAN amallar uchun.
 */
export function NotificationMatrix() {
  const settings = useNotificationSettings()
  const update = useUpdateNotificationSetting()

  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">Notification rules</CardTitle>
        <CardDescription>
          Pick where each event is delivered. Webhook rows go to every endpoint subscribed to the
          matching event.
        </CardDescription>
      </CardHeader>

      <div className="table-head grid items-center gap-3 px-4" style={{ gridTemplateColumns: GRID }}>
        <span>Event</span>
        {CHANNELS.map((channel) => (
          <span key={channel.key} className="text-center">
            {channel.label}
          </span>
        ))}
      </div>

      {settings.isLoading && !settings.data ? (
        <div className="space-y-2 p-4">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-9 w-full" />
          ))}
        </div>
      ) : (
        (settings.data ?? []).map((row) => (
          <Row key={row.event} row={row} onToggle={(channel, enabled) => update.mutate({ event: row.event, channel, enabled })} />
        ))
      )}
    </Card>
  )
}

function Row({
  row,
  onToggle,
}: {
  row: NotificationSetting
  onToggle: (channel: 'email' | 'in_app' | 'webhook', enabled: boolean) => void
}) {
  return (
    <div
      className="grid min-h-[52px] items-center gap-3 border-b border-line-subtle px-4 py-2 last:border-b-0 hover:bg-surface-3"
      style={{ gridTemplateColumns: GRID }}
    >
      <span className="min-w-0">
        <span className="flex items-center gap-2">
          <span className="truncate text-base text-fg-soft">{row.label}</span>
          {row.noisy ? (
            <span className="shrink-0 rounded border border-pending/25 px-1.5 py-px text-2xs text-pending">
              noisy
            </span>
          ) : null}
        </span>
        <span className="mt-0.5 block text-xs leading-[1.5] text-fg-faint">{row.description}</span>
      </span>

      {CHANNELS.map((channel) => (
        <span key={channel.key} className="flex justify-center">
          <Checkbox
            checked={row[channel.key]}
            onToggle={() => onToggle(channel.key, !row[channel.key])}
            aria-label={`${row.label} via ${channel.label}`}
          />
        </span>
      ))}
    </div>
  )
}
