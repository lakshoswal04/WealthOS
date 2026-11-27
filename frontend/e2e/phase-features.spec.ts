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

test("alerts report measurement failures and an unavailable health score does not crash", async ({ page }) => {
  await page.goto("/analysis/insights");
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
  await page.goto("/analysis/insights");
  await expect(page.getByRole("heading", { name: "Where the behavioural inputs come from" })).toBeVisible();
  await expect(page.getByText("Coverage is not a probability.", { exact: false })).toBeVisible();
  await expect(page.getByText(/mean-drift baseline value is not supplied/)).toBeVisible();
  await expect(page.getByText("Model ensemble", { exact: true })).toBeVisible();
});

