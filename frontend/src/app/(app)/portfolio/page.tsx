"use client";

import clsx from "clsx";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useOrderTicket } from "@/components/trade/order-ticket";
import { Icon, Loading, Sparkline, TextTabs } from "@/components/trade/primitives";
import { usePoll } from "@/lib/hooks";
import { trade, type PaperOrder, type PaperPortfolio, type PaperRow } from "@/lib/trade-api";
import { inr, inrSigned, num, pct, shortExpiry, tone } from "@/lib/tfmt";

type Segment = "stocks" | "fno";
type View = "positions" | "holdings" | "orders";
type Sort = "value" | "returns" | "name";

export default function PortfolioPage() {
  const pf = usePoll(() => trade.paperPortfolio(), 20_000);
  const orders = usePoll(() => trade.paperOrders(), 20_000);
  const [segment, setSegment] = useState<Segment>("stocks");
  const [view, setView] = useState<View>("holdings");
  const [sort, setSort] = useState<Sort>("value");

  useEffect(() => {
    const onOrder = () => { void pf.reload(); void orders.reload(); };
    window.addEventListener("paper-order", onOrder);
    return () => window.removeEventListener("paper-order", onOrder);
  }, [pf, orders]);

  if (pf.loading && !pf.data) return <Loading label="Loading your paper portfolio" />;
  if (!pf.data) return <p className="text-small text-[var(--down)]">{pf.error}</p>;
  const data = pf.data;

  const isFno = (r: { instrument: string }) => r.instrument === "option";
  const holdings = segment === "stocks" ? data.holdings : [];
  const positions = data.positions.filter((p) => (segment === "fno") === isFno(p));
  const orderRows = (orders.data?.orders ?? []).filter((o) => (segment === "fno") === isFno(o));

  // Header figures for the segment in view.
  const segValue = segment === "stocks"
    ? data.holdings_value + positions.reduce((s, p) => s + p.current_value, 0)
    : positions.reduce((s, p) => s + p.current_value, 0);
  const segInvested = segment === "stocks"
    ? data.holdings_invested + positions.reduce((s, p) => s + p.invested, 0)
    : positions.reduce((s, p) => s + p.invested, 0);
  const segReturn = segValue - segInvested;
  const segDay = [...holdings, ...positions].reduce((s, r) => s + r.day_pnl, 0);
  const segPrev = segValue - segDay;

  return (
    <div className="mx-auto max-w-[1250px]">
      <div className="mb-10 flex flex-wrap items-center justify-between gap-4">
        <TextTabs value={segment} onChange={(s) => { setSegment(s); setView(s === "fno" ? "positions" : "holdings"); }} options={[
          { value: "stocks", label: "Stocks" }, { value: "fno", label: "F&O" },
        ]} />
        <div className="flex items-center gap-3">
          <Link href="/autopilot" className="rounded-full border border-[var(--hairline-strong)] px-4 py-2 text-body hover:bg-[var(--surface-3)]">Autopilot</Link>
          <Link href="/analysis/overview" className="rounded-full border border-[var(--hairline-strong)] px-4 py-2 text-body hover:bg-[var(--surface-3)]">Analysis</Link>
          <span className="rounded-full bg-[var(--surface-3)] px-4 py-2 text-body font-medium" title="Paper trading with virtual money">Mock</span>
          <ResetButton onDone={() => { void pf.reload(); void orders.reload(); }} />
        </div>
      </div>

      <div className="grid gap-8 lg:grid-cols-[1fr_auto]">
        <div>
          <div className="text-small uppercase tracking-[0.1em] text-[var(--ink-muted)]">Current value</div>
          <div className="tabular mt-2 text-[44px] font-semibold leading-none">{inr(segValue)}</div>
          <div className="mt-3 text-body-lg">
            <span className="text-[var(--ink-muted)]">Total returns </span>
            <span className={clsx("tabular", tone(segReturn))}>{inrSigned(segReturn)} ({pct(segInvested ? (segReturn / segInvested) * 100 : 0)})</span>
          </div>
          <div className="mt-8 flex flex-wrap gap-x-14 gap-y-5">
            <Figure label="Today's change" value={<span className={tone(segDay)}>{inrSigned(segDay)} ({pct(segPrev ? (segDay / segPrev) * 100 : 0)})</span>} />
            <Figure label="Invested value" value={inr(segInvested, 0)} />
            <Figure label="Cash available" value={inr(data.available, 0)} hint={data.margin_used ? `${inr(data.margin_used, 0)} blocked as margin` : undefined} />
            <Figure label="Account value" value={inr(data.total_value, 0)} hint={`${inrSigned(data.total_return)} since start (${pct(data.total_return_pct)})`} />
          </div>
        </div>
        <WeeklyActivity data={data} />
      </div>

      {data.unpriced.length > 0 && (
        <div className="mt-10 rounded-[var(--radius)] border border-[var(--hairline-strong)] px-5 py-3 text-body text-[var(--ink-secondary)]">
          {data.unpriced.length} position{data.unpriced.length === 1 ? "" : "s"} could not be priced and {data.unpriced.length === 1 ? "is" : "are"} shown at cost:{" "}
          {data.unpriced[0].reason}
          {!data.options_feed.connected && <> <Link href="/settings/brokers" className="underline">Connect Upstox</Link></>}
        </div>
      )}

      <div className="mt-14 flex flex-wrap items-end justify-between gap-4 border-b border-[var(--hairline)]">
        <TextTabs value={view} onChange={setView} options={[
          { value: "positions", label: "Positions", count: positions.length },
          ...(segment === "stocks" ? [{ value: "holdings" as View, label: "Holdings", count: holdings.length }] : []),
          { value: "orders", label: "Orders", count: orderRows.length },
        ]} />
        {view !== "orders" && (
          <label className="mb-2 flex items-center gap-2 rounded-[var(--radius)] border border-[var(--hairline-strong)] px-4 py-2 text-body">
            <Icon name="swap" size={16} className="text-[var(--ink-muted)]" />
            <select value={sort} onChange={(e) => setSort(e.target.value as Sort)} className="bg-transparent focus:outline-none" aria-label="Sort">
              <option value="value">Market value</option><option value="returns">Returns</option><option value="name">Name</option>
            </select>
          </label>
        )}
      </div>

      <div className="mt-2">
        {view === "holdings" && <Rows rows={holdings} sort={sort} empty={<Empty text="No holdings yet." />} />}
        {view === "positions" && <Rows rows={positions} sort={sort} empty={<Empty text={segment === "fno" ? "No open F&O positions." : "No intraday positions."} fno={segment === "fno"} />} />}
        {view === "orders" && <Orders rows={orderRows} onChange={() => { void orders.reload(); void pf.reload(); }} />}
      </div>
      <p className="mt-10 text-caption text-[var(--ink-faint)]">
        Paper trading with virtual money, filled at real prices: live from Upstox when connected, otherwise delayed about fifteen minutes. Options need Upstox. Nothing reaches a broker or exchange.
      </p>
    </div>
  );
}

