'use client'

import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils/cn'
import { register } from '@/lib/auth'

/** Ro'yxatdan o'tish — MOCK (backend yo'q). */
export default function RegisterPage() {
  const router = useRouter()

  const [fullName, setFullName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
  // Backend `validate_password_strength` ayni qoidalarni tekshiradi
  const checks = [
    { label: 'At least 8 characters', ok: password.length >= 8 },
    { label: 'Contains a letter', ok: /[a-z]/i.test(password) },
    { label: 'Contains a number', ok: /\d/.test(password) },
  ]
  const score = checks.filter((c) => c.ok).length
  const mismatch = confirm.length > 0 && password !== confirm
  const canSubmit = emailValid && score === checks.length && !mismatch && !pending

  const onSubmit = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault()
    setError(null)
    setPending(true)
    try {
      await register(email, password, fullName || undefined)
      router.push('/dashboard')
    } catch {
      setError('Could not create your account. Please try again.')
    } finally {
      setPending(false)
    }
  }

  return (
    <Card className="p-6">
      <h1 className="m-0 text-2xl font-semibold tracking-[-.02em] text-fg">Create account</h1>
      <p className="mt-1.5 text-base text-fg-dim">
        Free plan includes 1,000 jobs a month. No card required.
      </p>

      <div className="mt-4 rounded-lg border border-accent/25 bg-accent/[0.07] px-3.5 py-2.5 text-sm text-accent-pale">
        Demo mode — nothing is sent to a server. You will be signed in locally.
      </div>

      <form className="mt-5 flex flex-col gap-4" onSubmit={onSubmit}>
        <label className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold uppercase tracking-[.05em] text-fg-faint">
            Full name
          </span>
          <Input
            autoFocus
            autoComplete="name"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            placeholder="Jordan Diaz"
          />
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold uppercase tracking-[.05em] text-fg-faint">
            Email
          </span>
          <Input
            type="email"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            aria-invalid={email.length > 0 && !emailValid}
          />
          {email.length > 0 && !emailValid ? (
            <span className="text-xs text-failed">Enter a valid email address</span>
          ) : null}
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold uppercase tracking-[.05em] text-fg-faint">
            Password
          </span>
          <Input
            type="password"
            autoComplete="new-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          {password.length > 0 ? (
            <span className="flex flex-col gap-1.5">
              <span className="flex gap-1">
                {checks.map((check, i) => (
                  <span
                    key={check.label}
                    className={cn(
                      'h-1 flex-1 rounded-sm',
                      i < score ? (score === 3 ? 'bg-success' : 'bg-pending') : 'bg-line',
                    )}
                  />
                ))}
              </span>
              {checks
                .filter((check) => !check.ok)
                .map((check) => (
                  <span key={check.label} className="text-xs text-fg-faint">
                    ○ {check.label}
                  </span>
                ))}
            </span>
          ) : null}
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold uppercase tracking-[.05em] text-fg-faint">
            Confirm password
          </span>
          <Input
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(event) => setConfirm(event.target.value)}
            aria-invalid={mismatch}
          />
          {mismatch ? <span className="text-xs text-failed">Passwords do not match</span> : null}
        </label>

        {error ? (
          <div className="rounded-lg border border-failed/25 bg-failed/[0.08] px-3 py-2 text-sm text-failed-text">
            {error}
          </div>
        ) : null}

        <Button type="submit" variant="primary" size="lg" disabled={!canSubmit} className="justify-center">
          {pending ? 'Creating account…' : 'Create account'}
        </Button>
      </form>

      <div className="mt-5 border-t border-line-inner pt-4 text-center text-sm text-fg-dim">
        Already have an account?{' '}
        <Link href="/login" className="font-medium">
          Sign in
        </Link>
      </div>
    </Card>
  )
}
