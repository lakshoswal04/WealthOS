import { V1, q, request } from "./http";
import type { Contract, Heatmap, MultiStrikeOI, OICrossovers, OptionCandles, OptionChain, OptionSummary, UnusualActivity } from "./types";

export const options = {
  expiries: (underlying: string) =>
    request<{ underlying: string; expiries: string[]; lot_size: number }>(`${V1}/options/expiries/${underlying}`),
  chain: (underlying: string, expiry?: string | null, strikes = 15) =>
    request<OptionChain>(`${V1}/options/chain/${underlying}${q({ expiry, strikes })}`),
  summary: (underlying: string, expiry?: string | null) =>
    request<OptionSummary>(`${V1}/options/summary/${underlying}${q({ expiry })}`),
  multiStrike: (underlying: string, strikes: number[], expiry?: string | null) =>
    request<MultiStrikeOI>(`${V1}/options/multi-strike/${underlying}${q({ strikes: strikes.join(","), expiry })}`),
  crossovers: (underlying: string, expiry?: string | null) =>
    request<OICrossovers>(`${V1}/options/crossovers/${underlying}${q({ expiry })}`),
  unusual: (limit = 20) => request<UnusualActivity>(`${V1}/options/unusual${q({ limit })}`),
  candles: (underlying: string, strike: number, optionType: "CE" | "PE", expiry: string | null, interval: string) =>
    request<OptionCandles>(`${V1}/options/candles/${underlying}${q({ strike, option_type: optionType, expiry, interval })}`),
  top: (segment: "options" | "futures", kind: "gainers" | "losers" | "movers", limit = 10) =>
    request<{ segment: string; kind: string; contracts: Contract[]; note: string }>(`${V1}/options/top${q({ segment, kind, limit })}`),
  heatmap: () => request<Heatmap>(`${V1}/options/heatmap`),
};