function Figure({ label, value, hint }: { label: string; value: React.ReactNode; hint?: string }) {
  return (
    <div title={hint}>
      <div className="flex items-center gap-1.5 text-small uppercase tracking-[0.1em] text-[var(--ink-muted)]">{label}
        {hint && <Icon name="clock" size={13} className="opacity-0" />}
      </div>
      <div className="tabular mt-2 text-h3">{value}</div>
      {hint && <div className="mt-1 text-caption text-[var(--ink-faint)]">{hint}</div>}
    </div>
  );
}

function WeeklyActivity({ data }: { data: PaperPortfolio }) {
  const days = data.weekly_activity.filter((d) => !["SAT", "SUN"].includes(d.weekday));
  const max = Math.max(1, ...days.map((d) => d.orders));
  const first = data.weekly_activity[0]?.date, last = data.weekly_activity.at(-1)?.date;
  const label = first && last ? `${new Date(first).getDate()}-${new Date(last).getDate()} ${new Date(last).toLocaleDateString("en-GB", { month: "short" }).toUpperCase()}` : "";
  return (
    <div className="min-w-[300px]">
      <div className="text-right text-small uppercase tracking-[0.1em] text-[var(--ink-muted)]">Weekly activity · {label}</div>
      <div className="mt-6 flex h-24 items-end justify-end gap-6">
        {days.map((d) => (
          <div key={d.date} className="flex flex-col items-center gap-2" title={`${d.orders} order${d.orders === 1 ? "" : "s"}`}>
            <div className="flex h-16 w-16 items-end">
              <div className={clsx("w-full rounded-t", d.orders ? "bg-[var(--ink-secondary)]" : "bg-[var(--surface-4)]")}
                style={{ height: d.orders ? `${Math.max(12, (d.orders / max) * 100)}%` : 3 }} />
            </div>
            <span className="text-caption text-[var(--ink-muted)]">{d.weekday}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function Monogram({ symbol }: { symbol: string }) {
  const hue = [...symbol].reduce((h, c) => h + c.charCodeAt(0) * 7, 0) % 360;
  return <span className="flex h-12 w-12 shrink-0 items-center justify-center rounded-[12px] text-body font-bold text-white" style={{ background: `hsl(${hue} 45% 32%)` }}>{symbol.slice(0, 2)}</span>;
}

function Rows({ rows, sort, empty }: { rows: PaperRow[]; sort: Sort; empty: React.ReactNode }) {
  const ticket = useOrderTicket();
  const sorted = useMemo(() => [...rows].sort((a, b) =>
    sort === "name" ? a.symbol.localeCompare(b.symbol) : sort === "returns" ? (b.pnl ?? 0) - (a.pnl ?? 0) : Math.abs(b.current_value) - Math.abs(a.current_value)), [rows, sort]);
  if (!rows.length) return <>{empty}</>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px]">
        <thead>
          <tr className="text-left text-small uppercase tracking-[0.1em] text-[var(--ink-muted)]">
            <th className="py-5 font-medium">Instrument</th><th />
            <th className="py-5 text-right font-medium">Market price (1D%)</th>
            <th className="py-5 text-right font-medium">Returns (%)</th>
            <th className="py-5 text-right font-medium">Current (invested)</th><th />
          </tr>
        </thead>
        <tbody className="border-t border-[var(--hairline)]">
          {sorted.map((r) => (
            <tr key={r.id} className="group border-b border-[var(--hairline)] last:border-0">
              <td className="py-5">
                <div className="flex items-center gap-4">
                  <Monogram symbol={r.underlying} />
                  <div>
                    <div className="flex items-center gap-2.5">
                      <Link href={`/chart?symbol=${r.underlying}`} className="text-h3 font-semibold hover:underline">
                        {r.instrument === "option" ? `${r.underlying} ${r.strike} ${r.option_type}` : r.symbol}
                      </Link>
                      <span className="rounded-full border border-[var(--hairline-strong)] px-2.5 py-0.5 text-small text-[var(--ink-secondary)]">{r.tag_label}</span>
                    </div>
                    <div className="mt-1 text-body-lg text-[var(--ink-secondary)]">
                      {r.instrument === "option"
                        ? `${r.quantity > 0 ? "Long" : "Short"} ${Math.abs(r.quantity)} · ${r.expiry ? shortExpiry(r.expiry) : ""} · avg ₹${num(r.avg_price)}`
                        : `${r.quantity} share${r.quantity === 1 ? "" : "s"} · avg ₹${num(r.avg_price)}`}
                    </div>
                  </div>
                </div>
              </td>
              <td className="px-4">{r.sparkline && <Sparkline values={r.sparkline} />}</td>
              <td className="py-5 text-right">
                {r.ltp != null ? (
                  <>
                    <div className="tabular text-h3">₹{num(r.ltp)}</div>
                    <div className={clsx("tabular mt-1 text-body-lg", tone(r.day_change_pct))}>{pct(r.day_change_pct, 1)}</div>
                  </>
                ) : (
                  <div className="text-body text-[var(--ink-muted)]" title={r.price_note}>Price unavailable</div>
                )}
              </td>
              <td className="py-5 text-right">
                <div className={clsx("tabular text-h3", tone(r.pnl))}>{r.pnl != null ? inrSigned(r.pnl) : "—"}</div>
                <div className={clsx("tabular mt-1 text-body-lg", tone(r.pnl))}>{r.pnl_pct != null ? pct(r.pnl_pct, 1) : ""}</div>
              </td>
              <td className="py-5 text-right">
                <div className="tabular text-h3">{inr(r.current_value, 0)}</div>
                <div className="tabular mt-1 text-body-lg text-[var(--ink-secondary)]">{inr(r.invested, 0)}</div>
              </td>
              <td className="w-28 pl-4 text-right">
                <button onClick={() => ticket.open(r.instrument === "option"
                  ? { instrument: "option", symbol: r.underlying, side: r.quantity > 0 ? "sell" : "buy", option_type: r.option_type, strike: r.strike, expiry: r.expiry, quantity: Math.abs(r.quantity) / (r.lot_size || 1), lot_size: r.lot_size, ltp: r.ltp }
                  : { instrument: "equity", symbol: r.symbol, side: "sell", quantity: r.quantity, ltp: r.ltp })}
                  className="rounded-full border border-[var(--hairline-strong)] px-4 py-1.5 text-small opacity-70 hover:bg-[var(--surface-3)] group-hover:opacity-100">
                  Exit
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}


function Orders({ rows, onChange }: { rows: PaperOrder[]; onChange: () => void }) {
  if (!rows.length) return <Empty text="No orders yet." />;
  const statusTone: Record<string, string> = {
    filled: "text-[var(--up)]", open: "text-[var(--ink-primary)]", cancelled: "text-[var(--ink-muted)]", rejected: "text-[var(--down)]",
  };
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] text-body">
        <thead>
          <tr className="text-left text-small uppercase tracking-[0.1em] text-[var(--ink-muted)]">
            <th className="py-4 font-medium">Time</th><th className="py-4 font-medium">Instrument</th><th className="py-4 font-medium">Side</th>
            <th className="py-4 text-right font-medium">Qty</th><th className="py-4 text-right font-medium">Price</th>
            <th className="py-4 pl-6 font-medium">Status</th><th className="py-4 font-medium">Source</th><th />
          </tr>
        </thead>
        <tbody className="border-t border-[var(--hairline)]">
          {rows.map((o) => (
            <tr key={o.id} className="border-b border-[var(--hairline)] last:border-0">
              <td className="tabular py-3 text-[var(--ink-secondary)]">{o.created_at ? new Date(o.created_at).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false }) : "—"}</td>
              <td className="py-3 font-medium">{o.symbol}</td>
              <td className={clsx("py-3 font-semibold uppercase", o.side === "buy" ? "text-[var(--up)]" : "text-[var(--down)]")}>{o.side}</td>
              <td className="tabular py-3 text-right">{o.quantity}</td>
              <td className="tabular py-3 text-right">{o.fill_price ? num(o.fill_price) : o.limit_price ? `${num(o.limit_price)} limit` : "Market"}</td>
              <td className={clsx("py-3 pl-6 capitalize", statusTone[o.status])} title={o.reject_reason ?? undefined}>
                {o.status}{o.reject_reason && <span className="block max-w-[260px] truncate text-caption normal-case text-[var(--ink-muted)]">{o.reject_reason}</span>}
              </td>
              <td className="py-3 text-[var(--ink-secondary)]">{o.tag_label}</td>
              <td className="py-3 text-right">
                {o.status === "open" && (
                  <button onClick={async () => { await trade.cancelOrder(o.id).catch(() => {}); onChange(); }}
                    className="rounded-full border border-[var(--hairline-strong)] px-3 py-1 text-small hover:text-[var(--down)]">Cancel</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Empty({ text, fno }: { text: string; fno?: boolean }) {
  return (
    <div className="py-14 text-center">
      <p className="text-body-lg text-[var(--ink-secondary)]">{text}</p>
      <p className="mt-2 text-body text-[var(--ink-muted)]">
        {fno ? <>Trade from the <Link href="/market/option-chain" className="underline">option chain</Link> or the <Link href="/chart" className="underline">chart</Link>.</>
          : <>Start <Link href="/autopilot" className="underline">Autopilot</Link>, take a <Link href="/market/model-picks" className="underline">model pick</Link>, or buy from a <Link href="/market/screener" className="underline">screen</Link>.</>}
      </p>
    </div>
  );
}

function ResetButton({ onDone }: { onDone: () => void }) {
  const [confirming, setConfirming] = useState(false);
  if (!confirming) {
    return <button onClick={() => setConfirming(true)} title="Reset the paper account" aria-label="Reset paper account"
      className="rounded-full border border-[var(--hairline-strong)] p-2.5 text-[var(--ink-secondary)] hover:bg-[var(--surface-3)]"><Icon name="refresh" size={17} /></button>;
  }
  return (
    <span className="flex items-center gap-2 text-small">
      Clear all paper trades?
      <button onClick={async () => { await trade.resetPaper().catch(() => {}); setConfirming(false); onDone(); }} className="rounded-full bg-[var(--sell)] px-3 py-1.5 font-semibold text-white">Reset</button>
      <button onClick={() => setConfirming(false)} className="rounded-full border border-[var(--hairline-strong)] px-3 py-1.5">Keep</button>
    </span>
  );
}
