/**
 * Cron ifodalarini tahlil qilish, tushuntirish va keyingi vaqtlarni hisoblash.
 *
 * ═══════════════════════════════════════════════════════════════════════
 * NEGA KUTUBXONA EMAS
 * ═══════════════════════════════════════════════════════════════════════
 *
 * Jadval sahifasida uchta narsa kerak: ifoda to'g'rimi, u nimani
 * anglatadi va keyingi safar qachon ishga tushadi. Uchalasini ham
 * foydalanuvchi YOZAYOTGANDA darhol ko'rsatish kerak — aks holda cron
 * yozish ko'r-ko'rona taxmin bo'lib qoladi.
 *
 * Qo'llanadigan sintaksis (standart 5 maydonli cron):
 *   daqiqa soat kun-oy oy hafta-kuni
 * Har maydonda: `*`, `5`, `1-5`, `1-5/2`, `*` va qiyalik, vergulli ro'yxat.
 * Oy va hafta kunlari nom bilan ham yoziladi (`JAN`, `MON`).
 *
 * `L`, `W`, `#`, `?` kabi kengaytmalar QO'LLANMAYDI — ular standart
 * emas va backend (APScheduler/cron) ularni baribir qabul qilmaydi.
 */

export interface CronField {
  /** Shu maydonda ruxsat etilgan qiymatlar. */
  values: number[]
  /** Maydon `*` bo'lsa — tavsifni soddalashtirish uchun. */
  isWildcard: boolean
}

export interface ParsedCron {
  minute: CronField
  hour: CronField
  dayOfMonth: CronField
  month: CronField
  dayOfWeek: CronField
}

const MONTH_NAMES = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
const DAY_NAMES = ['SUN', 'MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']
const DAY_LABELS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
const MONTH_LABELS = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]

interface FieldSpec {
  min: number
  max: number
  names?: readonly string[]
  label: string
}

const SPECS: readonly FieldSpec[] = [
  { min: 0, max: 59, label: 'minute' },
  { min: 0, max: 23, label: 'hour' },
  { min: 1, max: 31, label: 'day of month' },
  { min: 1, max: 12, names: MONTH_NAMES, label: 'month' },
  { min: 0, max: 6, names: DAY_NAMES, label: 'day of week' },
]

export class CronError extends Error {}

/** Bitta atomni (`1-5/2`) qiymatlar ro'yxatiga aylantiradi. */
function parseAtom(atom: string, spec: FieldSpec): number[] {
  const [rangePart, stepPart] = atom.split('/')
  if (stepPart !== undefined && !/^\d+$/.test(stepPart)) {
    throw new CronError(`Invalid step "${stepPart ?? ''}" in the ${spec.label} field`)
  }
  const step = stepPart === undefined ? 1 : Number(stepPart)
  if (step === 0) throw new CronError(`Step cannot be zero in the ${spec.label} field`)

  const toNumber = (token: string): number => {
    const upper = token.toUpperCase()
    const named = spec.names?.indexOf(upper)
    if (named !== undefined && named >= 0) {
      // Oy nomlari 1 dan, hafta kunlari 0 dan boshlanadi
      return spec.names === MONTH_NAMES ? named + 1 : named
    }
    if (!/^\d+$/.test(token)) {
      throw new CronError(`"${token}" is not valid in the ${spec.label} field`)
    }
    const value = Number(token)
    if (value < spec.min || value > spec.max) {
      throw new CronError(
        `${value} is out of range for the ${spec.label} field (${spec.min}–${spec.max})`,
      )
    }
    return value
  }

  let from = spec.min
  let to = spec.max
  if (rangePart !== '*' && rangePart !== undefined && rangePart !== '') {
    if (rangePart.includes('-')) {
      const [a, b] = rangePart.split('-')
      from = toNumber(a ?? '')
      to = toNumber(b ?? '')
      if (to < from) throw new CronError(`Range ${rangePart} runs backwards in the ${spec.label} field`)
    } else {
      from = toNumber(rangePart)
      // `5/15` — 5 dan boshlab maksimumgacha
      to = stepPart === undefined ? from : spec.max
    }
  }

  const values: number[] = []
  for (let v = from; v <= to; v += step) values.push(v)
  return values
}

