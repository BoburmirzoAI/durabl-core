/**
 * `DurablClient` testlari.
 *
 * Haqiqiy tarmoqqa chiqmaydi: `globalThis.fetch` har bir testda mock
 * qilinadi va barcha so'rovlar `calls` massiviga yoziladi — shu tufayli
 * URL, header va tananing to'g'riligini ham tekshirish mumkin.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { DurablClient } from '../src/client.js';
import {
  AuthenticationError,
  DurablApiError,
  DurablError,
  JobFailedError,
  NotFoundError,
  QuotaExceededError,
  RateLimitError,
  TimeoutError,
  ValidationError,
} from '../src/errors.js';
import { JobHandle } from '../src/job.js';
import type { DurablClientOptions, Job } from '../src/types.js';

// ---------------------------------------------------------------------------
// Test yordamchilari
// ---------------------------------------------------------------------------

/** Mock `fetch` qayd qilgan bitta so'rov. */
interface RecordedCall {
  url: string;
  method: string;
  headers: Record<string, string>;
  rawBody: string | undefined;
  body: unknown;
  signal: AbortSignal | null;
}

/** So'rovga javob qaytaruvchi funksiya. */
type Handler = (call: RecordedCall, index: number) => Response | Promise<Response>;

/** Joriy testda qayd qilingan so'rovlar. */
let calls: RecordedCall[] = [];

/** `globalThis.fetch` ni mock bilan almashtiradi. */
function installFetch(handler: Handler): void {
  const mock = vi.fn(async (input: string, init: RequestInit): Promise<Response> => {
    const headerMap: Record<string, string> = {};
    new Headers(init.headers ?? {}).forEach((value, key) => {
      headerMap[key] = value;
    });
    const rawBody = typeof init.body === 'string' ? init.body : undefined;
    let parsed: unknown;
    if (rawBody !== undefined) {
      try {
        parsed = JSON.parse(rawBody);
      } catch {
        parsed = rawBody;
      }
    }
    const call: RecordedCall = {
      url: input,
      method: init.method ?? 'GET',
      headers: headerMap,
      rawBody,
      body: parsed,
      signal: init.signal ?? null,
    };
    const index = calls.length;
    calls.push(call);
    return await handler(call, index);
  });
  vi.stubGlobal('fetch', mock);
}

/** Ketma-ket javoblar: ro'yxat tugasa oxirgisi takrorlanadi. */
function installSequence(...handlers: Handler[]): void {
  installFetch((call, index) => {
    const handler = handlers[Math.min(index, handlers.length - 1)];
    if (handler === undefined) {
      throw new Error('Test uchun javob berilmagan');
    }
    return handler(call, index);
  });
}

/** JSON javob yasaydi. */
function jsonResponse(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  });
}

/** Durabl xato javobi shakli (`CONTRACTS.md` 12-bo'lim). */
function errorResponse(
  status: number,
  code: string,
  message: string,
  details?: Record<string, unknown>,
): Response {
  return jsonResponse(
    { error: { code, message, details: details ?? null }, request_id: 'req-123' },
    status,
    { 'x-request-id': 'req-123' },
  );
}

/** Test uchun mijoz: tez retry va tez polling bilan. */
function makeClient(overrides: Partial<DurablClientOptions> = {}): DurablClient {
  return new DurablClient({
    apiKey: 'durabl_test_key',
    baseUrl: 'https://api.test.durabl.dev',
    maxRetries: 0,
    retryBaseDelayMs: 1,
    retryMaxDelayMs: 2,
    retryJitter: false,
    pollIntervalMs: 1,
    maxPollIntervalMs: 2,
    timeoutMs: 1_000,
    ...overrides,
  });
}

/** Test uchun job yozuvi. */
function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: 'job-1',
    status: 'queued',
    runtime: 'python',
    priority: 'normal',
    timeout_seconds: 30,
    max_retries: 3,
    retry_count: 0,
    created_at: '2026-10-04T10:00:00Z',
    ...overrides,
  };
}

/** Birinchi qayd qilingan so'rov (bo'lmasa test yiqiladi). */
function firstCall(): RecordedCall {
  const call = calls[0];
  if (call === undefined) {
    throw new Error('Hech qanday so\'rov yuborilmadi');
  }
  return call;
}

