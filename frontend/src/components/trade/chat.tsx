"use client";

import clsx from "clsx";
import Link from "next/link";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { RangeBar } from "@/components/charts/swing";
import { AllocationResult, ReviewBody } from "./autopilot-ui";
import { signals, trade, type ChatCard, type ChatMessage, type PaperOrder } from "@/lib/trade-api";
import { inr, num, pct, shortExpiry, tone } from "@/lib/tfmt";
import { useOrderTicket } from "./order-ticket";
import { Change, Icon, SourceTag } from "./primitives";

/* ─────────────────────────── composer ─────────────────────────── */

export const CHIPS: { key: string; label: string; icon: string; prompt: string }[] = [
  { key: "models", label: "Model picks", icon: "brain", prompt: "What do the models predict for the next two weeks?" },
  { key: "autopilot", label: "Autopilot", icon: "bolt", prompt: "Invest 50,000 in autopilot now" },
  { key: "backtest", label: "Backtest", icon: "clock", prompt: "Backtest the EMA crossover strategy on NIFTY" },
  { key: "strategy", label: "Strategy", icon: "pencil", prompt: "Suggest an F&O strategy for NIFTY this expiry" },
  { key: "research", label: "Research", icon: "search", prompt: "Tell me the best stocks for the next quarter" },
];

const PLACEHOLDERS = [
  "Build me a swing plan with 2 lakh",
  "Invest 50,000 in autopilot now",
  "Tell me the best stocks for the next quarter",
  "Where is NIFTY's support for today?",
  "Backtest a golden cross on HDFCBANK",
  "What's moving today?",
];

export function Composer({ onSubmit, busy, placeholder, large = false, value, onValueChange, autoFocus }: {
  onSubmit: (text: string) => void; busy?: boolean; placeholder?: string; large?: boolean;
  value?: string; onValueChange?: (v: string) => void; autoFocus?: boolean;
}) {
  const [inner, setInner] = useState("");
  const text = value ?? inner;
  const setText = onValueChange ?? setInner;
  const [hint, setHint] = useState(0);
  const ref = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (placeholder) return;
    const id = window.setInterval(() => setHint((h) => (h + 1) % PLACEHOLDERS.length), 3500);
    return () => window.clearInterval(id);
  }, [placeholder]);
  useEffect(() => { if (autoFocus) ref.current?.focus(); }, [autoFocus]);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [text]);

  const send = () => {
    const t = text.trim();
    if (!t || busy) return;
    onSubmit(t);
    setText("");
  };

  return (
    <div className={clsx("flex items-end gap-2 rounded-[32px] border border-[var(--hairline-strong)] bg-[var(--surface-1)] shadow-[var(--lift-2)] transition-colors focus-within:border-[var(--ink-muted)]",
      large ? "px-4 py-3" : "px-3 py-2")}>
      <span className="mb-2.5 hidden text-[var(--ink-secondary)] sm:block" title="Ask anything about markets, a stock or your paper portfolio"><Icon name="plus" size={20} /></span>
      <textarea ref={ref} rows={1} value={text} onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }}
        placeholder={placeholder ?? PLACEHOLDERS[hint]} aria-label="Message the AI"
        className={clsx("no-focus-ring min-w-0 flex-1 resize-none bg-transparent py-2.5 focus:outline-none placeholder:text-[var(--ink-muted)]",
          large ? "text-h3" : "text-body-lg")} />
      <button type="button" aria-label="Attach (coming soon)" title="Attachments are not supported yet" disabled
        className="mb-1.5 rounded-full p-2 text-[var(--ink-faint)]"><Icon name="clip" size={20} /></button>
      <button type="button" aria-label="Voice (coming soon)" title="Voice input is not supported yet" disabled
        className="mb-1.5 hidden rounded-full p-2 text-[var(--ink-faint)] sm:block"><Icon name="mic" size={20} /></button>
      <button type="button" onClick={send} disabled={busy || !text.trim()} aria-label="Send"
        className={clsx("mb-0.5 flex shrink-0 items-center justify-center rounded-full bg-[var(--action)] text-[var(--action-ink)] transition-opacity disabled:opacity-60",
          large ? "h-14 w-14" : "h-11 w-11")}>
        {busy ? <span className="h-4 w-4 animate-spin rounded-full border-2 border-[var(--surface-4)] border-t-[var(--action-ink)]" />
          : <Icon name="wave" size={large ? 24 : 20} strokeWidth={2} />}
      </button>
    </div>
  );
}

