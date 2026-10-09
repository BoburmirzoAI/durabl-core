/**
 * Mock ma'lumot uchun realistik matn namunalari.
 *
 * Maqsad — tizim "band ishlab turgan" taassurotini berish: haqiqiy kod,
 * haqiqiy xato matnlari, haqiqiy traceback'lar.
 */

/** Mijoz yuborishi mumkin bo'lgan kod namunalari. */
export const CODE_SAMPLES: readonly { runtime: 'python' | 'node'; label: string; code: string }[] = [
  {
    runtime: 'python',
    label: 'Image thumbnail',
    code: `import json, hashlib
from pathlib import Path

def main(url: str, size: int = 256):
    """Rasmni yuklab olib thumbnail yasaydi."""
    payload = json.loads(Path("payload.json").read_text())
    digest = hashlib.sha256(url.encode()).hexdigest()[:12]
    print(f"processing {url} -> {size}px ({digest})")
    return {"thumb": f"thumbs/{digest}_{size}.webp", "bytes": size * size * 3}
`,
  },
  {
    runtime: 'python',
    label: 'Report aggregation',
    code: `import json
from collections import Counter
from pathlib import Path

def main(rows):
    counter = Counter(r["region"] for r in rows)
    total = sum(counter.values())
    print(f"aggregated {total} rows across {len(counter)} regions")
    return {"regions": dict(counter), "total": total}
`,
  },
  {
    runtime: 'python',
    label: 'Webhook fan-out',
    code: `import json, urllib.request
from pathlib import Path

def main(targets, body):
    sent = []
    for url in targets:
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            sent.append({"url": url, "status": resp.status})
    return {"delivered": len(sent), "results": sent}
`,
  },
  {
    runtime: 'node',
    label: 'CSV transform',
    code: `const fs = require('fs')

module.exports.main = (rows) => {
  const parsed = rows.map((line) => line.split(','))
  const header = parsed.shift()
  console.log(\`parsed \${parsed.length} rows, \${header.length} columns\`)
  return { rows: parsed.length, columns: header }
}
`,
  },
  {
    runtime: 'node',
    label: 'Invoice PDF',
    code: `module.exports.main = async (invoiceId) => {
  const started = Date.now()
  console.log('rendering invoice', invoiceId)
  await new Promise((r) => setTimeout(r, 120))
  return { key: \`invoices/\${invoiceId}.pdf\`, ms: Date.now() - started }
}
`,
  },
]

/** Realistik xato turlari va traceback'lari. */
export const ERROR_SAMPLES: readonly {
  type: string
  /**
   * Qaysi runtime uchun mos.
   *
   * MUHIM: Python job'ining loglarida JavaScript `TypeError` chiqishi
   * mumkin emas. `'any'` — runtime'dan qat'i nazar bo'ladigan xatolar
   * (sandbox ishga tushmadi, lease yo'qoldi).
   */
  runtime: 'python' | 'node' | 'any'
  reason:
    | 'timeout'
    | 'non_zero_exit'
    | 'out_of_memory'
    | 'sandbox_error'
    | 'validation_error'
    | 'lease_lost'
    | 'internal_error'
  message: string
  traceback: string
}[] = [
  {
    type: 'TimeoutError',
    runtime: 'python',
    reason: 'timeout',
    message: 'Execution exceeded the 30s time limit',
    traceback: `Traceback (most recent call last):
  File "/sandbox/main.py", line 14, in main
    data = fetch_remote(url, timeout=None)
  File "/sandbox/main.py", line 7, in fetch_remote
    with urllib.request.urlopen(req) as resp:
TimeoutError: Execution exceeded the 30s time limit
  durabl: job killed by timeout_guard after 30.004s (SIGTERM, exit 143)`,
  },
  {
    type: 'ConnectionError',
    runtime: 'python',
    reason: 'non_zero_exit',
    message: "HTTPSConnectionPool(host='api.upstream.io', port=443): Max retries exceeded",
    traceback: `Traceback (most recent call last):
  File "/sandbox/main.py", line 22, in main
    resp = session.post(ENDPOINT, json=body, timeout=8)
  File "/usr/lib/python3.12/urllib/request.py", line 519, in open
    response = self._open(req, data)
ConnectionError: HTTPSConnectionPool(host='api.upstream.io', port=443):
  Max retries exceeded with url: /v2/ingest (Caused by NameResolutionError)`,
  },
  {
    type: 'MemoryError',
    runtime: 'python',
    reason: 'out_of_memory',
    message: 'Container exceeded its 256 MB memory limit',
    traceback: `Traceback (most recent call last):
  File "/sandbox/main.py", line 9, in main
    frames = [decode(chunk) for chunk in stream]
MemoryError: Container exceeded its 256 MB memory limit
  durabl: cgroup OOMKilled (exit 137) — increase memory_mb or stream the input`,
  },
  {
    type: 'ValueError',
    runtime: 'python',
    reason: 'non_zero_exit',
    message: "invalid literal for int() with base 10: 'n/a'",
    traceback: `Traceback (most recent call last):
  File "/sandbox/main.py", line 18, in main
    total += int(row["amount"])
ValueError: invalid literal for int() with base 10: 'n/a'`,
  },
  {
    type: 'KeyError',
    runtime: 'python',
    reason: 'non_zero_exit',
    message: "'customer_id'",
    traceback: `Traceback (most recent call last):
  File "/sandbox/main.py", line 11, in main
    customer = payload["customer_id"]
KeyError: 'customer_id'`,
  },
  {
    type: 'SyntaxError',
    runtime: 'python',
    reason: 'validation_error',
    message: "unexpected EOF while parsing (main.py, line 24)",
    traceback: `  File "/sandbox/main.py", line 24
    return {"ok": True
                      ^
SyntaxError: unexpected EOF while parsing
  durabl: rejected by code validation — retry will not help`,
  },
  {
    type: 'SandboxStartupError',
    runtime: 'any',
    reason: 'sandbox_error',
    message: 'Sandbox container failed to start',
    traceback: `durabl.exceptions.SandboxStartupError: Sandbox container failed to start
  image: durabl/runner-python:latest
  runtime: runsc
  cause: OCI runtime create failed: no such file or directory`,
  },
  {
    type: 'LeaseLostError',
    runtime: 'any',
    reason: 'lease_lost',
    message: 'Worker stopped responding — lease expired',
    traceback: `durabl.exceptions.LeaseLostError: Worker stopped responding — lease expired
  worker: wkr-03 (us-west-2a)
  last_heartbeat: 15.2s before expiry
  durabl: job automatically requeued to another worker`,
  },
  {
    type: 'TypeError',
    runtime: 'node',
    reason: 'non_zero_exit',
    message: "Cannot read properties of undefined (reading 'map')",
    traceback: `TypeError: Cannot read properties of undefined (reading 'map')
    at main (/sandbox/main.js:4:22)
    at /opt/durabl/entrypoint.js:118:24
    at process.processTicksAndRejections (node:internal/process/task_queues:95:5)`,
  },
]

