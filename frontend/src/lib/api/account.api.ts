/** Hisob sozlamalari endpointlari. */

import type {
  ApiDefaults,
  LoginEvent,
  NotificationEvent,
  NotificationSetting,
  TeamInviteInput,
  TeamMember,
  TeamRole,
  TwoFactorSetup,
  TwoFactorStatus,
  UserSession,
} from '@/types'
import {
  allNotificationSettings,
  allSessions,
  allTeamMembers,
  apiDefaults,
  apiDefaultsStore,
  generateRecoveryCodes,
  generateTotpSecret,
  loginHistory,
  notificationSettingStore,
  sessionStore,
  teamStore,
  twoFactorStatus,
  twoFactorStore,
} from '@/lib/mock/account'
import { Rng } from '@/lib/mock/seed'

import { ApiError, mockResponse, notFound } from './client'

// ───────────────────────────────────────────────────────────────────────────
// Sessiyalar
// ───────────────────────────────────────────────────────────────────────────

/** `GET /api/v1/account/sessions` */
export async function getSessions(): Promise<UserSession[]> {
  return mockResponse(() => allSessions(), 300)
}

/** `DELETE /api/v1/account/sessions/{id}` */
export async function revokeSession(id: string): Promise<{ revoked: boolean }> {
  return mockResponse(() => {
    const session = allSessions().find((s) => s.id === id)
    if (!session) throw notFound('Session', id)
    if (session.is_current) {
      throw new ApiError({
        status: 409,
        code: 'CURRENT_SESSION',
        message: 'You cannot revoke the session you are using — sign out instead',
      })
    }
    sessionStore.remove(id)
    return { revoked: true }
  }, 350)
}

/**
 * `POST /api/v1/account/sessions/revoke-others`
 *
 * Buzilgan hisobni tiklashda eng tez harakat: joriy sessiyadan boshqa
 * HAMMASI uziladi.
 */
export async function revokeOtherSessions(): Promise<{ revoked: number }> {
  return mockResponse(() => {
    const others = allSessions().filter((s) => !s.is_current)
    sessionStore.removeMany(others.map((s) => s.id))
    return { revoked: others.length }
  }, 500)
}

/** `GET /api/v1/account/login-history` */
export async function getLoginHistory(): Promise<LoginEvent[]> {
  return mockResponse(() => loginHistory(), 300)
}

// ───────────────────────────────────────────────────────────────────────────
// 2FA
// ───────────────────────────────────────────────────────────────────────────

/** `GET /api/v1/account/2fa` */
export async function getTwoFactorStatus(): Promise<TwoFactorStatus> {
  return mockResponse(() => twoFactorStatus(), 200)
}

/**
 * `POST /api/v1/account/2fa/setup`
 *
 * Kalit hali YOQILMAYDI — foydalanuvchi avval ilovadan kelgan kodni
 * tasdiqlashi kerak. Aks holda noto'g'ri sozlangan ilova bilan hisobga
 * kirib bo'lmay qoladi.
 */
export async function setupTwoFactor(email: string): Promise<TwoFactorSetup> {
  return mockResponse(() => {
    if (twoFactorStatus().enabled) {
      throw new ApiError({
        status: 409,
        code: 'ALREADY_ENABLED',
        message: 'Two-factor authentication is already enabled',
      })
    }
    const secret = generateTotpSecret()
    const label = encodeURIComponent(`Durabl:${email}`)
    return {
      secret,
      otpauth_url: `otpauth://totp/${label}?secret=${secret}&issuer=Durabl`,
      recovery_codes: generateRecoveryCodes(),
    }
  }, 450)
}

/**
 * `POST /api/v1/account/2fa/verify`
 *
 * Mock rejimida HAR QANDAY 6 xonali kod qabul qilinadi — haqiqiy TOTP
 * tekshiruvi server tomonda bo'ladi. Shakl tekshiruvi esa saqlanadi,
 * aks holda tugma "nima bo'lsa ham ishlaydi" bo'lib qolardi.
 */
export async function verifyTwoFactor(code: string): Promise<TwoFactorStatus> {
  return mockResponse(() => {
    if (!/^\d{6}$/.test(code.trim())) {
      throw new ApiError({
        status: 422,
        code: 'INVALID_CODE',
        message: 'The code must be 6 digits',
      })
    }
    twoFactorStore.update('self', {
      enabled: true,
      enabled_at: new Date().toISOString(),
      recovery_codes_left: 10,
    })
    return twoFactorStatus()
  }, 600)
}

/** `DELETE /api/v1/account/2fa` */
export async function disableTwoFactor(): Promise<TwoFactorStatus> {
  return mockResponse(() => {
    twoFactorStore.update('self', { enabled: false, enabled_at: null, recovery_codes_left: 0 })
    return twoFactorStatus()
  }, 400)
}

