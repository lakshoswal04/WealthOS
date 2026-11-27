"use client";

import clsx from "clsx";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useOrderTicket } from "@/components/trade/order-ticket";
import { Icon, Loading, Panel, SourceTag, TextTabs } from "@/components/trade/primitives";
import { usePoll } from "@/lib/hooks";
import {
  trade, type FieldInfo, type SavedScreen, type ScreenDefinition, type ScreenFilter, type ScreenInfo, type ScreenResult,
} from "@/lib/trade-api";
import { num, pct, tone } from "@/lib/tfmt";

type Group = "technicals" | "fundamentals" | "candlestick" | "mine";

/** Screen definitions travel in the URL as base64 JSON, so a built screen can be shared. */
const encode = (d: ScreenDefinition) => btoa(encodeURIComponent(JSON.stringify(d)));
const decode = (s: string): ScreenDefinition | null => {
  try { return JSON.parse(decodeURIComponent(atob(s))); } catch { return null; }
};

export default function ScreenerPage() {
  return <Suspense fallback={<Loading />}><Screener /></Suspense>;
}

function Screener() {
  const params = useSearchParams();
  const meta = usePoll(() => trade.screens(), null);
  const saved = usePoll(() => trade.savedScreens(), null);
  const id = params.get("id");
  const savedId = params.get("saved");
  const s = params.get("s");
  const build = params.get("build") === "1";

  if (meta.loading && !meta.data) return <Loading />;
  if (!meta.data) return <p className="text-small text-[var(--down)]">{meta.error}</p>;

  if (build || s) {
    return <Builder fields={meta.data.fields} initial={s ? decode(s) : null} onSaved={() => saved.reload()} />;
  }
  if (id || savedId) {
    const screen = meta.data.screens.find((x) => x.id === id) ?? null;
    const mine = saved.data?.screens.find((x) => String(x.id) === savedId) ?? null;
    return <Results screen={screen} saved={mine} savedId={savedId ? Number(savedId) : null} fields={meta.data.fields} />;
  }
  return <Hub screens={meta.data.screens} saved={saved.data?.screens ?? []} onChanged={() => saved.reload()}
    initialGroup={(params.get("group") as Group) || "technicals"} />;
}

/* ─────────────────────────── hub ─────────────────────────── */