function parseField(raw: string, spec: FieldSpec): CronField {
  const text = raw.trim()
  if (text === '') throw new CronError(`The ${spec.label} field is empty`)
  const values = new Set<number>()
  for (const atom of text.split(',')) {
    for (const value of parseAtom(atom.trim(), spec)) values.add(value)
  }
  if (values.size === 0) throw new CronError(`The ${spec.label} field matches nothing`)
  return { values: [...values].sort((a, b) => a - b), isWildcard: text === '*' }
}

/** Cron ifodasini tahlil qiladi; xato bo'lsa `CronError` tashlaydi. */
export function parseCron(expression: string): ParsedCron {
  const parts = expression.trim().split(/\s+/)
  if (parts.length !== 5) {
    throw new CronError(
      `Expected 5 fields (minute hour day month weekday), got ${parts.length === 1 && parts[0] === '' ? 0 : parts.length}`,
    )
  }
  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts
  return {
    minute: parseField(minute as string, SPECS[0] as FieldSpec),
    hour: parseField(hour as string, SPECS[1] as FieldSpec),
    dayOfMonth: parseField(dayOfMonth as string, SPECS[2] as FieldSpec),
    month: parseField(month as string, SPECS[3] as FieldSpec),
    dayOfWeek: parseField(dayOfWeek as string, SPECS[4] as FieldSpec),
  }
}

/** Qiymatlar ketma-ket va bir xil qadamli bo'lsa, qadamni qaytaradi. */
function uniformStep(values: number[], min: number, max: number): number | null {
  if (values.length < 2) return null
  const step = (values[1] as number) - (values[0] as number)
  for (let i = 2; i < values.length; i += 1) {
    if ((values[i] as number) - (values[i - 1] as number) !== step) return null
  }
  if (values[0] !== min) return null
  // Oxirgi qiymatdan keyin yana bitta qadam chegaradan oshishi kerak
  if ((values[values.length - 1] as number) + step <= max) return null
  return step
}

/**
 * Qadam, lekin maydon boshidan boshlanishi SHART emas.
 *
 * `0-20/2` kabi oraliqlarni tasvirlash uchun kerak: `uniformStep` bunday
 * holatda `null` qaytaradi, chunki u maydon minimumidan boshlanishni
 * talab qiladi.
 */
function uniformStepInRange(values: number[]): number | null {
  if (values.length < 3) return null
  const step = (values[1] as number) - (values[0] as number)
  for (let i = 2; i < values.length; i += 1) {
    if ((values[i] as number) - (values[i - 1] as number) !== step) return null
  }
  return step
}

function joinList(items: string[]): string {
  if (items.length === 0) return ''
  if (items.length === 1) return items[0] as string
  if (items.length === 2) return `${items[0]} and ${items[1]}`
  return `${items.slice(0, -1).join(', ')} and ${items[items.length - 1]}`
}

const pad = (n: number): string => String(n).padStart(2, '0')

/**
 * Odam o'qiydigan tavsif.
 *
 * Maqsad — cron bilmagan odam ham "haftada bir marta" ekanini bir
 * qarashda tushunishi. Shuning uchun eng ko'p uchraydigan shakllar
 * alohida ishlanadi, qolganlari esa umumiy shaklda tasvirlanadi.
 */
