import { expect, test } from "@playwright/test";
import { cleanupAccounts, signUpViaApi } from "./helpers";

/* Runs against the real trained models and live prices. */

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "functional; layout is covered elsewhere");
  await signUpViaApi(page, "autopilot");
});
test.afterEach(async ({ request }) => { await cleanupAccounts(request); });

test("autopilot switches on, rebalances with reasons, and stops", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/autopilot");
  await expect(page.getByRole("heading", { name: "Autopilot" })).toBeVisible();
  await expect(page.getByText("What Autopilot would hold today")).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Switch on" }).click();
  await expect(page.getByText("On", { exact: true })).toBeVisible({ timeout: 30_000 });
  await page.getByRole("button", { name: "Rebalance now" }).click();
  await expect(page.getByText(/· manual/)).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Added \d+ /).first()).toBeVisible();
  page.on("dialog", (d) => d.accept());
  await page.getByRole("button", { name: "Stop and sell" }).click();
  await expect(page.getByText("Off", { exact: true })).toBeVisible({ timeout: 60_000 });
});

test("an amount is planned across chosen sectors", async ({ page }) => {
  await page.goto("/market/model-picks#invest-amount");
  await page.getByLabel("Amount to invest").fill("50000");
  await page.getByRole("button", { name: "Banking", exact: true }).click();
  await page.getByRole("button", { name: "IT", exact: true }).click();
  await page.getByRole("button", { name: "Plan it" }).click();
  const planner = page.locator("#invest-amount");
  await expect(planner.getByText("Financial Services").first()).toBeVisible({ timeout: 30_000 });
  await expect(planner.getByText("Information Technology").first()).toBeVisible();
  await expect(planner.getByText(/Invested ₹/)).toBeVisible();
});

test("a new account's review asks for real holdings instead of inventing them", async ({ page }) => {
  await page.goto("/analysis/overview");
  await expect(page.getByText("No holdings yet")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("link", { name: "Import holdings" })).toBeVisible();
  // The chat says the same instead of inventing a portfolio.
  await page.goto("/home?prompt=Review%20my%20portfolio");
  await page.getByRole("button", { name: /send/i }).first().click();
  await expect(page.getByText(/No holdings imported yet/).first()).toBeVisible({ timeout: 60_000 });
});
