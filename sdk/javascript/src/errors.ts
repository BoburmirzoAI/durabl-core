/**
 * Durabl SDK xatolari.
 *
 * Ierarxiya:
 *
 *   DurablError                 <- barcha SDK xatolarining ildizi
 *   ├── DurablApiError          <- HTTP 4xx/5xx javoblari
 *   │   ├── AuthenticationError (401, 403)
 *   │   ├── NotFoundError       (404)
 *   │   ├── ValidationError     (400, 422)
 *   │   ├── QuotaExceededError  (402)
 *   │   └── RateLimitError      (429)
 *   ├── JobFailedError          <- job muvaffaqiyatsiz tugadi
 *   └── TimeoutError            <- so'rov yoki kutish vaqti tugadi
 *
 * Shuning uchun `catch (e) { if (e instanceof DurablError) ... }` har qanday
 * SDK xatosini tutadi.
 */

import type { FailureReason, Job, JobStatus } from './types.js';

// ---------------------------------------------------------------------------
// Ildiz xato
// ---------------------------------------------------------------------------

/** `DurablError` konstruktorining qo'shimcha parametrlari. */
export interface DurablErrorOptions {
  /** Barqaror mashina kodi (SCREAMING_SNAKE). */
  code?: string;
  /** Asl xato (sabab). */
  cause?: unknown;
  /** Qo'shimcha kontekst. */
  details?: Record<string, unknown> | null;
}

/** Barcha Durabl SDK xatolarining ildizi. */
export class DurablError extends Error {
  /** Barqaror mashina kodi — `if (err.code === 'QUOTA_EXCEEDED')` uchun. */
  readonly code: string;

  /** Backend yuborgan yoki SDK to'plagan qo'shimcha kontekst. */
  readonly details: Record<string, unknown> | null;

  constructor(message: string, options: DurablErrorOptions = {}) {
    super(message);
    // `new.target` — voris klass nomini avtomatik oladi (`NotFoundError` va h.k.).
    this.name = new.target.name;
    this.code = options.code ?? 'DURABL_ERROR';
    this.details = options.details ?? null;
    if (options.cause !== undefined) {
      (this as { cause?: unknown }).cause = options.cause;
    }
    // Transpilyatsiya qilingan muhitlarda `instanceof` ishlashi uchun.
    Object.setPrototypeOf(this, new.target.prototype);
  }
}

// ---------------------------------------------------------------------------
// HTTP xatolari
// ---------------------------------------------------------------------------

/** `DurablApiError` konstruktorining parametrlari. */
export interface DurablApiErrorOptions extends DurablErrorOptions {
  /** HTTP status kodi. */
  status: number;
  /** `X-Request-ID` — qo'llab-quvvatlashga murojaat qilganda kerak bo'ladi. */
  requestId?: string | null;
  /** Javobning xom tanasi (debug uchun). */
  body?: unknown;
}

/** Backend 4xx/5xx qaytarganda tashlanadigan xato. */
export class DurablApiError extends DurablError {
  /** HTTP status kodi. */
  readonly status: number;

  /** So'rovni kuzatish identifikatori (bo'lsa). */
  readonly requestId: string | null;

  /** Javobning xom tanasi. */
  readonly body: unknown;

  constructor(message: string, options: DurablApiErrorOptions) {
    super(message, options);
    this.status = options.status;
    this.requestId = options.requestId ?? null;
    this.body = options.body ?? null;
  }
}

/** 401/403 — API kalit yaroqsiz yoki ruxsat yo'q. */
export class AuthenticationError extends DurablApiError {}

/** 404 — so'ralgan resurs topilmadi. */
export class NotFoundError extends DurablApiError {}

/** 400/422 — so'rov ma'lumotlari yaroqsiz (kod validatsiyasi ham shu yerda). */
export class ValidationError extends DurablApiError {}

/** 402 — oylik kvota tugadi, rejani ko'tarish kerak. */
export class QuotaExceededError extends DurablApiError {}

/** `RateLimitError` konstruktorining parametrlari. */
export interface RateLimitErrorOptions extends DurablApiErrorOptions {
  /** Necha soniyadan keyin qayta urinish mumkin. */
  retryAfterSeconds?: number | null;
}

/** 429 — so'rovlar chastotasi yoki parallellik limiti oshdi. */
export class RateLimitError extends DurablApiError {
  /** `Retry-After` header yoki `details.retry_after` qiymati (soniya). */
  readonly retryAfterSeconds: number | null;

  constructor(message: string, options: RateLimitErrorOptions) {
    super(message, options);
    this.retryAfterSeconds = options.retryAfterSeconds ?? null;
  }
}

