"use client";

import Link from "next/link";
import { TradeHead } from "@/components/trade/app-shell";
import { useOrderTicket } from "@/components/trade/order-ticket";
import { Change, DataUnavailable, Loading, Panel, SourceTag } from "@/components/trade/primitives";
import { usePoll } from "@/lib/hooks";
import { options } from "@/lib/trade-api";
import { num, oiShort, shortExpiry } from "@/lib/tfmt";

export default function UnusualPage() {
  const { data, loading, failure } = usePoll(() => options.unusual(25), 60_000);
  const ticket = useOrderTicket();
  return (
    <div className="mx-auto max-w-[1150px]">
      <TradeHead title="Unusual option activity" lede="Index option contracts trading far more than their open interest today." aside={data && <SourceTag source="live" />} />
      {failure ? <DataUnavailable failure={failure} /> : loading && !data ? <Loading /> : data && (
        <Panel className="overflow-x-auto">
          <table className="w-full min-w-[820px] text-body">
            <thead><tr className="border-b border-[var(--hairline)] text-left text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">
              <th className="px-5 py-3 font-medium">Contract</th><th className="px-5 py-3 text-right font-medium">LTP</th>
              <th className="px-5 py-3 text-right font-medium">Chg</th><th className="px-5 py-3 text-right font-medium">Volume</th>
              <th className="px-5 py-3 text-right font-medium">OI</th><th className="px-5 py-3 text-right font-medium">Vol / OI</th>
              <th className="px-5 py-3 text-right font-medium">OI chg</th><th className="px-5 py-3" /></tr></thead>
            <tbody>
              {data.contracts.length === 0 && <tr><td colSpan={8} className="px-5 py-10 text-center text-[var(--ink-muted)]">Nothing unusual yet today.</td></tr>}
              {data.contracts.map((c) => (
                <tr key={c.symbol} className="border-b border-[var(--hairline)] last:border-0 hover:bg-[var(--surface-2)]">
                  <td className="px-5 py-3"><Link href={`/market/option-chain?u=${c.underlying}&expiry=${c.expiry}`} className="font-semibold hover:underline">{c.symbol}</Link>
                    <span className="ml-2 text-small text-[var(--ink-muted)]">{shortExpiry(c.expiry)}</span></td>
                  <td className="tabular px-5 py-3 text-right">{num(c.ltp)}</td>
                  <td className="px-5 py-3 text-right"><Change value={c.change_pct} /></td>
                  <td className="tabular px-5 py-3 text-right">{oiShort(c.volume)}</td>
                  <td className="tabular px-5 py-3 text-right">{oiShort(c.oi)}</td>
                  <td className="tabular px-5 py-3 text-right font-semibold">{c.volume_to_oi.toFixed(2)}×</td>
                  <td className="tabular px-5 py-3 text-right">{c.oi_change_pct != null ? `${c.oi_change_pct > 0 ? "+" : ""}${c.oi_change_pct}%` : "—"}</td>
                  <td className="px-5 py-3 text-right">
                    <button onClick={() => ticket.open({ instrument: "option", symbol: c.underlying, side: "buy", option_type: c.option_type, strike: c.strike, expiry: c.expiry, ltp: c.ltp })}
                      className="rounded-full border border-[var(--hairline-strong)] px-3 py-1 text-small hover:bg-[var(--surface-3)]">Trade</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Panel>
      )}
      {data && <p className="mt-3 text-caption text-[var(--ink-faint)]">{data.method}</p>}
    </div>
  );
}
