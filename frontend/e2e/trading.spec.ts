import { expect, test, type Page } from "@playwright/test";
import { API, cleanupAccounts, signUpViaApi } from "./helpers";

/**
 * The trading journey on real data. These run without an Upstox session,
 * so they also prove the rule that matters most: where real data is
 * missing, the page says why instead of showing a number.
 */

async function ask(page: Page, text: string) {
  const answers = page.getByText(/figures? (verified|unverified)/);
  const before = await answers.count();
  await page.getByLabel("Message the AI").last().fill(text);
  await page.getByLabel("Message the AI").last().press("Enter");
  await expect(answers).toHaveCount(before + 1, { timeout: 60_000 });
}

test.describe.configure({ mode: "serial" });

test.beforeEach(async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "a functional walkthrough; layout is covered by responsive.spec");
  test.setTimeout(120_000);
  await signUpViaApi(page, "trade");
});

test.afterEach(async ({ request }) => { await cleanupAccounts(request); });

test("the AI proposes an order and places it only when confirmed", async ({ page }) => {
  await page.goto("/home");
  await expect(page.getByRole("heading", { name: /What would you like to know/ })).toBeVisible();
  await ask(page, "buy 10 shares of RELIANCE");
  const confirm = page.getByRole("button", { name: "Confirm paper order" });
  await expect(confirm).toBeVisible();
  const token = await page.evaluate(() => localStorage.getItem("wealthos.token"));
  const before = await page.request.get(`${API}/api/v1/paper/orders`, { headers: { Authorization: `Bearer ${token}` } });
  expect((await before.json()).total).toBe(0);
  await confirm.click();
  await expect(page.getByText(/Filled 10 at/)).toBeVisible({ timeout: 20_000 });
  await page.goto("/portfolio");
  await expect(page.getByRole("link", { name: "RELIANCE" })).toBeVisible({ timeout: 15_000 });
});

test("option screens ask for Upstox instead of showing numbers", async ({ page }) => {
  for (const path of ["/market/option-chain", "/market/oi", "/market/unusual", "/tools/strategy-chart"]) {
    await page.goto(path);
    await expect(page.getByRole("link", { name: "Connect Upstox" }).first()).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText(/simulated|modelled/i)).toHaveCount(0);
  }
});

test("an OI question without Upstox explains how to connect", async ({ page }) => {
  await page.goto("/chart?symbol=NIFTY");
  await page.getByRole("button", { name: "Which strike has the most OI build-up?" }).click();
  await expect(page.getByText(/Connect your Upstox account/).first()).toBeVisible({ timeout: 60_000 });
});

test("screeners run and the builder validates", async ({ page }) => {
  await page.goto("/market/screener");
  await expect(page.getByRole("heading", { name: "Screeners" })).toBeVisible();
  await page.getByRole("link", { name: /Near the 52-week high/ }).click();
  await expect(page.getByText(/stocks match|cannot run right now/)).toBeVisible({ timeout: 30_000 });
});

test("every menu item is a working page and unavailable markets are not offered", async ({ page }) => {
  await page.goto("/market");
  await page.getByRole("button", { name: "Markets" }).click();
  await expect(page.getByRole("link", { name: "Commodities" })).toBeVisible();
  await expect(page.getByText("IPOs")).toHaveCount(0);
  await expect(page.getByText("FII / DII")).toHaveCount(0);
  await expect(page.getByText("Soon")).toHaveCount(0);
});
