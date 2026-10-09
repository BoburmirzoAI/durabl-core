/**
 * Minimal QR kod generatori (bayt rejimi, EC darajasi M, 1–10 versiyalar).
 *
 * ═══════════════════════════════════════════════════════════════════════
 * NEGA O'Z IMPLEMENTATSIYAMIZ
 * ═══════════════════════════════════════════════════════════════════════
 *
 * 2FA sozlashda QR kod HAQIQATAN skanerlanishi kerak — chizilgan "bezak"
 * kvadratchalar foydalanuvchini aldaydi. Tayyor kutubxona qo'shish esa
 * bitta ekran uchun ~50 KB bundle qo'shadi.
 *
 * Shuning uchun standartning faqat KERAKLI qismi yozilgan:
 * bayt rejimi, EC darajasi M, 1–10 versiyalar (≈ 216 bayt). `otpauth://`
 * URI odatda 70–120 bayt, demak bu oraliq yetarli.
 *
 * Natija — modul matritsasi (`boolean[][]`), uni chaqiruvchi SVG qilib
 * chizadi. Rasm formatini generator belgilamaydi.
 */

// ───────────────────────────────────────────────────────────────────────────
// GF(256) — Reed–Solomon uchun
// ───────────────────────────────────────────────────────────────────────────

const EXP = new Uint8Array(512)
const LOG = new Uint8Array(256)

{
  let x = 1
  for (let i = 0; i < 255; i += 1) {
    EXP[i] = x
    LOG[x] = i
    x <<= 1
    // Primitiv ko'phad: x^8 + x^4 + x^3 + x^2 + 1 (0x11D)
    if (x & 0x100) x ^= 0x11d
  }
  for (let i = 255; i < 512; i += 1) EXP[i] = EXP[i - 255] as number
}

function gfMul(a: number, b: number): number {
  if (a === 0 || b === 0) return 0
  return EXP[((LOG[a] as number) + (LOG[b] as number)) % 255] as number
}

/** `degree` darajali generator ko'phadi. */
function rsGenerator(degree: number): Uint8Array {
  let poly = new Uint8Array([1])
  for (let i = 0; i < degree; i += 1) {
    const next = new Uint8Array(poly.length + 1)
    for (let j = 0; j < poly.length; j += 1) {
      // Ko'phad KATTA darajadan boshlab saqlanadi: `poly[j]` ni x ga
      // ko'paytirish uni O'SHA indeksda qoldiradi, α^i ga ko'paytirish
      // esa keyingisiga qo'shiladi. (Oldin bu teskari edi.)
      next[j] = (next[j] as number) ^ (poly[j] as number)
      next[j + 1] = (next[j + 1] as number) ^ gfMul(poly[j] as number, EXP[i] as number)
    }
    poly = next
  }
  return poly
}

/** Ma'lumot bloki uchun EC kodso'zlari. */
function rsEncode(data: Uint8Array, ecCount: number): Uint8Array {
  const gen = rsGenerator(ecCount)
  const result = new Uint8Array(ecCount)
  for (const byte of data) {
    const factor = byte ^ (result[0] as number)
    result.copyWithin(0, 1)
    result[ecCount - 1] = 0
    if (factor !== 0) {
      for (let i = 0; i < ecCount; i += 1) {
        result[i] = (result[i] as number) ^ gfMul(gen[i + 1] as number, factor)
      }
    }
  }
  return result
}

// ───────────────────────────────────────────────────────────────────────────
// Versiya jadvallari (faqat EC darajasi M)
// ───────────────────────────────────────────────────────────────────────────

interface VersionSpec {
  /** Blokdagi EC kodso'zlari soni. */
  ecPerBlock: number
  /** `[bloklar soni, blokdagi MA'LUMOT kodso'zlari]` guruhlari. */
  groups: readonly (readonly [number, number])[]
  /** Hizalash namunalari markazlari. */
  alignment: readonly number[]
}