export function ChipRow({ onPick }: { onPick: (prompt: string) => void }) {
  return (
    <div className="flex flex-wrap justify-center gap-3">
      {CHIPS.map((c) => (
        <button key={c.key} onClick={() => onPick(c.prompt)}
          className="flex items-center gap-2 rounded-full border border-[var(--hairline-strong)] px-5 py-2.5 text-body-lg text-[var(--ink-secondary)] transition-colors hover:bg-[var(--surface-3)] hover:text-[var(--ink-primary)]">
          <Icon name={c.icon} size={17} /> {c.label}
        </button>
      ))}
    </div>
  );
}

/* ─────────────────────────── messages ─────────────────────────── */

export function MessageList({ messages, pending, compact = false }: {
  messages: ChatMessage[]; pending?: string | null; compact?: boolean;
}) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [messages.length, pending]);
  return (
    <div className={clsx("flex flex-col", compact ? "gap-4" : "gap-7")}>
      {messages.map((m) => <Message key={m.id} message={m} compact={compact} />)}
      {pending && (
        <>
          <UserBubble text={pending} />
          <div className="flex items-center gap-2 text-small text-[var(--ink-muted)]">
            <span className="flex gap-1">
              {[0, 1, 2].map((i) => <span key={i} className="h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--ink-muted)]" style={{ animationDelay: `${i * 150}ms` }} />)}
            </span>
            Checking the numbers…
          </div>
        </>
      )}
      <div ref={end} />
    </div>
  );
}

function UserBubble({ text }: { text: string }) {
  return (
    <div className="flex justify-end">
      <div className="max-w-[80%] whitespace-pre-wrap rounded-[22px] bg-[var(--surface-3)] px-4 py-2.5 text-body-lg">{text}</div>
    </div>
  );
}

