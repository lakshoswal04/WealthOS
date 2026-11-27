import { V1, q, request } from "./http";
import type { Candles, Instrument, MarketStatus, Quote } from "./types";

export const market = {
  status: () => request<MarketStatus>(`${V1}/markets/status`),
  indices: () => request<{ market: MarketStatus; indices: Quote[] }>(`${V1}/markets/indices`),
  quote: (symbol: string) => request<Quote>(`${V1}/markets/quote/${encodeURIComponent(symbol)}`),
  quotes: (symbols: string[]) =>
    request<{ quotes: Quote[]; unavailable: string[] }>(`${V1}/markets/quotes${q({ symbols: symbols.join(",") })}`),
  movers: (kind: "gainers" | "losers" | "movers", limit = 10) =>
    request<{ kind: string; stocks: Quote[]; market: MarketStatus }>(`${V1}/markets/movers${q({ kind, limit })}`),
  candles: (symbol: string, interval: string, range: string) =>
    request<Candles>(`${V1}/markets/candles/${encodeURIComponent(symbol)}${q({ interval, range })}`),
  search: (text: string) => request<{ results: Instrument[] }>(`${V1}/markets/search${q({ q: text })}`),
  universe: () => request<{ indices: Instrument[]; stocks: Instrument[] }>(`${V1}/markets/universe`),
};
