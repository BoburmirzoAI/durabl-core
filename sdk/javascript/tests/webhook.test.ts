/**
 * Webhook imzosini tekshirish testlari.
 *
 * Imzo backend `app/utils/security.py: sign_webhook()` bilan bir xil bo'lishi
 * SHART, shuning uchun bu yerda imzo SDK'dan mustaqil ravishda ham
 * (to'g'ridan-to'g'ri `node:crypto` bilan) hisoblanadi va solishtiriladi.
 */

import { createHmac } from 'node:crypto';

import { describe, expect, it } from 'vitest';

import { DurablError } from '../src/errors.js';
import {
  DEFAULT_SIGNATURE_TOLERANCE_SECONDS,
  computeWebhookDigest,
  parseSignatureHeader,
  parseWebhookEvent,
  signWebhookPayload,
  verifyWebhookSignature,
} from '../src/webhook.js';

/** Test uchun maxfiy kalit. */
const SECRET = 'whsec_test_kalit_123';

/** Webhook tanasi (backend `build_payload` shakliga yaqin). */
const PAYLOAD = JSON.stringify({
  event: 'job.succeeded',
  timestamp: '2026-10-04T10:00:00Z',
  job: { id: 'job-1', status: 'success' },
});

/** Hozirgi vaqt (unix soniya). */
function now(): number {
  return Math.floor(Date.now() / 1000);
}

/**
 * Imzoni SDK'dan mustaqil hisoblaydi — backend algoritmining nusxasi:
 * HMAC-SHA256(secret, "<timestamp>.<payload>") hex ko'rinishda.
 */
function referenceDigest(payload: string, secret: string, timestamp: number): string {
  return createHmac('sha256', secret).update(`${timestamp}.${payload}`, 'utf8').digest('hex');
}

describe('computeWebhookDigest()', () => {
  it('backend algoritmi bilan bir xil natija beradi', () => {
    const timestamp = 1_767_200_000;
    expect(computeWebhookDigest(PAYLOAD, SECRET, timestamp)).toBe(
      referenceDigest(PAYLOAD, SECRET, timestamp),
    );
  });

  it('timestamp o\'zgarsa digest ham o\'zgaradi (replay himoyasi)', () => {
    const a = computeWebhookDigest(PAYLOAD, SECRET, 1_767_200_000);
    const b = computeWebhookDigest(PAYLOAD, SECRET, 1_767_200_001);
    expect(a).not.toBe(b);
  });

  it('matn va baytlar uchun bir xil natija beradi', () => {
    const timestamp = 1_767_200_000;
    const bytes = new TextEncoder().encode(PAYLOAD);
    expect(computeWebhookDigest(bytes, SECRET, timestamp)).toBe(
      computeWebhookDigest(PAYLOAD, SECRET, timestamp),
    );
  });
});

describe('signWebhookPayload()', () => {
  it('`t=<unix>,v1=<hex>` shaklida header yasaydi', () => {
    const header = signWebhookPayload(PAYLOAD, SECRET, 1_767_200_000);
    expect(header).toMatch(/^t=1767200000,v1=[0-9a-f]{64}$/);
  });

  it('timestamp berilmasa hozirgi vaqtni ishlatadi', () => {
    const header = signWebhookPayload(PAYLOAD, SECRET);
    const parsed = parseSignatureHeader(header);
    expect(parsed).not.toBeNull();
    expect(Math.abs((parsed?.timestamp ?? 0) - now())).toBeLessThanOrEqual(2);
  });
});

describe('parseSignatureHeader()', () => {
  it('to\'g\'ri header\'ni qismlarga ajratadi', () => {
    expect(parseSignatureHeader('t=1767200000,v1=abc')).toEqual({
      timestamp: 1_767_200_000,
      signature: 'abc',
    });
  });

  it('bo\'shliqlarga chidamli', () => {
    expect(parseSignatureHeader('  t=1767200000 ,  v1=abc  ')).toEqual({
      timestamp: 1_767_200_000,
      signature: 'abc',
    });
  });

  it('takroriy v1 bo\'lsa birinchisini oladi', () => {
    expect(parseSignatureHeader('t=1,v1=birinchi,v1=ikkinchi')?.signature).toBe('birinchi');
  });

  it('t yoki v1 yo\'q bo\'lsa null qaytaradi', () => {
    expect(parseSignatureHeader('v1=abc')).toBeNull();
    expect(parseSignatureHeader('t=1767200000')).toBeNull();
    expect(parseSignatureHeader('')).toBeNull();
    expect(parseSignatureHeader('salom')).toBeNull();
  });

  it('t son bo\'lmasa null qaytaradi', () => {
    expect(parseSignatureHeader('t=hozir,v1=abc')).toBeNull();
    expect(parseSignatureHeader('t=-5,v1=abc')).toBeNull();
    expect(parseSignatureHeader('t=1.5,v1=abc')).toBeNull();
  });
});

