/**
 * Tizim boshqaruvi holati — texnik xizmat rejimi va funksiya bayroqlari.
 *
 * Alohida modul: bu ma'lumot urug'dan generatsiya qilinmaydi, u sof
 * O'ZGARUVCHAN holat (admin uni yoqadi/o'chiradi).
 */

import { notifyChanged } from './store'

export interface FeatureFlag {
  key: string
  label: string
  description: string
  enabled: boolean
  /** Bayroqni o'chirish xavfli bo'lsa ogohlantiramiz. */
  risky?: boolean
}

interface SystemControls {
  maintenance_mode: boolean
  /** Navbat to'xtatilgan — worker'lar yangi job olmaydi. */
  queue_paused: boolean
  flags: FeatureFlag[]
}

const state: SystemControls = {
  maintenance_mode: false,
  queue_paused: false,
  flags: [
    {
      key: 'gvisor_sandbox',
      label: 'gVisor sandbox',
      description: 'Job kodini runsc izolyatsiyasida bajarish. O\'chirilsa kod to\'g\'ridan-to\'g\'ri konteynerda ishlaydi.',
      enabled: true,
      risky: true,
    },
    {
      key: 'auto_retry',
      label: 'Avtomatik qayta urinish',
      description: 'Yiqilgan job\'lar eksponensial backoff bilan qayta uriniladi.',
      enabled: true,
    },
    {
      key: 'webhook_delivery',
      label: 'Webhook yetkazish',
      description: 'Hodisalar mijoz endpointlariga yuboriladi.',
      enabled: true,
    },
    {
      key: 'dlq_auto_purge',
      label: 'DLQ avtomatik tozalash',
      description: '30 kundan oshgan DLQ yozuvlari o\'chiriladi.',
      enabled: false,
    },
    {
      key: 'priority_queues',
      label: 'Ustuvorlik navbatlari',
      description: 'High/normal/low navbatlar alohida ishlanadi.',
      enabled: true,
    },
    {
      key: 'strict_quotas',
      label: 'Qat\'iy kvotalar',
      description: 'Limitdan oshgan foydalanuvchining job\'lari rad etiladi.',
      enabled: false,
      risky: true,
    },
  ],
}

export function systemControls(): SystemControls {
  return { ...state, flags: state.flags.map((f) => ({ ...f })) }
}

export function setMaintenanceMode(enabled: boolean): boolean {
  state.maintenance_mode = enabled
  notifyChanged()
  return state.maintenance_mode
}

export function setQueuePaused(paused: boolean): boolean {
  state.queue_paused = paused
  notifyChanged()
  return state.queue_paused
}

export function toggleFlag(key: string, enabled: boolean): FeatureFlag | undefined {
  const flag = state.flags.find((f) => f.key === key)
  if (!flag) return undefined
  flag.enabled = enabled
  notifyChanged()
  return { ...flag }
}
