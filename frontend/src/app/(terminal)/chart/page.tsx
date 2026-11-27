"use client";

import clsx from "clsx";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Logo } from "@/components/trade/app-shell";
import { CandleChart, type CandleChartHandle, type Overlays, type PriceLineSpec } from "@/components/trade/candle-chart";
import { useOrderTicket } from "@/components/trade/order-ticket";
import { Change, DataUnavailable, Icon, Loading, SourceTag } from "@/components/trade/primitives";
import {
  AIPanel, AlertsPanel, ChainPanel, INDEX_KEYS, OIPanel, PositionsPanel, StrategiesPanel, WatchlistPanel, usePriceAlerts,
} from "@/components/trade/terminal-panels";
import { useSettings } from "@/components/trade/settings-context";
import { readToken } from "@/lib/viz";
import { useDismiss, usePoll } from "@/lib/hooks";
import { trade, type Instrument, type OptionChain } from "@/lib/trade-api";
import { inrSigned, num, shortExpiry, tone } from "@/lib/tfmt";

const RANGES = ["1D", "5D", "1M", "3M", "1Y"] as const;
const INTERVALS = ["1m", "5m", "15m", "1h", "1D"] as const;
type Range = (typeof RANGES)[number];
type Interval = (typeof INTERVALS)[number];
type PanelKey = "ai" | "watchlist" | "chain" | "alerts" | "strategies" | "positions" | "oi";

/** A sensible bar size for each range; Yahoo serves 1m bars for 7 days only. */
const DEFAULT_INTERVAL: Record<Range, Interval> = { "1D": "1m", "5D": "5m", "1M": "1h", "3M": "1D", "1Y": "1D" };

export default function ChartPage() {
  return <Suspense fallback={<div className="p-8"><Loading /></div>}><Terminal /></Suspense>;
}

