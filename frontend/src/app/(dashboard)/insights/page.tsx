"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useApi } from "@/lib/auth";
import { percent, rupeesCompact, scoreColor, shortDate, titleCase } from "@/lib/format";
import {
  Badge, Card, CardBody, CardHeader, ErrorNote, Meter, Spinner, Stat, Unavailable,
} from "@/components/ui";
import { PageHead } from "@/components/ui/shell";
import { AnomalyTimeline, ClusterComparison, HealthBreakdown } from "@/components/charts";

export default function InsightsPage() {
  const [horizon, setHorizon] = useState(12);
  const profile = useApi(() => api.investorProfile(), []);
  const anomalies = useApi(() => api.anomalies(), []);
  const forecast = useApi(() => api.forecast(horizon), [horizon]);
  const health = useApi(() => api.healthScore(true), []);

  return (
    <>
      <PageHead
        title="Insights"
        lede="What the models see: your behavioural profile, unusual months, and where the portfolio may be heading."
      />

      {/* ── health score ── */}
      <Card className="rise">
        <CardHeader
          title="Portfolio Health Score"
          subtitle={health.data?.summary}
          action={health.data && (
            <Badge tone={health.data.total >= 70 ? "good" : health.data.total >= 55 ? "warning" : "serious"}>
              {health.data.total.toFixed(0)} / 100 · {health.data.grade}
            </Badge>
          )}
        />
        <CardBody>
          {health.loading && <Spinner />}
          {health.error && <ErrorNote message={health.error} />}
          {health.data && (
            <>
              <HealthBreakdown components={health.data.components} />

              <div className="mt-5 space-y-2.5">
                {health.data.components.map((component) => (
                  <div key={component.name}
                       className="rounded-[8px] border border-[var(--hairline)] bg-[var(--surface-1)] px-4 py-3">
                    <div className="flex items-baseline justify-between gap-3">
                      <span className="text-[13px] font-medium text-[var(--ink-primary)]">
                        {titleCase(component.name)}
                      </span>
                      <span className="tabular text-[12px] text-[var(--ink-secondary)]">
                        {component.score === null
                          ? "not measured"
                          : `${component.score.toFixed(1)} / 100 · ${component.contribution.toFixed(1)} of ${component.weight} pts`}
                      </span>
                    </div>
                    {component.score !== null && (
                      <div className="mt-2">
                        {/* Same status colours as the chart above, so a
                            component does not look different in two places. */}
                        <Meter value={component.score} color={scoreColor(component.score)} />
                      </div>
                    )}
                    <p className="mt-2 text-[11.5px] leading-relaxed text-[var(--ink-secondary)]">
                      {component.reason}
                    </p>
                  </div>
                ))}
              </div>

              {health.data.sensitivity && health.data.sensitivity.length > 0 && (
                <div className="mt-5">
                  <h3 className="text-[12px] font-medium uppercase tracking-[0.08em] text-[var(--ink-muted)]">
                    What moves the score
                  </h3>
                  <p className="mt-1 text-[11.5px] text-[var(--ink-secondary)]">
                    Each input nudged 10% up and down; the swing is how many points the total moves.
                  </p>
                  <ul className="mt-3 space-y-1.5">
                    {health.data.sensitivity.slice(0, 6).map((row) => (
                      <li key={row.input} className="flex items-center justify-between gap-3 text-[12px]">
                        <span className="text-[var(--ink-secondary)]">{titleCase(row.input)}</span>
                        <span className="flex items-center gap-2">
                          <span className="tabular text-[var(--ink-primary)]">±{row.swing.toFixed(2)} pts</span>
                          <span className="text-[11px] text-[var(--ink-muted)]">{row.direction}</span>
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <p className="mt-5 border-t border-[var(--hairline)] pt-3 text-[11.5px] leading-relaxed text-[var(--ink-muted)]">
                {health.data.methodology}
              </p>
            </>
          )}
        </CardBody>
      </Card>

      {/* ── investor profile ── */}
      <Card className="rise mt-5">
        <CardHeader
          title="Investor profile"
          subtitle="Which behavioural group this portfolio resembles, from a K-Means model fitted on 10,000 simulated investors."
          action={profile.data?.available && profile.data.cluster_name && (
            <Badge tone="accent">{profile.data.cluster_name}</Badge>
          )}
        />
        <CardBody>
          {profile.loading && <Spinner />}
          {profile.data && !profile.data.available && <Unavailable reason={profile.data.reason} />}
          {profile.data?.available && (
            <>
              <div className="grid gap-4 sm:grid-cols-3">
                <Stat label="Group" value={profile.data.cluster_name ?? "—"}
                      sub={`${percent(profile.data.cluster_share ?? 0, 1)} of the cohort`} />
                <Stat label="Match confidence" value={percent(profile.data.match_confidence ?? 0, 0)}
                      sub="distance to the next-closest group" />
                <Stat label="Stated tolerance"
                      value={titleCase(profile.data.stated_risk_tolerance ?? "not set")}
                      sub="from your profile" />
              </div>

              {profile.data.largest_differences_from_cluster && (
                <div className="mt-5">
                  <h3 className="mb-2 text-[12px] font-medium uppercase tracking-[0.08em] text-[var(--ink-muted)]">
                    Where you differ most from the group
                  </h3>
                  <ClusterComparison rows={profile.data.largest_differences_from_cluster} />
                </div>
              )}

              {profile.data.caveat && (
                <p className="mt-4 text-[11.5px] leading-relaxed text-[var(--ink-muted)]">
                  {profile.data.caveat}
                </p>
              )}
            </>
          )}
        </CardBody>
      </Card>

      {/* ── anomalies ── */}
      <Card className="rise mt-5">
        <CardHeader
          title="Unusual activity"
          subtitle="Months an autoencoder trained only on normal portfolios could not reconstruct."
          action={anomalies.data?.available && (
            <Badge tone={anomalies.data.anomalies_found ? "warning" : "good"}>
              {anomalies.data.anomalies_found} flagged of {anomalies.data.months_examined}
            </Badge>
          )}
        />
        <CardBody>
          {anomalies.loading && <Spinner />}
          {anomalies.data && !anomalies.data.available && <Unavailable reason={anomalies.data.reason} />}
          {anomalies.data?.available && (
            <>
              <AnomalyTimeline
                timeline={anomalies.data.timeline ?? []}
                threshold={anomalies.data.threshold ?? 0}
              />
              {anomalies.data.anomalies && anomalies.data.anomalies.length > 0 ? (
                <ul className="mt-4 space-y-2">
                  {anomalies.data.anomalies.map((anomaly) => (
                    <li key={anomaly.date}
                        className="rounded-[8px] border border-[var(--hairline)] bg-[var(--surface-1)] px-4 py-3">
                      <div className="flex items-center justify-between gap-3">
                        <span className="text-[13px] text-[var(--ink-primary)]">{shortDate(anomaly.date)}</span>
                        <Badge tone={anomaly.severity === "critical" ? "critical"
                          : anomaly.severity === "warning" ? "warning" : "neutral"}>
                          {anomaly.severity}
                        </Badge>
                      </div>
                      <p className="mt-1.5 text-[11.5px] text-[var(--ink-secondary)]">
                        Driven by {anomaly.contributing_features.map((f) => titleCase(f.feature)).join(", ")}.
                      </p>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="mt-4 text-center text-[13px] text-[var(--ink-secondary)]">
                  Nothing unusual found in the months examined.
                </p>
              )}
              {anomalies.data.caveat && (
                <p className="mt-4 text-[11.5px] leading-relaxed text-[var(--ink-muted)]">
                  {anomalies.data.caveat}
                </p>
              )}
            </>
          )}
        </CardBody>
      </Card>

      {/* ── forecast ── */}
      <Card className="rise mt-5">
        <CardHeader
          title="Wealth forecast"
          subtitle="Projected value from the trained models, against a baseline that assumes zero market return."
          action={
            <div className="flex gap-1">
              {[1, 3, 6, 12].map((h) => (
                <button
                  key={h}
                  onClick={() => setHorizon(h)}
                  className={`rounded-[6px] border px-2.5 py-1 text-[11.5px] transition-colors ${
                    horizon === h
                      ? "border-[var(--accent-dim)] bg-[color-mix(in_oklab,var(--accent)_14%,transparent)] text-[var(--accent)]"
                      : "border-[var(--hairline)] text-[var(--ink-secondary)] hover:bg-[var(--surface-3)]"
                  }`}
                >
                  {h}m
                </button>
              ))}
            </div>
          }
        />
        <CardBody>
          {forecast.loading && <Spinner />}
          {forecast.data && !forecast.data.available && <Unavailable reason={forecast.data.reason} />}
          {forecast.data?.available && (
            <>
              <div className="grid gap-4 sm:grid-cols-3">
                <Stat label="Today" value={rupeesCompact(forecast.data.current_value)} />
                <Stat label="Baseline" value={rupeesCompact(forecast.data.baseline_value)}
                      sub="value plus contributions, zero return" />
                <Stat label="Projected" value={rupeesCompact(forecast.data.projected_value)}
                      sub={`${percent(forecast.data.projected_growth_over_baseline ?? 0, 2, true)} over baseline`} />
              </div>

              {forecast.data.projection_range && (
                <div className="mt-5 rounded-[8px] border border-[var(--hairline)] bg-[var(--surface-1)] p-4">
                  <div className="flex items-baseline justify-between text-[12px]">
                    <span className="tabular text-[var(--ink-secondary)]">
                      {rupeesCompact(forecast.data.projection_range.low)}
                    </span>
                    <span className="text-[11px] uppercase tracking-[0.08em] text-[var(--ink-muted)]">
                      model range
                    </span>
                    <span className="tabular text-[var(--ink-secondary)]">
                      {rupeesCompact(forecast.data.projection_range.high)}
                    </span>
                  </div>
                  <div className="relative mt-2 h-1.5 rounded-full bg-[var(--surface-3)]">
                    <div className="absolute inset-y-0 rounded-full bg-[var(--series-1)]" style={{ left: 0, right: 0 }} />
                  </div>
                  <p className="mt-2.5 text-[11.5px] text-[var(--ink-secondary)]">
                    {forecast.data.projection_range.agreement}.
                  </p>
                </div>
              )}

              {forecast.data.model_predictions && (
                <ul className="mt-4 space-y-1.5">
                  {Object.entries(forecast.data.model_predictions).map(([model, prediction]) => (
                    <li key={model} className="flex items-center justify-between gap-3 text-[12.5px]">
                      <span className="uppercase tracking-wide text-[var(--ink-secondary)]">{model}</span>
                      <span className="tabular text-[var(--ink-primary)]">
                        {rupeesCompact(prediction.projected_value)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}

              {forecast.data.assumptions && (
                <p className="mt-4 rounded-[7px] border border-[var(--accent-dim)] bg-[color-mix(in_oklab,var(--accent)_8%,transparent)] px-3 py-2 text-[11.5px] leading-relaxed text-[var(--accent)]">
                  {forecast.data.assumptions.note}
                </p>
              )}
            </>
          )}
        </CardBody>
      </Card>
    </>
  );
}