function Message({ message, compact }: { message: ChatMessage; compact: boolean }) {
  if (message.role === "user") return <UserBubble text={message.content} />;
  const g = message.meta.grounding;
  return (
    <div className="flex gap-3">
      <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-[var(--surface-3)] text-[var(--accent)]">
        <Icon name="sparkle" size={15} />
      </span>
      <div className="min-w-0 flex-1">
        <div className={clsx("space-y-3 leading-relaxed text-[var(--ink-primary)]", compact ? "text-body" : "text-body-lg")}>
          {message.content.split(/\n{2,}/).map((para, i) => <p key={i} className="whitespace-pre-wrap">{para}</p>)}
        </div>
        {message.cards.length > 0 && (
          <div className="mt-4 space-y-3">
            {message.cards.map((card, i) => <Card key={i} card={card} compact={compact} />)}
          </div>
        )}
        <div className="mt-3 flex flex-wrap items-center gap-2 text-caption text-[var(--ink-faint)]">
          {g && (
            <span title={g.unverified_numbers.length ? `Unverified: ${g.unverified_numbers.join(", ")}` : "Every figure matched a backend measurement"}
              className={clsx("inline-flex items-center gap-1 rounded-full border px-2 py-[1px]",
                g.is_grounded ? "border-[color-mix(in_oklab,var(--up)_35%,transparent)] text-[var(--up)]"
                  : "border-[color-mix(in_oklab,var(--warning)_45%,transparent)] text-[var(--warning-ink)]")}>
              {g.is_grounded
                ? `${g.numbers_checked} figure${g.numbers_checked === 1 ? "" : "s"} verified`
                : `${g.unverified_numbers.length} figure(s) unverified`}
            </span>
          )}
          {message.meta.used_fallback && <span title={message.meta.fallback_reason ?? ""}>Template answer</span>}
          {message.meta.tools_called?.length ? <span>· {message.meta.tools_called.map((t) => t.replace(/_/g, " ")).join(", ")}</span> : null}
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────── cards ─────────────────────────── */

function Shell({ title, aside, children }: { title: ReactNode; aside?: ReactNode; children: ReactNode }) {
  return (
    <div className="@container overflow-hidden rounded-[var(--radius)] border border-[var(--hairline-strong)] bg-[var(--surface-1)]">
      <div className="flex items-center justify-between gap-3 border-b border-[var(--hairline)] px-4 py-2.5">
        <div className="text-body font-medium">{title}</div>
        {aside}
      </div>
      <div className="px-4 py-3">{children}</div>
    </div>
  );
}

function Card({ card, compact }: { card: ChatCard; compact: boolean }) {
  switch (card.type) {
    case "order_proposal": return <OrderProposalCard card={card} />;
    case "autopilot_proposal": return <AutopilotCard card={card} />;
    case "swing_plan": return <SwingPlanCard card={card} />;
    case "model_signals": return <ModelSignalsCard card={card} />;
    case "allocation": return (
      <Shell title={<span className="flex items-center gap-2"><Icon name="brain" size={15} className="text-[var(--accent)]" /> Plan for {inr(card.amount, 0)}{card.horizon === "long_term" ? " · long term" : ""}</span>}
        aside={<Link href="/market/model-picks#invest-amount" className="text-small text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]">Planner →</Link>}>
        <AllocationResult plan={card} compact={compact} />
      </Shell>
    );
    case "portfolio_review": return <ReviewBody review={card} compact />;
    case "autopilot_status": return (
      <Shell title={<span className="flex items-center gap-2"><Icon name="bolt" size={15} className="text-[var(--accent)]" /> Autopilot · {card.settings.enabled ? "on" : "off"}</span>}
        aside={<Link href="/autopilot" className="text-small text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]">Open →</Link>}>
        <div className="grid grid-cols-3 gap-3">
          <Fig label="Budget" value={inr(card.settings.budget, 0)} />
          <Fig label="Value" value={inr(card.sleeve_value, 0)} />
          <Fig label="P&L" value={`${card.pnl >= 0 ? "+" : ""}${inr(card.pnl, 0)}`} />
        </div>
        {card.holdings.length > 0 && <p className="mt-2 text-small text-[var(--ink-secondary)]">{card.holdings.map((h) => `${h.symbol} ×${h.quantity}`).join(", ")}</p>}
      </Shell>
    );
    case "backtest": return <BacktestCard card={card} compact={compact} />;
    case "screener": return (
      <Shell title={card.screen.name} aside={<Link href={`/market/screener?id=${card.screen.id}`} className="text-small text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]">Open screen →</Link>}>
        <p className="mb-2 text-small text-[var(--ink-muted)]">{card.matches} of {card.universe_size} stocks match.</p>
        <StockRows rows={card.results.slice(0, 6).map((r) => ({ symbol: r.symbol, name: r.name, ltp: r.close as number, change_pct: r.change_1d_pct as number }))} />
      </Shell>
    );
    case "ideas": return <IdeasCard card={card} />;
    case "option_summary": return (
      <Shell title={`${card.underlying} options · ${shortExpiry(card.expiry)}`} aside={<SourceTag source="live" />}>
        <div className="grid grid-cols-2 gap-3 @lg:grid-cols-4">
          <Fig label="Spot" value={num(card.spot)} sub={<Change value={card.spot_change_pct} />} />
          <Fig label="PCR" value={card.pcr?.toFixed(2) ?? "—"} />
          <Fig label="Support" value={card.support != null ? num(card.support, 0) : "—"} sub="max put OI" />
          <Fig label="Resistance" value={card.resistance != null ? num(card.resistance, 0) : "—"} sub="max call OI" />
          <Fig label="Max pain" value={num(card.max_pain, 0)} />
          <Fig label={`ATM ${card.atm_strike} CE`} value={inr(card.atm_call_premium)} />
          <Fig label={`ATM ${card.atm_strike} PE`} value={inr(card.atm_put_premium)} />
          <Fig label="ATM IV" value={card.atm_iv != null ? `${card.atm_iv.toFixed(2)}%` : "—"} />
        </div>
        <Link href={`/market/option-chain?u=${card.underlying}`} className="mt-3 inline-block text-small text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]">Open option chain →</Link>
      </Shell>
    );
    case "quote": return <QuoteCard card={card} />;
    case "movers": return (
      <Shell title={card.kind === "losers" ? "Top losers" : card.kind === "movers" ? "Top movers" : "Top gainers"} aside={<Link href="/market" className="text-small text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]">Markets →</Link>}>
        <div className="mb-3 flex flex-wrap gap-x-5 gap-y-1 text-small">
          {card.indices.filter((i) => i.symbol !== "INDIAVIX").slice(0, 4).map((i) => (
            <span key={i.symbol}><span className="font-medium">{i.symbol}</span> <span className="tabular">{num(i.ltp)}</span> <Change value={i.change_pct} /></span>
          ))}
        </div>
        <StockRows rows={card.stocks.slice(0, 6)} />
      </Shell>
    );
  }
}

function Fig({ label, value, sub }: { label: string; value: ReactNode; sub?: ReactNode }) {
  return (
    <div>
      <div className="text-micro uppercase tracking-[0.1em] text-[var(--ink-muted)]">{label}</div>
      <div className="tabular text-body-lg">{value}</div>
      {sub && <div className="text-caption text-[var(--ink-muted)]">{sub}</div>}
    </div>
  );
}

function StockRows({ rows }: { rows: { symbol: string; name?: string; ltp: number; change_pct: number }[] }) {
  return (
    <ul className="divide-y divide-[var(--hairline)]">
      {rows.map((r) => (
        <li key={r.symbol}>
          <Link href={`/chart?symbol=${r.symbol}`} className="flex items-center justify-between gap-3 py-2 hover:opacity-80">
            <span className="min-w-0 truncate"><span className="font-medium">{r.symbol}</span> {r.name && <span className="text-small text-[var(--ink-muted)]">{r.name}</span>}</span>
            <span className="flex shrink-0 items-center gap-4"><span className="tabular">{num(r.ltp)}</span><Change value={r.change_pct} className="w-16 text-right" /></span>
          </Link>
        </li>
      ))}
    </ul>
  );
}

function OrderProposalCard({ card }: { card: Extract<ChatCard, { type: "order_proposal" }> }) {
  const [state, setState] = useState<"idle" | "busy" | "done" | "error">("idle");
  const [result, setResult] = useState<PaperOrder | null>(null);
  const [error, setError] = useState<string | null>(null);
  const ticket = useOrderTicket();
  const o = card.order;

  async function confirm() {
    setState("busy");
    try {
      const placed = await trade.placeOrder({
        instrument: o.instrument, symbol: o.symbol, side: o.side, order_type: o.order_type,
        limit_price: o.limit_price, tag: "ai",
        ...(o.instrument === "option"
          ? { lots: o.lots, option_type: o.option_type, strike: o.strike, expiry: o.expiry }
          : { quantity: o.quantity, product: "delivery" }),
      });
      setResult(placed);
      setState("done");
      window.dispatchEvent(new CustomEvent("paper-order", { detail: placed }));
    } catch (err) {
      setError((err as Error).message);
      setState("error");
    }
  }

  return (
    <Shell title={<span className="flex items-center gap-2">
      <span className={clsx("rounded-full px-2 py-0.5 text-caption font-semibold uppercase text-white", o.side === "buy" ? "bg-[var(--buy)]" : "bg-[var(--sell)]")}>{o.side}</span>
      <span className="tabular">{o.display_symbol}</span>
    </span>} aside={<SourceTag source={card.price_source} />}>
      <div className="grid grid-cols-3 gap-3">
        <Fig label="Quantity" value={o.instrument === "option" ? `${o.lots} lot${o.lots === 1 ? "" : "s"} (${o.quantity})` : whole(o.quantity)} />
        <Fig label="Last price" value={inr(card.ltp)} />
        <Fig label="Approx. value" value={inr(card.estimated_value)} />
      </div>
      {state === "done" && result && (
        <p className={clsx("mt-3 text-small", result.status === "filled" ? "text-[var(--up)]" : result.status === "rejected" ? "text-[var(--down)]" : "text-[var(--ink-secondary)]")}>
          {result.status === "filled" ? `Filled ${result.quantity} at ${inr(result.fill_price)}. ` : result.status === "rejected" ? `Rejected: ${result.reject_reason}` : "Order placed and resting."}
          {result.status === "filled" && <Link href="/portfolio" className="underline">View portfolio</Link>}
        </p>
      )}
      {state === "error" && <p className="mt-3 text-small text-[var(--down)]">{error}</p>}
      {state !== "done" && (
        <div className="mt-3 flex gap-2">
          <button onClick={confirm} disabled={state === "busy"}
            className={clsx("rounded-full px-5 py-2 text-body font-semibold text-white disabled:opacity-60", o.side === "buy" ? "bg-[var(--buy)]" : "bg-[var(--sell)]")}>
            {state === "busy" ? "Placing…" : "Confirm paper order"}
          </button>
          <button onClick={() => ticket.open({ instrument: o.instrument, symbol: o.symbol, side: o.side, option_type: o.option_type, strike: o.strike, expiry: o.expiry, quantity: o.instrument === "option" ? o.lots : o.quantity, lot_size: o.lot_size, ltp: card.ltp, tag: "ai" })}
            className="rounded-full border border-[var(--hairline-strong)] px-4 py-2 text-body text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]">
            Edit
          </button>
        </div>
      )}
      <p className="mt-2 text-micro text-[var(--ink-faint)]">Nothing is placed until you confirm. Paper trading only.</p>
    </Shell>
  );
}

const whole = (n: number) => n.toLocaleString("en-IN");

function SwingPlanCard({ card }: { card: Extract<ChatCard, { type: "swing_plan" }> }) {
  const [state, setState] = useState<"idle" | "busy" | "done" | "error">("idle");
  const [placed, setPlaced] = useState<PaperOrder[]>([]);
  const [error, setError] = useState<string | null>(null);
  const legs = card.positions.filter((p) => p.quantity > 0);
  async function confirm() {
    setState("busy");
    try {
      const r = await signals.execute(legs.map((p) => ({ symbol: p.symbol, quantity: p.quantity })));
      setPlaced(r.orders);
      setState("done");
      window.dispatchEvent(new CustomEvent("paper-order"));
    } catch (err) { setError((err as Error).message); setState("error"); }
  }
  return (
    <Shell title={<span className="flex items-center gap-2"><Icon name="brain" size={15} className="text-[var(--accent)]" /> Swing plan · {inr(card.amount, 0)} · <span className="capitalize">{card.profile.name}</span></span>}>
      <table className="w-full text-small">
        <thead><tr className="text-left text-caption text-[var(--ink-muted)]"><th className="pb-1.5 font-normal">Stock</th><th className="pb-1.5 text-right font-normal">Qty</th><th className="pb-1.5 text-right font-normal">Price</th><th className="pb-1.5 text-right font-normal">Stop</th><th className="pb-1.5 text-right font-normal">Target</th></tr></thead>
        <tbody className="divide-y divide-[var(--hairline)]">
          {card.positions.map((p) => (
            <tr key={p.symbol}><td className="py-1.5"><span className="font-medium">{p.symbol}</span> <span className="text-[var(--ink-muted)]">#{p.rank}</span></td>
              <td className="tabular py-1.5 text-right">{p.quantity}</td><td className="tabular py-1.5 text-right">{num(p.price)}</td>
              <td className="tabular py-1.5 text-right text-[var(--down)]">{num(p.stop)}</td><td className="tabular py-1.5 text-right text-[var(--up)]">{num(p.target)}</td></tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 flex justify-between text-small text-[var(--ink-secondary)]"><span>Invested {inr(card.invested)}</span><span>Kept in cash {inr(card.cash_reserve)}</span></div>
      <ul className="mt-2 space-y-1 text-caption text-[var(--ink-muted)]">{card.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      {state === "done" ? (
        <p className="mt-3 text-small text-[var(--up)]">{placed.filter((p) => p.status === "filled").length} of {legs.length} orders filled. <Link href="/portfolio" className="underline">View portfolio</Link></p>
      ) : (
        <button onClick={confirm} disabled={state === "busy" || legs.length === 0} className="mt-3 rounded-full bg-[var(--action)] px-5 py-2 text-body font-semibold text-[var(--action-ink)] disabled:opacity-60">
          {state === "busy" ? "Placing…" : "Place on paper"}
        </button>
      )}
      {error && <p className="mt-2 text-small text-[var(--down)]">{error}</p>}
      <p className="mt-2 text-micro text-[var(--ink-faint)]">{card.disclaimer}</p>
    </Shell>
  );
}

function ModelSignalsCard({ card }: { card: Extract<ChatCard, { type: "model_signals" }> }) {
  if ("picks" in card) {
    return (
      <Shell title={<span className="flex items-center gap-2"><Icon name="brain" size={15} className="text-[var(--accent)]" /> Model picks · {card.as_of}</span>}
        aside={<Link href="/market/model-picks" className="text-small text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]">All picks →</Link>}>
        <table className="w-full text-small">
          <tbody className="divide-y divide-[var(--hairline)]">
            {card.picks.slice(0, 6).map((p) => (
              <tr key={p.symbol}>
                <td className="py-1.5"><span className="text-[var(--ink-muted)]">#{p.rank}</span> <Link href={`/chart?symbol=${p.symbol}`} className="font-medium hover:underline">{p.symbol}</Link></td>
                <td className="py-1.5 text-right"><RangeBar low={p.range_10d?.low ?? null} mid={p.range_10d?.mid ?? null} high={p.range_10d?.high ?? null} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-micro text-[var(--ink-faint)]">80% range for the next {card.horizon_sessions} sessions. {card.disclaimer}</p>
      </Shell>
    );
  }
  if (!card.eligible) {
    return <Shell title={`${card.symbol} · model view`}><p className="text-small text-[var(--ink-secondary)]">{card.reason}</p></Shell>;
  }
  return (
    <Shell title={<span className="flex items-center gap-2"><Icon name="brain" size={15} className="text-[var(--accent)]" /> {card.symbol} · ranked {card.rank} of {card.of}</span>}>
      <RangeBar low={card.range_10d?.low ?? null} mid={card.range_10d?.mid ?? null} high={card.range_10d?.high ?? null} />
      <div className="mt-3 grid grid-cols-3 gap-3">
        <Fig label="Volatility" value={card.vol_annual != null ? `${(card.vol_annual * 100).toFixed(0)}%` : "—"} />
        <Fig label="Stop" value={num(card.stop)} />
        <Fig label="Target" value={num(card.target)} />
      </div>
      <ul className="mt-3 space-y-1 text-caption text-[var(--ink-secondary)]">
        {card.drivers.map((d) => <li key={d.feature}>{d.effect === "raises" ? "↑" : "↓"} {d.label} ({d.percentile}th percentile)</li>)}
      </ul>
      <p className="mt-2 text-micro text-[var(--ink-faint)]">{card.disclaimer}</p>
    </Shell>
  );
}

function AutopilotCard({ card }: { card: Extract<ChatCard, { type: "autopilot_proposal" }> }) {
  const [state, setState] = useState<"idle" | "busy" | "done" | "error">("idle");
  const [placed, setPlaced] = useState<PaperOrder[]>([]);
  const [error, setError] = useState<string | null>(null);
  async function confirm() {
    setState("busy");
    try {
      const r = await trade.autopilot(card.basket.map((b) => ({ symbol: b.symbol, quantity: b.quantity })), card.amount);
      setPlaced(r.orders);
      setState("done");
      window.dispatchEvent(new CustomEvent("paper-order"));
    } catch (err) { setError((err as Error).message); setState("error"); }
  }
  return (
    <Shell title={<span className="flex items-center gap-2"><Icon name="bolt" size={15} className="text-[var(--accent)]" /> Autopilot basket · {inr(card.amount, 0)}</span>}>
      <table className="w-full text-small">
        <thead><tr className="text-left text-caption text-[var(--ink-muted)]"><th className="pb-1.5 font-normal">Stock</th><th className="pb-1.5 text-right font-normal">Price</th><th className="pb-1.5 text-right font-normal">Qty</th><th className="pb-1.5 text-right font-normal">Cost</th></tr></thead>
        <tbody className="divide-y divide-[var(--hairline)]">
          {card.basket.map((b) => (
            <tr key={b.symbol}><td className="py-1.5"><span className="font-medium">{b.symbol}</span> <span className="text-[var(--ink-muted)]">{b.sector}</span></td>
              <td className="tabular py-1.5 text-right">{num(b.ltp)}</td><td className="tabular py-1.5 text-right">{b.quantity}</td><td className="tabular py-1.5 text-right">{inr(b.cost)}</td></tr>
          ))}
        </tbody>
      </table>
      <div className="mt-2 flex justify-between text-small text-[var(--ink-secondary)]"><span>Invested {inr(card.invested)}</span><span>Left in cash {inr(card.uninvested)}</span></div>
      <p className="mt-2 text-caption text-[var(--ink-muted)]">{card.method}</p>
      {state === "done" ? (
        <p className="mt-3 text-small text-[var(--up)]">{placed.filter((p) => p.status === "filled").length} of {card.basket.length} orders filled. Autopilot now rebalances this sleeve on its own. <Link href="/autopilot" className="underline">Open Autopilot</Link></p>
      ) : (
        <button onClick={confirm} disabled={state === "busy"} className="mt-3 rounded-full bg-[var(--action)] px-5 py-2 text-body font-semibold text-[var(--action-ink)] disabled:opacity-60">
          {state === "busy" ? "Placing…" : "Start Autopilot"}
        </button>
      )}
      {error && <p className="mt-2 text-small text-[var(--down)]">{error}</p>}
      <p className="mt-2 text-micro text-[var(--ink-faint)]">{card.disclaimer}</p>
    </Shell>
  );
}

export function BacktestCard({ card, compact = false }: { card: Extract<ChatCard, { type: "backtest" }> | (Omit<Extract<ChatCard, { type: "backtest" }>, "type">); compact?: boolean }) {
  const data = card.equity_curve.map((p) => ({ ...p, label: new Date(p.time * 1000).toLocaleDateString("en-GB", { month: "short", year: "2-digit" }) }));
  return (
    <Shell title={`${card.strategy.name} · ${card.symbol}`} aside={<span className="text-caption text-[var(--ink-muted)]">{card.start} → {card.end}</span>}>
      <div className="grid grid-cols-3 gap-3 @xl:grid-cols-6">
        <Fig label="Return" value={<span className={tone(card.total_return_pct)}>{pct(card.total_return_pct)}</span>} />
        <Fig label="Buy & hold" value={<span className={tone(card.buy_and_hold_return_pct)}>{pct(card.buy_and_hold_return_pct)}</span>} />
        <Fig label="Max DD" value={pct(card.max_drawdown_pct)} />
        <Fig label="Sharpe" value={card.sharpe_ratio?.toFixed(2) ?? "—"} />
        <Fig label="Trades" value={card.trades} />
        <Fig label="Win rate" value={card.win_rate_pct !== null ? `${card.win_rate_pct.toFixed(1)}%` : "—"} />
      </div>
      <div className={clsx("mt-3", compact ? "h-36" : "h-48")}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="label" tick={{ fill: "var(--ink-muted)", fontSize: 11 }} tickLine={false} axisLine={false} minTickGap={40} />
            <YAxis tick={{ fill: "var(--ink-muted)", fontSize: 11 }} tickLine={false} axisLine={false} width={44} domain={["auto", "auto"]} tickFormatter={(v: number) => v.toFixed(2)} />
            <Tooltip contentStyle={{ background: "var(--surface-2)", border: "1px solid var(--hairline-strong)", borderRadius: 8, fontSize: 12 }} formatter={(v: number) => v.toFixed(3)} />
            <Line type="monotone" dataKey="strategy" name="Strategy" stroke="var(--accent)" dot={false} strokeWidth={1.8} />
            <Line type="monotone" dataKey="buy_and_hold" name="Buy & hold" stroke="var(--ink-muted)" dot={false} strokeWidth={1.2} strokeDasharray="4 3" />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-1 text-micro text-[var(--ink-faint)]">Growth of ₹1. {card.assumptions[1]} Past results do not predict future ones.</p>
    </Shell>
  );
}

function IdeasCard({ card }: { card: Extract<ChatCard, { type: "ideas" }> }) {
  const ticket = useOrderTicket();
  return (
    <Shell title={`${card.kind === "fno" ? "F&O" : card.kind[0].toUpperCase() + card.kind.slice(1)} ideas`}
      aside={<Link href={`/market/recommendations?kind=${card.kind}`} className="text-small text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]">All ideas →</Link>}>
      <ul className="divide-y divide-[var(--hairline)]">
        {card.ideas.slice(0, 4).map((i) => (
          <li key={i.id} className="flex items-center justify-between gap-3 py-2.5">
            <div className="min-w-0">
              <div className="font-medium">{i.instrument === "equity" ? `${i.side === "buy" ? "Buy" : "Sell"} ${i.symbol}` : i.name}</div>
              <div className="truncate text-caption text-[var(--ink-muted)]">
                {i.instrument === "equity"
                  ? `Entry ${num(i.entry)} · SL ${num(i.stop_loss)} · Target ${num(i.target)}`
                  : `${i.legs.length} legs · max profit ${inr(i.max_profit, 0)} · max loss ${inr(i.max_loss, 0)}`}
              </div>
            </div>
            {i.instrument === "equity" && (
              <button onClick={() => ticket.open({ instrument: "equity", symbol: i.symbol, side: i.side, ltp: i.ltp, tag: "strategy:idea" })}
                className={clsx("shrink-0 rounded-full px-3 py-1 text-small font-semibold text-white", i.side === "buy" ? "bg-[var(--buy)]" : "bg-[var(--sell)]")}>
                {i.side === "buy" ? "Buy" : "Sell"}
              </button>
            )}
          </li>
        ))}
      </ul>
      <p className="mt-2 text-micro text-[var(--ink-faint)]">{card.disclaimer}</p>
    </Shell>
  );
}

function QuoteCard({ card }: { card: Extract<ChatCard, { type: "quote" }> }) {
  const ticket = useOrderTicket();
  return (
    <Shell title={<span>{card.symbol} <span className="text-small font-normal text-[var(--ink-muted)]">{card.name}</span></span>} aside={<SourceTag source={card.source} />}>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="tabular text-h2">{num(card.ltp)}</div>
          <div className="text-small"><span className={tone(card.change)}>{card.change >= 0 ? "+" : ""}{num(card.change)}</span> <Change value={card.change_pct} parens /></div>
        </div>
        <div className="grid grid-cols-3 gap-4 text-small @max-sm:w-full">
          <Fig label="Open" value={num(card.open)} /><Fig label="High" value={num(card.high)} /><Fig label="Low" value={num(card.low)} />
        </div>
      </div>
      <div className="mt-3 flex gap-2">
        <Link href={`/chart?symbol=${card.symbol}`} className="rounded-full border border-[var(--hairline-strong)] px-4 py-1.5 text-small hover:bg-[var(--surface-3)]">Chart</Link>
        {card.kind === "equity" && <>
          <button onClick={() => ticket.open({ instrument: "equity", symbol: card.symbol, side: "buy", ltp: card.ltp })} className="rounded-full bg-[var(--buy)] px-4 py-1.5 text-small font-semibold text-white">Buy</button>
          <button onClick={() => ticket.open({ instrument: "equity", symbol: card.symbol, side: "sell", ltp: card.ltp })} className="rounded-full bg-[var(--sell)] px-4 py-1.5 text-small font-semibold text-white">Sell</button>
        </>}
      </div>
    </Shell>
  );
}

