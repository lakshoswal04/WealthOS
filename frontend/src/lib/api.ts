/**
 * Typed client for the WealthOS API.
 *
 * Every call carries the bearer token and surfaces a readable error. A 401
 * clears the stored session, so an expired token logs the user out instead
 * of leaving the dashboard stuck on spinners.
 */

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8010";

const TOKEN_KEY = "wealthos.token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* private browsing: the session simply will not persist */
  }
}

export function clearToken(): void {
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly body?: unknown) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch {
    throw new ApiError(
      "Could not reach the WealthOS API. Is the backend running?", 0
    );
  }

  if (response.status === 401) {
    clearToken();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.href = "/login";
    }
    throw new ApiError("Your session has expired. Please sign in again.", 401);
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let body: unknown = null;
  if (text) {
    try { body = JSON.parse(text); } catch { body = text; }
  }

  if (!response.ok) {
    throw new ApiError(detailOf(body) ?? `Request failed (${response.status})`, response.status, body);
  }
  return body as T;
}

function detailOf(body: unknown): string | null {
  if (!body || typeof body !== "object") return typeof body === "string" ? body : null;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  // FastAPI validation errors arrive as a list of field problems.
  if (Array.isArray(detail) && detail.length) {
    const first = detail[0] as { loc?: unknown[]; msg?: string };
    const field = Array.isArray(first.loc) ? first.loc.slice(1).join(".") : "";
    return field ? `${field}: ${first.msg}` : (first.msg ?? null);
  }
  return null;
}

const V1 = "/api/v1";

export const api = {
  // ---- auth ----
  register: (payload: Record<string, unknown>) =>
    request<{ access_token: string }>(`${V1}/auth/register`, {
      method: "POST", body: JSON.stringify(payload),
    }),
  login: (email: string, password: string) =>
    request<{ access_token: string }>(`${V1}/auth/login`, {
      method: "POST", body: JSON.stringify({ email, password }),
    }),
  me: () => request<UserProfile>(`${V1}/auth/me`),
  updateProfile: (payload: Record<string, unknown>) =>
    request<UserProfile>(`${V1}/auth/me`, { method: "PATCH", body: JSON.stringify(payload) }),

  // ---- portfolio ----
  portfolio: () => request<PortfolioSummary>(`${V1}/portfolio`),
  holdings: () => request<Holding[]>(`${V1}/portfolio/holdings`),
  addHolding: (payload: Record<string, unknown>) =>
    request<Holding>(`${V1}/portfolio/holdings`, { method: "POST", body: JSON.stringify(payload) }),
  deleteHolding: (id: number) =>
    request<void>(`${V1}/portfolio/holdings/${id}`, { method: "DELETE" }),
  assets: () => request<Asset[]>(`${V1}/portfolio/assets`),
  transactions: () => request<Transaction[]>(`${V1}/portfolio/transactions`),
  addTransaction: (payload: Record<string, unknown>) =>
    request<Transaction>(`${V1}/portfolio/transactions`, {
      method: "POST", body: JSON.stringify(payload),
    }),
  importCsv: (file: File, replaceExisting: boolean) => {
    const form = new FormData();
    form.append("file", file);
    return request<ImportResult>(
      `${V1}/portfolio/import?replace_existing=${replaceExisting}`,
      { method: "POST", body: form },
    );
  },

  // ---- analytics ----
  analytics: () => request<Analytics>(`${V1}/portfolio/analytics`),
  risk: () => request<RiskReport>(`${V1}/portfolio/risk`),
  concentration: () => request<Concentration>(`${V1}/portfolio/concentration`),

  // ---- goals & health ----
  goals: () => request<Goal[]>(`${V1}/goals`),
  createGoal: (payload: Record<string, unknown>) =>
    request<Goal>(`${V1}/goals`, { method: "POST", body: JSON.stringify(payload) }),
  deleteGoal: (id: number) => request<void>(`${V1}/goals/${id}`, { method: "DELETE" }),
  goalForecast: (id: number) => request<GoalForecast>(`${V1}/goals/${id}/forecast`),
  healthScore: (sensitivity = false) =>
    request<HealthScore>(`${V1}/health-score?sensitivity=${sensitivity}`),

  // ---- decision support ----
  alerts: () => request<{ alerts: PortfolioAlert[]; unread: number }>(`${V1}/alerts`),
  generateAlerts: () => request<AlertGeneration>(`${V1}/alerts/generate`, { method: "POST" }),
  readAlert: (id: number) => request<PortfolioAlert>(`${V1}/alerts/${id}/read`, { method: "POST" }),
  dismissAlert: (id: number) => request<void>(`${V1}/alerts/${id}`, { method: "DELETE" }),

  // ---- simulated broker connections ----
  linkedAccounts: () => request<{ accounts: LinkedAccount[]; simulation_notice: string }>(`${V1}/linked-accounts`),
  linkSandbox: (provider: string, accountReference: string) =>
    request<LinkedAccount>(`${V1}/linked-accounts`, {
      method: "POST", body: JSON.stringify({ provider, code: "wealthos-demo-code", account_reference: accountReference }),
    }),
  syncAccount: (id: number) => request<{ run: SyncRun; simulation_notice: string }>(`${V1}/linked-accounts/${id}/sync`, { method: "POST" }),
  syncHistory: (id: number) => request<{ runs: SyncRun[]; simulation_notice: string }>(`${V1}/linked-accounts/${id}/syncs`),
  disconnectAccount: (id: number) => request<void>(`${V1}/linked-accounts/${id}`, { method: "DELETE" }),

  // ---- models ----
  investorProfile: () => request<InvestorProfile>(`${V1}/investor-profile`),
  anomalies: () => request<AnomalyReport>(`${V1}/anomalies`),
  forecast: (horizon = 12) => request<Forecast>(`${V1}/forecast?horizon=${horizon}`),
  modelStatus: () => request<ModelStatus>(`${V1}/models/status`),

  // ---- research (public: no user data) ----
  research: () => request<ResearchReports>(`${V1}/research/reports`),

  // ---- scenario simulator ----
  simulateGoal: (id: number, overrides: SimulationOverrides) =>
    request<Simulation>(`${V1}/goals/${id}/simulate`, {
      method: "POST", body: JSON.stringify(overrides),
    }),

  // ---- copilot ----
  chat: (message: string, history: ChatTurn[]) =>
    request<CopilotReply>(`${V1}/copilot/chat`, {
      method: "POST", body: JSON.stringify({ message, history }),
    }),
  copilotCapabilities: () => request<CopilotCapabilities>(`${V1}/copilot/capabilities`),
};

