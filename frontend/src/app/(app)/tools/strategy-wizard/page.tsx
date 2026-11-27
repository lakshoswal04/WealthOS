"use client";

import clsx from "clsx";
import { useState } from "react";
import { TradeHead } from "@/components/trade/app-shell";
import { UnderlyingSelect } from "@/components/trade/oi";
import { PayoffChart, PayoffSummary } from "@/components/trade/payoff";
import { DataUnavailable, Loading, Panel } from "@/components/trade/primitives";
import { research, unavailableFrom, type Payoff, type Unavailable } from "@/lib/trade-api";

const VIEWS = [
  { key: "bullish", label: "Bullish", hint: "Expect a rise", strategy: "Bull call spread" },
  { key: "bearish", label: "Bearish", hint: "Expect a fall", strategy: "Bear put spread" },
  { key: "neutral", label: "Range-bound", hint: "Expect little movement", strategy: "Iron condor" },
  { key: "volatile", label: "Big move", hint: "Expect a large move, either way", strategy: "Long straddle" },
];

export default function StrategyWizardPage() {
  const [underlying, setUnderlying] = useState("NIFTY");
  const [view, setView] = useState<string | null>(null);
  const [payoff, setPayoff] = useState<Payoff | null>(null);
  const [failure, setFailure] = useState<Unavailable | null>(null);
  const [busy, setBusy] = useState(false);

  async function pick(v: string) {
    setView(v); setBusy(true); setFailure(null); setPayoff(null);
    try { setPayoff(await research.wizard(underlying, v)); }
    catch (err) { setFailure(unavailableFrom(err)); }
    finally { setBusy(false); }
  }

  return (
    <div className="mx-auto max-w-[1100px]">
      <TradeHead title="Strategy wizard" lede="Tell it your view; it builds a defined-risk strategy sized from the expected move the live chain implies."
        aside={<UnderlyingSelect value={underlying} onChange={(u) => { setUnderlying(u); setView(null); setPayoff(null); }} />} />
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {VIEWS.map((v) => (
          <button key={v.key} onClick={() => pick(v.key)}
            className={clsx("rounded-[var(--radius-lg)] border p-5 text-left transition-colors",
              view === v.key ? "border-[var(--ink-secondary)] bg-[var(--surface-2)]" : "border-[var(--hairline)] bg-[var(--surface-1)] hover:border-[var(--hairline-strong)]")}>
            <div className="text-h3 font-semibold">{v.label}</div>
            <div className="mt-1 text-body text-[var(--ink-secondary)]">{v.hint}</div>
            <div className="mt-3 text-small text-[var(--ink-muted)]">→ {v.strategy}</div>
          </button>
        ))}
      </div>
      <div className="mt-8 space-y-5">
        {busy && <Loading label="Pricing from the live chain" />}
        {failure && <DataUnavailable failure={failure} />}
        {payoff && (<><Panel className="p-4"><PayoffChart payoff={payoff} /></Panel><PayoffSummary payoff={payoff} /></>)}
        {!view && <Panel className="p-10 text-center text-body text-[var(--ink-muted)]">Pick a view to build a strategy. Educational, not advice.</Panel>}
      </div>
    </div>
  );
}
