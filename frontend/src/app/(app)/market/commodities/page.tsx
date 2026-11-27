"use client";

import { TradeHead } from "@/components/trade/app-shell";
import { Change, DataUnavailable, Loading, Panel } from "@/components/trade/primitives";
import { usePoll } from "@/lib/hooks";
import { research } from "@/lib/trade-api";
import { num, signed, tone } from "@/lib/tfmt";

export default function CommoditiesPage() {
  const { data, loading, failure } = usePoll(() => research.commodities(), 120_000);
  return (
    <div className="mx-auto max-w-[1100px]">
      <TradeHead title="Commodities" lede="International futures (COMEX, NYMEX, ICE) in US dollars. These are not MCX prices." />
      {failure ? <DataUnavailable failure={failure} /> : loading && !data ? <Loading /> : data && (
        <>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {data.commodities.map((c) => (
              <Panel key={c.ticker} className="p-6">
                <div className="flex items-start justify-between">
                  <div><div className="text-body-lg font-semibold">{c.name}</div><div className="text-small text-[var(--ink-muted)]">{c.venue} · {c.unit}</div></div>
                  <Change value={c.change_pct} className="text-body" />
                </div>
                <div className="tabular mt-5 text-h1">${num(c.price)}</div>
                <div className={`tabular mt-1 text-body ${tone(c.change)}`}>{signed(c.change)}</div>
                {c.inr_reference && (
                  <div className="mt-4 border-t border-[var(--hairline)] pt-3 text-small text-[var(--ink-secondary)]">
                    ≈ ₹{Math.round(c.inr_reference.value).toLocaleString("en-IN")} {c.inr_reference.unit.replace("₹ ", "")} at the live USD/INR rate
                  </div>
                )}
              </Panel>
            ))}
          </div>
          <p className="mt-4 text-caption text-[var(--ink-faint)]">{data.note} USD/INR {data.usd_inr ? num(data.usd_inr) : "—"}. Source: {data.source}.</p>
        </>
      )}
    </div>
  );
}
