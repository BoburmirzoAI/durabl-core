/**
 * Holat -> rang/yorliq moslashuvi.
 *
 * Ranglar `design-reference` dagi `ST` jadvalidan AYNAN olingan:
 *   success #22C55E, running #3B82F6, failed #EF4444,
 *   pending #EAB308, queued #A1A1AA
 * Nishon foni — shu rangning 12% shaffofligi (dizaynda `rgba(...,.12)`).
 *
 * DIQQAT: klass nomlari LITERAL yozilgan. Tailwind JIT dinamik qurilgan
 * nomni (`text-${token}`) manbada ko'rmaydi va CSS'ga chiqarmaydi, shuning
 * uchun har bir klass to'liq matn sifatida turishi SHART.
 */

import type { CSSProperties } from 'react'

import type {
  DeliveryStatus,
  ExecutionStatus,
  FailureReason,
  JobStatus,
  Runtime,
  WorkerState,
} from '@/types'

export interface StatusStyle {
  /** Matn rangi klassi. */
  text: string
  /** Nishon foni klassi. */
  bg: string
  /** Chegara klassi (katta nishonlar uchun). */
  border: string
  /** Nuqta foni klassi. */
  dot: string
  /** Inson o'qiydigan yorliq. */
  label: string
  /** Jonli holat — nuqta pulsatsiya qiladi. */
  live: boolean
  /** Pulsatsiya rangi uchun CSS o'zgaruvchi nomi. */
  pulseToken: string
}

const SUCCESS: StatusStyle = {
  text: 'text-success',
  bg: 'bg-success/[0.12]',
  border: 'border-success/25',
  dot: 'bg-success',
  label: 'Success',
  live: false,
  pulseToken: 'success',
}
const RUNNING: StatusStyle = {
  text: 'text-running',
  bg: 'bg-running/[0.12]',
  border: 'border-running/25',
  dot: 'bg-running',
  label: 'Running',
  live: true,
  pulseToken: 'running',
}
const FAILED: StatusStyle = {
  text: 'text-failed',
  bg: 'bg-failed/[0.12]',
  border: 'border-failed/25',
  dot: 'bg-failed',
  label: 'Failed',
  live: false,
  pulseToken: 'failed',
}
const PENDING: StatusStyle = {
  text: 'text-pending',
  bg: 'bg-pending/[0.12]',
  border: 'border-pending/25',
  dot: 'bg-pending',
  label: 'Pending',
  live: false,
  pulseToken: 'pending',
}
const QUEUED: StatusStyle = {
  text: 'text-queued',
  bg: 'bg-queued/[0.12]',
  border: 'border-queued/25',
  dot: 'bg-queued',
  label: 'Queued',
  live: false,
  pulseToken: 'queued',
}
const NEUTRAL: StatusStyle = {
  text: 'text-fg-dim',
  bg: 'bg-fg-dim/[0.12]',
  border: 'border-fg-dim/25',
  dot: 'bg-fg-dim',
  label: 'Cancelled',
  live: false,
  pulseToken: 'fg-dim',
}

/** Yorliq va jonlilikni almashtirib, ayni uslubdan nusxa oladi. */
const relabel = (base: StatusStyle, label: string, live = base.live): StatusStyle => ({
  ...base,
  label,
  live,
})

/**
 * Job holatlari.
 *
 * Dizaynda beshta holat ko'rsatilgan. Qolgan uchtasi backend'da bor:
 * `retrying` — `pending` uslubida (semantikasi bir xil: hali harakatda),
 * `cancelled` — neytral kulrang, `dead_letter` — qizil, lekin yorlig'i
 * "DLQ" (oddiy `failed` dan ajralib turishi uchun).
 */
export const JOB_STATUS_STYLES: Record<JobStatus, StatusStyle> = {
  pending: PENDING,
  queued: QUEUED,
  running: RUNNING,
  success: SUCCESS,
  failed: FAILED,
  retrying: relabel(PENDING, 'Retrying', true),
  cancelled: NEUTRAL,
  dead_letter: relabel(FAILED, 'DLQ'),
}

export function jobStatusStyle(status: JobStatus): StatusStyle {
  return JOB_STATUS_STYLES[status] ?? QUEUED
}

export const EXECUTION_STATUS_STYLES: Record<ExecutionStatus, StatusStyle> = {
  pending: PENDING,
  running: RUNNING,
  success: SUCCESS,
  failed: FAILED,
  timeout: relabel(PENDING, 'Timeout'),
  cancelled: NEUTRAL,
  lost: relabel(FAILED, 'Lost'),
}

