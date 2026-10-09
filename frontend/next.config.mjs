// Durabl frontend — Next.js konfiguratsiyasi.

/**
 * Backend manzili (brauzer ko'radigan manzil).
 *
 * HOZIR hech kim o'qimaydi — butun ilova mock ma'lumot bilan ishlaydi.
 * Backend ulangach `src/lib/api/client.ts` shu qiymatdan foydalanadi.
 */
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

/**
 * Dev rejimida CORS'dan qutulish uchun ixtiyoriy proxy.
 *
 * `NEXT_PUBLIC_API_PROXY=true` bo'lsa, `/api/v1/*` so'rovlari Next server
 * orqali backend'ga uzatiladi (brauzer uchun "same-origin" bo'lib ko'rinadi).
 *
 * Standart holatda O'CHIRILGAN — mock rejimda proxy'ning ma'nosi yo'q.
 * Backend ulanadigan qadamda shu bayroqni yoqish kifoya.
 */
const API_PROXY_ENABLED = process.env.NEXT_PUBLIC_API_PROXY === 'true'

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  // Docker uchun minimal runtime (frontend/Dockerfile `runner` qatlami shunga tayanadi)
  output: 'standalone',

  // `X-Powered-By: Next.js` sarlavhasi berilmaydi (keraksiz ma'lumot oshkor qilmaslik)
  poweredByHeader: false,

  // Lint build'ni to'xtatishi KERAK — xato kod image'ga tushmasin
  eslint: { ignoreDuringBuilds: false },

  experimental: {
    // Katta kutubxonalardan faqat ishlatilgan eksportlar bundle'ga tushadi.
    // `date-fns` ro'yxatda YO'Q — bu loyihada ishlatilmaydi.
    optimizePackageImports: ['lucide-react', 'recharts'],
  },

  async rewrites() {
    if (!API_PROXY_ENABLED) {
      return []
    }
    return [
      {
        source: '/api/v1/:path*',
        destination: `${API_URL}/api/v1/:path*`,
      },
    ]
  },

  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
        ],
      },
    ]
  },
}

export default nextConfig
