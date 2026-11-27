/**
 * Types for the trading surfaces.
 *
 * Every price carries a `source`: "live" is the user's own Upstox session,
 * "delayed" is Yahoo Finance (about fifteen minutes behind NSE). There is no
 * simulated data anywhere; missing data arrives as an API error with a reason.
 */

export type PriceSource = "live" | "delayed" | "unavailable" | "settlement" | "expired";

/* ── markets ── */
export interface Quote {
  symbol: string; name: string; kind: "index" | "equity"; sector: string | null;
  ltp: number; prev_close: number; change: number; change_pct: number;
  open: number; high: number; low: number; volume: number;
  source: PriceSource; as_of: string;
}
export interface MarketStatus {
  is_open: boolean; label: string; session_date: string; minute_of_session: number; as_of: string;
  price_source?: "live" | "delayed";
  upstox?: { connected: boolean; state: string; reason: string | null };
}
export interface Bar { time: number; open: number; high: number; low: number; close: number; volume: number; oi?: number }
export interface Candles {
  symbol: string; interval: string; range: string; range_clamped_to_days: number | null;
  source: PriceSource; bars: Bar[]; as_of: string;
}
export interface Instrument { symbol: string; name: string; kind: "index" | "equity"; sector: string }

/* ── options ── */
export interface OptionLeg {
  instrument_key: string | null; ltp: number; change: number; change_pct: number; iv: number;
  delta: number; gamma: number; theta: number; vega: number;
  oi: number; oi_change: number; volume: number; bid: number; ask: number;
}
export interface ChainRow { strike: number; ce: OptionLeg; pe: OptionLeg }
export interface OptionChain {
  underlying: string; expiry: string; expiries: string[]; spot: number; spot_change_pct: number | null;
  atm_strike: number; atm_iv: number | null; lot_size: number; strike_step: number | null;
  change_basis: string;
  total_call_oi: number; total_put_oi: number; total_call_oi_change: number; total_put_oi_change: number;
  pcr: number | null; max_pain: number; resistance: number | null; support: number | null;
  rows: ChainRow[]; source: "live"; note: string; as_of: string;
}
export interface OptionSummary {
  underlying: string; expiry: string; spot: number; spot_change_pct: number | null;
  atm_strike: number; atm_iv: number | null; pcr: number | null; max_pain: number;
  support: number | null; resistance: number | null; total_call_oi: number; total_put_oi: number;
  total_call_oi_change: number; total_put_oi_change: number; lot_size: number; change_basis: string;
  atm_call_premium: number; atm_put_premium: number;
  highest_call_oi: { strike: number; oi: number }[];
  highest_put_oi: { strike: number; oi: number }[];
  biggest_call_oi_addition: { strike: number; oi_change: number }[];
  biggest_put_oi_addition: { strike: number; oi_change: number }[];
  source: "live"; note: string; as_of: string;
}
export interface MultiStrikeOI {
  underlying: string; expiry: string; note: string;
  series: { strike: number; points: { time: string; ce: number | null; pe: number | null }[] }[];
}
export interface OICrossovers {
  underlying: string; expiry: string; spot: number; strikes_checked: number; interval: string; method: string;
  crossovers: { strike: number; time: string; direction: "puts_overtook_calls" | "calls_overtook_puts"; call_oi: number; put_oi: number }[];
}
export interface UnusualActivity {
  method: string;
  contracts: { symbol: string; underlying: string; expiry: string; strike: number; option_type: "CE" | "PE";
    ltp: number; change_pct: number; volume: number; oi: number; volume_to_oi: number; oi_change_pct: number | null }[];
}
export interface OptionCandles {
  symbol: string; underlying: string; expiry: string; strike: number; option_type: "CE" | "PE";
  interval: string; range: string; bars: Bar[]; lot_size: number; source: "live";
}
export interface Contract {
  symbol: string; underlying: string; expiry: string; ltp: number; change_pct: number;
  strike?: number; option_type?: "CE" | "PE"; oi?: number; volume?: number; lot_size?: number;
}
export interface Heatmap {
  source: PriceSource; priced: number; universe: number;
  groups: { sector: string; change_pct: number; stocks: { symbol: string; change_pct: number; ltp: number }[] }[];
}

