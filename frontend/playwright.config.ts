import { defineConfig, devices } from '@playwright/test';
import 'dotenv/config'

const browserChannel = process.env.PLAYWRIGHT_CHANNEL
const baseURL = process.env.PLAYWRIGHT_BASE_URL || "http://127.0.0.1:5174"
const apiURL = process.env.PLAYWRIGHT_API_URL || "http://127.0.0.1:8001"
const externalBackend = process.env.PLAYWRIGHT_EXTERNAL_BACKEND === "true"

// 端口来自上面两个 URL：本机同时跑别的项目时（8001/5174 被占用），
// 用 PLAYWRIGHT_BASE_URL / PLAYWRIGHT_API_URL 换一组端口即可，CI 默认值不变。
const basePort = new URL(baseURL).port || "5174"
const apiPort = new URL(apiURL).port || "8001"

// Test helpers use this value directly, while the Vite process receives the
// same value below. Neither path may silently fall back to the user backend.
process.env.VITE_API_URL = apiURL

const webServers = [
  ...(!externalBackend
    ? [
        {
          command:
            `uv run python scripts/start_test_backend.py --port ${apiPort}`,
          cwd: "..",
          url: `${apiURL}/api/v1/utils/health-check/`,
          reuseExistingServer: false,
          timeout: 180_000,
        },
      ]
    : []),
  {
    command: `bun run dev -- --host 127.0.0.1 --port ${basePort}`,
    url: baseURL,
    reuseExistingServer: false,
    timeout: 120_000,
    env: {
      ...process.env,
      VITE_API_URL: apiURL,
    },
  },
]

/**
 * Read environment variables from file.
 * https://github.com/motdotla/dotenv
 */

/**
 * See https://playwright.dev/docs/test-configuration.
 */
export default defineConfig({
  testDir: './tests',
  /* Run tests in files in parallel */
  fullyParallel: true,
  /* Fail the build on CI if you accidentally left test.only in the source code. */
  forbidOnly: !!process.env.CI,
  /* Retry on CI only */
  retries: process.env.CI ? 2 : 0,
  /* Opt out of parallel tests on CI. */
  workers: process.env.CI ? 1 : undefined,
  /* Reporter to use. See https://playwright.dev/docs/test-reporters */
  reporter: process.env.CI ? 'blob' : 'html',
  /* Shared settings for all the projects below. See https://playwright.dev/docs/api/class-testoptions. */
  use: {
    /* Base URL to use in actions like `await page.goto('/')`. */
    baseURL,
    ...(browserChannel ? { channel: browserChannel } : {}),

    /* Collect trace when retrying the failed test. See https://playwright.dev/docs/trace-viewer */
    trace: 'on-first-retry',
  },

  /* Configure projects for major browsers */
  projects: [
    { name: 'setup', testMatch: /.*\.setup\.ts/ },

    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        ...(browserChannel ? { channel: browserChannel } : {}),
        storageState: 'playwright/.auth/user.json',
      },
      dependencies: ['setup'],
    },

    // {
    //   name: 'firefox',
    //   use: {
    //     ...devices['Desktop Firefox'],
    //     storageState: 'playwright/.auth/user.json',
    //   },
    //   dependencies: ['setup'],
    // },

    // {
    //   name: 'webkit',
    //   use: {
    //     ...devices['Desktop Safari'],
    //     storageState: 'playwright/.auth/user.json',
    //   },
    //   dependencies: ['setup'],
    // },

    /* Test against mobile viewports. */
    // {
    //   name: 'Mobile Chrome',
    //   use: { ...devices['Pixel 5'] },
    // },
    // {
    //   name: 'Mobile Safari',
    //   use: { ...devices['iPhone 12'] },
    // },

    /* Test against branded browsers. */
    // {
    //   name: 'Microsoft Edge',
    //   use: { ...devices['Desktop Edge'], channel: 'msedge' },
    // },
    // {
    //   name: 'Google Chrome',
    //   use: { ...devices['Desktop Chrome'], channel: 'chrome' },
    // },
  ],

  /* Run your local dev server before starting the tests */
  webServer: webServers,
});
