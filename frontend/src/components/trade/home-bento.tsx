"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { RangeBar } from "@/components/charts/swing";
import { percent } from "@/lib/format";
import { usePoll } from "@/lib/hooks";
import { inr, inrSigned } from "@/lib/tfmt";
import { autopilot, signals, trade } from "@/lib/trade-api";

function Tile({ label, href, cta, children, className }: {
  label: string; href: string; cta: string; children: ReactNode; className?: string;
}) {
  return (
    <Link href={href} className={`group flex flex-col justify-between rounded-[var(--radius-lg)] border border-[var(--hairline)] bg-[var(--surface-1)] p-5 shadow-[var(--lift-1)] transition-all hover:-translate-y-0.5 hover:shadow-[var(--lift-2)] ${className ?? ""}`}>
      <div>
        <div className="label text-[var(--ink-muted)]">{label}</div>
        <div className="mt-3">{children}</div>
      </div>
      <div className="mt-4 text-small text-[var(--ink-muted)] transition-colors group-hover:text-[var(--accent)]">{cta} →</div>
    </Link>
  );
}

const quiet = "text-body text-[var(--ink-muted)]";

/** Four live tiles under the home composer: real data, one action each. */
export function HomeBento() {
  const pf = usePoll(() => trade.paperPortfolio(), 120_000, []);
  const ap = usePoll(() => autopilot.status(), 300_000, []);
  const picks = usePoll(() => signals.list(1), 600_000, []);
  const reg = usePoll(() => signals.regime(), 600_000, []);
  const top = picks.data?.picks[0];
  const r = reg.data;

  return (
    <div className="grid w-full max-w-[1000px] gap-4 sm:grid-cols-2 lg:grid-cols-[1.3fr_1fr_1fr]" data-stagger>
      <Tile label="Paper portfolio" href="/portfolio" cta="Open portfolio" className="lg:row-span-2">
        {pf.data ? (
          <>
            <div className="serif tabular text-[40px] leading-none">{inr(pf.data.total_value, 0)}</div>
            <div className={`mt-2 text-small ${pf.data.day_change >= 0 ? "text-[var(--up)]" : "text-[var(--down)]"}`}>
              {inrSigned(pf.data.day_change)} today · {inrSigned(pf.data.total_return)} since you started
            </div>
            <div className="mt-5 grid grid-cols-2 gap-3 border-t border-[var(--hairline)] pt-4 text-small">
              <div><div className="text-[var(--ink-muted)]">Cash</div><div className="tabular font-medium">{inr(pf.data.cash, 0)}</div></div>
              <div><div className="text-[var(--ink-muted)]">Holdings</div><div className="tabular font-medium">{pf.data.holdings.length}</div></div>
            </div>
          </>
        ) : <p className={quiet}>{pf.failure ? "Unavailable right now." : "Loading…"}</p>}
      </Tile>

      <Tile label="Autopilot" href="/autopilot" cta={ap.data?.settings.enabled ? "See its runs" : "Switch it on"}>
        {ap.data ? (
          ap.data.settings.enabled || Object.keys(ap.data.settings.sleeve).length ? (
            <>
              <div className="serif tabular text-[28px] leading-none">{inr(ap.data.sleeve_value, 0)}</div>
              <div className="mt-2 text-small text-[var(--ink-muted)]">
                {ap.data.pnl_pct != null ? `${ap.data.pnl_pct >= 0 ? "+" : ""}${ap.data.pnl_pct.toFixed(2)}%` : ""} ·{" "}
                {ap.data.next_run_in_sessions === 0 ? "rebalances after the close" : `next run in ${ap.data.next_run_in_sessions ?? "?"} sessions`}
              </div>
            </>
          ) : <p className="text-body text-[var(--ink-secondary)]">Off. Let the models run a paper sleeve for you, with reasons for every trade.</p>
        ) : <p className={quiet}>{ap.failure ? "Unavailable right now." : "Loading…"}</p>}
      </Tile>

      <Tile label="Market regime" href="/market/model-picks" cta="See model picks">
        {r?.available && r.probabilities ? (
          <>
            <div className="serif text-[28px] capitalize leading-none">{r.state}</div>
            <div className="mt-3 flex h-1.5 overflow-hidden rounded-full">
              <span style={{ width: `${r.probabilities.calm * 100}%` }} className="bg-[var(--up)]" />
              <span style={{ width: `${r.probabilities.normal * 100}%` }} className="bg-[var(--sage)]" />
              <span style={{ width: `${r.probabilities.stress * 100}%` }} className="bg-[var(--down)]" />
            </div>
            <div className="mt-2 text-small text-[var(--ink-muted)]">As of {r.as_of} · base exposure {percent(r.base_exposure, 0)}</div>
          </>
        ) : <p className={quiet}>{reg.failure ? reg.failure.message : "Loading…"}</p>}
      </Tile>

      <Tile label="Today's top model pick" href={top ? `/chart?symbol=${top.symbol}` : "/market/model-picks"} cta="Open the chart" className="sm:col-span-2">
        {top ? (
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <div className="serif text-[28px] leading-none">{top.symbol}</div>
              <div className="mt-1.5 text-small text-[var(--ink-muted)]">{top.name} · ranked 1 of {top.of}</div>
            </div>
            <div>
              <RangeBar low={top.range_10d?.low ?? null} mid={top.range_10d?.mid ?? null} high={top.range_10d?.high ?? null} />
              <div className="mt-1 text-right text-caption text-[var(--ink-muted)]">80% range, next 10 sessions</div>
            </div>
          </div>
        ) : <p className={quiet}>{picks.failure ? picks.failure.message : "Loading…"}</p>}
      </Tile>
    </div>
  );
}
