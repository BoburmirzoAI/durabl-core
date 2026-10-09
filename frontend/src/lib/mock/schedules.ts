/** Jadval (cron) va shablon mock generatori. */

import type {
  JobStatus,
  JobTemplate,
  Priority,
  Runtime,
  Schedule,
  ScheduleRun,
  ScheduleStatus,
} from '@/types'
import { nextCronRuns } from '@/lib/utils/cron'

import { NOW, Rng } from './seed'
import { MockCollection } from './store'

const SCHEDULE_DEFS: readonly {
  name: string
  description: string
  cron: string
  runtime: Runtime
  status: ScheduleStatus
  priority: Priority
  overlap?: boolean
}[] = [
  {
    name: 'Nightly warehouse sync',
    description: 'Copies yesterday’s orders into the analytics warehouse.',
    cron: '0 2 * * *',
    runtime: 'python',
    status: 'active',
    priority: 'high',
  },
  {
    name: 'Invoice PDF generation',
    description: 'Renders invoices for accounts that closed the previous day.',
    cron: '30 3 * * *',
    runtime: 'node',
    status: 'active',
    priority: 'normal',
  },
  {
    name: 'Stale session cleanup',
    description: 'Deletes sessions that have been idle for more than 30 days.',
    cron: '0 */6 * * *',
    runtime: 'python',
    status: 'active',
    priority: 'low',
  },
  {
    name: 'Weekly usage digest',
    description: 'Emails every workspace owner a summary of the past week.',
    cron: '0 8 * * 1',
    runtime: 'node',
    status: 'active',
    priority: 'normal',
  },
  {
    name: 'Search index rebuild',
    description: 'Full reindex — intentionally paused while the cluster is resized.',
    cron: '0 4 * * 0',
    runtime: 'python',
    status: 'paused',
    priority: 'low',
  },
  {
    name: 'Partner API reconciliation',
    description: 'Compares our ledger with the partner’s. Failing since the API change.',
    cron: '*/15 * * * *',
    runtime: 'python',
    status: 'errored',
    priority: 'high',
    overlap: true,
  },
]

export const scheduleStore = new MockCollection<Schedule>(buildSchedules, (s) => s.id)

function buildSchedules(): Schedule[] {
  return SCHEDULE_DEFS.map((def, i) => {
    const rng = new Rng(i * 48_271 + 101)
    const errored = def.status === 'errored'
    const paused = def.status === 'paused'
    const totalRuns = rng.int(40, 4_200)
    const lastRunAt = paused
      ? NOW - rng.int(3, 20) * 86_400_000
      : NOW - rng.int(5, 400) * 60_000

    return {
      id: `sch_${rng.hex(10)}`,
      name: def.name,
      description: def.description,
      cron: def.cron,
      timezone: 'UTC',
      runtime: def.runtime,
      priority: def.priority,
      status: def.status,
      allow_overlap: def.overlap ?? false,
      timeout_seconds: rng.pick([120, 300, 600, 900]),
      max_retries: rng.int(1, 5),
      created_at: new Date(NOW - rng.int(30, 500) * 86_400_000).toISOString(),
      updated_at: new Date(NOW - rng.int(1, 29) * 86_400_000).toISOString(),
      last_run_at: new Date(lastRunAt).toISOString(),
      last_run_status: (errored ? 'failed' : 'success') as JobStatus,
      // To'xtatilgan jadval keyingi ishga tushishga ega EMAS — bu muhim
      // farq, aks holda "pauza" so'zi yolg'on bo'lib qoladi
      next_run_at: paused
        ? null
        : (nextCronRuns(def.cron, 1, new Date(NOW))[0]?.toISOString() ?? null),
      consecutive_failures: errored ? rng.int(3, 9) : 0,
      total_runs: totalRuns,
      failed_runs: errored ? Math.round(totalRuns * 0.3) : Math.round(totalRuns * 0.02),
    }
  })
}

export function allSchedules(): Schedule[] {
  return scheduleStore.all()
}

export function findSchedule(id: string): Schedule | undefined {
  return allSchedules().find((s) => s.id === id)
}

/**
 * Jadval tarixidagi ishga tushishlar.
 *
 * Vaqtlar cron ifodasidan ORQAGA hisoblanadi — tasodifiy vaqtlar
 * qo'yilsa, "Nightly 02:00" jadvali tarixida 14:37 da ishga tushgan
 * qator paydo bo'lardi va butun sahifa yolg'onga o'xshardi.
 */
export function scheduleRuns(scheduleId: string, limit = 20): ScheduleRun[] {
  const schedule = findSchedule(scheduleId)
  if (!schedule) return []

  // Oldinga qarab hisoblab, keyin o'tmishga ko'chiramiz
  const forward = nextCronRuns(schedule.cron, limit + 1, new Date(NOW - 400 * 86_400_000))
  const stepMs =
    forward.length > 1
      ? (forward[1] as Date).getTime() - (forward[0] as Date).getTime()
      : 86_400_000

  return Array.from({ length: limit }, (_, i) => {
    const rng = new Rng(i * 196_613 + schedule.cron.length * 31)
    const scheduledFor = NOW - (i + 1) * stepMs
    const errored = schedule.status === 'errored'
    // Eng yangi urinishlar xatoli jadvalda muvaffaqiyatsiz bo'ladi
    const failing = errored && i < schedule.consecutive_failures
    const skipped = !failing && !schedule.allow_overlap && rng.bool(0.04)

    const status: ScheduleRun['status'] = skipped
      ? 'skipped'
      : failing
        ? 'failed'
        : rng.bool(0.96)
          ? 'success'
          : 'failed'

    return {
      id: `srun_${rng.hex(10)}`,
      schedule_id: scheduleId,
      job_id: skipped ? null : `job_${rng.hex(10)}`,
      scheduled_for: new Date(scheduledFor).toISOString(),
      // Rejalashtirilgan vaqt bilan haqiqiy boshlanish orasida navbat
      // kechikishi bo'ladi — bu haqiqiy tizimda doim shunday
      started_at: skipped ? null : new Date(scheduledFor + rng.int(120, 9_000)).toISOString(),
      status,
      duration_ms: skipped ? null : rng.int(400, 48_000),
      skip_reason: skipped ? 'Previous run was still in progress (overlap not allowed)' : null,
    }
  })
}

