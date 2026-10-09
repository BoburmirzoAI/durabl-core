/**
 * `DurablClient` — Durabl REST API bilan ishlovchi asosiy klass.
 *
 * Xususiyatlari:
 *   * Tashqi bog'liqlik YO'Q — global `fetch` ishlatiladi (Node 18+, brauzer).
 *   * `X-API-Key` autentifikatsiyasi.
 *   * `POST /jobs` uchun `Idempotency-Key` (berilmasa avtomatik yaratiladi) —
 *     tarmoq uzilib qayta urinilsa ham job ikki marta yaratilmaydi.
 *   * 429 va 5xx javoblarida eksponensial backoff bilan qayta urinish;
 *     `Retry-After` header'i hurmat qilinadi.
 *   * Har bir so'rov `AbortSignal` bilan vaqt limitiga tushadi.
 *   * `waitForResult()` — polling, interval asta-sekin oshadi (API'ni urmaslik uchun).
 */

import {
  DurablError,
  JobFailedError,
  TimeoutError,
  errorFromResponse,
} from './errors.js';
import { JobHandle } from './job.js';
import { RUNTIMES, isSettledJob } from './types.js';
import type {
  CancelResult,
  CreateWebhookOptions,
  DlqEntry,
  DlqRetryResult,
  DurablClientOptions,
  FetchLike,
  GetLogsOptions,
  HealthStatus,
  Job,
  JobLog,
  JobResult,
  JobStatus,
  ListDlqOptions,
  ListJobsOptions,
  PaginatedResponse,
  RequestOptions,
  RetryDlqOptions,
  SubmitOptions,
  TestWebhookOptions,
  UsageSummary,
  WaitOptions,
  Webhook,
  WebhookTestResult,
} from './types.js';

// ---------------------------------------------------------------------------
// Standart qiymatlar
// ---------------------------------------------------------------------------

const DEFAULT_BASE_URL = 'https://api.durabl.dev';
const DEFAULT_API_PREFIX = '/api/v1';
const DEFAULT_TIMEOUT_MS = 30_000;
const DEFAULT_MAX_RETRIES = 3;
const DEFAULT_RETRY_BASE_DELAY_MS = 500;
const DEFAULT_RETRY_MAX_DELAY_MS = 10_000;
const DEFAULT_POLL_INTERVAL_MS = 1_000;
const DEFAULT_MAX_POLL_INTERVAL_MS = 5_000;
const DEFAULT_WAIT_TIMEOUT_MS = 300_000;
const JITTER_RATIO = 0.25;
const POLL_GROWTH_FACTOR = 1.5;

/** SDK versiyasi — `User-Agent` da yuboriladi. */
export const SDK_VERSION = '1.0.0';

// ---------------------------------------------------------------------------
// Ichki turlar
// ---------------------------------------------------------------------------

/** URL query parametrlari uchun qabul qilinadigan qiymatlar. */
type QueryValue = string | number | boolean | Date | null | undefined | string[];

/** Query parametrlar to'plami. */
type QueryParams = Record<string, QueryValue>;

/** Bitta ichki HTTP so'rovining ta'rifi. */
interface InternalRequest {
  method: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  path: string;
  query?: QueryParams;
  body?: unknown;
  idempotencyKey?: string;
  signal?: AbortSignal;
  timeoutMs?: number;
  /** `true` bo'lsa `/api/v1` prefiksi qo'shilmaydi (masalan `/health`). */
  skipPrefix?: boolean;
}

/** Muvaffaqiyatli javob va uning meta-ma'lumoti. */
interface ApiResponse<T> {
  data: T;
  status: number;
  requestId: string | null;
}

// ---------------------------------------------------------------------------
// DurablClient
// ---------------------------------------------------------------------------

/** Durabl API mijozi. */
export class DurablClient {
  /** Normallashtirilgan API manzili (oxiridagi `/` olib tashlangan). */
  readonly baseUrl: string;

  /** API versiya prefiksi. */
  readonly apiPrefix: string = DEFAULT_API_PREFIX;

  private readonly apiKey: string;
  private readonly timeoutMs: number;
  private readonly maxRetries: number;
  private readonly retryBaseDelayMs: number;
  private readonly retryMaxDelayMs: number;
  private readonly retryJitter: boolean;
  private readonly pollIntervalMs: number;
  private readonly maxPollIntervalMs: number;
  private readonly autoIdempotency: boolean;
  private readonly userAgent: string;
  private readonly extraHeaders: Record<string, string>;
  private readonly fetchImpl: FetchLike | undefined;

