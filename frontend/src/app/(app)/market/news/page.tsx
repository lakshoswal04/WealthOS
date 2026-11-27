"use client";

import { useState } from "react";
import { TradeHead } from "@/components/trade/app-shell";
import { DataUnavailable, Loading, Panel } from "@/components/trade/primitives";
import { usePoll } from "@/lib/hooks";
import { research } from "@/lib/trade-api";

function ago(iso: string | null) {
  if (!iso) return "";
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60_000);
  if (mins < 60) return `${mins}m ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)}h ago`;
  return new Date(iso).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

export default function NewsPage() {
  const [symbol, setSymbol] = useState("");
  const [query, setQuery] = useState("");
  const { data, loading, failure } = usePoll(() => research.news(symbol || null, 60), 300_000, [symbol]);
  return (
    <div className="mx-auto max-w-[1000px]">
      <TradeHead title="Stocks in the news" lede="Headlines on NIFTY 100 companies, newest first. Each opens at its publisher."
        aside={
          <form onSubmit={(e) => { e.preventDefault(); setSymbol(query.trim().toUpperCase()); }} className="flex gap-2">
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter by symbol, e.g. INFY"
              className="w-56 rounded-full border border-[var(--hairline-strong)] bg-[var(--surface-1)] px-4 py-2 text-body uppercase focus:outline-none" />
            {symbol && <button type="button" onClick={() => { setSymbol(""); setQuery(""); }} className="rounded-full px-3 text-body text-[var(--ink-muted)]">Clear</button>}
          </form>
        } />
      {failure ? <DataUnavailable failure={failure} /> : loading && !data ? <Loading label="Collecting headlines" /> : data && (
        <Panel className="divide-y divide-[var(--hairline)]">
          {data.items.length === 0 && <p className="px-6 py-10 text-center text-body text-[var(--ink-muted)]">No headlines right now.</p>}
          {data.items.map((n) => (
            <a key={n.id} href={n.url} target="_blank" rel="noreferrer" className="block px-6 py-5 hover:bg-[var(--surface-2)]">
              <div className="flex items-center gap-3 text-small text-[var(--ink-muted)]">
                <span className="rounded-full bg-[var(--surface-3)] px-2.5 py-0.5 font-semibold text-[var(--ink-secondary)]">{n.symbol}</span>
                {n.publisher && <span>{n.publisher}</span>}<span>{ago(n.published_at)}</span>
              </div>
              <div className="mt-2 text-body-lg font-medium">{n.title}</div>
              {n.summary && <p className="mt-1.5 line-clamp-2 text-body text-[var(--ink-secondary)]">{n.summary}</p>}
            </a>
          ))}
        </Panel>
      )}
      {data && <p className="mt-3 text-caption text-[var(--ink-faint)]">Source: {data.source}. Headlines are third-party reporting, not WealthOS analysis.</p>}
    </div>
  );
}