/** `POST /api/v1/account/2fa/recovery-codes` — eskilarini bekor qiladi. */
export async function regenerateRecoveryCodes(): Promise<string[]> {
  return mockResponse(() => {
    if (!twoFactorStatus().enabled) {
      throw new ApiError({
        status: 409,
        code: 'NOT_ENABLED',
        message: 'Two-factor authentication is not enabled',
      })
    }
    const codes = generateRecoveryCodes()
    twoFactorStore.update('self', { recovery_codes_left: codes.length })
    return codes
  }, 450)
}

// ───────────────────────────────────────────────────────────────────────────
// Jamoa
// ───────────────────────────────────────────────────────────────────────────

/** `GET /api/v1/team/members` */
export async function getTeamMembers(): Promise<TeamMember[]> {
  return mockResponse(() => allTeamMembers(), 320)
}

/** `POST /api/v1/team/invites` */
export async function inviteTeamMember(input: TeamInviteInput): Promise<TeamMember> {
  return mockResponse(() => {
    const email = input.email.trim().toLowerCase()
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      throw new ApiError({ status: 422, code: 'INVALID_EMAIL', message: 'That email address is not valid' })
    }
    if (allTeamMembers().some((m) => m.email.toLowerCase() === email)) {
      throw new ApiError({
        status: 409,
        code: 'ALREADY_MEMBER',
        message: 'That email is already on the team',
      })
    }
    if (input.role === 'owner') {
      throw new ApiError({
        status: 422,
        code: 'OWNER_UNIQUE',
        message: 'Ownership cannot be granted through an invitation',
      })
    }
    const rng = new Rng(Date.now() % 700_001)
    const member: TeamMember = {
      id: `tm_${rng.hex(10)}`,
      email,
      full_name: null,
      initials: email.slice(0, 2).toUpperCase(),
      role: input.role,
      status: 'invited',
      joined_at: null,
      last_active_at: null,
      invite_expires_at: new Date(Date.now() + 7 * 86_400_000).toISOString(),
    }
    teamStore.insert(member)
    return member
  }, 500)
}

/** `PUT /api/v1/team/members/{id}` */
export async function changeTeamRole(id: string, role: TeamRole): Promise<TeamMember> {
  return mockResponse(() => {
    const member = allTeamMembers().find((m) => m.id === id)
    if (!member) throw notFound('Team member', id)
    if (member.role === 'owner') {
      throw new ApiError({
        status: 409,
        code: 'OWNER_IMMUTABLE',
        message: 'The owner\'s role cannot be changed — transfer ownership first',
      })
    }
    if (role === 'owner') {
      throw new ApiError({
        status: 422,
        code: 'OWNER_UNIQUE',
        message: 'Transferring ownership is a separate action',
      })
    }
    return teamStore.update(id, { role }) ?? member
  }, 380)
}

/** `DELETE /api/v1/team/members/{id}` */
export async function removeTeamMember(id: string): Promise<{ removed: boolean }> {
  return mockResponse(() => {
    const member = allTeamMembers().find((m) => m.id === id)
    if (!member) throw notFound('Team member', id)
    if (member.role === 'owner') {
      throw new ApiError({
        status: 409,
        code: 'OWNER_IMMUTABLE',
        message: 'The account owner cannot be removed',
      })
    }
    teamStore.remove(id)
    return { removed: true }
  }, 400)
}

/** `POST /api/v1/team/invites/{id}/resend` */
export async function resendInvite(id: string): Promise<TeamMember> {
  return mockResponse(() => {
    const member = allTeamMembers().find((m) => m.id === id)
    if (!member) throw notFound('Invitation', id)
    return (
      teamStore.update(id, {
        invite_expires_at: new Date(Date.now() + 7 * 86_400_000).toISOString(),
      }) ?? member
    )
  }, 400)
}

// ───────────────────────────────────────────────────────────────────────────
// Bildirishnomalar va standartlar
// ───────────────────────────────────────────────────────────────────────────

/** `GET /api/v1/account/notification-settings` */
export async function getNotificationSettings(): Promise<NotificationSetting[]> {
  return mockResponse(() => allNotificationSettings(), 250)
}

/** `PUT /api/v1/account/notification-settings/{event}` */
export async function updateNotificationSetting(
  event: NotificationEvent,
  channel: 'email' | 'in_app' | 'webhook',
  enabled: boolean,
): Promise<NotificationSetting> {
  return mockResponse(() => {
    const row = allNotificationSettings().find((s) => s.event === event)
    if (!row) throw notFound('Notification setting', event)
    return notificationSettingStore.update(event, { [channel]: enabled }) ?? row
  }, 220)
}

/** `GET /api/v1/account/job-defaults` */
export async function getApiDefaults(): Promise<ApiDefaults> {
  return mockResponse(() => apiDefaults(), 220)
}

/** `PUT /api/v1/account/job-defaults` */
export async function updateApiDefaults(patch: Partial<ApiDefaults>): Promise<ApiDefaults> {
  return mockResponse(() => {
    apiDefaultsStore.update('self', patch)
    return apiDefaults()
  }, 420)
}
