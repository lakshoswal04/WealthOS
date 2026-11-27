"use client";

import clsx from "clsx";
import Link from "next/link";
import { useState } from "react";
import { RangeBar } from "@/components/charts/swing";
import { percent } from "@/lib/format";
import { usePoll } from "@/lib/hooks";
import { inr, num } from "@/lib/tfmt";
import { autopilot, unavailableFrom, type AllocationPlan, type PortfolioReview, type Unavailable } from "@/lib/trade-api";
import { DataUnavailable, Icon, Loading, Panel, Segmented } from "./primitives";

/* ─────────────────────────── review of real holdings ─────────────────────────── */

export function PortfolioReviewPanel({ compact = false }: { compact?: boolean }) {
  const { data, loading, failure } = usePoll(() => autopilot.review(), 600_000, []);
  if (failure) return <DataUnavailable failure={failure} compact title="Holdings review unavailable" />;
  if (loading && !data) return <Loading label="Reviewing your holdings" />;
  if (!data) return null;
  return <ReviewBody review={data} compact={compact} />;
}

export function ReviewBody({ review, compact = false }: { review: PortfolioReview; compact?: boolean }) {
  if (!review.available) {
    return (
      <Panel className="p-6">
        <div className="flex items-center gap-2 text-body-lg font-semibold"><Icon name="brain" size={18} /> Model review of your holdings</div>
        <p className="mt-2 text-body text-[var(--ink-secondary)]">{review.reason}</p>
        <div className="mt-4 flex gap-2">
          <Link href="/import" className="rounded-full bg-[var(--action)] px-4 py-1.5 text-small font-semibold text-[var(--action-ink)]">Import holdings</Link>
          <Link href="/settings/brokers" className="rounded-full border border-[var(--hairline-strong)] px-4 py-1.5 text-small">Sync from Upstox</Link>
        </div>
      </Panel>
    );
  }
  const rows = review.holdings ?? [];
  return (
    <Panel className="p-6">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div className="flex items-center gap-2 text-body-lg font-semibold"><Icon name="brain" size={18} /> Model review of your holdings</div>
        <span className="text-caption text-[var(--ink-muted)]">As of {review.as_of} · {review.profile.name} profile</span>
      </div>
      <table className="mt-4 w-full text-small">
        <thead><tr className="text-left text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">
          <th className="pb-2 font-medium">Holding</th><th className="pb-2 text-right font-medium">Weight</th>
          <th className="pb-2 pl-4 font-medium">Model view, next 10 sessions</th>{!compact && <th className="pb-2 text-right font-medium">Volatility</th>}
        </tr></thead>
        <tbody className="divide-y divide-[var(--hairline)]">
          {rows.map((h) => (
            <tr key={h.symbol} className="align-top">
              <td className="py-2"><span className="font-medium">{h.symbol}</span> <span className="text-caption text-[var(--ink-muted)]">{h.sector ?? h.asset_class}</span></td>
              <td className="tabular py-2 text-right">{percent(h.weight, 1)}</td>
              <td className="py-2 pl-4">
                {h.model ? (
                  <div className="flex flex-wrap items-center gap-3">
                    <span className="tabular text-caption text-[var(--ink-secondary)]">rank {h.model.rank}/{h.model.of}</span>
                    <RangeBar low={h.model.range_10d?.low ?? null} mid={h.model.range_10d?.mid ?? null} high={h.model.range_10d?.high ?? null} />
                  </div>
                ) : <span className="text-caption text-[var(--ink-muted)]">{h.model_note}</span>}
              </td>
              {!compact && <td className="tabular py-2 text-right">{percent(h.model?.vol_annual, 0)}</td>}
            </tr>
          ))}
        </tbody>
      </table>
      {(review.suggestions ?? []).length > 0 && (
        <ul className="mt-4 space-y-1.5 text-body text-[var(--ink-secondary)]">
          {review.suggestions!.map((s) => <li key={s.text} className="flex gap-2"><span className="text-[var(--ink-faint)]">•</span>{s.text}</li>)}
        </ul>
      )}
      <p className="mt-3 text-caption text-[var(--ink-muted)]">{review.note}</p>
    </Panel>
  );
}

/* ─────────────────────────── planning an amount ─────────────────────────── */

const SECTOR_CHIPS = ["Banking", "IT", "Pharma", "Auto", "FMCG", "Metals", "Power", "Energy", "Capital goods", "Cement", "Realty", "Telecom"];

