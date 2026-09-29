import { defineConfig, devices } from "@playwright/test";

// Smoke tests of the production build against a mocked agent API (see e2e/mock-api.ts).
// They drive the installed Google Chrome, so no browser download is needed.
const port = Number(process.env.E2E_PORT ?? 8199);

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    trace: "retain-on-failure",
    // Settled styles only: axe measures contrast, which a fade-in would skew.
    reducedMotion: "reduce",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], channel: "chrome" } },
    { name: "mobile", use: { ...devices["Pixel 7"], channel: "chrome" } },
  ],
  webServer: {
    command: `npx next start --port ${port} --hostname 127.0.0.1`,
    url: `http://127.0.0.1:${port}`,
    reuseExistingServer: !process.env.CI,
    // Never reached: every /api request is answered inside the browser by the mock.
    env: { OPSPILOT_API_URL: "http://127.0.0.1:9" },
  },
});
