"use client";

import clsx from "clsx";
import Link from "next/link";
import { useState } from "react";
import { TradeHead } from "@/components/trade/app-shell";
import { DataUnavailable, Icon, Loading, Panel } from "@/components/trade/primitives";
import { percent } from "@/lib/format";
import { usePoll } from "@/lib/hooks";
import { inr, num } from "@/lib/tfmt";
import { autopilot, unavailableFrom, type AutopilotRun, type AutopilotStatus, type Unavailable } from "@/lib/trade-api";

export default function AutopilotPage() {
  const [tick, setTick] = useState(0);
  const { data, loading, failure } = usePoll(() => autopilot.status(), 120_000, [tick]);
  const refresh = () => setTick((t) => t + 1);

  return (
    <div>
      <TradeHead title="Autopilot"
        lede="A paper sleeve the trained models run for you. Every few sessions, after the close, it rebuilds the basket from the swing models' picks, sized for your risk profile and the market regime, places the paper orders itself, and tells you what it did and why. Your real holdings are only advised on, never traded." />
      {failure ? <DataUnavailable failure={failure} /> : loading && !data ? <Loading label="Loading Autopilot" /> : data && (
        <div className="grid gap-5 xl:grid-cols-[1fr_1.2fr]">
          <div className="space-y-5">
            <StatusCard status={data} onChange={refresh} />
            <SettingsCard status={data} onChange={refresh} />
          </div>
          <div className="space-y-5">
            <NextRun enabled={data.settings.enabled || Object.keys(data.settings.sleeve).length > 0} onChange={refresh} />
            <Runs runs={data.runs} />
          </div>
        </div>
      )}
      {data && <p className="mt-6 text-caption text-[var(--ink-faint)]">{data.disclaimer}</p>}
    </div>
  );
}

function Fig({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div>
      <div className="text-micro uppercase tracking-[0.1em] text-[var(--ink-muted)]">{label}</div>
      <div className={clsx("tabular mt-1 text-h3", tone)}>{value}</div>
      {sub && <div className="text-caption text-[var(--ink-muted)]">{sub}</div>}
    </div>
  );
}

