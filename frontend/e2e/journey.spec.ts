import { expect, test, type Page } from "@playwright/test";
import { cleanupAccounts, track } from "./helpers";

/**
 * The end-to-end journey the project demonstration follows:
 * register → import holdings → analytics → risk → goal → health score →
 * insights → the AI chat. The analytics live under /analysis since the
 * trading surfaces took the top level; trading has its own spec.
 */

const API = process.env.E2E_API_URL ?? "http://127.0.0.1:8010";

const HOLDINGS_CSV = `symbol,asset_type,quantity,average_price,purchase_date
RELIANCE,Equity,40,1150.50,2022-03-15
TCS,Equity,25,3200.00,2022-05-20
INFY,Equity,60,1350.00,2023-01-05
NIFTYBEES,ETF,500,185.40,2022-08-12
GOLDBEES,Gold,1200,48.20,2023-02-28
DEBT,Debt,300,52.10,2022-06-01`;

function uniqueEmail(): string {
  return `e2e-${Date.now()}-${Math.floor(Math.random() * 1e4)}@example.com`;
}

async function register(page: Page): Promise<string> {
  const email = uniqueEmail();
  await page.goto("/register");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("a-strong-test-password");
  await page.getByLabel("Full name").fill("E2E Investor");
  await page.getByLabel("Age").fill("34");
  await page.getByLabel("Horizon (years)").fill("20");
  await page.getByLabel("Annual income (₹)").fill("1800000");
  await page.getByLabel("Monthly savings (₹)").fill("45000");
  await page.getByRole("button", { name: "Create account" }).click();
  await page.waitForURL("**/home", { timeout: 20_000 });
  track(email);
  return email;
}

async function importHoldings(page: Page) {
  await page.goto("/import");
  await page.setInputFiles('input[type="file"]', {
    name: "holdings.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(HOLDINGS_CSV),
  });
  await page.getByRole("button", { name: "Import" }).click();
  await expect(page.getByText("Imported", { exact: true })).toBeVisible({ timeout: 20_000 });
}

test.afterEach(async ({ request }) => { await cleanupAccounts(request); });

test.beforeAll(async ({ request }) => {
  // Fail fast and clearly if the API is not running, rather than through a
  // cascade of confusing UI timeouts.
  const health = await request.get(`${API}/health`);
  expect(health.ok(), `API at ${API} is not reachable`).toBeTruthy();
});

/*
 * Card titles render as <h2>, so these assertions target the heading role
 * rather than any element whose text contains the phrase. Bare text matches
 * were passing by luck: they also matched the screen-reader labels on the new
 * loading placeholders, which made the assertion a race between the skeleton
 * disappearing and the heading appearing.
 */