  constructor(options: DurablClientOptions) {
    const apiKey = typeof options.apiKey === 'string' ? options.apiKey.trim() : '';
    if (apiKey === '') {
      throw new DurablError(
        '`apiKey` majburiy: DurablClient yaratish uchun API kalit kerak (durabl_...)',
        { code: 'MISSING_API_KEY' },
      );
    }

    this.apiKey = apiKey;
    this.baseUrl = normalizeBaseUrl(options.baseUrl ?? DEFAULT_BASE_URL);
    this.timeoutMs = options.timeoutMs ?? DEFAULT_TIMEOUT_MS;
    this.maxRetries = Math.max(0, options.maxRetries ?? DEFAULT_MAX_RETRIES);
    this.retryBaseDelayMs = Math.max(0, options.retryBaseDelayMs ?? DEFAULT_RETRY_BASE_DELAY_MS);
    this.retryMaxDelayMs = Math.max(0, options.retryMaxDelayMs ?? DEFAULT_RETRY_MAX_DELAY_MS);
    this.retryJitter = options.retryJitter ?? true;
    this.pollIntervalMs = Math.max(1, options.pollIntervalMs ?? DEFAULT_POLL_INTERVAL_MS);
    this.maxPollIntervalMs = Math.max(
      this.pollIntervalMs,
      options.maxPollIntervalMs ?? DEFAULT_MAX_POLL_INTERVAL_MS,
    );
    this.autoIdempotency = options.autoIdempotency ?? true;
    this.userAgent = options.userAgent ?? `durabl-js/${SDK_VERSION}`;
    this.extraHeaders = { ...(options.headers ?? {}) };
    this.fetchImpl = options.fetch;
  }

  // -------------------------------------------------------------------------
  // Job'lar
  // -------------------------------------------------------------------------

  /**
   * Yangi job yuboradi.
   *
   * `idempotencyKey` berilmasa avtomatik UUID yaratiladi: shu tufayli tarmoq
   * xatosidan keyingi qayta urinish bir xil job'ni ikkinchi marta yaratmaydi.
   * Avtomatik yaratishni `autoIdempotency: false` bilan o'chirish mumkin.
   *
   * @returns `JobHandle` — `.id`, `.wait()`, `.status()` va h.k.
   */
  async submit(options: SubmitOptions): Promise<JobHandle> {
    if (typeof options.code !== 'string' || options.code.trim() === '') {
      throw new DurablError('`code` bo\'sh bo\'lishi mumkin emas', { code: 'INVALID_ARGUMENT' });
    }
    if (!RUNTIMES.includes(options.runtime)) {
      throw new DurablError(
        `Noma'lum runtime: "${String(options.runtime)}" — ruxsat etilgan: ${RUNTIMES.join(', ')}`,
        { code: 'INVALID_ARGUMENT' },
      );
    }

    const idempotencyKey =
      options.idempotencyKey ?? (this.autoIdempotency ? generateIdempotencyKey() : undefined);

    const response = await this.requestRaw<Job>({
      method: 'POST',
      path: '/jobs',
      body: buildSubmitBody(options),
      idempotencyKey,
      signal: options.signal,
    });

    return new JobHandle(this, response.data, { created: response.status === 201 });
  }

  /** Bitta job'ning to'liq yozuvini oladi. */
  async getJob(jobId: string, options: RequestOptions = {}): Promise<Job> {
    const response = await this.requestRaw<Job>({
      method: 'GET',
      path: `/jobs/${encodeURIComponent(jobId)}`,
      signal: options.signal,
    });
    return response.data;
  }

  /** Faqat job holatini oladi (`pending`, `running`, `success`, ...). */
  async getStatus(jobId: string, options: RequestOptions = {}): Promise<JobStatus> {
    const job = await this.getJob(jobId, options);
    return job.status;
  }

  /**
   * Job natijasini oladi.
   *
   * Job hali tugamagan bo'lsa backend 409 (`RESULT_NOT_READY`) qaytaradi —
   * SDK buni `DurablApiError` sifatida tashlaydi. Kutish uchun
   * `waitForResult()` ishlatish qulayroq.
   */
  async getResult(jobId: string, options: RequestOptions = {}): Promise<JobResult> {
    const response = await this.requestRaw<unknown>({
      method: 'GET',
      path: `/jobs/${encodeURIComponent(jobId)}/result`,
      signal: options.signal,
    });
    return normalizeJobResult(response.data, jobId);
  }

