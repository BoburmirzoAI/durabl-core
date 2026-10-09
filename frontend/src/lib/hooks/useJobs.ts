'use client'

/** Job ro'yxati va mutatsiyalari. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { JobCreateInput, JobFilters, Priority } from '@/types'
import { jobsApi } from '@/lib/api'
import { useToast } from '@/components/common/ToastProvider'

import { QK } from './keys'

/**
 * Job'lar ro'yxati.
 *
 * Faol job bo'lsa (pending/queued/running/retrying) ro'yxat avtomatik
 * yangilanadi — foydalanuvchi F5 bosmasligi uchun. Hammasi tugagan bo'lsa
 * polling to'xtaydi (keraksiz so'rov yubormaslik uchun).
 */
export function useJobs(filters: JobFilters, options?: { autoRefresh?: boolean }) {
  const autoRefresh = options?.autoRefresh ?? true
  return useQuery({
    queryKey: QK.jobs.list(filters),
    queryFn: () => jobsApi.getJobs(filters),
    // Sahifa almashganda eski ma'lumot ko'rinib turadi (jadval "sakramaydi")
    placeholderData: (previous) => previous,
    refetchInterval: (query) => {
      if (!autoRefresh) return false
      const items = query.state.data?.items ?? []
      const hasActive = items.some((j) => !j.is_terminal)
      return hasActive ? 4_000 : false
    },
  })
}

export function useJob(id: string) {
  return useQuery({
    queryKey: QK.jobs.detail(id),
    queryFn: () => jobsApi.getJob(id),
    enabled: Boolean(id),
    // Tugamagan job'ni kuzatib turamiz
    refetchInterval: (query) => (query.state.data?.is_terminal === false ? 2_500 : false),
  })
}

export function useJobLogs(id: string, isLive: boolean) {
  return useQuery({
    queryKey: QK.jobs.logs(id),
    queryFn: () => jobsApi.getJobLogs(id),
    enabled: Boolean(id),
    refetchInterval: isLive ? 1_500 : false,
  })
}

export function useJobExecutions(id: string) {
  return useQuery({
    queryKey: QK.jobs.executions(id),
    queryFn: () => jobsApi.getJobExecutions(id),
    enabled: Boolean(id),
  })
}

export function useJobTimeline(id: string) {
  return useQuery({
    queryKey: QK.jobs.timeline(id),
    queryFn: () => jobsApi.getJobTimeline(id),
    enabled: Boolean(id),
  })
}

export function useSubmitJob() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (input: JobCreateInput) => jobsApi.createJob(input),
    onSuccess: (job) => {
      void qc.invalidateQueries({ queryKey: QK.jobs.all })
      toast({ title: 'Job submitted', description: job.id, variant: 'success' })
    },
    onError: (error: Error) => {
      toast({ title: 'Submit failed', description: error.message, variant: 'destructive' })
    },
  })
}

export function useCancelJob() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => jobsApi.cancelJob(id),
    onSuccess: (job) => {
      void qc.invalidateQueries({ queryKey: QK.jobs.all })
      toast({ title: 'Job cancelled', description: job.id })
    },
    onError: (error: Error) => {
      toast({ title: 'Cancel failed', description: error.message, variant: 'destructive' })
    },
  })
}

export function useRetryJob() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => jobsApi.retryJob(id),
    onSuccess: (job) => {
      void qc.invalidateQueries({ queryKey: QK.jobs.all })
      void qc.invalidateQueries({ queryKey: QK.dlq.all })
      toast({ title: 'Job re-queued', description: job.id, variant: 'success' })
    },
    onError: (error: Error) => {
      toast({ title: 'Retry failed', description: error.message, variant: 'destructive' })
    },
  })
}

export function useBulkCancelJobs() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (ids: string[]) => jobsApi.cancelJobs(ids),
    onSuccess: ({ cancelled }) => {
      void qc.invalidateQueries({ queryKey: QK.jobs.all })
      toast({ title: `${cancelled} jobs cancelled` })
    },
  })
}

export function useBulkRetryJobs() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (ids: string[]) => jobsApi.retryJobs(ids),
    onSuccess: ({ retried }) => {
      void qc.invalidateQueries({ queryKey: QK.jobs.all })
      toast({ title: `${retried} jobs re-queued`, variant: 'success' })
    },
  })
}

export function useDeleteJob() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => jobsApi.deleteJob(id),
    onSuccess: (_result, id) => {
      void qc.invalidateQueries({ queryKey: QK.jobs.all })
      toast({ title: 'Job deleted', description: id })
    },
    onError: (error: Error) => {
      toast({ title: 'Delete failed', description: error.message, variant: 'destructive' })
    },
  })
}

/** Lease/heartbeat tarixi — ishonchlilik tabi uchun. */
export function useJobLeaseHistory(id: string, enabled = true) {
  return useQuery({
    queryKey: QK.jobs.lease(id),
    queryFn: () => jobsApi.getJobLeaseHistory(id),
    enabled,
  })
}

/** Idempotency ma'lumoti — idempotency tabi uchun. */
export function useJobIdempotency(id: string, enabled = true) {
  return useQuery({
    queryKey: QK.jobs.idempotency(id),
    queryFn: () => jobsApi.getJobIdempotency(id),
    enabled,
  })
}

// ── Admin amallari ─────────────────────────────────────────────────────────

/**
 * Majburiy yiqitish.
 *
 * `useCancelJob` dan farqi natijada: bu job `failed` (yoki urinishlar
 * tugagan bo'lsa `dead_letter`) holatiga o'tadi, ya'ni statistikaga
 * kiradi va DLQ'ga tushishi mumkin.
 */
export function useForceFailJob() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: { id: string; reason?: string }) =>
      jobsApi.forceFailJob(args.id, args.reason),
    onSuccess: (job) => {
      void qc.invalidateQueries({ queryKey: QK.jobs.all })
      void qc.invalidateQueries({ queryKey: QK.dlq.all })
      toast({
        title: job.status === 'dead_letter' ? 'Force-failed into the DLQ' : 'Job force-failed',
        description:
          job.status === 'dead_letter'
            ? `${job.id} had used every retry, so it went straight to the dead letter queue.`
            : job.id,
        variant: 'destructive',
      })
    },
    onError: (error: Error) => {
      toast({ title: 'Could not force fail', description: error.message, variant: 'destructive' })
    },
  })
}

export function useSetJobPriority() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: { id: string; priority: Priority }) =>
      jobsApi.setJobPriority(args.id, args.priority),
    onSuccess: (job) => {
      void qc.invalidateQueries({ queryKey: QK.jobs.all })
      toast({ title: `Priority set to ${job.priority}`, description: job.id })
    },
    onError: (error: Error) => {
      toast({ title: 'Could not change priority', description: error.message, variant: 'destructive' })
    },
  })
}

export function useReassignJob() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: { id: string; workerId: string | null }) =>
      jobsApi.reassignJob(args.id, args.workerId),
    onSuccess: (job, variables) => {
      void qc.invalidateQueries({ queryKey: QK.jobs.all })
      void qc.invalidateQueries({ queryKey: QK.workers.all })
      toast({
        title: variables.workerId ? 'Reassigned' : 'Returned to the queue',
        description: variables.workerId
          ? `${job.id} is now pinned to ${variables.workerId}.`
          : `${job.id} will be picked up by the next free worker.`,
      })
    },
    onError: (error: Error) => {
      toast({ title: 'Could not reassign', description: error.message, variant: 'destructive' })
    },
  })
}
