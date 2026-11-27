"use client";

import clsx from "clsx";
import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { paper, type Payoff } from "@/lib/trade-api";
import { inr, inrSigned, num } from "@/lib/tfmt";
import { Panel, SourceTag } from "./primitives";

const tooltipStyle = { background: "var(--surface-2)", border: "1px solid var(--hairline-strong)", borderRadius: 8, fontSize: 12 };

export function PayoffChart({ payoff }: { payoff: Payoff }) {
  return (
    <div className="h-[360px]">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={payoff.curve} margin={{ top: 10, right: 16, bottom: 4, left: 8 }}>
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey="spot" type="number" domain={["dataMin", "dataMax"]} tick={{ fill: "var(--ink-muted)", fontSize: 11 }}
            tickFormatter={(v: number) => num(v, 0)} tickLine={false} axisLine={{ stroke: "var(--axis)" }} />
          <YAxis tick={{ fill: "var(--ink-muted)", fontSize: 11 }} tickFormatter={(v: number) => `${Math.round(v / 1000)}k`} tickLine={false} axisLine={false} width={48} />
          <Tooltip contentStyle={tooltipStyle} labelFormatter={(l) => `Spot ${num(Number(l), 0)}`} formatter={(v: number, n: string) => [inrSigned(v), n]} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <ReferenceLine y={0} stroke="var(--axis)" />
          <ReferenceLine x={payoff.spot} stroke="var(--ink-secondary)" strokeDasharray="4 4"
            label={{ value: `Spot ${num(payoff.spot, 0)}`, position: "top", fill: "var(--ink-secondary)", fontSize: 11 }} />
          {payoff.breakevens.map((b) => <ReferenceLine key={b} x={b} stroke="var(--accent)" strokeDasharray="2 4" />)}
          <Line dataKey="expiry" name="At expiry" stroke="var(--accent)" dot={false} strokeWidth={2} />
          <Line dataKey="today" name="Today" stroke="var(--series-1)" dot={false} strokeWidth={1.5} strokeDasharray="5 3" connectNulls />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function PayoffSummary({ payoff }: { payoff: Payoff }) {
  const [placing, setPlacing] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  async function placeAll() {
    setPlacing(true); setResult(null);
    const outcomes: string[] = [];
    for (const leg of payoff.legs) {
      try {
        const o = await paper.place({ instrument: "option", symbol: payoff.underlying, side: leg.action, lots: leg.lots,
          option_type: leg.option_type, strike: leg.strike, expiry: payoff.expiry, tag: "strategy:builder" });
        outcomes.push(`${leg.action} ${leg.strike} ${leg.option_type}: ${o.status === "filled" ? `filled at ${num(o.fill_price)}` : o.reject_reason ?? o.status}`);
      } catch (err) { outcomes.push(`${leg.strike} ${leg.option_type}: ${(err as Error).message}`); }
    }
    window.dispatchEvent(new CustomEvent("paper-order"));
    setResult(outcomes.join(" · "));
    setPlacing(false);
  }
  const fig = (label: string, value: string, cls?: string) => (
    <div><div className="text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">{label}</div><div className={clsx("tabular text-body-lg", cls)}>{value}</div></div>
  );
  return (
    <Panel className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="text-body-lg font-semibold">{payoff.strategy ?? "Your strategy"} · {payoff.underlying} {new Date(`${payoff.expiry}T00:00:00`).toLocaleDateString("en-GB", { day: "2-digit", month: "short" })}</div>
        <SourceTag source="live" />
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {fig(`Net ${payoff.net_premium_type}`, inr(Math.abs(payoff.net_premium), 0))}
        {fig("Max profit", payoff.max_profit == null ? "Unlimited" : inr(payoff.max_profit, 0), "text-[var(--up)]")}
        {fig("Max loss", payoff.max_loss == null ? "Unlimited" : inr(Math.abs(payoff.max_loss), 0), "text-[var(--down)]")}
        {fig("Breakeven", payoff.breakevens.length ? payoff.breakevens.map((b) => num(b, 0)).join(" / ") : "—")}
      </div>
      <table className="mt-5 w-full text-body">
        <tbody className="divide-y divide-[var(--hairline)]">
          {payoff.legs.map((l, i) => (
            <tr key={i}>
              <td className={clsx("py-2 font-semibold uppercase", l.action === "buy" ? "text-[var(--up)]" : "text-[var(--down)]")}>{l.action}</td>
              <td className="tabular py-2">{l.lots} × {l.strike} {l.option_type}</td>
              <td className="tabular py-2 text-right">{num(l.premium ?? 0)}</td>
              <td className="tabular py-2 text-right text-[var(--ink-muted)]">IV {l.iv ? (l.iv * 100).toFixed(1) : "—"}%</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <button onClick={placeAll} disabled={placing} className="rounded-full bg-[var(--action)] px-5 py-2.5 text-body font-semibold text-[var(--action-ink)] disabled:opacity-60">
          {placing ? "Placing…" : "Place all legs on paper"}
        </button>
        <span className="text-caption text-[var(--ink-muted)]">Lot size {payoff.lot_size}. {payoff.sizing ?? ""}</span>
      </div>
      {result && <p className="mt-3 text-small text-[var(--ink-secondary)]">{result}</p>}
      <p className="mt-3 text-caption text-[var(--ink-faint)]">{payoff.method}</p>
    </Panel>
  );
}