const VERSIONS: Record<number, VersionSpec> = {
  1: { ecPerBlock: 10, groups: [[1, 16]], alignment: [] },
  2: { ecPerBlock: 16, groups: [[1, 28]], alignment: [6, 18] },
  3: { ecPerBlock: 26, groups: [[1, 44]], alignment: [6, 22] },
  4: { ecPerBlock: 18, groups: [[2, 32]], alignment: [6, 26] },
  5: { ecPerBlock: 24, groups: [[2, 43]], alignment: [6, 30] },
  6: { ecPerBlock: 16, groups: [[4, 27]], alignment: [6, 34] },
  7: { ecPerBlock: 18, groups: [[4, 31]], alignment: [6, 22, 38] },
  8: { ecPerBlock: 22, groups: [[2, 38], [2, 39]], alignment: [6, 24, 42] },
  9: { ecPerBlock: 22, groups: [[3, 36], [2, 37]], alignment: [6, 26, 46] },
  10: { ecPerBlock: 26, groups: [[4, 43], [1, 44]], alignment: [6, 28, 50] },
}

function dataCapacity(version: number): number {
  const spec = VERSIONS[version] as VersionSpec
  return spec.groups.reduce((sum, [count, size]) => sum + count * size, 0)
}

/** Ma'lumot sig'adigan eng kichik versiya. */
function pickVersion(byteLength: number): number {
  for (let version = 1; version <= 10; version += 1) {
    // 4 bit rejim + uzunlik maydoni (v<10 uchun 8 bit, v>=10 uchun 16 bit)
    const countBits = version < 10 ? 8 : 16
    const needed = Math.ceil((4 + countBits + byteLength * 8) / 8)
    if (needed <= dataCapacity(version)) return version
  }
  throw new Error('QR: ma\'lumot 10-versiyaga sig\'maydi')
}

// ───────────────────────────────────────────────────────────────────────────
// Bit oqimi
// ───────────────────────────────────────────────────────────────────────────

class BitBuffer {
  private bits: number[] = []

  push(value: number, length: number): void {
    for (let i = length - 1; i >= 0; i -= 1) this.bits.push((value >>> i) & 1)
  }

  get length(): number {
    return this.bits.length
  }

  toBytes(): Uint8Array {
    const bytes = new Uint8Array(Math.ceil(this.bits.length / 8))
    this.bits.forEach((bit, i) => {
      if (bit) bytes[i >>> 3] = (bytes[i >>> 3] as number) | (0x80 >>> (i & 7))
    })
    return bytes
  }
}

/** Ma'lumotni kodso'zlarga aylantiradi (to'ldirish bilan). */
function encodeData(bytes: Uint8Array, version: number): Uint8Array {
  const capacity = dataCapacity(version)
  const buffer = new BitBuffer()
  buffer.push(0b0100, 4) // bayt rejimi
  buffer.push(bytes.length, version < 10 ? 8 : 16)
  for (const byte of bytes) buffer.push(byte, 8)

  // Tugatuvchi (eng ko'pi 4 bit) + bayt chegarasiga tekislash
  const remaining = capacity * 8 - buffer.length
  buffer.push(0, Math.min(4, remaining))
  if (buffer.length % 8 !== 0) buffer.push(0, 8 - (buffer.length % 8))

  const result = new Uint8Array(capacity)
  result.set(buffer.toBytes().slice(0, capacity))
  // Standart to'ldirish baytlari 0xEC / 0x11 navbatma-navbat
  for (let i = buffer.toBytes().length; i < capacity; i += 1) {
    result[i] = (i - buffer.toBytes().length) % 2 === 0 ? 0xec : 0x11
  }
  return result
}

/** Bloklarga bo'lib, EC qo'shib, standart tartibda aralashtiradi. */
function interleave(data: Uint8Array, version: number): Uint8Array {
  const spec = VERSIONS[version] as VersionSpec
  const dataBlocks: Uint8Array[] = []
  const ecBlocks: Uint8Array[] = []

  let offset = 0
  for (const [count, size] of spec.groups) {
    for (let i = 0; i < count; i += 1) {
      const block = data.slice(offset, offset + size)
      offset += size
      dataBlocks.push(block)
      ecBlocks.push(rsEncode(block, spec.ecPerBlock))
    }
  }

  const out: number[] = []
  const maxData = Math.max(...dataBlocks.map((b) => b.length))
  for (let i = 0; i < maxData; i += 1) {
    for (const block of dataBlocks) if (i < block.length) out.push(block[i] as number)
  }
  for (let i = 0; i < spec.ecPerBlock; i += 1) {
    for (const block of ecBlocks) out.push(block[i] as number)
  }
  return new Uint8Array(out)
}

