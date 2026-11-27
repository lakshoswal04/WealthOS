"use client";

import clsx from "clsx";
import { MagnitudeBars } from "@/components/charts";
import { GrowthCurves, ICByYear, RegimeTimeline, type GrowthSeries } from "@/components/charts/swing";
import {
  Card, CardBody, CardHeader, ErrorNote, LoadingRegion, MetricRow, Note, Section, SkeletonChart, SkeletonStats,
  Stat, Unavailable,
} from "@/components/ui";
import { PageHead } from "@/components/ui/shell";
import { useApi } from "@/lib/auth";
import { percent, ratio } from "@/lib/format";
import { signals, type Leaderboard, type SwingReport } from "@/lib/trade-api";

/* eslint-disable @typescript-eslint/no-explicit-any */

const NAMES: Record<string, string> = {
  ensemble: "Swing ensemble (deployed)", lgbm_ranker: "LightGBM LambdaRank", lgbm_regressor: "LightGBM regression",
  ridge: "Ridge regression", momentum_12_1: "12-1 momentum (baseline)", reversal_1w: "1-week reversal (baseline)",
  random: "Random (baseline)", lstm: "LSTM", gru: "GRU", tcn: "Temporal CNN", transformer: "Transformer",
  blend_lgbm_plus_best_deep: "Ensemble + best network", naive_rv22: "Trailing 1-month vol (naive)",
  har: "HAR-RV", garch: "GARCH(1,1)", lgbm: "LightGBM",
};
const name = (k: string) => NAMES[k] ?? k;
const tone = (v: number | null | undefined) =>
  v === null || v === undefined ? undefined : v > 0 ? "text-[var(--up)]" : v < 0 ? "text-[var(--down)]" : undefined;

export default function SwingLabPage() {
  const reports = useApi(() => signals.reports(), []);
  const board = useApi(() => signals.leaderboard().catch(() => null), []);

  if (reports.loading) {
    return (
      <LoadingRegion label="Loading swing-model evidence">
        <SkeletonStats count={4} />
        <div className="mt-5"><SkeletonChart height={300} /></div>
      </LoadingRegion>
    );
  }
  if (reports.error) return <ErrorNote message={reports.error} />;
  const r = reports.data!;

  return (
    <>
      <PageHead eyebrow="Research · market models" title="Swing Lab"
        lede="How the swing-trading models were built and tested on real NSE prices: every year from 2013 scored by a model trained only on earlier data, every trade paying Indian delivery costs, and every claim set against simple baselines. Every figure here is read from the pipeline reports." />
      <Verdict card={r.swing_model_card} ranker={r.swing_ranker} />
      <DataSection fetch={r.history_fetch} features={r.swing_features} />
      <RankerSection ranker={r.swing_ranker} />
      <RobustnessSection ranker={r.swing_ranker} />
      <DeepSection deep={r.swing_deep} ranker={r.swing_ranker} />
      <RangesSection ranker={r.swing_ranker} />
      <VolatilitySection vol={r.swing_volatility} />
      <RegimeSection regime={r.swing_regime} />
      <ProfilesSection portfolio={r.swing_portfolio} />
      <ForwardSection board={board.data ?? null} />
      <MethodSection ranker={r.swing_ranker} features={r.swing_features} />
    </>
  );
}

/* ───────────────────────── verdict ───────────────────────── */

