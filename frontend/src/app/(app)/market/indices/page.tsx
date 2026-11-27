"use client";

import Link from "next/link";
import { TradeHead } from "@/components/trade/app-shell";
import { Change, DataUnavailable, Loading, Panel, SourceTag } from "@/components/trade/primitives";
import { usePoll } from "@/lib/hooks";
import { trade } from "@/lib/trade-api";
import { num, signed, tone } from "@/lib/tfmt";

export default function IndicesPage() {
  const { data, loading, failure } = usePoll(() => trade.indices(), 15_000);
  return (
    <div>
      <TradeHead title="Indices" lede="NSE and BSE benchmark indices. Click one to open its chart." />
      {failure ? <DataUnavailable failure={failure} /> : loading && !data ? <Loading /> : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {(data?.indices ?? []).map((q) => (
            <Link key={q.symbol} href={`/chart?symbol=${q.symbol}`}>
              <Panel className="p-6 transition-colors hover:border-[var(--hairline-strong)]">
                <div className="flex items-start justify-between">
                  <div>
                    <div className="text-body-lg font-semibold">{q.symbol === "INDIAVIX" ? "INDIA VIX" : q.symbol}</div>
                    <div className="text-small text-[var(--ink-muted)]">{q.name}</div>
                  </div>
                  <SourceTag source={q.source} />
                </div>
                <div className="tabular mt-5 text-h1">{num(q.ltp)}</div>
                <div className="mt-1 text-body"><span className={tone(q.change)}>{signed(q.change)}</span> <Change value={q.change_pct} parens /></div>
                <div className="mt-4 grid grid-cols-3 gap-3 border-t border-[var(--hairline)] pt-4 text-small">
                  {[["Open", q.open], ["High", q.high], ["Low", q.low]].map(([l, v]) => (
                    <div key={l as string}><div className="text-caption text-[var(--ink-muted)]">{l}</div><div className="tabular">{num(v as number)}</div></div>
                  ))}
                </div>
              </Panel>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