export function describeCron(expression: string): string {
  const cron = parseCron(expression)
  const { minute, hour, dayOfMonth, month, dayOfWeek } = cron

  const minuteStep = uniformStep(minute.values, 0, 59)
  const hourStep = uniformStep(hour.values, 0, 23)

  // ── Vaqt qismi ──────────────────────────────────────────────────────────
  //
  // Maqsad: cron bilmagan odam ham o'qiy olsin. Shuning uchun daqiqa va
  // soat ALOHIDA tasvirlanadi va keyin birlashtiriladi — bu "At 2 minutes
  // past 24 hours" kabi ma'nosiz iboralarni oldini oladi.
  const minuteList = (): string =>
    joinList(minute.values.map((m) => `:${pad(m)}`))

  const hourList = (): string => joinList(hour.values.map((h) => `${pad(h)}:00`))

  /** Soatlar ketma-ket bo'lsa "09:00–17:59", aks holda ro'yxat. */
  const hourSpan = (): string => {
    const first = hour.values[0] as number
    const last = hour.values[hour.values.length - 1] as number
    const contiguous = hour.values.length === last - first + 1
    return contiguous && hour.values.length > 3
      ? `${pad(first)}:00 and ${pad(last)}:59`
      : hourList()
  }

  let time: string
  if (minute.isWildcard && hour.isWildcard) {
    time = 'Every minute'
  } else if (minute.isWildcard) {
    // Har daqiqada, lekin faqat ba'zi soatlarda
    time =
      hourStep !== null
        ? `Every minute, every ${hourStep === 1 ? 'hour' : `${hourStep} hours`}`
        : hour.values.length > 3
          ? `Every minute between ${hourSpan()}`
          : `Every minute during ${hourList()}`
  } else if (hour.isWildcard) {
    time =
      minuteStep !== null
        ? minuteStep === 1
          ? 'Every minute'
          : `Every ${minuteStep} minutes`
        : minute.values.length <= 6
          ? `At ${minuteList()} past every hour`
          : `At ${minute.values.length} minutes past every hour`
  } else {
    // Ikkala maydon ham cheklangan
    const minutePart =
      minute.values.length === 1
        ? `:${pad(minute.values[0] as number)}`
        : minuteStep !== null
          ? `every ${minuteStep} minutes`
          : minute.values.length <= 4
            ? minuteList()
            : `${minute.values.length} minutes`

    if (minute.values.length === 1 && hour.values.length === 1) {
      time = `At ${pad(hour.values[0] as number)}:${pad(minute.values[0] as number)}`
    } else if (minute.values.length === 1 && hour.values.length <= 4) {
      time = `At ${joinList(hour.values.map((h) => `${pad(h)}:${pad(minute.values[0] as number)}`))}`
    } else if (hourStep !== null) {
      time = `At ${minutePart} past every ${hourStep === 1 ? 'hour' : `${hourStep} hours`}`
    } else {
      const span =
        hour.values.length > 4
          ? `${pad(hour.values[0] as number)}:00 and ${pad(hour.values[hour.values.length - 1] as number)}:00`
          : hourList()
      const hourStepInRange = uniformStepInRange(hour.values)
      // `minutePart` "every N minutes" bo'lsa "At every…" g'aliz chiqadi
      const everyMinutes = minutePart.startsWith('every ')
      time =
        hourStepInRange !== null && hourStepInRange > 1
          ? everyMinutes
            ? `Every ${minutePart.slice(6)}, every ${hourStepInRange} hours between ${span}`
            : `At ${minutePart} past every ${hourStepInRange} hours between ${span}`
          : everyMinutes
            ? `Every ${minutePart.slice(6)} between ${span}`
            : `At ${minutePart} past ${span}`
    }
  }

  // Kun qismi
  const parts: string[] = []
  // POSIX qoidasi: ikkala maydon ham cheklangan bo'lsa ular OR bilan
  // birlashadi. "on Wednesday on days 1 and 15" buni yashiradi, shuning
  // uchun "or" yoziladi.
  const bothDayFields = !dayOfWeek.isWildcard && !dayOfMonth.isWildcard
  if (!dayOfWeek.isWildcard) {
    const names = dayOfWeek.values.map((d) => DAY_LABELS[d % 7] as string)
    const weekdaysOnly =
      dayOfWeek.values.length === 5 && dayOfWeek.values.every((d) => d >= 1 && d <= 5)
    const weekendOnly =
      dayOfWeek.values.length === 2 && dayOfWeek.values.every((d) => d === 0 || d === 6)
    parts.push(
      weekdaysOnly ? 'on weekdays' : weekendOnly ? 'on weekends' : `on ${joinList(names)}`,
    )
  }
  if (!dayOfMonth.isWildcard) {
    const text =
      dayOfMonth.values.length === 1
        ? `on day ${dayOfMonth.values[0]} of the month`
        : `on days ${joinList(dayOfMonth.values.map(String))}`
    parts.push(bothDayFields ? `or ${text}` : text)
  }
  if (!month.isWildcard) {
    parts.push(`in ${joinList(month.values.map((m) => MONTH_LABELS[m - 1] as string))}`)
  }

  return parts.length === 0 ? time : `${time} ${parts.join(' ')}`
}

