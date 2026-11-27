"use client";

import clsx from "clsx";
import { useMemo, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { usePoll } from "@/lib/hooks";
import { options } from "@/lib/trade-api";
import { num, oiShort, shortExpiry } from "@/lib/tfmt";
import { DataUnavailable, Loading, Panel, SourceTag } from "./primitives";

export const UNDERLYINGS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"] as const;

const selectClass = "rounded-[var(--radius-sm)] bg-transparent text-body font-semibold text-[var(--ink-primary)] focus:outline-none";
const tooltipStyle = { background: "var(--surface-2)", border: "1px solid var(--hairline-strong)", borderRadius: 8, fontSize: 12 };

export function UnderlyingSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} aria-label="Underlying"
      className="rounded-[var(--radius)] border border-[var(--hairline-strong)] bg-[var(--surface-1)] px-4 py-2.5 text-body-lg font-medium focus:outline-none">
      {UNDERLYINGS.map((u) => <option key={u} value={u}>{u}</option>)}
    </select>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <span className="flex items-baseline gap-2">
      <span className="text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">{label}</span>
      <span className="tabular font-semibold">{value}</span>
    </span>
  );
}

const signedShort = (v: number) => `${v > 0 ? "+" : ""}${oiShort(v)}`;

export function OIAnalysis({ underlying }: { underlying: string }) {
  const [expiry, setExpiry] = useState<string | null>(null);
  const [show, setShow] = useState<"oi" | "change">("oi");
  const { data, failure, loading } = usePoll(() => options.chain(underlying, expiry, 15), 30_000, [underlying, expiry]);

  const rows = useMemo(() => (data?.rows ?? []).map((r) => ({
    strike: r.strike,
    call: (show === "oi" ? r.ce.oi : r.ce.oi_change) / 1e5,
    put: (show === "oi" ? r.pe.oi : r.pe.oi_change) / 1e5,
  })), [data, show]);

  return (
    <Panel>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--hairline)] px-6 py-5">
        <div className="text-h3 font-semibold">Open Interest <span className="text-small font-normal text-[var(--ink-muted)]">(in lakh)</span></div>
        {data && <SourceTag source="live" />}
      </div>
      {failure ? <div className="p-6"><DataUnavailable failure={failure} /></div> : (
        <>
          <div className="flex flex-wrap items-center gap-x-6 gap-y-3 px-6 py-4 text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">
            <label className="flex items-center gap-2">EXP
              <select value={expiry ?? data?.expiry ?? ""} onChange={(e) => setExpiry(e.target.value)} className={selectClass}>
                {(data?.expiries ?? []).map((e) => <option key={e} value={e}>{shortExpiry(e).toUpperCase()}</option>)}
              </select>
            </label>
            <span className="normal-case tracking-normal">Change: since the previous session&apos;s close</span>
            <span className="flex items-center gap-2">SHOW
              <span className="inline-flex rounded-[var(--radius-sm)] border border-[var(--hairline-strong)] p-0.5 normal-case tracking-normal">
                {(["oi", "change"] as const).map((s) => (
                  <button key={s} onClick={() => setShow(s)}
                    className={clsx("rounded-[6px] px-3 py-1 text-body", show === s ? "bg-[var(--surface-4)] text-[var(--ink-primary)]" : "text-[var(--ink-secondary)]")}>
                    {s === "oi" ? "OI" : "Change"}
                  </button>
                ))}
              </span>
            </span>
          </div>
          {data && (
            <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-y border-[var(--hairline)] px-6 py-4 text-body">
              <span className="flex items-center gap-2"><span className="h-3 w-3 rounded-sm bg-[var(--down)]" /> Call OI</span>
              <span className="flex items-center gap-2"><span className="h-3 w-3 rounded-sm bg-[var(--up)]" /> Put OI</span>
              <span className="hidden h-5 w-px bg-[var(--hairline-strong)] sm:block" />
              <Stat label="Total call OI" value={oiShort(data.total_call_oi)} />
              <Stat label="Total put OI" value={oiShort(data.total_put_oi)} />
              <Stat label="PCR" value={data.pcr?.toFixed(2) ?? "—"} />
              <Stat label="Calls · day" value={signedShort(data.total_call_oi_change)} />
              <Stat label="Puts · day" value={signedShort(data.total_put_oi_change)} />
              <Stat label="Max pain" value={num(data.max_pain, 0)} />
            </div>
          )}
          <div className="h-[420px] px-2 pb-4 pt-6">
            {loading && !data ? <Loading label="Loading open interest" /> : (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={rows} margin={{ top: 24, right: 16, bottom: 4, left: 4 }} barGap={2}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="strike" tick={{ fill: "var(--ink-muted)", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "var(--axis)" }} interval={1} />
                  <YAxis tick={{ fill: "var(--ink-muted)", fontSize: 11 }} tickLine={false} axisLine={false} width={44} />
                  <Tooltip contentStyle={tooltipStyle} cursor={{ fill: "var(--surface-3)" }}
                    formatter={(v: number, name: string) => [`${v.toFixed(2)} L`, name === "call" ? "Call" : "Put"]}
                    labelFormatter={(l) => `Strike ${l}`} />
                  {data && (
                    <ReferenceLine x={data.atm_strike} stroke="var(--ink-secondary)" strokeDasharray="4 4"
                      label={{ value: `ATM ${data.atm_strike}`, position: "top", fill: "var(--ink-secondary)", fontSize: 12 }} />
                  )}
                  <ReferenceLine y={0} stroke="var(--axis)" />
                  <Bar dataKey="call" fill="var(--down)" radius={[3, 3, 0, 0]} maxBarSize={16} />
                  <Bar dataKey="put" fill="var(--up)" radius={[3, 3, 0, 0]} maxBarSize={16} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
          {data && <p className="px-6 pb-5 text-caption text-[var(--ink-faint)]">{data.note}</p>}
        </>
      )}
    </Panel>
  );
}

