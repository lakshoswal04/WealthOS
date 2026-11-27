"use client";

import clsx from "clsx";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { usePoll } from "@/lib/hooks";
import { RangeBar } from "@/components/charts/swing";
import { signals, trade, type ChatMessage, type OptionChain, type Unavailable } from "@/lib/trade-api";
import { inr, inrSigned, num, oiShort, shortExpiry, tone } from "@/lib/tfmt";
import { Composer, MessageList } from "./chat";
import { useOrderTicket } from "./order-ticket";
import { Change, DataUnavailable, Icon, Loading } from "./primitives";

export const INDEX_KEYS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"];

function PanelHead({ title, children, onClose }: { title: React.ReactNode; children?: React.ReactNode; onClose: () => void }) {
  return (
    <div className="flex items-center justify-between border-b border-[var(--hairline)] px-4 py-3">
      <div className="flex items-center gap-2 text-body-lg font-semibold">{title}</div>
      <div className="flex items-center gap-1 text-[var(--ink-muted)]">
        {children}
        <button onClick={onClose} aria-label="Close panel" className="rounded-full p-1.5 hover:bg-[var(--surface-3)] hover:text-[var(--ink-primary)]"><Icon name="x" size={16} /></button>
      </div>
    </div>
  );
}

/* ─────────────────────────── AI ─────────────────────────── */

export function AIPanel({ symbol, onClose }: { symbol: string; onClose: () => void }) {
  const [threadId, setThreadId] = useState<number | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [pending, setPending] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { setThreadId(null); setMessages([]); }, [symbol]);

  const isIndex = INDEX_KEYS.includes(symbol);
  const prompts = isIndex
    ? ["Where is the support for today?", "Which strike has the most OI build-up?", "Explain the Call and Put premium move", "Suggest a hedge for this view"]
    : [`What do the models say about ${symbol}?`, `How is ${symbol} doing today?`, `Backtest a golden cross on ${symbol}`, `Buy 10 shares of ${symbol}`];

  const send = useCallback(async (text: string) => {
    setPending(text); setError(null);
    try {
      let id = threadId;
      if (!id) { id = (await trade.newThread(`${symbol}: ${text}`.slice(0, 110), symbol)).id; setThreadId(id); }
      const { message } = await trade.send(id, text, symbol);
      setMessages((m) => [...m, { id: -Date.now(), role: "user", content: text, cards: [], meta: {}, created_at: null }, message]);
    } catch (err) { setError((err as Error).message); } finally { setPending(null); }
  }, [threadId, symbol]);

  return (
    <div className="flex h-full flex-col">
      <PanelHead onClose={onClose} title={<><Icon name="sparkle" size={18} /> AI <span className="rounded-full bg-[var(--surface-3)] px-2.5 py-0.5 text-small font-medium text-[var(--ink-secondary)]">{symbol}</span></>}>
        <button onClick={() => { setThreadId(null); setMessages([]); }} aria-label="New conversation" className="rounded-full p-1.5 hover:bg-[var(--surface-3)] hover:text-[var(--ink-primary)]"><Icon name="plus" size={16} /></button>
        {threadId && <Link href={`/home?thread=${threadId}`} aria-label="Open in chat history" className="rounded-full p-1.5 hover:bg-[var(--surface-3)] hover:text-[var(--ink-primary)]"><Icon name="history" size={16} /></Link>}
      </PanelHead>
      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-5">
        {messages.length === 0 && !pending ? (
          <>
            {!isIndex && <ModelStrip symbol={symbol} />}
            <div className="mb-3 text-body font-medium text-[var(--ink-secondary)]">Ask about it</div>
            <div className="space-y-2.5">
              {prompts.map((p) => (
                <button key={p} onClick={() => send(p)} className="block w-full rounded-[var(--radius)] border border-[var(--hairline-strong)] px-4 py-3 text-left text-body hover:bg-[var(--surface-3)]">{p}</button>
              ))}
            </div>
            <p className="mt-4 text-small text-[var(--ink-muted)]">Answers quote only figures the backend measured.</p>
          </>
        ) : <MessageList messages={messages} pending={pending} compact />}
        {error && <p className="mt-3 text-small text-[var(--down)]">{error}</p>}
      </div>
      <div className="border-t border-[var(--hairline)] p-3">
        <Composer onSubmit={send} busy={!!pending} placeholder={`Ask about ${symbol}…`} />
      </div>
    </div>
  );
}

