"use client";

import clsx from "clsx";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { TradeHead } from "@/components/trade/app-shell";
import { useOrderTicket } from "@/components/trade/order-ticket";
import { Change, DataUnavailable, Loading, Panel, Segmented, SourceTag } from "@/components/trade/primitives";
import { usePoll } from "@/lib/hooks";
import { trade, type EquityIdea, type FnoIdea } from "@/lib/trade-api";
import { inr, num, shortExpiry } from "@/lib/tfmt";

type Kind = "intraday" | "delivery" | "fno" | "model";

export default function RecommendationsPage() {
  return <Suspense fallback={<Loading />}><Recommendations /></Suspense>;
}

function Recommendations() {
  const params = useSearchParams();
  const initial = params.get("kind") as Kind | null;
  const [kind, setKind] = useState<Kind>(initial && ["intraday", "delivery", "fno", "model"].includes(initial) ? initial : "delivery");
  const { data, loading, failure } = usePoll(() => trade.recommendations(kind, 12), 60_000, [kind]);

  return (
    <div>
      <TradeHead title="Recommendations"
        lede={kind === "model"
          ? "The trained swing models' top-ranked stocks, with stops and targets from each stock's volatility forecast. Research signals, not advice: paper trade them first."
          : "Rule-based setups from the screens and the live option chain. Each one shows the rule that produced it and how its levels were set. Educational, not advice: paper trade them first."}
        aside={<Segmented value={kind} onChange={setKind} options={[
          { value: "intraday", label: "Intraday" }, { value: "delivery", label: "Delivery" }, { value: "fno", label: "F&O" },
          { value: "model", label: "Model" },
        ]} />} />
      {failure ? <DataUnavailable failure={failure} /> : loading && !data ? <Loading label="Finding setups" /> : data && (
        <>
          {data.ideas.length === 0 && <Panel className="p-8 text-body text-[var(--ink-muted)]">No stock meets the {kind} rules right now. Setups appear as the session develops.</Panel>}
          <div className="grid gap-5 lg:grid-cols-2">
            {data.ideas.map((idea) => idea.instrument === "equity"
              ? <EquityCard key={idea.id} idea={idea} />
              : <FnoCard key={idea.id} idea={idea} />)}
          </div>
          <p className="mt-6 text-caption text-[var(--ink-faint)]">{data.disclaimer}</p>
        </>
      )}
    </div>
  );
}

function Level({ label, value, toneClass }: { label: string; value: string; toneClass?: string }) {
  return (
    <div>
      <div className="text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">{label}</div>
      <div className={clsx("tabular text-body-lg", toneClass)}>{value}</div>
    </div>
  );
}

function EquityCard({ idea }: { idea: EquityIdea }) {
  const ticket = useOrderTicket();
  return (
    <Panel className="flex flex-col p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <span className={clsx("rounded-full px-2.5 py-0.5 text-caption font-semibold uppercase text-white", idea.side === "buy" ? "bg-[var(--buy)]" : "bg-[var(--sell)]")}>{idea.side}</span>
            <Link href={`/chart?symbol=${idea.symbol}`} className="text-h3 font-semibold hover:underline">{idea.symbol}</Link>
          </div>
          <div className="mt-1 text-small text-[var(--ink-muted)]">{idea.name} · {idea.sector}</div>
        </div>
        <div className="text-right">
          <div className="tabular text-body-lg">{num(idea.ltp)}</div>
          <Change value={idea.change_pct} className="text-small" />
        </div>
      </div>
      <div className="mt-5 grid grid-cols-4 gap-3 rounded-[var(--radius)] bg-[var(--surface-2)] p-4">
        <Level label="Entry" value={num(idea.entry)} />
        <Level label="Stop loss" value={num(idea.stop_loss)} toneClass="text-[var(--down)]" />
        <Level label="Target" value={num(idea.target)} toneClass="text-[var(--up)]" />
        <Level label="Reward : risk" value={`${idea.risk_reward.toFixed(2)}`} />
      </div>
      <ul className="mt-4 flex-1 space-y-1.5 text-body text-[var(--ink-secondary)]">
        {idea.rationale.map((r) => <li key={r} className="flex gap-2"><span className="text-[var(--ink-faint)]">•</span>{r}</li>)}
      </ul>
      {idea.kind === "model" && <p className="mt-3 text-caption text-[var(--ink-muted)]">{idea.method} <Link href="/analysis/swing-lab" className="underline">How it was tested</Link></p>}
      <div className="mt-5 flex items-center justify-between border-t border-[var(--hairline)] pt-4">
        <span className="text-caption text-[var(--ink-muted)]">{idea.horizon}{idea.atr !== null && ` · ATR ${num(idea.atr)}`} <SourceTag source={idea.price_source} className="ml-2" /></span>
        <button onClick={() => ticket.open({ instrument: "equity", symbol: idea.symbol, side: idea.side, ltp: idea.ltp, tag: idea.kind === "model" ? "model:swing" : "strategy:idea" })}
          className={clsx("rounded-full px-5 py-2 text-body font-semibold text-white", idea.side === "buy" ? "bg-[var(--buy)]" : "bg-[var(--sell)]")}>
          Paper trade
        </button>
      </div>
    </Panel>
  );
}

