'use client'

import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { login } from '@/lib/auth'

/**
 * Kirish sahifasi — MOCK autentifikatsiya.
 *
 * Backend yo'q, shuning uchun istalgan email/parol ishlaydi. Shu holat
 * foydalanuvchiga OCHIQ aytiladi — aks holda "parolim ishladi" degan
 * yolg'on taassurot qoladi.
 */
export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  )
}

function LoginForm() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const next = searchParams.get('next') ?? '/dashboard'

  const [email, setEmail] = useState('jordan@durabl.dev')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [pending, setPending] = useState(false)

  const emailValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)
  const canSubmit = emailValid && password.length > 0 && !pending

  const onSubmit = async (event: React.FormEvent): Promise<void> => {
    event.preventDefault()
    setError(null)
    setPending(true)
    try {
      await login(email, password)
      router.push(next)
    } catch {
      setError('Could not sign in. Please try again.')
    } finally {
      setPending(false)
    }
  }

  return (
    <Card className="p-6">
      <h1 className="m-0 text-2xl font-semibold tracking-[-.02em] text-fg">Sign in</h1>
      <p className="mt-1.5 text-base text-fg-dim">
        Welcome back. Pick up where your jobs left off.
      </p>

      <div className="mt-4 rounded-lg border border-accent/25 bg-accent/[0.07] px-3.5 py-2.5 text-sm text-accent-pale">
        Demo mode — any email and password will sign you in. No backend is connected yet.
      </div>

      <form className="mt-5 flex flex-col gap-4" onSubmit={onSubmit}>
        <label className="flex flex-col gap-1.5">
          <span className="text-xs font-semibold uppercase tracking-[.05em] text-fg-faint">
            Email
          </span>
          <Input
            type="email"
            autoComplete="email"
            autoFocus
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            aria-invalid={email.length > 0 && !emailValid}
          />
          {email.length > 0 && !emailValid ? (
            <span className="text-xs text-failed">Enter a valid email address</span>
          ) : null}
        </label>

        <label className="flex flex-col gap-1.5">
          <span className="flex items-baseline">
            <span className="text-xs font-semibold uppercase tracking-[.05em] text-fg-faint">
              Password
            </span>
            <Link href="/login" className="ml-auto text-xs font-normal">
              Forgot password?
            </Link>
          </span>
          <Input
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="anything works in demo mode"
          />
        </label>

        {error ? (
          <div className="rounded-lg border border-failed/25 bg-failed/[0.08] px-3 py-2 text-sm text-failed-text">
            {error}
          </div>
        ) : null}

        <Button type="submit" variant="primary" size="lg" disabled={!canSubmit} className="justify-center">
          {pending ? 'Signing in…' : 'Sign in'}
        </Button>
      </form>

      <div className="mt-5 border-t border-line-inner pt-4 text-center text-sm text-fg-dim">
        New to Durabl?{' '}
        <Link href="/register" className="font-medium">
          Create an account
        </Link>
      </div>
    </Card>
  )
}
