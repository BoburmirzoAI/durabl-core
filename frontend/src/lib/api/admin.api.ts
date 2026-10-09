/** Admin endpointlari. */

import type {
  ActivityEvent,
  AdminCreateUserInput,
  AdminCreditEntry,
  AdminStats,
  AdminUser,
  AdminUserDetail,
  AdminUserFilters,
  Paginated,
  PlanType,
} from '@/types'
import { activityFeed, adminStats, allAdminUsers, userStore } from '@/lib/mock/users'
import { adminNoteStore, adminUserDetail, creditStore } from '@/lib/mock/admin-users'
import { Rng } from '@/lib/mock/seed'

import { ApiError, mockResponse, notFound } from './client'
import { DEFAULT_PAGE_SIZE, filterByAny, paginate, searchIn, sortBy } from './paginate'

/** `GET /api/v1/admin/stats` */
export async function getAdminStats(): Promise<AdminStats> {
  return mockResponse(() => adminStats())
}

/** `GET /api/v1/admin/users` */
export async function getAdminUsers(filters: AdminUserFilters = {}): Promise<Paginated<AdminUser>> {
  return mockResponse(() => {
    let rows = allAdminUsers()
    rows = searchIn(rows, filters.search, ['email', 'full_name'])
    rows = filterByAny(rows, filters.plan, (u) => u.plan)
    if (filters.is_active !== undefined) rows = rows.filter((u) => u.is_active === filters.is_active)
    if (filters.is_admin !== undefined) rows = rows.filter((u) => u.is_admin === filters.is_admin)
    rows = sortBy(rows, filters.sort_by ?? 'created_at', filters.sort_order ?? 'desc')
    return paginate(rows, filters.page ?? 1, filters.page_size ?? DEFAULT_PAGE_SIZE)
  })
}

export interface AdminUserPatch {
  is_active?: boolean
  is_admin?: boolean
  plan?: PlanType
  full_name?: string
}

/** `PUT /api/v1/admin/users/{id}` */
export async function updateAdminUser(id: string, patch: AdminUserPatch): Promise<AdminUser> {
  return mockResponse(() => {
    const user = allAdminUsers().find((u) => u.id === id)
    if (!user) throw notFound('User', id)
    return userStore.update(id, patch) ?? user
  }, 400)
}

/**
 * `POST /api/v1/admin/users/{id}/suspend`
 *
 * To'xtatilgan foydalanuvchi job yubora olmaydi. Jadvalda alohida holat
 * sifatida ko'rinadi.
 */
export async function suspendUser(id: string): Promise<AdminUser> {
  return mockResponse(() => {
    const user = allAdminUsers().find((u) => u.id === id)
    if (!user) throw notFound('User', id)
    if (user.is_admin) {
      throw new ApiError({
        status: 409,
        code: 'CANNOT_SUSPEND_ADMIN',
        message: 'An admin account cannot be suspended',
      })
    }
    return userStore.update(id, { is_active: false }) ?? user
  }, 400)
}

/** `POST /api/v1/admin/users/{id}/reactivate` */
export async function reactivateUser(id: string): Promise<AdminUser> {
  return mockResponse(() => {
    const user = allAdminUsers().find((u) => u.id === id)
    if (!user) throw notFound('User', id)
    return userStore.update(id, { is_active: true }) ?? user
  }, 400)
}

/** `PUT /api/v1/admin/users/{id}` — tarif rejasini almashtirish. */
export async function changeUserPlan(id: string, plan: PlanType): Promise<AdminUser> {
  return mockResponse(() => {
    const user = allAdminUsers().find((u) => u.id === id)
    if (!user) throw notFound('User', id)
    return userStore.update(id, { plan }) ?? user
  }, 400)
}

/**
 * `POST /api/v1/admin/users/{id}/reset-keys`
 *
 * Foydalanuvchining barcha API kalitlarini bekor qiladi — buzilgan kalit
 * aniqlanganda ishlatiladi.
 */
export async function resetUserKeys(id: string): Promise<{ revoked: number }> {
  return mockResponse(() => {
    const user = allAdminUsers().find((u) => u.id === id)
    if (!user) throw notFound('User', id)
    const revoked = user.api_key_count
    userStore.update(id, { api_key_count: 0 })
    return { revoked }
  }, 500)
}

/** Ommaviy to'xtatish (admin hisoblar o'tkazib yuboriladi). */
export async function suspendUsers(ids: string[]): Promise<{ suspended: number }> {
  return mockResponse(() => {
    const targets = ids.filter((id) => {
      const user = allAdminUsers().find((u) => u.id === id)
      return user !== undefined && !user.is_admin && user.is_active
    })
    return { suspended: userStore.updateMany(targets, { is_active: false }) }
  }, 600)
}

/** Ommaviy tarif almashtirish. */
export async function changeUsersPlan(
  ids: string[],
  plan: PlanType,
): Promise<{ updated: number }> {
  return mockResponse(() => ({ updated: userStore.updateMany(ids, { plan }) }), 600)
}