/** The swing models' view of one stock, shown above the AI prompts. */
function ModelStrip({ symbol }: { symbol: string }) {
  const { data, failure } = usePoll(() => signals.symbol(symbol), 600_000, [symbol]);
  if (failure) return <p className="mb-5 text-small text-[var(--ink-muted)]">Model view: {failure.message}</p>;
  if (!data) return null;
  if (!data.eligible) return <p className="mb-5 text-small text-[var(--ink-muted)]">Model view: {data.reason}</p>;
  const r = data.range_10d;
  return (
    <div className="mb-5 rounded-[var(--radius)] border border-[var(--hairline-strong)] p-4">
      <div className="flex items-baseline justify-between">
        <span className="flex items-center gap-1.5 text-small font-medium text-[var(--ink-secondary)]"><Icon name="brain" size={14} /> Swing models</span>
        <span className="tabular text-small">rank <b>{data.rank}</b> of {data.of}</span>
      </div>
      <div className="mt-3"><RangeBar low={r?.low ?? null} mid={r?.mid ?? null} high={r?.high ?? null} /></div>
      <div className="mt-1 text-caption text-[var(--ink-muted)]">80% range, next {data.model.horizon_sessions} sessions · as of {data.as_of}</div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {data.drivers.map((d) => (
          <span key={d.feature} className="rounded-full border border-[var(--hairline)] px-2 py-[1px] text-caption text-[var(--ink-secondary)]">
            {d.effect === "raises" ? "↑" : "↓"} {d.label}
          </span>
        ))}
      </div>
      <Link href="/market/model-picks" className="mt-2 inline-block text-caption text-[var(--ink-muted)] hover:text-[var(--ink-primary)]">Research signal, not advice · all picks →</Link>
    </div>
  );
}

/* ─────────────────────────── watchlist ─────────────────────────── */

const WATCH_KEY = "wealthos.watchlist";
const DEFAULT_WATCH = ["NIFTY", "BANKNIFTY", "SENSEX", "RELIANCE", "HDFCBANK", "INFY", "TCS", "ICICIBANK"];

