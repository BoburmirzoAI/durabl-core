/**
 * DLQ mock generatori.
 *
 * DLQ yozuvlari job'lardan KELIB CHIQADI: `dead_letter` holatidagi har bir
 * job uchun bitta yozuv. Shu tufayli DLQ chuqurligi dashboard'dagi job
 * holatlari bilan o'zaro mos bo'ladi (yolg'on raqam ko'rsatmaymiz).
 */

import type { DlqEntry, DlqStats, FailureReason } from '@/types'

import { ERROR_SAMPLES, USER_EMAILS } from './fixtures'
import { allJobs } from './jobs'
import { NOW, Rng } from './seed'
import { MockCollection } from './store'

/** DLQ yozuvi to'plami — bir marta quriladi, keyin o'zgartiriladi. */
export const dlqStore = new MockCollection<DlqEntry>(build, (item) => item.id)

function build(): DlqEntry[] {
  const dead = allJobs().filter((j) => j.status === 'dead_letter')
  return dead.map((job, i) => {
    const rng = new Rng(i * 104_729 + 7)
    const sample =
      ERROR_SAMPLES.find((e) => e.reason === job.failure_reason) ?? rng.pick(ERROR_SAMPLES)
    // Yozuvlarning ~20% i hal qilingan (operator qayta urinib ko'rgan)
    const resolved = rng.bool(0.2)
    return {
      id: `dlq_${rng.hex(10)}`,
      job_id: job.id,
      user_id: job.user_id,
      user_email: rng.pick(USER_EMAILS),
      runtime: job.runtime,
      failure_reason: job.failure_reason ?? sample.reason,
      error_type: sample.type,
      last_error: sample.message,
      traceback: sample.traceback,
      failed_at: job.finished_at ?? job.created_at,
      retry_count: job.retry_count,
      manual_retry_count: resolved ? rng.int(1, 2) : 0,
      resolved,
      resolved_at: resolved ? new Date(NOW - rng.int(5, 400) * 60_000).toISOString() : null,
      notes: resolved && rng.bool(0.5) ? 'Fixed upstream timeout, re-ran successfully.' : null,
    }
  })
}

export function allDlqEntries(): DlqEntry[] {
  return dlqStore.all()
}

export function findDlqEntry(id: string): DlqEntry | undefined {
  return allDlqEntries().find((e) => e.id === id)
}

export function dlqStats(): DlqStats {
  const entries = allDlqEntries()
  const unresolved = entries.filter((e) => !e.resolved)
  const dayAgo = NOW - 86_400_000

  const byReason: Partial<Record<FailureReason, number>> = {}
  const byType = new Map<string, number>()
  for (const e of unresolved) {
    byReason[e.failure_reason] = (byReason[e.failure_reason] ?? 0) + 1
    byType.set(e.error_type, (byType.get(e.error_type) ?? 0) + 1)
  }

  const top = [...byType.entries()].sort((a, b) => b[1] - a[1])[0]
  const oldest = unresolved
    .map((e) => e.failed_at)
    .sort((a, b) => new Date(a).getTime() - new Date(b).getTime())[0]

  return {
    depth: unresolved.length,
    total: entries.length,
    resolved: entries.length - unresolved.length,
    unresolved: unresolved.length,
    added_last_24h: entries.filter((e) => new Date(e.failed_at).getTime() >= dayAgo).length,
    top_error: top ? { type: top[0], count: top[1] } : null,
    by_reason: byReason,
    oldest_failed_at: oldest ?? null,
  }
}

/** Sidebar nishoni uchun — hal qilinmagan yozuvlar soni. */
export function dlqDepth(): number {
  return allDlqEntries().filter((e) => !e.resolved).length
}
