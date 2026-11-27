"use client";

import Link from "next/link";
import { TradeHead } from "@/components/trade/app-shell";
import { DataUnavailable, Loading, SourceTag } from "@/components/trade/primitives";
import { usePoll } from "@/lib/hooks";
import { trade } from "@/lib/trade-api";
import { pct } from "@/lib/tfmt";

/** Green for gains and red for losses, saturating at ±3%. */
function shade(change: number) {
  const t = Math.min(Math.abs(change) / 3, 1);
  const base = change >= 0 ? "var(--up)" : "var(--down)";
  return `color-mix(in oklab, ${base} ${Math.round(12 + t * 58)}%, var(--surface-1))`;
}

export default function HeatmapPage() {
  const { data, loading, failure } = usePoll(() => trade.heatmap(), 30_000);
  return (
    <div>
      <TradeHead title="F&O heatmap" lede="Every NIFTY 100 stock's move today, grouped by industry. Industries are ordered by their average change."
        aside={<SourceTag source={data?.source} />} />
      {failure ? <DataUnavailable failure={failure} /> : loading && !data ? <Loading /> : (
        <div className="space-y-6">
          {(data?.groups ?? []).map((g) => (
            <section key={g.sector}>
              <div className="mb-2 flex items-baseline gap-3">
                <h2 className="text-body-lg font-semibold">{g.sector}</h2>
                <span className="tabular text-small" style={{ color: g.change_pct >= 0 ? "var(--up)" : "var(--down)" }}>{pct(g.change_pct)}</span>
              </div>
              <div className="grid grid-cols-[repeat(auto-fill,minmax(118px,1fr))] gap-1.5">
                {g.stocks.map((s) => (
                  <Link key={s.symbol} href={`/chart?symbol=${s.symbol}`} title={`${s.symbol} ${pct(s.change_pct)}`}
                    className="rounded-[8px] px-3 py-2.5 transition-transform hover:scale-[1.03]" style={{ background: shade(s.change_pct) }}>
                    <div className="truncate text-small font-semibold">{s.symbol}</div>
                    <div className="tabular text-caption">{pct(s.change_pct)}</div>
                  </Link>
                ))}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
