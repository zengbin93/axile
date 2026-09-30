import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  testMatch: 'notification.e2e.ts',
  workers: 1,
  timeout: 20000,
  use: { baseURL: 'http://127.0.0.1:15380', headless: true, trace: 'retain-on-failure' },
  webServer: {
    command: 'bun run dev --port 15380 --strictPort',
    url: 'http://127.0.0.1:15380/e2e/notification.html',
    timeout: 20000,
    reuseExistingServer: true,
  },
})