function Hub({ screens, saved, onChanged, initialGroup }: {
  screens: ScreenInfo[]; saved: SavedScreen[]; onChanged: () => void; initialGroup: Group;
}) {
  const [group, setGroup] = useState<Group>(initialGroup);
  const [category, setCategory] = useState("All");
  const [query, setQuery] = useState("");
  useEffect(() => { setCategory("All"); }, [group]);

  const inGroup = screens.filter((x) => x.group === group);
  const categories = ["All", ...Array.from(new Set(inGroup.map((x) => x.category)))];
  const shown = inGroup.filter((x) => (category === "All" || x.category === category)
    && (x.name + x.description).toLowerCase().includes(query.toLowerCase()));

  async function bookmark(screen: ScreenInfo) {
    await trade.saveScreen(screen.name, { filters: screen.filters, sort: screen.sort }).catch(() => {});
    onChanged();
  }

  return (
    <div className="mx-auto max-w-[1250px]">
      <div className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <h1 className="display flex items-center gap-3 text-display">Screeners
          <span title="Screens run over the NIFTY 100 on daily bars, with today's bar from the delayed live quote." className="text-[var(--ink-muted)]"><Icon name="clock" size={18} /></span>
        </h1>
        <Link href="/market/screener?build=1" className="flex items-center gap-2 rounded-full bg-[var(--action)] px-5 py-3 text-body-lg font-medium text-[var(--action-ink)] hover:opacity-90">
          <Icon name="plus" size={18} /> Build new screen
        </Link>
      </div>
      <p className="mb-5 text-body-lg font-medium text-[var(--ink-secondary)]">Ready-made and saved screens</p>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-4 border-b border-[var(--hairline)]">
        <TextTabs size="md" value={group} onChange={setGroup} options={[
          { value: "technicals", label: "Technicals" }, { value: "fundamentals", label: "Fundamentals" },
          { value: "candlestick", label: "Candlestick" }, { value: "mine", label: "My screens", count: saved.length },
        ]} />
        <label className="mb-2 flex w-full max-w-[400px] items-center gap-2 rounded-[var(--radius-sm)] bg-[var(--surface-1)] px-4 py-2.5">
          <Icon name="search" size={16} className="text-[var(--ink-muted)]" />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search screens" className="flex-1 bg-transparent text-body focus:outline-none" />
        </label>
      </div>

      {group === "mine" ? (
        saved.length === 0 ? (
          <p className="py-10 text-body text-[var(--ink-muted)]">No saved screens yet. Bookmark a ready-made screen or build your own.</p>
        ) : (
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            {saved.filter((x) => x.name.toLowerCase().includes(query.toLowerCase())).map((x) => (
              <ScreenCard key={x.id} href={`/market/screener?saved=${x.id}`} name={x.name} tag="Mine"
                description={`${x.definition.filters.length} filter${x.definition.filters.length === 1 ? "" : "s"}`}
                footer={x.definition.filters.map((f) => f.field.replace(/_/g, " ")).join(", ")}
                action={<button aria-label="Delete screen" onClick={async (e) => { e.preventDefault(); await trade.deleteSaved(x.id).catch(() => {}); onChanged(); }}
                  className="text-[var(--ink-muted)] hover:text-[var(--down)]"><Icon name="trash" size={17} /></button>} />
            ))}
          </div>
        )
      ) : (
        <>
          <div className="mb-6 flex flex-wrap gap-3">
            {categories.map((c) => (
              <button key={c} onClick={() => setCategory(c)}
                className={clsx("rounded-full px-5 py-2 text-body-lg transition-colors", c === category
                  ? "bg-[var(--action)] text-[var(--action-ink)]" : "border border-[var(--hairline-strong)] text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]")}>
                {c}
              </button>
            ))}
          </div>
          <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
            {shown.map((x) => (
              <ScreenCard key={x.id} href={`/market/screener?id=${x.id}`} name={x.name} tag={x.category}
                description={x.description} footer={x.columns.map(shortLabel).join(", ")}
                action={<button aria-label={`Save ${x.name} to My screens`} onClick={(e) => { e.preventDefault(); void bookmark(x); }}
                  className="text-[var(--ink-muted)] hover:text-[var(--ink-primary)]"><Icon name="bookmark" size={18} /></button>} />
            ))}
          </div>
        </>
      )}
    </div>
  );
}

function ScreenCard({ href, name, tag, description, footer, action }: {
  href: string; name: string; tag: string; description: string; footer: string; action: React.ReactNode;
}) {
  return (
    <Link href={href} className="group flex min-w-0 flex-col rounded-[var(--radius-lg)] border border-[var(--hairline)] bg-[var(--surface-1)] transition-colors hover:border-[var(--hairline-strong)]">
      <div className="flex-1 px-6 pb-5 pt-6">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="text-h3 font-semibold">{name}</span>
            <span className="rounded-full bg-[var(--surface-3)] px-2.5 py-0.5 text-small">{tag}</span>
          </div>
          <Icon name="chevronRight" size={18} className="mt-1 text-[var(--ink-muted)] group-hover:text-[var(--ink-primary)]" />
        </div>
        <p className="text-body-lg leading-relaxed text-[var(--ink-secondary)]">{description}</p>
      </div>
      <div className="flex items-center justify-between border-t border-[var(--hairline)] px-6 py-4">
        <span className="truncate text-body text-[var(--ink-muted)]">{footer}</span>
        {action}
      </div>
    </Link>
  );
}

const SHORT: Record<string, string> = {
  new_52w_high: "New 52W High", rel_volume: "Rel Vol", avg_value_cr: "Avg Value", pct_from_52w_high: "From 52W High",
  pct_from_52w_low: "From 52W Low", above_sma_200: "Above SMA 200", above_sma_50: "Above SMA 50", rsi_14: "RSI",
  change_1d_pct: "1D %", change_5d_pct: "5D %", change_1m_pct: "1M %", golden_cross_10d: "Golden cross",
  death_cross_10d: "Death cross", macd_bullish_cross_3d: "MACD bullish crossover", close: "Close",
  pe: "P/E", pb: "P/B", roe_pct: "ROE %", market_cap_cr: "Mkt cap (Cr)", dividend_yield_pct: "Div yield %",
  debt_to_equity: "Debt/Equity", sma_50: "SMA 50", sma_200: "SMA 200",
};
const shortLabel = (f: string) => SHORT[f] ?? f.replace(/_/g, " ");

