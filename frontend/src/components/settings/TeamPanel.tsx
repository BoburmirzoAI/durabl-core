'use client'

import { useState } from 'react'

import { ConfirmDialog } from '@/components/common/ConfirmDialog'
import { RelativeTime } from '@/components/common/RelativeTime'
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { SkeletonRows } from '@/components/ui/skeleton'
import {
  useChangeTeamRole,
  useInviteTeamMember,
  useRemoveTeamMember,
  useResendInvite,
  useTeamMembers,
} from '@/lib/hooks/useAccount'
import { cn } from '@/lib/utils/cn'
import { formatTimestamp } from '@/lib/utils/time'
import { TEAM_ROLES, TEAM_ROLE_INFO, type TeamMember, type TeamRole } from '@/types'

const GRID = 'minmax(190px,1.6fr) 110px 100px minmax(120px,1fr) 44px'

const STATUS_CLASS: Record<TeamMember['status'], string> = {
  active: 'bg-success/[0.12] text-success',
  invited: 'bg-pending/[0.12] text-pending',
  suspended: 'bg-failed/[0.12] text-failed',
}

/**
 * Jamoa boshqaruvi.
 *
 * ## Rollar nega to'rtta
 *
 * Ikkita rol (admin/a'zo) yetarli emas: CI uchun job yuboradigan
 * dasturchi bilan faqat hisobot ko'radigan menejer bir xil huquqqa ega
 * bo'lmasligi kerak. Beshta esa ortiqcha — har bir rolni tushuntirib
 * berishning iloji bo'lmay qoladi.
 *
 * `owner` alohida: uni taklif qilib ham, o'zgartirib ham bo'lmaydi,
 * chunki hisobda aniq bitta egasi bo'lishi shart.
 */