describe('verifyWebhookSignature()', () => {
  it('to\'g\'ri imzoni qabul qiladi', () => {
    const header = signWebhookPayload(PAYLOAD, SECRET);
    expect(verifyWebhookSignature(PAYLOAD, header, SECRET)).toBe(true);
  });

  it('mustaqil hisoblangan imzoni ham qabul qiladi (backend bilan moslik)', () => {
    const timestamp = now();
    const header = `t=${timestamp},v1=${referenceDigest(PAYLOAD, SECRET, timestamp)}`;
    expect(verifyWebhookSignature(PAYLOAD, header, SECRET)).toBe(true);
  });

  it('noto\'g\'ri maxfiy kalitni rad etadi', () => {
    const header = signWebhookPayload(PAYLOAD, SECRET);
    expect(verifyWebhookSignature(PAYLOAD, header, 'boshqa_kalit')).toBe(false);
  });

  it('o\'zgartirilgan tanani rad etadi', () => {
    const header = signWebhookPayload(PAYLOAD, SECRET);
    const tampered = PAYLOAD.replace('success', 'failed');
    expect(verifyWebhookSignature(tampered, header, SECRET)).toBe(false);
  });

  it('timestamp almashtirilsa rad etadi', () => {
    const timestamp = now();
    const header = signWebhookPayload(PAYLOAD, SECRET, timestamp);
    const forged = header.replace(`t=${timestamp}`, `t=${timestamp - 1}`);
    expect(verifyWebhookSignature(PAYLOAD, forged, SECRET)).toBe(false);
  });

  it('eskirgan imzoni rad etadi (tolerantlikdan tashqari)', () => {
    const stale = now() - (DEFAULT_SIGNATURE_TOLERANCE_SECONDS + 60);
    const header = signWebhookPayload(PAYLOAD, SECRET, stale);
    expect(verifyWebhookSignature(PAYLOAD, header, SECRET)).toBe(false);
  });

  it('tolerantlik ichidagi eski imzoni qabul qiladi', () => {
    const header = signWebhookPayload(PAYLOAD, SECRET, now() - 60);
    expect(verifyWebhookSignature(PAYLOAD, header, SECRET)).toBe(true);
  });

  it('kelajakdan kelgan imzoni rad etadi', () => {
    const future = now() + DEFAULT_SIGNATURE_TOLERANCE_SECONDS + 60;
    const header = signWebhookPayload(PAYLOAD, SECRET, future);
    expect(verifyWebhookSignature(PAYLOAD, header, SECRET)).toBe(false);
  });

  it('tolerantlik 0 bo\'lsa vaqt tekshiruvi o\'chadi', () => {
    const header = signWebhookPayload(PAYLOAD, SECRET, 1_000_000);
    expect(verifyWebhookSignature(PAYLOAD, header, SECRET, 0)).toBe(true);
  });

  it('maxsus tolerantlikni hurmat qiladi', () => {
    const header = signWebhookPayload(PAYLOAD, SECRET, now() - 30);
    expect(verifyWebhookSignature(PAYLOAD, header, SECRET, 10)).toBe(false);
    expect(verifyWebhookSignature(PAYLOAD, header, SECRET, 120)).toBe(true);
  });

  it('shakli buzilgan header va bo\'sh kalitni rad etadi', () => {
    expect(verifyWebhookSignature(PAYLOAD, 'axlat', SECRET)).toBe(false);
    expect(verifyWebhookSignature(PAYLOAD, '', SECRET)).toBe(false);
    expect(verifyWebhookSignature(PAYLOAD, signWebhookPayload(PAYLOAD, SECRET), '')).toBe(false);
  });

  it('uzunligi boshqa imzoni rad etadi (timingSafeEqual yiqilmaydi)', () => {
    const header = `t=${now()},v1=qisqa`;
    expect(verifyWebhookSignature(PAYLOAD, header, SECRET)).toBe(false);
  });

  it('bayt ko\'rinishidagi tanani ham tekshiradi', () => {
    const bytes = new TextEncoder().encode(PAYLOAD);
    const header = signWebhookPayload(bytes, SECRET);
    expect(verifyWebhookSignature(bytes, header, SECRET)).toBe(true);
  });
});

describe('parseWebhookEvent()', () => {
  it('imzo to\'g\'ri bo\'lsa hodisani qaytaradi', () => {
    const header = signWebhookPayload(PAYLOAD, SECRET);

    const event = parseWebhookEvent(PAYLOAD, header, SECRET);

    expect(event.event).toBe('job.succeeded');
    expect(event.job?.id).toBe('job-1');
  });

  it('imzo yaroqsiz bo\'lsa INVALID_WEBHOOK_SIGNATURE tashlaydi', () => {
    const header = signWebhookPayload(PAYLOAD, 'boshqa_kalit');

    const error = (() => {
      try {
        parseWebhookEvent(PAYLOAD, header, SECRET);
        return null;
      } catch (caught: unknown) {
        return caught;
      }
    })();

    expect(error).toBeInstanceOf(DurablError);
    expect((error as DurablError).code).toBe('INVALID_WEBHOOK_SIGNATURE');
  });

  it('tana JSON bo\'lmasa INVALID_WEBHOOK_PAYLOAD tashlaydi', () => {
    const broken = 'bu JSON emas';
    const header = signWebhookPayload(broken, SECRET);

    expect(() => parseWebhookEvent(broken, header, SECRET)).toThrowError(/JSON/);
  });
});