function Terminal() {
  const params = useSearchParams();
  const router = useRouter();
  const { settings } = useSettings();
  const symbol = (params.get("symbol") ?? settings?.preferences.default_symbol ?? "NIFTY").toUpperCase();
  const isIndex = INDEX_KEYS.includes(symbol);

  const [mode, setMode] = useState<"simple" | "pro">("simple");
  const [range, setRange] = useState<Range>("1D");
  const [interval, setInterval] = useState<Interval>("1m");
  const [kind, setKind] = useState<"candles" | "line">("candles");
  const [overlays, setOverlays] = useState<Overlays>({});
  const [layers, setLayers] = useState({ oi: true, prevClose: true, maxPain: false });
  const [showOptions, setShowOptions] = useState(true);
  const [panes, setPanes] = useState({ CE: true, PE: true });
  const [expiry, setExpiry] = useState<string | null>(null);
  const [oneTap, setOneTap] = useState(false);
  const prefsApplied = useRef(false);
  useEffect(() => {
    if (!settings || prefsApplied.current) return;
    prefsApplied.current = true;
    setOneTap(settings.preferences.one_tap_default);
    const iv = settings.preferences.chart_interval as Interval;
    if (INTERVALS.includes(iv)) setInterval(iv);
  }, [settings]);
  const [hideMoney, setHideMoney] = useState(false);
  const [panel, setPanel] = useState<PanelKey | null>("ai");
  const [toast, setToast] = useState<string | null>(null);
  const chartRef = useRef<CandleChartHandle>(null);

  useEffect(() => { setExpiry(null); }, [symbol]);
  useEffect(() => { if (!toast) return; const id = window.setTimeout(() => setToast(null), 4000); return () => window.clearTimeout(id); }, [toast]);

  const quote = usePoll(() => trade.quote(symbol), 10_000, [symbol]);
  const candles = usePoll(() => trade.candles(symbol, interval, range), interval === "1D" ? 120_000 : 15_000, [symbol, interval, range]);
  const chain = usePoll<OptionChain | null>(() => isIndex ? trade.chain(symbol, expiry, 25) : Promise.resolve(null), 30_000, [symbol, expiry, isIndex]);
  const pf = usePoll(() => trade.paperPortfolio(), 20_000);
  const { alerts, persist } = usePriceAlerts((a, p) => {
    if (settings?.notifications.price_alerts !== false) setToast(`Alert: ${a.symbol} is ${a.dir} ${num(a.price)} (now ${num(p)})`);
  });

  useEffect(() => {
    const on = () => void pf.reload();
    window.addEventListener("paper-order", on);
    return () => window.removeEventListener("paper-order", on);
  }, [pf]);

  const bars = candles.data?.bars ?? [];
  const priceLines = useMemo<PriceLineSpec[]>(() => {
    const out: PriceLineSpec[] = [];
    if (layers.prevClose && quote.data) out.push({ price: quote.data.prev_close, title: "Prev close" });
    if (isIndex && chain.data && layers.oi && interval !== "1D") {
      if (chain.data.resistance != null) out.push({ price: chain.data.resistance, title: `${chain.data.resistance} CE wall`, color: readToken("down") || "#b04a33" });
      if (chain.data.support != null) out.push({ price: chain.data.support, title: `${chain.data.support} PE wall`, color: readToken("up") || "#2c6e48" });
    }
    if (isIndex && chain.data && layers.maxPain && interval !== "1D") out.push({ price: chain.data.max_pain, title: "Max pain", color: readToken("accent") || "#1f4d3a" });
    return out;
  }, [layers, quote.data, chain.data, isIndex, interval]);

  const pickRange = (r: Range) => { setRange(r); setInterval(DEFAULT_INTERVAL[r]); };
  const setSymbol = (s: string) => router.push(`/chart?symbol=${s}`);

  const ticket = useOrderTicket();
  const trade1 = async (type: "CE" | "PE", side: "buy" | "sell", strike: number, ltp: number) => {
    if (!chain.data) return;
    if (!oneTap) {
      ticket.open({ instrument: "option", symbol, side, option_type: type, strike, expiry: chain.data.expiry, quantity: 1, lot_size: chain.data.lot_size, ltp });
      return;
    }
    try {
      const o = await trade.placeOrder({ instrument: "option", symbol, side, lots: 1, option_type: type, strike, expiry: chain.data.expiry, tag: "manual" });
      if (settings?.notifications.order_fills !== false || o.status !== "filled") {
        setToast(o.status === "filled" ? `${side === "buy" ? "Bought" : "Sold"} 1 lot ${strike} ${type} at ${num(o.fill_price)}` : `Rejected: ${o.reject_reason}`);
      }
      window.dispatchEvent(new CustomEvent("paper-order", { detail: o }));
    } catch (err) { setToast((err as Error).message); }
  };

  const q = quote.data;
  const pnl = pf.data ? pf.data.day_change : null;
  const optionPanes = isIndex && showOptions && chain.data;

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-[var(--surface-0)]">
      {/* ── top bar ── */}
      <header className="flex h-16 shrink-0 items-center gap-3 border-b border-[var(--hairline)] px-4">
        <Link href="/home" aria-label="Home"><Logo size={30} /></Link>
        <div className="hidden items-center rounded-full border border-[var(--hairline-strong)] p-1 sm:flex">
          {(["simple", "pro"] as const).map((m) => (
            <button key={m} onClick={() => setMode(m)} className={clsx("rounded-full px-4 py-1.5 text-body capitalize",
              mode === m ? "bg-[var(--action)] text-[var(--action-ink)]" : "text-[var(--ink-secondary)]")}>{m}</button>
          ))}
        </div>
        <button onClick={() => setShowOptions((v) => !v)} disabled={!isIndex} title={isIndex ? "Show or hide the Call/Put panes" : "Option panes are available for indices"}
          className="hidden rounded-[var(--radius-sm)] border border-[var(--hairline-strong)] p-2 text-[var(--ink-secondary)] disabled:opacity-40 md:block">
          <Icon name="grid" size={18} />
        </button>
        <SymbolPicker symbol={symbol} onPick={setSymbol}>
          <span className="flex items-center gap-2.5 whitespace-nowrap">
            <span className="text-h3 font-semibold">{symbol}</span>
            {q && <span className="tabular text-h3 font-semibold">₹{num(q.ltp)}</span>}
            {q && <Change value={q.change_pct} className="text-body-lg" />}
            <Icon name="chevron" size={16} className="text-[var(--ink-muted)]" />
          </span>
        </SymbolPicker>

        <button onClick={() => setOneTap((v) => !v)} title="1-Tap: option Buy/Sell places one lot immediately, without the order ticket"
          className="ml-auto hidden items-center gap-3 rounded-full border border-[var(--hairline-strong)] px-4 py-2 lg:flex">
          <span className="text-body-lg font-medium">1-Tap</span>
          <span className={clsx("relative h-6 w-11 rounded-full transition-colors", oneTap ? "bg-[var(--buy)]" : "bg-[var(--surface-4)]")}>
            <span className={clsx("absolute top-1 h-4 w-4 rounded-full bg-white transition-all", oneTap ? "left-6" : "left-1")} />
          </span>
        </button>

        <div className="ml-auto flex items-center gap-1 lg:ml-6">
          <button onClick={() => setHideMoney((v) => !v)} aria-label="Hide amounts" className="rounded-full p-2.5 text-[var(--ink-secondary)] hover:bg-[var(--surface-3)]"><Icon name="eyeOff" size={19} /></button>
          <Link href="/portfolio" className="rounded-full px-3 py-2 text-body-lg text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]">Orders</Link>
          <span className="whitespace-nowrap px-2 text-body-lg text-[var(--ink-secondary)]">P&amp;L <span className={clsx("tabular", !hideMoney && tone(pnl))}>{hideMoney ? "••••" : inrSigned(pnl ?? 0)}</span></span>
          <Link href="/analysis/insights" aria-label="Alerts" className="rounded-full p-2.5 text-[var(--ink-secondary)] hover:bg-[var(--surface-3)]"><Icon name="bell" size={20} /></Link>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* ── tool rail ── */}
        <nav className="hidden w-14 shrink-0 flex-col items-center gap-1 border-r border-[var(--hairline)] py-3 md:flex">
          <RailButton icon="search" label="Search symbol (⌘K)" onClick={() => document.getElementById("symbol-picker")?.click()} />
          <RailButton icon="expand" label="Fit chart" onClick={() => chartRef.current?.fit()} />
          <RailButton icon="share" label="Download chart image" onClick={() => {
            const url = chartRef.current?.screenshot(); if (!url) return;
            const a = document.createElement("a"); a.href = url; a.download = `${symbol}-${range}-${interval}.png`; a.click();
          }} />
          <RailButton icon="candles" label="Candles / line" onClick={() => setKind((k) => k === "candles" ? "line" : "candles")} />
          <RailButton icon="layers" label="OI walls on chart" active={layers.oi} onClick={() => setLayers((l) => ({ ...l, oi: !l.oi }))} />
          <div className="mt-auto" />
          <RailButton icon="chevronLeft" label="Back to WealthOS" onClick={() => router.push("/home")} />
        </nav>

        {/* ── chart column ── */}
        <div className="flex min-w-0 flex-1 flex-col gap-3 p-3">
          <section className={clsx("flex min-h-0 flex-col rounded-[var(--radius-lg)] border border-[var(--hairline-strong)] bg-[var(--surface-1)]",
            optionPanes ? "flex-[3]" : "flex-1")}>
            <div className="flex flex-wrap items-center gap-2 border-b border-[var(--hairline)] px-4 py-2.5">
              <span className="text-body font-semibold">{symbol}</span>
              {q && <span className="tabular text-body-lg font-semibold">{num(q.ltp)}</span>}
              {q && <span className={clsx("tabular text-body", tone(q.change))}>{q.change >= 0 ? "+" : ""}{num(q.change)} ({q.change_pct >= 0 ? "+" : ""}{q.change_pct.toFixed(2)}%)</span>}
              {isIndex && chain.data && (
                <select value={expiry ?? chain.data.expiry} onChange={(e) => setExpiry(e.target.value)} aria-label="Expiry"
                  className="ml-2 rounded-[var(--radius-sm)] bg-[var(--surface-3)] px-3 py-1.5 text-body focus:outline-none">
                  {chain.data.expiries.map((e) => <option key={e} value={e}>Expiry {shortExpiry(e)}</option>)}
                </select>
              )}
              <span className="ml-auto flex items-center gap-2">
                <SourceTag source={candles.data?.source} />
                {isIndex && (
                  <div className="flex rounded-[var(--radius-sm)] bg-[var(--surface-3)] p-0.5">
                    {(["CE", "PE"] as const).map((t) => {
                      const on = showOptions && panes[t];
                      return (
                        <button key={t} aria-pressed={on} onClick={() => {
                          setShowOptions(true);
                          // Turning off the last visible pane hides the row instead.
                          setPanes((p) => (on && !p[t === "CE" ? "PE" : "CE"]) ? p : { ...p, [t]: !on });
                        }} className={clsx("rounded-[6px] px-3 py-1 text-body", on ? "bg-[var(--surface-1)] text-[var(--ink-primary)]" : "text-[var(--ink-muted)]")}>
                          {t === "CE" ? "Call" : "Put"}
                        </button>
                      );
                    })}
                  </div>
                )}
                {q?.kind === "equity" && (
                  <>
                    <button onClick={() => ticket.open({ instrument: "equity", symbol, side: "buy", ltp: q.ltp })} className="rounded-full bg-[var(--buy)] px-4 py-1.5 text-body font-semibold text-white">Buy</button>
                    <button onClick={() => ticket.open({ instrument: "equity", symbol, side: "sell", ltp: q.ltp })} className="rounded-full bg-[var(--sell)] px-4 py-1.5 text-body font-semibold text-white">Sell</button>
                  </>
                )}
                <button aria-label="Copy link" title="Copy link to this chart" onClick={() => { void navigator.clipboard?.writeText(window.location.href); setToast("Link copied"); }}
                  className="rounded-full p-1.5 text-[var(--ink-secondary)] hover:bg-[var(--surface-3)]"><Icon name="share" size={18} /></button>
                <button aria-label="Full screen" onClick={() => { if (document.fullscreenElement) void document.exitFullscreen(); else void document.documentElement.requestFullscreen?.(); }}
                  className="rounded-full p-1.5 text-[var(--ink-secondary)] hover:bg-[var(--surface-3)]"><Icon name="expand" size={18} /></button>
              </span>
            </div>

            <div className="no-scrollbar flex items-center gap-1 overflow-x-auto border-b border-[var(--hairline)] px-3 py-1.5 text-body">
              {RANGES.map((r) => <ToolTab key={r} active={range === r} onClick={() => pickRange(r)}>{r}</ToolTab>)}
              <span className="mx-2 h-5 w-px bg-[var(--hairline-strong)]" />
              {INTERVALS.map((i) => <ToolTab key={i} active={interval === i} onClick={() => setInterval(i)}>{i}</ToolTab>)}
              <span className="mx-2 h-5 w-px bg-[var(--hairline-strong)]" />
              <Dropdown label={<><Icon name="candles" size={16} /> {kind === "candles" ? "Candles" : "Line"}</>}>
                {(["candles", "line"] as const).map((k) => <MenuCheck key={k} on={kind === k} onClick={() => setKind(k)}>{k === "candles" ? "Candles" : "Line"}</MenuCheck>)}
              </Dropdown>
              <Dropdown label={<><span className="font-serif italic">fx</span> Indicators</>}>
                {([["sma20", "SMA 20"], ["sma50", "SMA 50"], ["ema9", "EMA 9"], ["ema21", "EMA 21"], ["vwap", "VWAP (session)"]] as const).map(([k, l]) => (
                  <MenuCheck key={k} on={!!overlays[k]} onClick={() => setOverlays((o) => ({ ...o, [k]: !o[k] }))}>{l}</MenuCheck>
                ))}
              </Dropdown>
              <Dropdown label={<><Icon name="layers" size={16} /> Layers</>}>
                <MenuCheck on={layers.prevClose} onClick={() => setLayers((l) => ({ ...l, prevClose: !l.prevClose }))}>Previous close</MenuCheck>
                <MenuCheck on={layers.oi} disabled={!isIndex} onClick={() => setLayers((l) => ({ ...l, oi: !l.oi }))}>OI walls (support / resistance)</MenuCheck>
                <MenuCheck on={layers.maxPain} disabled={!isIndex} onClick={() => setLayers((l) => ({ ...l, maxPain: !l.maxPain }))}>Max pain</MenuCheck>
              </Dropdown>
              <Dropdown label={<><Icon name="grid" size={16} /> Options</>}>
                <MenuCheck on={showOptions} disabled={!isIndex} onClick={() => setShowOptions((v) => !v)}>Call / Put panes</MenuCheck>
                <MenuCheck on={oneTap} onClick={() => setOneTap((v) => !v)}>1-Tap trading</MenuCheck>
              </Dropdown>
              {candles.data?.range_clamped_to_days && <span className="ml-2 whitespace-nowrap text-caption text-[var(--ink-muted)]">Yahoo limits {interval} bars to {candles.data.range_clamped_to_days} days</span>}
            </div>

            <div className="relative min-h-0 flex-1">
              {candles.loading && !candles.data ? <div className="p-6"><Loading label="Loading candles" /></div>
                : candles.failure ? <div className="p-6"><DataUnavailable failure={candles.failure} /></div>
                  : <CandleChart ref={chartRef} bars={bars} kind={kind} overlays={overlays} priceLines={priceLines}
                      volume={!isIndex} intraday={interval !== "1D"}
                      label={`${q?.name ?? symbol} · ${interval} · ${isIndex && symbol === "SENSEX" ? "BSE" : "NSE"}`} />}
            </div>
          </section>

          {isIndex && showOptions && chain.failure && (
            <div className="flex-[1.2]"><DataUnavailable failure={chain.failure} compact /></div>
          )}
          {optionPanes && chain.data && (
            <div className={clsx("grid min-h-0 gap-3", mode === "pro" ? "flex-[2]" : "flex-[1.6]",
              panes.CE && panes.PE ? "grid-cols-1 lg:grid-cols-2" : "grid-cols-1")}>
              {panes.CE && <OptionPane chain={chain.data} type="CE" interval={["1m", "5m", "15m"].includes(interval) ? interval : "5m"} onTrade={trade1} />}
              {panes.PE && <OptionPane chain={chain.data} type="PE" interval={["1m", "5m", "15m"].includes(interval) ? interval : "5m"} onTrade={trade1} />}
            </div>
          )}
        </div>

        {/* ── side panel ── */}
        {panel && (
          <aside className="hidden w-[380px] shrink-0 flex-col border-l border-[var(--hairline)] bg-[var(--surface-1)] lg:flex">
            {panel === "ai" && <AIPanel symbol={symbol} onClose={() => setPanel(null)} />}
            {panel === "watchlist" && <WatchlistPanel symbol={symbol} onPick={setSymbol} onClose={() => setPanel(null)} />}
            {panel === "chain" && (isIndex ? <ChainPanel chain={chain.data} failure={chain.failure} onClose={() => setPanel(null)} /> : <NotIndex onClose={() => setPanel(null)} what="Option chains" />)}
            {panel === "alerts" && <AlertsPanel symbol={symbol} ltp={q?.ltp ?? null} alerts={alerts} persist={persist} onClose={() => setPanel(null)} />}
            {panel === "strategies" && <StrategiesPanel symbol={symbol} onClose={() => setPanel(null)} />}
            {panel === "positions" && <PositionsPanel onPick={setSymbol} onClose={() => setPanel(null)} />}
            {panel === "oi" && (isIndex ? <OIPanel chain={chain.data} failure={chain.failure} onClose={() => setPanel(null)} /> : <NotIndex onClose={() => setPanel(null)} what="Open interest" />)}
          </aside>
        )}

        {/* ── right rail ── */}
        <nav className="hidden w-[92px] shrink-0 flex-col items-center gap-1 border-l border-[var(--hairline)] py-3 lg:flex">
          {([
            ["ai", "AI analysis", "sparkle"], ["watchlist", "Watchlist", "bookmark"], ["chain", "Option chain", "grid"],
            ["alerts", "Alerts", "alarm"], ["strategies", "Strategies", "target"], ["positions", "Positions", "briefcase"], ["oi", "OI", "bars"],
          ] as const).map(([key, label, icon]) => (
            <button key={key} onClick={() => setPanel(panel === key ? null : key)}
              className={clsx("flex w-[80px] flex-col items-center gap-1.5 rounded-[var(--radius)] py-2.5 text-caption transition-colors",
                panel === key ? "bg-[var(--surface-3)] text-[var(--ink-primary)]" : "text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]")}>
              <Icon name={icon} size={21} /> {label}
            </button>
          ))}
        </nav>
      </div>

      {toast && (
        <div role="status" className="fade fixed bottom-6 left-1/2 z-[90] -translate-x-1/2 rounded-full border border-[var(--hairline-strong)] bg-[var(--surface-2)] px-5 py-2.5 text-body shadow-[var(--lift-3)]">
          {toast}
        </div>
      )}
    </div>
  );
}

