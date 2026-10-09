'use client'

/** Worker fleet va tizim holati. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { workersApi } from '@/lib/api'
import { useToast } from '@/components/common/ToastProvider'

import { QK } from './keys'

/** Worker'lar — jonli ko'rsatkich, shuning uchun tez-tez yangilanadi. */
export function useWorkers() {
  return useQuery({
    queryKey: QK.workers.list,
    queryFn: () => workersApi.getWorkers(),
    refetchInterval: 5_000,
  })
}

export function useQueueDepths() {
  return useQuery({
    queryKey: QK.workers.queues,
    queryFn: () => workersApi.getQueueDepths(),
    refetchInterval: 5_000,
  })
}

export function useSystemStatus() {
  return useQuery({
    queryKey: QK.workers.system,
    queryFn: () => workersApi.getSystemStatus(),
    refetchInterval: 5_000,
  })
}

export function useDrainWorker() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => workersApi.drainWorker(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.workers.all })
      toast({ title: 'Worker draining' })
    },
  })
}

export function useResumeWorker() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => workersApi.resumeWorker(id),
    onSuccess: (worker) => {
      void qc.invalidateQueries({ queryKey: QK.workers.all })
      toast({ title: 'Worker resumed', description: worker.id, variant: 'success' })
    },
  })
}

export function useRestartWorker() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => workersApi.restartWorker(id),
    onSuccess: (worker) => {
      void qc.invalidateQueries({ queryKey: QK.workers.all })
      toast({ title: 'Worker restarting', description: `${worker.id} is booting` })
    },
    onError: (error: Error) => {
      toast({ title: 'Restart failed', description: error.message, variant: 'destructive' })
    },
  })
}

export function useAddWorker() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: () => workersApi.addWorker(),
    onSuccess: (worker) => {
      void qc.invalidateQueries({ queryKey: QK.workers.all })
      toast({
        title: 'Worker added',
        description: `${worker.id} · ${worker.region}`,
        variant: 'success',
      })
    },
  })
}

/** Texnik xizmat rejimi, navbat holati va funksiya bayroqlari. */
export function useSystemControls() {
  return useQuery({
    queryKey: QK.workers.controls,
    queryFn: () => workersApi.getSystemControls(),
  })
}

export function useSetMaintenance() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (enabled: boolean) => workersApi.setMaintenance(enabled),
    onSuccess: ({ maintenance_mode }) => {
      void qc.invalidateQueries({ queryKey: QK.workers.all })
      toast({
        title: maintenance_mode ? 'Maintenance mode ON' : 'Maintenance mode OFF',
        description: maintenance_mode
          ? 'New job submissions are rejected while this is on.'
          : 'Job submissions accepted again.',
        variant: maintenance_mode ? 'destructive' : 'success',
      })
    },
  })
}

export function useSetQueuePause() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (paused: boolean) => workersApi.setQueuePause(paused),
    onSuccess: ({ queue_paused }) => {
      void qc.invalidateQueries({ queryKey: QK.workers.all })
      toast({
        title: queue_paused ? 'Queue paused' : 'Queue resumed',
        description: queue_paused ? 'Workers finish current jobs but take no new ones.' : undefined,
        variant: queue_paused ? 'destructive' : 'success',
      })
    },
  })
}

export function useSetFeatureFlag() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: ({ key, enabled }: { key: string; enabled: boolean }) =>
      workersApi.setFeatureFlag(key, enabled),
    onSuccess: (flag) => {
      void qc.invalidateQueries({ queryKey: QK.workers.controls })
      toast({ title: `${flag.label} ${flag.enabled ? 'enabled' : 'disabled'}` })
    },
  })
}

export function useRestartSubsystem() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (subsystem: 'database' | 'redis' | 'sandbox') =>
      workersApi.restartSubsystem(subsystem),
    onSuccess: ({ subsystem }) => {
      void qc.invalidateQueries({ queryKey: QK.workers.all })
      toast({ title: `${subsystem} restarted`, variant: 'success' })
    },
  })
}

export function useFlushCache() {
  const { toast } = useToast()
  return useMutation({
    mutationFn: () => workersApi.flushCache(),
    onSuccess: ({ keys_removed }) => {
      toast({
        title: 'Cache flushed',
        description: `${keys_removed.toLocaleString()} keys removed`,
        variant: 'success',
      })
    },
  })
}

export function useRebuildIndex() {
  const { toast } = useToast()
  return useMutation({
    mutationFn: () => workersApi.rebuildIndex(),
    onSuccess: ({ documents }) => {
      toast({
        title: 'Index rebuilt',
        description: `${documents.toLocaleString()} documents indexed`,
        variant: 'success',
      })
    },
  })
}

export function useClearDlq() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: () => workersApi.clearDlq(),
    onSuccess: ({ removed }) => {
      void qc.invalidateQueries({ queryKey: QK.dlq.all })
      void qc.invalidateQueries({ queryKey: QK.workers.all })
      toast({ title: `DLQ cleared`, description: `${removed} entries removed`, variant: 'success' })
    },
  })
}
