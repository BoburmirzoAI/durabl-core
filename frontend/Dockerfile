# =============================================================================
# Durabl frontend — Next.js 14 (App Router) uchun ko'p qatlamli image
#
# Qatlamlar (target):
#   deps    — faqat npm bog'liqliklari (kesh uchun alohida)
#   dev     — development server (`next dev`, hot reload) — docker-compose ishlatadi
#   builder — `npm run build` (standalone chiqish)
#   runner  — production (minimal, non-root, `node server.js`)
#
# MUHIM: `runner` qatlami Next.js "standalone" chiqishiga tayanadi.
# `next.config.mjs` ichida `output: 'standalone'` bo'lishi SHART (bor).
#
# HOZIRGI HOLAT: frontend to'liq MOCK ma'lumot bilan ishlaydi — image ichida
# backend'ga birorta so'rov yuborilmaydi. `NEXT_PUBLIC_API_URL` build argumenti
# qabul qilinadi va bundle'ga joylanadi, lekin hali hech kim o'qimaydi.
# Backend ulangach shu argument o'z-o'zidan ishlay boshlaydi.
#
# Build (prod): docker build --target runner -t durabl/frontend:latest frontend
# Build (dev):  docker build --target dev     -t durabl/frontend:dev    frontend
# =============================================================================

ARG NODE_VERSION=22

# -----------------------------------------------------------------------------
# 1-qatlam: asos
# -----------------------------------------------------------------------------
FROM node:${NODE_VERSION}-alpine AS base

#: Next.js telemetriyasi o'chirilgan (tashqi so'rov yuborilmaydi)
ENV NEXT_TELEMETRY_DISABLED=1

#: `libc6-compat` — ba'zi native modullar (swc) alpine'da shuni talab qiladi
RUN apk add --no-cache libc6-compat

WORKDIR /app

# -----------------------------------------------------------------------------
# 2-qatlam: deps — bog'liqliklar (package.json o'zgarmasa keshdan olinadi)
# -----------------------------------------------------------------------------
FROM base AS deps

COPY package.json package-lock.json* ./

#: Lock fayl bo'lsa `npm ci` (aniq versiyalar), bo'lmasa `npm install`
RUN if [ -f package-lock.json ]; then \
        npm ci; \
    else \
        echo "DIQQAT: package-lock.json topilmadi — npm install ishlatiladi"; \
        npm install; \
    fi

# -----------------------------------------------------------------------------
# 3-qatlam: dev — development server (compose shu target'ni ishlatadi)
# Kod `volume` bilan mount qilinadi, node_modules image'dan qoladi.
# -----------------------------------------------------------------------------
FROM base AS dev

ENV NODE_ENV=development \
    WATCHPACK_POLLING=true

COPY --from=deps /app/node_modules ./node_modules
COPY . .

EXPOSE 3000

#: `-H 0.0.0.0` — konteyner tashqarisidan ochilishi uchun
CMD ["npm", "run", "dev", "--", "-H", "0.0.0.0", "-p", "3000"]

# -----------------------------------------------------------------------------
# 4-qatlam: builder — production build
# -----------------------------------------------------------------------------
FROM base AS builder

#: `NEXT_PUBLIC_*` qiymatlari build vaqtida JS bundle ichiga joylanadi,
#  shuning uchun ularni build argument sifatida berish shart.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ARG NEXT_PUBLIC_WS_URL=ws://localhost:8000
#: Mock qatlamining sun'iy kechikishi — `lib/api/client.ts` build vaqtida o'qiydi
ARG NEXT_PUBLIC_MOCK_LATENCY_MS=200
ENV NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_PUBLIC_WS_URL=${NEXT_PUBLIC_WS_URL} \
    NEXT_PUBLIC_MOCK_LATENCY_MS=${NEXT_PUBLIC_MOCK_LATENCY_MS} \
    NODE_ENV=production

COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

#: Standalone chiqishi yo'q bo'lsa aniq xato bilan to'xtaymiz (jim qolmaymiz)
RUN if [ ! -d .next/standalone ]; then \
        echo "XATO: .next/standalone topilmadi — next.config.mjs ichida output: 'standalone' bo'lishi shart"; \
        exit 1; \
    fi

# -----------------------------------------------------------------------------
# 5-qatlam: runner — minimal production image (non-root)
# -----------------------------------------------------------------------------
FROM node:${NODE_VERSION}-alpine AS runner

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /app

#: Non-root foydalanuvchi (`node` useri allaqachon 1000 — biz 1001 dan foydalanamiz)
RUN addgroup --system --gid 1001 nodejs \
    && adduser --system --uid 1001 --ingroup nodejs nextjs

#: Statik fayllar va standalone server
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs

EXPOSE 3000

HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:3000/ || exit 1

#: Standalone chiqishda server fayli — `server.js`
CMD ["node", "server.js"]
