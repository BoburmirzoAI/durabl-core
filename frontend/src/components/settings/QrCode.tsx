'use client'

import { useMemo } from 'react'

import { encodeQr } from '@/lib/utils/qr'

/**
 * QR kod — inline SVG.
 *
 * Rasm serverdan kelmaydi va `<img src="data:...">` ham ishlatilmaydi:
 * TOTP kaliti QR ichida, demak uni tashqi xizmatga (masalan Google
 * Charts API) yuborish — kalitni oshkor qilish. Shuning uchun kod
 * brauzerda, mijoz tomonda chiziladi.
 */
export function QrCode({
  value,
  size = 200,
  className,
}: {
  value: string
  size?: number
  className?: string
}) {
  const matrix = useMemo(() => {
    try {
      return encodeQr(value)
    } catch {
      return null
    }
  }, [value])

  if (!matrix) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-line bg-surface-2 text-xs text-fg-faint"
        style={{ width: size, height: size }}
      >
        Could not render QR
      </div>
    )
  }

  const quiet = 4
  const total = matrix.length + quiet * 2
  const path = matrix
    .flatMap((row, r) =>
      row.map((on, c) => (on ? `M${c + quiet} ${r + quiet}h1v1h-1z` : '')).filter(Boolean),
    )
    .join('')

  return (
    <svg
      role="img"
      aria-label="Two-factor setup QR code"
      viewBox={`0 0 ${total} ${total}`}
      width={size}
      height={size}
      shapeRendering="crispEdges"
      className={className}
    >
      <rect width={total} height={total} fill="#ffffff" />
      <path d={path} fill="#000000" />
    </svg>
  )
}