function StatusCard({ status, onChange }: { status: AutopilotStatus; onChange: () => void }) {
  const s = status.settings;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<Unavailable | null>(null);
  const running = Object.keys(s.sleeve).length > 0;
  async function act(fn: () => Promise<unknown>) {
    setBusy(true); setError(null);
    try { await fn(); onChange(); window.dispatchEvent(new CustomEvent("paper-order")); }
    catch (err) { setError(unavailableFrom(err)); }
    finally { setBusy(false); }
  }
  return (
    <Panel className="p-6">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 text-body-lg font-semibold"><Icon name="bolt" size={18} /> Status</div>
        <span className={clsx("rounded-full px-2.5 py-0.5 text-caption font-medium",
          s.enabled ? "bg-[color-mix(in_oklab,var(--up)_14%,transparent)] text-[var(--up)]" : "bg-[var(--surface-3)] text-[var(--ink-secondary)]")}>
          {s.enabled ? "On" : running ? "Paused" : "Off"}
        </span>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-4">
        <Fig label="Budget" value={inr(s.budget, 0)} />
        <Fig label="Sleeve value" value={inr(status.sleeve_value, 0)} sub={s.sleeve_cash != null ? `${inr(s.sleeve_cash, 0)} cash` : undefined} />
        <Fig label="P&L" value={`${status.pnl >= 0 ? "+" : ""}${inr(status.pnl, 0)}`} sub={status.pnl_pct != null ? `${status.pnl_pct.toFixed(2)}%` : undefined}
          tone={status.pnl > 0 ? "text-[var(--up)]" : status.pnl < 0 ? "text-[var(--down)]" : undefined} />
      </div>
      {status.holdings.length > 0 && (
        <table className="mt-4 w-full text-small">
          <tbody className="divide-y divide-[var(--hairline)]">
            {status.holdings.map((h) => (
              <tr key={h.symbol}><td className="py-1.5 font-medium">{h.symbol}</td><td className="tabular py-1.5 text-right">{h.quantity}</td>
                <td className="tabular py-1.5 text-right">{num(h.price)}</td><td className="tabular py-1.5 text-right">{inr(h.value, 0)}</td></tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="mt-3 text-small text-[var(--ink-secondary)]">
        {s.enabled
          ? status.next_run_in_sessions === 0 ? "Next rebalance: after the next close." : `Next rebalance in ${status.next_run_in_sessions ?? "?"} session(s), after the close.`
          : running ? "Paused: it holds its basket but will not rebalance." : "Switch it on with a budget, or say “invest 50,000 in autopilot” in the chat."}
      </p>
      {error && <div className="mt-3"><DataUnavailable failure={error} compact /></div>}
      <div className="mt-4 flex flex-wrap gap-2">
        {s.enabled
          ? <button disabled={busy} onClick={() => act(() => autopilot.update({ enabled: false }))} className="rounded-full border border-[var(--hairline-strong)] px-4 py-1.5 text-small">Pause</button>
          : <button disabled={busy} onClick={() => act(() => autopilot.update({ enabled: true }))} className="rounded-full bg-[var(--action)] px-4 py-1.5 text-small font-semibold text-[var(--action-ink)]">{running ? "Resume" : "Switch on"}</button>}
        {(s.enabled || running) && <button disabled={busy} onClick={() => act(() => autopilot.run())} className="rounded-full border border-[var(--hairline-strong)] px-4 py-1.5 text-small">Rebalance now</button>}
        {running && <button disabled={busy} onClick={() => { if (window.confirm("Sell Autopilot's paper holdings and switch it off?")) void act(() => autopilot.stop(true)); }}
          className="rounded-full border border-[color-mix(in_oklab,var(--down)_45%,transparent)] px-4 py-1.5 text-small text-[var(--down)]">Stop and sell</button>}
      </div>
    </Panel>
  );
}

function SettingsCard({ status, onChange }: { status: AutopilotStatus; onChange: () => void }) {
  const s = status.settings;
  const running = Object.keys(s.sleeve).length > 0;
  const [budget, setBudget] = useState(String(s.budget));
  const [cadence, setCadence] = useState(s.cadence_sessions);
  const [symbols, setSymbols] = useState(s.avoid_symbols.join(", "));
  const [sectors, setSectors] = useState(s.avoid_sectors.join(", "));
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<Unavailable | null>(null);
  const split = (v: string) => v.split(",").map((x) => x.trim()).filter(Boolean);
  async function save() {
    setMsg(null); setError(null);
    try {
      await autopilot.update({
        ...(running ? {} : { budget: Number(budget) }), cadence_sessions: cadence,
        avoid_symbols: split(symbols).map((x) => x.toUpperCase()), avoid_sectors: split(sectors),
      });
      setMsg("Saved."); onChange();
    } catch (err) { setError(unavailableFrom(err)); }
  }
  const field = "w-full rounded-[var(--radius-sm)] border border-[var(--hairline-strong)] bg-[var(--surface-2)] px-3 py-2 text-body focus:outline-none";
  return (
    <Panel className="p-6">
      <div className="text-body-lg font-semibold">Settings</div>
      <div className="mt-4 grid gap-4 sm:grid-cols-2">
        <label className="block"><span className="mb-1 block text-caption text-[var(--ink-muted)]">Budget (₹)</span>
          <input value={budget} disabled={running} onChange={(e) => setBudget(e.target.value.replace(/[^\d]/g, ""))} inputMode="numeric" className={clsx(field, "tabular disabled:opacity-50")} />
          {running && <span className="mt-1 block text-caption text-[var(--ink-faint)]">Stop and sell to change the budget.</span>}
        </label>
        <label className="block"><span className="mb-1 block text-caption text-[var(--ink-muted)]">Rebalance every</span>
          <select value={cadence} onChange={(e) => setCadence(Number(e.target.value))} className={field}>
            <option value={5}>5 sessions (weekly)</option><option value={10}>10 sessions</option><option value={20}>20 sessions</option>
          </select>
        </label>
        <label className="block sm:col-span-2"><span className="mb-1 block text-caption text-[var(--ink-muted)]">Never buy these stocks</span>
          <input value={symbols} onChange={(e) => setSymbols(e.target.value)} placeholder="ADANIENT, YESBANK" className={field} />
        </label>
        <label className="block sm:col-span-2"><span className="mb-1 block text-caption text-[var(--ink-muted)]">Avoid these sectors</span>
          <input value={sectors} onChange={(e) => setSectors(e.target.value)} placeholder="Metals, Realty" className={field} />
        </label>
      </div>
      <p className="mt-3 text-caption text-[var(--ink-muted)]">
        It also follows &ldquo;Things to avoid&rdquo; in <Link href="/settings/memory" className="underline">Memory</Link>, sizes for your risk
        profile (<Link href="/profile" className="underline">change it</Link>), and leans away from sectors that are already large in your real holdings.
      </p>
      {error && <div className="mt-3"><DataUnavailable failure={error} compact /></div>}
      <div className="mt-4 flex items-center gap-3">
        <button onClick={save} className="rounded-full bg-[var(--action)] px-5 py-2 text-body font-semibold text-[var(--action-ink)]">Save settings</button>
        {msg && <span className="text-small text-[var(--up)]">{msg}</span>}
      </div>
    </Panel>
  );
}

function NextRun({ enabled, onChange }: { enabled: boolean; onChange: () => void }) {
  const { data, failure, loading } = usePoll(() => autopilot.preview(), 300_000, [enabled]);
  void onChange;
  return (
    <Panel className="p-6">
      <div className="text-body-lg font-semibold">{enabled ? "What the next rebalance would do" : "What Autopilot would hold today"}</div>
      {failure ? <div className="mt-3"><DataUnavailable failure={failure} compact /></div> : loading && !data ? <Loading /> : data && (
        <>
          <table className="mt-3 w-full text-small">
            <thead><tr className="text-left text-caption text-[var(--ink-muted)]"><th className="pb-1.5 font-normal">Stock</th><th className="pb-1.5 font-normal">Sector</th>
              <th className="pb-1.5 text-right font-normal">Weight</th><th className="pb-1.5 text-right font-normal">Value</th></tr></thead>
            <tbody className="divide-y divide-[var(--hairline)]">
              {data.target.positions.map((p) => (
                <tr key={p.symbol}><td className="py-1.5"><Link href={`/chart?symbol=${p.symbol}`} className="font-medium hover:underline">{p.symbol}</Link> <span className="text-caption text-[var(--ink-muted)]">#{p.rank}</span></td>
                  <td className="py-1.5 text-[var(--ink-secondary)]">{p.sector}</td>
                  <td className="tabular py-1.5 text-right">{percent(p.weight, 1)}</td><td className="tabular py-1.5 text-right">{inr(p.value, 0)}</td></tr>
              ))}
            </tbody>
          </table>
          {enabled && (
            <div className="mt-3 text-small text-[var(--ink-secondary)]">
              {data.orders.length === 0 ? "No trades needed: the sleeve matches its target."
                : `${data.orders.length} paper order(s): ` + data.orders.map((o) => `${o.side === "buy" ? "+" : "−"}${o.quantity} ${o.symbol} (${o.reason})`).join("; ")}
            </div>
          )}
          <ul className="mt-3 space-y-1 text-caption text-[var(--ink-muted)]">{data.target.notes.map((n) => <li key={n}>{n}</li>)}</ul>
          {data.target.excluded.length > 0 && (
            <p className="mt-2 text-caption text-[var(--ink-faint)]">Skipped: {data.target.excluded.map((e) => `${e.symbol} (${e.reason})`).join("; ")}.</p>
          )}
        </>
      )}
    </Panel>
  );
}

function Runs({ runs }: { runs: AutopilotRun[] }) {
  return (
    <Panel className="p-6">
      <div className="text-body-lg font-semibold">Run history</div>
      {runs.length === 0 ? <p className="mt-3 text-body text-[var(--ink-muted)]">No runs yet.</p> : (
        <ol className="mt-3 space-y-4">
          {runs.map((r) => (
            <li key={r.id} className="border-l-2 border-[var(--hairline-strong)] pl-4">
              <div className="flex items-baseline justify-between gap-2">
                <span className="font-medium">{r.run_on} · {r.mode === "auto" ? "automatic" : "manual"}</span>
                <span className={clsx("text-caption", r.status === "done" ? "text-[var(--up)]" : r.status === "partial" ? "text-[var(--ink-secondary)]" : "text-[var(--down)]")}>{r.status}</span>
              </div>
              <ul className="mt-1 space-y-0.5 text-small text-[var(--ink-secondary)]">
                {(r.orders ?? []).map((o, i) => (
                  <li key={`${o.symbol}-${i}`}>
                    {o.error ? <span className="text-[var(--down)]">{o.symbol}: not placed ({o.error})</span>
                      : <>{o.side === "buy" ? "Added" : "Reduced"} {o.quantity} {o.symbol}{o.fill_price ? ` at ${num(o.fill_price)}` : ""}{o.reason ? ` · ${o.reason}` : ""}</>}
                  </li>
                ))}
              </ul>
              {r.regime?.state && <div className="mt-1 text-caption text-[var(--ink-muted)]">Regime: {r.regime.state}</div>}
            </li>
          ))}
        </ol>
      )}
    </Panel>
  );
}
