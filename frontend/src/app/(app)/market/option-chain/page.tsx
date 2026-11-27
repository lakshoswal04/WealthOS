"use client";

import clsx from "clsx";
import { useSearchParams } from "next/navigation";
import { Fragment, Suspense, useState } from "react";
import { TradeHead } from "@/components/trade/app-shell";
import { UnderlyingSelect } from "@/components/trade/oi";
import { useOrderTicket } from "@/components/trade/order-ticket";
import { Change, DataUnavailable, Loading, Panel, SourceTag } from "@/components/trade/primitives";
import { usePoll } from "@/lib/hooks";
import { trade, type ChainRow, type OptionChain } from "@/lib/trade-api";
import { num, oiShort, shortExpiry } from "@/lib/tfmt";

export default function OptionChainPage() {
  return <Suspense fallback={<Loading />}><Chain /></Suspense>;
}

function Chain() {
  const params = useSearchParams();
  const [underlying, setUnderlying] = useState(params.get("u") ?? "NIFTY");
  const [expiry, setExpiry] = useState<string | null>(params.get("expiry"));
  const [greeks, setGreeks] = useState(false);
  const { data, loading, failure } = usePoll(() => trade.chain(underlying, expiry, 15), 15_000, [underlying, expiry]);

  return (
    <div>
      <TradeHead title="Option chain"
        lede="The live chain from your Upstox session: premiums, open interest, volume, IV and Greeks. Click a premium to paper trade it."
        aside={<UnderlyingSelect value={underlying} onChange={(u) => { setUnderlying(u); setExpiry(null); }} />} />

      {data && <Header chain={data} expiry={expiry ?? data.expiry} onExpiry={setExpiry} greeks={greeks} onGreeks={setGreeks} />}

      <Panel className="mt-5 overflow-hidden">
        {failure ? <div className="p-6"><DataUnavailable failure={failure} /></div>
          : loading && !data ? <div className="px-6"><Loading label="Loading the chain" /></div>
            : data && <Table chain={data} greeks={greeks} />}
      </Panel>
      {data && <p className="mt-3 text-caption text-[var(--ink-faint)]">{data.note}</p>}
    </div>
  );
}

