'use client'

/** API kalitlar. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { ApiKeyCreateInput, ApiKeyScope } from '@/types'
import { apiKeysApi } from '@/lib/api'
import { useToast } from '@/components/common/ToastProvider'
import { formatDate } from '@/lib/utils/time'

import { QK } from './keys'

export function useApiKeys() {
  return useQuery({ queryKey: QK.apiKeys.list, queryFn: () => apiKeysApi.getApiKeys() })
}

/**
 * Kalit yaratish.
 *
 * Toast KO'RSATILMAYDI — xom kalit modal ichida bir marta ko'rsatilishi
 * kerak, toast uni yashirib qo'yishi mumkin. Modal o'zi muvaffaqiyat
 * holatiga o'tadi.
 */
export function useCreateApiKey() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: ApiKeyCreateInput) => apiKeysApi.createApiKey(input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.apiKeys.all })
    },
  })
}

export function useRevokeApiKey() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => apiKeysApi.revokeApiKey(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.apiKeys.all })
      toast({ title: 'Key revoked' })
    },
    onError: (error: Error) => {
      toast({ title: 'Revoke failed', description: error.message, variant: 'destructive' })
    },
  })
}

export function useRenameApiKey() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: { id: string; name: string }) => apiKeysApi.renameApiKey(args.id, args.name),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.apiKeys.all })
      toast({ title: 'Key renamed' })
    },
  })
}

/**
 * Kalit foydalanish statistikasi.
 *
 * Faqat tafsilot paneli OCHIQ bo'lganda so'raladi — 30 kunlik grafik
 * ro'yxatdagi har bir kalit uchun oldindan yuklanishi keraksiz.
 */
export function useApiKeyUsage(id: string | null) {
  return useQuery({
    queryKey: QK.apiKeys.usage(id ?? 'none'),
    queryFn: () => apiKeysApi.getApiKeyUsage(id as string),
    enabled: id !== null,
  })
}

export function useUpdateApiKeyScopes() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: { id: string; scopes: ApiKeyScope[] }) =>
      apiKeysApi.updateApiKeyScopes(args.id, args.scopes),
    onSuccess: (key) => {
      void qc.invalidateQueries({ queryKey: QK.apiKeys.all })
      toast({
        title: 'Permissions updated',
        description: `"${key.name}" now has ${key.scopes.length} scope${key.scopes.length === 1 ? '' : 's'}.`,
      })
    },
    onError: (error: Error) => {
      toast({ title: 'Update failed', description: error.message, variant: 'destructive' })
    },
  })
}

export function useUpdateApiKeyExpiry() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: { id: string; expiresInDays: number | null }) =>
      apiKeysApi.updateApiKeyExpiry(args.id, args.expiresInDays),
    onSuccess: (key) => {
      void qc.invalidateQueries({ queryKey: QK.apiKeys.all })
      toast({
        title: key.expires_at ? 'Expiry updated' : 'Expiry removed',
        description: key.expires_at
          ? `"${key.name}" now expires ${formatDate(key.expires_at)}.`
          : `"${key.name}" no longer expires.`,
      })
    },
    onError: (error: Error) => {
      toast({ title: 'Update failed', description: error.message, variant: 'destructive' })
    },
  })
}

/**
 * Kalitni almashtirish.
 *
 * `useCreateApiKey` kabi toast KO'RSATMAYDI — yangi xom kalit modal ichida
 * bir marta ko'rsatiladi, toast uni yashirib qo'yishi mumkin.
 */
export function useRotateApiKey() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => apiKeysApi.rotateApiKey(id),
    onSuccess: (rotation) => {
      void qc.invalidateQueries({ queryKey: QK.apiKeys.all })
      void qc.invalidateQueries({ queryKey: QK.apiKeys.usage(rotation.key_id) })
    },
    onError: (error: Error) => {
      toast({ title: 'Rotation failed', description: error.message, variant: 'destructive' })
    },
  })
}