  /**
   * Job tugashini kutadi va natijani qaytaradi (polling).
   *
   * Polling intervali har qadamda 1.5 barobar oshadi (`maxPollIntervalMs` gacha) —
   * tez tugaydigan job'lar uchun javob tez keladi, uzoq job'lar uchun API
   * behuda urilmaydi.
   *
   * @throws {JobFailedError} Job muvaffaqiyatsiz tugadi (`throwOnFailure: false` bo'lmasa).
   * @throws {TimeoutError}   `timeoutMs` ichida tugamadi.
   */
  async waitForResult(jobId: string, options: WaitOptions = {}): Promise<JobResult> {
    const timeoutMs = options.timeoutMs ?? DEFAULT_WAIT_TIMEOUT_MS;
    const maxInterval = Math.max(1, options.maxPollIntervalMs ?? this.maxPollIntervalMs);
    const throwOnFailure = options.throwOnFailure ?? true;
    const deadline = Date.now() + timeoutMs;
    let interval = Math.max(1, options.pollIntervalMs ?? this.pollIntervalMs);
    let lastStatus: JobStatus = 'pending';

    for (;;) {
      const job = await this.getJob(jobId, { signal: options.signal });
      lastStatus = job.status;
      options.onUpdate?.(job);

      if (isSettledJob(job)) {
        if (job.status === 'success' || !throwOnFailure) {
          return await this.getResult(jobId, { signal: options.signal });
        }
        throw new JobFailedError(job);
      }

      const remaining = deadline - Date.now();
      if (remaining <= 0) {
        throw new TimeoutError(
          `Job ${jobId} ${timeoutMs} ms ichida tugamadi (oxirgi holat: ${lastStatus})`,
          { timeoutMs, details: { job_id: jobId, last_status: lastStatus } },
        );
      }

      await sleep(Math.min(interval, remaining), options.signal);
      interval = Math.min(Math.round(interval * POLL_GROWTH_FACTOR), maxInterval);
    }
  }

  /** Job'ni bekor qiladi (faqat yakuniy holatga o'tmagan job'lar uchun). */
  async cancel(jobId: string, options: RequestOptions = {}): Promise<CancelResult> {
    const response = await this.requestRaw<unknown>({
      method: 'POST',
      path: `/jobs/${encodeURIComponent(jobId)}/cancel`,
      signal: options.signal,
    });
    return normalizeCancelResult(response.data, jobId);
  }

  /** Job'lar ro'yxatini filtr va sahifalash bilan oladi. */
  async listJobs(options: ListJobsOptions = {}): Promise<PaginatedResponse<Job>> {
    const page = options.page ?? 1;
    const pageSize = options.pageSize ?? 20;
    const response = await this.requestRaw<unknown>({
      method: 'GET',
      path: '/jobs',
      query: {
        status: options.status,
        runtime: options.runtime,
        priority: options.priority,
        search: options.search,
        tags: options.tags,
        start: options.start,
        end: options.end,
        page,
        page_size: pageSize,
        sort_by: options.sortBy,
        sort_order: options.sortOrder,
      },
      signal: options.signal,
    });
    return normalizePage<Job>(response.data, page, pageSize);
  }

  /**
   * Job loglarini oladi.
   *
   * Backend `JobLogsResponse` ni qaytaradi — yozuvlar `entries` kalitida
   * (`items` EMAS). Zaxira sifatida `items`/`logs` va xom massiv ham
   * tushuniladi.
   */
  async getLogs(jobId: string, options: GetLogsOptions = {}): Promise<JobLog[]> {
    const response = await this.requestRaw<unknown>({
      method: 'GET',
      path: `/jobs/${encodeURIComponent(jobId)}/logs`,
      query: { after_sequence: options.afterSequence, limit: options.limit },
      signal: options.signal,
    });
    return extractList<JobLog>(response.data, 'entries', 'logs');
  }

  // -------------------------------------------------------------------------
  // DLQ (o'lik xatlar navbati)
  // -------------------------------------------------------------------------

