import { defineConfig, devices } from "@playwright/test";

/**
 * UI tests run against the real stack: a running API on :8010 and the
 * Next.js app on :3000. They exercise the journey a viva demonstration
 * follows, so a regression in the wiring between the two shows up here
 * rather than live.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 45_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:3000",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    viewport: { width: 1440, height: 980 },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
