'use client'

/** Hisob sozlamalari: sessiyalar, 2FA, jamoa, bildirishnomalar. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type {
  ApiDefaults,
  NotificationEvent,
  TeamInviteInput,
  TeamRole,
} from '@/types'
import { accountApi } from '@/lib/api'
import { useToast } from '@/components/common/ToastProvider'

import { QK } from './keys'

// ── Sessiyalar ─────────────────────────────────────────────────────────────

export function useSessions() {
  return useQuery({ queryKey: QK.account.sessions, queryFn: () => accountApi.getSessions() })
}

export function useRevokeSession() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => accountApi.revokeSession(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.account.sessions })
      toast({ title: 'Session signed out' })
    },
    onError: (error: Error) => {
      toast({ title: 'Could not revoke', description: error.message, variant: 'destructive' })
    },
  })
}

export function useRevokeOtherSessions() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: () => accountApi.revokeOtherSessions(),
    onSuccess: ({ revoked }) => {
      void qc.invalidateQueries({ queryKey: QK.account.sessions })
      toast({
        title: revoked === 0 ? 'No other sessions' : `Signed out ${revoked} session${revoked === 1 ? '' : 's'}`,
        variant: 'success',
      })
    },
  })
}

export function useLoginHistory() {
  return useQuery({
    queryKey: QK.account.loginHistory,
    queryFn: () => accountApi.getLoginHistory(),
  })
}

// ── 2FA ────────────────────────────────────────────────────────────────────

export function useTwoFactorStatus() {
  return useQuery({ queryKey: QK.account.twoFactor, queryFn: () => accountApi.getTwoFactorStatus() })
}

/**
 * Sozlashni boshlash.
 *
 * Toast KO'RSATILMAYDI: kalit va tiklash kodlari dialog ichida bir marta
 * ko'rsatiladi, toast ularni yopib qo'yishi mumkin.
 */
export function useSetupTwoFactor() {
  return useMutation({ mutationFn: (email: string) => accountApi.setupTwoFactor(email) })
}

export function useVerifyTwoFactor() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (code: string) => accountApi.verifyTwoFactor(code),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.account.all })
      toast({ title: 'Two-factor authentication enabled', variant: 'success' })
    },
    onError: (error: Error) => {
      toast({ title: 'Verification failed', description: error.message, variant: 'destructive' })
    },
  })
}

export function useDisableTwoFactor() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: () => accountApi.disableTwoFactor(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.account.all })
      toast({ title: 'Two-factor authentication disabled' })
    },
  })
}

export function useRegenerateRecoveryCodes() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => accountApi.regenerateRecoveryCodes(),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.account.twoFactor })
    },
  })
}

// ── Jamoa ──────────────────────────────────────────────────────────────────

export function useTeamMembers() {
  return useQuery({ queryKey: QK.account.team, queryFn: () => accountApi.getTeamMembers() })
}

export function useInviteTeamMember() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (input: TeamInviteInput) => accountApi.inviteTeamMember(input),
    onSuccess: (member) => {
      void qc.invalidateQueries({ queryKey: QK.account.team })
      toast({
        title: 'Invitation sent',
        description: `${member.email} can join as ${member.role}.`,
        variant: 'success',
      })
    },
    onError: (error: Error) => {
      toast({ title: 'Invite failed', description: error.message, variant: 'destructive' })
    },
  })
}

export function useChangeTeamRole() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: { id: string; role: TeamRole }) =>
      accountApi.changeTeamRole(args.id, args.role),
    onSuccess: (member) => {
      void qc.invalidateQueries({ queryKey: QK.account.team })
      toast({ title: `${member.email} is now ${member.role}` })
    },
    onError: (error: Error) => {
      toast({ title: 'Could not change role', description: error.message, variant: 'destructive' })
    },
  })
}

export function useRemoveTeamMember() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => accountApi.removeTeamMember(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.account.team })
      toast({ title: 'Member removed' })
    },
    onError: (error: Error) => {
      toast({ title: 'Could not remove', description: error.message, variant: 'destructive' })
    },
  })
}

export function useResendInvite() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => accountApi.resendInvite(id),
    onSuccess: (member) => {
      void qc.invalidateQueries({ queryKey: QK.account.team })
      toast({ title: `Invitation resent to ${member.email}` })
    },
  })
}

// ── Bildirishnomalar va standartlar ────────────────────────────────────────

export function useNotificationSettings() {
  return useQuery({
    queryKey: QK.account.notificationSettings,
    queryFn: () => accountApi.getNotificationSettings(),
  })
}

export function useUpdateNotificationSetting() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: {
      event: NotificationEvent
      channel: 'email' | 'in_app' | 'webhook'
      enabled: boolean
    }) => accountApi.updateNotificationSetting(args.event, args.channel, args.enabled),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.account.notificationSettings })
    },
    onError: (error: Error) => {
      toast({ title: 'Could not save', description: error.message, variant: 'destructive' })
    },
  })
}

export function useApiDefaults() {
  return useQuery({ queryKey: QK.account.apiDefaults, queryFn: () => accountApi.getApiDefaults() })
}

export function useUpdateApiDefaults() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (patch: Partial<ApiDefaults>) => accountApi.updateApiDefaults(patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.account.apiDefaults })
      toast({ title: 'Defaults saved', variant: 'success' })
    },
  })
}