function Header({ chain, expiry, onExpiry, greeks, onGreeks }: {
  chain: OptionChain; expiry: string; onExpiry: (e: string) => void; greeks: boolean; onGreeks: (v: boolean) => void;
}) {
  const stats: [string, string][] = [
    ["PCR", chain.pcr?.toFixed(2) ?? "—"],
    ["Max pain", num(chain.max_pain, 0)],
    ["Support", num(chain.support, 0)],
    ["Resistance", num(chain.resistance, 0)],
    ["ATM IV", chain.atm_iv != null ? `${chain.atm_iv.toFixed(2)}%` : "—"],
    ["Lot", String(chain.lot_size)],
  ];
  return (
    <div className="flex flex-wrap items-end justify-between gap-5">
      <div>
        <div className="flex items-baseline gap-3">
          <span className="text-h3 font-semibold">{chain.underlying}</span>
          <span className="tabular text-h2">{num(chain.spot)}</span>
          <Change value={chain.spot_change_pct} className="text-body-lg" />
          <SourceTag source="live" />
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          {chain.expiries.map((e) => (
            <button key={e} onClick={() => onExpiry(e)}
              className={clsx("rounded-full border px-3.5 py-1.5 text-small", e === expiry
                ? "border-[var(--ink-secondary)] bg-[var(--surface-3)] font-medium text-[var(--ink-primary)]"
                : "border-[var(--hairline-strong)] text-[var(--ink-muted)] hover:text-[var(--ink-secondary)]")}>
              {shortExpiry(e)}
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        {stats.map(([l, v]) => (
          <div key={l}><div className="text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">{l}</div><div className="tabular text-body-lg">{v}</div></div>
        ))}
        <label className="flex items-center gap-2 text-small text-[var(--ink-secondary)]">
          <input type="checkbox" checked={greeks} onChange={(e) => onGreeks(e.target.checked)} className="accent-[var(--accent)]" /> Greeks
        </label>
      </div>
    </div>
  );
}

function Table({ chain, greeks }: { chain: OptionChain; greeks: boolean }) {
  const ticket = useOrderTicket();
  const maxOI = Math.max(...chain.rows.flatMap((r) => [r.ce.oi, r.pe.oi]), 1);
  const open = (row: ChainRow, type: "CE" | "PE") => ticket.open({
    instrument: "option", symbol: chain.underlying, side: "buy", option_type: type, strike: row.strike,
    expiry: chain.expiry, quantity: 1, lot_size: chain.lot_size, ltp: type === "CE" ? row.ce.ltp : row.pe.ltp,
  });
  const callCols = greeks ? ["OI", "Δ", "Θ", "IV", "LTP"] : ["OI", "OI chg (day)", "Volume", "IV", "LTP", "Chg%"];
  const putCols = [...callCols].reverse();

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[960px] text-small">
        <thead>
          <tr className="border-b border-[var(--hairline)] text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">
            <th colSpan={callCols.length} className="py-2.5 text-center font-medium text-[var(--down)]">Calls</th>
            <th className="py-2.5" />
            <th colSpan={putCols.length} className="py-2.5 text-center font-medium text-[var(--up)]">Puts</th>
          </tr>
          <tr className="border-b border-[var(--hairline)] text-caption text-[var(--ink-muted)]">
            {callCols.map((c) => <th key={`c${c}`} className="px-3 py-2 text-right font-normal">{c}</th>)}
            <th className="bg-[var(--surface-2)] px-3 py-2 text-center font-semibold text-[var(--ink-secondary)]">Strike</th>
            {putCols.map((c) => <th key={`p${c}`} className="px-3 py-2 text-left font-normal">{c}</th>)}
          </tr>
        </thead>
        <tbody>
          {chain.rows.map((row, i) => {
            const callITM = row.strike < chain.spot;
            const putITM = row.strike > chain.spot;
            const spotLineAfter = i < chain.rows.length - 1 && row.strike <= chain.spot && chain.rows[i + 1].strike > chain.spot;
            const ce = row.ce, pe = row.pe;
            const callCells = greeks
              ? [oiShort(ce.oi), ce.delta.toFixed(2), ce.theta.toFixed(1), ce.iv.toFixed(1)]
              : [oiShort(ce.oi), signedOI(ce.oi_change), oiShort(ce.volume), ce.iv.toFixed(1)];
            const putCells = greeks
              ? [pe.iv.toFixed(1), pe.theta.toFixed(1), pe.delta.toFixed(2), oiShort(pe.oi)]
              : [pe.iv.toFixed(1), oiShort(pe.volume), signedOI(pe.oi_change), oiShort(pe.oi)];
            return (
              <Fragment key={row.strike}>
                <tr className={clsx("border-b border-[var(--hairline)] hover:bg-[var(--surface-2)]", row.strike === chain.atm_strike && "font-medium")}>
                  {callCells.map((v, j) => (
                    <td key={j} className={clsx("tabular relative px-3 py-2 text-right", callITM && "bg-[color-mix(in_oklab,var(--accent)_6%,transparent)]")}>
                      {j === 0 && <span className="absolute inset-y-1.5 right-0 rounded-l bg-[color-mix(in_oklab,var(--down)_22%,transparent)]" style={{ width: `${(ce.oi / maxOI) * 100}%` }} />}
                      <span className="relative">{v}</span>
                    </td>
                  ))}
                  <td className={clsx("px-3 py-2 text-right", callITM && "bg-[color-mix(in_oklab,var(--accent)_6%,transparent)]")}>
                    <button onClick={() => open(row, "CE")} className="tabular rounded px-1.5 py-0.5 font-semibold hover:bg-[var(--buy)] hover:text-white" title={`Trade ${row.strike} CE`}>{num(ce.ltp)}</button>
                  </td>
                  {!greeks && <td className={clsx("px-3 py-2 text-right", callITM && "bg-[color-mix(in_oklab,var(--accent)_6%,transparent)]")}><Change value={ce.change_pct} /></td>}

                  <td className={clsx("tabular bg-[var(--surface-2)] px-3 py-2 text-center font-semibold", row.strike === chain.atm_strike && "text-[var(--accent)]")}>
                    {row.strike}
                  </td>

                  {!greeks && <td className={clsx("px-3 py-2", putITM && "bg-[color-mix(in_oklab,var(--accent)_6%,transparent)]")}><Change value={pe.change_pct} /></td>}
                  <td className={clsx("px-3 py-2", putITM && "bg-[color-mix(in_oklab,var(--accent)_6%,transparent)]")}>
                    <button onClick={() => open(row, "PE")} className="tabular rounded px-1.5 py-0.5 font-semibold hover:bg-[var(--buy)] hover:text-white" title={`Trade ${row.strike} PE`}>{num(pe.ltp)}</button>
                  </td>
                  {putCells.map((v, j) => (
                    <td key={j} className={clsx("tabular relative px-3 py-2", putITM && "bg-[color-mix(in_oklab,var(--accent)_6%,transparent)]")}>
                      {j === putCells.length - 1 && <span className="absolute inset-y-1.5 left-0 rounded-r bg-[color-mix(in_oklab,var(--up)_22%,transparent)]" style={{ width: `${(pe.oi / maxOI) * 100}%` }} />}
                      <span className="relative">{v}</span>
                    </td>
                  ))}
                </tr>
                {spotLineAfter && (
                  <tr><td colSpan={callCols.length + putCols.length + 1} className="p-0">
                    <div className="relative h-0 border-t border-dashed border-[var(--accent)]">
                      <span className="tabular absolute left-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full bg-[var(--accent)] px-2.5 py-0.5 text-caption font-semibold text-[var(--accent-ink)]">
                        Spot {num(chain.spot)}
                      </span>
                    </div>
                  </td></tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const signedOI = (v: number) => `${v > 0 ? "+" : ""}${oiShort(v)}`;
