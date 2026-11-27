import { V1, del, post, q, request } from "./http";
import type { Backtest, FieldInfo, Ideas, SavedScreen, ScreenDefinition, ScreenInfo, ScreenResult, Strategy } from "./types";

export const screeners = {
  list: () => request<{ screens: ScreenInfo[]; fields: FieldInfo[] }>(`${V1}/screeners`),
  run: (id: string, limit = 50) => request<ScreenResult>(`${V1}/screeners/run/${id}${q({ limit })}`),
  runCustom: (definition: ScreenDefinition) => post<ScreenResult>(`${V1}/screeners/run`, definition),
  saved: () => request<{ screens: SavedScreen[] }>(`${V1}/screeners/saved`),
  save: (name: string, definition: ScreenDefinition) => post<SavedScreen>(`${V1}/screeners/saved`, { name, definition }),
  runSaved: (id: number) => request<ScreenResult>(`${V1}/screeners/saved/${id}/run`),
  deleteSaved: (id: number) => del(`${V1}/screeners/saved/${id}`),
};

export const ideas = {
  recommendations: (kind: "intraday" | "delivery" | "fno" | "model", limit = 8) =>
    request<Ideas>(`${V1}/ideas/recommendations${q({ kind, limit })}`),
  strategies: (style?: string) => request<{ strategies: Strategy[] }>(`${V1}/ideas/strategies${q({ style })}`),
  backtest: (id: string, symbol?: string | null) => request<Backtest>(`${V1}/ideas/backtest/${id}${q({ symbol })}`),
};
