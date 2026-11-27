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
  },
  /**
   * Three viewports, not one.
   *
   * Everything ran at 1440x980 only, which is the width at which this layout
   * was built and therefore the width least likely to be broken. The tablet
   * tier in particular had no coverage at all because it had no styles: `md:`
   * appeared meaningfully once in the whole application, so a tablet got
   * whatever the phone got and nothing noticed.
   *
   * The journey spec stays desktop-only -- it is a functional walkthrough and
   * running it three times would triple the time without testing anything
   * new. The responsive spec is the one that runs everywhere.
   */
  projects: [
    {
      name: "desktop",
      use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 980 } },
    },
    {
      name: "tablet",
      // 820x1180 is an iPad Air in portrait: inside the `md` tier and below
      // `lg`, which is exactly the band that had no styles of its own.
      use: { ...devices["Desktop Chrome"], viewport: { width: 820, height: 1180 } },
      testMatch: /responsive\.spec\.ts/,
    },
    {
      name: "mobile",
      // 390x844 is an iPhone 14. Narrower than the 168px category axis that
      // used to take 43% of it.
      use: { ...devices["Desktop Chrome"], viewport: { width: 390, height: 844 } },
      testMatch: /responsive\.spec\.ts/,
    },
  ],
});