// ───────────────────────────────────────────────────────────────────────────
// Matritsa
// ───────────────────────────────────────────────────────────────────────────

type Grid = (boolean | null)[][]

function placeFinder(grid: Grid, row: number, col: number): void {
  for (let r = -1; r <= 7; r += 1) {
    for (let c = -1; c <= 7; c += 1) {
      const y = row + r
      const x = col + c
      if (y < 0 || y >= grid.length || x < 0 || x >= grid.length) continue
      const inRing = (r >= 0 && r <= 6 && (c === 0 || c === 6)) || (c >= 0 && c <= 6 && (r === 0 || r === 6))
      const inCore = r >= 2 && r <= 4 && c >= 2 && c <= 4
      ;(grid[y] as (boolean | null)[])[x] = inRing || inCore
    }
  }
}

function placeAlignment(grid: Grid, centers: readonly number[]): void {
  const size = grid.length
  for (const row of centers) {
    for (const col of centers) {
      // Qidiruv namunalari ustiga tushadigan markazlar o'tkazib yuboriladi
      const onFinder =
        (row <= 8 && col <= 8) || (row <= 8 && col >= size - 9) || (row >= size - 9 && col <= 8)
      if (onFinder) continue
      for (let r = -2; r <= 2; r += 1) {
        for (let c = -2; c <= 2; c += 1) {
          const ring = Math.max(Math.abs(r), Math.abs(c))
          ;(grid[row + r] as (boolean | null)[])[col + c] = ring !== 1
        }
      }
    }
  }
}

/** 15 bitli format ma'lumoti (EC M = 00, maska 0..7). */
function formatBits(mask: number): number {
  const data = (0b00 << 3) | mask
  let value = data << 10
  for (let i = 4; i >= 0; i -= 1) {
    if (value & (1 << (i + 10))) value ^= 0b10100110111 << i
  }
  return ((data << 10) | value) ^ 0b101010000010010
}

/** 18 bitli versiya ma'lumoti (faqat 7+ versiyalar uchun). */
function versionBits(version: number): number {
  let value = version << 12
  for (let i = 5; i >= 0; i -= 1) {
    if (value & (1 << (i + 12))) value ^= 0b1111100100101 << i
  }
  return (version << 12) | value
}

const MASKS: readonly ((row: number, col: number) => boolean)[] = [
  (r, c) => (r + c) % 2 === 0,
  (r) => r % 2 === 0,
  (_, c) => c % 3 === 0,
  (r, c) => (r + c) % 3 === 0,
  (r, c) => (Math.floor(r / 2) + Math.floor(c / 3)) % 2 === 0,
  (r, c) => ((r * c) % 2) + ((r * c) % 3) === 0,
  (r, c) => (((r * c) % 2) + ((r * c) % 3)) % 2 === 0,
  (r, c) => (((r + c) % 2) + ((r * c) % 3)) % 2 === 0,
]

