"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { TradeHead } from "@/components/trade/app-shell";
import { MultiStrikeOI, OIAnalysis, OICrossovers, UnderlyingSelect } from "@/components/trade/oi";
import { Loading, TextTabs } from "@/components/trade/primitives";

export default function OIPage() {
  return <Suspense fallback={<Loading />}><OI /></Suspense>;
}

function OI() {
  const params = useSearchParams();
  const initial = params.get("view");
  const [view, setView] = useState<"single" | "multi" | "crossovers">(
    initial === "multi" || initial === "crossovers" ? initial : "single");
  const [underlying, setUnderlying] = useState(params.get("u") ?? "NIFTY");
  return (
    <div>
      <TradeHead title="Open interest" lede="Where option writers are positioned: call OI marks resistance, put OI marks support. Live from your Upstox session."
        aside={<UnderlyingSelect value={underlying} onChange={setUnderlying} />} />
      <div className="mb-6 border-b border-[var(--hairline)]">
        <TextTabs size="md" value={view} onChange={setView} options={[
          { value: "single", label: "OI by strike" }, { value: "multi", label: "Multi-strike OI" },
          { value: "crossovers", label: "OI crossovers" },
        ]} />
      </div>
      {view === "single" ? <OIAnalysis underlying={underlying} />
        : view === "multi" ? <MultiStrikeOI underlying={underlying} /> : <OICrossovers underlying={underlying} />}
    </div>
  );
}