/** `GET /api/v1/admin/users/{id}` — slide-over paneli uchun bitta foydalanuvchi. */
export async function getAdminUser(id: string): Promise<AdminUser> {
  return mockResponse(() => {
    const user = allAdminUsers().find((u) => u.id === id)
    if (!user) throw notFound('User', id)
    return user
  })
}

/** Jonli faollik oqimi. */
export async function getActivityFeed(): Promise<ActivityEvent[]> {
  return mockResponse(() => activityFeed())
}

// ───────────────────────────────────────────────────────────────────────────
// Foydalanuvchi detal sahifasi
// ───────────────────────────────────────────────────────────────────────────

/** `GET /api/v1/admin/users/{id}/detail` */
export async function getAdminUserDetail(id: string): Promise<AdminUserDetail> {
  return mockResponse(() => {
    const detail = adminUserDetail(id)
    if (!detail) throw notFound('User', id)
    return detail
  }, 480)
}

/**
 * `POST /api/v1/admin/users/{id}/credits`
 *
 * Musbat summa — kredit, manfiy — hisobdan yechish. Sabab MAJBURIY:
 * pul harakati izsiz qolmasligi kerak.
 */
export async function adjustUserCredit(
  id: string,
  amountUsd: number,
  reason: string,
  kind: AdminCreditEntry['kind'],
): Promise<AdminCreditEntry> {
  return mockResponse(() => {
    if (!allAdminUsers().some((u) => u.id === id)) throw notFound('User', id)
    if (reason.trim().length === 0) {
      throw new ApiError({
        status: 422,
        code: 'REASON_REQUIRED',
        message: 'A reason is required',
      })
    }
    if (amountUsd === 0) {
      throw new ApiError({ status: 422, code: 'ZERO_AMOUNT', message: 'The amount must not be zero' })
    }
    const rng = new Rng(Date.now() % 600_013)
    const entry: AdminCreditEntry & { user_id: string } = {
      id: `cr_${rng.hex(10)}`,
      user_id: id,
      at: new Date().toISOString(),
      amount_usd: Math.round(amountUsd * 100) / 100,
      reason: reason.trim(),
      actor: 'admin@durabl.dev',
      kind,
    }
    creditStore.insert(entry)
    return entry
  }, 520)
}

/** `PUT /api/v1/admin/users/{id}/note` — ichki eslatma. */
export async function setAdminUserNote(id: string, note: string): Promise<{ note: string }> {
  return mockResponse(() => {
    if (!allAdminUsers().some((u) => u.id === id)) throw notFound('User', id)
    const trimmed = note.trim()
    if (adminNoteStore.find(id)) adminNoteStore.update(id, { note: trimmed })
    else adminNoteStore.insert({ id, note: trimmed })
    return { note: trimmed }
  }, 300)
}

/**
 * `POST /api/v1/admin/users`
 *
 * Admin qo'lda foydalanuvchi yaratadi — korporativ mijoz uchun hisob
 * ochish yoki sinov hisobini tayyorlash holatlarida kerak.
 */
export async function createAdminUser(input: AdminCreateUserInput): Promise<AdminUser> {
  return mockResponse(() => {
    const email = input.email.trim().toLowerCase()
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      throw new ApiError({ status: 422, code: 'INVALID_EMAIL', message: 'That email address is not valid' })
    }
    if (allAdminUsers().some((u) => u.email.toLowerCase() === email)) {
      throw new ApiError({
        status: 409,
        code: 'EMAIL_TAKEN',
        message: 'An account with that email already exists',
      })
    }
    const rng = new Rng(Date.now() % 500_009)
    const name = input.full_name?.trim() || null
    const user: AdminUser = {
      id: `usr_${rng.hex(8)}`,
      email,
      full_name: name,
      initials: (name ?? email)
        .split(/[\s@.]/)
        .filter(Boolean)
        .slice(0, 2)
        .map((part) => (part[0] ?? '').toUpperCase())
        .join(''),
      is_active: true,
      is_admin: input.is_admin,
      plan: input.plan,
      last_login_at: null,
      created_at: new Date().toISOString(),
      job_count: 0,
      jobs_this_period: 0,
      dlq_depth: 0,
      api_key_count: 0,
    }
    userStore.insert(user)
    if (input.starting_credit_usd && input.starting_credit_usd > 0) {
      creditStore.insert({
        id: `cr_${rng.hex(10)}`,
        user_id: user.id,
        at: new Date().toISOString(),
        amount_usd: input.starting_credit_usd,
        reason: 'Starting credit on manual account creation',
        actor: 'admin@durabl.dev',
        kind: 'credit',
      })
    }
    return user
  }, 650)
}

/** Ommaviy eksport uchun ustunlar tayyor ro'yxati. */
export async function exportAdminUsers(filters: AdminUserFilters = {}): Promise<AdminUser[]> {
  return mockResponse(() => {
    let rows = allAdminUsers()
    rows = searchIn(rows, filters.search, ['email', 'full_name'])
    rows = filterByAny(rows, filters.plan, (u) => u.plan)
    if (filters.is_active !== undefined) rows = rows.filter((u) => u.is_active === filters.is_active)
    return rows
  }, 400)
}
