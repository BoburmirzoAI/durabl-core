/**
 * Webhook imzosini tekshirish.
 *
 * Durabl har bir webhook so'roviga `X-Durabl-Signature` header'ini qo'yadi:
 *
 *     t=<unix_timestamp>,v1=<hex_hmac_sha256>
 *
 * Imzolanadigan matn — `<unix_timestamp>.<xom_tana>`. Timestamp imzoga
 * kirgani uchun eski so'rovni qayta yuborish (replay) ishlamaydi: qabul
 * qiluvchi tomon timestamp'ning hozirgi vaqtdan qancha farq qilishini
 * tekshiradi.
 *
 * Bu backend'dagi `app/utils/security.py: sign_webhook()` bilan AYNAN bir xil
 * algoritm.
 *
 * DIQQAT: bu modul Node'ning `crypto` modulidan foydalanadi, shuning uchun
 * faqat server tomonda ishlaydi (webhook'ni qabul qilish ham server ishi).
 * Brauzerda `client.ts` ni alohida import qilish kerak.
 */

import { createHmac, timingSafeEqual } from 'node:crypto';

import { DurablError } from './errors.js';
import type { WebhookEventPayload } from './types.js';

/** Imzo eskirgan deb hisoblanadigan standart vaqt (soniya) — backend bilan bir xil. */
export const DEFAULT_SIGNATURE_TOLERANCE_SECONDS = 300;

/** `X-Durabl-Signature` header'idan ajratilgan qismlar. */
export interface ParsedWebhookSignature {
  /** Imzo yaratilgan vaqt (unix soniya). */
  timestamp: number;
  /** HMAC-SHA256 natijasi (hex). */
  signature: string;
}

/**
 * `t=...,v1=...` header'ini qismlarga ajratadi.
 *
 * Shakl buzilgan bo'lsa (`t` yoki `v1` yo'q, `t` son emas) `null` qaytaradi —
 * xato tashlamaydi, chunki yaroqsiz imzo "xato" emas, oddiy "tekshirilmadi".
 */
export function parseSignatureHeader(header: string): ParsedWebhookSignature | null {
  if (typeof header !== 'string' || header.trim() === '') {
    return null;
  }

  const parts: Record<string, string> = {};
  for (const chunk of header.split(',')) {
    const trimmed = chunk.trim();
    const separator = trimmed.indexOf('=');
    if (separator <= 0) {
      continue;
    }
    const key = trimmed.slice(0, separator).trim();
    const value = trimmed.slice(separator + 1).trim();
    // Birinchi uchragan qiymat saqlanadi — takroriy `v1=` bilan aldash mumkin emas.
    if (key !== '' && value !== '' && !(key in parts)) {
      parts[key] = value;
    }
  }

  const rawTimestamp = parts['t'];
  const signature = parts['v1'];
  if (rawTimestamp === undefined || signature === undefined) {
    return null;
  }
  if (!/^\d+$/.test(rawTimestamp)) {
    return null;
  }
  const timestamp = Number.parseInt(rawTimestamp, 10);
  if (!Number.isSafeInteger(timestamp)) {
    return null;
  }
  return { timestamp, signature };
}

/**
 * `<timestamp>.<payload>` matnining HMAC-SHA256 hex digest'ini hisoblaydi.
 *
 * Tana matn sifatida berilsa UTF-8 da kodlanadi. Baytlar bilan ishlash muhim:
 * agar HTTP framework tanani qayta serialize qilsa (masalan kalitlar tartibi
 * o'zgarsa) imzo mos kelmaydi — shuning uchun XOM tanani uzatish kerak.
 */
export function computeWebhookDigest(
  payload: string | Uint8Array,
  secret: string,
  timestamp: number,
): string {
  const body = typeof payload === 'string' ? Buffer.from(payload, 'utf8') : Buffer.from(payload);
  const signedPayload = Buffer.concat([Buffer.from(`${timestamp}.`, 'utf8'), body]);
  return createHmac('sha256', secret).update(signedPayload).digest('hex');
}

/**
 * Imzo header'ini yasaydi — testlar va o'z webhook'ini imzolash uchun.
 *
 * @param timestamp Berilmasa hozirgi vaqt ishlatiladi.
 */
export function signWebhookPayload(
  payload: string | Uint8Array,
  secret: string,
  timestamp: number = Math.floor(Date.now() / 1000),
): string {
  return `t=${timestamp},v1=${computeWebhookDigest(payload, secret, timestamp)}`;
}

/**
 * Webhook imzosini tekshiradi.
 *
 * @param payload          So'rovning XOM tanasi (matn yoki baytlar).
 * @param signatureHeader  `X-Durabl-Signature` header qiymati.
 * @param secret           Webhook yaratilganda olingan maxfiy kalit.
 * @param toleranceSeconds Timestamp farqi uchun ruxsat (standart 300 soniya).
 *                         `0` berilsa vaqt tekshiruvi butunlay o'chadi.
 * @returns Imzo haqiqiy bo'lsa `true`.
 */
export function verifyWebhookSignature(
  payload: string | Uint8Array,
  signatureHeader: string,
  secret: string,
  toleranceSeconds: number = DEFAULT_SIGNATURE_TOLERANCE_SECONDS,
): boolean {
  if (typeof secret !== 'string' || secret === '') {
    return false;
  }

  const parsed = parseSignatureHeader(signatureHeader);
  if (parsed === null) {
    return false;
  }

  if (toleranceSeconds > 0) {
    const now = Math.floor(Date.now() / 1000);
    // Kelajakdagi imzo ham rad etiladi (soat farqi yoki qalbaki timestamp).
    if (Math.abs(now - parsed.timestamp) > toleranceSeconds) {
      return false;
    }
  }

  const expected = Buffer.from(computeWebhookDigest(payload, secret, parsed.timestamp), 'utf8');
  const received = Buffer.from(parsed.signature, 'utf8');
  // `timingSafeEqual` teng uzunlik talab qiladi; uzunlik farqi — darhol rad.
  if (expected.length !== received.length) {
    return false;
  }
  return timingSafeEqual(expected, received);
}

/**
 * Imzoni tekshiradi va tanani JSON sifatida o'qiydi.
 *
 * Imzo yaroqsiz bo'lsa `DurablError` (`INVALID_WEBHOOK_SIGNATURE`) tashlanadi —
 * webhook handler'ida `try/catch` bilan 400 qaytarish qulay bo'lsin.
 */
export function parseWebhookEvent(
  payload: string | Uint8Array,
  signatureHeader: string,
  secret: string,
  toleranceSeconds: number = DEFAULT_SIGNATURE_TOLERANCE_SECONDS,
): WebhookEventPayload {
  if (!verifyWebhookSignature(payload, signatureHeader, secret, toleranceSeconds)) {
    throw new DurablError(
      'Webhook imzosi haqiqiy emas yoki muddati o\'tgan — so\'rov rad etildi',
      { code: 'INVALID_WEBHOOK_SIGNATURE' },
    );
  }

  const text = typeof payload === 'string' ? payload : Buffer.from(payload).toString('utf8');
  try {
    return JSON.parse(text) as WebhookEventPayload;
  } catch (error) {
    throw new DurablError('Webhook tanasi yaroqli JSON emas', {
      code: 'INVALID_WEBHOOK_PAYLOAD',
      cause: error,
    });
  }
}
