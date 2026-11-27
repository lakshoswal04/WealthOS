"use client";

import { api, type Report } from "@/lib/api";
import { useApi } from "@/lib/auth";
import { percent, ratio, titleCase } from "@/lib/format";
import { isAvailable, list, num, numberRecord, reasonFor, record, str } from "@/lib/reports";
import {
  Badge, Card, CardBody, CardHeader, ErrorNote, MetricRow, Note, Section,
  LoadingRegion, SkeletonChart, SkeletonStats, Stat, Unavailable,
} from "@/components/ui";
import { PageHead } from "@/components/ui/shell";
import { MagnitudeBars, MetricComparisonBars } from "@/components/charts";

export default function DataQualityPage() {
  const reports = useApi(() => api.research(), []);

  if (reports.loading) {
    return (
      <LoadingRegion label="Loading data pipeline evidence">
        <SkeletonStats count={4} />
        <div className="mt-5"><SkeletonChart height={240} /></div>
      </LoadingRegion>
    );
  }
  if (reports.error) return <ErrorNote message={reports.error} />;

  const data = reports.data?.data ?? {};

  return (
    <>
      <PageHead
        eyebrow="Research"
        title="Data Quality"
        lede="What is real in this platform, what is simulated, and what the pipeline had to repair before any of it could be trusted."
      />

      <SourcesSection seed={data.database_seed} priors={data.big_sharks_priors} />
      <AdjustmentSection report={data.adjustment_impact} />
      <SpliceSection report={data.price_build} />
      <IngestSection report={data.ingest_quality} />
      <CohortSection report={data.cohort} />
    </>
  );
}

/* ───────────────────────── sources ───────────────────────── */

function SourcesSection({ seed, priors }: { seed?: Report; priors?: Report }) {
  const assets = num(seed, "db_assets");
  const prices = num(seed, "db_prices");
  const span = list<string>(seed, "price_span");
  const matchRate = num(priors, "symbol_mapping.match_rate");

  return (
    <Section
      title="Where the data comes from"
      lede="Every price is real. Every investor is simulated. The distinction is maintained everywhere, including here."
    >
      <div className="grid gap-4 sm:grid-cols-3">
        <Card><CardBody>
          <Stat label="Assets priced" value={assets || "—"} sub="equity, ETF, gold, debt, cash" />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Price observations"
                value={prices ? prices.toLocaleString("en-IN") : "—"}
                sub={span.length === 2 ? `${span[0]} to ${span[1]}` : undefined} />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Symbol mapping" value={percent(matchRate, 1)}
                sub="of Big Sharks names matched to NSE symbols" />
        </CardBody></Card>
      </div>

      <div className="mt-4 grid gap-px overflow-hidden rounded-[var(--radius)] border border-[var(--hairline)] bg-[var(--hairline)] md:grid-cols-2">
        {[
          {
            name: "Kaggle — NSE India Stock Data", kind: "Real",
            role: "Deep index history from 1990, 18 sector indices, the NIFTY GS government-securities family and INDIA VIX. 5.23M rows across 2,096 symbols.",
            caveat: "Not used for portfolio return calculations — see the finding below.",
          },
          {
            name: "Yahoo Finance", kind: "Real",
            role: "Split-, bonus- and dividend-adjusted prices for every tradeable asset, 2000 to the present. The only source for gold and ETFs, which the Kaggle set does not contain at all.",
            caveat: "One cached fetch; every later stage runs offline.",
          },
          {
            name: "Kaggle — Big Sharks Portfolio", kind: "Real, derived",
            role: "An empirical distribution of which Indian stocks investors concentrate in, used so the synthetic cohort looks like real portfolios rather than a uniform draw from the NIFTY 50.",
            caveat: "Institutional investors, not retail. Their holding preferences inform the cohort; their position sizes do not.",
          },
          {
            name: "Synthetic investor layer", kind: "Simulated",
            role: "Profiles, holdings, transactions and goals for 10,000 investors generated from six latent archetypes, priced against the real market panel.",
            caveat: "Every investor-level record in any demonstration is simulated and labelled as such.",
          },
        ].map((source) => (
          <div key={source.name} className="bg-[var(--surface-2)] p-5">
            <div className="flex items-start justify-between gap-3">
              <h3 className="text-body font-medium text-[var(--ink-primary)]">{source.name}</h3>
              <Badge tone={source.kind === "Simulated" ? "warning" : "good"}>{source.kind}</Badge>
            </div>
            <p className="mt-2 text-small leading-relaxed text-[var(--ink-secondary)]">
              {source.role}
            </p>
            <p className="mt-2 text-caption leading-relaxed text-[var(--ink-muted)]">
              {source.caveat}
            </p>
          </div>
        ))}
      </div>
    </Section>
  );
}