/* ── screeners ── */
export interface ScreenFilter { field: string; op: string; value?: number | number[]; value_field?: string }
export interface ScreenDefinition { filters: ScreenFilter[]; sort?: { field: string; dir: "asc" | "desc" }; limit?: number }
export interface ScreenInfo {
  id: string; name: string; group: "technicals" | "fundamentals" | "candlestick";
  category: string; description: string; filters: ScreenFilter[];
  sort: { field: string; dir: "asc" | "desc" }; columns: string[]; field_labels: string[];
}
export interface FieldInfo { field: string; label: string; group: string; type: "number" | "boolean" }
export interface SavedScreen { id: number; name: string; definition: ScreenDefinition; created_at: string | null }
export interface ScreenResult {
  available: boolean; reason?: string; count: number; universe_size: number;
  columns?: string[]; results: (Record<string, number | string | boolean | null> & { symbol: string; name: string; sector: string | null })[];
  definition?: ScreenDefinition; data_source?: string; price_source?: string; as_of?: string;
  screen?: ScreenInfo; saved?: SavedScreen;
}

/* ── ideas ── */
export interface EquityIdea {
  id: string; kind: "intraday" | "delivery" | "model"; instrument: "equity"; symbol: string; name: string;
  sector: string; side: "buy" | "sell"; ltp: number; change_pct: number | null;
  entry: number; stop_loss: number; target: number; risk_reward: number; atr: number | null;
  horizon: string; rationale: string[]; method: string; price_source: PriceSource;
  /** Present on model ideas: the swing ensemble's view. */
  model?: { score: number; percentile: number; range_10d: SignalRange | null; recommended: boolean };
}
export interface StrategyLeg { action: "buy" | "sell"; strike: number; option_type: "CE" | "PE"; premium: number; expiry: string }
export interface FnoIdea {
  id: string; kind: "fno"; instrument: "option_strategy"; symbol: string; name: string;
  bias: string; strategy: string; expiry: string; spot: number; lot_size: number;
  legs: StrategyLeg[]; net_premium: number; net_premium_type: "credit" | "debit";
  max_profit: number; max_loss: number; expected_move: number;
  rationale: string[]; horizon: string; method: string; price_source: PriceSource;
}
export type Idea = EquityIdea | FnoIdea;
export interface Ideas { kind: string; ideas: Idea[]; count: number; disclaimer: string; as_of: string }
export interface Strategy {
  id: string; name: string; style: "intraday" | "swing" | "positional";
  description: string; entry: string; exit: string; default_symbol: string; backtestable: boolean;
}
export interface Backtest {
  available: boolean; reason?: string; strategy: Strategy; symbol: string;
  start: string; end: string; sessions: number;
  total_return_pct: number | null; annualized_return_pct: number | null;
  max_drawdown_pct: number | null; sharpe_ratio: number | null;
  buy_and_hold_return_pct: number | null; trades: number; win_rate_pct: number | null;
  exposure_pct: number; cost_per_side_pct: number;
  equity_curve: { time: number; strategy: number; buy_and_hold: number }[];
  assumptions: string[];
}

/* ── paper trading ── */
export interface PaperRow {
  id: number; symbol: string; underlying: string; instrument: "equity" | "option";
  product: string; option_type: "CE" | "PE" | null; strike: number | null; expiry: string | null;
  quantity: number; avg_price: number; ltp: number | null; day_change_pct: number | null;
  current_value: number; invested: number; pnl: number | null; day_pnl: number; pnl_pct: number | null;
  realized_pnl: number; tag: string; tag_label: string; price_source: PriceSource; price_note?: string;
  lot_size: number; name?: string; sparkline?: number[];
}
export interface PaperPortfolio {
  mode: "paper"; cash: number; margin_used: number; available: number; starting_cash: number;
  total_value: number; total_return: number; total_return_pct: number; realized_pnl: number;
  holdings_value: number; holdings_invested: number; holdings_pnl: number; holdings_pnl_pct: number;
  positions_pnl: number; day_change: number; day_change_pct: number;
  holdings: PaperRow[]; positions: PaperRow[];
  weekly_activity: { date: string; weekday: string; orders: number }[];
  unpriced: { symbol: string; reason: string }[];
  options_feed: { connected: boolean; reason: string | null };
  as_of: string;
}
export interface PaperOrder {
  id: number; symbol: string; instrument: "equity" | "option"; underlying: string;
  option_type: "CE" | "PE" | null; strike: number | null; expiry: string | null;
  side: "buy" | "sell"; quantity: number; order_type: "market" | "limit";
  limit_price: number | null; product: string;
  status: "open" | "filled" | "cancelled" | "rejected"; fill_price: number | null;
  reject_reason: string | null; tag: string; tag_label: string; price_source: string | null;
  created_at: string | null; filled_at: string | null;
}
export interface OrderRequest {
  instrument: "equity" | "option"; symbol: string; side: "buy" | "sell";
  quantity?: number | null; lots?: number | null; order_type?: "market" | "limit";
  limit_price?: number | null; product?: "delivery" | "intraday" | null;
  option_type?: "CE" | "PE" | null; strike?: number | null; expiry?: string | null; tag?: string;
}
export interface AutopilotBasket {
  amount: number; invested: number; uninvested: number; method: string; disclaimer: string;
  basket: { symbol: string; name: string; sector: string; ltp: number; quantity: number; cost: number; price_source: PriceSource;
    rank?: number; weight?: number; stop?: number | null; target?: number | null }[];
  notes?: string[];
  requires_confirmation?: boolean;
}