  /** DLQ yozuvlari ro'yxati. */
  async listDlq(options: ListDlqOptions = {}): Promise<PaginatedResponse<DlqEntry>> {
    const page = options.page ?? 1;
    const pageSize = options.pageSize ?? 20;
    const response = await this.requestRaw<unknown>({
      method: 'GET',
      path: '/dlq',
      query: {
        resolved: options.resolved,
        failure_reason: options.failureReason,
        page,
        page_size: pageSize,
      },
      signal: options.signal,
    });
    return normalizePage<DlqEntry>(response.data, page, pageSize);
  }

  /** DLQ yozuvini qayta navbatga qo'yadi (qo'lda retry). */
  async retryDlq(entryId: string, options: RetryDlqOptions = {}): Promise<DlqRetryResult> {
    const response = await this.requestRaw<unknown>({
      method: 'POST',
      path: `/dlq/${encodeURIComponent(entryId)}/retry`,
      body: options.notes === undefined ? undefined : { notes: options.notes },
      signal: options.signal,
    });
    return normalizeDlqRetryResult(response.data, entryId);
  }

  // -------------------------------------------------------------------------
  // Webhook'lar
  // -------------------------------------------------------------------------

  /** Yangi webhook yaratadi. Javobdagi `secret` ni saqlab qo'yish kerak. */
  async createWebhook(options: CreateWebhookOptions): Promise<Webhook> {
    if (typeof options.url !== 'string' || options.url.trim() === '') {
      throw new DurablError('`url` bo\'sh bo\'lishi mumkin emas', { code: 'INVALID_ARGUMENT' });
    }
    const body: Record<string, unknown> = { url: options.url };
    if (options.events !== undefined) {
      body['events'] = options.events;
    }
    if (options.description !== undefined) {
      body['description'] = options.description;
    }
    if (options.secret !== undefined) {
      body['secret'] = options.secret;
    }
    if (options.isActive !== undefined) {
      body['is_active'] = options.isActive;
    }

    const response = await this.requestRaw<Webhook>({
      method: 'POST',
      path: '/webhooks',
      body,
      signal: options.signal,
    });
    return response.data;
  }

  /** Foydalanuvchining barcha webhook'lari. */
  async listWebhooks(options: RequestOptions = {}): Promise<Webhook[]> {
    const response = await this.requestRaw<unknown>({
      method: 'GET',
      path: '/webhooks',
      signal: options.signal,
    });
    return extractList<Webhook>(response.data, 'webhooks');
  }

  /** Webhook'ni o'chiradi. */
  async deleteWebhook(webhookId: string, options: RequestOptions = {}): Promise<void> {
    await this.requestRaw<unknown>({
      method: 'DELETE',
      path: `/webhooks/${encodeURIComponent(webhookId)}`,
      signal: options.signal,
    });
  }

  /** Webhook'ga test so'rovi yuboradi (URL ishlashini tekshirish uchun). */
  async testWebhook(
    webhookId: string,
    options: TestWebhookOptions = {},
  ): Promise<WebhookTestResult> {
    const response = await this.requestRaw<WebhookTestResult>({
      method: 'POST',
      path: `/webhooks/${encodeURIComponent(webhookId)}/test`,
      body: options.event === undefined ? undefined : { event: options.event },
      signal: options.signal,
    });
    return response.data;
  }

  // -------------------------------------------------------------------------
  // Billing va salomatlik
  // -------------------------------------------------------------------------

  /** Joriy davr uchun foydalanish statistikasi. */
  async usage(options: RequestOptions = {}): Promise<UsageSummary> {
    const response = await this.requestRaw<UsageSummary>({
      method: 'GET',
      path: '/billing/usage',
      signal: options.signal,
    });
    return response.data;
  }

  /**
   * API tirikligini tekshiradi (`GET /health`).
   *
   * Bu endpoint `/api/v1` prefiksi ostida emas va autentifikatsiya talab
   * qilmaydi, lekin header'lar baribir yuboriladi (zarari yo'q).
   */
  async ping(options: RequestOptions = {}): Promise<HealthStatus> {
    const response = await this.requestRaw<HealthStatus>({
      method: 'GET',
      path: '/health',
      skipPrefix: true,
      signal: options.signal,
    });
    return response.data;
  }

  // -------------------------------------------------------------------------
  // HTTP qatlami
  // -------------------------------------------------------------------------