/* ───────────────── the corporate-action finding ───────────────── */

function AdjustmentSection({ report }: { report?: Report }) {
  if (!isAvailable(report)) {
    return (
      <Section title="The corporate-action problem">
        <Card><Unavailable reason={reasonFor(report)} /></Card>
      </Section>
    );
  }

  const compared = num(report, "symbols_compared");
  const affected = num(report, "symbols_with_phantom_moves");
  const phantom = num(report, "total_phantom_moves");
  const flips = num(report, "sharpe_sign_flips");
  const window = list<string>(report, "window");

  const worst = list<{
    symbol: string; phantom_moves: number;
    vol_unadjusted: number; vol_adjusted: number;
    mdd_unadjusted: number; mdd_adjusted: number;
    sharpe_unadjusted: number; sharpe_adjusted: number;
  }>(report, "worst_cases");

  const comparison = worst.slice(0, 5).map((row) => ({
    metric: row.symbol,
    Unadjusted: Number((row.vol_unadjusted * 100).toFixed(2)),
    Adjusted: Number((row.vol_adjusted * 100).toFixed(2)),
  }));

  return (
    <Section
      title="The corporate-action problem"
      lede="The most consequential data finding in the project, and the reason the raw source is not used for any portfolio calculation."
    >
      <Card tone="accent">
        <CardBody>
          <p className="max-w-3xl text-body-lg leading-relaxed text-[var(--ink-primary)]">
            The Kaggle NSE closing prices are <strong>not adjusted for corporate
            actions</strong>. A 1:1 bonus issue halves the raw price overnight, so
            the series records a 50% crash that never happened — RELIANCE reads
            −50.3% on 2017-09-07, TCS −50.5% on 2018-05-31.
          </p>
          <p className="mt-3 max-w-3xl text-body leading-relaxed text-[var(--ink-secondary)]">
            Every one of those numbers would have looked entirely plausible on a
            dashboard. The source&rsquo;s own <code className="text-caption">Prev Close</code> column
            was checked as a possible fix and carries no adjustment information.
          </p>
        </CardBody>
      </Card>

      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card><CardBody>
          {/* The window matters: the same universe shows 78 phantom moves
              across the full 1996-2021 Kaggle history. This figure is the
              one inside the comparison window, so it must say so. */}
          <Stat label="Phantom crashes" value={phantom} tone="text-[var(--critical-ink)]"
                sub={`across ${affected} of ${compared} symbols, ${window[0] ?? ""} to ${window[1] ?? ""}`} />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Volatility overstated"
                value={`${num(report, "volatility_overstated_pp.max").toFixed(1)}pp`}
                tone="text-[var(--serious-ink)]"
                sub={`${num(report, "volatility_overstated_pp.median").toFixed(1)}pp median`} />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Drawdown overstated"
                value={`${num(report, "max_drawdown_overstated_pp.max").toFixed(1)}pp`}
                tone="text-[var(--serious-ink)]"
                sub={`${num(report, "max_drawdown_overstated_pp.median").toFixed(1)}pp median`} />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Sharpe sign flips" value={flips} tone="text-[var(--critical-ink)]"
                sub="profitable holdings judged loss-makers" />
        </CardBody></Card>
      </div>

      <Note>
        A sign flip is the worst case: a holding that genuinely earned a positive
        risk-adjusted return reads as a loss-maker. {flips} of {compared} symbols
        do exactly that on the unadjusted series.
      </Note>

      <div className="mt-4 grid gap-5 md:grid-cols-2">
        <Card>
          <CardHeader title="Volatility, both ways"
                      subtitle={`Annualised, over ${window[0] ?? "the overlap"} to ${window[1] ?? "2021"}. The five worst-affected symbols.`} />
          <CardBody>
            <MetricComparisonBars metrics={comparison} seriesNames={["Unadjusted", "Adjusted"]} />
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="What it would have reported"
                      subtitle="The same symbols, computed from each series." />
          <CardBody>
            <div className="overflow-x-auto">
              <table className="w-full text-small">
                <caption className="sr-only">
                  Data pipeline validation checks, with the result of each
                </caption>
                <thead>
                  <tr className="border-b border-[var(--hairline)] text-left text-micro uppercase tracking-[0.07em] text-[var(--ink-muted)]">
                    <th className="py-2 pr-3 font-medium">Symbol</th>
                    <th className="py-2 pr-3 text-right font-medium">Max drawdown</th>
                    <th className="py-2 text-right font-medium">Sharpe</th>
                  </tr>
                </thead>
                <tbody>
                  {worst.map((row) => (
                    <tr key={row.symbol} className="border-b border-[var(--hairline)] last:border-0">
                      <td className="py-2 pr-3 text-[var(--ink-primary)]">{row.symbol}</td>
                      <td className="tabular py-2 pr-3 text-right">
                        <span className="text-[var(--critical-ink)]">
                          {(row.mdd_unadjusted * 100).toFixed(1)}%
                        </span>
                        <span className="mx-1 text-[var(--ink-faint)]">→</span>
                        <span className="text-[var(--ink-primary)]">
                          {(row.mdd_adjusted * 100).toFixed(1)}%
                        </span>
                      </td>
                      <td className="tabular py-2 text-right">
                        <span className={row.sharpe_unadjusted < 0
                          ? "text-[var(--critical-ink)]" : "text-[var(--ink-secondary)]"}>
                          {row.sharpe_unadjusted.toFixed(2)}
                        </span>
                        <span className="mx-1 text-[var(--ink-faint)]">→</span>
                        <span className="text-[var(--good-ink)]">
                          {row.sharpe_adjusted.toFixed(2)}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardBody>
        </Card>
      </div>
    </Section>
  );
}

/* ───────────────────────── splices ───────────────────────── */

function SpliceSection({ report }: { report?: Report }) {
  // `return null` here made the whole section vanish with no
  // explanation, so a reader could not tell an unavailable report
  // from a page that had finished rendering.
  if (!isAvailable(report)) {
    return (
      <Card className="mt-5">
        <CardHeader title="Price series splices" />
        <CardBody>
          <Unavailable reason="The data pipeline report has not been generated yet. Run stage 03 to produce it." />
        </CardBody>
      </Card>
    );
  }

  const splices = record(report, "splices");
  const panel = record(report, "panel");
  const repairs = record(report, "repairs");

  return (
    <Section
      title="Joining the sources"
      lede="Two joins happen in the price pipeline, held to deliberately different standards. The pipeline aborts rather than writing a series that looks plausible and is wrong."
    >
      <div className="grid gap-5 md:grid-cols-2">
        {Object.entries(splices).map(([name, raw]) => {
          const splice = { s: raw };
          const kind = str(splice, "s.kind");
          const sameInstrument = kind === "same_instrument";
          return (
            <Card key={name}>
              <CardHeader
                title={name === "NIFTY50" ? "Benchmark — NIFTY 50" : "Debt series"}
                eyebrow={sameInstrument ? "same instrument" : "proxy handoff"}
                subtitle={sameInstrument
                  ? "Both sources carry the identical index, so the join must be near-exact."
                  : "One instrument takes over from a related but distinct one. Recorded as a change of instrument, never as a continuation."}
                action={<Badge tone={sameInstrument ? "good" : "warning"}>
                  {sameInstrument ? "exact" : "handoff"}
                </Badge>}
              />
              <CardBody>
                <MetricRow label="Return correlation"
                           value={ratio(num(splice, "s.return_correlation"), 4)}
                           note={sameInstrument ? "gate ≥ 0.95" : "gate ≥ 0.80"} />
                <MetricRow label="Overlap"
                           value={`${num(splice, "s.overlap_days").toLocaleString("en-IN")} days`} />
                <MetricRow label="Volatility ratio" value={ratio(num(splice, "s.vol_ratio"), 3)}
                           note={sameInstrument ? undefined : "gate 0.5–2.0"} />
                <MetricRow label="Move at the join"
                           value={percent(num(splice, "s.max_move_at_join"), 2)}
                           note="gate < 50%" />
                <MetricRow label="Handover" value={str(splice, "s.handover_date")} />
              </CardBody>
            </Card>
          );
        })}
      </div>

      <Note>
        LTGILTBEES was evaluated first as the debt successor and <strong>rejected</strong>:
        12.7% volatility, three times the index it would have replaced, and a return
        correlation of only 0.30. The gate caught it.
      </Note>

      {Object.keys(repairs).length > 0 && (
        <Card className="mt-4">
          <CardHeader
            title="Feed defects repaired"
            subtitle="Only reverting round trips are repaired, so a genuine one-way jump still fails the build."
          />
          <CardBody>
            <p className="mb-3 text-small leading-relaxed text-[var(--ink-secondary)]">
              NIFTYBEES, BANKBEES and GOLDBEES each sit at a tenth of their price —
              a hundredth for GOLDBEES — for exactly two sessions in December 2019,
              then snap back. A real split does not revert.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {Object.keys(repairs).map((symbol) => (
                <Badge key={symbol} tone="neutral">{symbol}</Badge>
              ))}
            </div>
            <p className="mt-3 text-caption text-[var(--ink-muted)]">
              Panel: {num({ p: panel }, "p.trading_days").toLocaleString("en-IN")} trading
              days × {num({ p: panel }, "p.assets")} assets, {str({ p: panel }, "p.start")} to{" "}
              {str({ p: panel }, "p.end")}.
            </p>
          </CardBody>
        </Card>
      )}
    </Section>
  );
}

/* ───────────────────────── ingest ───────────────────────── */

function IngestSection({ report }: { report?: Report }) {
  if (!isAvailable(report)) {
    return (
      <Card className="mt-5">
        <CardHeader title="Adjustment validation" />
        <CardBody>
          <Unavailable reason="The adjustment validation report has not been generated yet. Run stage 03b to produce it." />
        </CardBody>
      </Card>
    );
  }

  const equity = record(report, "equity");
  const index = record(report, "index");
  const coverage = record(report, "universe_coverage");

  return (
    <Section
      title="Ingest quality"
      lede="Defects are flagged, never silently deleted. An extreme observation in Indian equity history is usually a real event, and removing it would quietly bias every volatility and drawdown figure computed downstream."
    >
      <div className="grid gap-5 md:grid-cols-2">
        <Card>
          <CardHeader title="Equity files" />
          <CardBody>
            <MetricRow label="Rows" value={num({ e: equity }, "e.rows").toLocaleString("en-IN")} />
            <MetricRow label="Symbols" value={num({ e: equity }, "e.symbols").toLocaleString("en-IN")} />
            <MetricRow label="Files read" value={num({ e: equity }, "e.files_read")} />
            <MetricRow label="Files skipped" value={num({ e: equity }, "e.files_skipped")}
                       note="header-only, no data rows" />
            <MetricRow label="OHLC defects" value={num({ e: equity }, "e.invalid_ohlc_rows").toLocaleString("en-IN")}
                       note={`${num({ e: equity }, "e.invalid_ohlc_pct").toFixed(2)}% of rows`} />
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Index files" />
          <CardBody>
            <MetricRow label="Rows" value={num({ i: index }, "i.rows").toLocaleString("en-IN")} />
            <MetricRow label="Indices" value={num({ i: index }, "i.symbols")} />
            <MetricRow label="OHLC defects" value={num({ i: index }, "i.invalid_ohlc_rows").toLocaleString("en-IN")}
                       note={`${num({ i: index }, "i.invalid_ohlc_pct").toFixed(2)}% of rows`} />
            <MetricRow label="Universe coverage"
                       value={`${num({ c: coverage }, "c.found")}/${num({ c: coverage }, "c.required")}`}
                       note="MVP equity symbols present" />
          </CardBody>
        </Card>
      </div>

      <Note tone="muted">
        Early index history records only the closing level and writes 0.0 into
        open, high and low. Those zeros are absent data, not a price of zero
        rupees, and are converted to missing — otherwise every intraday range
        calculation and the OHLC consistency check itself would be meaningless.
        The remaining index defects sit almost entirely in the government-securities
        family, which trades thinly and has unreliable intraday bands. Only
        closing prices are used.
      </Note>
    </Section>
  );
}

/* ───────────────────────── cohort ───────────────────────── */

function CohortSection({ report }: { report?: Report }) {
  if (!isAvailable(report)) {
    return (
      <Card className="mt-5">
        <CardHeader title="Seeded database" />
        <CardBody>
          <Unavailable reason="The database seed report has not been generated yet. Run stage 04 to produce it." />
        </CardBody>
      </Card>
    );
  }

  const archetypes = numberRecord(report, "archetype_counts");
  const anomalies = record(report, "anomalies");
  const byType = numberRecord(report, "anomalies.by_type");
  const investors = num(report, "n_investors");
  const months = num(report, "investor_months");
  const mismatch = num(report, "risk_mismatch_count");

  return (
    <Section
      title="The synthetic cohort"
      lede="Ten thousand investors simulated against the real price panel. Three choices exist specifically to keep the later model evaluation honest."
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card><CardBody>
          <Stat label="Investors" value={investors.toLocaleString("en-IN")} />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Investor-months" value={`${(months / 1e6).toFixed(2)}M`}
                sub="monthly snapshots simulated" />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Risk mismatches" value={percent(mismatch / Math.max(investors, 1), 1)}
                sub="stated tolerance contradicts behaviour, on purpose" />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Anomalous months" value={num({ a: anomalies }, "a.months").toLocaleString("en-IN")}
                sub={`across ${num({ a: anomalies }, "a.investors").toLocaleString("en-IN")} investors`} />
        </CardBody></Card>
      </div>

      <div className="mt-4 grid gap-5 md:grid-cols-2">
        <Card>
          <CardHeader title="Archetype composition"
                      subtitle="Archetypes overlap deliberately — a cohort of cleanly separated blobs would flatter the clustering model into a score that says nothing." />
          <CardBody>
            <MagnitudeBars
              items={Object.entries(archetypes).map(([name, count]) => ({
                label: titleCase(name), value: count,
              }))}
              format={(v) => v.toLocaleString("en-IN")}
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Injected anomalies"
                      subtitle="Applied to recorded snapshots rather than threaded through the simulation, so each one's location and type are known exactly — which is what makes real precision and recall measurable." />
          <CardBody>
            <MagnitudeBars
              items={Object.entries(byType).map(([type, count]) => ({
                label: titleCase(type), value: count,
              }))}
              format={(v) => v.toLocaleString("en-IN")}
              color="var(--series-2)"
            />
            <Note tone="muted">{str(report, "anomalies.caveat")}</Note>
          </CardBody>
        </Card>
      </div>
    </Section>
  );
}