/* ── chat ── */
export interface OrderProposal {
  requires_confirmation: true;
  order: {
    instrument: "equity" | "option"; symbol: string; display_symbol: string; side: "buy" | "sell";
    quantity: number; lots: number | null; lot_size: number | null; option_type: "CE" | "PE" | null;
    strike: number | null; expiry: string | null; order_type: "market" | "limit";
    limit_price: number | null; product: string;
  };
  ltp: number; estimated_value: number; cash_available: number; price_source: PriceSource; note: string;
}
export type ChatCard =
  | ({ type: "order_proposal" } & OrderProposal)
  | ({ type: "autopilot_proposal" } & AutopilotBasket)
  | ({ type: "backtest" } & Backtest)
  | ({ type: "screener"; screen: { id: string; name: string; description: string }; matches: number; universe_size: number; results: ScreenResult["results"] })
  | ({ type: "ideas" } & Ideas)
  | ({ type: "option_summary" } & OptionSummary)
  | ({ type: "quote" } & Quote)
  | ({ type: "movers"; kind: string; market: MarketStatus; indices: Pick<Quote, "symbol" | "ltp" | "change" | "change_pct" | "source">[]; stocks: Pick<Quote, "symbol" | "name" | "sector" | "ltp" | "change_pct">[] })
  | ({ type: "swing_plan" } & SwingPlan)
  | ({ type: "model_signals" } & (Signals | SymbolSignal))
  | ({ type: "allocation" } & AllocationPlan)
  | ({ type: "portfolio_review" } & PortfolioReview)
  | ({ type: "autopilot_status" } & AutopilotStatus);
export interface ChatMessage {
  id: number; role: "user" | "assistant"; content: string; cards: ChatCard[];
  meta: {
    model?: string; used_fallback?: boolean; fallback_reason?: string | null; tools_called?: string[];
    grounding?: { is_grounded: boolean; numbers_checked: number; unverified_numbers: number[] };
    latency_ms?: number; disclaimer?: string; remembered?: { id: number; section: string; text: string }[];
  };
  created_at: string | null;
}
export interface ChatThread {
  id: number; title: string; context: { symbol?: string } | null;
  created_at: string | null; updated_at: string | null; messages?: ChatMessage[];
}

/* ── account ── */
export interface Preferences {
  default_symbol: string; default_quantity: number; default_lots: number;
  default_product: "delivery" | "intraday"; default_order_type: "market" | "limit";
  one_tap_default: boolean; chart_interval: string; confirm_ai_orders: true;
}
export interface Notifications { order_fills: boolean; price_alerts: boolean; portfolio_alerts: boolean }
export interface UserSettings { preferences: Preferences; notifications: Notifications; memory_paused: boolean; delivery_note: string }
export interface MemoryItem { id: number; section: string; text: string; source: "manual" | "chat"; created_at: string | null }
export interface MemoryState { paused: boolean; sections: Record<string, string>; memories: MemoryItem[] }
export type BrokerState = "connected" | "expired" | "not_connected" | "no_credentials";
export interface BrokerStatus {
  broker: "upstox" | "zerodha" | "groww" | "dhan"; name: string; supported: boolean; reason?: string;
  credentials_saved?: boolean; api_key_hint?: string | null; state?: BrokerState; display_name?: string | null;
  token_expires_at?: string | null; last_successful_sync_at?: string | null; redirect_uri?: string; places_orders?: false;
}
export interface SyncResult {
  run: { status: string; holdings_seen: number; holdings_created: number; holdings_updated: number;
    error_kind: string | null; error_message: string | null; details: { unknown_symbols_skipped?: number } };
}