  /**
   * Bitta API so'rovini bajaradi — retry, backoff va timeout bilan.
   *
   * 429 va 5xx javoblari hamda tarmoq xatolari `maxRetries` marta qayta
   * uriniladi; qolgan xatolar darhol tashlanadi (qayta urinish foydasiz).
   */
  private async requestRaw<T>(request: InternalRequest): Promise<ApiResponse<T>> {
    const url = this.buildUrl(request.path, request.query, request.skipPrefix ?? false);
    const headers: Record<string, string> = {
      Accept: 'application/json',
      'X-API-Key': this.apiKey,
      'User-Agent': this.userAgent,
      ...this.extraHeaders,
    };

    let bodyText: string | undefined;
    if (request.body !== undefined) {
      bodyText = JSON.stringify(request.body);
      headers['Content-Type'] = 'application/json';
    }
    if (request.idempotencyKey !== undefined && request.idempotencyKey !== '') {
      headers['Idempotency-Key'] = request.idempotencyKey;
    }

    const timeoutMs = request.timeoutMs ?? this.timeoutMs;

    for (let attempt = 0; ; attempt += 1) {
      const isLastAttempt = attempt >= this.maxRetries;
      let response: Response;

      try {
        response = await this.fetchOnce(
          url,
          { method: request.method, headers, body: bodyText },
          timeoutMs,
          request.signal,
        );
      } catch (error) {
        // Foydalanuvchi o'zi bekor qilgan bo'lsa qayta urinmaymiz.
        if (request.signal?.aborted === true) {
          throw error;
        }
        const failure =
          error instanceof TimeoutError
            ? error
            : new DurablError(`Durabl API'ga ulanib bo'lmadi: ${describeError(error)}`, {
                code: 'NETWORK_ERROR',
                cause: error,
                details: { url },
              });
        if (isLastAttempt) {
          throw failure;
        }
        await sleep(this.backoffDelay(attempt), request.signal);
        continue;
      }

      const requestId = response.headers.get('x-request-id');

      if (response.ok) {
        const data = await parseResponseBody<T>(response);
        return { data, status: response.status, requestId };
      }

      const retryAfterSeconds = parseRetryAfter(response.headers.get('retry-after'));
      const errorBody = await parseResponseBody<unknown>(response);

      if (isRetryableStatus(response.status) && !isLastAttempt) {
        const serverDelayMs =
          retryAfterSeconds === null ? this.backoffDelay(attempt) : retryAfterSeconds * 1000;
        // Server juda uzoq kutishni so'rasa ham `retryMaxDelayMs` dan oshmaymiz.
        await sleep(Math.min(serverDelayMs, this.retryMaxDelayMs), request.signal);
        continue;
      }

      throw errorFromResponse(response.status, errorBody, { requestId, retryAfterSeconds });
    }
  }

  /** Bitta `fetch` chaqiruvi — vaqt limiti va tashqi bekor qilish bilan. */
  private async fetchOnce(
    url: string,
    init: { method: string; headers: Record<string, string>; body: string | undefined },
    timeoutMs: number,
    signal: AbortSignal | undefined,
  ): Promise<Response> {
    const fetchImpl = this.fetchImpl ?? (globalThis.fetch as FetchLike | undefined);
    if (typeof fetchImpl !== 'function') {
      throw new DurablError(
        'Global `fetch` topilmadi: Node 18+ ishlatish yoki `fetch` parametrini berish kerak',
        { code: 'FETCH_UNAVAILABLE' },
      );
    }

    const requestInit: RequestInit = { method: init.method, headers: init.headers };
    if (init.body !== undefined) {
      requestInit.body = init.body;
    }

    if (timeoutMs <= 0 && signal === undefined) {
      return await fetchImpl(url, requestInit);
    }

    const controller = new AbortController();
    let timedOut = false;
    const timer =
      timeoutMs > 0
        ? setTimeout(() => {
            timedOut = true;
            controller.abort();
          }, timeoutMs)
        : undefined;

    const onExternalAbort = (): void => controller.abort();
    if (signal !== undefined) {
      if (signal.aborted) {
        controller.abort();
      } else {
        signal.addEventListener('abort', onExternalAbort, { once: true });
      }
    }

    try {
      return await fetchImpl(url, { ...requestInit, signal: controller.signal });
    } catch (error) {
      if (timedOut) {
        throw new TimeoutError(`So'rov ${timeoutMs} ms ichida javob bermadi`, {
          timeoutMs,
          cause: error,
          details: { url },
        });
      }
      throw error;
    } finally {
      if (timer !== undefined) {
        clearTimeout(timer);
      }
      signal?.removeEventListener('abort', onExternalAbort);
    }
  }

