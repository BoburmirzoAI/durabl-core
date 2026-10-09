import Link from 'next/link'

import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Docs',
  description: 'Durabl documentation — authentication, submitting jobs, webhooks and error codes.',
}

/**
 * Hujjatlar sahifasi.
 *
 * Chap tomonda sticky ichki navigatsiya (anchor havolalar), o'ngda
 * bo'limlar. Hamma namuna HAQIQIY backend shartnomasiga mos:
 * yo'llar `/api/v1/...`, header'lar `X-API-Key` / `Idempotency-Key`,
 * xato shakli `{"error":{"code","message"}}`.
 *
 * SERVER komponent — interaktivlik yo'q.
 */
const SECTIONS = [
  { id: 'quickstart', label: 'Quickstart' },
  { id: 'auth', label: 'Authentication' },
  { id: 'submit', label: 'Submitting jobs' },
  { id: 'results', label: 'Getting results' },
  { id: 'idempotency', label: 'Idempotency' },
  { id: 'retries', label: 'Retries & DLQ' },
  { id: 'webhooks', label: 'Webhooks' },
  { id: 'errors', label: 'Error codes' },
] as const

const ERROR_CODES = [
  ['AUTHENTICATION_REQUIRED', '401', 'No token or API key was supplied.'],
  ['INVALID_API_KEY', '401', 'The key is unknown, revoked or expired.'],
  ['PERMISSION_DENIED', '403', 'Authenticated, but not allowed to do this.'],
  ['JOB_NOT_FOUND', '404', 'No job with that id belongs to you.'],
  ['IDEMPOTENCY_CONFLICT', '409', 'Same key, different request body.'],
  ['RESULT_NOT_READY', '409', 'The job has not reached a terminal state yet.'],
  ['JOB_NOT_CANCELLABLE', '409', 'The job already finished.'],
  ['PAYLOAD_TOO_LARGE', '413', 'Code or payload exceeded the size limit.'],
  ['CODE_VALIDATION_FAILED', '422', 'Static checks rejected the code.'],
  ['QUOTA_EXCEEDED', '402', 'Monthly plan allowance is used up.'],
  ['RATE_LIMIT_EXCEEDED', '429', 'Too many requests — see Retry-After.'],
  ['CONCURRENCY_LIMIT_EXCEEDED', '429', 'Too many jobs running at once.'],
] as const

