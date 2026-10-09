'use client'

import { useState } from 'react'

import { CopyButton } from '@/components/common/CopyButton'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { DetailDrawer, DrawerRow, DrawerSection } from '@/components/common/DetailDrawer'
import { RelativeTime } from '@/components/common/RelativeTime'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { useApiKeyUsage, useRevokeApiKey, useUpdateApiKeyExpiry } from '@/lib/hooks/useApiKeys'
import { formatNumber } from '@/lib/utils/format'
import { formatDate, formatTimestamp } from '@/lib/utils/time'
import type { ApiKey, ApiKeyEndpointUsage } from '@/types'

import { KeyUsageChart } from './KeyUsageChart'
import { ScopeEditor } from './ScopeEditor'

/**
 * Kalit tafsiloti paneli.
 *
 * ## Bu panel qanday savollarga javob beradi
 *
 * 1. **"Bu kalit ishlatilyaptimi?"** — 30 kunlik grafik va bugungi son.
 *    Ishlatilmaydigan kalitni bekor qilish kerak, lekin buni bilish uchun
 *    dalil kerak.
 * 2. **"Kalit nima qilyapti?"** — eng ko'p urilgan endpointlar. CI kaliti
 *    birdan `/dlq/{id}/retry` urishni boshlasa — nimadir noto'g'ri.
 * 3. **"Kalit o'g'irlanganmi?"** — oxirgi IP, turli IP'lar soni, user-agent.
 * 4. **"Nima qila olaman?"** — huquqlarni toraytirish, muddat qo'yish,
 *    almashtirish, bekor qilish. Hammasi shu panelda.
 *
 * ## Nega panel, sahifa emas
 *
 * Kalitlar ro'yxati qisqa va foydalanuvchi ularni SOLISHTIRADI. Sahifaga
 * o'tish kontekstni yo'qotadi; panel ortidagi jadval ko'rinib turadi.
 */
export function KeyDetailDrawer({
  apiKey,
  onOpenChange,
  onRotate,
}: {
  apiKey: ApiKey | null
  onOpenChange: (open: boolean) => void
  onRotate: (apiKey: ApiKey) => void
}) {
  const usage = useApiKeyUsage(apiKey?.id ?? null)
  const expiry = useUpdateApiKeyExpiry()
  const revoke = useRevokeApiKey()
  const [confirmRevoke, setConfirmRevoke] = useState(false)

  const expired = Boolean(apiKey?.expires_at && new Date(apiKey.expires_at) < new Date())
  const revoked = Boolean(apiKey?.revoked_at)
  const data = usage.data

  // Ogohlantirish shartlari — har biri alohida sabab bilan ko'rsatiladi
  const stale =
    apiKey?.is_active &&
    apiKey.last_used_at !== null &&
    Date.now() - new Date(apiKey.last_used_at).getTime() > 30 * 86_400_000
  const neverUsed = apiKey?.is_active && apiKey.last_used_at === null
  const manyIps = (data?.distinct_ips ?? 0) > 4

  return (
    <>
      <DetailDrawer
        open={apiKey !== null}
        onOpenChange={onOpenChange}
        width="lg"
        title={
          <span className="flex min-w-0 items-center gap-2.5">
            <span className="truncate">{apiKey?.name}</span>
            {revoked ? (
              <Badge variant="danger">Revoked</Badge>
            ) : expired ? (
              <Badge className="bg-pending/[0.12] text-pending">Expired</Badge>
            ) : (
              <Badge variant="success">Active</Badge>
            )}
          </span>
        }
        description={
          <span className="flex items-center gap-1.5">
            <code className="font-mono text-xs text-fg-muted">{apiKey?.masked_key}</code>
            {apiKey ? <CopyButton value={apiKey.key_prefix} label="Key prefix" silent /> : null}
          </span>
        }
        stats={
          data
            ? [
                { label: 'Requests 30d', value: formatNumber(data.requests_30d) },
                { label: 'Today', value: formatNumber(data.requests_today) },
                {
                  label: 'Error rate',
                  value: `${data.error_rate}%`,
                  tone: data.error_rate > 5 ? 'bad' : data.error_rate > 1 ? 'warn' : 'good',
                },
                {
                  label: 'Rate limited',
                  value: formatNumber(data.rate_limited_30d),
                  tone: data.rate_limited_30d > 0 ? 'warn' : 'default',
                },
              ]
            : undefined
        }
        loading={usage.isLoading}
        error={usage.error}
        onRetry={() => void usage.refetch()}
        footer={
          apiKey ? (
            <div className="flex w-full flex-wrap items-center gap-2">
              <span className="min-w-0 flex-1 text-xs text-fg-faint">
                Created {formatDate(apiKey.created_at)}
              </span>
              <Button variant="ghost" onClick={() => onOpenChange(false)}>
                Close
              </Button>
              <Button
                variant="secondary"
                disabled={revoked}
                onClick={() => onRotate(apiKey)}
                title={revoked ? 'Revoked keys cannot be rotated' : undefined}
              >
                Rotate key
              </Button>
              <Button variant="danger" disabled={revoked} onClick={() => setConfirmRevoke(true)}>
                Revoke
              </Button>
            </div>
          ) : null
        }
      >
        {apiKey && data ? (
          <div className="space-y-3.5">
            {/* Ogohlantirishlar — faqat haqiqatan muhim bo'lsa ko'rinadi */}
            {neverUsed ? (
              <Notice tone="warn">
                This key has never been used. If you created it by mistake, revoke it.
              </Notice>
            ) : null}
            {stale ? (
              <Notice tone="warn">
                Last used{' '}
                {Math.round(
                  (Date.now() - new Date(apiKey.last_used_at as string).getTime()) / 86_400_000,
                )}{' '}
                days ago. Unused keys are the easiest ones to leak.
              </Notice>
            ) : null}
            {manyIps ? (
              <Notice tone="bad">
                Used from {data.distinct_ips} different IP addresses in the last 30 days. If you
                did not expect that, rotate the key.
              </Notice>
            ) : null}

            <KeyUsageChart daily={data.daily} />

            <DrawerSection title="Top endpoints">
              {data.top_endpoints.length === 0 ? (
                <p className="text-sm text-fg-dim">No traffic recorded for this key.</p>
              ) : (
                <div className="space-y-px">
                  {data.top_endpoints.map((row) => (
                    <EndpointRow key={`${row.method} ${row.path}`} row={row} max={data.top_endpoints[0]?.requests ?? 1} />
                  ))}
                </div>
              )}
            </DrawerSection>

            <DrawerSection title="Permissions">
              <ScopeEditor apiKey={apiKey} />
            </DrawerSection>

            <DrawerSection
              title="Expiry"
              action={
                apiKey.expires_at && !revoked ? (
                  <Button
                    variant="link"
                    size="sm"
                    disabled={expiry.isPending}
                    onClick={() => expiry.mutate({ id: apiKey.id, expiresInDays: null })}
                  >
                    Remove expiry
                  </Button>
                ) : null
              }
            >
              <p className="text-sm text-fg-dim">
                {apiKey.expires_at
                  ? expired
                    ? `Expired ${formatDate(apiKey.expires_at)}. Rotate the key to issue a new one.`
                    : `Expires ${formatTimestamp(apiKey.expires_at)}.`
                  : 'This key never expires. Short-lived keys limit the damage of a leak.'}
              </p>
              {!revoked ? (
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  <span className="text-xs text-fg-faint">Set expiry to</span>
                  {[7, 30, 90, 365].map((days) => (
                    <Button
                      key={days}
                      variant="outline"
                      size="sm"
                      disabled={expiry.isPending}
                      onClick={() => expiry.mutate({ id: apiKey.id, expiresInDays: days })}
                    >
                      {days === 365 ? '1 year' : `${days}d`}
                    </Button>
                  ))}
                </div>
              ) : null}
            </DrawerSection>

            <DrawerSection title="Last seen">
              <DrawerRow
                label="Last used"
                value={<RelativeTime value={apiKey.last_used_at} />}
              />
              <DrawerRow label="IP address" value={data.last_ip ?? '—'} mono />
              <DrawerRow label="Client" value={data.last_user_agent ?? '—'} mono />
              <DrawerRow
                label="Distinct IPs (30d)"
                value={formatNumber(data.distinct_ips)}
              />
              <DrawerRow label="Key prefix" value={apiKey.key_prefix} mono />
              {apiKey.revoked_at ? (
                <DrawerRow label="Revoked" value={formatTimestamp(apiKey.revoked_at)} />
              ) : null}
            </DrawerSection>
          </div>
        ) : null}
      </DetailDrawer>

      <ConfirmDialog
        open={confirmRevoke}
        onOpenChange={setConfirmRevoke}
        title="Revoke API key?"
        description={
          apiKey
            ? `Any client using "${apiKey.name}" will immediately start receiving 401 responses. This cannot be undone — rotate instead if you just need a new secret.`
            : ''
        }
        confirmLabel="Revoke key"
        destructive
        pending={revoke.isPending}
        onConfirm={() => {
          if (apiKey) revoke.mutate(apiKey.id)
          setConfirmRevoke(false)
          onOpenChange(false)
        }}
      />
    </>
  )
}

