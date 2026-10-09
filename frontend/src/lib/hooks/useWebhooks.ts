'use client'

/** Webhook CRUD va yuborish tarixi. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { DeliveryFilters, WebhookCreateInput } from '@/types'
import { webhooksApi } from '@/lib/api'
import { useToast } from '@/components/common/ToastProvider'

import { QK } from './keys'

export function useWebhooks() {
  return useQuery({ queryKey: QK.webhooks.list, queryFn: () => webhooksApi.getWebhooks() })
}

export function useDeliveries(filters: DeliveryFilters) {
  return useQuery({
    queryKey: QK.webhooks.deliveries(filters),
    queryFn: () => webhooksApi.getDeliveries(filters),
    placeholderData: (previous) => previous,
  })
}

export function useCreateWebhook() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (input: WebhookCreateInput) => webhooksApi.createWebhook(input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.webhooks.all })
      toast({ title: 'Webhook created', variant: 'success' })
    },
    onError: (error: Error) => {
      toast({ title: 'Create failed', description: error.message, variant: 'destructive' })
    },
  })
}

export function useUpdateWebhook() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: { id: string; patch: Partial<WebhookCreateInput> & { is_active?: boolean } }) =>
      webhooksApi.updateWebhook(args.id, args.patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.webhooks.all })
      toast({ title: 'Webhook updated' })
    },
  })
}

export function useDeleteWebhook() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => webhooksApi.deleteWebhook(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.webhooks.all })
      toast({ title: 'Webhook deleted' })
    },
  })
}

/** Test yuborish — natija toast'da ko'rsatiladi. */
export function useTestWebhook() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => webhooksApi.testWebhook(id),
    onSuccess: (result) => {
      // Sinov yangi yetkazish yozuvi yaratadi — ro'yxat yangilanishi SHART,
      // aks holda foydalanuvchi natijani faqat toast'da ko'radi.
      void qc.invalidateQueries({ queryKey: QK.webhooks.all })
      toast({
        title: result.success ? 'Test delivered' : 'Test failed',
        description: result.success
          ? `${result.status_code} · ${result.duration_ms}ms`
          : (result.error ?? 'Unknown error'),
        variant: result.success ? 'success' : 'destructive',
      })
    },
  })
}

export function useResendDelivery() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => webhooksApi.resendDelivery(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.webhooks.all })
      toast({ title: 'Delivery re-sent', variant: 'success' })
    },
  })
}

/**
 * Imzolash kalitini almashtirish.
 *
 * Yangi kalit FAQAT javobda qaytadi — shuning uchun `onSuccess` natijani
 * chaqiruvchiga beradi va u modalda bir marta ko'rsatiladi.
 */
export function useRotateWebhookSecret() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => webhooksApi.rotateWebhookSecret(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.webhooks.all })
      toast({
        title: 'Signing secret rotated',
        description: 'Copy the new secret now — it is shown only once.',
        variant: 'success',
      })
    },
    onError: (error: Error) => {
      toast({ title: 'Rotation failed', description: error.message, variant: 'destructive' })
    },
  })
}
