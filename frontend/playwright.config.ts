import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 45_000,
  expect: { timeout: 10_000 },
  reporter: [
    ['list'],
    ['html', { open: 'never' }],
    ['json', { outputFile: '../artifacts/browser/results.json' }],
  ],
  use: {
    baseURL: process.env.SCOPEGATE_WEB_URL ?? 'http://localhost:5187',
    browserName: 'chromium',
    channel:
      process.env.SCOPEGATE_BROWSER_CHANNEL ??
      (process.platform === 'darwin' ? 'chrome' : undefined),
    viewport: { width: 1440, height: 1000 },
    trace: 'retain-on-failure',
    actionTimeout: 10_000,
    screenshot: 'only-on-failure',
  },
});