export default function DocsPage() {
  return (
    <div className="mx-auto max-w-[1100px] px-5 py-14">
      <div className="flex gap-10">
        {/* Ichki navigatsiya */}
        <nav
          aria-label="On this page"
          className="sticky top-[76px] hidden h-fit w-[180px] shrink-0 flex-col gap-1 lg:flex"
        >
          <div className="px-2.5 pb-1.5 text-2xs font-semibold uppercase tracking-[.09em] text-fg-faint">
            On this page
          </div>
          {SECTIONS.map((section) => (
            <a
              key={section.id}
              href={`#${section.id}`}
              className="rounded-md px-2.5 py-1.5 text-base text-fg-muted hover:bg-surface-2 hover:text-fg"
            >
              {section.label}
            </a>
          ))}
        </nav>

        <div className="min-w-0 flex-1">
          <h1 className="m-0 text-[36px] font-semibold tracking-[-.03em] text-fg">
            Documentation
          </h1>
          <p className="mt-3 max-w-[620px] text-lg text-fg-muted">
            Durabl exposes a small HTTP API and two SDKs. Everything below works against{' '}
            <code className="font-mono text-base text-accent-light">
              https://api.durabl.dev/api/v1
            </code>
            .
          </p>

          <Section id="quickstart" title="Quickstart">
            <P>
              Create an API key in{' '}
              <Link href="/api-keys" className="font-medium">
                API Keys
              </Link>
              , then submit your first job. The SDK polls until the job reaches a terminal state.
            </P>
            <Code
              label="Python"
              code={`pip install durabl

from durabl import DurablClient

client = DurablClient(api_key="durabl_xxx")

job = client.submit(
    code="print('hello from Durabl')",
    runtime="python",
    timeout=30,
)

result = client.wait_for_result(job.id, timeout=60)
print(result.stdout)   # hello from Durabl
print(result.ok)       # True`}
            />
            <Code
              label="JavaScript"
              code={`npm install durabl

import { DurablClient } from 'durabl'

const client = new DurablClient({ apiKey: 'durabl_xxx' })

const job = await client.submit({
  code: "console.log('hello from Durabl')",
  runtime: 'node',
})

const result = await job.wait({ timeoutMs: 60_000 })
console.log(result.stdout)`}
            />
          </Section>

          <Section id="auth" title="Authentication">
            <P>
              Two mechanisms. Use an <B>API key</B> for machine-to-machine traffic and a <B>JWT</B>{' '}
              for dashboard sessions.
            </P>
            <Code
              label="API key (recommended for SDKs)"
              code={`curl https://api.durabl.dev/api/v1/jobs \\
  -H "X-API-Key: durabl_xxx"`}
            />
            <Code
              label="JWT"
              code={`curl https://api.durabl.dev/api/v1/jobs \\
  -H "Authorization: Bearer <access_token>"`}
            />
            <P>
              Keys are stored as SHA-256 hashes, so the full value is shown exactly once at
              creation time.
            </P>
          </Section>

          <Section id="submit" title="Submitting jobs">
            <Code
              label="POST /jobs"
              code={`curl -X POST https://api.durabl.dev/api/v1/jobs \\
  -H "X-API-Key: durabl_xxx" \\
  -H "Idempotency-Key: order-12345" \\
  -H "Content-Type: application/json" \\
  -d '{
    "code": "def main(n):\\n    return n * 2",
    "runtime": "python",
    "payload": { "args": [21] },
    "timeout_seconds": 30,
    "max_retries": 3,
    "priority": "normal",
    "tags": ["prod", "etl"]
  }'`}
            />
            <P>
              The payload is written into the sandbox as{' '}
              <code className="font-mono text-base text-accent-light">payload.json</code>. If your
              code defines <code className="font-mono text-base text-accent-light">main()</code> or{' '}
              <code className="font-mono text-base text-accent-light">handler()</code>, Durabl calls
              it with <code className="font-mono text-base text-accent-light">args</code> and{' '}
              <code className="font-mono text-base text-accent-light">kwargs</code> and records the
              return value as the result.
            </P>
            <P>
              Responses are <B>201</B> for a newly created job and <B>200</B> when an idempotency
              key replayed an existing one.
            </P>
          </Section>

          <Section id="results" title="Getting results">
            <P>Poll the job, or let a webhook tell you when it finishes.</P>
            <Code
              label="Polling"
              code={`GET /api/v1/jobs/{id}          # full job
GET /api/v1/jobs/{id}/status   # lightweight, for tight polling loops
GET /api/v1/jobs/{id}/result   # 409 RESULT_NOT_READY until terminal
GET /api/v1/jobs/{id}/logs     # stdout / stderr lines
GET /api/v1/jobs/{id}/timeline # queue wait, execution, per-attempt timings`}
            />
          </Section>

          <Section id="idempotency" title="Idempotency">
            <P>
              Send an <code className="font-mono text-base text-accent-light">Idempotency-Key</code>{' '}
              header and Durabl guarantees the code runs at most once for that key, even if your
              client retried after a timeout.
            </P>
            <Code
              code={`# first call  -> 201, creates job_abc
# second call -> 200, returns the SAME job_abc
# different body, same key -> 409 IDEMPOTENCY_CONFLICT`}
            />
            <P>Keys are scoped per user and remembered for 24 hours.</P>
          </Section>

          <Section id="retries" title="Retries & dead letter queue">
            <P>
              A failed job is retried with exponential backoff —{' '}
              <code className="font-mono text-base text-accent-light">1s → 2s → 4s → 8s</code> plus
              jitter — up to <code className="font-mono text-base text-accent-light">max_retries</code>
              . Every attempt is recorded separately so you can see exactly which worker failed and
              why.
            </P>
            <P>
              When the attempts run out the job lands in the{' '}
              <Link href="/dlq" className="font-medium">
                dead letter queue
              </Link>
              . Nothing is discarded: you see the traceback, fix the cause, and retry from the
              dashboard or the API.
            </P>
            <P>
              Some failures skip retries entirely because retrying cannot help — out of memory,
              output too large, and code that fails validation.
            </P>
          </Section>

          <Section id="webhooks" title="Webhooks">
            <P>
              Durabl POSTs signed JSON to your endpoint. The signature header is{' '}
              <code className="font-mono text-base text-accent-light">
                X-Durabl-Signature: t=&lt;unix&gt;,v1=&lt;hex&gt;
              </code>{' '}
              and the signed payload is{' '}
              <code className="font-mono text-base text-accent-light">
                &lt;timestamp&gt;.&lt;body&gt;
              </code>{' '}
              — including the timestamp is what makes replay attacks fail.
            </P>
            <Code
              label="Verify in Python"
              code={`import hmac, hashlib

def verify(body: bytes, header: str, secret: str, tolerance: int = 300) -> bool:
    parts = dict(p.split("=", 1) for p in header.split(","))
    if abs(int(time.time()) - int(parts["t"])) > tolerance:
        return False
    signed = f"{parts['t']}.".encode() + body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, parts["v1"])`}
            />
          </Section>

          <Section id="errors" title="Error codes">
            <P>
              Every error has the same shape, so you can branch on{' '}
              <code className="font-mono text-base text-accent-light">error.code</code> rather than
              parsing messages.
            </P>
            <Code
              code={`{
  "error": {
    "code": "IDEMPOTENCY_CONFLICT",
    "message": "This Idempotency-Key was used with a different request body.",
    "details": { "idempotency_key": "order-12345" }
  },
  "request_id": "06cc4c21661f4289"
}`}
            />

            <div className="mt-4 overflow-hidden rounded-2xl border border-line bg-surface">
              <div
                className="grid border-b border-line-inner px-4 py-2.5 text-2xs font-semibold uppercase tracking-[.06em] text-fg-faint"
                style={{ gridTemplateColumns: 'minmax(210px,1fr) 60px 2fr' }}
              >
                <span>Code</span>
                <span>HTTP</span>
                <span>Meaning</span>
              </div>
              {ERROR_CODES.map(([code, status, meaning]) => (
                <div
                  key={code}
                  className="grid items-center border-b border-line-subtle px-4 py-2.5 last:border-b-0"
                  style={{ gridTemplateColumns: 'minmax(210px,1fr) 60px 2fr' }}
                >
                  <span className="font-mono text-sm text-accent-light">{code}</span>
                  <span className="tabular font-mono text-sm text-fg-muted">{status}</span>
                  <span className="text-sm text-fg-muted">{meaning}</span>
                </div>
              ))}
            </div>
          </Section>

          <div className="mt-14 rounded-2xl border border-line bg-surface px-5 py-6">
            <div className="text-lg font-semibold text-fg">Ready to try it?</div>
            <p className="mt-2 text-base text-fg-muted">
              The dashboard runs on sample data right now — explore it without signing up.
            </p>
            <Link
              href="/dashboard"
              className="mt-4 inline-flex rounded-lg bg-accent-solid px-5 py-2.5 text-base font-medium text-white hover:bg-accent-hover hover:text-white"
            >
              Open the dashboard
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}

function Section({
  id,
  title,
  children,
}: {
  id: string
  title: string
  children: React.ReactNode
}) {
  return (
    <section id={id} className="mt-12 scroll-mt-[76px]">
      <h2 className="m-0 text-2xl font-semibold tracking-[-.02em] text-fg">{title}</h2>
      <div className="mt-3 flex flex-col gap-3">{children}</div>
    </section>
  )
}

function P({ children }: { children: React.ReactNode }) {
  return <p className="m-0 max-w-[660px] text-base leading-[1.65] text-fg-muted">{children}</p>
}

function B({ children }: { children: React.ReactNode }) {
  return <strong className="font-semibold text-fg-soft">{children}</strong>
}

function Code({ label, code }: { label?: string; code: string }) {
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-surface">
      {label ? (
        <div className="border-b border-line-inner px-3.5 py-2 text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
          {label}
        </div>
      ) : null}
      <pre className="m-0 overflow-x-auto whitespace-pre bg-canvas-deep px-3.5 py-3 font-mono text-sm leading-[1.75] text-fg-soft">
        {code}
      </pre>
    </div>
  )
}
