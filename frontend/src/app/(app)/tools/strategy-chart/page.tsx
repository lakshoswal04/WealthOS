"use client";

import { useEffect, useState } from "react";
import { TradeHead } from "@/components/trade/app-shell";
import { UnderlyingSelect } from "@/components/trade/oi";
import { PayoffChart, PayoffSummary } from "@/components/trade/payoff";
import { DataUnavailable, Icon, Loading, Panel } from "@/components/trade/primitives";
import { usePoll } from "@/lib/hooks";
import { options, research, unavailableFrom, type Payoff, type PayoffLeg, type Unavailable } from "@/lib/trade-api";
import { shortExpiry } from "@/lib/tfmt";

const control = "rounded-[var(--radius-sm)] border border-[var(--hairline-strong)] bg-[var(--surface-2)] px-3 py-2 text-body focus:outline-none";

export default function StrategyChartPage() {
  const [underlying, setUnderlying] = useState("NIFTY");
  const [expiry, setExpiry] = useState<string | null>(null);
  const chain = usePoll(() => options.chain(underlying, expiry, 20), null, [underlying, expiry]);
  const [legs, setLegs] = useState<PayoffLeg[]>([]);
  const [payoff, setPayoff] = useState<Payoff | null>(null);
  const [failure, setFailure] = useState<Unavailable | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (chain.data && legs.length === 0) {
      setLegs([{ option_type: "CE", strike: chain.data.atm_strike, action: "buy", lots: 1 }]);
    }
  }, [chain.data]); // eslint-disable-line react-hooks/exhaustive-deps

  async function draw() {
    setBusy(true); setFailure(null);
    try { setPayoff(await research.payoff(underlying, chain.data?.expiry ?? null, legs)); }
    catch (err) { setFailure(unavailableFrom(err)); setPayoff(null); }
    finally { setBusy(false); }
  }
  const strikes = (chain.data?.rows ?? []).map((r) => r.strike);
  const update = (i: number, patch: Partial<PayoffLeg>) => setLegs((ls) => ls.map((l, j) => (j === i ? { ...l, ...patch } : l)));

  return (
    <div className="mx-auto max-w-[1200px]">
      <TradeHead title="Strategy chart" lede="Build a multi-leg option position from the live chain and see its payoff at expiry and today."
        aside={<UnderlyingSelect value={underlying} onChange={(u) => { setUnderlying(u); setExpiry(null); setLegs([]); setPayoff(null); }} />} />
      {chain.failure ? <DataUnavailable failure={chain.failure} /> : !chain.data ? <Loading /> : (
        <div className="grid gap-6 xl:grid-cols-[400px_1fr]">
          <Panel className="h-fit p-5">
            <label className="mb-4 block text-small text-[var(--ink-muted)]">Expiry
              <select value={expiry ?? chain.data.expiry} onChange={(e) => { setExpiry(e.target.value); setPayoff(null); }} className={`${control} mt-1 w-full`}>
                {chain.data.expiries.map((e) => <option key={e} value={e}>{shortExpiry(e)}</option>)}
              </select>
            </label>
            <div className="space-y-2">
              {legs.map((l, i) => (
                <div key={i} className="flex items-center gap-1.5">
                  <select value={l.action} onChange={(e) => update(i, { action: e.target.value as "buy" | "sell" })} className={control}><option value="buy">Buy</option><option value="sell">Sell</option></select>
                  <input type="number" min={1} value={l.lots} onChange={(e) => update(i, { lots: Math.max(1, Number(e.target.value) || 1) })} className={`${control} w-16`} aria-label="Lots" />
                  <select value={l.strike} onChange={(e) => update(i, { strike: Number(e.target.value) })} className={`${control} flex-1`}>
                    {strikes.map((k) => <option key={k} value={k}>{k}</option>)}
                  </select>
                  <select value={l.option_type} onChange={(e) => update(i, { option_type: e.target.value as "CE" | "PE" })} className={control}><option>CE</option><option>PE</option></select>
                  <button aria-label="Remove leg" onClick={() => setLegs((ls) => ls.filter((_, j) => j !== i))} className="p-1.5 text-[var(--ink-muted)] hover:text-[var(--down)]"><Icon name="x" size={15} /></button>
                </div>
              ))}
            </div>
            <button onClick={() => setLegs((ls) => [...ls, { option_type: "PE" as const, strike: chain.data!.atm_strike, action: "buy" as const, lots: 1 }].slice(0, 6))} disabled={legs.length >= 6}
              className="mt-3 flex items-center gap-1.5 rounded-full border border-[var(--hairline-strong)] px-4 py-2 text-body hover:bg-[var(--surface-3)] disabled:opacity-40">
              <Icon name="plus" size={15} /> Add leg
            </button>
            <button onClick={draw} disabled={busy || !legs.length} className="mt-5 w-full rounded-full bg-[var(--action)] py-3 text-body-lg font-semibold text-[var(--action-ink)] disabled:opacity-60">
              {busy ? "Pricing…" : "Draw payoff"}
            </button>
          </Panel>
          <div className="space-y-5">
            {failure && <DataUnavailable failure={failure} compact />}
            {payoff ? (<><Panel className="p-4"><PayoffChart payoff={payoff} /></Panel><PayoffSummary payoff={payoff} /></>)
              : !failure && <Panel className="p-10 text-center text-body text-[var(--ink-muted)]">Choose legs and draw the payoff. Premiums and IV come from the live chain.</Panel>}
          </div>
        </div>
      )}
    </div>
  );
}
