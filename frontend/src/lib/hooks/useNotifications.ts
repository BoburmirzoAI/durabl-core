'use client'

/** Bildirishnomalar — qo'ng'iroq paneli va `/notifications` sahifasi. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { notificationsApi } from '@/lib/api'
import { useToast } from '@/components/common/ToastProvider'
import type { NotificationFilters } from '@/types'

import { QK } from './keys'

export function useNotifications(filters: NotificationFilters = {}) {
  return useQuery({
    queryKey: QK.notifications.list(filters),
    queryFn: () => notificationsApi.listNotifications(filters),
    placeholderData: (previous) => previous,
  })
}

/** O'qilmaganlar soni — qo'ng'iroqdagi nishon. */
export function useUnreadCount() {
  return useQuery({
    queryKey: QK.notifications.unread,
    queryFn: () => notificationsApi.getUnreadCount(),
    refetchInterval: 30_000,
  })
}

export function useMarkNotificationRead() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => notificationsApi.markRead(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: QK.notifications.all }),
  })
}

export function useMarkAllRead() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: () => notificationsApi.markAllRead(),
    onSuccess: (data) => {
      void qc.invalidateQueries({ queryKey: QK.notifications.all })
      toast({
        title: data.updated > 0 ? 'All caught up' : 'Nothing to mark',
        description:
          data.updated > 0 ? `${data.updated} notifications marked as read.` : undefined,
        variant: 'success',
      })
    },
  })
}
