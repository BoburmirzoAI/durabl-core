/**
 * `JobHandle` — bitta job ustida ishlash uchun qulay o'ram (wrapper).
 *
 * `client.submit()` shu klassni qaytaradi, shuning uchun job identifikatorini
 * qo'lda tashib yurish shart emas:
 *
 * ```ts
 * const job = await client.submit({ code: "print('salom')", runtime: 'python' });
 * console.log(job.id);
 * const result = await job.wait();
 * ```
 *
 * Klass oxirgi ma'lum job holatini keshlaydi (`job.snapshot`), lekin hech
 * qachon eski ma'lumotni "yangi" deb ko'rsatmaydi: `status()` va `refresh()`
 * har safar serverga murojaat qiladi.
 */

import type { DurablClient } from './client.js';
import type {
  CancelResult,
  GetLogsOptions,
  Job,
  JobLog,
  JobResult,
  JobStatus,
  RequestOptions,
  WaitOptions,
} from './types.js';

/** `JobHandle` konstruktorining qo'shimcha ma'lumoti. */
export interface JobHandleMeta {
  /**
   * Job shu so'rovda yangi yaratildimi (HTTP 201) yoki idempotency tufayli
   * mavjud job qaytarildimi (HTTP 200). Ma'lum bo'lmasa `null`.
   */
  created?: boolean;
}

/** Bitta job uchun amallar to'plami. */
export class JobHandle {
  /** Job identifikatori (UUID matn). */
  readonly id: string;

  /**
   * `true` — job shu `submit()` da yangi yaratildi;
   * `false` — idempotency kaliti bo'yicha mavjud job qaytarildi;
   * `null` — noma'lum (handle identifikatordan yasalgan).
   */
  readonly created: boolean | null;

  private readonly client: DurablClient;
  private lastKnown: Job | null;

  constructor(client: DurablClient, job: Job | string, meta: JobHandleMeta = {}) {
    this.client = client;
    if (typeof job === 'string') {
      this.id = job;
      this.lastKnown = null;
    } else {
      this.id = job.id;
      this.lastKnown = job;
    }
    this.created = meta.created ?? null;
  }

  /** Oxirgi ma'lum job yozuvi (serverga murojaat qilmaydi). */
  get snapshot(): Job | null {
    return this.lastKnown;
  }

  /** Job yozuvini serverdan qayta o'qiydi va keshni yangilaydi. */
  async refresh(options: RequestOptions = {}): Promise<Job> {
    const job = await this.client.getJob(this.id, options);
    this.lastKnown = job;
    return job;
  }

  /** Job holatini oladi (`pending`, `running`, `success`, ...). */
  async status(options: RequestOptions = {}): Promise<JobStatus> {
    const job = await this.refresh(options);
    return job.status;
  }

  /** Job natijasini oladi (job tugamagan bo'lsa backend 409 qaytaradi). */
  async result(options: RequestOptions = {}): Promise<JobResult> {
    return await this.client.getResult(this.id, options);
  }

  /** Job tugashini kutadi va natijani qaytaradi. */
  async wait(options: WaitOptions = {}): Promise<JobResult> {
    return await this.client.waitForResult(this.id, {
      ...options,
      onUpdate: (job: Job): void => {
        this.lastKnown = job;
        options.onUpdate?.(job);
      },
    });
  }

  /** Job'ni bekor qiladi va keshdagi holatni yangilaydi. */
  async cancel(options: RequestOptions = {}): Promise<CancelResult> {
    const result = await this.client.cancel(this.id, options);
    if (this.lastKnown !== null) {
      this.lastKnown = { ...this.lastKnown, status: result.status };
    }
    return result;
  }

  /** Job loglarini oladi. */
  async logs(options: GetLogsOptions = {}): Promise<JobLog[]> {
    return await this.client.getLogs(this.id, options);
  }

  /** `JSON.stringify(handle)` da foydali chiqish beradi. */
  toJSON(): { id: string; created: boolean | null; snapshot: Job | null } {
    return { id: this.id, created: this.created, snapshot: this.lastKnown };
  }

  /** Log va xato xabarlarida o'qishga qulay ko'rinish. */
  toString(): string {
    const status = this.lastKnown === null ? 'noma\'lum' : this.lastKnown.status;
    return `JobHandle(${this.id}, holat=${status})`;
  }
}
