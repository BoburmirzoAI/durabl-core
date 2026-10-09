'use client'

/** DLQ ro'yxati, statistikasi va amallari. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type { DlqFilters } from '@/types'
import { dlqApi } from '@/lib/api'
import { useToast } from '@/components/common/ToastProvider'

import { QK } from './keys'

export function useDlqEntries(filters: DlqFilters) {
  return useQuery({
    queryKey: QK.dlq.list(filters),
    queryFn: () => dlqApi.getDlqEntries(filters),
    placeholderData: (previous) => previous,
  })
}

/**
 * DLQ statistikasi — sidebar nishoni ham shundan oladi, shuning uchun
 * `staleTime` qisqa va ma'lumot umumiy kesh'da bo'lishi muhim.
 */
export function useDlqStats() {
  return useQuery({
    queryKey: QK.dlq.stats,
    queryFn: () => dlqApi.getDlqStats(),
    staleTime: 15_000,
    refetchInterval: 30_000,
  })
}

export function useRetryDlqEntry() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => dlqApi.retryDlqEntry(id),
    onSuccess: (result) => {
      void qc.invalidateQueries({ queryKey: QK.dlq.all })
      void qc.invalidateQueries({ queryKey: QK.jobs.all })
      toast({ title: 'Re-queued', description: result.job_id, variant: 'success' })
    },
    onError: (error: Error) => {
      toast({ title: 'Retry failed', description: error.message, variant: 'destructive' })
    },
  })
}

export function useDeleteDlqEntry() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => dlqApi.deleteDlqEntry(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.dlq.all })
      toast({ title: 'Entry deleted' })
    },
    onError: (error: Error) => {
      toast({ title: 'Delete failed', description: error.message, variant: 'destructive' })
    },
  })
}

export function useBulkRetryDlq() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (ids: string[]) => dlqApi.retryDlqEntries(ids),
    onSuccess: ({ retried }) => {
      void qc.invalidateQueries({ queryKey: QK.dlq.all })
      toast({ title: `${retried} entries re-queued`, variant: 'success' })
    },
  })
}

export function useBulkDeleteDlq() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (ids: string[]) => dlqApi.deleteDlqEntries(ids),
    onSuccess: ({ deleted }) => {
      void qc.invalidateQueries({ queryKey: QK.dlq.all })
      toast({ title: `${deleted} entries deleted` })
    },
  })
}

export function useRetryAllDlq() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: () => dlqApi.retryAllDlq(),
    onSuccess: ({ retried }) => {
      void qc.invalidateQueries({ queryKey: QK.dlq.all })
      void qc.invalidateQueries({ queryKey: QK.jobs.all })
      toast({ title: `${retried} entries re-queued`, variant: 'success' })
    },
  })
}

/**
 * Hal qilingan dead letter'larni tozalash (admin).
 *
 * `useRetryAllDlq` dan farqi: bu HECH NARSANI qayta urinmaydi, faqat
 * allaqachon hal qilingan yozuvlarni o'chiradi.
 */
export function usePurgeDlq() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: () => dlqApi.purgeResolvedDlq(),
    onSuccess: ({ purged }) => {
      void qc.invalidateQueries({ queryKey: QK.dlq.all })
      toast({
        title: purged === 0 ? 'Nothing to purge' : `Purged ${purged} resolved entries`,
        description: purged === 0 ? 'No resolved dead letters were found.' : undefined,
      })
    },
  })
}