/* ─────────────────────────── results ─────────────────────────── */

function Results({ screen, saved, savedId, fields }: {
  screen: ScreenInfo | null; saved: SavedScreen | null; savedId: number | null; fields: FieldInfo[];
}) {
  const { data, loading, error } = usePoll<ScreenResult>(
    () => savedId ? trade.runSaved(savedId) : trade.runScreen(screen!.id, 100), 60_000, [screen?.id, savedId]);
  const definition: ScreenDefinition | undefined = screen ? { filters: screen.filters, sort: screen.sort } : saved?.definition;
  const title = screen?.name ?? saved?.name ?? "Screen";

  return (
    <div className="mx-auto max-w-[1250px]">
      <Link href="/market/screener" className="text-body text-[var(--ink-muted)] hover:text-[var(--ink-secondary)]">← All screens</Link>
      <div className="mb-6 mt-3 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="display text-display">{title}</h1>
          {screen && <p className="mt-2 max-w-3xl text-body-lg text-[var(--ink-secondary)]">{screen.description}</p>}
          {definition && <FilterChips filters={definition.filters} fields={fields} />}
        </div>
        {definition && (
          <Link href={`/market/screener?s=${encode(definition)}`} className="rounded-full border border-[var(--hairline-strong)] px-5 py-2.5 text-body hover:bg-[var(--surface-3)]">
            Edit filters
          </Link>
        )}
      </div>
      {loading && !data ? <Loading label="Running the screen" /> : error ? <p className="text-small text-[var(--down)]">{error}</p>
        : data && <ResultTable result={data} />}
    </div>
  );
}

function FilterChips({ filters, fields }: { filters: ScreenFilter[]; fields: FieldInfo[] }) {
  const label = (f: string) => fields.find((x) => x.field === f)?.label ?? f;
  const describe = (f: ScreenFilter) => {
    const ops: Record<string, string> = { gt: ">", gte: "≥", lt: "<", lte: "≤", eq: "=" };
    if (f.op === "is_true") return label(f.field);
    if (f.op === "is_false") return `Not: ${label(f.field)}`;
    if (f.op === "between" && Array.isArray(f.value)) return `${label(f.field)} ${f.value[0]}–${f.value[1]}`;
    return `${label(f.field)} ${ops[f.op] ?? f.op} ${f.value_field ? label(f.value_field) : f.value}`;
  };
  return (
    <div className="mt-3 flex flex-wrap gap-2">
      {filters.map((f, i) => <span key={i} className="rounded-full border border-[var(--hairline-strong)] px-3 py-1 text-small text-[var(--ink-secondary)]">{describe(f)}</span>)}
    </div>
  );
}