function NotIndex({ what, onClose }: { what: string; onClose: () => void }) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex justify-end p-3"><button onClick={onClose} aria-label="Close" className="text-[var(--ink-muted)]"><Icon name="x" size={16} /></button></div>
      <p className="px-5 text-body text-[var(--ink-muted)]">{what} are available for the indices: NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY and SENSEX.</p>
    </div>
  );
}

function RailButton({ icon, label, onClick, active }: { icon: string; label: string; onClick: () => void; active?: boolean }) {
  return (
    <button onClick={onClick} title={label} aria-label={label}
      className={clsx("rounded-[var(--radius-sm)] p-2.5 transition-colors", active ? "bg-[var(--surface-3)] text-[var(--ink-primary)]" : "text-[var(--ink-secondary)] hover:bg-[var(--surface-3)] hover:text-[var(--ink-primary)]")}>
      <Icon name={icon} size={20} />
    </button>
  );
}

function ToolTab({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} className={clsx("whitespace-nowrap rounded-[6px] px-2.5 py-1", active ? "bg-[var(--surface-3)] font-semibold text-[var(--ink-primary)]" : "text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]")}>
      {children}
    </button>
  );
}

function Dropdown({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss(open, close);
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen((v) => !v)} className="flex items-center gap-1.5 whitespace-nowrap rounded-[6px] px-2.5 py-1 text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]">
        {label} <Icon name="chevron" size={13} />
      </button>
      {open && (
        <div className="fade absolute left-0 top-[calc(100%+4px)] z-40 min-w-[220px] rounded-[var(--radius)] border border-[var(--hairline-strong)] bg-[var(--surface-2)] p-1.5 shadow-[var(--lift-3)]">
          {children}
        </div>
      )}
    </div>
  );
}