/** Runtime'ga xos ochilish qatori — loglarning birinchisi. */
export const RUNTIME_BANNER: Record<'python' | 'node', string> = {
  python: 'durabl: runtime python3.12 · sandbox runsc · memory 256MB · cpus 0.5',
  node: 'durabl: runtime node22 · sandbox runsc · memory 256MB · cpus 0.5',
}

/**
 * Log qatorlari — MANTIQIY KETMA-KETLIKDA.
 *
 * DIQQAT: bu ro'yxat ARALASHTIRILMAYDI. Ilgari `rng.shuffle(...)` ishlatilgan
 * va natijada loglarda "batch 1/4", keyin "4/4", keyin "3/4" chiqib,
 * natijalarni yozish ma'lumot o'qishdan oldin ko'rinardi. Ketma-ketlikdan
 * faqat BOSHIDAN uzluksiz bo'lak olinadi.
 */
export const LOG_LINES: readonly string[] = [
  'durabl: payload.json loaded (2 args, 0 kwargs)',
  'connecting to upstream api.internal:5432',
  'connection established in 18ms',
  'fetching batch 1/4 (250 records)',
  'fetching batch 2/4 (250 records)',
  'fetching batch 3/4 (250 records)',
  'fetching batch 4/4 (187 records)',
  'processed 937 records · 0 skipped',
  'writing results to s3://durabl-output/job-results/',
  'upload complete (1.2 MB)',
  'durabl: result serialized (142 bytes)',
]

/** Foydalanuvchi email'lari (admin ro'yxati va DLQ "By User" guruhi uchun). */
export const USER_EMAILS: readonly string[] = [
  'jordan@durabl.dev',
  'sam.ortiz@acme.io',
  'priya@shipfast.co',
  'lee@northwind.dev',
  'maya.khan@pixelforge.io',
  'tom@dataloop.ai',
  'ana@brightline.co',
  'kenji@orbital.dev',
  'ruth@fernwood.io',
  'dev@stacklane.sh',
]

export const USER_NAMES: readonly string[] = [
  'Jordan Diaz',
  'Sam Ortiz',
  'Priya Raman',
  'Lee Nakamura',
  'Maya Khan',
  'Tom Weaver',
  'Ana Bright',
  'Kenji Mori',
  'Ruth Fern',
  'Dev Patel',
]

/** Worker joylashuvlari. */
export const REGIONS: readonly string[] = [
  'us-east-1a',
  'us-east-1b',
  'us-east-1c',
  'us-west-2a',
  'us-west-2b',
  'eu-west-1a',
  'eu-central-1a',
  'ap-south-1a',
]

/** Job teglari. */
export const TAGS: readonly string[] = [
  'prod',
  'staging',
  'etl',
  'images',
  'reports',
  'billing',
  'cron',
  'backfill',
  'ml',
  'webhooks',
]

/** Idempotency kalit namunalari. */
export const IDEMPOTENCY_PREFIXES: readonly string[] = [
  'order',
  'invoice',
  'upload',
  'sync',
  'digest',
  'export',
  'resize',
  'notify',
]
