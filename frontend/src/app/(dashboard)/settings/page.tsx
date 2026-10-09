'use client'

import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card, CardTitle } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { Input } from '@/components/ui/input'
import { SectionHeader } from '@/components/common/SectionHeader'
import { Switch } from '@/components/ui/switch'
import { Tabs } from '@/components/ui/tabs'
import { ApiDefaultsPanel } from '@/components/settings/ApiDefaultsPanel'
import { LoginHistoryPanel } from '@/components/settings/LoginHistoryPanel'
import { NotificationMatrix } from '@/components/settings/NotificationMatrix'
import { SessionsPanel } from '@/components/settings/SessionsPanel'
import { TeamPanel } from '@/components/settings/TeamPanel'
import { TwoFactorPanel } from '@/components/settings/TwoFactorPanel'
import { useToast } from '@/components/common/ToastProvider'
import { currentUser, logout } from '@/lib/auth'
import { cn } from '@/lib/utils/cn'
import { formatDate } from '@/lib/utils/time'
import { useUiStore } from '@/stores/uiStore'
import type { UserPreferences } from '@/types'

type TabValue =
  | 'profile'
  | 'security'
  | 'team'
  | 'preferences'
  | 'notifications'
  | 'defaults'
  | 'danger'

const TABS = [
  { value: 'profile' as TabValue, label: 'Profile' },
  { value: 'security' as TabValue, label: 'Security' },
  { value: 'team' as TabValue, label: 'Team' },
  { value: 'preferences' as TabValue, label: 'Preferences' },
  { value: 'notifications' as TabValue, label: 'Notifications' },
  { value: 'defaults' as TabValue, label: 'Job defaults' },
  { value: 'danger' as TabValue, label: 'Danger zone' },
] as const

/**
 * Sozlamalar.
 *
 * ## Tablar nega shu tartibda
 *
 * `profile` → `security` → `team`: shaxsiy, keyin himoya, keyin
 * boshqalar. So'ng kundalik ishga tegishli `preferences`,
 * `notifications`, `defaults`. `danger` oxirida — tasodifan bosilmasligi
 * uchun.
 *
 * ## Nima haqiqatan ishlaydi
 *
 * `preferences` → `uiStore` (UI darhol o'zgaradi).
 * `security` (sessiyalar, 2FA), `team`, `notifications`, `defaults` →
 * mock do'konlar; o'zgarish saqlanadi va sahifalar orasida yurganda
 * yo'qolmaydi. Parol almashtirish esa faqat toast ko'rsatadi, chunki
 * mock qatlamida saqlanadigan parol yo'q.
 */
export default function SettingsPage() {
  const [tab, setTab] = useState<TabValue>('profile')
  const user = currentUser()

  return (
    <>
      <SectionHeader title="Settings" description={user.email} />

      <Card className="overflow-hidden">
        <div className="border-b border-line-inner">
          <Tabs aria-label="Settings sections" variant="underline" items={TABS} value={tab} onChange={setTab} />
        </div>

        <div className="p-5">
          {tab === 'profile' ? <ProfileTab /> : null}
          {tab === 'security' ? <SecurityTab /> : null}
          {tab === 'team' ? <TeamPanel /> : null}
          {tab === 'preferences' ? <PreferencesTab /> : null}
          {tab === 'notifications' ? (
            <div className="space-y-4">
              <NotificationsTab />
              <NotificationMatrix />
            </div>
          ) : null}
          {tab === 'defaults' ? <ApiDefaultsPanel /> : null}
          {tab === 'danger' ? <DangerTab /> : null}
        </div>
      </Card>
    </>
  )
}

/** Avatar ranglari — brend palitrasidan, matn kontrasti tekshirilgan. */
const AVATAR_COLORS = [
  { key: 'accent', label: 'Violet', className: 'bg-accent/[0.18] text-accent-light' },
  { key: 'success', label: 'Green', className: 'bg-success/[0.16] text-success' },
  { key: 'pending', label: 'Amber', className: 'bg-pending/[0.16] text-pending' },
  { key: 'failed', label: 'Red', className: 'bg-failed/[0.16] text-failed' },
  { key: 'neutral', label: 'Grey', className: 'bg-surface-4 text-fg-soft' },
] as const

