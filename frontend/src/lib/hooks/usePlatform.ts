'use client'

/** Platforma konfiguratsiyasi (faqat admin). */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type {
  BackupSettings,
  PlanConfig,
  PlanType,
  QueueConfig,
  RateLimitRule,
  SandboxConfig,
} from '@/types'
import { platformApi } from '@/lib/api'
import { useToast } from '@/components/common/ToastProvider'

import { QK } from './keys'

// ── Tezlik chegaralari ─────────────────────────────────────────────────────

export function useRateLimits() {
  return useQuery({ queryKey: QK.platform.rateLimits, queryFn: () => platformApi.getRateLimits() })
}

export function useUpdateRateLimit() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: { plan: PlanType; patch: Partial<RateLimitRule> }) =>
      platformApi.updateRateLimit(args.plan, args.patch),
    onSuccess: (rule) => {
      void qc.invalidateQueries({ queryKey: QK.platform.all })
      toast({
        title: `${rule.plan} limits updated`,
        description: `${rule.requests_per_minute} req/min, burst ${rule.burst}.`,
        variant: 'success',
      })
    },
    onError: (error: Error) => {
      toast({ title: 'Update rejected', description: error.message, variant: 'destructive' })
    },
  })
}

// ── Tariflar ───────────────────────────────────────────────────────────────

export function usePlanConfigs() {
  return useQuery({ queryKey: QK.platform.plans, queryFn: () => platformApi.getPlanConfigs() })
}

export function useUpdatePlanConfig() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: { plan: PlanType; patch: Partial<PlanConfig> }) =>
      platformApi.updatePlanConfig(args.plan, args.patch),
    onSuccess: (config) => {
      void qc.invalidateQueries({ queryKey: QK.platform.all })
      void qc.invalidateQueries({ queryKey: QK.billing.all })
      toast({
        title: `${config.plan} plan updated`,
        description: 'New subscriptions use this immediately; existing ones move at renewal.',
        variant: 'success',
      })
    },
    onError: (error: Error) => {
      toast({ title: 'Update rejected', description: error.message, variant: 'destructive' })
    },
  })
}

// ── Sandbox va navbat ──────────────────────────────────────────────────────

export function useSandboxConfig() {
  return useQuery({ queryKey: QK.platform.sandbox, queryFn: () => platformApi.getSandboxConfig() })
}

export function useUpdateSandboxConfig() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (patch: Partial<SandboxConfig>) => platformApi.updateSandboxConfig(patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.platform.sandbox })
      toast({
        title: 'Sandbox settings saved',
        description: 'Applies to jobs started from now on; running jobs keep their old settings.',
        variant: 'success',
      })
    },
    onError: (error: Error) => {
      toast({ title: 'Rejected', description: error.message, variant: 'destructive' })
    },
  })
}

export function useQueueConfig() {
  return useQuery({ queryKey: QK.platform.queue, queryFn: () => platformApi.getQueueConfig() })
}

export function useUpdateQueueConfig() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (patch: Partial<QueueConfig>) => platformApi.updateQueueConfig(patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.platform.queue })
      toast({ title: 'Queue settings saved', variant: 'success' })
    },
    onError: (error: Error) => {
      toast({ title: 'Rejected', description: error.message, variant: 'destructive' })
    },
  })
}

// ── Sirlar ─────────────────────────────────────────────────────────────────

export function useSecrets() {
  return useQuery({ queryKey: QK.platform.secrets, queryFn: () => platformApi.getSecrets() })
}

export function useUpdateSecret() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: { key: string; value: string }) =>
      platformApi.updateSecret(args.key, args.value),
    onSuccess: (secret) => {
      void qc.invalidateQueries({ queryKey: QK.platform.secrets })
      toast({
        title: `${secret.key} rotated`,
        description: `Used by ${secret.used_by} — restart those services to pick it up.`,
        variant: 'success',
      })
    },
    onError: (error: Error) => {
      toast({ title: 'Rejected', description: error.message, variant: 'destructive' })
    },
  })
}

// ── Zaxira nusxalar ────────────────────────────────────────────────────────

export function useBackups() {
  return useQuery({ queryKey: QK.platform.backups, queryFn: () => platformApi.getBackups() })
}

export function useBackupSettings() {
  return useQuery({
    queryKey: QK.platform.backupSettings,
    queryFn: () => platformApi.getBackupSettings(),
  })
}

export function useUpdateBackupSettings() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (patch: Partial<BackupSettings>) => platformApi.updateBackupSettings(patch),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.platform.backupSettings })
      toast({ title: 'Backup settings saved', variant: 'success' })
    },
  })
}

export function useTriggerBackup() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: () => platformApi.triggerBackup(),
    onSuccess: (record) => {
      void qc.invalidateQueries({ queryKey: QK.platform.backups })
      toast({
        title: 'Backup started',
        description: `${record.id} — this usually takes a couple of minutes.`,
        variant: 'success',
      })
    },
  })
}

export function useRestoreBackup() {
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => platformApi.restoreBackup(id),
    onSuccess: (result) => {
      toast({ title: 'Restore accepted', description: result.message })
    },
    onError: (error: Error) => {
      toast({ title: 'Restore rejected', description: error.message, variant: 'destructive' })
    },
  })
}