export function WatchlistPanel({ symbol, onPick, onClose }: { symbol: string; onPick: (s: string) => void; onClose: () => void }) {
  const [list, setList] = useState<string[]>(DEFAULT_WATCH);
  useEffect(() => {
    try { const saved = JSON.parse(localStorage.getItem(WATCH_KEY) ?? "null"); if (Array.isArray(saved)) setList(saved); } catch { /* default */ }
  }, []);
  const save = (next: string[]) => { setList(next); localStorage.setItem(WATCH_KEY, JSON.stringify(next)); };
  const { data } = usePoll(() => trade.quotes(list), 15_000, [list.join(",")]);
  const quotes = new Map((data?.quotes ?? []).map((q) => [q.symbol, q]));
  return (
    <div className="flex h-full flex-col">
      <PanelHead title="Watchlist" onClose={onClose}>
        {!list.includes(symbol) && (
          <button onClick={() => save([...list, symbol])} className="rounded-full px-2.5 py-1 text-small hover:bg-[var(--surface-3)] hover:text-[var(--ink-primary)]">+ {symbol}</button>
        )}
      </PanelHead>
      <ul className="min-h-0 flex-1 divide-y divide-[var(--hairline)] overflow-y-auto">
        {list.map((s) => {
          const q = quotes.get(s);
          return (
            <li key={s} className={clsx("group flex items-center gap-2 px-4 py-3 hover:bg-[var(--surface-2)]", s === symbol && "bg-[var(--surface-2)]")}>
              <button onClick={() => onPick(s)} className="flex min-w-0 flex-1 items-center justify-between text-left">
                <span className="truncate font-medium">{s}</span>
                <span className="text-right"><span className="tabular block">{q ? num(q.ltp) : "—"}</span><Change value={q?.change_pct} className="text-small" /></span>
              </button>
              <button onClick={() => save(list.filter((x) => x !== s))} aria-label={`Remove ${s}`} className="invisible text-[var(--ink-faint)] hover:text-[var(--down)] group-hover:visible"><Icon name="x" size={14} /></button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/* ─────────────────────────── option chain ─────────────────────────── */

export function ChainPanel({ chain, failure, onClose }: { chain: OptionChain | null; failure?: Unavailable | null; onClose: () => void }) {
  const ticket = useOrderTicket();
  if (failure) return <div className="flex h-full flex-col"><PanelHead title="Option chain" onClose={onClose} /><div className="p-4"><DataUnavailable failure={failure} compact /></div></div>;
  if (!chain) return <div className="flex h-full flex-col"><PanelHead title="Option chain" onClose={onClose} /><div className="px-4"><Loading /></div></div>;
  const atmIndex = chain.rows.findIndex((r) => r.strike === chain.atm_strike);
  const rows = chain.rows.slice(Math.max(atmIndex - 8, 0), atmIndex + 9);
  const open = (strike: number, type: "CE" | "PE", ltp: number) => ticket.open({
    instrument: "option", symbol: chain.underlying, side: "buy", option_type: type, strike, expiry: chain.expiry, quantity: 1, lot_size: chain.lot_size, ltp,
  });
  return (
    <div className="flex h-full flex-col">
      <PanelHead title={<>Option chain <span className="text-small font-normal text-[var(--ink-muted)]">{shortExpiry(chain.expiry)}</span></>} onClose={onClose}>
        <Link href={`/market/option-chain?u=${chain.underlying}&expiry=${chain.expiry}`} className="rounded-full px-2 py-1 text-small hover:text-[var(--ink-primary)]">Full</Link>
      </PanelHead>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <table className="w-full text-small">
          <thead className="sticky top-0 bg-[var(--surface-1)] text-caption text-[var(--ink-muted)]">
            <tr><th className="px-3 py-2 text-right font-normal">CE OI</th><th className="px-2 py-2 text-right font-normal">CE</th><th className="px-2 py-2 font-normal">Strike</th><th className="px-2 py-2 text-left font-normal">PE</th><th className="px-3 py-2 text-left font-normal">PE OI</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.strike} className={clsx("border-b border-[var(--hairline)]", r.strike === chain.atm_strike && "bg-[var(--surface-2)]")}>
                <td className="tabular px-3 py-1.5 text-right text-[var(--ink-muted)]">{oiShort(r.ce.oi)}</td>
                <td className="px-2 py-1.5 text-right"><button onClick={() => open(r.strike, "CE", r.ce.ltp)} className="tabular rounded px-1 hover:bg-[var(--buy)] hover:text-white">{num(r.ce.ltp)}</button></td>
                <td className={clsx("tabular px-2 py-1.5 text-center font-semibold", r.strike === chain.atm_strike && "text-[var(--accent)]")}>{r.strike}</td>
                <td className="px-2 py-1.5"><button onClick={() => open(r.strike, "PE", r.pe.ltp)} className="tabular rounded px-1 hover:bg-[var(--buy)] hover:text-white">{num(r.pe.ltp)}</button></td>
                <td className="tabular px-3 py-1.5 text-[var(--ink-muted)]">{oiShort(r.pe.oi)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="px-4 py-3 text-caption text-[var(--ink-faint)]">Live from your Upstox session.</p>
      </div>
    </div>
  );
}

/* ─────────────────────────── price alerts ─────────────────────────── */

interface PriceAlert { id: string; symbol: string; dir: "above" | "below"; price: number; triggered?: string }
const ALERT_KEY = "wealthos.price-alerts";

export function usePriceAlerts(onFire: (a: PriceAlert, ltp: number) => void) {
  const [alerts, setAlerts] = useState<PriceAlert[]>([]);
  useEffect(() => { try { setAlerts(JSON.parse(localStorage.getItem(ALERT_KEY) ?? "[]")); } catch { /* none */ } }, []);
  const persist = useCallback((next: PriceAlert[]) => { setAlerts(next); localStorage.setItem(ALERT_KEY, JSON.stringify(next)); }, []);
  const live = alerts.filter((a) => !a.triggered);
  const symbols = useMemo(() => Array.from(new Set(live.map((a) => a.symbol))), [live]);
  const { data } = usePoll(() => symbols.length ? trade.quotes(symbols) : Promise.resolve({ quotes: [], unavailable: [] }), 15_000, [symbols.join(",")]);
  useEffect(() => {
    if (!data?.quotes.length) return;
    const price = new Map(data.quotes.map((q) => [q.symbol, q.ltp]));
    let changed = false;
    const next = alerts.map((a) => {
      const p = price.get(a.symbol);
      if (a.triggered || p === undefined) return a;
      if ((a.dir === "above" && p >= a.price) || (a.dir === "below" && p <= a.price)) {
        changed = true; onFire(a, p);
        return { ...a, triggered: new Date().toISOString() };
      }
      return a;
    });
    if (changed) persist(next);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data]);
  return { alerts, persist };
}

export function AlertsPanel({ symbol, ltp, alerts, persist, onClose }: {
  symbol: string; ltp: number | null; alerts: PriceAlert[]; persist: (a: PriceAlert[]) => void; onClose: () => void;
}) {
  const [price, setPrice] = useState("");
  const add = () => {
    const p = Number(price);
    if (!(p > 0) || ltp === null) return;
    persist([...alerts, { id: String(Date.now()), symbol, dir: p >= ltp ? "above" : "below", price: p }]);
    setPrice("");
  };
  return (
    <div className="flex h-full flex-col">
      <PanelHead title="Price alerts" onClose={onClose} />
      <div className="border-b border-[var(--hairline)] p-4">
        <div className="mb-2 text-small text-[var(--ink-muted)]">Alert when {symbol} crosses</div>
        <div className="flex gap-2">
          <input value={price} onChange={(e) => setPrice(e.target.value.replace(/[^\d.]/g, ""))} placeholder={ltp ? num(ltp) : "Price"}
            onKeyDown={(e) => { if (e.key === "Enter") add(); }}
            className="tabular min-w-0 flex-1 rounded-[var(--radius-sm)] border border-[var(--hairline-strong)] bg-[var(--surface-2)] px-3 py-2 focus:outline-none" />
          <button onClick={add} className="rounded-full bg-[var(--action)] px-4 text-body font-semibold text-[var(--action-ink)]">Add</button>
        </div>
        <p className="mt-2 text-caption text-[var(--ink-faint)]">Checked every 15 seconds while WealthOS is open, against delayed prices.</p>
      </div>
      <ul className="min-h-0 flex-1 divide-y divide-[var(--hairline)] overflow-y-auto">
        {alerts.length === 0 && <li className="px-4 py-6 text-small text-[var(--ink-muted)]">No alerts yet.</li>}
        {[...alerts].reverse().map((a) => (
          <li key={a.id} className="flex items-center justify-between px-4 py-3 text-body">
            <span className={clsx(a.triggered && "text-[var(--ink-muted)] line-through")}>{a.symbol} {a.dir} <span className="tabular">{num(a.price)}</span></span>
            <span className="flex items-center gap-2">
              {a.triggered && <span className="text-caption text-[var(--up)]">Triggered</span>}
              <button onClick={() => persist(alerts.filter((x) => x.id !== a.id))} aria-label="Delete alert" className="text-[var(--ink-faint)] hover:text-[var(--down)]"><Icon name="trash" size={14} /></button>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ─────────────────────────── strategies ─────────────────────────── */

export function StrategiesPanel({ symbol, onClose }: { symbol: string; onClose: () => void }) {
  const isIndex = INDEX_KEYS.includes(symbol);
  const { data, loading, failure } = usePoll(() => trade.recommendations(isIndex ? "fno" : "delivery", 12), null, [isIndex]);
  const ideas = (data?.ideas ?? []).filter((i) => !isIndex || i.symbol === symbol);
  return (
    <div className="flex h-full flex-col">
      <PanelHead title="Strategies" onClose={onClose}>
        <Link href="/strategy-templates" className="rounded-full px-2 py-1 text-small hover:text-[var(--ink-primary)]">Library</Link>
      </PanelHead>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {failure && <DataUnavailable failure={failure} compact />}
        {loading && !data && !failure && <Loading />}
        {data && ideas.length === 0 && <p className="text-small text-[var(--ink-muted)]">No rule-based setup for {symbol} right now.</p>}
        {ideas.map((i) => (
          <div key={i.id} className="rounded-[var(--radius)] border border-[var(--hairline-strong)] p-3">
            <div className="font-medium">{i.instrument === "equity" ? `${i.side === "buy" ? "Buy" : "Sell"} ${i.symbol}` : i.name}</div>
            <div className="mt-1 text-small text-[var(--ink-muted)]">
              {i.instrument === "equity" ? `Entry ${num(i.entry)} · SL ${num(i.stop_loss)} · T ${num(i.target)}`
                : i.legs.map((l) => `${l.action} ${l.strike} ${l.option_type}`).join(" · ")}
            </div>
            <div className="mt-1 text-caption text-[var(--ink-faint)]">{i.rationale[0]}</div>
          </div>
        ))}
        {data && <p className="text-caption text-[var(--ink-faint)]">{data.disclaimer}</p>}
      </div>
    </div>
  );
}

/* ─────────────────────────── positions ─────────────────────────── */

export function PositionsPanel({ onPick, onClose }: { onPick: (s: string) => void; onClose: () => void }) {
  const { data, loading, reload } = usePoll(() => trade.paperPortfolio(), 15_000);
  useEffect(() => {
    const on = () => void reload();
    window.addEventListener("paper-order", on);
    return () => window.removeEventListener("paper-order", on);
  }, [reload]);
  const rows = [...(data?.positions ?? []), ...(data?.holdings ?? [])];
  return (
    <div className="flex h-full flex-col">
      <PanelHead title="Positions" onClose={onClose}>
        <Link href="/portfolio" className="rounded-full px-2 py-1 text-small hover:text-[var(--ink-primary)]">Portfolio</Link>
      </PanelHead>
      {data && (
        <div className="grid grid-cols-2 gap-3 border-b border-[var(--hairline)] px-4 py-3 text-small">
          <div><div className="text-caption text-[var(--ink-muted)]">Today</div><div className={clsx("tabular text-body-lg", tone(data.day_change))}>{inrSigned(data.day_change)}</div></div>
          <div><div className="text-caption text-[var(--ink-muted)]">Available</div><div className="tabular text-body-lg">{inr(data.available, 0)}</div></div>
        </div>
      )}
      <ul className="min-h-0 flex-1 divide-y divide-[var(--hairline)] overflow-y-auto">
        {loading && !data && <li className="px-4"><Loading /></li>}
        {data && rows.length === 0 && <li className="px-4 py-6 text-small text-[var(--ink-muted)]">No open positions.</li>}
        {rows.map((r) => (
          <li key={`${r.id}-${r.symbol}`}>
            <button onClick={() => onPick(r.underlying)} className="flex w-full items-center justify-between px-4 py-3 text-left hover:bg-[var(--surface-2)]">
              <span className="min-w-0"><span className="block truncate font-medium">{r.symbol}</span><span className="text-caption text-[var(--ink-muted)]">{r.quantity} @ {num(r.avg_price)}</span></span>
              <span className="text-right"><span className={clsx("tabular block", tone(r.pnl))}>{inrSigned(r.pnl)}</span><span className="tabular text-caption text-[var(--ink-muted)]">{num(r.ltp)}</span></span>
            </button>
          </li>
        ))}
      </ul>
      {data && data.unpriced.length > 0 && (
        <div className="border-t border-[var(--hairline)] px-4 py-2 text-caption text-[var(--ink-muted)]">{data.unpriced.length} position(s) without a live price, shown at cost.</div>
      )}
    </div>
  );
}

/* ─────────────────────────── OI ─────────────────────────── */

export function OIPanel({ chain, failure, onClose }: { chain: OptionChain | null; failure?: Unavailable | null; onClose: () => void }) {
  if (failure) return <div className="flex h-full flex-col"><PanelHead title="Open interest" onClose={onClose} /><div className="p-4"><DataUnavailable failure={failure} compact /></div></div>;
  if (!chain) return <div className="flex h-full flex-col"><PanelHead title="Open interest" onClose={onClose} /><div className="px-4"><Loading /></div></div>;
  const atmIndex = chain.rows.findIndex((r) => r.strike === chain.atm_strike);
  const rows = chain.rows.slice(Math.max(atmIndex - 10, 0), atmIndex + 11);
  const max = Math.max(...rows.flatMap((r) => [r.ce.oi, r.pe.oi]), 1);
  return (
    <div className="flex h-full flex-col">
      <PanelHead title="Open interest" onClose={onClose}>
        <Link href={`/market/oi?u=${chain.underlying}`} className="rounded-full px-2 py-1 text-small hover:text-[var(--ink-primary)]">Analysis</Link>
      </PanelHead>
      <div className="grid grid-cols-3 gap-2 border-b border-[var(--hairline)] px-4 py-3 text-small">
        <div><div className="text-caption text-[var(--ink-muted)]">PCR</div><div className="tabular">{chain.pcr?.toFixed(2)}</div></div>
        <div><div className="text-caption text-[var(--ink-muted)]">Support</div><div className="tabular text-[var(--up)]">{chain.support}</div></div>
        <div><div className="text-caption text-[var(--ink-muted)]">Resistance</div><div className="tabular text-[var(--down)]">{chain.resistance}</div></div>
      </div>
      <div className="min-h-0 flex-1 space-y-1 overflow-y-auto px-4 py-3">
        {rows.map((r) => (
          <div key={r.strike} className="grid grid-cols-[1fr_auto_1fr] items-center gap-2 text-caption">
            <div className="flex justify-end"><div className="h-2.5 rounded-l bg-[var(--down)]" style={{ width: `${(r.ce.oi / max) * 100}%` }} /></div>
            <span className={clsx("tabular w-14 text-center", r.strike === chain.atm_strike && "font-semibold text-[var(--accent)]")}>{r.strike}</span>
            <div><div className="h-2.5 rounded-r bg-[var(--up)]" style={{ width: `${(r.pe.oi / max) * 100}%` }} /></div>
          </div>
        ))}
      </div>
      <p className="px-4 pb-3 text-caption text-[var(--ink-faint)]">Calls left (red), puts right (green). Live OI from Upstox.</p>
    </div>
  );
}
