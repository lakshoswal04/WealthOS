"use client";

import clsx from "clsx";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { OIAnalysis, UnderlyingSelect } from "@/components/trade/oi";
import { Change, DataUnavailable, Loading, Panel, Segmented, SourceTag, TextTabs } from "@/components/trade/primitives";
import { usePoll } from "@/lib/hooks";
import { trade, type Contract, type Quote } from "@/lib/trade-api";
import { num, shortExpiry } from "@/lib/tfmt";

type Kind = "gainers" | "losers" | "movers";
type Segment = "stocks" | "options" | "futures";

export default function MarketPage() {
  return <Suspense fallback={<Loading />}><Market /></Suspense>;
}

function Market() {
  const params = useSearchParams();
  const initial = (params.get("segment") as Segment) || "stocks";
  const [kind, setKind] = useState<Kind>("gainers");
  const [segment, setSegment] = useState<Segment>(["stocks", "options", "futures"].includes(initial) ? initial : "stocks");
  const [underlying, setUnderlying] = useState("NIFTY");

  return (
    <div className="space-y-12">
      <Panel className="px-7 py-6">
        <div className="mb-5 flex flex-wrap items-center justify-between gap-4">
          <TextTabs value={kind} onChange={setKind} options={[
            { value: "gainers", label: "Top gainers" }, { value: "losers", label: "Top losers" }, { value: "movers", label: "Top movers" },
          ]} />
          <Segmented value={segment} onChange={setSegment} options={[
            { value: "stocks", label: "Stocks" }, { value: "options", label: "Options" }, { value: "futures", label: "Futures" },
          ]} />
        </div>
        {segment === "stocks" ? <StockMovers kind={kind} /> : <ContractMovers kind={kind} segment={segment} />}
      </Panel>

      <section>
        <div className="mb-5 flex items-center justify-between">
          <h2 className="display text-h1">OI analysis</h2>
          <UnderlyingSelect value={underlying} onChange={setUnderlying} />
        </div>
        <OIAnalysis underlying={underlying} />
      </section>
    </div>
  );
}

function Logo({ symbol }: { symbol: string }) {
  // A monogram tile; real company logos are trademarks and are not bundled.
  const hue = [...symbol].reduce((h, c) => h + c.charCodeAt(0) * 7, 0) % 360;
  return (
    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[10px] text-small font-bold text-white"
      style={{ background: `hsl(${hue} 45% 32%)` }}>
      {symbol.slice(0, 2)}
    </span>
  );
}

function StockMovers({ kind }: { kind: Kind }) {
  const { data, loading, failure } = usePoll(() => trade.movers(kind, 8), 20_000, [kind]);
  if (failure) return <DataUnavailable failure={failure} compact />;
  if (loading && !data) return <Loading />;
  return (
    <>
      <ul className="divide-y divide-[var(--hairline)]">
        {(data?.stocks ?? []).map((q: Quote) => (
          <li key={q.symbol}>
            <Link href={`/chart?symbol=${q.symbol}`} className="flex items-center gap-4 py-3.5 transition-colors hover:bg-[var(--surface-2)]">
              <Logo symbol={q.symbol} />
              <span className="min-w-0 flex-1 truncate">
                <span className="text-body-lg font-semibold">{q.symbol}</span>
                <span className="ml-3 text-body text-[var(--ink-secondary)]">{q.name}</span>
              </span>
              <span className="tabular w-28 text-right text-body-lg">{num(q.ltp)}</span>
              <Change value={q.change_pct} className="w-24 text-right text-body-lg" />
            </Link>
          </li>
        ))}
      </ul>
      <Footer asOf={data?.market.as_of} source={data?.stocks[0]?.source} href="/market/heatmap" />
    </>
  );
}

function ContractMovers({ kind, segment }: { kind: Kind; segment: "options" | "futures" }) {
  const { data, loading, failure } = usePoll(() => trade.topContracts(segment, kind, 8), 30_000, [kind, segment]);
  if (failure) return <DataUnavailable failure={failure} compact />;
  if (loading && !data) return <Loading />;
  return (
    <>
      <ul className="divide-y divide-[var(--hairline)]">
        {(data?.contracts ?? []).map((c: Contract) => (
          <li key={c.symbol}>
            <Link href={segment === "options" ? `/market/option-chain?u=${c.underlying}&expiry=${c.expiry}` : `/chart?symbol=${c.underlying}`}
              className="flex items-center gap-4 py-3.5 hover:bg-[var(--surface-2)]">
              <Logo symbol={c.underlying} />
              <span className="min-w-0 flex-1 truncate">
                <span className="text-body-lg font-semibold">{c.underlying}</span>
                <span className="ml-3 text-body text-[var(--ink-secondary)]">
                  {shortExpiry(c.expiry)} {segment === "options" ? `${c.strike} ${c.option_type}` : `FUT · lot ${c.lot_size ?? ""}`}
                </span>
              </span>
              <span className="tabular w-28 text-right text-body-lg">{num(c.ltp)}</span>
              <Change value={c.change_pct} className="w-24 text-right text-body-lg" />
            </Link>
          </li>
        ))}
      </ul>
      <Footer source="live" href={segment === "options" ? "/market/unusual" : "/market/heatmap"} />
    </>
  );
}

function Footer({ asOf, source, href }: { asOf?: string; source?: string; href: string }) {
  return (
    <div className="mt-4 flex items-center justify-between">
      <span className="flex items-center gap-3 text-body text-[var(--ink-muted)]">
        {asOf && <>as of {new Date(asOf).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false })}</>}
        <SourceTag source={source} />
      </span>
      <Link href={href} className={clsx("text-body-lg font-medium text-[var(--ink-primary)] hover:opacity-80")}>See all ›</Link>
    </div>
  );
}