  /** To'liq URL yasaydi (prefiks + yo'l + query). */
  private buildUrl(path: string, query: QueryParams | undefined, skipPrefix: boolean): string {
    const prefix = skipPrefix ? '' : this.apiPrefix;
    const normalizedPath = path.startsWith('/') ? path : `/${path}`;
    const base = `${this.baseUrl}${prefix}${normalizedPath}`;
    const search = encodeQuery(query);
    return search === '' ? base : `${base}?${search}`;
  }

  /** Eksponensial backoff kechikishi (ms). */
  private backoffDelay(attempt: number): number {
    const raw = this.retryBaseDelayMs * 2 ** attempt;
    const capped = Math.min(raw, this.retryMaxDelayMs);
    if (!this.retryJitter) {
      return capped;
    }
    // Jitter — ko'p mijoz bir vaqtda qayta urinmasligi uchun.
    return Math.round(capped * (1 + Math.random() * JITTER_RATIO));
  }
}

// ---------------------------------------------------------------------------
// Modul darajasidagi yordamchilar
// ---------------------------------------------------------------------------

/**
 * Berilgan vaqt kutadi; `signal` bekor qilinsa darhol xato bilan tugaydi.
 */
export function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  if (ms <= 0) {
    return signal?.aborted === true ? Promise.reject(abortError()) : Promise.resolve();
  }
  return new Promise<void>((resolve, reject) => {
    let timer: ReturnType<typeof setTimeout> | undefined;
    const onAbort = (): void => {
      if (timer !== undefined) {
        clearTimeout(timer);
      }
      reject(abortError());
    };

    timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, ms);

    if (signal !== undefined) {
      if (signal.aborted) {
        clearTimeout(timer);
        reject(abortError());
        return;
      }
      signal.addEventListener('abort', onAbort, { once: true });
    }
  });
}

/** Bekor qilinganda tashlanadigan xato. */
function abortError(): DurablError {
  return new DurablError('Operatsiya bekor qilindi', { code: 'ABORTED' });
}

/** API manzilidan oxirgi `/` larni olib tashlaydi. */
function normalizeBaseUrl(baseUrl: string): string {
  const trimmed = baseUrl.trim();
  if (trimmed === '') {
    return DEFAULT_BASE_URL;
  }
  return trimmed.replace(/\/+$/, '');
}

/** 429 va 5xx — qayta urinishga arziydigan statuslar. */
function isRetryableStatus(status: number): boolean {
  return status === 429 || status >= 500;
}

/** `Retry-After` header'ini soniyaga aylantiradi (son yoki HTTP-sana). */
function parseRetryAfter(raw: string | null): number | null {
  if (raw === null || raw.trim() === '') {
    return null;
  }
  const asNumber = Number(raw.trim());
  if (Number.isFinite(asNumber) && asNumber >= 0) {
    return asNumber;
  }
  const asDate = Date.parse(raw);
  if (!Number.isNaN(asDate)) {
    return Math.max(0, Math.ceil((asDate - Date.now()) / 1000));
  }
  return null;
}

/** Javob tanasini JSON (yoki matn) sifatida o'qiydi. */
async function parseResponseBody<T>(response: Response): Promise<T> {
  if (response.status === 204 || response.status === 205 || response.status === 304) {
    return undefined as T;
  }
  let text: string;
  try {
    text = await response.text();
  } catch {
    return undefined as T;
  }
  if (text === '') {
    return undefined as T;
  }
  const contentType = response.headers.get('content-type') ?? '';
  const looksLikeJson = text.startsWith('{') || text.startsWith('[');
  if (contentType.includes('json') || looksLikeJson) {
    try {
      return JSON.parse(text) as T;
    } catch {
      // JSON emas — xom matn qaytariladi (xato xabari bo'lishi mumkin).
    }
  }
  return text as unknown as T;
}

/** Query parametrlarini kodlaydi; `undefined`/`null` lar tashlab ketiladi. */
function encodeQuery(query: QueryParams | undefined): string {
  if (query === undefined) {
    return '';
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null) {
      continue;
    }
    if (Array.isArray(value)) {
      for (const item of value) {
        params.append(key, item);
      }
      continue;
    }
    if (value instanceof Date) {
      params.append(key, value.toISOString());
      continue;
    }
    params.append(key, String(value));
  }
  return params.toString();
}