function Verdict({ card, ranker }: { card: SwingReport; ranker: SwingReport }) {
  if (!card?.available) return <Unavailable reason={card?.reason} />;
  const s = card.signal ?? {};
  const b = card.backtest ?? {};
  const ew = card.equal_weight ?? {};
  const dsr = ranker?.models?.ensemble?.deflated_sharpe?.dsr;
  return (
    <Section title="The verdict" lede="Generated from the numbers below, not written by hand.">
      <Card>
        <CardBody>
          <div className="grid grid-cols-2 gap-6 md:grid-cols-5">
            <Stat label="Rank IC" value={ratio(s.mean_ic, 3)} sub={`t = ${ratio(s.t_stat, 1)}`} />
            <Stat label="Hit rate" value={percent(card.hit_rate?.relative, 1)} sub="right side of the median" />
            <Stat label="CAGR, after costs" value={percent(b.cagr, 1)} sub={`equal-weight ${percent(ew.cagr, 1)}`} tone={tone((b.cagr ?? 0) - (ew.cagr ?? 0))} />
            <Stat label="Sharpe" value={ratio(b.sharpe, 2)} sub={`equal-weight ${ratio(ew.sharpe, 2)}`} />
            <Stat label="Deflated Sharpe" value={percent(dsr, 0)} sub={`after ${ranker?.n_trials_charged ?? "?"} trials`} />
          </div>
          <p className="mt-6 max-w-4xl text-body leading-relaxed text-[var(--ink-secondary)]">{card.verdict}</p>
          <div className="mt-4 flex flex-wrap gap-2">
            {Object.entries(card.gate_checks ?? {}).map(([k, ok]) => (
              <span key={k} className={clsx("rounded-full px-2.5 py-0.5 text-caption",
                ok ? "bg-[color-mix(in_oklab,var(--up)_14%,transparent)] text-[var(--up)]" : "bg-[color-mix(in_oklab,var(--down)_14%,transparent)] text-[var(--down)]")}>
                {ok ? "✓" : "✗"} {k.replaceAll("_", " ")}
              </span>
            ))}
          </div>
        </CardBody>
      </Card>
    </Section>
  );
}

/* ───────────────────────── data ───────────────────────── */

