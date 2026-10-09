'use client'

/** Admin paneli ma'lumoti. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { AdminCreateUserInput, AdminUserFilters } from '@/types'
import type { AdminUserPatch } from '@/lib/api/admin.api'
import { adminApi } from '@/lib/api'
import { useToast } from '@/components/common/ToastProvider'

import type { PlanType } from '@/types'

import { QK } from './keys'

export function useAdminStats() {
  return useQuery({
    queryKey: QK.admin.stats,
    queryFn: () => adminApi.getAdminStats(),
    refetchInterval: 30_000,
  })
}

export function useAdminUsers(filters: AdminUserFilters) {
  return useQuery({
    queryKey: QK.admin.users(filters),
    queryFn: () => adminApi.getAdminUsers(filters),
    placeholderData: (previous) => previous,
  })
}

/** Jonli faollik oqimi — admin bosh sahifasida ko'rinadi. */
export function useActivityFeed() {
  return useQuery({
    queryKey: QK.admin.activity,
    queryFn: () => adminApi.getActivityFeed(),
    refetchInterval: 10_000,
  })
}

export function useUpdateAdminUser() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: { id: string; patch: AdminUserPatch }) =>
      adminApi.updateAdminUser(args.id, args.patch),
    onSuccess: (user) => {
      void qc.invalidateQueries({ queryKey: QK.admin.all })
      toast({ title: 'User updated', description: user.email, variant: 'success' })
    },
    onError: (error: Error) => {
      toast({ title: 'Update failed', description: error.message, variant: 'destructive' })
    },
  })
}

/** Slide-over paneli uchun bitta foydalanuvchi. */
export function useAdminUser(id: string | null) {
  return useQuery({
    queryKey: QK.admin.user(id ?? ''),
    queryFn: () => adminApi.getAdminUser(id as string),
    enabled: id !== null,
  })
}

export function useSuspendUser() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => adminApi.suspendUser(id),
    onSuccess: (user) => {
      void qc.invalidateQueries({ queryKey: QK.admin.all })
      toast({ title: 'User suspended', description: user.email })
    },
    onError: (error: Error) => {
      toast({ title: 'Suspend failed', description: error.message, variant: 'destructive' })
    },
  })
}

export function useReactivateUser() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => adminApi.reactivateUser(id),
    onSuccess: (user) => {
      void qc.invalidateQueries({ queryKey: QK.admin.all })
      toast({ title: 'User reactivated', description: user.email, variant: 'success' })
    },
  })
}

export function useChangeUserPlan() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: ({ id, plan }: { id: string; plan: PlanType }) =>
      adminApi.changeUserPlan(id, plan),
    onSuccess: (user) => {
      void qc.invalidateQueries({ queryKey: QK.admin.all })
      toast({ title: `Plan changed to ${user.plan}`, description: user.email, variant: 'success' })
    },
  })
}

export function useResetUserKeys() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => adminApi.resetUserKeys(id),
    onSuccess: ({ revoked }) => {
      void qc.invalidateQueries({ queryKey: QK.admin.all })
      toast({
        title: revoked > 0 ? `${revoked} API keys revoked` : 'No keys to revoke',
        variant: revoked > 0 ? 'success' : 'default',
      })
    },
  })
}

export function useBulkSuspendUsers() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (ids: string[]) => adminApi.suspendUsers(ids),
    onSuccess: ({ suspended }) => {
      void qc.invalidateQueries({ queryKey: QK.admin.all })
      toast({
        title: suspended > 0 ? `${suspended} users suspended` : 'Nothing to suspend',
        description: suspended === 0 ? 'Admins and already-suspended users are skipped.' : undefined,
      })
    },
  })
}

export function useBulkChangePlan() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: ({ ids, plan }: { ids: string[]; plan: PlanType }) =>
      adminApi.changeUsersPlan(ids, plan),
    onSuccess: ({ updated }) => {
      void qc.invalidateQueries({ queryKey: QK.admin.all })
      toast({ title: `${updated} users moved`, variant: 'success' })
    },
  })
}

// ── Foydalanuvchi detal sahifasi ───────────────────────────────────────────

export function useAdminUserDetail(id: string | null) {
  return useQuery({
    queryKey: QK.admin.userDetail(id ?? 'none'),
    queryFn: () => adminApi.getAdminUserDetail(id as string),
    enabled: id !== null,
  })
}

/**
 * Hisobga kredit qo'shish yoki yechish.
 *
 * Detal so'rovi ham, ro'yxat ham yangilanadi: ro'yxatda balans
 * ko'rsatilmasa ham, keyingi ochilishda eski ma'lumot chiqmasligi kerak.
 */
export function useAdjustUserCredit() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: {
      id: string
      amountUsd: number
      reason: string
      kind: 'credit' | 'refund' | 'charge' | 'adjustment'
    }) => adminApi.adjustUserCredit(args.id, args.amountUsd, args.reason, args.kind),
    onSuccess: (entry, variables) => {
      void qc.invalidateQueries({ queryKey: QK.admin.userDetail(variables.id) })
      toast({
        title:
          entry.amount_usd > 0
            ? `Credited $${entry.amount_usd.toFixed(2)}`
            : `Charged $${Math.abs(entry.amount_usd).toFixed(2)}`,
        description: entry.reason,
        variant: 'success',
      })
    },
    onError: (error: Error) => {
      toast({ title: 'Adjustment failed', description: error.message, variant: 'destructive' })
    },
  })
}

export function useSetAdminUserNote() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: { id: string; note: string }) =>
      adminApi.setAdminUserNote(args.id, args.note),
    onSuccess: (_result, variables) => {
      void qc.invalidateQueries({ queryKey: QK.admin.userDetail(variables.id) })
      toast({ title: 'Note saved' })
    },
  })
}

export function useCreateAdminUser() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (input: AdminCreateUserInput) => adminApi.createAdminUser(input),
    onSuccess: (user) => {
      void qc.invalidateQueries({ queryKey: QK.admin.all })
      toast({ title: 'Account created', description: user.email, variant: 'success' })
    },
    onError: (error: Error) => {
      toast({ title: 'Could not create', description: error.message, variant: 'destructive' })
    },
  })
}