/** Sana yoki matnni ISO-8601 ga aylantiradi. */
function toIsoString(value: Date | string): string {
  return value instanceof Date ? value.toISOString() : value;
}

/** Qiymat oddiy obyektmi? */
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Xatodan o'qishga qulay xabar ajratadi. */
function describeError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

/**
 * Takrorlanmaslik kaliti yaratadi.
 *
 * `crypto.randomUUID` Node 18+ va zamonaviy brauzerlarda bor; bo'lmasa
 * (eski muhit yoki `http://` kontekst) zaxira variant ishlatiladi.
 */
function generateIdempotencyKey(): string {
  const webCrypto = globalThis.crypto as { randomUUID?: () => string } | undefined;
  if (webCrypto !== undefined && typeof webCrypto.randomUUID === 'function') {
    return webCrypto.randomUUID();
  }
  const random = Math.random().toString(36).slice(2);
  const extra = Math.random().toString(36).slice(2);
  return `durabl-${Date.now().toString(36)}-${random}${extra}`;
}

/** `SubmitOptions` ni backend `JobCreate` shakliga o'tkazadi. */
function buildSubmitBody(options: SubmitOptions): Record<string, unknown> {
  const body: Record<string, unknown> = {
    code: options.code,
    runtime: options.runtime,
  };

  const timeoutSeconds = options.timeoutSeconds ?? options.timeout;
  if (timeoutSeconds !== undefined) {
    body['timeout_seconds'] = timeoutSeconds;
  }
  const maxRetries = options.maxRetries ?? options.retries;
  if (maxRetries !== undefined) {
    body['max_retries'] = maxRetries;
  }
  if (options.priority !== undefined) {
    body['priority'] = options.priority;
  }
  if (options.payload !== undefined) {
    body['payload'] = options.payload;
  }
  if (options.envVars !== undefined) {
    body['env_vars'] = options.envVars;
  }
  if (options.scheduledAt !== undefined) {
    body['scheduled_at'] = toIsoString(options.scheduledAt);
  }
  if (options.cronExpression !== undefined) {
    body['cron_expression'] = options.cronExpression;
  }
  if (options.tags !== undefined) {
    body['tags'] = options.tags;
  }
  if (options.memoryMb !== undefined) {
    body['memory_mb'] = options.memoryMb;
  }
  if (options.cpus !== undefined) {
    body['cpus'] = options.cpus;
  }
  return body;
}

/**
 * Ro'yxat javobini `{ items, pagination }` shakliga keltiradi.
 *
 * Backend shartnomaga ko'ra aynan shu shaklni qaytaradi; bu funksiya faqat
 * himoya qatlami — xom massiv kelsa ham SDK buzilmaydi.
 */
function normalizePage<T>(raw: unknown, page: number, pageSize: number): PaginatedResponse<T> {
  if (Array.isArray(raw)) {
    return { items: raw as T[], pagination: buildPagination(raw.length, page, pageSize) };
  }
  if (isRecord(raw)) {
    const items = Array.isArray(raw['items']) ? (raw['items'] as T[]) : [];
    const pagination = raw['pagination'];
    if (isRecord(pagination)) {
      return { items, pagination: normalizePaginationMeta(pagination, page, pageSize, items.length) };
    }
    return { items, pagination: buildPagination(items.length, page, pageSize) };
  }
  return { items: [], pagination: buildPagination(0, page, pageSize) };
}

/** Yetishmayotgan pagination maydonlarini hisoblab to'ldiradi. */
function normalizePaginationMeta(
  raw: Record<string, unknown>,
  page: number,
  pageSize: number,
  itemCount: number,
): PaginatedResponse<unknown>['pagination'] {
  const resolvedPage = typeof raw['page'] === 'number' ? raw['page'] : page;
  const resolvedSize = typeof raw['page_size'] === 'number' ? raw['page_size'] : pageSize;
  const total = typeof raw['total'] === 'number' ? raw['total'] : itemCount;
  const fallback = buildPagination(total, resolvedPage, resolvedSize);
  return {
    page: resolvedPage,
    page_size: resolvedSize,
    total,
    total_pages: typeof raw['total_pages'] === 'number' ? raw['total_pages'] : fallback.total_pages,
    has_next: typeof raw['has_next'] === 'boolean' ? raw['has_next'] : fallback.has_next,
    has_prev: typeof raw['has_prev'] === 'boolean' ? raw['has_prev'] : fallback.has_prev,
  };
}