test("the full demonstration journey works end to end", async ({ page }) => {
  await register(page);

  // ---- import ----
  await importHoldings(page);
  await expect(page.getByText(/6 rows read/)).toBeVisible();

  // The HDFCBANK-style cost-basis warning only fires on affected symbols;
  // here we simply assert the import succeeded and linked onward.
  await page.getByRole("link", { name: "See your dashboard" }).click();
  await page.waitForURL("**/analysis/overview");

  // ---- overview ----
  await expect(page.getByRole("heading", { name: "Overview", exact: true })).toBeVisible();
  await expect(page.getByText("Total value")).toBeVisible();
  await expect(page.getByText("Asset allocation")).toBeVisible();
  // A real figure, not a placeholder.
  await expect(page.locator("text=/₹[0-9,]+/").first()).toBeVisible();

  // ---- portfolio ----
  await page.getByRole("link", { name: "Holdings", exact: true }).click();
  await page.waitForURL("**/analysis/holdings");
  await expect(page.getByText("6 holdings")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("RELIANCE").first()).toBeVisible();
  await expect(page.getByText("Sector exposure")).toBeVisible();

  // ---- risk ----
  await page.getByRole("link", { name: "Risk", exact: true }).click();
  await page.waitForURL("**/analysis/risk");
  await expect(page.getByRole("heading", { name: "Risk", exact: true })).toBeVisible();
  await expect(page.getByText("Sharpe ratio").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Max drawdown")).toBeVisible();
  await expect(page.getByText("Correlation").first()).toBeVisible();
  // Assumptions must travel with the numbers.
  await expect(page.getByText("How these were computed")).toBeVisible();

  // ---- goals ----
  await page.getByRole("link", { name: "Goals", exact: true }).click();
  await page.waitForURL("**/analysis/goals");
  await page.getByRole("button", { name: "New goal" }).click();
  await page.getByLabel("Name").fill("Retirement");
  await page.getByLabel("Target amount (₹)").fill("25000000");
  await page.getByLabel("Target date").fill("2046-04-01");
  await page.getByLabel("Monthly contribution (₹)").fill("40000");
  await page.getByRole("button", { name: "Create goal" }).click();

  await page.getByText("Retirement").first().click();
  await expect(page.getByText("Scenarios")).toBeVisible({ timeout: 20_000 });
  // A projection must present a range and never read as a promise.
  await expect(page.getByText("pessimistic")).toBeVisible();
  await expect(page.getByText(/not a prediction/)).toBeVisible();

  // ---- insights ----
  await page.getByRole("link", { name: "Insights", exact: true }).click();
  await page.waitForURL("**/analysis/insights");
  await expect(page.getByRole("heading", { name: "Portfolio Health Score" })).toBeVisible({ timeout: 25_000 });
  await expect(page.getByRole("heading", { name: "What moves the score" })).toBeVisible({ timeout: 25_000 });
  await expect(page.getByRole("heading", { name: "Wealth forecast" })).toBeVisible();

  // ---- AI chat (formerly the Copilot page) ----
  await page.goto("/home");
  await page.getByLabel("Message the AI").fill("Why is my portfolio risky?");
  await page.getByLabel("Message the AI").press("Enter");
  // Every figure in the answer must be traceable to a backend measurement.
  await expect(page.getByText(/figures verified/)).toBeVisible({ timeout: 30_000 });
});

test("a malformed CSV is rejected in full and says why", async ({ page }) => {
  await register(page);
  await page.goto("/import");

  await page.setInputFiles('input[type="file"]', {
    name: "bad.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(
      "symbol,quantity,average_price\nRELIANCE,10,1000\nNOTREAL,5,3000\n",
    ),
  });
  await page.getByRole("button", { name: "Import" }).click();

  // Targets the outcome badge rather than any element containing the word.
  // A bare text match broke when the results table gained a screen-reader
  // caption that also mentions rejected rows -- the assertion was testing
  // the copy, not the outcome.
  const outcome = page.getByTestId("import-outcome");
  await expect(outcome).toBeVisible({ timeout: 20_000 });
  await expect(outcome).toHaveText("Rejected");
  await expect(page.getByText(/Nothing was saved/)).toBeVisible();
  await expect(page.getByText(/not a supported symbol/)).toBeVisible();

  // The valid row must not have been written either.
  await page.goto("/analysis/holdings");
  await expect(page.getByText("Nothing held yet")).toBeVisible({ timeout: 15_000 });
});

test("an empty portfolio explains itself instead of showing broken charts", async ({ page }) => {
  await register(page);

  await page.goto("/analysis/overview");
  await expect(page.getByText("No holdings yet")).toBeVisible({ timeout: 15_000 });

  await page.goto("/analysis/risk");
  await expect(page.getByText("Not enough history")).toBeVisible({ timeout: 15_000 });
});

test("protected pages redirect an anonymous visitor to sign in", async ({ page }) => {
  await page.context().clearCookies();
  for (const path of ["/home", "/portfolio", "/chart", "/overview"]) {
    await page.goto(path);
    await page.waitForURL("**/login", { timeout: 15_000 });
    await expect(page.getByRole("heading", { name: "Welcome back." })).toBeVisible();
  }
});