// ---------------------------------------------------------------------------
// Domen xatolari
// ---------------------------------------------------------------------------

/** Job muvaffaqiyatsiz tugadi (`waitForResult` shuni tashlaydi). */
export class JobFailedError extends DurablError {
  /** Xato paytidagi job holati (to'liq obyekt). */
  readonly job: Job;

  /** Job'ning yakuniy holati. */
  readonly status: JobStatus;

  /** Muvaffaqiyatsizlik sababi (bo'lsa). */
  readonly failureReason: FailureReason | null;

  /** Sandbox jarayonining chiqish kodi (bo'lsa). */
  readonly exitCode: number | null;

  /** Kod yozgan xato oqimi (bo'lsa). */
  readonly stderr: string | null;

  constructor(job: Job, message?: string) {
    super(message ?? describeFailure(job), {
      code: 'JOB_FAILED',
      details: {
        job_id: job.id,
        status: job.status,
        failure_reason: job.failure_reason ?? null,
        exit_code: job.exit_code ?? null,
      },
    });
    this.job = job;
    this.status = job.status;
    this.failureReason = job.failure_reason ?? null;
    this.exitCode = typeof job.exit_code === 'number' ? job.exit_code : null;
    this.stderr = typeof job.stderr === 'string' ? job.stderr : null;
  }
}

/** `TimeoutError` konstruktorining parametrlari. */
export interface TimeoutErrorOptions extends DurablErrorOptions {
  /** Oshib ketgan limit (ms). */
  timeoutMs?: number;
}

/** So'rov yoki `waitForResult` kutish vaqti tugadi. */
export class TimeoutError extends DurablError {
  /** Oshib ketgan limit (ms), ma'lum bo'lmasa `null`. */
  readonly timeoutMs: number | null;

  constructor(message: string, options: TimeoutErrorOptions = {}) {
    super(message, { ...options, code: options.code ?? 'TIMEOUT' });
    this.timeoutMs = options.timeoutMs ?? null;
  }
}

// ---------------------------------------------------------------------------
// Javobdan xato yasash
// ---------------------------------------------------------------------------

/** 401/403 bilan keladigan kodlar. */
const AUTH_CODES: ReadonlySet<string> = new Set([
  'AUTHENTICATION_REQUIRED',
  'INVALID_CREDENTIALS',
  'TOKEN_EXPIRED',
  'INVALID_TOKEN',
  'INVALID_API_KEY',
  'PERMISSION_DENIED',
  'ADMIN_REQUIRED',
  'INACTIVE_USER',
]);

/** 404 bilan keladigan kodlar. */
const NOT_FOUND_CODES: ReadonlySet<string> = new Set([
  'NOT_FOUND',
  'USER_NOT_FOUND',
  'JOB_NOT_FOUND',
  'EXECUTION_NOT_FOUND',
  'WEBHOOK_NOT_FOUND',
  'API_KEY_NOT_FOUND',
  'DLQ_ENTRY_NOT_FOUND',
]);

/** 429 bilan keladigan kodlar. */
const RATE_LIMIT_CODES: ReadonlySet<string> = new Set([
  'RATE_LIMIT_EXCEEDED',
  'CONCURRENCY_LIMIT_EXCEEDED',
]);

/** 402 bilan keladigan kodlar. */
const QUOTA_CODES: ReadonlySet<string> = new Set(['QUOTA_EXCEEDED']);

/** 400/422 bilan keladigan kodlar. */
const VALIDATION_CODES: ReadonlySet<string> = new Set([
  'VALIDATION_ERROR',
  'BAD_REQUEST',
  'CODE_VALIDATION_FAILED',
  'CODE_SYNTAX_ERROR',
  'UNSUPPORTED_RUNTIME',
  'WEBHOOK_URL_NOT_ALLOWED',
  'PAYLOAD_TOO_LARGE',
]);

/** `errorFromResponse()` ning qo'shimcha parametrlari. */
export interface ErrorFromResponseOptions {
  /** `X-Request-ID` header qiymati. */
  requestId?: string | null;
  /** `Retry-After` header qiymati (soniya). */
  retryAfterSeconds?: number | null;
}

/**
 * HTTP javobidan mos `DurablApiError` vorisini yasaydi.
 *
 * Avval backend yuborgan `error.code` ga qaraladi, u tanilmasa HTTP statusi
 * bo'yicha qaror qabul qilinadi. Shuning uchun backend yangi kod qo'shsa ham
 * SDK to'g'ri sinf tanlaydi.
 */