/* ──────────────── types ──────────────── */

export interface PortfolioAlert {
  id: number; title: string; message: string; severity: string; alert_type: string;
  metric_value: number | null; threshold: number | null; is_read: boolean; created_at: string | null;
  details: Record<string, unknown>;
}
export interface AlertGeneration {
  generated_count: number; suppressed_as_already_open: string[]; rejected: { rule: string; reason: string }[];
  measurement_failures: Record<string, string>;
}
export interface LinkedAccount {
  id: number; display_name: string; provider: string; account_reference: string;
  status: string; last_successful_sync_at: string | null; last_sync_error: string | null;
  simulation_notice: string; is_simulated: boolean;
}
export interface SyncRun {
  id: number; status: string; started_at: string | null; holdings_created: number;
  holdings_updated: number; transactions_created: number; duplicates_skipped: number;
  error_message: string | null;
}

export interface UserProfile {
  id: number; email: string; full_name: string | null; age: number | null;
  annual_income: number | null; monthly_savings: number | null;
  risk_tolerance: string | null; investment_horizon_years: number | null;
  is_synthetic: boolean; joined_on: string | null; created_at: string;
}

export interface Asset {
  id: number; symbol: string; name: string; asset_class: string;
  sector: string | null; price_source: string | null;
}

export interface Holding {
  id: number; symbol: string; name: string; asset_class: string; sector: string | null;
  quantity: number; average_price: number; purchase_date: string | null;
  current_price: number | null; market_value: number | null; cost_basis: number | null;
  unrealized_gain: number | null; unrealized_gain_pct: number | null; weight: number | null;
}

