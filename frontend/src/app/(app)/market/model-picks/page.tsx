"use client";

import clsx from "clsx";
import Link from "next/link";
import { useState } from "react";
import { RangeBar } from "@/components/charts/swing";
import { TradeHead } from "@/components/trade/app-shell";
import { AllocationPlanner } from "@/components/trade/autopilot-ui";
import { useOrderTicket } from "@/components/trade/order-ticket";
import { DataUnavailable, Icon, Loading, Panel, Segmented } from "@/components/trade/primitives";
import { percent } from "@/lib/format";
import { usePoll } from "@/lib/hooks";
import { inr, num } from "@/lib/tfmt";
import {
  signals, unavailableFrom, type ModelCard, type Regime, type SignalPick, type SwingPlan, type Unavailable,
} from "@/lib/trade-api";

const STATE_TONE: Record<string, string> = {
  calm: "text-[var(--up)]", normal: "text-[var(--ink-primary)]", stress: "text-[var(--down)]",
};

export default function ModelPicksPage() {
  const [limit, setLimit] = useState<"20" | "60">("20");
  const { data, loading, failure } = usePoll(() => signals.list(Number(limit)), 300_000, [limit]);

  return (
    <div>
      <TradeHead title="Model picks"
        lede="Stocks ranked by the trained swing models for the next two trading weeks, with a calibrated range, a volatility forecast and the reasons behind each score. Research signals for paper trading, not advice."
        aside={<Segmented value={limit} onChange={setLimit} options={[
          { value: "20", label: "Top 20" }, { value: "60", label: "All 60" },
        ]} />} />
      {failure ? <DataUnavailable failure={failure} /> : loading && !data ? <Loading label="Scoring today's stocks" /> : data && (
        <>
          <div className="grid gap-5 xl:grid-cols-[1.1fr_1fr]">
            <RegimeBanner regime={data.regime} />
            <Record card={data.model} />
          </div>
          <Panel className="mt-5 overflow-x-auto">
            <table className="w-full min-w-[980px] text-body">
              <thead>
                <tr className="border-b border-[var(--hairline)] text-left text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">
                  <th className="px-5 py-3 font-medium">Rank</th>
                  <th className="py-3 font-medium">Stock</th>
                  <th className="py-3 text-right font-medium">Score</th>
                  <th className="py-3 pl-6 font-medium">Next 10 sessions (80% range)</th>
                  <th className="py-3 text-right font-medium">Volatility</th>
                  <th className="py-3 text-right font-medium">Stop · target</th>
                  <th className="py-3 pl-6 font-medium">Why</th>
                  <th />
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--hairline)]">
                {data.picks.map((p) => <PickRow key={p.symbol} pick={p} />)}
              </tbody>
            </table>
          </Panel>
          <p className="mt-3 text-caption text-[var(--ink-muted)]">
            As of the {data.as_of} close · {data.universe_size} eligible stocks ({data.model.universe}) · stops and
            targets use your <span className="capitalize">{data.profile.name}</span> profile
            ({data.profile.stop_multiple}× and {data.profile.target_multiple}× the 10-session volatility forecast).
          </p>
          <SwingPlanPanel />
          <div className="mt-8"><AllocationPlanner /></div>
          <p className="mt-6 text-caption text-[var(--ink-faint)]">{data.disclaimer}</p>
        </>
      )}
    </div>
  );
}

function RegimeBanner({ regime }: { regime: Regime }) {
  if (!regime.available || !regime.probabilities) {
    return <Panel className="p-5 text-body text-[var(--ink-muted)]">{regime.reason ?? "Regime unavailable."}</Panel>;
  }
  const p = regime.probabilities;
  return (
    <Panel className="p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-micro uppercase tracking-[0.13em] text-[var(--ink-muted)]">Market regime · {regime.as_of}</div>
          <div className={clsx("mt-1 text-h2 font-semibold capitalize", STATE_TONE[regime.state ?? "normal"])}>{regime.state}</div>
        </div>
        <div className="text-right">
          <div className="text-micro uppercase tracking-[0.13em] text-[var(--ink-muted)]">Base exposure</div>
          <div className="tabular mt-1 text-h3">{percent(regime.base_exposure, 0)}</div>
        </div>
      </div>
      <div className="mt-4 flex h-2 overflow-hidden rounded-full">
        <span style={{ width: `${p.calm * 100}%` }} className="bg-[var(--up)]" />
        <span style={{ width: `${p.normal * 100}%` }} className="bg-[var(--ink-muted)]" />
        <span style={{ width: `${p.stress * 100}%` }} className="bg-[var(--down)]" />
      </div>
      <div className="mt-2 flex justify-between text-caption text-[var(--ink-secondary)]">
        <span>Calm {percent(p.calm, 0)}</span><span>Normal {percent(p.normal, 0)}</span><span>Stress {percent(p.stress, 0)}</span>
      </div>
      <p className="mt-3 text-caption text-[var(--ink-muted)]">
        From NIFTY&apos;s return and volatility and India VIX, using data up to today only. A risk dial for sizing, not a market-timing call.
      </p>
    </Panel>
  );
}