/** Pagination meta'sini noldan hisoblaydi. */
function buildPagination(
  total: number,
  page: number,
  pageSize: number,
): PaginatedResponse<unknown>['pagination'] {
  const totalPages = pageSize > 0 ? Math.ceil(total / pageSize) : 0;
  return {
    page,
    page_size: pageSize,
    total,
    total_pages: totalPages,
    has_next: page < totalPages,
    has_prev: page > 1,
  };
}

/**
 * Javobdan massivni ajratadi.
 *
 * Avval `items` (shartnoma shakli), keyin berilgan zaxira kalitlar
 * (masalan `entries` — `JobLogsResponse`), oxirida xom massiv tekshiriladi.
 */
function extractList<T>(raw: unknown, ...altKeys: string[]): T[] {
  if (Array.isArray(raw)) {
    return raw as T[];
  }
  if (isRecord(raw)) {
    for (const key of ['items', ...altKeys]) {
      const candidate = raw[key];
      if (Array.isArray(candidate)) {
        return candidate as T[];
      }
    }
  }
  return [];
}

/**
 * Natija javobini `JobResult` ga keltiradi.
 *
 * `JobResultResponse` job identifikatorini `id` kalitida yuboradi (`job_id`
 * EMAS), shuning uchun `job_id` shu yerda to'ldiriladi — aks holda turda
 * majburiy deb e'lon qilingan maydon ish vaqtida `undefined` bo'lib qolardi.
 */
function normalizeJobResult(raw: unknown, jobId: string): JobResult {
  if (!isRecord(raw)) {
    return { job_id: jobId, status: 'success' };
  }
  const selfId = typeof raw['id'] === 'string' ? raw['id'] : null;
  const ownId = typeof raw['job_id'] === 'string' ? raw['job_id'] : null;
  return {
    ...(raw as Omit<JobResult, 'job_id' | 'status'>),
    job_id: ownId ?? selfId ?? jobId,
    status: typeof raw['status'] === 'string' ? (raw['status'] as JobStatus) : 'success',
  };
}

/** Bekor qilish javobini `CancelResult` ga keltiradi. */
function normalizeCancelResult(raw: unknown, jobId: string): CancelResult {
  if (isRecord(raw)) {
    const id = typeof raw['job_id'] === 'string' ? raw['job_id'] : null;
    const selfId = typeof raw['id'] === 'string' ? raw['id'] : null;
    const status = typeof raw['status'] === 'string' ? (raw['status'] as JobStatus) : 'cancelled';
    const result: CancelResult = { job_id: id ?? selfId ?? jobId, status };
    if (typeof raw['cancelled_at'] === 'string') {
      result.cancelled_at = raw['cancelled_at'];
    }
    if (typeof raw['message'] === 'string') {
      result.message = raw['message'];
    }
    if (selfId !== null) {
      result.id = selfId;
    }
    return result;
  }
  return { job_id: jobId, status: 'cancelled' };
}

/** DLQ retry javobini `DlqRetryResult` ga keltiradi. */
function normalizeDlqRetryResult(raw: unknown, entryId: string): DlqRetryResult {
  if (isRecord(raw)) {
    const jobId =
      typeof raw['job_id'] === 'string'
        ? raw['job_id']
        : typeof raw['id'] === 'string'
          ? raw['id']
          : '';
    const serverEntryId = typeof raw['entry_id'] === 'string' ? raw['entry_id'] : null;
    const result: DlqRetryResult = { job_id: jobId, entry_id: serverEntryId ?? entryId };
    if (typeof raw['status'] === 'string') {
      result.status = raw['status'] as JobStatus;
    }
    if (typeof raw['requeued'] === 'boolean') {
      result.requeued = raw['requeued'];
    }
    if (typeof raw['resolved'] === 'boolean') {
      result.resolved = raw['resolved'];
    }
    if (typeof raw['retried_at'] === 'string') {
      result.retried_at = raw['retried_at'];
    }
    if (typeof raw['message'] === 'string') {
      result.message = raw['message'];
    }
    return result;
  }
  return { job_id: '', entry_id: entryId };
}
