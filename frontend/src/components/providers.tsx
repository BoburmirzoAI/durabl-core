'use client'

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useState } from 'react'

import { ToastProvider } from '@/components/common/ToastProvider'
import { TooltipProvider } from '@/components/ui/tooltip'
import { ApiError } from '@/lib/api/client'

/**
 * Global provayderlar.
 *
 * `QueryClient` `useState` ichida yaratiladi — har render'da yangi nusxa
 * yasalmasligi va SSR'da foydalanuvchilar orasida kesh aralashmasligi uchun.
 */
export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            // Mock qatlami tez ishlaydi, lekin keraksiz qayta so'rovni
            // oldini olish uchun 15s "yangi" deb hisoblanadi
            staleTime: 15_000,
            refetchOnWindowFocus: false,
            retry: (failureCount, error) => {
              // 4xx da qayta urinish befoyda (topilmadi, ruxsat yo'q)
              if (error instanceof ApiError && error.isClientError) return false
              return failureCount < 2
            },
          },
          mutations: { retry: false },
        },
      }),
  )

  return (
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={300}>
        <ToastProvider>{children}</ToastProvider>
      </TooltipProvider>
    </QueryClientProvider>
  )
}