export function MultiStrikeOI({ underlying }: { underlying: string }) {
  const chain = usePoll(() => options.chain(underlying, null, 6), null, [underlying]);
  const [picked, setPicked] = useState<number[] | null>(null);
  const strikeList = (chain.data?.rows ?? []).map((r) => r.strike);
  const atmIndex = chain.data ? strikeList.indexOf(chain.data.atm_strike) : -1;
  const strikes = picked ?? (atmIndex >= 0 ? strikeList.slice(Math.max(atmIndex - 1, 0), atmIndex + 2) : []);
  const series = usePoll(() => strikes.length ? options.multiStrike(underlying, strikes) : Promise.resolve(null),
    60_000, [underlying, strikes.join(",")]);

  const rows = useMemo(() => {
    const s = series.data?.series ?? [];
    if (!s.length) return [];
    const times = Array.from(new Set(s.flatMap((one) => one.points.map((p) => p.time)))).sort();
    return times.map((time) => {
      const row: Record<string, number | string | null> = { time };
      for (const one of s) {
        const p = one.points.find((x) => x.time === time);
        row[`${one.strike} CE`] = p?.ce != null ? p.ce / 1e5 : null;
        row[`${one.strike} PE`] = p?.pe != null ? p.pe / 1e5 : null;
      }
      return row;
    });
  }, [series.data]);

  const colors = ["var(--series-1)", "var(--series-2)", "var(--series-3)", "var(--series-5)", "var(--series-7)", "var(--series-4)"];
  const failure = chain.failure ?? series.failure;

  return (
    <Panel>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--hairline)] px-6 py-5">
        <div>
          <div className="text-h3 font-semibold">Multi-strike OI</div>
          <p className="mt-1 text-small text-[var(--ink-muted)]">How open interest built through today&apos;s session at chosen strikes (lakh, 5-minute candles).</p>
        </div>
        {series.data && <SourceTag source="live" />}
      </div>
      {failure ? <div className="p-6"><DataUnavailable failure={failure} /></div> : (
        <>
          <div className="flex flex-wrap gap-2 px-6 py-4">
            {strikeList.map((k) => {
              const on = strikes.includes(k);
              return (
                <button key={k} onClick={() => setPicked(on ? strikes.filter((s) => s !== k) : [...strikes, k].slice(-4))}
                  className={clsx("tabular rounded-full border px-3 py-1 text-small",
                    on ? "border-[var(--ink-secondary)] bg-[var(--surface-3)] text-[var(--ink-primary)]" : "border-[var(--hairline-strong)] text-[var(--ink-muted)]")}>
                  {k}
                </button>
              );
            })}
          </div>
          <div className="h-[380px] px-2 pb-5">
            {series.loading && !series.data ? <Loading /> : rows.length === 0 ? (
              <p className="px-6 py-10 text-center text-body text-[var(--ink-muted)]">No candles yet today: the session has not traded these strikes.</p>
            ) : (
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 4, left: 4 }}>
                  <CartesianGrid stroke="var(--grid)" vertical={false} />
                  <XAxis dataKey="time" tick={{ fill: "var(--ink-muted)", fontSize: 11 }} tickLine={false} axisLine={{ stroke: "var(--axis)" }} minTickGap={32} />
                  <YAxis tick={{ fill: "var(--ink-muted)", fontSize: 11 }} tickLine={false} axisLine={false} width={44} />
                  <Tooltip contentStyle={tooltipStyle} formatter={(v: number) => `${v.toFixed(2)} L`} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                  {(series.data?.series ?? []).flatMap((s, i) => [
                    <Line key={`${s.strike}ce`} dataKey={`${s.strike} CE`} stroke={colors[i % colors.length]} dot={false} strokeWidth={1.8} connectNulls />,
                    <Line key={`${s.strike}pe`} dataKey={`${s.strike} PE`} stroke={colors[i % colors.length]} dot={false} strokeWidth={1.4} strokeDasharray="5 3" connectNulls />,
                  ])}
                </LineChart>
              </ResponsiveContainer>
            )}
          </div>
        </>
      )}
    </Panel>
  );
}