export function AllocationPlanner() {
  const [amount, setAmount] = useState("50000");
  const [sectors, setSectors] = useState<string[]>([]);
  const [horizon, setHorizon] = useState<"swing" | "long_term">("swing");
  const [plan, setPlan] = useState<AllocationPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Unavailable | null>(null);
  async function go() {
    setBusy(true); setError(null);
    try { setPlan(await autopilot.allocate(Number(amount), sectors.length ? sectors : null, horizon)); }
    catch (err) { setPlan(null); setError(unavailableFrom(err)); }
    finally { setBusy(false); }
  }
  const toggle = (s: string) => setSectors((cur) => cur.includes(s) ? cur.filter((x) => x !== s) : [...cur, s]);
  return (
    <Panel id="invest-amount" className="p-6">
      <h2 className="text-h3 font-semibold">Invest an amount</h2>
      <p className="mt-1 max-w-2xl text-body text-[var(--ink-secondary)]">
        Split an amount across sectors with the models&apos; best-ranked stock in each, sized for your risk profile at live prices. Long term adds a core of index, gold and bond ETFs.
      </p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <div className="relative">
          <span className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--ink-muted)]">₹</span>
          <input value={amount} onChange={(e) => setAmount(e.target.value.replace(/[^\d]/g, ""))} inputMode="numeric" aria-label="Amount to invest"
            className="tabular w-36 rounded-full border border-[var(--hairline-strong)] bg-[var(--surface-2)] py-2 pl-7 pr-4 text-body focus:outline-none" />
        </div>
        <Segmented size="sm" value={horizon} onChange={setHorizon} options={[{ value: "swing", label: "Next 2 weeks" }, { value: "long_term", label: "Long term" }]} />
        <button onClick={go} disabled={busy || Number(amount) < 5000}
          className="rounded-full bg-[var(--action)] px-5 py-2 text-body font-semibold text-[var(--action-ink)] disabled:opacity-50">
          {busy ? "Planning…" : "Plan it"}
        </button>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5">
        {SECTOR_CHIPS.map((s) => (
          <button key={s} onClick={() => toggle(s)} aria-pressed={sectors.includes(s)}
            className={clsx("rounded-full border px-3 py-1 text-small",
              sectors.includes(s) ? "border-[var(--ink-secondary)] bg-[var(--surface-3)] text-[var(--ink-primary)]" : "border-[var(--hairline-strong)] text-[var(--ink-muted)]")}>
            {s}
          </button>
        ))}
        <span className="self-center text-caption text-[var(--ink-faint)]">{sectors.length ? "" : "No sector picked: the models choose"}</span>
      </div>
      {error && <div className="mt-4"><DataUnavailable failure={error} compact /></div>}
      {plan && <div className="mt-5"><AllocationResult plan={plan} /></div>}
    </Panel>
  );
}

export function AllocationResult({ plan, compact = false }: { plan: AllocationPlan; compact?: boolean }) {
  if (plan.available === false) return <p className="text-small text-[var(--ink-secondary)]">{plan.reason}</p>;
  return (
    <div>
      {plan.core.length > 0 && (
        <div className="mb-4">
          <div className="mb-1.5 text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">Long-term core (ETFs, at your broker)</div>
          <div className="grid gap-2 sm:grid-cols-3">
            {plan.core.map((c) => (
              <div key={c.symbol} className="rounded-[var(--radius)] bg-[var(--surface-2)] p-3">
                <div className="font-medium">{c.symbol} <span className="tabular text-[var(--ink-muted)]">{percent(c.weight, 0)}</span></div>
                <div className="text-caption text-[var(--ink-muted)]">{c.what}</div>
                <div className="tabular mt-1">{inr(c.value, 0)}{c.units != null && <span className="text-caption text-[var(--ink-muted)]"> · about {c.units} units</span>}</div>
              </div>
            ))}
          </div>
        </div>
      )}
      {plan.picks.length > 0 && (
        <>
          <div className="mb-1.5 text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">{plan.core.length ? "Satellite: model picks" : "By sector"}</div>
          <table className="w-full text-small">
            <thead><tr className="text-left text-caption text-[var(--ink-muted)]">
              <th className="pb-1.5 font-normal">Sector</th><th className="pb-1.5 font-normal">Stock</th>
              <th className="pb-1.5 text-right font-normal">Qty</th><th className="pb-1.5 text-right font-normal">Cost</th>
              {!compact && <th className="pb-1.5 pl-4 font-normal">80% range, 10 sessions</th>}
              {!compact && <th className="pb-1.5 text-right font-normal">Stop · target</th>}
            </tr></thead>
            <tbody className="divide-y divide-[var(--hairline)]">
              {plan.picks.map((p) => (
                <tr key={p.symbol} className="align-top">
                  <td className="py-1.5 text-[var(--ink-secondary)]">{p.sector}</td>
                  <td className="py-1.5"><Link href={`/chart?symbol=${p.symbol}`} className="font-medium hover:underline">{p.symbol}</Link> <span className="text-caption text-[var(--ink-muted)]">#{p.rank}{p.already_held ? " · held" : ""}</span></td>
                  <td className="tabular py-1.5 text-right">{p.quantity}</td>
                  <td className="tabular py-1.5 text-right">{inr(p.cost, 0)}</td>
                  {!compact && <td className="py-1.5 pl-4"><RangeBar low={p.range_10d?.low ?? null} mid={p.range_10d?.mid ?? null} high={p.range_10d?.high ?? null} /></td>}
                  {!compact && <td className="tabular whitespace-nowrap py-1.5 text-right"><span className="text-[var(--down)]">{num(p.stop)}</span> · <span className="text-[var(--up)]">{num(p.target)}</span></td>}
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <div className="mt-2 flex justify-between text-small text-[var(--ink-secondary)]"><span>Invested {inr(plan.invested, 0)}</span><span>Left over {inr(plan.cash_left, 0)}</span></div>
      <ul className="mt-2 space-y-1 text-caption text-[var(--ink-muted)]">{plan.notes.map((n) => <li key={n}>{n}</li>)}</ul>
      <p className="mt-2 text-micro text-[var(--ink-faint)]">{plan.disclaimer}</p>
    </div>
  );
}
