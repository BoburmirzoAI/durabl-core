'use client'

import { cn } from '@/lib/utils/cn'
import type { FailureReason } from '@/types'

/**
 * Xato turiga qarab tuzatish maslahati.
 *
 * ## Nega bu bor
 *
 * DLQ "nima yiqildi" ni ko'rsatadi, lekin foydalanuvchiga "endi nima
 * qilay?" degan savol qoladi. Har bir `failure_reason` uchun ANIQ keyingi
 * qadam bor — uni taxmin qilishga majburlash vaqtni yo'qotadi.
 *
 * Maslahatlar `constants.FailureReason` bilan to'liq mos: yangi sabab
 * qo'shilsa, TypeScript bu yerda ham talab qiladi (`Record` to'liq bo'lishi
 * shart), ya'ni izohsiz qolib ketmaydi.
 */
interface Hint {
  /** Nima bo'ldi — bir jumlada. */
  cause: string
  /** Keyingi qadam. */
  action: string
  /** Qayta urinish foyda beradimi. */
  retryable: boolean
}

const HINTS: Record<FailureReason, Hint> = {
  non_zero_exit: {
    cause: "The code exited with a non-zero status — there is an unhandled exception inside.",
    action: "Read the last traceback line, fix the code and resubmit with 'Edit & retry'.",
    retryable: true,
  },
  timeout: {
    cause: "Execution exceeded the time limit and was killed.",
    action: "Find the slow path, or raise `timeout_seconds` (up to your plan limit).",
    retryable: true,
  },
  out_of_memory: {
    cause: "The container exceeded its memory limit and was OOM-killed (exit 137).",
    action: "Stream the input instead of loading it all, or raise `memory_mb`.",
    retryable: true,
  },
  sandbox_error: {
    cause: "The sandbox container failed to start — this is an infrastructure problem.",
    action: "This is not your code's fault. Retry; if it persists, contact support.",
    retryable: true,
  },
  validation_error: {
    cause: "The code was rejected BEFORE execution — a syntax or validation error.",
    action: "Retrying will NOT help. Fix the code and submit a new job.",
    retryable: false,
  },
  lease_lost: {
    cause: "The worker stopped sending heartbeats and its lease expired.",
    action: "The job was automatically re-queued. If this repeats, check the worker fleet health.",
    retryable: true,
  },
  max_retries_exceeded: {
    cause: "Every automatic retry was used, but the same error came back each time.",
    action: "Retrying without fixing the root cause is pointless — resolve the traceback first.",
    retryable: false,
  },
  internal_error: {
    cause: "An unexpected error occurred inside Durabl.",
    action: "This one is on us. Retry; if it persists, report it with the `request_id`.",
    retryable: true,
  },
  output_too_large: {
    cause: "The returned result or captured output exceeded the size limit.",
    action: "Trim the result, or write large data to external storage (S3) and return a link.",
    retryable: false,
  },
}

export function DlqFixHint({
  reason,
  className,
}: {
  reason: FailureReason
  className?: string
}) {
  const hint = HINTS[reason]
  if (!hint) return null

  return (
    <div
      className={cn(
        'rounded-lg border px-3.5 py-3',
        hint.retryable ? 'border-accent/20 bg-accent/[0.05]' : 'border-pending/25 bg-pending/[0.06]',
        className,
      )}
    >
      <div className="flex items-start gap-2.5">
        <svg
          width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round"
          className={cn('mt-0.5 shrink-0', hint.retryable ? 'text-accent-light' : 'text-pending')}
          aria-hidden
        >
          <path d="M9 18h6M10 22h4M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z" />
        </svg>
        <div className="min-w-0 text-sm">
          <div className="text-fg-soft">{hint.cause}</div>
          <div className="mt-1 text-fg-dim">{hint.action}</div>
          {!hint.retryable ? (
            <div className="mt-1.5 inline-flex items-center gap-1.5 rounded-md bg-pending/[0.14] px-2 py-0.5 text-2xs font-semibold text-pending">
              Retrying will not help
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}

/** Boshqa joylarda ishlatish uchun (masalan admin DLQ root-cause paneli). */
export function fixHintFor(reason: FailureReason): Hint | undefined {
  return HINTS[reason]
}