/* ── research tools ── */
export interface NewsItem { id: string; symbol: string; title: string; summary: string; publisher: string | null; url: string; published_at: string | null }
export interface CalendarEvent { symbol: string; name: string; event: "earnings" | "ex_dividend" | "dividend_payment"; date: string; detail: string | null }
export interface StockEvents {
  symbol: string; name: string; dividends: { date: string; amount: number }[];
  splits: { date: string; ratio: number }[]; upcoming: Omit<CalendarEvent, "name">[];
}
export interface Commodity {
  ticker: string; name: string; venue: string; unit: string; price: number; change: number; change_pct: number;
  inr_reference?: { value: number; unit: string };
}
export interface PairAnalysis {
  a: string; b: string; sessions: number; correlation: number; hedge_ratio: number; z_score: number;
  half_life_days: number | null; z_window: number; ratio: number; signal: string; method: string;
  series: { date: string; ratio: number; z: number | null }[];
}
export interface PairHit { a: string; b: string; sector: string; correlation: number; z_score: number }
export interface PayoffLeg { option_type: "CE" | "PE"; strike: number; action: "buy" | "sell"; lots: number; premium?: number; iv?: number | null; quantity?: number }
export interface Payoff {
  underlying: string; expiry: string; spot: number; lot_size: number; legs: PayoffLeg[];
  net_premium: number; net_premium_type: "credit" | "debit"; max_profit: number | null; max_loss: number | null;
  breakevens: number[]; curve: { spot: number; expiry: number; today: number | null }[]; method: string;
  view?: string; strategy?: string; expected_move?: number; sizing?: string;
}
export interface PromptBook {
  lang: "en" | "hi";
  hero: { eyebrow: string; title_1: string; title_2a: string; title_2b: string; title_2c: string; title_3: string; lede: string };
  chapters: { slug: string; number: number; level: number; icon: string; title: string; badge: string; summary: string;
    principles: string[]; examples: { prompt: string; tool: string }[]; vague: { prompt: string; why: string }[] }[];
}

/* ── swing models ── */
export type RegimeState = "calm" | "normal" | "stress";
export interface RegimeProbabilities { calm: number; normal: number; stress: number }
export interface Regime {
  available: boolean; reason?: string; as_of?: string; state?: RegimeState;
  probabilities?: RegimeProbabilities; base_exposure?: number;
  exposure_map?: Record<RegimeState, number>; trained_through?: string; method?: string;
  history?: ({ date: string } & RegimeProbabilities)[] | null; disclaimer?: string;
}
export interface ModelCard {
  deployed: string; version: string | null; feature_version: string | null; trained_through: string | null;
  recommended: boolean; volatility_model: string | null; horizon_sessions: number; universe: string;
  oos: {
    first_test_year: number | null; mean_ic: number | null; t_stat: number | null; hit_rate: number | null;
    top_decile_positive: number | null; cagr: number | null; max_drawdown: number | null; sharpe: number | null;
    equal_weight_cagr: number | null; equal_weight_max_drawdown: number | null;
  };
}
export interface SignalDriver { feature: string; label: string; percentile: number | null; effect: "raises" | "lowers"; weight?: number }
export interface SignalRange { low: number | null; mid: number | null; high: number | null; coverage: number }
export interface SignalPick {
  symbol: string; name: string; sector: string; score: number; rank: number; of: number; percentile: number;
  last_close: number; range_10d: SignalRange | null; vol_annual: number | null; vol_10d: number | null;
  stop: number | null; target: number | null; drivers: SignalDriver[]; models?: Record<string, number | null>;
}
export interface RiskProfileInfo {
  name: string; max_names: number; max_weight: number; vol_target: number; max_exposure: number;
  stop_multiple: number; target_multiple: number; regime_floor: number;
}
export interface Signals {
  as_of: string; horizon_sessions: number; universe_size: number; profile: RiskProfileInfo;
  regime: Regime; model: ModelCard; picks: SignalPick[]; price_source: string; disclaimer: string;
}
export type SymbolSignal =
  | ({ eligible: true; as_of: string; model: ModelCard; disclaimer: string } & SignalPick)
  | { eligible: false; symbol: string; reason: string; as_of: string; model: ModelCard; disclaimer: string };
