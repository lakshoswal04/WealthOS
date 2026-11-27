import { V1, post, q, request } from "./http";
import type { CalendarEvent, Commodity, NewsItem, PairAnalysis, PairHit, Payoff, PayoffLeg, StockEvents } from "./types";

export const research = {
  news: (symbol?: string | null, limit = 40) =>
    request<{ items: NewsItem[]; source: string; count: number }>(`${V1}/markets/news${q({ symbol, limit })}`),
  calendar: (days = 60) => request<{ events: CalendarEvent[]; days_ahead: number; source: string }>(`${V1}/markets/calendar${q({ days })}`),
  events: (symbol: string) => request<StockEvents>(`${V1}/markets/events/${encodeURIComponent(symbol)}`),
  commodities: () => request<{ commodities: Commodity[]; usd_inr: number | null; source: string; note: string }>(`${V1}/markets/commodities`),
  pair: (a: string, b: string) => request<PairAnalysis>(`${V1}/tools/pairs${q({ a, b })}`),
  pairScreen: (minCorrelation = 0.7, minAbsZ = 1.5) =>
    request<{ pairs: PairHit[]; checked: number }>(`${V1}/tools/pairs/screen${q({ min_correlation: minCorrelation, min_abs_z: minAbsZ })}`),
  payoff: (underlying: string, expiry: string | null, legs: PayoffLeg[]) =>
    post<Payoff>(`${V1}/tools/strategy/payoff`, { underlying, expiry, legs }),
  wizard: (underlying: string, view: string, expiry?: string | null) =>
    request<Payoff>(`${V1}/tools/strategy/wizard${q({ underlying, view, expiry })}`),
};
