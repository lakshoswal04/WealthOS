"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { TradeHead } from "@/components/trade/app-shell";
import { DataUnavailable, Loading, Panel } from "@/components/trade/primitives";
import { usePoll } from "@/lib/hooks";
import { research } from "@/lib/trade-api";
import { num } from "@/lib/tfmt";

export default function EventsPage() {
  return <Suspense fallback={<Loading />}><Events /></Suspense>;
}

function Events() {
  const params = useSearchParams();
  const router = useRouter();
  const symbol = (params.get("symbol") ?? "RELIANCE").toUpperCase();
  const [input, setInput] = useState(symbol);
  const { data, loading, failure } = usePoll(() => research.events(symbol), null, [symbol]);
  const fmt = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" });
  return (
    <div className="mx-auto max-w-[1000px]">
      <TradeHead title="Stock events" lede="Dividends, splits and upcoming results for one company."
        aside={
          <form onSubmit={(e) => { e.preventDefault(); router.push(`/market/events?symbol=${input.trim().toUpperCase()}`); }} className="flex gap-2">
            <input value={input} onChange={(e) => setInput(e.target.value)} className="w-44 rounded-full border border-[var(--hairline-strong)] bg-[var(--surface-1)] px-4 py-2 text-body uppercase focus:outline-none" />
            <button className="rounded-full bg-[var(--action)] px-5 text-body font-semibold text-[var(--action-ink)]">Show</button>
          </form>
        } />
      {failure ? <DataUnavailable failure={failure} /> : loading && !data ? <Loading /> : data && (
        <div className="grid gap-5 md:grid-cols-3">
          <Panel className="p-6 md:col-span-3">
            <div className="text-h3 font-semibold">{data.symbol} <span className="text-body font-normal text-[var(--ink-muted)]">{data.name}</span></div>
            <div className="mt-4 flex flex-wrap gap-3">
              {data.upcoming.length === 0 ? <span className="text-body text-[var(--ink-muted)]">No upcoming dates announced.</span> : data.upcoming.map((u, i) => (
                <span key={i} className="rounded-full border border-[var(--hairline-strong)] px-4 py-1.5 text-body">
                  {u.event === "earnings" ? "Results" : u.event === "ex_dividend" ? "Ex-dividend" : "Dividend paid"} · {fmt(u.date)}{u.detail ? ` · ${u.detail}` : ""}
                </span>
              ))}
            </div>
          </Panel>
          <Panel className="p-6 md:col-span-2">
            <h2 className="mb-3 text-body-lg font-semibold">Dividends</h2>
            {data.dividends.length === 0 ? <p className="text-body text-[var(--ink-muted)]">No dividends on record.</p> : (
              <table className="w-full text-body"><tbody className="divide-y divide-[var(--hairline)]">
                {[...data.dividends].reverse().map((d) => (
                  <tr key={d.date}><td className="py-2 text-[var(--ink-secondary)]">{fmt(d.date)}</td><td className="tabular py-2 text-right">₹{num(d.amount)} a share</td></tr>
                ))}
              </tbody></table>
            )}
          </Panel>
          <Panel className="p-6">
            <h2 className="mb-3 text-body-lg font-semibold">Splits and bonuses</h2>
            {data.splits.length === 0 ? <p className="text-body text-[var(--ink-muted)]">None on record.</p> : (
              <ul className="space-y-2 text-body">{[...data.splits].reverse().map((s) => (
                <li key={s.date} className="flex justify-between"><span className="text-[var(--ink-secondary)]">{fmt(s.date)}</span><span className="tabular">{s.ratio}:1</span></li>
              ))}</ul>
            )}
          </Panel>
        </div>
      )}
    </div>
  );
}