export function errorFromResponse(
  status: number,
  body: unknown,
  options: ErrorFromResponseOptions = {},
): DurablApiError {
  const parsed = extractErrorBody(body);
  const code = parsed.code ?? defaultCodeForStatus(status);
  const message = parsed.message ?? `Durabl API ${status} statusi bilan javob qaytardi`;
  const requestId = options.requestId ?? parsed.requestId ?? null;
  const base: DurablApiErrorOptions = {
    status,
    code,
    details: parsed.details,
    requestId,
    body,
  };

  if (status === 401 || status === 403 || AUTH_CODES.has(code)) {
    return new AuthenticationError(message, base);
  }
  if (status === 404 || NOT_FOUND_CODES.has(code)) {
    return new NotFoundError(message, base);
  }
  if (status === 429 || RATE_LIMIT_CODES.has(code)) {
    const fromDetails = numberOrNull(parsed.details?.['retry_after']);
    return new RateLimitError(message, {
      ...base,
      retryAfterSeconds: options.retryAfterSeconds ?? fromDetails,
    });
  }
  if (status === 402 || QUOTA_CODES.has(code)) {
    return new QuotaExceededError(message, base);
  }
  if (status === 400 || status === 422 || status === 413 || VALIDATION_CODES.has(code)) {
    return new ValidationError(message, base);
  }
  return new DurablApiError(message, base);
}

// ---------------------------------------------------------------------------
// Ichki yordamchilar
// ---------------------------------------------------------------------------

/** Xato tanasidan ajratilgan qismlar. */
interface ExtractedError {
  code?: string;
  message?: string;
  details: Record<string, unknown> | null;
  requestId?: string | null;
}

/** Qiymat oddiy obyektmi? */
function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Qiymatni songa aylantiradi, bo'lmasa `null`. */
function numberOrNull(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

/**
 * Javob tanasidan `code`/`message`/`details` ni ajratadi.
 *
 * Asosiy shakl — Durabl'ning `{ error: {...}, request_id }` formati; lekin
 * proxy yoki FastAPI standart handler'i `{ detail: ... }` qaytarishi ham
 * mumkin, shuning uchun u ham tushuniladi.
 */
function extractErrorBody(body: unknown): ExtractedError {
  if (typeof body === 'string') {
    const trimmed = body.trim();
    return trimmed === '' ? { details: null } : { message: trimmed, details: null };
  }
  if (!isRecord(body)) {
    return { details: null };
  }

  const requestId = typeof body['request_id'] === 'string' ? body['request_id'] : null;
  const error = body['error'];

  if (isRecord(error)) {
    return {
      code: typeof error['code'] === 'string' ? error['code'] : undefined,
      message: typeof error['message'] === 'string' ? error['message'] : undefined,
      details: isRecord(error['details']) ? error['details'] : null,
      requestId,
    };
  }

  const detail = body['detail'];
  if (typeof detail === 'string') {
    return { message: detail, details: null, requestId };
  }
  if (detail !== undefined) {
    return { message: 'So\'rov validatsiyadan o\'tmadi', details: { detail }, requestId };
  }
  if (typeof body['message'] === 'string') {
    return { message: body['message'], details: null, requestId };
  }
  return { details: null, requestId };
}

/** Kod kelmagan bo'lsa HTTP statusiga mos standart kod. */
function defaultCodeForStatus(status: number): string {
  switch (status) {
    case 400:
      return 'BAD_REQUEST';
    case 401:
      return 'AUTHENTICATION_REQUIRED';
    case 402:
      return 'QUOTA_EXCEEDED';
    case 403:
      return 'PERMISSION_DENIED';
    case 404:
      return 'NOT_FOUND';
    case 409:
      return 'CONFLICT';
    case 413:
      return 'PAYLOAD_TOO_LARGE';
    case 422:
      return 'VALIDATION_ERROR';
    case 429:
      return 'RATE_LIMIT_EXCEEDED';
    case 503:
      return 'SERVICE_UNAVAILABLE';
    default:
      return status >= 500 ? 'INTERNAL_ERROR' : 'HTTP_ERROR';
  }
}

/** Job muvaffaqiyatsizligi uchun o'qishga qulay xabar yasaydi. */
function describeFailure(job: Job): string {
  const parts: string[] = [`Job ${job.id} "${job.status}" holatida tugadi`];
  if (job.failure_reason) {
    parts.push(`sabab: ${job.failure_reason}`);
  }
  if (typeof job.exit_code === 'number') {
    parts.push(`exit_code: ${job.exit_code}`);
  }
  if (typeof job.error === 'string' && job.error.trim() !== '') {
    parts.push(job.error.trim());
  }
  return parts.join(' — ');
}