export interface AllocationSlice { label: string; value: number; weight: number }

export interface PortfolioSummary {
  total_value: number; total_cost: number; unrealized_gain: number;
  unrealized_gain_pct: number; n_holdings: number; n_sectors: number;
  as_of: string | null;
  allocation_by_class: AllocationSlice[];
  allocation_by_sector: AllocationSlice[];
  top_holdings: Holding[];
}

export interface Transaction {
  id: number; transaction_type: string; date: string; symbol: string | null;
  quantity: number | null; price: number | null; value: number; fees: number;
}

export interface ImportRowError {
  row_number: number; field: string | null; value: string | null; message: string;
}
export interface ImportResult {
  accepted: boolean; rows_read: number; rows_imported: number;
  holdings_created: number; holdings_updated: number;
  errors: ImportRowError[]; warnings: string[];
}

export interface PerformanceSummary {
  observations: number; total_return: number; annualized_return: number;
  annualized_volatility: number; downside_deviation: number; sharpe_ratio: number;
  sortino_ratio: number; calmar_ratio: number; max_drawdown: number;
  var_95: number; cvar_95: number; beta: number; alpha: number;
  treynor_ratio: number; risk_free_rate: number; periods_per_year: number;
}

export interface Analytics {
  summary: PerformanceSummary;
  windows: Record<string, {
    total_return: number; annualized_return: number; annualized_volatility: number;
    benchmark_total_return?: number; excess_return?: number;
  }>;
  series: {
    dates: string[]; cumulative_return: number[];
    benchmark_cumulative_return: number[] | null;
  };
  assumptions: Record<string, unknown>;
}

export interface RiskReport {
  summary: PerformanceSummary;
  drawdown: {
    max_drawdown: number; current_drawdown: number | null;
    peak_date: string | null; trough_date: string | null; recovery_date: string | null;
    recovered: boolean; drawdown_days: number | null;
    series: { dates: string[]; drawdown: number[] };
  };
  correlation: { symbols: string[]; matrix: (number | null)[][]; average_pairwise: number };
  risk_return_scatter: {
    symbol: string; annualized_return: number; annualized_volatility: number; weight: number;
  }[];
  assumptions: Record<string, unknown>;
}

export interface Concentration {
  n_holdings: number; hhi: number; hhi_normalized: number; effective_holdings: number;
  top_1_weight: number; top_3_weight: number; top_5_weight: number;
  largest_holding: string | null; weights: Record<string, number>;
  sector_weights?: Record<string, number>; sector_hhi?: number; n_sectors?: number;
  max_sector_weight?: number; largest_sector?: string | null;
  asset_class_weights?: Record<string, number>;
  average_pairwise_correlation: number | null;
  interpretation: string[];
}

export interface Goal {
  id: number; name: string; goal_type: string; target_amount: number;
  current_amount: number; target_date: string; monthly_contribution: number;
  status: string; priority: number; progress_fraction: number;
}

export interface GoalForecast {
  goal_id: number; name: string; target_amount: number; current_amount: number;
  monthly_contribution: number; target_date: string; months_remaining: number;
  projected_value: number; funding_ratio: number; shortfall: number; on_track: boolean;
  progress_ratio: number; required_monthly_contribution: number; contribution_gap: number;
  assumptions: Record<string, never> & Record<string, unknown>;
  scenarios: Record<string, {
    annual_return: number; projected_value: number;
    funding_ratio: number | null; shortfall: number;
  }>;
  path: { months: number[]; projected_value: number[]; target: number };
}

export interface HealthComponent {
  name: string; score: number | null; weight: number;
  contribution: number; inputs: Record<string, unknown>; reason: string;
}
export interface HealthScore {
  total: number | null; grade: string; summary: string; missing_inputs: string[];
  components: HealthComponent[]; methodology: string;
  weights: Record<string, number>;
  sensitivity?: {
    input: string; baseline_value: number; swing: number;
    direction: string; saturated?: boolean;
  }[];
  context: Record<string, unknown>;
  methodology_version?: string;
  version_comparison?: { v1_total: number | null; v2_total: number | null; difference: number | null; note: string };
}

