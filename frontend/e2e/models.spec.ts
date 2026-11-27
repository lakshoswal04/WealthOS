import { expect, test } from "@playwright/test";
import { cleanupAccounts, signUpViaApi } from "./helpers";

/* Runs against the real trained swing models and the real daily price store. */

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "functional; layout is covered elsewhere");
  await signUpViaApi(page, "models");
});
test.afterEach(async ({ request }) => { await cleanupAccounts(request); });

test("model picks show ranked stocks, the regime and the model's record", async ({ page }) => {
  await page.goto("/market/model-picks");
  await expect(page.getByRole("heading", { name: "Model picks" })).toBeVisible();
  await expect(page.getByText(/Market regime ·/)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Out-of-sample record since/)).toBeVisible();
  const rows = page.locator("table").first().locator("tbody tr");
  await expect(rows).toHaveCount(20);
  await page.getByRole("tab", { name: "All 60" }).click();
  await expect(rows).toHaveCount(60);
  await expect(page.getByText(/Not investment advice/).first()).toBeVisible();
});

test("a swing plan is built for the profile and placed on paper", async ({ page }) => {
  await page.goto("/market/model-picks#swing-plan");
  await page.getByLabel("Amount to plan").fill("200000");
  await page.getByRole("button", { name: "Build plan" }).click();
  await expect(page.getByText(/Your profile is moderate/)).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Place on paper" }).click();
  await expect(page.getByText(/paper orders filled/)).toBeVisible({ timeout: 30_000 });
  await page.goto("/portfolio");
  await expect(page.getByText(/Model|model:swing/).first()).toBeVisible({ timeout: 30_000 });
});

test("the swing lab shows the evidence", async ({ page }) => {
  await page.goto("/analysis/swing-lab");
  await expect(page.getByRole("heading", { name: "Swing Lab" })).toBeVisible();
  for (const heading of ["The verdict", "Data, and the survivorship check", "Deep learning against gradient boosting",
    "Ranges, not point forecasts", "The forward test", "Method and limits"]) {
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
  }
  await expect(page.getByText("Swing ensemble (deployed)").first()).toBeVisible();
});

test("the Ideas page has a Model tab", async ({ page }) => {
  await page.goto("/market/recommendations?kind=model");
  await expect(page.getByText(/Ranked 1 of/)).toBeVisible({ timeout: 30_000 });
});
