/**
 * Vitest sozlamasi — SDK testlari uchun.
 *
 * Testlar haqiqiy tarmoqqa chiqmaydi: `globalThis.fetch` har bir testda
 * mock qilinadi. Shuning uchun muhit `node` va parallellik cheklanmagan.
 */

import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'node',
    include: ['tests/**/*.test.ts'],
    globals: false,
    testTimeout: 10_000,
    hookTimeout: 10_000,
    restoreMocks: true,
    unstubGlobals: true,
    coverage: {
      provider: 'v8',
      include: ['src/**/*.ts'],
      reporter: ['text', 'html'],
    },
  },
});