export interface InvestorProfile {
  available: boolean; reason?: string;
  cluster?: number; cluster_name?: string; cluster_size?: number; cluster_share?: number;
  match_confidence?: number;
  distinguishing_traits?: { highest: { feature: string; z: number }[]; lowest: { feature: string; z: number }[] };
  investor_features?: Record<string, number>;
  largest_differences_from_cluster?: { feature: string; investor: number; cluster_average: number }[];
  stated_risk_tolerance?: string | null; method?: string; caveat?: string;
  feature_provenance?: {
    sources: Record<string, "observed" | "reconstructed" | "unavailable">;
    confidence: number; confidence_basis: string; note: string;
    observed_feature_count: number; observable_feature_count: number;
  };
}

export interface AnomalyReport {
  available: boolean; reason?: string;
  threshold?: number; months_examined?: number; anomalies_found?: number;
  anomalies?: {
    date: string; score: number; threshold: number; severity: string;
    contributing_features: { feature: string; value: number }[];
  }[];
  timeline?: { date: string; score: number; is_anomaly: boolean }[];
  method?: string; caveat?: string;
}

export interface Forecast {
  available: boolean; reason?: string;
  horizon_months?: number; current_value?: number; monthly_contribution?: number;
  baseline_value?: number; projected_value?: number;
  projected_growth_over_baseline?: number;
  projection_range?: { low: number; high: number; log_growth_spread: number; agreement: string };
  model_predictions?: Record<string, { excess_log_growth: number; projected_value: number }>;
  models_used?: string[];
  assumptions?: Record<string, string>;
  recommendation?: {
    recommended_source: string; model_beats_baseline: boolean;
    walk_forward_mean_skill: number | null; note: string;
  };
}

export interface ModelStatus {
  available: Record<string, boolean>; all_loaded: boolean;
  failures: Record<string, string>; model_dir: string;
}

export interface ChatTurn { role: "user" | "assistant"; content: string }

export interface CopilotReply {
  answer: string; model: string; used_fallback: boolean;
  fallback_reason: string | null; tools_called: string[];
  grounding: {
    numbers_checked: number; numbers_verified: number; groundedness_rate: number;
    unverified_numbers: number[]; is_grounded: boolean; tool_values_available: number;
  };
  latency_ms: number;
  usage: { input_tokens: number; output_tokens: number } | null;
  disclaimer: string;
}

export interface CopilotCapabilities {
  mode: string; model: string;
  tools: { name: string; description: string }[];
  grounding: string; limits: string[];
}

/* ──────────────── research & simulation types ──────────────── */

/** Reports are rendered defensively: the pages read what they need and show
 *  an explicit "not available" panel when a stage has not been run. Typing
 *  every nested field would be a maintenance cost for no safety gain, so
 *  each report is loosely typed with the fields the pages actually index. */
export interface Report {
  available: boolean;
  reason?: string;
  [key: string]: unknown;
}

export interface ResearchReports {
  models: Record<string, Report>;
  data: Record<string, Report>;
}

export interface ClusterMapPoint {
  pc1: number; pc2: number; cluster: number;
  cluster_name: string; archetype: string;
}

export interface SimulationOverrides {
  monthly_contribution?: number;
  annual_return?: number;
  annual_volatility?: number;
  months?: number;
}

export interface SimulationInputs {
  monthly_contribution: number;
  annual_return: number;
  annual_volatility: number;
  months: number;
}

export interface Simulation {
  goal_id: number; name: string;
  target_amount: number; current_amount: number; months: number;
  inputs: SimulationInputs;
  defaults: SimulationInputs;
  bounds: Record<string, [number, number]>;
  deterministic: { months: number[]; projected_value: number[]; final_value: number };
  monte_carlo: {
    months: number[];
    percentiles: Record<string, number[]>;
    final_values: Record<string, number>;
    success_probability: number | null;
    n_paths: number;
    assumptions: Record<string, string | number>;
  };
  success_probability: number | null;
  required_monthly_contribution: number;
  funding_ratio: number;
  on_track: boolean;
  return_estimate: Record<string, unknown>;
}
