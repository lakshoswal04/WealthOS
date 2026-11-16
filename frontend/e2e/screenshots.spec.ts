import { test, type Page } from "@playwright/test";

/**
 * Captures a reference screenshot of each dashboard page against a seeded
 * portfolio. Not an assertion suite: these are the images used in the
 * project report and to eyeball layout, label collisions and overflow,
 * which a colour validator cannot catch.
 */

const CSV = `symbol,asset_type,quantity,average_price,purchase_date
RELIANCE,Equity,40,1150.50,2022-03-15
TCS,Equity,25,3200.00,2022-05-20
INFY,Equity,60,1350.00,2023-01-05
HDFCBANK,Equity,80,740.00,2021-11-10
ITC,Equity,200,310.75,2023-07-19
NIFTYBEES,ETF,500,185.40,2022-08-12
GOLDBEES,Gold,1200,48.20,2023-02-28
DEBT,Debt,300,52.10,2022-06-01`;

async function seed(page: Page) {
  await page.goto("/register");
  await page.getByLabel("Email").fill(`shots-${Date.now()}@example.com`);
  await page.getByLabel("Password").fill("a-strong-test-password");
  await page.getByLabel("Full name").fill("Demo Investor");
  await page.getByLabel("Age").fill("32");
  await page.getByLabel("Horizon (years)").fill("20");
  await page.getByLabel("Annual income (₹)").fill("1800000");
  await page.getByLabel("Monthly savings (₹)").fill("45000");
  await page.getByRole("button", { name: "Create account" }).click();
  await page.waitForURL("**/import");

  await page.setInputFiles('input[type="file"]', {
    name: "holdings.csv", mimeType: "text/csv", buffer: Buffer.from(CSV),
  });
  await page.getByRole("button", { name: "Import" }).click();
  await page.getByText("Imported", { exact: true }).waitFor({ timeout: 20_000 });

  await page.getByRole("button", { name: "New goal" }).waitFor({ state: "detached" }).catch(() => {});
  await page.goto("/goals");
  await page.getByRole("button", { name: "New goal" }).click();
  await page.getByLabel("Name").fill("Retirement");
  await page.getByLabel("Target amount (₹)").fill("25000000");
  await page.getByLabel("Target date").fill("2046-04-01");
  await page.getByLabel("Monthly contribution (₹)").fill("40000");
  await page.getByRole("button", { name: "Create goal" }).click();
  await page.getByText("Retirement").first().waitFor();
}

test("capture every page", async ({ page }) => {
  test.setTimeout(240_000);
  await seed(page);

  const pages: [string, string][] = [
    ["/overview", "overview"],
    ["/portfolio", "portfolio"],
    ["/risk", "risk"],
    ["/goals", "goals"],
    ["/insights", "insights"],
    ["/copilot", "copilot"],
    ["/import", "import"],
    ["/profile", "profile"],
  ];

  for (const [path, name] of pages) {
    await page.goto(path);
    // Charts and model panels settle after their fetches resolve.
    await page.waitForTimeout(3500);
    if (path === "/goals") {
      await page.getByText("Retirement").first().click();
      await page.waitForTimeout(2500);
    }
    if (path === "/copilot") {
      await page.getByRole("button", { name: "Why is my portfolio risky?" }).click();
      await page.getByText(/figures verified/).waitFor({ timeout: 30_000 });
      await page.waitForTimeout(800);
    }
    await page.screenshot({ path: `../docs/screenshots/${name}.png`, fullPage: true });
  }
});
