'use client'

import { useEffect, useState } from 'react'

/**
 * Qiymatni kechiktirib qaytaradi.
 *
 * Qidiruv maydonida har harf uchun so'rov yubormaslik uchun ishlatiladi
 * (dizayndagi filtr paneli).
 */
export function useDebounce<T>(value: T, delayMs = 300): T {
  const [debounced, setDebounced] = useState(value)

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(timer)
  }, [value, delayMs])

  return debounced
}
