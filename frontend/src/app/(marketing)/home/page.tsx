import Link from 'next/link'

import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Durabl — Reliable background jobs',
}

/**
 * LANDING PAGE (`/home`) — PLACEHOLDER.
 *
 * Nega `/home`, `/` emas: ildiz yo'li (`app/page.tsx`) autentifikatsiya
 * holatiga qarab yo'naltiradi. Ikki fayl bir yo'lga tushsa Next.js build
 * xato beradi.
 *
 * Prompt'da ochiq aytilgan: premium landing page (3D animatsiya, scroll
 * effektlari) ALOHIDA promt bilan quriladi va butunlay boshqa texnologiya
 * talab qiladi (Three.js / React Three Fiber / GSAP).
 *
 * Shu sababli bu yerda minimal, lekin TO'LIQ ishlaydigan versiya turadi:
 * brend, bir qatorli ta'rif, asosiy tamoyillar va CTA. Premium versiya
 * kelganda shu fayl almashtiriladi — boshqa hech narsaga tegish kerak emas.
 */
const PRINCIPLES = [
  {
    title: 'Durability',
    body: 'A job that is accepted is never lost. It is written to PostgreSQL before it ever reaches the queue.',
  },
  {
    title: 'Idempotency',
    body: 'Send the same Idempotency-Key twice and the code runs once — even if the network retried for you.',
  },
  {
    title: 'Isolation',
    body: 'Every job runs in its own gVisor sandbox: no network, read-only filesystem, hard CPU and memory limits.',
  },
  {
    title: 'Observability',
    body: 'Throughput, latency percentiles and DLQ depth — plus the full lifecycle of every single job.',
  },
  {
    title: 'Reliability',
    body: 'Workers hold a 15s lease with heartbeats. If one dies, the job moves to another worker automatically.',
  },
] as const

export default function HomePage() {
  return (
    <div className="mx-auto max-w-[1100px] px-5 py-16">
      <div className="rounded-xl border border-pending/25 bg-pending/[0.07] px-4 py-2.5 text-sm text-pending">
        Placeholder landing page — the animated version ships separately.
      </div>

      <h1 className="mt-10 max-w-[760px] text-[44px] font-semibold leading-[1.1] tracking-[-.03em] text-fg">
        Your background jobs will never silently disappear.
      </h1>
      <p className="mt-5 max-w-[620px] text-xl leading-[1.5] text-fg-muted">
        Durabl runs Python and JavaScript in an isolated sandbox, retries what fails, and puts
        whatever truly broke into a dead letter queue you can actually act on.
      </p>

      <div className="mt-8 flex flex-wrap items-center gap-3">
        <Link
          href="/register"
          className="rounded-lg bg-accent-solid px-5 py-2.5 text-base font-medium text-white hover:bg-accent-hover hover:text-white"
        >
          Start free
        </Link>
        <Link
          href="/dashboard"
          className="rounded-lg border border-line bg-surface px-5 py-2.5 text-base font-medium text-fg-soft hover:border-line-hover hover:text-fg"
        >
          Open the dashboard
        </Link>
        <Link href="/docs" className="px-2 text-base font-medium">
          Read the docs →
        </Link>
      </div>

      <div className="mt-14 grid gap-3.5 sm:grid-cols-2 lg:grid-cols-3">
        {PRINCIPLES.map((principle) => (
          <div key={principle.title} className="rounded-2xl border border-line bg-surface p-5">
            <div className="text-lg font-semibold text-fg">{principle.title}</div>
            <p className="mt-2 text-base leading-[1.6] text-fg-muted">{principle.body}</p>
          </div>
        ))}
      </div>

      <div className="mt-14 overflow-hidden rounded-2xl border border-line bg-surface">
        <div className="border-b border-line-inner px-5 py-3.5 text-md font-semibold text-fg">
          Submit a job in four lines
        </div>
        <pre className="m-0 overflow-x-auto whitespace-pre bg-canvas-deep px-5 py-4 font-mono text-sm leading-[1.8] text-fg-soft">
{`from durabl import DurablClient

client = DurablClient(api_key="durabl_xxx")
job = client.submit(code="print('hello')", runtime="python")
print(client.wait_for_result(job.id).stdout)`}
        </pre>
      </div>
    </div>
  )
}