export function TeamPanel() {
  const members = useTeamMembers()
  const invite = useInviteTeamMember()
  const changeRole = useChangeTeamRole()
  const remove = useRemoveTeamMember()
  const resend = useResendInvite()

  const [inviteOpen, setInviteOpen] = useState(false)
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<TeamRole>('developer')
  const [confirmRemove, setConfirmRemove] = useState<TeamMember | null>(null)

  const rows = members.data ?? []
  const active = rows.filter((m) => m.status === 'active').length
  const pending = rows.filter((m) => m.status === 'invited').length

  return (
    <>
      <div className="space-y-3.5">
        <Card className="overflow-hidden">
          <CardHeader>
            <div className="flex flex-wrap items-start gap-4">
              <div>
                <CardTitle className="text-md">Team members</CardTitle>
                <CardDescription>
                  {members.data
                    ? `${active} active${pending > 0 ? `, ${pending} pending invite${pending === 1 ? '' : 's'}` : ''}`
                    : 'Who can access this account'}
                </CardDescription>
              </div>
              <Button
                variant="primary"
                className="ml-auto"
                onClick={() => {
                  setEmail('')
                  setRole('developer')
                  setInviteOpen(true)
                }}
              >
                Invite member
              </Button>
            </div>
          </CardHeader>

          <div className="table-head grid items-center gap-3 px-4" style={{ gridTemplateColumns: GRID }}>
            <span>Member</span>
            <span>Role</span>
            <span>Status</span>
            <span>Last active</span>
            <span className="sr-only">Actions</span>
          </div>

          {members.isLoading && !members.data ? (
            <SkeletonRows rows={4} columns={GRID} />
          ) : (
            rows.map((member) => (
              <div
                key={member.id}
                className="grid h-[52px] items-center gap-3 border-b border-line-subtle px-4 last:border-b-0 hover:bg-surface-3"
                style={{ gridTemplateColumns: GRID }}
              >
                <span className="flex min-w-0 items-center gap-2.5">
                  <span
                    className={cn(
                      'flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-2xs font-semibold',
                      member.status === 'active'
                        ? 'bg-accent/[0.16] text-accent-light'
                        : 'bg-surface-3 text-fg-faint',
                    )}
                  >
                    {member.initials}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-base text-fg-soft">
                      {member.full_name ?? member.email}
                    </span>
                    {member.full_name ? (
                      <span className="block truncate text-xs text-fg-faint">{member.email}</span>
                    ) : null}
                  </span>
                </span>

                <span>
                  <Badge size="sm" variant="outline" className="capitalize">
                    {member.role}
                  </Badge>
                </span>

                <span>
                  <Badge size="sm" className={STATUS_CLASS[member.status]}>
                    {member.status}
                  </Badge>
                </span>

                <span className="min-w-0">
                  {member.status === 'invited' ? (
                    <span className="block truncate text-xs text-fg-faint">
                      expires{' '}
                      {member.invite_expires_at ? formatTimestamp(member.invite_expires_at) : '—'}
                    </span>
                  ) : (
                    <RelativeTime
                      value={member.last_active_at}
                      className="block truncate text-sm text-fg-muted"
                    />
                  )}
                </span>

                <span className="flex justify-end">
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button
                        type="button"
                        aria-label={`Actions for ${member.email}`}
                        className="inline-flex h-[26px] w-[26px] items-center justify-center rounded-md text-fg-dim transition-colors hover:bg-line hover:text-fg"
                      >
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden>
                          <circle cx="12" cy="5" r="1.6" />
                          <circle cx="12" cy="12" r="1.6" />
                          <circle cx="12" cy="19" r="1.6" />
                        </svg>
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent>
                      {member.status === 'invited' ? (
                        <DropdownMenuItem
                          disabled={resend.isPending}
                          onSelect={() => resend.mutate(member.id)}
                        >
                          Resend invitation
                        </DropdownMenuItem>
                      ) : null}
                      {TEAM_ROLES.filter((r) => r !== 'owner' && r !== member.role).map((r) => (
                        <DropdownMenuItem
                          key={r}
                          disabled={member.role === 'owner' || changeRole.isPending}
                          onSelect={() => changeRole.mutate({ id: member.id, role: r })}
                        >
                          Change to {r}
                        </DropdownMenuItem>
                      ))}
                      <DropdownMenuItem
                        danger
                        disabled={member.role === 'owner'}
                        onSelect={() => setConfirmRemove(member)}
                      >
                        {member.status === 'invited' ? 'Cancel invitation' : 'Remove from team'}
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </span>
              </div>
            ))
          )}
        </Card>

        <Card className="overflow-hidden">
          <CardHeader>
            <CardTitle className="text-md">What each role can do</CardTitle>
          </CardHeader>
          <div className="divide-y divide-line-subtle">
            {TEAM_ROLES.map((r) => (
              <div key={r} className="flex flex-wrap items-baseline gap-3 px-4 py-2.5">
                <span className="w-[86px] shrink-0 text-base font-medium capitalize text-fg-soft">
                  {TEAM_ROLE_INFO[r].title}
                </span>
                <span className="min-w-0 flex-1 text-sm leading-[1.55] text-fg-dim">
                  {TEAM_ROLE_INFO[r].description}
                </span>
              </div>
            ))}
          </div>
        </Card>
      </div>

      <Dialog open={inviteOpen} onOpenChange={setInviteOpen}>
        <DialogContent width="md">
          <DialogHeader>
            <div>
              <DialogTitle>Invite a team member</DialogTitle>
              <DialogDescription>
                They receive an email with a link that expires in 7 days.
              </DialogDescription>
            </div>
          </DialogHeader>

          <DialogBody className="space-y-4">
            <label className="block">
              <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                Email address
              </span>
              <Input
                autoFocus
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="teammate@company.com"
              />
            </label>

            <div>
              <span className="mb-1.5 block text-2xs font-semibold uppercase tracking-[.05em] text-fg-faint">
                Role
              </span>
              <div className="space-y-px">
                {TEAM_ROLES.filter((r) => r !== 'owner').map((r) => (
                  <label
                    key={r}
                    className={cn(
                      'flex cursor-pointer items-start gap-3 rounded-lg px-2.5 py-2.5 transition-colors',
                      role === r ? 'bg-accent/[0.06]' : 'hover:bg-surface-3',
                    )}
                  >
                    <input
                      type="radio"
                      name="team-role"
                      checked={role === r}
                      onChange={() => setRole(r)}
                      className="mt-1 h-3.5 w-3.5 shrink-0 accent-[hsl(var(--accent))]"
                    />
                    <span className="min-w-0">
                      <span className="block text-base font-medium text-fg-soft">
                        {TEAM_ROLE_INFO[r].title}
                      </span>
                      <span className="mt-0.5 block text-sm leading-[1.5] text-fg-dim">
                        {TEAM_ROLE_INFO[r].description}
                      </span>
                    </span>
                  </label>
                ))}
              </div>
            </div>
          </DialogBody>

          <DialogFooter>
            <Button variant="ghost" onClick={() => setInviteOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              size="md"
              disabled={email.trim().length === 0 || invite.isPending}
              onClick={() =>
                invite.mutate({ email, role }, { onSuccess: () => setInviteOpen(false) })
              }
            >
              {invite.isPending ? 'Sending…' : 'Send invitation'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={confirmRemove !== null}
        onOpenChange={(open) => {
          if (!open) setConfirmRemove(null)
        }}
        title={
          confirmRemove?.status === 'invited' ? 'Cancel this invitation?' : 'Remove from team?'
        }
        description={
          confirmRemove
            ? confirmRemove.status === 'invited'
              ? `${confirmRemove.email} will not be able to use the invitation link.`
              : `${confirmRemove.email} loses access immediately. Jobs they submitted are kept, and any API key they created stays active — revoke it separately if needed.`
            : ''
        }
        confirmLabel={confirmRemove?.status === 'invited' ? 'Cancel invitation' : 'Remove'}
        destructive
        pending={remove.isPending}
        onConfirm={() => {
          if (confirmRemove) remove.mutate(confirmRemove.id)
          setConfirmRemove(null)
        }}
      />
    </>
  )
}