function ResultTable({ result }: { result: ScreenResult }) {
  const ticket = useOrderTicket();
  if (!result.available) {
    return <Panel className="p-6 text-body text-[var(--ink-secondary)]">This screen cannot run right now: {result.reason}</Panel>;
  }
  const columns = (result.columns ?? []).filter((c) => c !== "close" && c !== "change_1d_pct");
  const fmt = (c: string, v: unknown) => {
    if (v === null || v === undefined) return "—";
    if (typeof v === "boolean") return v ? "Yes" : "No";
    if (typeof v === "number") return c.endsWith("_pct") ? pct(v, 2, c.startsWith("change")) : num(v);
    return String(v);
  };
  return (
    <>
      <div className="mb-3 flex items-center justify-between text-body text-[var(--ink-muted)]">
        <span>{result.count} of {result.universe_size} stocks match</span>
        <span className="flex items-center gap-2">
          {result.price_source === "delayed" && <SourceTag source="delayed" />}
          {result.data_source === "analytics_panel_close_only" && <span title="Daily OHLCV not fetched: run make data">Close-only data</span>}
        </span>
      </div>
      <Panel className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-body">
          <thead>
            <tr className="border-b border-[var(--hairline)] text-left text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">
              <th className="px-5 py-3 font-medium">Stock</th>
              <th className="px-5 py-3 text-right font-medium">Price</th>
              <th className="px-5 py-3 text-right font-medium">1D</th>
              {columns.map((c) => <th key={c} className="px-5 py-3 text-right font-medium">{shortLabel(c)}</th>)}
              <th className="px-5 py-3" />
            </tr>
          </thead>
          <tbody>
            {result.results.length === 0 && (
              <tr><td colSpan={columns.length + 4} className="px-5 py-10 text-center text-[var(--ink-muted)]">No stock meets every filter right now.</td></tr>
            )}
            {result.results.map((r) => (
              <tr key={r.symbol} className="border-b border-[var(--hairline)] last:border-0 hover:bg-[var(--surface-2)]">
                <td className="px-5 py-3">
                  <Link href={`/chart?symbol=${r.symbol}`} className="hover:underline"><span className="font-semibold">{r.symbol}</span></Link>
                  <div className="text-caption text-[var(--ink-muted)]">{r.name}</div>
                </td>
                <td className="tabular px-5 py-3 text-right">{num(r.close as number)}</td>
                <td className={clsx("tabular px-5 py-3 text-right", tone(r.change_1d_pct as number))}>{pct(r.change_1d_pct as number)}</td>
                {columns.map((c) => <td key={c} className="tabular px-5 py-3 text-right">{fmt(c, r[c])}</td>)}
                <td className="px-5 py-3 text-right">
                  <button onClick={() => ticket.open({ instrument: "equity", symbol: r.symbol, side: "buy", ltp: r.close as number, tag: "strategy:screen" })}
                    className="rounded-full bg-[var(--buy)] px-3 py-1 text-small font-semibold text-white">Buy</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </>
  );
}

/* ─────────────────────────── builder ─────────────────────────── */

const NUM_OPS = [{ v: "gte", l: "≥" }, { v: "lte", l: "≤" }, { v: "gt", l: ">" }, { v: "lt", l: "<" }, { v: "between", l: "between" }];
const BOOL_OPS = [{ v: "is_true", l: "is true" }, { v: "is_false", l: "is false" }];

function Builder({ fields, initial, onSaved }: { fields: FieldInfo[]; initial: ScreenDefinition | null; onSaved: () => void }) {
  const router = useRouter();
  const [filters, setFilters] = useState<ScreenFilter[]>(initial?.filters?.length ? initial.filters : [{ field: "rsi_14", op: "lte", value: 35 }]);
  const [sort, setSort] = useState(initial?.sort ?? { field: "change_1d_pct", dir: "desc" as const });
  const [result, setResult] = useState<ScreenResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [savedMsg, setSavedMsg] = useState<string | null>(null);
  const byField = useMemo(() => Object.fromEntries(fields.map((f) => [f.field, f])), [fields]);
  const groups = ["technical", "candlestick", "fundamental"];

  const definition: ScreenDefinition = { filters, sort, limit: 100 };

  async function run() {
    setBusy(true); setError(null);
    try {
      setResult(await trade.runCustom(definition));
      router.replace(`/market/screener?s=${encode(definition)}`, { scroll: false });
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }
  async function save() {
    if (!name.trim()) return;
    try { await trade.saveScreen(name.trim(), definition); setSavedMsg(`Saved "${name.trim()}" to My screens.`); setName(""); onSaved(); }
    catch (err) { setError((err as Error).message); }
  }
  const update = (i: number, patch: Partial<ScreenFilter>) => setFilters((fs) => fs.map((f, j) => j === i ? { ...f, ...patch } : f));

  const control = "rounded-[var(--radius-sm)] border border-[var(--hairline-strong)] bg-[var(--surface-2)] px-3 py-2 text-body focus:outline-none";

  return (
    <div className="mx-auto max-w-[1250px]">
      <Link href="/market/screener" className="text-body text-[var(--ink-muted)] hover:text-[var(--ink-secondary)]">← All screens</Link>
      <h1 className="display mb-2 mt-3 text-display">Build a screen</h1>
      <p className="mb-6 text-body-lg text-[var(--ink-secondary)]">Combine up to twelve filters over the NIFTY 100. Every filter must hold for a stock to match.</p>

      <Panel className="p-6">
        <div className="space-y-3">
          {filters.map((f, i) => {
            const info = byField[f.field];
            const ops = info?.type === "boolean" ? BOOL_OPS : NUM_OPS;
            return (
              <div key={i} className="flex flex-wrap items-center gap-2">
                <select value={f.field} className={clsx(control, "min-w-[260px]")} onChange={(e) => {
                  const nf = byField[e.target.value];
                  update(i, nf?.type === "boolean" ? { field: e.target.value, op: "is_true", value: undefined } : { field: e.target.value, op: "gte", value: 0 });
                }}>
                  {groups.map((g) => (
                    <optgroup key={g} label={g[0].toUpperCase() + g.slice(1)}>
                      {fields.filter((x) => x.group === g).map((x) => <option key={x.field} value={x.field}>{x.label}</option>)}
                    </optgroup>
                  ))}
                </select>
                <select value={f.op} className={control} onChange={(e) => update(i, { op: e.target.value, value: e.target.value === "between" ? [0, 100] : typeof f.value === "number" ? f.value : 0 })}>
                  {ops.map((o) => <option key={o.v} value={o.v}>{o.l}</option>)}
                </select>
                {info?.type !== "boolean" && (f.op === "between" && Array.isArray(f.value) ? (
                  <>
                    <input className={clsx(control, "w-28")} value={f.value[0]} inputMode="decimal" onChange={(e) => update(i, { value: [Number(e.target.value) || 0, (f.value as number[])[1]] })} />
                    <span className="text-[var(--ink-muted)]">and</span>
                    <input className={clsx(control, "w-28")} value={f.value[1]} inputMode="decimal" onChange={(e) => update(i, { value: [(f.value as number[])[0], Number(e.target.value) || 0] })} />
                  </>
                ) : (
                  <input className={clsx(control, "w-32")} value={typeof f.value === "number" ? f.value : ""} inputMode="decimal"
                    onChange={(e) => update(i, { value: Number(e.target.value) || 0 })} />
                ))}
                <button aria-label="Remove filter" onClick={() => setFilters((fs) => fs.filter((_, j) => j !== i))} disabled={filters.length === 1}
                  className="rounded-full p-2 text-[var(--ink-muted)] hover:text-[var(--down)] disabled:opacity-30"><Icon name="x" size={16} /></button>
              </div>
            );
          })}
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button onClick={() => setFilters((fs) => [...fs, { field: "above_sma_200", op: "is_true" }])} disabled={filters.length >= 12}
            className="flex items-center gap-1.5 rounded-full border border-[var(--hairline-strong)] px-4 py-2 text-body hover:bg-[var(--surface-3)] disabled:opacity-40">
            <Icon name="plus" size={15} /> Add filter
          </button>
          <span className="ml-auto flex items-center gap-2 text-body text-[var(--ink-muted)]">Sort by
            <select value={sort.field} onChange={(e) => setSort({ ...sort, field: e.target.value })} className={control}>
              {fields.filter((x) => x.type === "number").map((x) => <option key={x.field} value={x.field}>{x.label}</option>)}
            </select>
            <select value={sort.dir} onChange={(e) => setSort({ ...sort, dir: e.target.value as "asc" | "desc" })} className={control}>
              <option value="desc">High to low</option><option value="asc">Low to high</option>
            </select>
          </span>
          <button onClick={run} disabled={busy} className="rounded-full bg-[var(--action)] px-6 py-2.5 text-body font-semibold text-[var(--action-ink)] disabled:opacity-60">
            {busy ? "Running…" : "Run screen"}
          </button>
        </div>
        <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-[var(--hairline)] pt-4">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Name this screen to save it" className={clsx(control, "w-72")} />
          <button onClick={save} disabled={!name.trim()} className="rounded-full border border-[var(--hairline-strong)] px-4 py-2 text-body hover:bg-[var(--surface-3)] disabled:opacity-40">Save to My screens</button>
          {savedMsg && <span className="text-small text-[var(--up)]">{savedMsg}</span>}
        </div>
        {error && <p className="mt-3 text-small text-[var(--down)]">{error}</p>}
      </Panel>

      {result && <div className="mt-8"><ResultTable result={result} /></div>}
    </div>
  );
}
