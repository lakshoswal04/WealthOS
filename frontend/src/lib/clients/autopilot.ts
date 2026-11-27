import { V1, post, request } from "./http";
import type { AllocationPlan, AutopilotPreview, AutopilotRun, AutopilotSettings, AutopilotStatus, PaperOrder, PortfolioReview } from "./types";

/** Autopilot (a model-run paper sleeve), the review of real holdings, and amount planning. */
export const autopilot = {
  status: () => request<AutopilotStatus>(`${V1}/autopilot`),
  update: (body: Partial<Pick<AutopilotSettings, "enabled" | "budget" | "cadence_sessions" | "avoid_symbols" | "avoid_sectors">>) =>
    request<AutopilotSettings>(`${V1}/autopilot/settings`, { method: "PUT", body: JSON.stringify(body) }),
  preview: () => request<AutopilotPreview>(`${V1}/autopilot/preview`),
  run: () => post<AutopilotRun>(`${V1}/autopilot/run`, {}),
  stop: (sell = true) => post<{ settings: AutopilotSettings; orders: PaperOrder[] }>(`${V1}/autopilot/stop?sell=${sell}`, {}),
  runs: (limit = 20) => request<{ runs: AutopilotRun[] }>(`${V1}/autopilot/runs?limit=${limit}`),
  review: () => request<PortfolioReview>(`${V1}/portfolio/review`),
  allocate: (amount: number, sectors: string[] | null, horizon: "swing" | "long_term") =>
    post<AllocationPlan>(`${V1}/advisor/allocate`, { amount, sectors, horizon }),
};
