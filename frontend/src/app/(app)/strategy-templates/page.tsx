"use client";

import clsx from "clsx";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { TradeHead } from "@/components/trade/app-shell";
import { BacktestCard } from "@/components/trade/chat";
import { Loading, Panel, Segmented } from "@/components/trade/primitives";
import { usePoll } from "@/lib/hooks";
import { trade, type Backtest, type Strategy } from "@/lib/trade-api";

type Style = "all" | "intraday" | "swing" | "positional";

export default function StrategiesPage() {
  return <Suspense fallback={<Loading />}><Strategies /></Suspense>;
}

function Strategies() {
  const params = useSearchParams();
  const initial = params.get("style") as Style | null;
  const [style, setStyle] = useState<Style>(initial && ["intraday", "swing", "positional"].includes(initial) ? initial : "all");
  const { data, loading } = usePoll(() => trade.strategies(), null);
  const [active, setActive] = useState<Strategy | null>(null);
  const [symbol, setSymbol] = useState("");
  const [result, setResult] = useState<Backtest | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const list = (data?.strategies ?? []).filter((s) => style === "all" || s.style === style);

  async function run(s: Strategy, sym?: string) {
    setActive(s); setBusy(true); setError(null); setResult(null);
    const chosen = (sym ?? symbol).trim().toUpperCase() || s.default_symbol;
    setSymbol(chosen);
    try {
      const r = await trade.backtest(s.id, chosen);
      if (!r.available) setError(r.reason ?? "Backtest unavailable."); else setResult(r);
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  return (
    <div>
      <TradeHead title="Strategy library"
        lede="Rule-based strategies you can backtest on two years of daily data, with costs, against buy and hold. Results describe the past only."
        aside={<Segmented value={style} onChange={setStyle} options={[
          { value: "all", label: "All" }, { value: "intraday", label: "Intraday" }, { value: "swing", label: "Swing" }, { value: "positional", label: "Positional" },
        ]} />} />
      {loading && !data ? <Loading /> : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
          <div className="space-y-3">
            {list.map((s) => (
              <button key={s.id} onClick={() => run(s, s.default_symbol)}
                className={clsx("block w-full rounded-[var(--radius-lg)] border p-5 text-left transition-colors",
                  active?.id === s.id ? "border-[var(--ink-muted)] bg-[var(--surface-2)]" : "border-[var(--hairline)] bg-[var(--surface-1)] hover:border-[var(--hairline-strong)]")}>
                <div className="flex items-center justify-between gap-3">
                  <span className="text-h3 font-semibold">{s.name}</span>
                  <span className="rounded-full bg-[var(--surface-3)] px-2.5 py-0.5 text-small capitalize">{s.style}</span>
                </div>
                <p className="mt-2 text-body text-[var(--ink-secondary)]">{s.description}</p>
                <div className="mt-3 grid gap-1 text-small text-[var(--ink-muted)] sm:grid-cols-2">
                  <span><span className="text-[var(--up)]">Entry</span> · {s.entry}</span>
                  <span><span className="text-[var(--down)]">Exit</span> · {s.exit}</span>
                </div>
              </button>
            ))}
          </div>
          <div className="xl:sticky xl:top-36 xl:self-start">
            {!active ? (
              <Panel className="p-8 text-body text-[var(--ink-muted)]">Pick a strategy to backtest it.</Panel>
            ) : (
              <Panel className="p-5">
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  <span className="text-body-lg font-semibold">{active.name}</span>
                  <span className="text-[var(--ink-muted)]">on</span>
                  <input value={symbol} onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                    onKeyDown={(e) => { if (e.key === "Enter") void run(active); }}
                    className="w-40 rounded-[var(--radius-sm)] border border-[var(--hairline-strong)] bg-[var(--surface-2)] px-3 py-1.5 text-body uppercase focus:outline-none" />
                  <button onClick={() => run(active)} disabled={busy} className="rounded-full bg-[var(--action)] px-4 py-1.5 text-body font-semibold text-[var(--action-ink)] disabled:opacity-60">
                    {busy ? "Running…" : "Backtest"}
                  </button>
                </div>
                {busy && <Loading label="Backtesting" />}
                {error && <p className="text-small text-[var(--down)]">{error}</p>}
                {result && <BacktestCard card={result} />}
                {result && (
                  <ul className="mt-3 space-y-1 text-caption text-[var(--ink-muted)]">
                    {result.assumptions.map((a) => <li key={a}>· {a}</li>)}
                  </ul>
                )}
              </Panel>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