function DataSection({ fetch, features }: { fetch: SwingReport; features: SwingReport }) {
  if (!features?.available) return null;
  const study: any[] = features.survivorship_study ?? [];
  return (
    <Section title="Data, and the survivorship check"
      lede={`Daily prices for today's NIFTY 100 from Yahoo, ${fetch?.first_date ?? ""} to ${fetch?.last_date ?? ""} (median ${fetch?.median_years_per_stock ?? "?"} years per stock). A list of today's members is a list of winners, so the bias was measured before anything was trained.`}>
      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardHeader title="What the bias does to a backtest" subtitle="Equal-weight and plain momentum books from 2013, after costs" />
          <CardBody>
            <table className="w-full text-small">
              <thead><tr className="text-left text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">
                <th className="pb-2 font-medium">Eligible stocks each day</th><th className="pb-2 text-right font-medium">Equal-weight</th>
                <th className="pb-2 text-right font-medium">Momentum top 10</th><th className="pb-2 text-right font-medium">Momentum edge</th></tr></thead>
              <tbody className="divide-y divide-[var(--hairline)]">
                {study.map((row) => (
                  <tr key={row.eligible} className={clsx(row.chosen && "font-medium text-[var(--ink-primary)]")}>
                    <td className="py-2">{row.eligible}{row.chosen && " ← used"}</td>
                    <td className="tabular py-2 text-right">{percent(row.equal_weight_cagr, 1)}</td>
                    <td className="tabular py-2 text-right">{percent(row.momentum_top10_cagr, 1)}</td>
                    <td className={clsx("tabular py-2 text-right", tone(row.momentum_edge_over_equal_weight))}>{percent(row.momentum_edge_over_equal_weight, 1, true)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-4 text-small text-[var(--ink-secondary)]">
              Restricting each date to the most-traded stocks <em>at that time</em> removes most of momentum&apos;s apparent edge, which came from buying stocks that later grew into the index. Models are judged by their margin over the equal-weight book of the same universe, which carries the same remaining bias. NIFTY over the same years: {percent(features.nifty_price_index_since_first_test_year?.cagr, 1)} a year (price index, no dividends).
            </p>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Features" subtitle={`${features.features?.length ?? 0} inputs, each known at the day's close`} />
          <CardBody>
            <MetricRow label="Stock-days" value={(features.rows ?? 0).toLocaleString("en-IN")} />
            <MetricRow label="Stocks ranked each day" value={features.liquid_top} />
            <MetricRow label="Horizon" value={`${features.horizon_sessions} sessions`} />
            <MetricRow label="Target" value="excess 10-session return" note="next open to close, vs the day's mean" />
            <p className="mt-3 text-caption text-[var(--ink-muted)]">
              Returns over 1 week to 12 months, momentum, distance from 52-week high and low, moving-average gaps, RSI, MACD, volatility, beta, volume surges, illiquidity and sector-relative return, each ranked across stocks; plus the market&apos;s trend, volatility, VIX and breadth. Fundamentals were left out: Yahoo only has today&apos;s values, which would leak the future.
            </p>
          </CardBody>
        </Card>
      </div>
    </Section>
  );
}

/* ───────────────────────── ranker ───────────────────────── */

function ModelTable({ models, keys }: { models: Record<string, any>; keys: string[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[820px] text-small">
        <thead><tr className="text-left text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">
          <th className="pb-2 font-medium">Model</th><th className="pb-2 text-right font-medium">Rank IC</th>
          <th className="pb-2 text-right font-medium">t</th><th className="pb-2 text-right font-medium">Hit rate</th>
          <th className="pb-2 text-right font-medium">Top-decile up</th><th className="pb-2 text-right font-medium">CAGR</th>
          <th className="pb-2 text-right font-medium">Sharpe</th><th className="pb-2 text-right font-medium">Max DD</th>
          <th className="pb-2 text-right font-medium">Turnover</th><th className="pb-2 text-right font-medium">Deflated Sharpe</th>
        </tr></thead>
        <tbody className="divide-y divide-[var(--hairline)]">
          {keys.filter((k) => models[k]).map((k) => {
            const m = models[k]; const s = m.signal ?? {}; const b = m.backtest ?? {};
            return (
              <tr key={k} className={clsx(k === "ensemble" && "font-medium text-[var(--ink-primary)]")}>
                <td className="py-2">{name(k)}</td>
                <td className="tabular py-2 text-right">{ratio(s.mean_ic, 4)}</td>
                <td className="tabular py-2 text-right">{ratio(s.t_stat, 1)}</td>
                <td className="tabular py-2 text-right">{percent(s.hit_rate?.relative, 1)}</td>
                <td className="tabular py-2 text-right">{percent(s.hit_rate?.top_decile_positive, 1)}</td>
                <td className="tabular py-2 text-right">{percent(b.cagr, 1)}</td>
                <td className="tabular py-2 text-right">{ratio(b.sharpe, 2)}</td>
                <td className="tabular py-2 text-right">{percent(b.max_drawdown, 0)}</td>
                <td className="tabular py-2 text-right">{b.turnover_annual ? `${b.turnover_annual.toFixed(1)}×` : "—"}</td>
                <td className="tabular py-2 text-right">{percent(m.deflated_sharpe?.dsr, 0)}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RankerSection({ ranker }: { ranker: SwingReport }) {
  if (!ranker?.available) return <Section title="Stock ranker"><Unavailable reason={ranker?.reason} /></Section>;
  const m = ranker.models ?? {};
  const ew = ranker.benchmarks?.equal_weight;
  const nifty = ranker.benchmarks?.nifty;
  const series: GrowthSeries[] = [
    { key: "ensemble", name: name("ensemble"), points: m.ensemble?.curve ?? [] },
    { key: "momentum", name: name("momentum_12_1"), points: m.momentum_12_1?.curve ?? [] },
    { key: "ew", name: "Equal-weight universe", points: ew?.curve ?? [], benchmark: true },
    { key: "nifty", name: "NIFTY 50 (price)", points: nifty?.curve ?? [], benchmark: true },
  ];
  const years = Object.keys(m.ensemble?.signal?.ic_by_year ?? {});
  const icRows = years.map((y) => ({
    year: y, ensemble: m.ensemble.signal.ic_by_year[y], momentum: m.momentum_12_1?.signal?.ic_by_year?.[y] ?? null,
  }));
  const shap = Object.entries(ranker.feature_importance_shap ?? {}).slice(0, 10)
    .map(([k, v]) => ({ label: ranker_label(k), value: v as number }));
  return (
    <Section title="Which stocks will beat the others? The stock ranker"
      lede={`${ranker.design?.walk_forward}. ${ranker.design?.tuning}. ${ranker.design?.portfolio}.`}>
      <Card>
        <CardHeader title="Every model and baseline, out of sample" subtitle={`${ranker.models?.ensemble?.backtest?.start} to ${ranker.models?.ensemble?.backtest?.end}`} />
        <CardBody>
          <ModelTable models={m} keys={["ensemble", "lgbm_ranker", "lgbm_regressor", "ridge", "momentum_12_1", "reversal_1w", "random"]} />
          <p className="mt-3 text-caption text-[var(--ink-muted)]">
            Rank IC: the daily correlation between a model&apos;s ranking and what happened, with a t-statistic corrected for overlapping 10-day labels. Hit rate: share of stocks put on the right side of the day&apos;s median (50% is chance). Equal-weight universe: {percent(ew?.backtest?.cagr, 1)} a year, Sharpe {ratio(ew?.backtest?.sharpe, 2)}, worst drawdown {percent(ew?.backtest?.max_drawdown, 0)}.
          </p>
        </CardBody>
      </Card>
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card><CardHeader title="Growth of ₹1, after costs" subtitle="Log scale" /><CardBody><GrowthCurves series={series} /></CardBody></Card>
        <Card><CardHeader title="Rank IC by test year" subtitle="Above zero: the ranking beat chance that year" />
          <CardBody><ICByYear rows={icRows} series={[{ key: "ensemble", name: "Swing ensemble" }, { key: "momentum", name: "Momentum" }]} /></CardBody></Card>
      </div>
      <Card className="mt-5">
        <CardHeader title="What the ranker relies on" subtitle="Mean absolute SHAP contribution over the last two years" />
        <CardBody><MagnitudeBars items={shap} format={(v) => v.toFixed(3)} /></CardBody>
      </Card>
    </Section>
  );
}

function ranker_label(k: string) {
  const labels: Record<string, string> = {
    f_beta_126: "Beta to NIFTY", f_vol_60: "3-month volatility", f_sector_rel_21: "1-month return vs sector",
    f_dist_52w_low: "Distance from 52-week low", f_idio_vol_126: "Stock-specific volatility", f_ret_63: "3-month return",
    f_atr_pct: "Average true range", f_dist_52w_high: "Distance from 52-week high", f_mom_12_1: "12-1 momentum",
    f_ret_5: "1-week return", f_ret_21: "1-month return", f_vol_20: "1-month volatility", f_rsi_14: "RSI (14)",
    m_vix: "India VIX", m_dispersion_21: "Cross-stock dispersion", m_breadth_200: "Breadth", f_amihud_21: "Illiquidity",
    f_ret_252: "12-month return", f_ret_126: "6-month return", f_max_ret_21: "Biggest daily jump", f_skew_63: "Return skew",
    m_index_ret_21: "NIFTY 1-month return", m_index_vol_20: "NIFTY volatility", f_volume_z_20: "Volume surge",
  };
  return labels[k] ?? k.replace(/^[fm]_/, "").replaceAll("_", " ");
}

/* ───────────────────────── robustness ───────────────────────── */

function RobustnessSection({ ranker }: { ranker: SwingReport }) {
  const rb = ranker?.robustness;
  if (!rb) return null;
  const base = ranker.models?.ensemble?.backtest ?? {};
  const rows: [string, any][] = [
    ["As deployed (top 10, weekly, buffer 20)", base],
    ["Slippage doubled (0.10% a side)", rb.double_slippage], ["Slippage tripled (0.15% a side)", rb.triple_slippage],
    ["Top 5 instead of 10", rb.top_5], ["Top 20 instead of 10", rb.top_20],
    ["Rebalance every 10 sessions", rb.rebalance_every_10], ["No hold buffer", rb.no_buffer],
  ];
  const smoothing: any[] = ranker.smoothing_study ?? [];
  return (
    <Section title="Does it survive the obvious objections?"
      lede="The same out-of-sample scores, with the assumptions changed one at a time.">
      <div className="grid gap-5 lg:grid-cols-2">
        <Card><CardHeader title="Costs and construction" /><CardBody>
          {rows.map(([label, s]) => <MetricRow key={label} label={label} value={`${percent(s?.cagr, 1)} · Sharpe ${ratio(s?.sharpe, 2)} · DD ${percent(s?.max_drawdown, 0)}`} />)}
          <MetricRow label="Rank IC on stocks with 10+ years of history" value={ratio(rb.mature_stocks_only?.mean_ic, 4)} note="least affected by survivorship" />
        </CardBody></Card>
        <Card><CardHeader title="Tried and rejected: smoothing scores" subtitle="Averaging each stock's rank over 5 or 10 days to trade less" /><CardBody>
          {smoothing.filter((x) => x.model === "ensemble").map((x) => (
            <MetricRow key={x.window} label={`${x.window}-day smoothing`} value={`IC ${ratio(x.mean_ic, 4)} · ${percent(x.cagr, 1)} · turnover ${x.turnover_annual?.toFixed(1)}×`} />
          ))}
          <p className="mt-3 text-caption text-[var(--ink-muted)]">The signal fades within days, so smoothing loses more edge than it saves in costs. These variants are still charged to the deflated Sharpe ratio.</p>
        </CardBody></Card>
      </div>
    </Section>
  );
}

/* ───────────────────────── deep learning ───────────────────────── */

function DeepSection({ deep, ranker }: { deep: SwingReport; ranker: SwingReport }) {
  if (!deep?.available) return <Section title="Deep learning"><Unavailable reason={deep?.reason} /></Section>;
  const m = deep.models ?? {};
  const ew = ranker?.benchmarks?.equal_weight;
  const series: GrowthSeries[] = [
    { key: "ensemble", name: name("ensemble"), points: m.ensemble?.curve ?? [] },
    { key: "best", name: name(deep.best_deep_model), points: m[deep.best_deep_model]?.curve ?? [] },
    { key: "blend", name: name("blend_lgbm_plus_best_deep"), points: m.blend_lgbm_plus_best_deep?.curve ?? [] },
    { key: "ew", name: "Equal-weight universe", points: ew?.curve ?? [], benchmark: true },
  ];
  return (
    <Section title="Deep learning against gradient boosting"
      lede={`LSTM, GRU, a temporal convolutional network and a PatchTST-style transformer read ${deep.design?.input}. Same test years, purge, costs and backtest as the ranker; retrained ${deep.design?.retraining}.`}>
      <Card><CardBody>
        <ModelTable models={m} keys={["ensemble", "lstm", "gru", "tcn", "transformer", "blend_lgbm_plus_best_deep"]} />
        <p className="mt-3 text-caption text-[var(--ink-muted)]">
          Chronos (a pre-trained time-series foundation model): {deep.chronos?.status} — {deep.chronos?.reason}.
        </p>
      </CardBody></Card>
      <Card className="mt-5"><CardHeader title="Growth of ₹1, after costs" subtitle="Log scale" /><CardBody><GrowthCurves series={series} /></CardBody></Card>
    </Section>
  );
}

/* ───────────────────────── ranges ───────────────────────── */

function RangesSection({ ranker }: { ranker: SwingReport }) {
  const iv = ranker?.intervals;
  if (!iv) return null;
  return (
    <Section title="Ranges, not point forecasts"
      lede="Each pick shows an 80% range for its next 10 sessions from LightGBM quantile models. Raw quantile models were too narrow, so each fold's range is widened by conformal calibration on the year before it.">
      <Card><CardBody>
        <div className="grid gap-6 md:grid-cols-[220px_1fr]">
          <Stat label="Out-of-sample coverage" value={percent(iv.oos_coverage_calibrated, 1)} sub={`target ${percent(iv.nominal, 0)}`} />
          <div className="grid grid-cols-4 gap-x-6 gap-y-1 sm:grid-cols-7">
            {(iv.per_fold ?? []).map((f: any) => (
              <div key={f.year} className="text-small">
                <div className="text-caption text-[var(--ink-muted)]">{f.year}</div>
                <div className="tabular">{percent(f.calibrated, 0)}</div>
                <div className="tabular text-caption text-[var(--ink-faint)]">raw {percent(f.raw, 0)}</div>
              </div>
            ))}
          </div>
        </div>
      </CardBody></Card>
    </Section>
  );
}

/* ───────────────────────── volatility ───────────────────────── */

function VolatilitySection({ vol }: { vol: SwingReport }) {
  if (!vol?.available) return null;
  const rows = Object.entries(vol.overall_common_rows ?? {}) as [string, any][];
  return (
    <Section title="How much will it move? Volatility forecasts"
      lede={`${vol.question} Used for position sizing, stop distances and the volatility target. ${vol.serving_note}`}>
      <Card><CardBody>
        <table className="w-full text-small">
          <thead><tr className="text-left text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">
            <th className="pb-2 font-medium">Model</th><th className="pb-2 text-right font-medium">QLIKE (lower is better)</th>
            <th className="pb-2 text-right font-medium">R² of log vol</th><th className="pb-2 text-right font-medium">Mean abs. error</th></tr></thead>
          <tbody className="divide-y divide-[var(--hairline)]">
            {rows.map(([k, v]) => (
              <tr key={k} className={clsx(k === vol.serving_model && "font-medium text-[var(--ink-primary)]")}>
                <td className="py-2">{name(k)}{k === vol.serving_model && " ← served"}{k === vol.best_by_qlike && " (best QLIKE)"}</td>
                <td className="tabular py-2 text-right">{ratio(v.qlike, 4)}</td>
                <td className="tabular py-2 text-right">{ratio(v.r2_log_vs_train_mean, 3)}</td>
                <td className="tabular py-2 text-right">{percent(v.mae_vol, 1)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-3 text-caption text-[var(--ink-muted)]">
          The best model cuts forecast loss by {percent(vol.improvement_vs_naive_qlike, 0)} against trailing one-month volatility. R² is modest because the target, realised volatility over just 10 days, is itself noisy.
        </p>
      </CardBody></Card>
    </Section>
  );
}

/* ───────────────────────── regime ───────────────────────── */

function RegimeSection({ regime }: { regime: SwingReport }) {
  if (!regime?.available) return null;
  const followed = Object.entries(regime.what_followed_each_state ?? {}) as [string, any][];
  const ov = regime.overlay ?? {};
  return (
    <Section title="Calm, normal or stress? The regime model"
      lede={`A three-state hidden Markov model on NIFTY's 10-day return, its volatility and India VIX, refitted each year. Probabilities are filtered: each day uses only data up to that day. Exposure map fixed in advance: calm ${percent(regime.exposure_map?.calm, 0)}, normal ${percent(regime.exposure_map?.normal, 0)}, stress ${percent(regime.exposure_map?.stress, 0)}.`}>
      <Card><CardHeader title="Filtered state probabilities, out of sample" /><CardBody>
        <RegimeTimeline points={regime.timeline ?? []} />
      </CardBody></Card>
      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card><CardHeader title="What followed each state" subtitle="NIFTY over the next 10 sessions" /><CardBody>
          <table className="w-full text-small">
            <thead><tr className="text-left text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">
              <th className="pb-2 font-medium">State</th><th className="pb-2 text-right font-medium">Share of days</th>
              <th className="pb-2 text-right font-medium">Realised vol</th><th className="pb-2 text-right font-medium">Mean return</th>
              <th className="pb-2 text-right font-medium">Spell</th></tr></thead>
            <tbody className="divide-y divide-[var(--hairline)]">
              {followed.map(([k, v]) => (
                <tr key={k}><td className="py-2 capitalize">{k}</td>
                  <td className="tabular py-2 text-right">{percent(v.share_of_days, 0)}</td>
                  <td className="tabular py-2 text-right">{percent(v.nifty_next_10d_realised_vol, 0)}</td>
                  <td className={clsx("tabular py-2 text-right", tone(v.nifty_next_10d_mean_return))}>{percent(v.nifty_next_10d_mean_return, 1, true)}</td>
                  <td className="tabular py-2 text-right">{Math.round(v.avg_spell_sessions ?? 0)} days</td></tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-caption text-[var(--ink-muted)]">The model identifies turbulent markets well (volatility roughly doubles from calm to stress), but stress was followed by rebounds on average. It is a risk dial, not a timing signal.</p>
        </CardBody></Card>
        <Card><CardHeader title="With and without the overlay" /><CardBody>
          {Object.entries(ov).filter(([, v]: any) => v?.ungated).map(([k, v]: any) => (
            <MetricRow key={k} label={k === "ensemble_top10" ? "Swing ensemble top 10" : k === "equal_weight" ? "Equal-weight universe" : "NIFTY 50"}
              value={`${percent(v.ungated.cagr, 1)} → ${percent(v.gated.cagr, 1)} · DD ${percent(v.ungated.max_drawdown, 0)} → ${percent(v.gated.max_drawdown, 0)}`} />
          ))}
          <p className="mt-3 text-caption text-[var(--ink-muted)]">The overlay trades some return for smaller drawdowns. That is why conservative profiles lean on it and aggressive ones barely do.</p>
        </CardBody></Card>
      </div>
    </Section>
  );
}

/* ───────────────────────── profiles ───────────────────────── */

function ProfilesSection({ portfolio }: { portfolio: SwingReport }) {
  if (!portfolio?.available) return null;
  const prof = portfolio.profiles ?? {};
  const series: GrowthSeries[] = [
    ...Object.entries(prof).map(([k, v]: any) => ({ key: k, name: k[0].toUpperCase() + k.slice(1), points: v.curve ?? [] })),
    { key: "ew", name: "Equal-weight universe", points: portfolio.benchmarks?.equal_weight_curve ?? [], benchmark: true },
  ];
  return (
    <Section title="From scores to a basket you could hold: risk profiles"
      lede={`${portfolio.construction?.sizing}; ${portfolio.construction?.exposure}. The same code builds the live swing plan.`}>
      <div className="grid gap-5 lg:grid-cols-[1fr_1.3fr]">
        <Card><CardBody>
          {Object.entries(prof).map(([k, v]: any) => (
            <div key={k} className="border-b border-[var(--hairline)] py-3 last:border-0">
              <div className="flex items-baseline justify-between"><span className="font-medium capitalize">{k}</span>
                <span className="tabular text-body">{percent(v.backtest.cagr, 1)} a year</span></div>
              <div className="mt-1 text-caption text-[var(--ink-muted)]">
                vol {percent(v.backtest.volatility, 0)} · Sharpe {ratio(v.backtest.sharpe, 2)} · worst drawdown {percent(v.backtest.max_drawdown, 0)} · {percent(v.backtest.avg_exposure, 0)} invested on average · {v.profile.max_names} names
              </div>
            </div>
          ))}
          <Note tone="muted">Uninvested cash earns nothing here; a real account would earn a liquid-fund rate on it, so the low-exposure profiles are understated.</Note>
        </CardBody></Card>
        <Card><CardHeader title="Growth of ₹1 by profile" subtitle="Log scale, after costs" /><CardBody><GrowthCurves series={series} /></CardBody></Card>
      </div>
    </Section>
  );
}

/* ───────────────────────── forward test ───────────────────────── */

function ForwardSection({ board }: { board: Leaderboard | null }) {
  return (
    <Section title="The forward test"
      lede="Backtests are written knowing how history ended. From the day the models went live, every model's scores are recorded once, frozen, and replayed against prices that arrive later. This is the only test the models cannot have been tuned on.">
      <Card><CardBody>
        {!board || !board.started_on ? <p className="text-body text-[var(--ink-muted)]">The forward test starts the first time the models run on this server.</p> : (
          <>
            <p className="text-small text-[var(--ink-secondary)]">Started {board.started_on} · {board.sessions} session{board.sessions === 1 ? "" : "s"} since. {board.rules}</p>
            {board.note && <div className="mt-3"><Note tone="muted">{board.note}</Note></div>}
            <table className="mt-4 w-full text-small">
              <thead><tr className="text-left text-caption uppercase tracking-[0.08em] text-[var(--ink-muted)]">
                <th className="pb-2 font-medium">Book</th><th className="pb-2 text-right font-medium">Return</th>
                <th className="pb-2 text-right font-medium">Max DD</th><th className="pb-2 text-right font-medium">Signal days</th></tr></thead>
              <tbody className="divide-y divide-[var(--hairline)]">
                {[...board.models, ...(board.benchmarks ?? [])].map((m) => (
                  <tr key={m.model_id}><td className="py-2">{m.label}</td>
                    <td className={clsx("tabular py-2 text-right", tone(m.total_return))}>{percent(m.total_return, 2, true)}</td>
                    <td className="tabular py-2 text-right">{percent(m.max_drawdown, 1)}</td>
                    <td className="tabular py-2 text-right">{m.signal_days ?? "—"}</td></tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </CardBody></Card>
    </Section>
  );
}

/* ───────────────────────── method ───────────────────────── */

function MethodSection({ ranker, features }: { ranker: SwingReport; features: SwingReport }) {
  return (
    <Section title="Method and limits">
      <Card><CardBody>
        <ul className="space-y-2 text-body text-[var(--ink-secondary)]">
          <li>• <b>No look-ahead.</b> Features use prices up to each day&apos;s close; trades happen at the next open; training labels that overlap a test year are purged, with a further 5-session embargo. Unit tests perturb future prices and check nothing computed for earlier dates moves.</li>
          <li>• <b>Tuning before testing.</b> Hyperparameters were chosen on 2011–2012 and frozen; {ranker?.n_trials_charged ?? "all"} configurations were looked at in total, and the deflated Sharpe ratio charges for every one.</li>
          <li>• <b>Costs.</b> STT 0.1% each side, stamp duty 0.015% on buys, exchange and SEBI fees with GST, and 0.05% slippage a side: about 0.32% a round trip.</li>
          <li>• <b>Survivorship.</b> The universe is today&apos;s NIFTY 100 (NSE&apos;s historical lists cannot be fetched automatically). Mitigated with a point-in-time liquidity filter (top {features?.liquid_top}) and by judging against an equal-weight book of the same universe; absolute returns remain flattered.</li>
          <li>• <b>Dividends.</b> Stock prices include dividends; the NIFTY series does not, so NIFTY is a secondary benchmark.</li>
          <li>• <b>What a hit rate of 51% means.</b> Market models rank; they do not foresee. A small, consistent edge across hundreds of stock-days is what the IC and its t-statistic measure.</li>
          <li>• <b>Use.</b> Research signals for paper trading. Not investment advice. Past out-of-sample results do not promise future returns.</li>
        </ul>
      </CardBody></Card>
    </Section>
  );
}