/** Ism yoki emaildan bosh harflarni oladi. */
function initialsOf(name: string, email: string): string {
  const source = name.trim() || email
  return source
    .split(/[\s@._-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => (part[0] ?? '').toUpperCase())
    .join('')
}

function ProfileTab() {
  const user = currentUser()
  const { toast } = useToast()
  const preferences = useUiStore((s) => s.preferences)
  const setPreference = useUiStore((s) => s.setPreference)

  const [fullName, setFullName] = useState(user.full_name ?? '')
  const [company, setCompany] = useState('')
  const [color, setColor] = useState<string>(preferences.avatar_color)

  const initials = initialsOf(fullName, user.email)
  const swatch =
    AVATAR_COLORS.find((c) => c.key === color) ?? (AVATAR_COLORS[0] as (typeof AVATAR_COLORS)[number])

  return (
    <form
      className="flex max-w-[520px] flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault()
        // Rang HAQIQATAN saqlanadi (uiStore) — u butun interfeysdagi
        // avatarga ta'sir qiladi. Ism va kompaniya esa backend talab
        // qiladi, shuning uchun hozircha faqat tasdiq ko'rsatiladi.
        setPreference('avatar_color', swatch.key)
        toast({
          title: 'Profile saved',
          description: fullName.trim() || user.email,
          variant: 'success',
        })
      }}
    >
      <div className="flex flex-wrap items-center gap-4 rounded-xl border border-line bg-surface-2 p-4">
        <span
          className={cn(
            'flex h-14 w-14 shrink-0 items-center justify-center rounded-full text-base font-semibold',
            swatch.className,
          )}
        >
          {initials || '—'}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-base text-fg-soft">Avatar</div>
          <p className="mt-0.5 text-sm text-fg-faint">
            Durabl uses initials rather than uploaded images — nothing to moderate, nothing to
            host. Pick the colour.
          </p>
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {AVATAR_COLORS.map((option) => (
              <button
                key={option.key}
                type="button"
                aria-label={option.label}
                aria-pressed={color === option.key}
                onClick={() => setColor(option.key)}
                className={cn(
                  'flex h-7 w-7 items-center justify-center rounded-full text-2xs font-semibold ring-offset-2 ring-offset-surface-2 transition-shadow',
                  option.className,
                  color === option.key && 'ring-2 ring-accent',
                )}
              >
                {initials.slice(0, 1) || '·'}
              </button>
            ))}
          </div>
        </div>
      </div>

      <Field label="Full name">
        <Input value={fullName} onChange={(event) => setFullName(event.target.value)} />
      </Field>
      <Field label="Company" hint="Shown on invoices">
        <Input
          value={company}
          onChange={(event) => setCompany(event.target.value)}
          placeholder="Acme Inc."
        />
      </Field>
      <Field label="Email" hint="Contact support to change your email">
        <Input value={user.email} readOnly className="cursor-not-allowed text-fg-muted" />
      </Field>
      <Field
        label="Member since"
        hint="Timestamps across Durabl are shown in UTC"
      >
        <Input value={formatDate(user.created_at)} readOnly className="cursor-not-allowed text-fg-muted" />
      </Field>
      <div>
        <Button type="submit" variant="primary" size="md">
          Save changes
        </Button>
      </div>
    </form>
  )
}

function SecurityTab() {
  const user = currentUser()
  return (
    <div className="space-y-4">
      <PasswordForm />
      <TwoFactorPanel email={user.email} />
      <SessionsPanel />
      <LoginHistoryPanel />
    </div>
  )
}

function PasswordForm() {
  const { toast } = useToast()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')

  // Parol mustahkamligi — oddiy, lekin foydali ko'rsatkich
  const checks = [
    { label: 'At least 8 characters', ok: next.length >= 8 },
    { label: 'Contains a letter', ok: /[a-z]/i.test(next) },
    { label: 'Contains a number', ok: /\d/.test(next) },
  ]
  const score = checks.filter((c) => c.ok).length
  const mismatch = confirm.length > 0 && next !== confirm
  const canSubmit = current.length > 0 && score === checks.length && !mismatch

  return (
    <form
      className="flex max-w-[460px] flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault()
        toast({ title: 'Password updated', variant: 'success' })
        setCurrent('')
        setNext('')
        setConfirm('')
      }}
    >
      <Field label="Current password">
        <Input
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(event) => setCurrent(event.target.value)}
        />
      </Field>
      <Field label="New password">
        <Input
          type="password"
          autoComplete="new-password"
          value={next}
          onChange={(event) => setNext(event.target.value)}
        />
      </Field>

      {next.length > 0 ? (
        <div className="flex flex-col gap-1.5">
          <div className="flex gap-1">
            {checks.map((check, i) => (
              <span
                key={check.label}
                className={cn(
                  'h-1 flex-1 rounded-sm',
                  i < score ? (score === 3 ? 'bg-success' : 'bg-pending') : 'bg-line',
                )}
              />
            ))}
          </div>
          {checks.map((check) => (
            <span
              key={check.label}
              className={cn('text-xs', check.ok ? 'text-success' : 'text-fg-faint')}
            >
              {check.ok ? '✓' : '○'} {check.label}
            </span>
          ))}
        </div>
      ) : null}

      <Field label="Confirm new password" error={mismatch ? 'Passwords do not match' : null}>
        <Input
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
        />
      </Field>

      <div>
        <Button type="submit" variant="primary" size="md" disabled={!canSubmit}>
          Update password
        </Button>
      </div>
    </form>
  )
}

