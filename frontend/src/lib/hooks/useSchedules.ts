'use client'

/** Jadvallar va shablonlar. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type {
  ScheduleCreateInput,
  ScheduleFilters,
  TemplateCreateInput,
} from '@/types'
import type { SchedulePatch } from '@/lib/api/schedules.api'
import { schedulesApi } from '@/lib/api'
import { useToast } from '@/components/common/ToastProvider'

import { QK } from './keys'

export function useSchedules(filters: ScheduleFilters = {}) {
  return useQuery({
    queryKey: QK.schedules.list(filters),
    queryFn: () => schedulesApi.getSchedules(filters),
    placeholderData: (previous) => previous,
  })
}

export function useSchedule(id: string | null) {
  return useQuery({
    queryKey: QK.schedules.detail(id ?? 'none'),
    queryFn: () => schedulesApi.getSchedule(id as string),
    enabled: id !== null,
  })
}

export function useScheduleRuns(id: string | null) {
  return useQuery({
    queryKey: QK.schedules.runs(id ?? 'none'),
    queryFn: () => schedulesApi.getScheduleRuns(id as string),
    enabled: id !== null,
  })
}

/**
 * Cron tekshiruvi.
 *
 * Foydalanuvchi yozayotganda chaqiriladi, shuning uchun `placeholderData`
 * bilan oldingi natija ushlab turiladi — aks holda har harfda panel
 * bo'shab-to'lib ko'zni charchatadi.
 */
export function useCronValidation(expression: string) {
  return useQuery({
    queryKey: QK.schedules.cron(expression),
    queryFn: () => schedulesApi.validateCron(expression),
    enabled: expression.trim().length > 0,
    placeholderData: (previous) => previous,
    staleTime: Number.POSITIVE_INFINITY,
  })
}

export function useSetScheduleEnabled() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: { id: string; enabled: boolean }) =>
      schedulesApi.setScheduleEnabled(args.id, args.enabled),
    onSuccess: (schedule) => {
      void qc.invalidateQueries({ queryKey: QK.schedules.all })
      toast({
        title: schedule.status === 'active' ? 'Schedule resumed' : 'Schedule paused',
        description:
          schedule.status === 'active'
            ? `"${schedule.name}" will run again on its cron.`
            : `"${schedule.name}" will not run until resumed.`,
      })
    },
  })
}

export function useRunScheduleNow() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => schedulesApi.runScheduleNow(id),
    onSuccess: ({ job_id }) => {
      void qc.invalidateQueries({ queryKey: QK.schedules.all })
      void qc.invalidateQueries({ queryKey: QK.jobs.all })
      toast({ title: 'Run queued', description: job_id, variant: 'success' })
    },
  })
}

export function useUpdateSchedule() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: { id: string; patch: SchedulePatch }) =>
      schedulesApi.updateSchedule(args.id, args.patch),
    onSuccess: (schedule) => {
      void qc.invalidateQueries({ queryKey: QK.schedules.all })
      toast({ title: 'Schedule updated', description: schedule.name, variant: 'success' })
    },
    onError: (error: Error) => {
      toast({ title: 'Update failed', description: error.message, variant: 'destructive' })
    },
  })
}

export function useCreateSchedule() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (input: ScheduleCreateInput) => schedulesApi.createSchedule(input),
    onSuccess: (schedule) => {
      void qc.invalidateQueries({ queryKey: QK.schedules.all })
      toast({ title: 'Schedule created', description: schedule.name, variant: 'success' })
    },
    onError: (error: Error) => {
      toast({ title: 'Could not create', description: error.message, variant: 'destructive' })
    },
  })
}

export function useDeleteSchedule() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => schedulesApi.deleteSchedule(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.schedules.all })
      toast({ title: 'Schedule deleted' })
    },
  })
}

// ── Shablonlar ─────────────────────────────────────────────────────────────

export function useTemplates() {
  return useQuery({ queryKey: QK.templates.list, queryFn: () => schedulesApi.getTemplates() })
}

export function useCreateTemplate() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (input: TemplateCreateInput) => schedulesApi.createTemplate(input),
    onSuccess: (template) => {
      void qc.invalidateQueries({ queryKey: QK.templates.all })
      toast({ title: 'Template saved', description: template.name, variant: 'success' })
    },
    onError: (error: Error) => {
      toast({ title: 'Could not save', description: error.message, variant: 'destructive' })
    },
  })
}

export function useDeleteTemplate() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => schedulesApi.deleteTemplate(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.templates.all })
      toast({ title: 'Template deleted' })
    },
    onError: (error: Error) => {
      toast({ title: 'Could not delete', description: error.message, variant: 'destructive' })
    },
  })
}

export function useMarkTemplateUsed() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => schedulesApi.markTemplateUsed(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.templates.all })
    },
  })
}
