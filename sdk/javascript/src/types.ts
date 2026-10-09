/**
 * Durabl JS/TS SDK — API bilan almashinadigan barcha turlar.
 *
 * Bu faylda ikki xil narsa bor:
 *   1. Backend enumlariga AYNAN mos string union turlari (`app/constants.py`).
 *   2. HTTP javob/so'rov shakllari (`docs/CONTRACTS.md` 12-bo'lim).
 *
 * MUHIM: tarmoq orqali keladigan maydonlar `snake_case` (backend shundan yuboradi),
 * SDK foydalanuvchisi beradigan parametrlar esa `camelCase` (JS konvensiyasi).
 * Konvertatsiyani `client.ts` bajaradi.
 */

// ---------------------------------------------------------------------------
// Enumlar (backend `app/constants.py` bilan bir xil qiymatlar)
// ---------------------------------------------------------------------------

/** Job hayot sikli holatlari — backend `JobStatus`. */
export type JobStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'success'
  | 'failed'
  | 'retrying'
  | 'cancelled'
  | 'dead_letter';

/** Bitta bajarish urinishining holati — backend `ExecutionStatus`. */
export type ExecutionStatus =
  | 'pending'
  | 'running'
  | 'success'
  | 'failed'
  | 'timeout'
  | 'cancelled'
  | 'lost';

/** Qo'llab-quvvatlanadigan bajarish muhitlari — backend `Runtime`. */
export type Runtime = 'python' | 'node';

/** Navbat ustuvorligi — backend `Priority`. */
export type Priority = 'high' | 'normal' | 'low';

/** Log qaysi oqimdan kelgani — backend `LogStream`. */
export type LogStream = 'stdout' | 'stderr' | 'system';

/** Obuna bo'lish mumkin bo'lgan webhook hodisalari — backend `WebhookEvent`. */
export type WebhookEventName =
  | 'job.queued'
  | 'job.started'
  | 'job.succeeded'
  | 'job.failed'
  | 'job.cancelled'
  | 'job.dead_lettered';

/** Webhook yuborish natijasi — backend `DeliveryStatus`. */
export type DeliveryStatus = 'pending' | 'success' | 'failed' | 'retrying' | 'exhausted';

/** Job nega muvaffaqiyatsiz bo'lgani — backend `FailureReason`. */
export type FailureReason =
  | 'non_zero_exit'
  | 'timeout'
  | 'out_of_memory'
  | 'sandbox_error'
  | 'validation_error'
  | 'lease_lost'
  | 'max_retries_exceeded'
  | 'internal_error'
  | 'output_too_large';

/** Obuna rejalari — backend `PlanType`. */
export type PlanType = 'free' | 'starter' | 'pro' | 'enterprise';

// ---------------------------------------------------------------------------
// Enum qiymatlarining ish vaqtidagi ro'yxatlari (validatsiya uchun)
// ---------------------------------------------------------------------------

/** Barcha job holatlari (ish vaqtida tekshirish uchun). */
export const JOB_STATUSES: readonly JobStatus[] = [
  'pending',
  'queued',
  'running',
  'success',
  'failed',
  'retrying',
  'cancelled',
  'dead_letter',
];

/** Yakuniy holatlar — bundan keyin job avtomatik o'zgarmaydi. */
export const TERMINAL_JOB_STATUSES: readonly JobStatus[] = ['success', 'cancelled', 'dead_letter'];

/** Job hali tizimda harakatda bo'lgan holatlar. */
export const ACTIVE_JOB_STATUSES: readonly JobStatus[] = ['pending', 'queued', 'running', 'retrying'];

/** Qo'llab-quvvatlanadigan runtime'lar. */
export const RUNTIMES: readonly Runtime[] = ['python', 'node'];

/** Ustuvorlik qiymatlari (yuqoridan pastga). */
export const PRIORITIES: readonly Priority[] = ['high', 'normal', 'low'];

