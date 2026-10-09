'use client'

/** Admin operatsion sahifalari: audit, billing, e'lonlar, tiketlar. */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import type {
  Announcement,
  AnnouncementInput,
  AuditFilters,
  TicketFilters,
  TicketPriority,
  TicketStatus,
} from '@/types'
import { adminOpsApi } from '@/lib/api'
import { useToast } from '@/components/common/ToastProvider'

import { QK } from './keys'

export function useAuditLog(filters: AuditFilters) {
  return useQuery({
    queryKey: QK.adminOps.audit(filters),
    queryFn: () => adminOpsApi.getAuditLog(filters),
    placeholderData: (previous) => previous,
  })
}

export function usePlatformBilling() {
  return useQuery({
    queryKey: QK.adminOps.billing,
    queryFn: () => adminOpsApi.getPlatformBilling(),
  })
}

// ── E'lonlar ───────────────────────────────────────────────────────────────

export function useAnnouncements() {
  return useQuery({
    queryKey: QK.adminOps.announcements,
    queryFn: () => adminOpsApi.getAnnouncements(),
  })
}

export function useCreateAnnouncement() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (input: AnnouncementInput) => adminOpsApi.createAnnouncement(input),
    onSuccess: (announcement) => {
      void qc.invalidateQueries({ queryKey: QK.adminOps.announcements })
      toast({
        title: announcement.status === 'live' ? 'Announcement is live' : 'Announcement scheduled',
        description: announcement.title,
        variant: 'success',
      })
    },
    onError: (error: Error) => {
      toast({ title: 'Could not publish', description: error.message, variant: 'destructive' })
    },
  })
}

export function useSetAnnouncementStatus() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: { id: string; status: Announcement['status'] }) =>
      adminOpsApi.setAnnouncementStatus(args.id, args.status),
    onSuccess: (announcement) => {
      void qc.invalidateQueries({ queryKey: QK.adminOps.announcements })
      toast({
        title:
          announcement.status === 'ended'
            ? 'Announcement ended'
            : announcement.status === 'live'
              ? 'Announcement is live'
              : 'Announcement updated',
      })
    },
  })
}

export function useDeleteAnnouncement() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (id: string) => adminOpsApi.deleteAnnouncement(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: QK.adminOps.announcements })
      toast({ title: 'Announcement deleted' })
    },
    onError: (error: Error) => {
      toast({ title: 'Could not delete', description: error.message, variant: 'destructive' })
    },
  })
}

// ── Tiketlar ───────────────────────────────────────────────────────────────

export function useTickets(filters: TicketFilters) {
  return useQuery({
    queryKey: QK.adminOps.tickets(filters),
    queryFn: () => adminOpsApi.getTickets(filters),
    placeholderData: (previous) => previous,
  })
}

export function useReplyToTicket() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: { id: string; body: string }) =>
      adminOpsApi.replyToTicket(args.id, args.body),
    onSuccess: (ticket) => {
      void qc.invalidateQueries({ queryKey: QK.adminOps.all })
      toast({ title: 'Reply sent', description: ticket.user_email, variant: 'success' })
    },
    onError: (error: Error) => {
      toast({ title: 'Could not send', description: error.message, variant: 'destructive' })
    },
  })
}

export function useUpdateTicket() {
  const qc = useQueryClient()
  const { toast } = useToast()
  return useMutation({
    mutationFn: (args: {
      id: string
      patch: { status?: TicketStatus; priority?: TicketPriority; assignee?: string | null }
    }) => adminOpsApi.updateTicket(args.id, args.patch),
    onSuccess: (ticket) => {
      void qc.invalidateQueries({ queryKey: QK.adminOps.all })
      toast({ title: `Ticket is now ${ticket.status}` })
    },
  })
}

// ── Platforma agregatlari ──────────────────────────────────────────────────

export function usePlatformExecutions() {
  return useQuery({
    queryKey: QK.adminOps.executions,
    queryFn: () => adminOpsApi.getPlatformExecutions(),
  })
}

export function usePlatformDlq() {
  return useQuery({ queryKey: QK.adminOps.dlq, queryFn: () => adminOpsApi.getPlatformDlq() })
}

export function usePlatformWebhooks() {
  return useQuery({
    queryKey: QK.adminOps.webhooks,
    queryFn: () => adminOpsApi.getPlatformWebhooks(),
  })
}

export function usePlanWorkload() {
  return useQuery({
    queryKey: QK.adminOps.planWorkload,
    queryFn: () => adminOpsApi.getPlanWorkload(),
  })
}