export interface SwingPlanPosition {
  symbol: string; name: string; sector: string; rank: number; of: number; score: number;
  range_10d: SignalRange | null; vol_annual: number | null; drivers: SignalDriver[];
  weight: number; price: number; price_source: string; quantity: number; cost: number;
  stop: number | null; target: number | null;
}
export interface SwingPlan {
  as_of: string; amount: number; profile: RiskProfileInfo; regime: Regime; exposure: number;
  vol_scale: number; forecast_portfolio_vol: number; invested: number; cash_reserve: number;
  positions: SwingPlanPosition[]; notes: string[]; model: ModelCard; disclaimer: string;
  requires_confirmation?: boolean;
}
export interface CurvePoint { date: string; value: number }
export interface LeaderboardRow {
  model_id: string; label: string; version?: string; signal_days?: number; total_return: number | null;
  sessions: number; max_drawdown: number | null; volatility: number | null; curve: CurvePoint[];
  holdings?: [string, number][];
}
export interface Leaderboard {
  started_on: string | null; sessions: number; rules?: string; models: LeaderboardRow[];
  benchmarks?: LeaderboardRow[]; note?: string | null; disclaimer?: string;
}
/** The pipeline's swing reports, loosely typed: they are read-only evidence. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type SwingReport = { available: boolean; reason?: string; [key: string]: any };
export type SwingReports = Record<
  "history_fetch" | "swing_features" | "swing_ranker" | "swing_volatility" | "swing_regime" |
  "swing_deep" | "swing_portfolio" | "swing_model_card", SwingReport>;

/* ── autopilot, review, allocation ── */
export interface AutopilotSettings {
  enabled: boolean; budget: number; cadence_sessions: number; avoid_symbols: string[]; avoid_sectors: string[];
  sleeve: Record<string, number>; sleeve_cash: number | null; last_run_on: string | null;
}
export interface AutopilotOrder {
  symbol: string; side: "buy" | "sell"; quantity: number; price: number; value: number; reason: string;
  price_source?: string; fill_price?: number; error?: string;
}
export interface AutopilotRun {
  id: number; run_on: string; mode: "auto" | "manual"; status: "done" | "partial" | "failed";
  regime: Regime | null; target: { symbol: string; sector?: string; rank?: number; weight?: number; value?: number; quantity?: number }[] | null;
  orders: AutopilotOrder[] | null; notes: string[] | null; sleeve_value: number | null; created_at: string | null;
}
export interface AutopilotStatus {
  settings: AutopilotSettings; holdings: { symbol: string; quantity: number; price: number | null; value: number | null; price_source: string }[];
  sleeve_value: number; pnl: number; pnl_pct: number | null; next_run_in_sessions: number | null;
  runs: AutopilotRun[]; disclaimer: string;
}
export interface AutopilotPreview {
  target: { as_of: string; profile: RiskProfileInfo; exposure: number; regime: Regime; positions: (SwingPlanPosition & { value: number })[];
    excluded: { symbol: string; rank: number; reason: string }[]; notes: string[] };
  orders: AutopilotOrder[]; sleeve: Record<string, number>; sleeve_cash: number; sleeve_value: number;
}
export interface AllocationPick {
  sector: string; symbol: string; name: string; rank: number; of: number; weight: number; price: number | null;
  price_source: string; quantity: number; cost: number | null; range_10d: SignalRange | null;
  stop: number | null; target: number | null; already_held: boolean; why: string[];
}
export interface AllocationPlan {
  available?: boolean; reason?: string;
  amount: number; horizon: "swing" | "long_term"; as_of: string; profile: RiskProfileInfo; regime: Regime;
  sectors_requested: string[] | null; core: { symbol: string; what: string; weight: number; value: number; units: number | null }[];
  picks: AllocationPick[]; excluded: { symbol: string; rank: number; reason: string }[];
  invested: number; cash_left: number; suggested_exposure: number; notes: string[]; model: ModelCard; disclaimer: string;
}
export interface PortfolioReview {
  available: boolean; reason?: string; as_of?: string; profile: RiskProfileInfo; regime?: Regime;
  holdings?: {
    symbol: string; name: string; sector: string | null; asset_class: string; weight: number | null;
    market_value: number | null; gain_pct: number | null; risk_contribution: number | null;
    model: { rank: number; of: number; percentile: number; range_10d: SignalRange | null; vol_annual: number | null; drivers: SignalDriver[] } | null;
    model_note?: string;
  }[];
  sector_weights?: Record<string, number>; equity_risk_estimate?: number | null;
  suggestions?: { symbol: string | null; kind: string; text: string }[]; note?: string; disclaimer?: string;
}