beforeEach(() => {
  calls = [];
});

afterEach(() => {
  vi.unstubAllGlobals();
});

// ---------------------------------------------------------------------------
// Konstruktor
// ---------------------------------------------------------------------------

describe('DurablClient konstruktori', () => {
  it('apiKey bo\'sh bo\'lsa DurablError tashlaydi', () => {
    expect(() => new DurablClient({ apiKey: '   ' })).toThrow(DurablError);
    expect(() => new DurablClient({ apiKey: '' })).toThrowError(/apiKey/);
  });

  it('baseUrl oxiridagi slash larni olib tashlaydi', async () => {
    installFetch(() => jsonResponse(makeJob()));
    const client = makeClient({ baseUrl: 'https://api.test.durabl.dev///' });
    await client.getJob('job-1');
    expect(firstCall().url).toBe('https://api.test.durabl.dev/api/v1/jobs/job-1');
  });
});

// ---------------------------------------------------------------------------
// submit()
// ---------------------------------------------------------------------------

describe('submit()', () => {
  it('POST /api/v1/jobs ga X-API-Key bilan murojaat qiladi', async () => {
    installFetch(() => jsonResponse(makeJob(), 201));
    const client = makeClient();

    const handle = await client.submit({ code: 'print(1)', runtime: 'python' });

    const call = firstCall();
    expect(call.method).toBe('POST');
    expect(call.url).toBe('https://api.test.durabl.dev/api/v1/jobs');
    expect(call.headers['x-api-key']).toBe('durabl_test_key');
    expect(call.headers['content-type']).toBe('application/json');
    expect(handle).toBeInstanceOf(JobHandle);
    expect(handle.id).toBe('job-1');
    expect(handle.created).toBe(true);
  });

  it('camelCase parametrlarni backend snake_case shakliga o\'tkazadi', async () => {
    installFetch(() => jsonResponse(makeJob(), 201));
    const client = makeClient();

    await client.submit({
      code: 'print(1)',
      runtime: 'node',
      priority: 'high',
      timeout: 45,
      retries: 5,
      payload: { url: 'https://example.com' },
      envVars: { TOKEN: 'x' },
      tags: ['rasm', 'yuklash'],
      memoryMb: 512,
      cpus: 1.5,
      cronExpression: '*/5 * * * *',
      scheduledAt: new Date('2026-10-05T12:00:00.000Z'),
    });

    expect(firstCall().body).toEqual({
      code: 'print(1)',
      runtime: 'node',
      priority: 'high',
      timeout_seconds: 45,
      max_retries: 5,
      payload: { url: 'https://example.com' },
      env_vars: { TOKEN: 'x' },
      tags: ['rasm', 'yuklash'],
      memory_mb: 512,
      cpus: 1.5,
      cron_expression: '*/5 * * * *',
      scheduled_at: '2026-10-05T12:00:00.000Z',
    });
  });

  it('idempotencyKey berilmasa avtomatik yaratadi', async () => {
    installFetch(() => jsonResponse(makeJob(), 201));
    const client = makeClient();

    await client.submit({ code: 'print(1)', runtime: 'python' });

    const key = firstCall().headers['idempotency-key'];
    expect(typeof key).toBe('string');
    expect((key ?? '').length).toBeGreaterThan(8);
  });

  it('berilgan idempotencyKey ni header\'ga qo\'yadi', async () => {
    installFetch(() => jsonResponse(makeJob(), 200));
    const client = makeClient();

    const handle = await client.submit({
      code: 'print(1)',
      runtime: 'python',
      idempotencyKey: 'buyruq-42',
    });

    expect(firstCall().headers['idempotency-key']).toBe('buyruq-42');
    // 200 — job avval yaratilgan, idempotency ishladi.
    expect(handle.created).toBe(false);
  });

  it('autoIdempotency: false bo\'lsa header qo\'shilmaydi', async () => {
    installFetch(() => jsonResponse(makeJob(), 201));
    const client = makeClient({ autoIdempotency: false });

    await client.submit({ code: 'print(1)', runtime: 'python' });

    expect(firstCall().headers['idempotency-key']).toBeUndefined();
  });

  it('bo\'sh kod bilan so\'rov yubormaydi', async () => {
    installFetch(() => jsonResponse(makeJob(), 201));
    const client = makeClient();

    await expect(client.submit({ code: '   ', runtime: 'python' })).rejects.toBeInstanceOf(
      DurablError,
    );
    expect(calls).toHaveLength(0);
  });

  it('noma\'lum runtime bilan so\'rov yubormaydi', async () => {
    installFetch(() => jsonResponse(makeJob(), 201));
    const client = makeClient();

    await expect(
      client.submit({ code: 'print(1)', runtime: 'ruby' as unknown as 'python' }),
    ).rejects.toThrowError(/runtime/);
    expect(calls).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// Job o'qish metodlari
// ---------------------------------------------------------------------------

describe('job o\'qish metodlari', () => {
  it('getJob() to\'g\'ri yo\'lga murojaat qiladi', async () => {
    installFetch(() => jsonResponse(makeJob({ status: 'running' })));
    const client = makeClient();

    const job = await client.getJob('job-1');

    expect(firstCall().url).toBe('https://api.test.durabl.dev/api/v1/jobs/job-1');
    expect(job.status).toBe('running');
  });

  it('getStatus() faqat holat matnini qaytaradi', async () => {
    installFetch(() => jsonResponse(makeJob({ status: 'success' })));
    const client = makeClient();

    await expect(client.getStatus('job-1')).resolves.toBe('success');
  });

  it('getResult() /result yo\'lidan natijani oladi', async () => {
    installFetch(() =>
      jsonResponse({ job_id: 'job-1', status: 'success', stdout: 'salom\n', exit_code: 0 }),
    );
    const client = makeClient();

    const result = await client.getResult('job-1');

    expect(firstCall().url).toBe('https://api.test.durabl.dev/api/v1/jobs/job-1/result');
    expect(result.stdout).toBe('salom\n');
  });

  it('getResult() backendning `id` kalitini `job_id` ga ko\'chiradi', async () => {
    // `JobResultResponse` job identifikatorini `id` da yuboradi (`job_id` emas).
    installFetch(() =>
      jsonResponse({
        id: 'job-7',
        status: 'success',
        result: 42,
        stdout: '',
        stderr: '',
        exit_code: 0,
        duration_ms: 12,
        succeeded: true,
      }),
    );
    const client = makeClient();

    const result = await client.getResult('job-7');

    expect(result.job_id).toBe('job-7');
    expect(result.id).toBe('job-7');
    expect(result.result).toBe(42);
    expect(result.succeeded).toBe(true);
  });

  it('getLogs() filtrlarni query\'ga qo\'yadi va `logs` kalitini tushunadi', async () => {
    installFetch(() =>
      jsonResponse({
        job_id: 'job-1',
        logs: [{ stream: 'stdout', content: 'salom', sequence: 1, timestamp: 'now' }],
      }),
    );
    const client = makeClient();

    const logs = await client.getLogs('job-1', { afterSequence: 5, limit: 100 });

    expect(firstCall().url).toContain('after_sequence=5');
    expect(firstCall().url).toContain('limit=100');
    expect(logs).toHaveLength(1);
    expect(logs[0]?.content).toBe('salom');
  });

  it('getLogs() `items` kalitini ham tushunadi', async () => {
    installFetch(() =>
      jsonResponse({ items: [{ stream: 'stderr', content: 'xato', sequence: 2, timestamp: 'now' }] }),
    );
    const client = makeClient();

    const logs = await client.getLogs('job-1');

    expect(logs[0]?.stream).toBe('stderr');
  });

  it('getLogs() backendning haqiqiy `entries` kalitini o\'qiydi', async () => {
    // `JobLogsResponse` yozuvlarni `entries` da yuboradi — asosiy yo'l shu.
    installFetch(() =>
      jsonResponse({
        job_id: 'job-1',
        execution_id: 'exec-1',
        entries: [
          { stream: 'stdout', content: 'birinchi', sequence: 1, timestamp: 'now' },
          { stream: 'stderr', content: 'ikkinchi', sequence: 2, timestamp: 'now' },
        ],
        next_sequence: 3,
        has_more: false,
        count: 2,
      }),
    );
    const client = makeClient();

    const logs = await client.getLogs('job-1');

    expect(logs).toHaveLength(2);
    expect(logs[0]?.content).toBe('birinchi');
    expect(logs[1]?.stream).toBe('stderr');
  });
});

// ---------------------------------------------------------------------------
// listJobs()
// ---------------------------------------------------------------------------

describe('listJobs()', () => {
  it('filtrlarni snake_case query parametrlariga o\'tkazadi', async () => {
    installFetch(() =>
      jsonResponse({
        items: [makeJob()],
        pagination: {
          page: 2,
          page_size: 10,
          total: 25,
          total_pages: 3,
          has_next: true,
          has_prev: true,
        },
      }),
    );
    const client = makeClient();

    const page = await client.listJobs({
      status: ['queued', 'running'],
      runtime: 'python',
      priority: 'high',
      search: 'rasm',
      page: 2,
      pageSize: 10,
      sortBy: 'created_at',
      sortOrder: 'desc',
    });

    const url = firstCall().url;
    expect(url).toContain('status=queued&status=running');
    expect(url).toContain('runtime=python');
    expect(url).toContain('priority=high');
    expect(url).toContain('page=2');
    expect(url).toContain('page_size=10');
    expect(url).toContain('sort_by=created_at');
    expect(url).toContain('sort_order=desc');
    expect(page.items).toHaveLength(1);
    expect(page.pagination.total).toBe(25);
    expect(page.pagination.has_next).toBe(true);
  });

  it('backend xom massiv qaytarsa ham {items, pagination} shaklini beradi', async () => {
    installFetch(() => jsonResponse([makeJob(), makeJob({ id: 'job-2' })]));
    const client = makeClient();

    const page = await client.listJobs({ page: 1, pageSize: 20 });

    expect(page.items).toHaveLength(2);
    expect(page.pagination).toEqual({
      page: 1,
      page_size: 20,
      total: 2,
      total_pages: 1,
      has_next: false,
      has_prev: false,
    });
  });
});

// ---------------------------------------------------------------------------
// waitForResult()
// ---------------------------------------------------------------------------

describe('waitForResult()', () => {
  it('job tugaguncha polling qiladi va natijani qaytaradi', async () => {
    installSequence(
      () => jsonResponse(makeJob({ status: 'queued' })),
      () => jsonResponse(makeJob({ status: 'running' })),
      () => jsonResponse(makeJob({ status: 'success' })),
      () => jsonResponse({ job_id: 'job-1', status: 'success', stdout: 'tayyor', exit_code: 0 }),
    );
    const client = makeClient();
    const seen: string[] = [];

    const result = await client.waitForResult('job-1', {
      onUpdate: (job) => seen.push(job.status),
    });

    expect(seen).toEqual(['queued', 'running', 'success']);
    expect(result.stdout).toBe('tayyor');
    expect(calls).toHaveLength(4);
    expect(calls[3]?.url).toContain('/result');
  });

  it('dead_letter holatida JobFailedError tashlaydi', async () => {
    installFetch(() =>
      jsonResponse(
        makeJob({ status: 'dead_letter', failure_reason: 'timeout', exit_code: 137, retry_count: 3 }),
      ),
    );
    const client = makeClient();

    const error = await client.waitForResult('job-1').catch((e: unknown) => e);

    expect(error).toBeInstanceOf(JobFailedError);
    const failure = error as JobFailedError;
    expect(failure.status).toBe('dead_letter');
    expect(failure.failureReason).toBe('timeout');
    expect(failure.exitCode).toBe(137);
    expect(failure.code).toBe('JOB_FAILED');
  });

  it('failed holatida urinishlar qolgan bo\'lsa kutishni davom etadi', async () => {
    installSequence(
      () => jsonResponse(makeJob({ status: 'failed', retry_count: 1, max_retries: 3 })),
      () => jsonResponse(makeJob({ status: 'retrying', retry_count: 2, max_retries: 3 })),
      () => jsonResponse(makeJob({ status: 'success', retry_count: 2, max_retries: 3 })),
      () => jsonResponse({ job_id: 'job-1', status: 'success', stdout: 'oxiri' }),
    );
    const client = makeClient();

    const result = await client.waitForResult('job-1');

    expect(result.stdout).toBe('oxiri');
    expect(calls).toHaveLength(4);
  });

  it('failed holatida urinishlar tugagan bo\'lsa xato tashlaydi', async () => {
    installFetch(() => jsonResponse(makeJob({ status: 'failed', retry_count: 3, max_retries: 3 })));
    const client = makeClient();

    await expect(client.waitForResult('job-1')).rejects.toBeInstanceOf(JobFailedError);
    expect(calls).toHaveLength(1);
  });

  it('throwOnFailure: false bo\'lsa natijani qaytaradi', async () => {
    installSequence(
      () => jsonResponse(makeJob({ status: 'dead_letter', retry_count: 3 })),
      () => jsonResponse({ job_id: 'job-1', status: 'dead_letter', error: 'timeout' }),
    );
    const client = makeClient();

    const result = await client.waitForResult('job-1', { throwOnFailure: false });

    expect(result.error).toBe('timeout');
  });

  it('vaqt tugasa TimeoutError tashlaydi', async () => {
    installFetch(() => jsonResponse(makeJob({ status: 'running' })));
    const client = makeClient();

    const error = await client
      .waitForResult('job-1', { timeoutMs: 15, pollIntervalMs: 1 })
      .catch((e: unknown) => e);

    expect(error).toBeInstanceOf(TimeoutError);
    expect((error as TimeoutError).timeoutMs).toBe(15);
    expect((error as TimeoutError).message).toContain('running');
  });
});

// ---------------------------------------------------------------------------
// cancel, dlq, webhook, billing
// ---------------------------------------------------------------------------

describe('boshqa endpointlar', () => {
  it('cancel() POST /cancel ga boradi va javobni normallashtiradi', async () => {
    installFetch(() =>
      jsonResponse({ job_id: 'job-1', status: 'cancelled', cancelled_at: '2026-10-04T10:05:00Z' }),
    );
    const client = makeClient();

    const result = await client.cancel('job-1');

    expect(firstCall().method).toBe('POST');
    expect(firstCall().url).toBe('https://api.test.durabl.dev/api/v1/jobs/job-1/cancel');
    expect(result).toEqual({
      job_id: 'job-1',
      status: 'cancelled',
      cancelled_at: '2026-10-04T10:05:00Z',
    });
  });

  it('cancel() to\'liq Job obyekti qaytarilsa ham ishlaydi', async () => {
    installFetch(() => jsonResponse(makeJob({ status: 'cancelled' })));
    const client = makeClient();

    const result = await client.cancel('job-1');

    expect(result.job_id).toBe('job-1');
    expect(result.status).toBe('cancelled');
  });

  it('listDlq() filtrlarni uzatadi', async () => {
    installFetch(() =>
      jsonResponse({
        items: [
          {
            id: 'dlq-1',
            job_id: 'job-9',
            failure_reason: 'max_retries_exceeded',
            failed_at: '2026-10-04T09:00:00Z',
            retry_count: 3,
            resolved: false,
          },
        ],
        pagination: {
          page: 1,
          page_size: 20,
          total: 1,
          total_pages: 1,
          has_next: false,
          has_prev: false,
        },
      }),
    );
    const client = makeClient();

    const page = await client.listDlq({ resolved: false, failureReason: 'max_retries_exceeded' });

    expect(firstCall().url).toContain('resolved=false');
    expect(firstCall().url).toContain('failure_reason=max_retries_exceeded');
    expect(page.items[0]?.job_id).toBe('job-9');
  });

  it('retryDlq() izohni tanada yuboradi va `DlqRetryResponse` ni o\'qiydi', async () => {
    // Backend `DlqRetryResponse` shakli: entry_id, job_id, status,
    // requeued, resolved, retried_at, message.
    installFetch(() =>
      jsonResponse({
        entry_id: 'dlq-1',
        job_id: 'job-9',
        status: 'queued',
        requeued: true,
        resolved: true,
        retried_at: '2026-01-01T00:00:00Z',
        message: 'navbatga qaytarildi',
      }),
    );
    const client = makeClient();

    const result = await client.retryDlq('dlq-1', { notes: 'qo\'lda tekshirildi' });

    expect(firstCall().url).toBe('https://api.test.durabl.dev/api/v1/dlq/dlq-1/retry');
    expect(firstCall().body).toEqual({ notes: 'qo\'lda tekshirildi' });
    expect(result).toEqual({
      job_id: 'job-9',
      entry_id: 'dlq-1',
      status: 'queued',
      requeued: true,
      resolved: true,
      retried_at: '2026-01-01T00:00:00Z',
      message: 'navbatga qaytarildi',
    });
  });

  it('createWebhook() tanani snake_case ga o\'tkazadi', async () => {
    installFetch(() =>
      jsonResponse(
        {
          id: 'wh-1',
          url: 'https://example.com/hook',
          events: ['job.succeeded'],
          is_active: true,
          secret: 'whsec_x',
        },
        201,
      ),
    );
    const client = makeClient();

    const webhook = await client.createWebhook({
      url: 'https://example.com/hook',
      events: ['job.succeeded'],
      description: 'asosiy',
      isActive: true,
    });

    expect(firstCall().body).toEqual({
      url: 'https://example.com/hook',
      events: ['job.succeeded'],
      description: 'asosiy',
      is_active: true,
    });
    expect(webhook.secret).toBe('whsec_x');
  });

  it('createWebhook() bo\'sh url bilan so\'rov yubormaydi', async () => {
    installFetch(() => jsonResponse({}, 201));
    const client = makeClient();

    await expect(client.createWebhook({ url: '' })).rejects.toBeInstanceOf(DurablError);
    expect(calls).toHaveLength(0);
  });

  it('listWebhooks() {items} shaklini massivga aylantiradi', async () => {
    installFetch(() =>
      jsonResponse({
        items: [{ id: 'wh-1', url: 'https://example.com/hook', events: [], is_active: true }],
        pagination: {
          page: 1,
          page_size: 20,
          total: 1,
          total_pages: 1,
          has_next: false,
          has_prev: false,
        },
      }),
    );
    const client = makeClient();

    const webhooks = await client.listWebhooks();

    expect(webhooks).toHaveLength(1);
    expect(webhooks[0]?.id).toBe('wh-1');
  });

  it('deleteWebhook() 204 (tanasiz) javobni muammosiz hazm qiladi', async () => {
    installFetch(() => new Response(null, { status: 204 }));
    const client = makeClient();

    await expect(client.deleteWebhook('wh-1')).resolves.toBeUndefined();
    expect(firstCall().method).toBe('DELETE');
    expect(firstCall().url).toBe('https://api.test.durabl.dev/api/v1/webhooks/wh-1');
  });

  it('testWebhook() hodisa nomini yuboradi', async () => {
    installFetch(() => jsonResponse({ success: true, status_code: 200, duration_ms: 42 }));
    const client = makeClient();

    const result = await client.testWebhook('wh-1', { event: 'job.failed' });

    expect(firstCall().url).toBe('https://api.test.durabl.dev/api/v1/webhooks/wh-1/test');
    expect(firstCall().body).toEqual({ event: 'job.failed' });
    expect(result.success).toBe(true);
  });

  it('usage() billing endpointiga boradi', async () => {
    installFetch(() =>
      jsonResponse({
        period: '2026-10',
        plan: 'pro',
        job_count: 120,
        success_count: 118,
        failed_count: 2,
        execution_seconds: 345.5,
      }),
    );
    const client = makeClient();

    const usage = await client.usage();

    expect(firstCall().url).toBe('https://api.test.durabl.dev/api/v1/billing/usage');
    expect(usage.plan).toBe('pro');
    expect(usage.job_count).toBe(120);
  });

  it('ping() /health ga (versiya prefiksisiz) boradi', async () => {
    installFetch(() => jsonResponse({ status: 'ok', version: '1.0.0' }));
    const client = makeClient();

    const health = await client.ping();

    expect(firstCall().url).toBe('https://api.test.durabl.dev/health');
    expect(health.status).toBe('ok');
  });
});

// ---------------------------------------------------------------------------
// Xatolar
// ---------------------------------------------------------------------------

describe('xato kodlari', () => {
  it('401 -> AuthenticationError', async () => {
    installFetch(() => errorResponse(401, 'INVALID_API_KEY', 'API kalit yaroqsiz'));
    const client = makeClient();

    const error = await client.getJob('job-1').catch((e: unknown) => e);

    expect(error).toBeInstanceOf(AuthenticationError);
    const apiError = error as AuthenticationError;
    expect(apiError.status).toBe(401);
    expect(apiError.code).toBe('INVALID_API_KEY');
    expect(apiError.requestId).toBe('req-123');
  });

  it('404 -> NotFoundError', async () => {
    installFetch(() => errorResponse(404, 'JOB_NOT_FOUND', 'Job topilmadi'));
    const client = makeClient();

    await expect(client.getJob('yo-q')).rejects.toBeInstanceOf(NotFoundError);
  });

  it('402 -> QuotaExceededError', async () => {
    installFetch(() => errorResponse(402, 'QUOTA_EXCEEDED', 'Oylik kvota tugadi'));
    const client = makeClient();

    await expect(client.submit({ code: 'x', runtime: 'python' })).rejects.toBeInstanceOf(
      QuotaExceededError,
    );
  });

  it('422 -> ValidationError va details saqlanadi', async () => {
    installFetch(() =>
      errorResponse(422, 'CODE_VALIDATION_FAILED', 'Kod taqiqlangan import ishlatadi', {
        violations: ['subprocess'],
      }),
    );
    const client = makeClient();

    const error = await client
      .submit({ code: 'import subprocess', runtime: 'python' })
      .catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ValidationError);
    expect((error as ValidationError).details).toEqual({ violations: ['subprocess'] });
  });

  it('409 -> umumiy DurablApiError (natija hali tayyor emas)', async () => {
    installFetch(() => errorResponse(409, 'RESULT_NOT_READY', 'Natija hali tayyor emas'));
    const client = makeClient();

    const error = await client.getResult('job-1').catch((e: unknown) => e);

    expect(error).toBeInstanceOf(DurablApiError);
    expect(error).not.toBeInstanceOf(NotFoundError);
    expect((error as DurablApiError).code).toBe('RESULT_NOT_READY');
  });

  it('429 -> RateLimitError va Retry-After o\'qiladi', async () => {
    installFetch(() =>
      jsonResponse({ error: { code: 'RATE_LIMIT_EXCEEDED', message: 'Juda ko\'p so\'rov' } }, 429, {
        'retry-after': '7',
      }),
    );
    const client = makeClient({ maxRetries: 0 });

    const error = await client.getJob('job-1').catch((e: unknown) => e);

    expect(error).toBeInstanceOf(RateLimitError);
    expect((error as RateLimitError).retryAfterSeconds).toBe(7);
  });

  it('JSON bo\'lmagan xato javobini ham xabar sifatida o\'qiydi', async () => {
    installFetch(() => new Response('Bad Gateway', { status: 502 }));
    const client = makeClient({ maxRetries: 0 });

    const error = await client.getJob('job-1').catch((e: unknown) => e);

    expect(error).toBeInstanceOf(DurablApiError);
    expect((error as DurablApiError).message).toBe('Bad Gateway');
    expect((error as DurablApiError).code).toBe('INTERNAL_ERROR');
  });
});

// ---------------------------------------------------------------------------
// Qayta urinish (retry) va timeout
// ---------------------------------------------------------------------------

describe('qayta urinish', () => {
  it('429 dan keyin qayta urinadi va muvaffaqiyatga erishadi', async () => {
    installSequence(
      () => jsonResponse({ error: { code: 'RATE_LIMIT_EXCEEDED', message: 'kuting' } }, 429),
      () => jsonResponse(makeJob({ status: 'success' })),
    );
    const client = makeClient({ maxRetries: 2 });

    const job = await client.getJob('job-1');

    expect(job.status).toBe('success');
    expect(calls).toHaveLength(2);
  });

  it('5xx larni maxRetries marta qayta uradi, keyin xato tashlaydi', async () => {
    installFetch(() => jsonResponse({ error: { code: 'DATABASE_ERROR', message: 'DB yiqildi' } }, 503));
    const client = makeClient({ maxRetries: 2 });

    const error = await client.getJob('job-1').catch((e: unknown) => e);

    expect(error).toBeInstanceOf(DurablApiError);
    expect((error as DurablApiError).status).toBe(503);
    // 1 asosiy + 2 qayta urinish
    expect(calls).toHaveLength(3);
  });

  it('4xx larni qayta urinmaydi', async () => {
    installFetch(() => errorResponse(404, 'JOB_NOT_FOUND', 'topilmadi'));
    const client = makeClient({ maxRetries: 3 });

    await expect(client.getJob('job-1')).rejects.toBeInstanceOf(NotFoundError);
    expect(calls).toHaveLength(1);
  });

  it('tarmoq xatosidan keyin qayta urinadi', async () => {
    installSequence(
      () => {
        throw new TypeError('fetch failed');
      },
      () => jsonResponse(makeJob({ status: 'running' })),
    );
    const client = makeClient({ maxRetries: 1 });

    const job = await client.getJob('job-1');

    expect(job.status).toBe('running');
    expect(calls).toHaveLength(2);
  });

  it('tarmoq xatosi tugamasa NETWORK_ERROR kodi bilan xato tashlaydi', async () => {
    installFetch(() => {
      throw new TypeError('fetch failed');
    });
    const client = makeClient({ maxRetries: 1 });

    const error = await client.ping().catch((e: unknown) => e);

    expect(error).toBeInstanceOf(DurablError);
    expect((error as DurablError).code).toBe('NETWORK_ERROR');
    expect(calls).toHaveLength(2);
  });

  it('so\'rov vaqti tugasa TimeoutError tashlaydi', async () => {
    installFetch(
      (call) =>
        new Promise<Response>((_resolve, reject) => {
          call.signal?.addEventListener('abort', () => reject(new Error('aborted')));
        }),
    );
    const client = makeClient({ timeoutMs: 20, maxRetries: 0 });

    const error = await client.ping().catch((e: unknown) => e);

    expect(error).toBeInstanceOf(TimeoutError);
    expect((error as TimeoutError).timeoutMs).toBe(20);
  });
});

// ---------------------------------------------------------------------------
// Sozlamalar va JobHandle
// ---------------------------------------------------------------------------

describe('sozlamalar va JobHandle', () => {
  it('qo\'shimcha header\'lar har bir so\'rovga qo\'shiladi', async () => {
    installFetch(() => jsonResponse(makeJob()));
    const client = makeClient({ headers: { 'X-Tenant': 'durabl-demo' }, userAgent: 'my-app/2.0' });

    await client.getJob('job-1');

    expect(firstCall().headers['x-tenant']).toBe('durabl-demo');
    expect(firstCall().headers['user-agent']).toBe('my-app/2.0');
  });

  it('fetch parametri global fetch o\'rnini bosadi', async () => {
    const custom = vi.fn(async (): Promise<Response> => jsonResponse(makeJob({ status: 'success' })));
    vi.stubGlobal('fetch', undefined);
    const client = makeClient({ fetch: custom });

    await expect(client.getStatus('job-1')).resolves.toBe('success');
    expect(custom).toHaveBeenCalledTimes(1);
  });

  it('JobHandle metodlari client\'ga delegatsiya qiladi', async () => {
    installSequence(
      () => jsonResponse(makeJob({ status: 'queued' }), 201),
      () => jsonResponse(makeJob({ status: 'running' })),
      () => jsonResponse({ logs: [{ stream: 'stdout', content: 'a', sequence: 1, timestamp: 'now' }] }),
      () => jsonResponse({ job_id: 'job-1', status: 'cancelled' }),
    );
    const client = makeClient();

    const handle = await client.submit({ code: 'print(1)', runtime: 'python' });
    expect(handle.snapshot?.status).toBe('queued');

    await expect(handle.status()).resolves.toBe('running');
    expect(handle.snapshot?.status).toBe('running');

    await expect(handle.logs()).resolves.toHaveLength(1);

    const cancelled = await handle.cancel();
    expect(cancelled.status).toBe('cancelled');
    expect(handle.snapshot?.status).toBe('cancelled');
    expect(handle.toJSON().id).toBe('job-1');
    expect(handle.toString()).toContain('job-1');
  });

  it('JobHandle identifikatordan ham yasaladi', async () => {
    installFetch(() => jsonResponse({ job_id: 'job-7', status: 'success', stdout: 'ok' }));
    const client = makeClient();

    const handle = new JobHandle(client, 'job-7');

    expect(handle.snapshot).toBeNull();
    expect(handle.created).toBeNull();
    await expect(handle.result()).resolves.toMatchObject({ stdout: 'ok' });
  });
});