export function OICrossovers({ underlying }: { underlying: string }) {
  const { data, failure, loading } = usePoll(() => options.crossovers(underlying), 120_000, [underlying]);
  return (
    <Panel>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--hairline)] px-6 py-5">
        <div>
          <div className="text-h3 font-semibold">OI crossovers</div>
          <p className="mt-1 text-small text-[var(--ink-muted)]">Strikes where put OI overtook call OI, or the reverse, during today&apos;s session.</p>
        </div>
        {data && <SourceTag source="live" />}
      </div>
      {failure ? <div className="p-6"><DataUnavailable failure={failure} /></div> : loading && !data ? <div className="px-6"><Loading /></div> : data && (
        <div className="px-6 py-4">
          {data.crossovers.length === 0 ? (
            <p className="py-8 text-center text-body text-[var(--ink-muted)]">No crossovers across {data.strikes_checked} strikes so far today.</p>
          ) : (
            <table className="w-full text-body">
              <thead><tr className="text-left text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">
                <th className="py-2 font-medium">Time</th><th className="py-2 font-medium">Strike</th><th className="py-2 font-medium">What happened</th>
                <th className="py-2 text-right font-medium">Call OI</th><th className="py-2 text-right font-medium">Put OI</th></tr></thead>
              <tbody className="divide-y divide-[var(--hairline)]">
                {data.crossovers.map((c, i) => (
                  <tr key={i}>
                    <td className="tabular py-2.5">{c.time}</td>
                    <td className="tabular py-2.5 font-semibold">{c.strike}</td>
                    <td className={clsx("py-2.5", c.direction === "puts_overtook_calls" ? "text-[var(--up)]" : "text-[var(--down)]")}>
                      {c.direction === "puts_overtook_calls" ? "Puts overtook calls (support building)" : "Calls overtook puts (resistance building)"}
                    </td>
                    <td className="tabular py-2.5 text-right">{oiShort(c.call_oi)}</td>
                    <td className="tabular py-2.5 text-right">{oiShort(c.put_oi)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          <p className="mt-3 text-caption text-[var(--ink-faint)]">{data.method} Expiry {shortExpiry(data.expiry)}; spot {num(data.spot)}.</p>
        </div>
      )}
    </Panel>
  );
}