/**
 * Keyingi ishga tushish vaqtlari (UTC).
 *
 * Standart cron qoidasi: kun-oy va hafta-kuni maydonlarining IKKALASI
 * ham `*` bo'lmasa, ular OR bilan birlashtiriladi — ya'ni ikkisidan
 * biri mos kelsa yetarli. Bu g'alati, lekin POSIX shunday va buni
 * buzish backend bilan nomuvofiqlikka olib keladi.
 */
export function nextCronRuns(expression: string, count = 5, from = new Date()): Date[] {
  const cron = parseCron(expression)
  const runs: Date[] = []

  const minutes = new Set(cron.minute.values)
  const hours = new Set(cron.hour.values)
  const days = new Set(cron.dayOfMonth.values)
  const months = new Set(cron.month.values)
  const weekdays = new Set(cron.dayOfWeek.values)
  const domWild = cron.dayOfMonth.isWildcard
  const dowWild = cron.dayOfWeek.isWildcard

  // Keyingi daqiqadan boshlaymiz (soniyalar nolga tushiriladi)
  const cursor = new Date(from.getTime())
  cursor.setUTCSeconds(0, 0)
  cursor.setUTCMinutes(cursor.getUTCMinutes() + 1)

  // 4 yil = har qanday mumkin bo'lgan cron uchun yetarli chegara
  const limit = 4 * 366 * 24 * 60
  for (let i = 0; i < limit && runs.length < count; i += 1) {
    const month = cursor.getUTCMonth() + 1
    if (!months.has(month)) {
      // Keyingi oyning boshiga sakraymiz — daqiqama-daqiqa yurish shart emas
      cursor.setUTCMonth(cursor.getUTCMonth() + 1, 1)
      cursor.setUTCHours(0, 0, 0, 0)
      continue
    }
    const dayMatches =
      domWild && dowWild
        ? true
        : domWild
          ? weekdays.has(cursor.getUTCDay())
          : dowWild
            ? days.has(cursor.getUTCDate())
            : days.has(cursor.getUTCDate()) || weekdays.has(cursor.getUTCDay())

    if (!dayMatches) {
      cursor.setUTCDate(cursor.getUTCDate() + 1)
      cursor.setUTCHours(0, 0, 0, 0)
      continue
    }
    if (!hours.has(cursor.getUTCHours())) {
      cursor.setUTCHours(cursor.getUTCHours() + 1, 0, 0, 0)
      continue
    }
    if (!minutes.has(cursor.getUTCMinutes())) {
      cursor.setUTCMinutes(cursor.getUTCMinutes() + 1, 0, 0)
      continue
    }
    runs.push(new Date(cursor.getTime()))
    cursor.setUTCMinutes(cursor.getUTCMinutes() + 1, 0, 0)
  }

  return runs
}

/** Sutkada necha marta ishga tushishini baholaydi. */
export function runsPerDay(expression: string): number {
  const runs = nextCronRuns(expression, 200)
  if (runs.length === 0) return 0
  const first = runs[0] as Date
  const window = 86_400_000
  const within = runs.filter((d) => d.getTime() - first.getTime() < window).length
  // 200 taga yetgan bo'lsa, sutkalik son undan ko'p bo'lishi mumkin
  return within
}

/** Tez-tez ishlatiladigan tayyor ifodalar. */
export const CRON_PRESETS: readonly { label: string; cron: string }[] = [
  { label: 'Every 5 minutes', cron: '*/5 * * * *' },
  { label: 'Every 15 minutes', cron: '*/15 * * * *' },
  { label: 'Hourly', cron: '0 * * * *' },
  { label: 'Every 6 hours', cron: '0 */6 * * *' },
  { label: 'Daily at 02:00', cron: '0 2 * * *' },
  { label: 'Weekdays at 09:00', cron: '0 9 * * 1-5' },
  { label: 'Weekly (Mon 08:00)', cron: '0 8 * * 1' },
  { label: 'Monthly (1st, 03:00)', cron: '0 3 1 * *' },
]