function MenuCheck({ on, onClick, children, disabled }: { on: boolean; onClick: () => void; children: React.ReactNode; disabled?: boolean }) {
  return (
    <button onClick={onClick} disabled={disabled}
      className="flex w-full items-center justify-between gap-4 rounded-[6px] px-3 py-2 text-left text-body hover:bg-[var(--surface-3)] disabled:opacity-40">
      {children}
      <span className={clsx("h-4 w-4 rounded border", on ? "border-[var(--accent)] bg-[var(--accent)]" : "border-[var(--hairline-strong)]")} />
    </button>
  );
}

function SymbolPicker({ symbol, onPick, children }: { symbol: string; onPick: (s: string) => void; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [results, setResults] = useState<Instrument[]>([]);
  const close = useCallback(() => setOpen(false), []);
  const ref = useDismiss(open, close);
  useEffect(() => {
    const id = window.setTimeout(() => {
      (text.trim() ? trade.search(text) : trade.universe().then((u) => ({ results: [...u.indices, ...u.stocks.slice(0, 12)] })))
        .then((r) => setResults(r.results)).catch(() => setResults([]));
    }, 120);
    return () => window.clearTimeout(id);
  }, [text, open]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen(true); } };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div ref={ref} className="relative">
      <button id="symbol-picker" onClick={() => setOpen((v) => !v)} aria-label={`Change symbol (current ${symbol})`}
        className="rounded-[var(--radius-sm)] px-2 py-1 hover:bg-[var(--surface-3)]">{children}</button>
      {open && (
        <div className="fade absolute left-0 top-[calc(100%+6px)] z-50 w-[360px] rounded-[var(--radius)] border border-[var(--hairline-strong)] bg-[var(--surface-2)] shadow-[var(--lift-3)]">
          <input autoFocus value={text} onChange={(e) => setText(e.target.value)} placeholder="Search symbol"
            onKeyDown={(e) => { if (e.key === "Enter" && results[0]) { onPick(results[0].symbol); setOpen(false); } }}
            className="w-full border-b border-[var(--hairline)] bg-transparent px-4 py-3 text-body-lg focus:outline-none" />
          <ul className="max-h-[360px] overflow-y-auto py-1">
            {results.map((r) => (
              <li key={r.symbol}>
                <button onClick={() => { onPick(r.symbol); setOpen(false); setText(""); }}
                  className="flex w-full items-center justify-between px-4 py-2 text-left hover:bg-[var(--surface-3)]">
                  <span><span className="font-semibold">{r.symbol}</span> <span className="text-small text-[var(--ink-muted)]">{r.name}</span></span>
                  <span className="text-caption text-[var(--ink-faint)]">{r.kind === "index" ? "Index" : ""}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function OptionPane({ chain, type, interval, onTrade }: {
  chain: OptionChain; type: "CE" | "PE"; interval: string;
  onTrade: (type: "CE" | "PE", side: "buy" | "sell", strike: number, ltp: number) => void;
}) {
  const [strike, setStrike] = useState(chain.atm_strike);
  useEffect(() => { setStrike(chain.atm_strike); }, [chain.underlying, chain.expiry]); // eslint-disable-line react-hooks/exhaustive-deps
  const row = chain.rows.find((r) => r.strike === strike);
  const leg = row ? (type === "CE" ? row.ce : row.pe) : null;
  const candles = usePoll(() => trade.optionCandles(chain.underlying, strike, type, chain.expiry, interval),
    30_000, [chain.underlying, strike, type, chain.expiry, interval]);
  const strikes = chain.rows.map((r) => r.strike);
  const step = (d: number) => {
    const i = strikes.indexOf(strike);
    const next = strikes[Math.min(Math.max(i + d, 0), strikes.length - 1)];
    if (next !== undefined) setStrike(next);
  };

  return (
    <section className="flex min-h-0 flex-col rounded-[var(--radius-lg)] border border-[var(--hairline)] bg-[var(--surface-1)]">
      <div className="flex flex-wrap items-center gap-2 border-b border-[var(--hairline)] px-3 py-2">
        <span className="rounded-full border border-[var(--hairline-strong)] px-3 py-1 text-small font-semibold">{type === "CE" ? "CALL" : "PUT"}</span>
        <button onClick={() => step(-1)} aria-label="Lower strike" className="rounded p-1 text-[var(--ink-secondary)] hover:bg-[var(--surface-3)]"><Icon name="chevronLeft" size={16} /></button>
        <select value={strike} onChange={(e) => setStrike(Number(e.target.value))} aria-label={`${type} strike`}
          className="tabular rounded bg-transparent text-body-lg font-semibold focus:outline-none">
          {strikes.map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <button onClick={() => step(1)} aria-label="Higher strike" className="rounded p-1 text-[var(--ink-secondary)] hover:bg-[var(--surface-3)]"><Icon name="chevronRight" size={16} /></button>
        <span className="text-small text-[var(--ink-muted)]">{shortExpiry(chain.expiry)}</span>
        {leg && <span className="tabular ml-1 text-body-lg font-semibold">{num(leg.ltp)}</span>}
        {leg && <Change value={leg.change_pct} parens className="text-body" />}
        <span className="ml-auto flex gap-1.5">
          <button onClick={() => leg && onTrade(type, "buy", strike, leg.ltp)} className="rounded-full bg-[var(--buy)] px-4 py-1.5 text-small font-semibold text-white">Buy</button>
          <button onClick={() => leg && onTrade(type, "sell", strike, leg.ltp)} className="rounded-full bg-[var(--sell)] px-4 py-1.5 text-small font-semibold text-white">Sell</button>
        </span>
      </div>
      <div className="relative min-h-[160px] flex-1">
        {candles.loading && !candles.data ? <div className="p-4"><Loading /></div> : candles.data && (
          <CandleChart bars={candles.data.bars} volume={false} compact intraday
            label={`${chain.underlying} ${strike} ${type}`} />
        )}
      </div>
    </section>
  );
}
