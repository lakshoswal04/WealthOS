import { expect, test } from "@playwright/test";

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem("wealthos.token", "test-token"));
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const reply = async (body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
    if (path === "/api/v1/auth/me") return reply({ id: 1, email: "test@example.com", full_name: "Test", risk_tolerance: "moderate" });
    if (path === "/api/v1/portfolio") return reply({ n_holdings: 0 });
    if (path === "/api/v1/linked-accounts" && request.method() === "GET") return reply({ accounts: [], simulation_notice: "Simulation only" });
    if (path === "/api/v1/linked-accounts" && request.method() === "POST") return reply({ id: 1, is_simulated: true }, 201);
    if (path === "/api/v1/alerts" && request.method() === "GET") return reply({ alerts: [], unread: 0 });
    if (path === "/api/v1/alerts/generate") return reply({ generated_count: 0, rejected: [], measurement_failures: { risk: "Not enough history" } });
    if (path === "/api/v1/health-score") return reply({ total: null, summary: "No score yet", components: [], methodology: "", sensitivity: [] });
    return reply({ available: false, reason: "No data" });
  });
});

test("sandbox linking is explicitly labeled and sends a simulated request", async ({ page }) => {
  await page.goto("/import");
  await expect(page.getByRole("heading", { name: "Simulated account linking" })).toBeVisible();
  await expect(page.getByText(/Syncing adds simulated transactions/)).toBeVisible();
  const request = page.waitForRequest((r) => r.url().endsWith("/api/v1/linked-accounts") && r.method() === "POST");
  await page.getByRole("button", { name: "Create simulated link" }).click();
  expect((await request).postDataJSON()).toMatchObject({ provider: "sandbox", account_reference: "SBX0001" });
});

test("alerts report measurement failures and an unavailable health score does not crash", async ({ page }) => {
  await page.goto("/insights");
  await expect(page.getByText(/A health score is not available yet/)).toBeVisible();
  await page.getByRole("button", { name: "Check portfolio" }).click();
  await expect(page.getByText("Risk: Not enough history")).toBeVisible();
});

test("insights show provenance and distinguish forecast baselines", async ({ page }) => {
  await page.route("**/api/v1/investor-profile", (route) => route.fulfill({ json: {
    available: true, cluster_name: "Example", cluster_share: 0.1, match_confidence: 0.3,
    feature_provenance: { sources: { turnover: "reconstructed", contribution_rate: "observed" }, confidence: 0.5, confidence_basis: "Coverage is not a probability.", note: "Reconstruction can bias turnover." },
  } }));
  await page.route("**/api/v1/forecast?*", (route) => route.fulfill({ json: {
    available: true, current_value: 100, baseline_value: 100, projected_value: 110,
    projected_growth_over_baseline: 0.1,
    recommendation: { recommended_source: "baseline_mean_drift", model_beats_baseline: false, note: "Evaluated across folds." },
  } }));
  await page.goto("/insights");
  await expect(page.getByRole("heading", { name: "Where the behavioural inputs come from" })).toBeVisible();
  await expect(page.getByText("Coverage is not a probability.", { exact: false })).toBeVisible();
  await expect(page.getByText(/mean-drift baseline value is not supplied/)).toBeVisible();
  await expect(page.getByText("Model ensemble", { exact: true })).toBeVisible();
});

test("simulated sync reports failures and retains history after disconnect", async ({ page }) => {
  let disconnected = false;
  let syncRequests = 0;
  await page.route("**/api/v1/linked-accounts**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    const method = route.request().method();
    if (path === "/api/v1/linked-accounts") return route.fulfill({ json: { simulation_notice: "Simulation only", accounts: [{ id: 7, display_name: "Sandbox 0001", status: disconnected ? "disconnected" : "active", last_successful_sync_at: null, last_sync_error: null }] } });
    if (path.endsWith("/sync")) { syncRequests++; return route.fulfill({ json: { run: { status: "failed" } } }); }
    if (path.endsWith("/syncs")) return route.fulfill({ json: { runs: [{ id: 1, status: "failed", started_at: null, holdings_created: 0, holdings_updated: 0, transactions_created: 0, error_message: "Provider unavailable" }] } });
    if (method === "DELETE") { disconnected = true; return route.fulfill({ status: 204 }); }
    return route.fulfill({ status: 404 });
  });
  await page.goto("/import");
  await expect(page.getByText("Sandbox 0001")).toBeVisible();
  page.once("dialog", (dialog) => dialog.dismiss());
  await page.getByRole("button", { name: "Sync simulated data" }).click();
  expect(syncRequests).toBe(0);
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Sync simulated data" }).click();
  await expect(page.getByText(/Provider unavailable/)).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Disconnect", exact: true }).click();
  await expect(page.getByText("Disconnected", { exact: true })).toBeVisible();
  await expect(page.getByText(/Provider unavailable/)).toBeVisible();
});
