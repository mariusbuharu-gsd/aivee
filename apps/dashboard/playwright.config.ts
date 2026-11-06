import { defineConfig, devices } from '@playwright/test';

// End-to-end tests in a real browser.
//
// - `npm run e2e` (default, CI): the dashboard on the built-in mock API, desktop and phone.
//   Needs nothing else running.
// - `npm run e2e:real`: the dashboard against a running API (`make api`, seeded with
//   `make seed`). Reads E2E_API_URL (default http://localhost:8000) and DEMO_PASSWORD from the
//   environment; the password is never logged.

const real = process.env.E2E_REAL === '1';
const port = real ? 5174 : 5175;
const apiUrl = process.env.E2E_API_URL ?? 'http://localhost:8000';

export default defineConfig({
  testDir: './e2e',
  testMatch: real ? 'real/**/*.spec.ts' : 'mock/**/*.spec.ts',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 2 : undefined,
  reporter: process.env.CI ? [['github'], ['list']] : 'list',
  timeout: 45_000,
  use: {
    baseURL: `http://localhost:${port}`,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    locale: 'ro-RO',
    timezoneId: 'Europe/Bucharest',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'phone', use: { ...devices['Pixel 7'] } },
  ],
  webServer: {
    // A production build, not the dev server: no dependency re-optimisation reloading pages
    // mid-test, and it is what users get.
    command: `npx vite build --outDir dist-e2e --emptyOutDir && npx vite preview --outDir dist-e2e --port ${port} --strictPort`,
    url: `http://localhost:${port}/intra`,
    reuseExistingServer: false,
    timeout: 120_000,
    // Mock mode: no VITE_API_URL, so the dashboard uses its in-browser mock.
    env: real ? { VITE_API_URL: apiUrl } : { VITE_API_URL: '' },
  },
});