function Record({ card }: { card: ModelCard }) {
  const o = card.oos;
  return (
    <Panel className="p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-micro uppercase tracking-[0.13em] text-[var(--ink-muted)]">Out-of-sample record since {o.first_test_year}</div>
          <div className="mt-1 text-body-lg font-medium">Swing ensemble v{card.version}</div>
        </div>
        <span className={clsx("rounded-full px-2.5 py-0.5 text-caption font-medium",
          card.recommended ? "bg-[color-mix(in_oklab,var(--up)_14%,transparent)] text-[var(--up)]"
            : "bg-[var(--surface-3)] text-[var(--ink-secondary)]")}>
          {card.recommended ? "Passed its deployment gate" : "Research only: gate not passed"}
        </span>
      </div>
      <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
        <Fig label="Rank IC" value={num(o.mean_ic, 3)} sub={o.t_stat ? `t = ${o.t_stat.toFixed(1)}` : undefined} />
        <Fig label="Hit rate" value={percent(o.hit_rate, 1)} sub="vs 50% chance" />
        <Fig label="Top-10 CAGR" value={percent(o.cagr, 1)} sub={`equal-weight ${percent(o.equal_weight_cagr, 1)}`} />
        <Fig label="Worst drawdown" value={percent(o.max_drawdown, 0)} sub={`equal-weight ${percent(o.equal_weight_max_drawdown, 0)}`} />
      </div>
      <div className="mt-4 flex items-center justify-between border-t border-[var(--hairline)] pt-3 text-caption text-[var(--ink-muted)]">
        <span>Trained through {card.trained_through} · after Indian delivery costs</span>
        <Link href="/analysis/swing-lab" className="font-medium text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]">How it was tested →</Link>
      </div>
    </Panel>
  );
}

function Fig({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="text-micro uppercase tracking-[0.1em] text-[var(--ink-muted)]">{label}</div>
      <div className="tabular mt-1 text-h3">{value}</div>
      {sub && <div className="text-caption text-[var(--ink-muted)]">{sub}</div>}
    </div>
  );
}

function PickRow({ pick }: { pick: SignalPick }) {
  const ticket = useOrderTicket();
  const r = pick.range_10d;
  return (
    <tr className="align-top">
      <td className="tabular px-5 py-3 text-[var(--ink-muted)]">{pick.rank}</td>
      <td className="py-3">
        <Link href={`/chart?symbol=${pick.symbol}`} className="font-semibold hover:underline">{pick.symbol}</Link>
        <div className="text-caption text-[var(--ink-muted)]">{pick.name} · {pick.sector}</div>
      </td>
      <td className="tabular py-3 text-right">
        {num(pick.percentile, 0)}<span className="text-caption text-[var(--ink-muted)]">th</span>
      </td>
      <td className="py-3 pl-6"><RangeBar low={r?.low ?? null} mid={r?.mid ?? null} high={r?.high ?? null} /></td>
      <td className="tabular py-3 text-right">{percent(pick.vol_annual, 0)}</td>
      <td className="tabular whitespace-nowrap py-3 text-right text-small leading-relaxed">
        <div className="text-[var(--down)]">{num(pick.stop)}</div>
        <div className="text-[var(--up)]">{num(pick.target)}</div>
      </td>
      <td className="max-w-[340px] py-3 pl-6">
        <div className="flex flex-wrap gap-1.5">
          {pick.drivers.map((d) => (
            <span key={d.feature} title={`${d.label} is at the ${d.percentile}th percentile of the universe; it ${d.effect} the score.`}
              className={clsx("whitespace-nowrap rounded-full border px-2 py-[1px] text-caption",
                d.effect === "raises" ? "border-[color-mix(in_oklab,var(--up)_40%,transparent)] text-[var(--ink-secondary)]"
                  : "border-[color-mix(in_oklab,var(--down)_40%,transparent)] text-[var(--ink-muted)]")}>
              {d.effect === "raises" ? "↑" : "↓"} {d.label}
            </span>
          ))}
        </div>
      </td>
      <td className="py-3 pr-5 text-right">
        <button onClick={() => ticket.open({ instrument: "equity", symbol: pick.symbol, side: "buy", ltp: pick.last_close, tag: "model:swing" })}
          className="whitespace-nowrap rounded-full border border-[var(--hairline-strong)] px-3 py-1 text-small hover:bg-[var(--surface-3)]">
          Paper trade
        </button>
      </td>
    </tr>
  );
}