/** Maska sifatini baholash (standartdagi 4 qoida). */
function penalty(grid: boolean[][]): number {
  const size = grid.length
  let score = 0

  // 1-qoida: qatorda/ustunda 5+ bir xil modul
  const runScore = (line: boolean[]): number => {
    let total = 0
    let run = 1
    for (let i = 1; i < line.length; i += 1) {
      if (line[i] === line[i - 1]) run += 1
      else {
        if (run >= 5) total += 3 + (run - 5)
        run = 1
      }
    }
    if (run >= 5) total += 3 + (run - 5)
    return total
  }
  for (let i = 0; i < size; i += 1) {
    score += runScore(grid[i] as boolean[])
    score += runScore(grid.map((row) => (row as boolean[])[i] as boolean))
  }

  // 2-qoida: 2×2 bir xil bloklar
  for (let r = 0; r < size - 1; r += 1) {
    for (let c = 0; c < size - 1; c += 1) {
      const v = (grid[r] as boolean[])[c]
      if (
        v === (grid[r] as boolean[])[c + 1] &&
        v === (grid[r + 1] as boolean[])[c] &&
        v === (grid[r + 1] as boolean[])[c + 1]
      ) {
        score += 3
      }
    }
  }

  // 3-qoida: qidiruv namunasiga o'xshash ketma-ketlik
  const PATTERN = [true, false, true, true, true, false, true, false, false, false, false]
  const REVERSED = [...PATTERN].reverse()
  const matches = (line: boolean[], at: number, pattern: boolean[]): boolean =>
    pattern.every((bit, i) => line[at + i] === bit)
  for (let i = 0; i < size; i += 1) {
    const row = grid[i] as boolean[]
    const col = grid.map((r) => (r as boolean[])[i] as boolean)
    for (let j = 0; j + 11 <= size; j += 1) {
      if (matches(row, j, PATTERN) || matches(row, j, REVERSED)) score += 40
      if (matches(col, j, PATTERN) || matches(col, j, REVERSED)) score += 40
    }
  }

  // 4-qoida: qora modullar ulushi 50% dan qanchalik uzoq
  const dark = grid.reduce((sum, row) => sum + (row as boolean[]).filter(Boolean).length, 0)
  const ratio = (dark * 100) / (size * size)
  score += Math.floor(Math.abs(ratio - 50) / 5) * 10

  return score
}

/**
 * Matnni QR modul matritsasiga aylantiradi.
 *
 * `true` — qora modul. Chekka (quiet zone) QO'SHILMAYDI; uni chizuvchi
 * tomon qo'shadi, chunki o'lcham SVG'da osonroq boshqariladi.
 */
export function encodeQr(text: string): boolean[][] {
  const bytes = new TextEncoder().encode(text)
  const version = pickVersion(bytes.length)
  const spec = VERSIONS[version] as VersionSpec
  const size = version * 4 + 17
  const codewords = interleave(encodeData(bytes, version), version)

  const grid: Grid = Array.from({ length: size }, () => Array.from({ length: size }, () => null))

  placeFinder(grid, 0, 0)
  placeFinder(grid, 0, size - 7)
  placeFinder(grid, size - 7, 0)
  placeAlignment(grid, spec.alignment)

  // Vaqt chiziqlari
  for (let i = 8; i < size - 8; i += 1) {
    ;(grid[6] as (boolean | null)[])[i] = i % 2 === 0
    ;(grid[i] as (boolean | null)[])[6] = i % 2 === 0
  }
  // Doimiy qora modul
  ;(grid[size - 8] as (boolean | null)[])[8] = true

  // Format maydonlarini band qilamiz (qiymati keyin yoziladi)
  const reserveFormat = (): void => {
    for (let i = 0; i <= 8; i += 1) {
      if (i !== 6) {
        if ((grid[8] as (boolean | null)[])[i] === null) (grid[8] as (boolean | null)[])[i] = false
        if ((grid[i] as (boolean | null)[])[8] === null) (grid[i] as (boolean | null)[])[8] = false
      }
    }
    for (let i = 0; i < 8; i += 1) {
      if ((grid[8] as (boolean | null)[])[size - 1 - i] === null) {
        ;(grid[8] as (boolean | null)[])[size - 1 - i] = false
      }
      if ((grid[size - 1 - i] as (boolean | null)[])[8] === null) {
        ;(grid[size - 1 - i] as (boolean | null)[])[8] = false
      }
    }
  }

  if (version >= 7) {
    const bits = versionBits(version)
    for (let i = 0; i < 18; i += 1) {
      const bit = ((bits >>> i) & 1) === 1
      ;(grid[Math.floor(i / 3)] as (boolean | null)[])[size - 11 + (i % 3)] = bit
      ;(grid[size - 11 + (i % 3)] as (boolean | null)[])[Math.floor(i / 3)] = bit
    }
  }
  reserveFormat()

  // Ma'lumotdan oldingi holat — funktsional modullar aynan shular
  const occupied: boolean[][] = grid.map((row) =>
    (row as (boolean | null)[]).map((cell) => cell !== null),
  )

  // Ma'lumotni zigzag tartibida joylashtiramiz (o'ngdan chapga, 2 ustunli)
  let bitIndex = 0
  let upward = true
  for (let right = size - 1; right > 0; right -= 2) {
    // 6-ustun vaqt chizig'i — o'tkazib yuboriladi
    const rightCol = right <= 6 ? right - 1 : right
    for (let step = 0; step < size; step += 1) {
      const row = upward ? size - 1 - step : step
      for (const col of [rightCol, rightCol - 1]) {
        if ((grid[row] as (boolean | null)[])[col] !== null) continue
        const byte = codewords[bitIndex >>> 3] ?? 0
        const bit = ((byte >>> (7 - (bitIndex & 7))) & 1) === 1
        ;(grid[row] as (boolean | null)[])[col] = bit
        bitIndex += 1
      }
    }
    upward = !upward
  }

  // Funktsional modullar xaritasi — maska faqat MA'LUMOTGA qo'llanadi.
  //
  // Xaritani qo'lda yozish o'rniga, ma'lumot joylashtirilgunga QADAR
  // bo'sh bo'lmagan kataklar olinadi: ta'rifi aynan shu va qo'lda
  // yozilgan ro'yxatdan farqli o'laroq xato qilish mumkin emas.
  const functional: boolean[][] = occupied

  // Eng yaxshi maskani tanlaymiz
  let best: boolean[][] | null = null
  let bestMask = 0
  let bestScore = Number.POSITIVE_INFINITY

  for (let mask = 0; mask < 8; mask += 1) {
    const rule = MASKS[mask] as (row: number, col: number) => boolean
    const candidate: boolean[][] = grid.map((row, r) =>
      (row as (boolean | null)[]).map((cell, c) =>
        (functional[r] as boolean[])[c] ? cell === true : (cell === true) !== rule(r, c),
      ),
    )
    writeFormat(candidate, mask)
    const score = penalty(candidate)
    if (score < bestScore) {
      bestScore = score
      best = candidate
      bestMask = mask
    }
  }

  const result = best as boolean[][]
  writeFormat(result, bestMask)
  return result
}

