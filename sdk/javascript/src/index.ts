/**
 * Durabl — ishonchli background job va kod bajarish platformasining
 * rasmiy JavaScript/TypeScript SDK'si.
 *
 * ```ts
 * import { DurablClient } from 'durabl';
 *
 * const client = new DurablClient({ apiKey: process.env.DURABL_API_KEY! });
 * const job = await client.submit({ code: "print('salom')", runtime: 'python' });
 * const result = await job.wait();
 * console.log(result.stdout);
 * ```
 *
 * Kutubxona tashqi bog'liqliksiz: HTTP uchun global `fetch` ishlatiladi
 * (Node 18+ va brauzerlarda mavjud). Faqat `webhook.ts` Node'ning `crypto`
 * modulini talab qiladi — u imzo tekshirish uchun server tomonda ishlaydi.
 */

// --- Asosiy klasslar -------------------------------------------------------
export { DurablClient, SDK_VERSION, sleep } from './client.js';
export { JobHandle } from './job.js';

// --- Xatolar ---------------------------------------------------------------
export {
  AuthenticationError,
  DurablApiError,
  DurablError,
  JobFailedError,
  NotFoundError,
  QuotaExceededError,
  RateLimitError,
  TimeoutError,
  ValidationError,
  errorFromResponse,
} from './errors.js';

// --- Webhook imzosi -------------------------------------------------------
export {
  DEFAULT_SIGNATURE_TOLERANCE_SECONDS,
  computeWebhookDigest,
  parseSignatureHeader,
  parseWebhookEvent,
  signWebhookPayload,
  verifyWebhookSignature,
} from './webhook.js';

// --- Enum qiymatlari va yordamchilar --------------------------------------
export {
  ACTIVE_JOB_STATUSES,
  JOB_STATUSES,
  PRIORITIES,
  RUNTIMES,
  TERMINAL_JOB_STATUSES,
  WEBHOOK_EVENTS,
  isSettledJob,
  isTerminalStatus,
} from './types.js';

// --- Turlar ----------------------------------------------------------------
export type {
  ApiErrorBody,
  CancelResult,
  CreateWebhookOptions,
  DeliveryStatus,
  DlqEntry,
  DlqRetryResult,
  DurablClientOptions,
  Execution,
  ExecutionStatus,
  FailureReason,
  FetchLike,
  GetLogsOptions,
  HealthStatus,
  Job,
  JobLog,
  JobResult,
  JobStatus,
  ListDlqOptions,
  ListJobsOptions,
  LogStream,
  PaginatedResponse,
  PaginationMeta,
  PlanType,
  Priority,
  RequestOptions,
  RetryDlqOptions,
  Runtime,
  SubmitOptions,
  SuccessResponse,
  TestWebhookOptions,
  UsageSummary,
  WaitOptions,
  Webhook,
  WebhookEventName,
  WebhookEventPayload,
  WebhookTestResult,
} from './types.js';

export type {
  DurablApiErrorOptions,
  DurablErrorOptions,
  ErrorFromResponseOptions,
  RateLimitErrorOptions,
  TimeoutErrorOptions,
} from './errors.js';

export type { ParsedWebhookSignature } from './webhook.js';
export type { JobHandleMeta } from './job.js';