function SwingPlanPanel() {
  const [amount, setAmount] = useState("100000");
  const [plan, setPlan] = useState<SwingPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Unavailable | null>(null);
  const [placed, setPlaced] = useState<string | null>(null);

  async function build() {
    setBusy(true); setError(null); setPlaced(null);
    try { setPlan(await signals.plan(Number(amount))); }
    catch (err) { setPlan(null); setError(unavailableFrom(err)); }
    finally { setBusy(false); }
  }

  async function place() {
    if (!plan) return;
    setBusy(true); setError(null);
    try {
      const legs = plan.positions.filter((p) => p.quantity > 0).map((p) => ({ symbol: p.symbol, quantity: p.quantity }));
      const res = await signals.execute(legs);
      const filled = res.orders.filter((o) => o.status === "filled").length;
      setPlaced(`${filled} of ${legs.length} paper orders filled. See them in your paper portfolio.`);
      window.dispatchEvent(new CustomEvent("paper-order"));
    } catch (err) { setError(unavailableFrom(err)); }
    finally { setBusy(false); }
  }

  return (
    <Panel id="swing-plan" className="mt-8 p-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h2 className="text-h3 font-semibold">Swing plan</h2>
          <p className="mt-1 max-w-2xl text-body text-[var(--ink-secondary)]">
            A basket built from these picks for your risk profile: sized by forecast volatility, scaled to your volatility target and to today&apos;s regime. Nothing is placed until you confirm.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--ink-muted)]">₹</span>
            <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d]/g, ""))} inputMode="numeric"
              aria-label="Amount to plan"
              className="tabular w-40 rounded-full border border-[var(--hairline-strong)] bg-[var(--surface-2)] py-2 pl-7 pr-4 text-body focus:outline-none" />
          </div>
          <button onClick={build} disabled={busy || Number(amount) < 10_000}
            className="rounded-full bg-[var(--action)] px-5 py-2 text-body font-semibold text-[var(--action-ink)] disabled:opacity-50">
            {busy && !plan ? "Building…" : "Build plan"}
          </button>
        </div>
      </div>

      {error && <div className="mt-5"><DataUnavailable failure={error} compact /></div>}

      {plan && (
        <div className="mt-6">
          <div className="grid grid-cols-2 gap-4 rounded-[var(--radius)] bg-[var(--surface-2)] p-4 sm:grid-cols-4">
            <Fig label="Profile" value={plan.profile.name[0].toUpperCase() + plan.profile.name.slice(1)} />
            <Fig label="Invested" value={inr(plan.invested, 0)} sub={`${percent(plan.invested / plan.amount, 0)} of ${inr(plan.amount, 0)}`} />
            <Fig label="Kept in cash" value={inr(plan.cash_reserve, 0)} />
            <Fig label="Forecast basket vol" value={percent(plan.forecast_portfolio_vol, 0)} sub={`target ${percent(plan.profile.vol_target, 0)}`} />
          </div>
          <table className="mt-4 w-full text-body">
            <thead>
              <tr className="text-left text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">
                <th className="py-2 font-medium">Stock</th><th className="py-2 text-right font-medium">Weight</th>
                <th className="py-2 text-right font-medium">Qty</th><th className="py-2 text-right font-medium">Price</th>
                <th className="py-2 text-right font-medium">Cost</th><th className="py-2 text-right font-medium">Stop</th>
                <th className="py-2 text-right font-medium">Target</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--hairline)]">
              {plan.positions.map((p) => (
                <tr key={p.symbol}>
                  <td className="py-2"><span className="font-semibold">{p.symbol}</span> <span className="text-caption text-[var(--ink-muted)]">#{p.rank}</span></td>
                  <td className="tabular py-2 text-right">{percent(p.weight, 1)}</td>
                  <td className="tabular py-2 text-right">{p.quantity}</td>
                  <td className="tabular py-2 text-right">{num(p.price)}</td>
                  <td className="tabular py-2 text-right">{inr(p.cost, 0)}</td>
                  <td className="tabular py-2 text-right text-[var(--down)]">{num(p.stop)}</td>
                  <td className="tabular py-2 text-right text-[var(--up)]">{num(p.target)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="mt-4 space-y-1.5 text-body text-[var(--ink-secondary)]">
            {plan.notes.map((n) => <li key={n} className="flex gap-2"><span className="text-[var(--ink-faint)]">•</span>{n}</li>)}
          </ul>
          <div className="mt-5 flex flex-wrap items-center justify-between gap-3 border-t border-[var(--hairline)] pt-4">
            <span className="flex items-center gap-2 text-small text-[var(--ink-muted)]"><Icon name="lock" size={14} />Paper trading at real prices. Nothing reaches a broker.</span>
            {placed ? <span className="text-body text-[var(--up)]">{placed}</span> : (
              <button onClick={place} disabled={busy || plan.positions.every((p) => p.quantity === 0)}
                className="rounded-full bg-[var(--buy)] px-5 py-2 text-body font-semibold text-white disabled:opacity-50">
                {busy ? "Placing…" : "Place on paper"}
              </button>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}
