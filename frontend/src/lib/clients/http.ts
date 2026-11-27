/** Shared request helpers for the trading clients. */

import { ApiError, request } from "@/lib/api";

export { ApiError, request };

export const V1 = "/api/v1";

export const q = (params: Record<string, string | number | boolean | null | undefined>) => {
  const parts = Object.entries(params)
    .filter(([, v]) => v !== null && v !== undefined && v !== "")
    .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  return parts.length ? `?${parts.join("&")}` : "";
};

export const post = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const put = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });

export const patch = <T,>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });

export const del = <T = void,>(path: string) => request<T>(path, { method: "DELETE" });

/**
 * Why data is missing, as the API reports it. `upstox_required` means the
 * user can fix it by connecting or re-logging into Upstox; the action says how.
 */
export interface Unavailable {
  message: string;
  code: "upstox_required" | "market_data_unavailable" | "models_unavailable" | "error";
  state?: string;
  action?: { label: string; href: string };
}

export function unavailableFrom(err: unknown): Unavailable {
  if (err instanceof ApiError) {
    const body = (err.body ?? {}) as { code?: string; state?: string; action?: { label: string; href: string } };
    if (body.code === "upstox_required" || body.code === "market_data_unavailable" || body.code === "models_unavailable") {
      return { message: err.message, code: body.code, state: body.state, action: body.action };
    }
  }
  return { message: (err as Error)?.message ?? "Something went wrong.", code: "error" };
}
