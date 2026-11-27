import { V1, post, q, request } from "./http";
import type { Leaderboard, PaperOrder, Regime, Signals, SwingPlan, SwingReports, SymbolSignal } from "./types";

/** The trained swing models: today's signals, the regime, the swing plan and the forward test. */
export const signals = {
  list: (limit = 20) => request<Signals>(`${V1}/signals${q({ limit })}`),
  symbol: (symbol: string) => request<SymbolSignal>(`${V1}/signals/${encodeURIComponent(symbol)}`),
  regime: () => request<Regime>(`${V1}/signals/regime`),
  leaderboard: () => request<Leaderboard>(`${V1}/signals/leaderboard`),
  plan: (amount: number) => post<SwingPlan>(`${V1}/advisor/swing-plan`, { amount }),
  execute: (positions: { symbol: string; quantity: number }[]) =>
    post<{ orders: PaperOrder[] }>(`${V1}/advisor/swing-plan/execute`, { positions }),
  reports: () => request<SwingReports>(`${V1}/research/swing`),
};
