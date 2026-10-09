'use client'

import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

import { startSimulation } from '@/lib/mock/simulation'
import { subscribe } from '@/lib/mock/store'

import { QK } from './keys'

/**
 * Mock simulyatsiyasini ishga tushiradi va o'zgarishda so'rovlarni yangilaydi.
 *
 * Qobiqda BIR MARTA chaqiriladi. Har bir sahifa o'zi chaqirsa, bir nechta
 * taymer paydo bo'lib ko'rsatkichlar bir-biriga mos kelmasdi.
 *
 * `invalidateQueries` o'rniga maqsadli kalitlar ishlatiladi: butun keshni
 * bekor qilish foydalanuvchi yozayotgan filtrlarni ham qayta so'ratadi.
 */
export function useSimulation(enabled = true): void {
  const qc = useQueryClient()

  useEffect(() => {
    if (!enabled) return

    const stopSimulation = startSimulation()
    const unsubscribe = subscribe(() => {
      void qc.invalidateQueries({ queryKey: QK.jobs.all })
      void qc.invalidateQueries({ queryKey: QK.workers.all })
      void qc.invalidateQueries({ queryKey: QK.analytics.all })
    })

    return () => {
      unsubscribe()
      stopSimulation()
    }
  }, [qc, enabled])
}