function PreferencesTab() {
  const preferences = useUiStore((s) => s.preferences)
  const setPreference = useUiStore((s) => s.setPreference)

  return (
    <div className="flex max-w-[560px] flex-col gap-1">
      <Toggle
        label="Auto-refresh lists"
        description="Poll job and execution lists while active jobs are running."
        checked={preferences.auto_refresh}
        onChange={(value) => setPreference('auto_refresh', value)}
      />
      <Toggle
        label="Show log timestamps"
        description="Display per-line timestamps in the log viewer."
        checked={preferences.show_log_timestamps}
        onChange={(value) => setPreference('show_log_timestamps', value)}
      />
      <div className="flex items-start justify-between gap-6 border-b border-line-subtle py-3.5 last:border-b-0">
        <div className="min-w-0">
          <div className="text-base text-fg-soft">Table density</div>
          <div className="mt-0.5 text-sm text-fg-faint">
            Compact fits more rows; comfortable adds breathing room.
          </div>
        </div>
        <Tabs
          aria-label="Table density"
          items={[
            { value: 'compact' as UserPreferences['density'], label: 'Compact' },
            { value: 'comfortable' as UserPreferences['density'], label: 'Comfortable' },
          ]}
          value={preferences.density}
          onChange={(value) => setPreference('density', value)}
        />
      </div>
      <div className="flex items-start justify-between gap-6 py-3.5">
        <div className="min-w-0">
          <div className="text-base text-fg-soft">Theme</div>
          <div className="mt-0.5 text-sm text-fg-faint">
            Durabl is dark-only — a light theme is on the roadmap.
          </div>
        </div>
        <span className="shrink-0 rounded-md border border-line bg-surface-2 px-2.5 py-1 text-sm text-fg-muted">
          Dark
        </span>
      </div>
    </div>
  )
}

function NotificationsTab() {
  const preferences = useUiStore((s) => s.preferences)
  const setPreference = useUiStore((s) => s.setPreference)

  return (
    <div className="flex max-w-[560px] flex-col gap-1">
      <Toggle
        label="DLQ threshold alerts"
        description="Notify me when the dead letter queue exceeds the configured threshold."
        checked={preferences.notify_dlq_threshold}
        onChange={(value) => setPreference('notify_dlq_threshold', value)}
      />
      <Toggle
        label="Job failure alerts"
        description="Notify me every time a job fails. Noisy on high volume."
        checked={preferences.notify_job_failed}
        onChange={(value) => setPreference('notify_job_failed', value)}
      />
      <div className="mt-3 rounded-lg border border-line-inner bg-canvas-deep px-3.5 py-3 text-sm text-fg-faint">
        These two switches control the in-app bell. Per-event delivery across email, in-app and
        webhook is configured below.
      </div>
    </div>
  )
}

function DangerTab() {
  const router = useRouter()
  const { toast } = useToast()
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [typed, setTyped] = useState('')

  return (
    <>
      <div className="flex max-w-[560px] flex-col gap-4">
        <Card className="border-failed/25 p-4">
          <CardTitle className="text-md text-failed">Deactivate account</CardTitle>
          <p className="mt-1.5 text-sm text-fg-muted">
            Your account is deactivated, not deleted: job history and invoices are retained so you
            can still audit past runs. Running jobs are cancelled and API keys stop working
            immediately.
          </p>
          <div className="mt-4">
            <Button variant="danger" size="md" onClick={() => setConfirmOpen(true)}>
              Deactivate my account
            </Button>
          </div>
        </Card>
      </div>

      <ConfirmDialog
        open={confirmOpen}
        onOpenChange={(open) => {
          setConfirmOpen(open)
          if (!open) setTyped('')
        }}
        title="Deactivate account?"
        description="Type DEACTIVATE to confirm. You will be signed out immediately."
        confirmLabel={typed === 'DEACTIVATE' ? 'Deactivate' : 'Type DEACTIVATE'}
        destructive
        onConfirm={() => {
          if (typed !== 'DEACTIVATE') return
          toast({ title: 'Account deactivated' })
          logout()
          router.push('/login')
        }}
      >
        <Input
          autoFocus
          value={typed}
          onChange={(event) => setTyped(event.target.value.toUpperCase())}
          placeholder="DEACTIVATE"
          className="font-mono"
          aria-label="Type DEACTIVATE to confirm"
        />
      </ConfirmDialog>
    </>
  )
}

function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string
  hint?: string
  error?: string | null
  children: React.ReactNode
}) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="flex items-baseline gap-2">
        <span className="text-xs font-semibold uppercase tracking-[.05em] text-fg-faint">
          {label}
        </span>
        {hint ? <span className="text-xs text-fg-faint">{hint}</span> : null}
      </span>
      {children}
      {error ? <span className="text-xs text-failed">{error}</span> : null}
    </label>
  )
}

function Toggle({
  label,
  description,
  checked,
  onChange,
}: {
  label: string
  description: string
  checked: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <div className="flex items-start justify-between gap-6 border-b border-line-subtle py-3.5">
      <div className="min-w-0">
        <div className="text-base text-fg-soft">{label}</div>
        <div className="mt-0.5 text-sm text-fg-faint">{description}</div>
      </div>
      <Switch checked={checked} onCheckedChange={onChange} aria-label={label} />
    </div>
  )
}