const METHOD_CLASS: Record<ApiKeyEndpointUsage['method'], string> = {
  GET: 'text-success',
  POST: 'text-accent',
  PUT: 'text-pending',
  DELETE: 'text-failed',
}

/** Endpoint qatori — ulush ustun sifatida orqa fonda ko'rinadi. */
function EndpointRow({ row, max }: { row: ApiKeyEndpointUsage; max: number }) {
  const share = max === 0 ? 0 : (row.requests / max) * 100
  return (
    <div className="relative overflow-hidden rounded-md px-2 py-1.5">
      <div
        className="absolute inset-y-0 left-0 bg-accent/[0.07]"
        style={{ width: `${share}%` }}
        aria-hidden
      />
      <div className="relative flex items-center gap-2.5">
        <span className={`w-[46px] shrink-0 font-mono text-2xs font-semibold ${METHOD_CLASS[row.method]}`}>
          {row.method}
        </span>
        <span className="min-w-0 flex-1 truncate font-mono text-xs text-fg-soft" title={row.path}>
          {row.path}
        </span>
        <span className="tabular shrink-0 font-mono text-xs text-fg-muted">
          {formatNumber(row.requests)}
        </span>
        <span
          className={`tabular w-[46px] shrink-0 text-right font-mono text-2xs ${
            row.error_rate > 2 ? 'text-failed-text' : 'text-fg-faint'
          }`}
        >
          {row.error_rate}%
        </span>
      </div>
    </div>
  )
}

function Notice({ tone, children }: { tone: 'warn' | 'bad'; children: React.ReactNode }) {
  const cls =
    tone === 'bad'
      ? 'border-failed/25 bg-failed/[0.07] text-failed-text'
      : 'border-pending/25 bg-pending/[0.07] text-pending'
  return (
    <div className={`rounded-lg border px-3.5 py-2.5 text-sm leading-[1.55] ${cls}`}>
      {children}
    </div>
  )
}