test("old analytics links redirect to their new home", async ({ page }) => {
  await register(page);
  for (const [from, to] of [["/overview", "/analysis/overview"], ["/risk", "/analysis/risk"],
                            ["/research", "/analysis/model-lab"], ["/copilot", "/home"]]) {
    await page.goto(from);
    await page.waitForURL(`**${to}`, { timeout: 15_000 });
  }
});

/* ───────────────── landing page and research pages ───────────────── */

test("the landing page is public and routes to sign-up", async ({ page }) => {
  await page.context().clearCookies();
  await page.goto("/");

  // An anonymous visitor must land here, not be bounced to a login form.
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Your wealth.");

  // The models' measured record is read from the pipeline reports at runtime.
  await page.locator("#method").scrollIntoViewIfNeeded();
  await expect(page.getByText("rank IC, out of sample")).toBeVisible();

  // The disclaimer is present, not buried.
  await expect(page.getByText(/not investment advice/i).first()).toBeVisible();

  await page.getByRole("link", { name: "Get started →" }).first().click();
  await page.waitForURL("**/register");
});

test("the research reports endpoint needs no account", async ({ request }) => {
  const response = await request.get(`${API}/api/v1/research/reports`);
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  expect(Object.keys(body)).toEqual(expect.arrayContaining(["models", "data"]));
});

test("the Model Lab renders real training evidence", async ({ page }) => {
  await register(page);
  await importHoldings(page);

  await page.goto("/analysis/model-lab");
  await expect(page.getByRole("heading", { name: "Model Lab" })).toBeVisible();

  await expect(page.getByText("Investor behaviour clustering")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("ARI vs archetype")).toBeVisible();
  await expect(page.getByText("Did it recover the real groups?")).toBeVisible();

  await expect(page.getByText("Portfolio anomaly detection")).toBeVisible();
  await expect(page.getByText("Against a shallow baseline")).toBeVisible();

  await expect(page.getByText("Wealth trajectory forecasting")).toBeVisible();
  await expect(page.getByText("Skill across horizons")).toBeVisible();

  await expect(page.getByText("Copilot grounding")).toBeVisible();
  await expect(page.getByText("Leakage controls")).toBeVisible();
});

test("the Data Quality page shows the corporate-action finding", async ({ page }) => {
  await register(page);

  await page.goto("/analysis/data-quality");
  await expect(page.getByRole("heading", { name: "Data Quality" })).toBeVisible();

  await expect(page.getByText("The corporate-action problem")).toBeVisible({ timeout: 20_000 });
  // The specific evidence, not just the heading.
  await expect(page.getByText(/not adjusted for corporate actions/)).toBeVisible();
  await expect(page.getByText("Sharpe sign flips")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Joining the sources" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "The synthetic cohort" })).toBeVisible();
});

test("the scenario simulator responds to input", async ({ page }) => {
  test.setTimeout(90_000);
  await register(page);
  await importHoldings(page);

  await page.goto("/analysis/goals");
  await page.getByRole("button", { name: "New goal" }).click();
  await page.getByLabel("Name").fill("Retirement");
  await page.getByLabel("Target amount (₹)").fill("25000000");
  await page.getByLabel("Target date").fill("2046-04-01");
  await page.getByLabel("Monthly contribution (₹)").fill("20000");
  await page.getByRole("button", { name: "Create goal" }).click();
  await page.getByText("Retirement").first().click();

  await expect(page.getByText("What would it take?")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Chance of reaching the target")).toBeVisible();

  // Scoped to the simulator: a bare percentage selector also matches the
  // goal card's progress figure elsewhere on the page.
  const probability = page.getByTestId("success-probability");
  await expect(probability).toBeVisible();

  // A projection must never read as a promise.
  await expect(page.getByText(/not a prediction/).first()).toBeVisible();

  // Raising the contribution must change the answer.
  const before = await probability.textContent();
  await page.getByLabel("Monthly contribution").fill("250000");
  await expect
    .poll(async () => probability.textContent(), { timeout: 15_000 })
    .not.toBe(before);
});