function FnoCard({ idea }: { idea: FnoIdea }) {
  const ticket = useOrderTicket();
  return (
    <Panel className="flex flex-col p-6">
      <div className="flex items-start justify-between gap-3">
        <div>
          <div className="text-h3 font-semibold">{idea.name}</div>
          <div className="mt-1 text-small capitalize text-[var(--ink-muted)]">{idea.bias} · expiry {shortExpiry(idea.expiry)} · spot {num(idea.spot)}</div>
        </div>
        <SourceTag source="live" />
      </div>
      <table className="mt-5 w-full text-body">
        <thead><tr className="text-left text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]"><th className="pb-2 font-medium">Leg</th><th className="pb-2 text-right font-medium">Premium</th><th /></tr></thead>
        <tbody className="divide-y divide-[var(--hairline)]">
          {idea.legs.map((l) => (
            <tr key={`${l.action}${l.strike}${l.option_type}`}>
              <td className="py-2"><span className={clsx("mr-2 font-semibold uppercase", l.action === "buy" ? "text-[var(--up)]" : "text-[var(--down)]")}>{l.action}</span><span className="tabular">{l.strike} {l.option_type}</span></td>
              <td className="tabular py-2 text-right">{num(l.premium)}</td>
              <td className="py-2 text-right">
                <button onClick={() => ticket.open({ instrument: "option", symbol: idea.symbol, side: l.action, option_type: l.option_type, strike: l.strike, expiry: l.expiry, quantity: 1, lot_size: idea.lot_size, ltp: l.premium, tag: "strategy:fno-idea" })}
                  className="rounded-full border border-[var(--hairline-strong)] px-3 py-0.5 text-small hover:bg-[var(--surface-3)]">Trade leg</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-4 grid grid-cols-3 gap-3 rounded-[var(--radius)] bg-[var(--surface-2)] p-4">
        <Level label={`Net ${idea.net_premium_type}`} value={num(Math.abs(idea.net_premium))} />
        <Level label="Max profit / lot" value={inr(idea.max_profit, 0)} toneClass="text-[var(--up)]" />
        <Level label="Max loss / lot" value={inr(idea.max_loss, 0)} toneClass="text-[var(--down)]" />
      </div>
      <ul className="mt-4 flex-1 space-y-1.5 text-body text-[var(--ink-secondary)]">
        {idea.rationale.map((r) => <li key={r} className="flex gap-2"><span className="text-[var(--ink-faint)]">•</span>{r}</li>)}
      </ul>
      <p className="mt-4 border-t border-[var(--hairline)] pt-3 text-caption text-[var(--ink-muted)]">{idea.method} Lot size {idea.lot_size}; expected move {num(idea.expected_move, 0)} points.</p>
    </Panel>
  );
}