/** Format ma'lumotini ikkala nusxasiga yozadi. */
function writeFormat(grid: boolean[][], mask: number): void {
  const size = grid.length
  const bits = formatBits(mask)
  for (let i = 0; i < 15; i += 1) {
    const bit = ((bits >>> i) & 1) === 1

    // Birinchi nusxa — chap-yuqori qidiruv namunasi atrofida.
    // Tartib ISO 18004 bo'yicha: 0..5 ustun 8 da pastga, so'ng burchak,
    // keyin qator 8 da chapga. (Oldin bu almashtirilgan edi.)
    if (i < 6) (grid[i] as boolean[])[8] = bit
    else if (i === 6) (grid[7] as boolean[])[8] = bit
    else if (i === 7) (grid[8] as boolean[])[8] = bit
    else if (i === 8) (grid[8] as boolean[])[7] = bit
    else (grid[8] as boolean[])[14 - i] = bit

    // Ikkinchi nusxa — o'ng-yuqori qator va chap-pastki ustun
    if (i < 8) (grid[8] as boolean[])[size - 1 - i] = bit
    else (grid[size - 15 + i] as boolean[])[8] = bit
  }
  ;(grid[size - 8] as boolean[])[8] = true
}

/** Matritsani SVG qatoriga aylantiradi (chekka bilan). */
export function qrToSvg(matrix: boolean[][], { quiet = 4 } = {}): string {
  const size = matrix.length
  const total = size + quiet * 2
  const paths: string[] = []
  matrix.forEach((row, r) => {
    row.forEach((on, c) => {
      if (on) paths.push(`M${c + quiet} ${r + quiet}h1v1h-1z`)
    })
  })
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${total} ${total}" shape-rendering="crispEdges">`,
    `<rect width="${total}" height="${total}" fill="#fff"/>`,
    `<path fill="#000" d="${paths.join('')}"/>`,
    '</svg>',
  ].join('')
}


