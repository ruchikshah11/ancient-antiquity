import { defineConfig } from '@playwright/test';

/**
 * Browser tests against the running dev servers:
 *   backend  python manage.py runserver 127.0.0.1:8000 (seeded demo data)
 *   frontend npx vite --port 5173
 * Run: npm run test:e2e   (uses the installed Microsoft Edge, no browser download needed)
 * Override the target with E2E_BASE_URL, e.g. against a staging build.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1, // the booking test changes shared demo data; keep runs predictable
  retries: process.env.CI ? 1 : 0,
  reporter: [['list']],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? 'http://127.0.0.1:5173',
    channel: 'msedge',
    headless: true,
    locale: 'en-IN',
    timezoneId: 'Asia/Kolkata',
    viewport: { width: 1280, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  outputDir: './e2e-results',
});
