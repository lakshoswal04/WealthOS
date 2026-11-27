"use client";

import Link from "next/link";
import { useState } from "react";
import { TradeHead } from "@/components/trade/app-shell";
import { DataUnavailable, Loading, Panel, Segmented } from "@/components/trade/primitives";
import { usePoll } from "@/lib/hooks";
import { research, type CalendarEvent } from "@/lib/trade-api";

const LABEL: Record<CalendarEvent["event"], string> = { earnings: "Results", ex_dividend: "Ex-dividend", dividend_payment: "Dividend paid" };

export default function CalendarPage() {
  const [filter, setFilter] = useState<"all" | "earnings" | "dividends">("all");
  const { data, loading, failure } = usePoll(() => research.calendar(90), null);
  const events = (data?.events ?? []).filter((e) => filter === "all" || (filter === "earnings" ? e.event === "earnings" : e.event !== "earnings"));
  const byDate = events.reduce<Record<string, CalendarEvent[]>>((acc, e) => { (acc[e.date] ??= []).push(e); return acc; }, {});
  return (
    <div className="mx-auto max-w-[1000px]">
      <TradeHead title="Calendar" lede="Upcoming results and dividend dates across the NIFTY 100, for the next 90 days."
        aside={<Segmented value={filter} onChange={setFilter} options={[{ value: "all", label: "All" }, { value: "earnings", label: "Results" }, { value: "dividends", label: "Dividends" }]} />} />
      {failure ? <DataUnavailable failure={failure} /> : loading && !data ? <Loading label="Collecting dates" /> : (
        <div className="space-y-5">
          {Object.keys(byDate).length === 0 && <Panel className="p-10 text-center text-body text-[var(--ink-muted)]">Nothing scheduled in this window.</Panel>}
          {Object.entries(byDate).map(([date, list]) => (
            <Panel key={date} className="overflow-hidden">
              <div className="border-b border-[var(--hairline)] bg-[var(--surface-2)] px-6 py-3 text-body font-semibold">
                {new Date(`${date}T00:00:00`).toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}
              </div>
              <ul className="divide-y divide-[var(--hairline)]">
                {list.map((e, i) => (
                  <li key={i} className="flex items-center justify-between px-6 py-3.5">
                    <Link href={`/market/events?symbol=${e.symbol}`} className="hover:underline">
                      <span className="font-semibold">{e.symbol}</span> <span className="text-body text-[var(--ink-muted)]">{e.name}</span>
                    </Link>
                    <span className="flex items-center gap-3 text-body">
                      {e.detail && <span className="text-[var(--ink-muted)]">{e.detail}</span>}
                      <span className="rounded-full border border-[var(--hairline-strong)] px-3 py-0.5 text-small">{LABEL[e.event]}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </Panel>
          ))}
        </div>
      )}
      {data && <p className="mt-3 text-caption text-[var(--ink-faint)]">Source: {data.source}. Companies can move dates; check the exchange filing before acting.</p>}
    </div>
  );
}