export function executionStatusStyle(status: ExecutionStatus): StatusStyle {
  return EXECUTION_STATUS_STYLES[status] ?? PENDING
}

export const DELIVERY_STATUS_STYLES: Record<DeliveryStatus, StatusStyle> = {
  pending: PENDING,
  success: relabel(SUCCESS, 'Delivered'),
  failed: FAILED,
  retrying: relabel(PENDING, 'Retrying', true),
  exhausted: relabel(FAILED, 'Exhausted'),
}

export function deliveryStatusStyle(status: DeliveryStatus): StatusStyle {
  return DELIVERY_STATUS_STYLES[status] ?? PENDING
}

export const WORKER_STATE_STYLES: Record<WorkerState, StatusStyle> = {
  starting: relabel(PENDING, 'Starting', true),
  idle: relabel(QUEUED, 'Idle'),
  busy: relabel(SUCCESS, 'Busy', true),
  draining: relabel(PENDING, 'Draining'),
  stopped: relabel(NEUTRAL, 'Stopped'),
  dead: relabel(FAILED, 'Dead'),
}

export function workerStateStyle(state: WorkerState): StatusStyle {
  return WORKER_STATE_STYLES[state] ?? WORKER_STATE_STYLES.idle
}

/** Runtime nishonlari — dizaynda Python ko'k, Node yashil nuqta bilan. */
export const RUNTIME_STYLES: Record<Runtime, StatusStyle> = {
  python: relabel(RUNNING, 'Python', false),
  node: relabel(SUCCESS, 'Node'),
}

export function runtimeStyle(runtime: Runtime): StatusStyle {
  return RUNTIME_STYLES[runtime] ?? RUNTIME_STYLES.python
}

/**
 * Pulsatsiya rangini CSS o'zgaruvchisi orqali beradi.
 * `animate-pulse-dot` keyframe'i `--pulse-color` ni o'qiydi.
 */
export function pulseStyle(token: string): CSSProperties {
  return { '--pulse-color': `var(--${token})` } as CSSProperties
}

/**
 * CPU yuklamasi rangi — dizayndagi qoida:
 * <60% yashil, <82% sariq, aks holda qizil.
 */
export function cpuColorClass(cpu: number): string {
  if (cpu < 60) return 'bg-success'
  if (cpu < 82) return 'bg-pending'
  return 'bg-failed'
}

export function cpuTextClass(cpu: number): string {
  if (cpu < 60) return 'text-success'
  if (cpu < 82) return 'text-pending'
  return 'text-failed'
}

/** Foydalanish o'lchagichi darajasi -> rang. */
export function usageLevelClass(level: 'ok' | 'warn' | 'over'): string {
  if (level === 'over') return 'bg-failed'
  if (level === 'warn') return 'bg-pending'
  return 'bg-accent'
}

/** Trend rangi: yaxshi o'zgarish yashil, yomon qizil, o'zgarmasa kulrang. */
export function trendClass(direction: 'up' | 'down' | 'flat', isGood: boolean): string {
  if (direction === 'flat') return 'text-fg-faint'
  return isGood ? 'text-success' : 'text-failed'
}

/**
 * Xato sabablarining o'qiladigan nomlari.
 *
 * Nega umumiy `humanize()` yetmaydi: u shunchaki `_` ni bo'sh joyga
 * almashtiradi va `non_zero_exit` -> "Non zero exit" bo'lib chiqadi, to'g'risi
 * esa "Non-zero exit". Domen atamalari taxmin qilinmaydi — aniq yoziladi.
 */
export const FAILURE_REASON_LABELS: Record<FailureReason, string> = {
  non_zero_exit: 'Non-zero exit',
  timeout: 'Timeout',
  out_of_memory: 'Out of memory',
  sandbox_error: 'Sandbox error',
  validation_error: 'Validation error',
  lease_lost: 'Lease lost',
  max_retries_exceeded: 'Max retries exceeded',
  internal_error: 'Internal error',
  output_too_large: 'Output too large',
}

/** Xato sababi yorlig'i (noma'lum qiymat kelsa ham yiqilmaydi). */
export function failureReasonLabel(reason: FailureReason | string): string {
  return (
    FAILURE_REASON_LABELS[reason as FailureReason] ??
    String(reason).replace(/[_-]+/g, ' ').replace(/^./, (c) => c.toUpperCase())
  )
}
