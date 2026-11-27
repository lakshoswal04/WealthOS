import { expect, test } from "@playwright/test";
import { cleanupAccounts, signUpViaApi } from "./helpers";

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "functional; layout is covered elsewhere");
  await signUpViaApi(page, "settings");
});
test.afterEach(async ({ request }) => { await cleanupAccounts(request); });

test("the account menu reaches every settings page", async ({ page }) => {
  await page.goto("/home");
  await page.getByRole("button", { name: "Account menu" }).click();
  for (const label of ["Broker APIs", "Trading Preferences", "Memory", "Account", "Notifications", "Tutorials"]) {
    await expect(page.getByRole("link", { name: label, exact: true })).toBeVisible();
  }
  await page.getByRole("button", { name: "Keyboard shortcuts" }).click();
  await expect(page.getByRole("dialog")).toContainText("Search stocks and indices");
});

test("trading preferences save", async ({ page }) => {
  await page.goto("/settings/trading");
  const lots = page.getByRole("spinbutton").nth(1);
  await lots.fill("3");
  await page.getByRole("button", { name: "Save preferences" }).click();
  await expect(page.getByText(/Saved\./)).toBeVisible();
  await page.reload();
  await expect(page.getByRole("spinbutton").nth(1)).toHaveValue("3");
});

test("memory can be added, paused and removed", async ({ page }) => {
  await page.goto("/settings/memory");
  await expect(page.getByText("Memory is on")).toBeVisible();
  await page.getByRole("button", { name: "Add to Markets" }).click();
  await page.getByPlaceholder(/Trades NIFTY/).fill("Trades NIFTY weekly options");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await expect(page.getByText("Trades NIFTY weekly options")).toBeVisible();
  await page.getByRole("switch", { name: "Pause memory" }).click();
  await expect(page.getByText("Memory is paused")).toBeVisible();
  await page.getByRole("button", { name: "Forget this" }).click();
  await expect(page.getByText("Trades NIFTY weekly options")).toHaveCount(0);
});

test("the Upstox wizard saves credentials and stops at the real login", async ({ page }) => {
  await page.goto("/settings/brokers");
  await expect(page.getByText("Step 1 of 7")).toBeVisible();
  for (let i = 0; i < 3; i++) await page.getByRole("button", { name: "Continue" }).click();
  await page.getByPlaceholder("API key").fill("test-upstox-key-0001");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByPlaceholder("API secret").fill("test-upstox-secret");
  await page.getByRole("button", { name: "Save and continue" }).click();
  await expect(page.getByText(/Key ending ••••0001 is saved/)).toBeVisible();
  await expect(page.getByRole("button", { name: "Log in with Upstox" })).toBeVisible();
  // The next click leaves for upstox.com; the flow beyond it needs a real account.
});

test("the prompt book's examples open the chat prefilled", async ({ page }) => {
  await page.goto("/prompt-book");
  await page.getByRole("link", { name: /Autopilot prompts/ }).click();
  await page.getByRole("link", { name: /Try it/ }).first().click();
  await expect(page.getByLabel("Message the AI")).toHaveValue("Invest 50,000 in autopilot now");
});