/** Barcha webhook hodisa nomlari. */
export const WEBHOOK_EVENTS: readonly WebhookEventName[] = [
  'job.queued',
  'job.started',
  'job.succeeded',
  'job.failed',
  'job.cancelled',
  'job.dead_lettered',
];

/** Holat yakuniymi? (`JobStatus.is_terminal` ning JS ekvivalenti) */
export function isTerminalStatus(status: JobStatus): boolean {
  return TERMINAL_JOB_STATUSES.includes(status);
}

/**
 * Job'ni kutishni to'xtatish kerakmi?
 *
 * Yakuniy holatlardan tashqari `failed` holati ham hisobga olinadi: agar barcha
 * urinishlar sarflangan bo'lsa (`retry_count >= max_retries`), bu ham oxiri —
 * aks holda backend uni `retrying` ga o'tkazadi va kutishda davom etamiz.
 */
export function isSettledJob(job: Job): boolean {
  if (isTerminalStatus(job.status)) {
    return true;
  }
  if (job.status === 'failed') {
    const used = typeof job.retry_count === 'number' ? job.retry_count : 0;
    const allowed = typeof job.max_retries === 'number' ? job.max_retries : 0;
    return used >= allowed;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Umumiy javob shakllari (CONTRACTS.md 12-bo'lim)
// ---------------------------------------------------------------------------

/** Sahifalash meta-ma'lumoti. */
export interface PaginationMeta {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  has_next: boolean;
  has_prev: boolean;
}

/** Ro'yxat javobi: `{ items, pagination }`. */
export interface PaginatedResponse<T> {
  items: T[];
  pagination: PaginationMeta;
}

/** Xato javobi: `{ error: { code, message, details? }, request_id? }`. */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown> | null;
  };
  request_id?: string | null;
}

/** Oddiy "bajarildi" javobi (DELETE, cancel, test va h.k.). */
export interface SuccessResponse {
  success: boolean;
  message?: string;
  data?: Record<string, unknown> | null;
}

/** `/health` javobi. */
export interface HealthStatus {
  status: string;
  version?: string;
  environment?: string;
  checks?: Record<string, unknown> | null;
  /** Server ishga tushganidan beri o'tgan vaqt (soniya). */
  uptime_seconds?: number | null;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Domen obyektlari
// ---------------------------------------------------------------------------

/** Job yozuvi (`JobRead`). Faqat har doim keladigan maydonlar majburiy. */
export interface Job {
  id: string;
  status: JobStatus;
  runtime: Runtime;
  priority: Priority;
  timeout_seconds: number;
  max_retries: number;
  retry_count: number;
  created_at: string;
  user_id?: string;
  code?: string;
  payload?: Record<string, unknown> | null;
  env_vars?: Record<string, string> | null;
  memory_mb?: number | null;
  cpus?: number | null;
  idempotency_key?: string | null;
  scheduled_at?: string | null;
  cron_expression?: string | null;
  updated_at?: string | null;
  queued_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  cancelled_at?: string | null;
  result?: unknown;
  stdout?: string | null;
  stderr?: string | null;
  exit_code?: number | null;
  duration_ms?: number | null;
  error?: string | null;
  failure_reason?: FailureReason | null;
  correlation_id?: string;
  tags?: string[] | null;
  /** Backend hisoblaydigan maydon: holat yakuniymi. */
  is_terminal?: boolean;
  /** Backend hisoblaydigan maydon: sarflangan urinishlar soni. */
  attempts_used?: number;
}

/** `GET /jobs/{id}/result` javobi (`JobResultResponse`). */
export interface JobResult {
  /**
   * Job identifikatori.
   *
   * Backend uni `id` kalitida yuboradi; SDK `getResult()` da shu maydonga
   * ko'chiradi, shuning uchun bu yerda har doim to'lgan bo'ladi.
   */
  job_id: string;
  status: JobStatus;
  /** Backend yuborgan xom kalit (`JobResultResponse.id`). */
  id?: string;
  /** Backend hisoblaydigan maydon: `status === 'success' && exit_code === 0`. */
  succeeded?: boolean;
  result?: unknown;
  stdout?: string | null;
  stderr?: string | null;
  exit_code?: number | null;
  duration_ms?: number | null;
  error?: string | null;
  failure_reason?: FailureReason | null;
  finished_at?: string | null;
  retry_count?: number;
}

/** Bitta log qatori (`ExecutionLogRead`). */
export interface JobLog {
  stream: LogStream;
  content: string;
  sequence: number;
  timestamp: string;
  id?: string;
  job_id?: string;
  execution_id?: string;
}

/** Bitta bajarish urinishi (`ExecutionRead`). */
export interface Execution {
  id: string;
  job_id: string;
  attempt_number: number;
  status: ExecutionStatus;
  worker_id?: string | null;
  lease_expires_at?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  exit_code?: number | null;
  duration_ms?: number | null;
  error_message?: string | null;
  failure_reason?: FailureReason | null;
  stdout_bytes?: number;
  stderr_bytes?: number;
  result?: unknown;
  sandbox_id?: string | null;
  memory_peak_mb?: number | null;
  created_at?: string;
  updated_at?: string | null;
  /** Backend hisoblaydigan maydon: urinish yakuniy holatdami. */
  is_finished?: boolean;
}

/** DLQ (o'lik xatlar navbati) yozuvi (`DlqEntryRead`). */
export interface DlqEntry {
  id: string;
  job_id: string;
  failure_reason: FailureReason;
  failed_at: string;
  retry_count: number;
  resolved: boolean;
  user_id?: string;
  last_error?: string | null;
  resolved_at?: string | null;
  resolved_by_id?: string | null;
  notes?: string | null;
  manual_retry_count?: number;
  created_at?: string;
  updated_at?: string | null;
  /** Backend hisoblaydigan maydon: yozuvni qayta urinish mumkinmi. */
  is_retryable?: boolean;
  job?: Job | null;
}

/** `POST /dlq/{id}/retry` natijasi (`DlqRetryResponse`). */
export interface DlqRetryResult {
  job_id: string;
  entry_id?: string;
  status?: JobStatus;
  /** Job haqiqatan navbatga qaytarildimi. */
  requeued?: boolean;
  /** DLQ yozuvi hal qilingan deb belgilandimi. */
  resolved?: boolean;
  retried_at?: string | null;
  message?: string;
}

/** Webhook yozuvi (`WebhookRead`). `secret` faqat yaratilganda qaytariladi. */
export interface Webhook {
  id: string;
  url: string;
  events: WebhookEventName[];
  is_active: boolean;
  secret?: string | null;
  description?: string | null;
  last_triggered_at?: string | null;
  consecutive_failures?: number;
  disabled_at?: string | null;
  created_at?: string;
  updated_at?: string | null;
  user_id?: string;
  /** Backend hisoblaydigan maydon: webhook ketma-ket xatolar tufayli o'chirilganmi. */
  is_disabled?: boolean;
}

/** `POST /webhooks/{id}/test` natijasi (`WebhookTestResponse`). */
export interface WebhookTestResult {
  success: boolean;
  /** Qaysi hodisa nomi bilan test yuborildi. */
  event?: WebhookEventName;
  status_code?: number | null;
  response_body?: string | null;
  error?: string | null;
  duration_ms?: number | null;
  sent_at?: string | null;
}

/** `GET /billing/usage` javobi (`UsageSummary`). */
export interface UsageSummary {
  period: string;
  plan: PlanType;
  job_count: number;
  success_count: number;
  failed_count: number;
  execution_seconds: number;
  /** Reja bo'yicha oylik job limiti. */
  monthly_limit?: number;
  /** Reja bo'yicha bir vaqtdagi job limiti. */
  concurrent_limit?: number;
  period_started_at?: string | null;
  period_ends_at?: string | null;
  /** Backend hisoblaydigan maydon: limitdan qolgan job soni. */
  remaining?: number;
  /** Backend hisoblaydigan maydon: limitning necha foizi sarflangani (limit oshsa 100 dan katta). */
  usage_percent?: number;
  /** Backend hisoblaydigan maydon: limit oshib ketdimi. */
  quota_exceeded?: boolean;
}

/** `POST /jobs/{id}/cancel` natijasi (`JobCancelResponse`). */
export interface CancelResult {
  /**
   * Job identifikatori. Backend uni `id` kalitida yuboradi — SDK `cancel()`
   * da shu maydonga ko'chiradi.
   */
  job_id: string;
  status: JobStatus;
  /** Backend yuborgan xom kalit (`JobCancelResponse.id`). */
  id?: string;
  cancelled_at?: string | null;
  message?: string;
}

/**
 * Webhook tanasi (`WebhookService.build_payload` yuboradigan shakl).
 *
 * Backend payload'iga yangi maydon qo'shilsa SDK buzilmasligi uchun indeks
 * imzosi (`[key: string]: unknown`) ochiq qoldirilgan.
 */
export interface WebhookEventPayload {
  event: WebhookEventName;
  timestamp?: string;
  delivery_id?: string;
  job?: (Partial<Job> & { id: string }) | null;
  data?: Record<string, unknown> | null;
  [key: string]: unknown;
}

// ---------------------------------------------------------------------------
// Mijoz (SDK foydalanuvchisi) beradigan parametrlar — camelCase
// ---------------------------------------------------------------------------

/** `fetch` ning SDK ichida ishlatiladigan minimal imzosi. */
export type FetchLike = (input: string, init: RequestInit) => Promise<Response>;

/** `DurablClient` konstruktori parametrlari. */
export interface DurablClientOptions {
  /** API kalit (`durabl_...`) — `X-API-Key` header'ida yuboriladi. */
  apiKey: string;
  /** API manzili; standart `https://api.durabl.dev`. */
  baseUrl?: string;
  /** Bitta HTTP so'rov uchun vaqt limiti (ms); standart 30000. `0` — limitsiz. */
  timeoutMs?: number;
  /** 429/5xx va tarmoq xatolarida qo'shimcha urinishlar soni; standart 3. */
  maxRetries?: number;
  /** Eksponensial backoff boshlang'ich kechikishi (ms); standart 500. */
  retryBaseDelayMs?: number;
  /** Backoff maksimal kechikishi (ms); standart 10000. */
  retryMaxDelayMs?: number;
  /** Backoff'ga tasodifiy qo'shimcha (jitter) qo'shilsinmi; standart `true`. */
  retryJitter?: boolean;
  /** `waitForResult` boshlang'ich polling davri (ms); standart 1000. */
  pollIntervalMs?: number;
  /** `waitForResult` maksimal polling davri (ms); standart 5000. */
  maxPollIntervalMs?: number;
  /** `submit()` uchun avtomatik `Idempotency-Key` yaratilsinmi; standart `true`. */
  autoIdempotency?: boolean;
  /** `User-Agent` header qiymati. */
  userAgent?: string;
  /** Har bir so'rovga qo'shiladigan qo'shimcha header'lar. */
  headers?: Record<string, string>;
  /** `globalThis.fetch` o'rniga ishlatiladigan funksiya (test yoki proxy uchun). */
  fetch?: FetchLike;
}

/** Barcha metodlarda mavjud umumiy parametr. */
export interface RequestOptions {
  /** So'rovni tashqaridan bekor qilish uchun signal. */
  signal?: AbortSignal;
}

/** `submit()` parametrlari. */
export interface SubmitOptions extends RequestOptions {
  /** Bajarilishi kerak bo'lgan kod (majburiy). */
  code: string;
  /** Qaysi muhitda bajarilsin (majburiy). */
  runtime: Runtime;
  /** Navbat ustuvorligi. */
  priority?: Priority;
  /** Kodga uzatiladigan argumentlar. */
  payload?: Record<string, unknown> | null;
  /** Sandbox muhit o'zgaruvchilari. */
  envVars?: Record<string, string>;
  /** Vaqt limiti (soniya). */
  timeoutSeconds?: number;
  /** `timeoutSeconds` taxallusi — Python SDK'dagi `timeout=` bilan mos. */
  timeout?: number;
  /** Maksimal qayta urinishlar soni. */
  maxRetries?: number;
  /** `maxRetries` taxallusi. */
  retries?: number;
  /** Kechiktirilgan bajarish vaqti. */
  scheduledAt?: Date | string;
  /** Cron ifodasi (takrorlanuvchi job uchun). */
  cronExpression?: string;
  /** Qidiruv uchun teglar. */
  tags?: string[];
  /** Xotira limiti (MB). */
  memoryMb?: number;
  /** CPU limiti. */
  cpus?: number;
  /** Takrorlanmaslik kaliti — berilmasa avtomatik yaratiladi. */
  idempotencyKey?: string;
}

/** `listJobs()` filtrlari. */
export interface ListJobsOptions extends RequestOptions {
  status?: JobStatus | JobStatus[];
  runtime?: Runtime;
  priority?: Priority;
  /** Kod yoki teg bo'yicha matnli qidiruv. */
  search?: string;
  tags?: string[];
  /** Davr boshi. */
  start?: Date | string;
  /** Davr oxiri. */
  end?: Date | string;
  page?: number;
  pageSize?: number;
  sortBy?: string;
  sortOrder?: 'asc' | 'desc';
}

/** `getLogs()` parametrlari. */
export interface GetLogsOptions extends RequestOptions {
  /** Shu ketma-ket raqamdan keyingi loglar (inkremental o'qish uchun). */
  afterSequence?: number;
  /** Maksimal qatorlar soni. */
  limit?: number;
}

/** `listDlq()` filtrlari. */
export interface ListDlqOptions extends RequestOptions {
  resolved?: boolean;
  failureReason?: FailureReason;
  page?: number;
  pageSize?: number;
}

/** `retryDlq()` parametrlari. */
export interface RetryDlqOptions extends RequestOptions {
  /** Qayta urinish sababi (audit uchun izoh). */
  notes?: string;
}

/** `createWebhook()` parametrlari. */
export interface CreateWebhookOptions extends RequestOptions {
  url: string;
  /** Obuna bo'linadigan hodisalar; berilmasa backend standartini qo'llaydi. */
  events?: WebhookEventName[];
  description?: string;
  /** Imzo kaliti; berilmasa backend o'zi yaratadi. */
  secret?: string;
  isActive?: boolean;
}

/** `testWebhook()` parametrlari. */
export interface TestWebhookOptions extends RequestOptions {
  /** Qaysi hodisa nomi bilan test yuborilsin. */
  event?: WebhookEventName;
}

/** `waitForResult()` / `JobHandle.wait()` parametrlari. */
export interface WaitOptions extends RequestOptions {
  /** Umumiy kutish limiti (ms); standart 300000 (5 daqiqa). */
  timeoutMs?: number;
  /** Boshlang'ich polling davri (ms). */
  pollIntervalMs?: number;
  /** Polling davri shu qiymatdan oshmaydi (ms). */
  maxPollIntervalMs?: number;
  /** `false` bo'lsa muvaffaqiyatsiz job uchun xato tashlanmaydi; standart `true`. */
  throwOnFailure?: boolean;
  /** Har bir polling natijasida chaqiriladi (progress ko'rsatish uchun). */
  onUpdate?: (job: Job) => void;
}
