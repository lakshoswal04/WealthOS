"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { TradeHead } from "@/components/trade/app-shell";
import { DataUnavailable, Loading, Panel, Segmented } from "@/components/trade/primitives";
import { usePoll } from "@/lib/hooks";
import { research } from "@/lib/trade-api";

const tooltipStyle = { background: "var(--surface-2)", border: "1px solid var(--hairline-strong)", borderRadius: 8, fontSize: 12 };

export default function PairsPage() {
  return <Suspense fallback={<Loading />}><Pairs /></Suspense>;
}

function Pairs() {
  const params = useSearchParams();
  const router = useRouter();
  const view = params.get("view") === "screener" ? "screener" : "builder";
  const a = (params.get("a") ?? "HDFCBANK").toUpperCase();
  const b = (params.get("b") ?? "ICICIBANK").toUpperCase();
  const go = (q: Record<string, string>) => router.push(`/tools/pairs?${new URLSearchParams(q)}`);
  return (
    <div className="mx-auto max-w-[1150px]">
      <TradeHead title={view === "builder" ? "Pair builder" : "Pair screener"}
        lede="Two stocks that usually move together, and how far apart they are now: the ratio's z-score against its own 60-session history."
        aside={<Segmented value={view} onChange={(v) => go(v === "screener" ? { view: "screener" } : { a, b })}
          options={[{ value: "builder", label: "Builder" }, { value: "screener", label: "Screener" }]} />} />
      {view === "builder" ? <Builder a={a} b={b} onPick={(x, y) => go({ a: x, b: y })} /> : <Screener onPick={(x, y) => go({ a: x, b: y })} />}
    </div>
  );
}

function Builder({ a, b, onPick }: { a: string; b: string; onPick: (a: string, b: string) => void }) {
  const [ia, setA] = useState(a);
  const [ib, setB] = useState(b);
  const { data, loading, failure } = usePoll(() => research.pair(a, b), null, [a, b]);
  const input = "w-40 rounded-full border border-[var(--hairline-strong)] bg-[var(--surface-1)] px-4 py-2 text-body uppercase focus:outline-none";
  return (
    <>
      <form onSubmit={(e) => { e.preventDefault(); onPick(ia.trim().toUpperCase(), ib.trim().toUpperCase()); }} className="mb-6 flex flex-wrap items-center gap-3">
        <input value={ia} onChange={(e) => setA(e.target.value)} className={input} aria-label="Stock A" />
        <span className="text-[var(--ink-muted)]">vs</span>
        <input value={ib} onChange={(e) => setB(e.target.value)} className={input} aria-label="Stock B" />
        <button className="rounded-full bg-[var(--action)] px-5 py-2 text-body font-semibold text-[var(--action-ink)]">Compare</button>
      </form>
      {failure ? <DataUnavailable failure={failure} /> : loading && !data ? <Loading /> : data && (
        <div className="space-y-5">
          <Panel className="grid grid-cols-2 gap-5 p-6 sm:grid-cols-5">
            {[["Correlation", data.correlation.toFixed(2)], ["Z-score", data.z_score.toFixed(2)], ["Half-life", data.half_life_days ? `${data.half_life_days} days` : "No mean reversion"],
              ["Hedge ratio", data.hedge_ratio.toFixed(2)], ["Ratio A/B", data.ratio.toFixed(3)]].map(([l, v]) => (
              <div key={l}><div className="text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">{l}</div><div className="tabular text-h3">{v}</div></div>
            ))}
            <div className="col-span-2 text-body text-[var(--ink-secondary)] sm:col-span-5">{data.a} / {data.b}: {data.signal}.</div>
          </Panel>
          <Panel className="p-4">
            <div className="mb-2 px-2 text-body font-semibold">Z-score of the ratio</div>
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.series} margin={{ top: 6, right: 12, bottom: 0, left: 0 }}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="date" tick={{ fill: "var(--ink-muted)", fontSize: 11 }} tickLine={false} minTickGap={50} />
                  <YAxis tick={{ fill: "var(--ink-muted)", fontSize: 11 }} tickLine={false} axisLine={false} width={36} />
                  <Tooltip contentStyle={tooltipStyle} />
                  {[-2, 0, 2].map((y) => <ReferenceLine key={y} y={y} stroke={y ? "var(--accent)" : "var(--axis)"} strokeDasharray={y ? "4 4" : undefined} />)}
                  <Line dataKey="z" stroke="var(--series-1)" dot={false} strokeWidth={1.6} connectNulls />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </Panel>
          <p className="text-caption text-[var(--ink-faint)]">{data.method} {data.sessions} sessions. A stretched ratio can stay stretched; this is analysis, not advice.</p>
        </div>
      )}
    </>
  );
}

function Screener({ onPick }: { onPick: (a: string, b: string) => void }) {
  const { data, loading, failure } = usePoll(() => research.pairScreen(0.7, 1.5), null);
  return failure ? <DataUnavailable failure={failure} /> : loading && !data ? <Loading label="Scanning same-sector pairs" /> : data ? (
    <Panel className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-body">
        <thead><tr className="border-b border-[var(--hairline)] text-left text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">
          <th className="px-5 py-3 font-medium">Pair</th><th className="px-5 py-3 font-medium">Sector</th>
          <th className="px-5 py-3 text-right font-medium">Correlation</th><th className="px-5 py-3 text-right font-medium">Z-score</th></tr></thead>
        <tbody>
          {data.pairs.length === 0 && <tr><td colSpan={4} className="px-5 py-10 text-center text-[var(--ink-muted)]">No correlated pair is stretched right now.</td></tr>}
          {data.pairs.map((p) => (
            <tr key={`${p.a}-${p.b}`} onClick={() => onPick(p.a, p.b)} className="cursor-pointer border-b border-[var(--hairline)] last:border-0 hover:bg-[var(--surface-2)]">
              <td className="px-5 py-3 font-semibold">{p.a} / {p.b}</td><td className="px-5 py-3 text-[var(--ink-secondary)]">{p.sector}</td>
              <td className="tabular px-5 py-3 text-right">{p.correlation.toFixed(2)}</td>
              <td className={`tabular px-5 py-3 text-right font-semibold ${Math.abs(p.z_score) >= 2 ? "text-[var(--accent)]" : ""}`}>{p.z_score.toFixed(2)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="px-5 py-3 text-caption text-[var(--ink-faint)]">Same-sector pairs with correlation of at least 0.70 and |z| of at least 1.5, from {data.checked} checked.</p>
    </Panel>
  ) : null;
}