// ───────────────────────────────────────────────────────────────────────────
// Shablonlar
// ───────────────────────────────────────────────────────────────────────────

const TEMPLATE_DEFS: readonly {
  name: string
  description: string
  category: string
  runtime: Runtime
  code: string
  payload: string
  builtin: boolean
}[] = [
  {
    name: 'HTTP fetch and transform',
    description: 'Calls an HTTP endpoint, reshapes the response and returns it.',
    category: 'integration',
    runtime: 'python',
    builtin: true,
    payload: '{\n  "url": "https://api.example.com/orders",\n  "limit": 100\n}',
    code: `import json
import urllib.request


def main(payload):
    """Fetch the endpoint and return a reduced view of the response."""
    url = payload["url"]
    limit = payload.get("limit", 50)

    with urllib.request.urlopen(url, timeout=20) as response:
        data = json.load(response)

    rows = data.get("items", [])[:limit]
    return {
        "count": len(rows),
        "ids": [row["id"] for row in rows],
    }
`,
  },
  {
    name: 'CSV report builder',
    description: 'Aggregates rows and returns a CSV string ready for download.',
    category: 'report',
    runtime: 'python',
    builtin: true,
    payload: '{\n  "rows": [\n    {"region": "EU", "amount": 120},\n    {"region": "US", "amount": 310}\n  ]\n}',
    code: `import csv
import io
from collections import defaultdict


def main(payload):
    """Aggregate by region and return the report as CSV text."""
    totals = defaultdict(float)
    for row in payload["rows"]:
        totals[row["region"]] += row["amount"]

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["region", "total"])
    for region, total in sorted(totals.items()):
        writer.writerow([region, round(total, 2)])

    return {"csv": buffer.getvalue(), "regions": len(totals)}
`,
  },
  {
    name: 'Webhook fan-out',
    description: 'Delivers one event to several endpoints with per-target results.',
    category: 'integration',
    runtime: 'node',
    builtin: true,
    payload: '{\n  "event": "order.created",\n  "targets": ["https://a.example/hook", "https://b.example/hook"]\n}',
    code: `// Delivers one event to several endpoints.
// One failing target does not stop the others — each result is returned
// separately so a retry can target exactly what failed.
export default async function main(payload) {
  const results = await Promise.allSettled(
    payload.targets.map(async (url) => {
      const response = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event: payload.event }),
      })
      if (!response.ok) throw new Error(\`\${url} returned \${response.status}\`)
      return url
    }),
  )

  return {
    delivered: results.filter((r) => r.status === 'fulfilled').length,
    failed: results
      .filter((r) => r.status === 'rejected')
      .map((r) => String(r.reason)),
  }
}
`,
  },
  {
    name: 'Database cleanup',
    description: 'Deletes rows older than the retention window, in batches.',
    category: 'maintenance',
    runtime: 'python',
    builtin: true,
    payload: '{\n  "table": "sessions",\n  "older_than_days": 30,\n  "batch_size": 1000\n}',
    code: `def main(payload):
    """Delete old rows in batches.

    Deleting everything in one statement holds a lock on the table for a
    long time, so the work is chunked.
    """
    table = payload["table"]
    days = payload.get("older_than_days", 30)
    batch = payload.get("batch_size", 1000)

    deleted = 0
    while True:
        removed = delete_batch(table, days, batch)  # noqa: F821
        deleted += removed
        if removed < batch:
            break

    return {"table": table, "deleted": deleted}
`,
  },
  {
    name: 'Nightly warehouse sync',
    description: 'Saved from the schedule of the same name.',
    category: 'etl',
    runtime: 'python',
    builtin: false,
    payload: '{\n  "source": "orders",\n  "since": "yesterday"\n}',
    code: `def main(payload):
    """Copy yesterday's records into the warehouse."""
    source = payload["source"]
    rows = extract(source, payload.get("since", "yesterday"))  # noqa: F821
    load("warehouse." + source, rows)  # noqa: F821
    return {"source": source, "rows": len(rows)}
`,
  },
]

export const templateStore = new MockCollection<JobTemplate>(buildTemplates, (t) => t.id)

function buildTemplates(): JobTemplate[] {
  return TEMPLATE_DEFS.map((def, i) => {
    const rng = new Rng(i * 69_621 + 7)
    const useCount = def.builtin ? rng.int(0, 40) : rng.int(5, 300)
    return {
      id: `tpl_${rng.hex(10)}`,
      name: def.name,
      description: def.description,
      category: def.category,
      runtime: def.runtime,
      code: def.code,
      payload: def.payload,
      timeout_seconds: rng.pick([120, 300, 600]),
      memory_mb: rng.pick([256, 512, 1_024]),
      max_retries: rng.int(1, 5),
      priority: rng.pick(['low', 'normal', 'high'] as Priority[]),
      is_builtin: def.builtin,
      use_count: useCount,
      created_at: new Date(NOW - rng.int(10, 400) * 86_400_000).toISOString(),
      last_used_at: useCount === 0 ? null : new Date(NOW - rng.int(1, 60) * 86_400_000).toISOString(),
    }
  })
}

export function allTemplates(): JobTemplate[] {
  return templateStore.all()
}
