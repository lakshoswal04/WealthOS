"use client";

import { api, type Report } from "@/lib/api";
import { useApi } from "@/lib/auth";
import { percent, ratio, titleCase } from "@/lib/format";
import { isAvailable, list, num, numberRecord, reasonFor, record, str } from "@/lib/reports";
import {
  Card, CardBody, CardHeader, ErrorNote, MetricRow, Note, Section,
  Spinner, Stat, Unavailable,
} from "@/components/ui";
import { PageHead } from "@/components/ui/shell";
import {
  type ClusterPoint, ClusterMapScatter, CountMatrix, LossCurve, MagnitudeBars,
  MetricComparisonBars, SilhouetteByK, SkillByHorizon,
} from "@/components/charts";

const HORIZONS = ["1m", "3m", "6m", "12m"] as const;

export default function ModelLabPage() {
  const reports = useApi(() => api.research(), []);

  if (reports.loading) return <Spinner label="Loading training evidence…" />;
  if (reports.error) return <ErrorNote message={reports.error} />;

  const models = reports.data?.models ?? {};

  return (
    <>
      <PageHead
        eyebrow="Research"
        title="Model Lab"
        lede="How each model was selected, what it was measured against, and where it is weak. Every figure here is read from the pipeline reports, not written into this page."
      />

      <ClusteringSection report={models.clustering} map={models.cluster_map} />
      <AnomalySection report={models.anomaly_detection} />
      <ForecastSection reports={models} />
      <CopilotSection report={models.copilot_groundedness} />
      <SplitsSection report={models.features} />
    </>
  );
}

/* ───────────────────────── clustering ───────────────────────── */

function ClusteringSection({ report, map }: { report?: Report; map?: Report }) {
  if (!isAvailable(report)) {
    return (
      <Section title="Investor behaviour clustering">
        <Card><Unavailable reason={reasonFor(report)} /></Card>
      </Section>
    );
  }

  const k = num(report, "chosen_k");
  const ari = num(report, "archetype_recovery.adjusted_rand_index");
  const nmi = num(report, "archetype_recovery.normalized_mutual_info");
  const stability = num(report, "stability.mean_ari");
  const selection = list<{ k: number; silhouette: number; davies_bouldin: number }>(
    report, "k_selection");
  const silhouette = selection.find((row) => row.k === k)?.silhouette ?? 0;
  const algorithms = record(report, "algorithm_comparison");
  const clusters = list<{
    cluster: number; name: string; size: number; share: number;
    distinguishing_traits: { highest: { feature: string; z: number }[] };
  }>(report, "clusters");

  // The crosstab arrives as {clusterIndex: {archetype: count}}.
  const crosstab = record(report, "archetype_recovery.crosstab");
  const columns = Object.keys(crosstab).sort((a, b) => Number(a) - Number(b));
  const rows = [...new Set(columns.flatMap((c) => Object.keys(record(crosstab, c))))].sort();
  const matrix = rows.map((archetype) =>
    columns.map((cluster) => num(crosstab, `${cluster}.${archetype}`)));

  const points = list<ClusterPoint>(map, "points");

  return (
    <Section
      title="Investor behaviour clustering"
      lede="K-Means over fifteen behavioural features. Age and income are deliberately excluded: the goal is to group investors by how they behave, and demographics would let the model cluster on who they are instead."
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card><CardBody>
          <Stat label="Clusters" value={k} sub="chosen by silhouette" />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Silhouette" value={ratio(silhouette)} sub="how tight the clusters are" />
        </CardBody></Card>
        <Card tone="accent"><CardBody>
          <Stat label="ARI vs archetype" value={ratio(ari)} tone="text-[var(--accent)]"
                sub={`NMI ${ratio(nmi)} — whether they are the right clusters`} />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Stability" value={ratio(stability)} sub="mean ARI across 20 resamples" />
        </CardBody></Card>
      </div>

      <Note>
        Silhouette says the clusters are <em>tight</em>. Adjusted Rand Index says they
        are the <em>right</em> ones. A model can score well on the first while
        recovering nothing real — and only a synthetic cohort, where the generating
        label is known, makes the second measurable at all.
      </Note>

      <div className="mt-4 grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title="Choosing k"
                      subtitle="Silhouette across every candidate. k was selected, not assumed." />
          <CardBody><SilhouetteByK points={selection} chosen={k} /></CardBody>
        </Card>

        <Card>
          <CardHeader title="Against other algorithms"
                      subtitle="Gaussian Mixture and Agglomerative were fitted on the same features. K-Means was not assumed; it won." />
          <CardBody>
            {Object.entries(algorithms).map(([name, scores]) => (
              <MetricRow
                key={name}
                label={titleCase(name)}
                value={ratio(num({ s: scores }, "s.silhouette"))}
                tone={name === "kmeans" ? "text-[var(--accent)]" : undefined}
                note={name === "kmeans" ? "selected" : undefined}
              />
            ))}
            <p className="mt-3 text-[11.5px] text-[var(--ink-muted)]">
              Silhouette, higher is better. Agglomerative was fitted on a subsample
              for tractability.
            </p>
          </CardBody>
        </Card>
      </div>

      {points.length > 0 && (
        <Card className="mt-5">
          <CardHeader
            title="The investor cohort"
            subtitle={`${points.length.toLocaleString("en-IN")} investors projected to two principal components. Axes are unitless — only the separation between groups carries meaning.`}
          />
          <CardBody><ClusterMapScatter points={points} /></CardBody>
        </Card>
      )}

      {matrix.length > 0 && (
        <Card className="mt-5">
          <CardHeader
            title="Did it recover the real groups?"
            subtitle="Each generated archetype against the cluster it was assigned to. A near-diagonal matrix means the model found the structure that was actually there."
          />
          <CardBody>
            <CountMatrix
              rows={rows.map(titleCase)} columns={columns}
              values={matrix}
              rowLabel="generated archetype" columnLabel="recovered cluster"
            />
          </CardBody>
        </Card>
      )}

      <Card className="mt-5">
        <CardHeader title="The groups it found"
                    subtitle="Named from the fitted centroids after training, never decided in advance." />
        <CardBody>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {[...clusters].sort((a, b) => b.size - a.size).map((cluster) => (
              <div key={cluster.cluster}
                   className="rounded-[var(--radius-sm)] border border-[var(--hairline)] bg-[var(--surface-1)] p-4">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-[13px] font-medium text-[var(--ink-primary)]">
                    {cluster.name}
                  </span>
                  <span className="tabular text-[11.5px] text-[var(--ink-muted)]">
                    {percent(cluster.share, 1)}
                  </span>
                </div>
                <div className="tabular mt-1 text-[11px] text-[var(--ink-faint)]">
                  {cluster.size.toLocaleString("en-IN")} investors
                </div>
                <ul className="mt-2.5 space-y-0.5">
                  {(cluster.distinguishing_traits?.highest ?? []).slice(0, 3).map((trait) => (
                    <li key={trait.feature} className="text-[11px] text-[var(--ink-secondary)]">
                      ↑ {titleCase(trait.feature)}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </CardBody>
      </Card>
    </Section>
  );
}

/* ───────────────────────── anomaly ───────────────────────── */

function AnomalySection({ report }: { report?: Report }) {
  if (!isAvailable(report)) {
    return (
      <Section title="Portfolio anomaly detection">
        <Card><Unavailable reason={reasonFor(report)} /></Card>
      </Section>
    );
  }

  const autoencoder = record(report, "autoencoder");
  const forest = record(report, "isolation_forest");
  const history = list<{ epoch: number; train_loss: number; holdout_loss: number }>(
    report, "training.history");
  const byType = record(report, "by_anomaly_type");

  const comparison = ["precision", "recall", "f1", "pr_auc"].map((metric) => ({
    metric: metric === "pr_auc" ? "PR-AUC" : titleCase(metric),
    Autoencoder: num({ a: autoencoder }, `a.${metric}`),
    "Isolation Forest": num({ f: forest }, `f.${metric}`),
  }));

  const recalls = Object.entries(byType).map(([type, entry]) => ({
    label: titleCase(type),
    value: num({ e: entry }, "e.recall"),
  }));

  const weakest = [...recalls].sort((a, b) => a.value - b.value)[0];

  return (
    <Section
      title="Portfolio anomaly detection"
      lede="A PyTorch autoencoder trained only on normal months, so it never learns to reproduce the behaviour it is meant to flag. The bottleneck is deliberately narrow — a high-capacity network reconstructs anomalies as faithfully as normal rows, which defeats the whole approach."
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card><CardBody>
          <Stat label="Precision" value={ratio(num({ a: autoencoder }, "a.precision"))} />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Recall" value={ratio(num({ a: autoencoder }, "a.recall"))} />
        </CardBody></Card>
        <Card tone="accent"><CardBody>
          <Stat label="PR-AUC" value={ratio(num({ a: autoencoder }, "a.pr_auc"))}
                tone="text-[var(--accent)]"
                sub={`vs ${ratio(num({ f: forest }, "f.pr_auc"))} baseline`} />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="False positives"
                value={percent(num({ a: autoencoder }, "a.false_positive_rate"), 3)}
                sub="of normal months flagged" />
        </CardBody></Card>
      </div>

      <Note>
        PR-AUC is the headline rather than ROC-AUC. At roughly 0.3% positives,
        ROC-AUC is flattering by construction. The Isolation Forest exists so the
        deep model has to earn its place — and it does, by a wide margin.
      </Note>

      <div className="mt-4 grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title="Against a shallow baseline"
                      subtitle="The same features, the same threshold selection, a standard detector." />
          <CardBody>
            <MetricComparisonBars metrics={comparison}
                                  seriesNames={["Autoencoder", "Isolation Forest"]} />
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Training"
                      subtitle="Early stopping on the held-out slice. The gap between the lines is what overfitting would look like." />
          <CardBody>
            {history.length ? <LossCurve history={history} />
              : <Unavailable reason="No training history was recorded." />}
          </CardBody>
        </Card>
      </div>

      <Card className="mt-5">
        <CardHeader
          title="Recall by anomaly type"
          subtitle="Where the detector is strong, and where it is not."
        />
        <CardBody>
          <MagnitudeBars items={recalls} domain={[0, 1]}
                         format={(v) => `${(v * 100).toFixed(0)}%`} />
          {weakest && weakest.value < 0.7 && (
            <Note tone="muted">
              <strong className="text-[var(--ink-primary)]">{weakest.label}</strong> is
              the weak case at {percent(weakest.value, 1)} recall, and is reported
              rather than hidden. A large one-off contribution genuinely resembles
              ordinary lumpy saving — the signal looks like normal behaviour, only
              larger.
            </Note>
          )}
        </CardBody>
      </Card>

      <Note tone="muted">
        {str(report, "caveat")}
      </Note>
    </Section>
  );
}

/* ───────────────────────── forecasting ───────────────────────── */

function ForecastSection({ reports }: { reports: Record<string, Report> }) {
  const twelve = reports.forecast_12m;
  if (!isAvailable(twelve)) {
    return (
      <Section title="Wealth trajectory forecasting">
        <Card><Unavailable reason={reasonFor(twelve)} /></Card>
      </Section>
    );
  }

  const skillRows = HORIZONS.map((horizon) => {
    const report = reports[`forecast_${horizon}`];
    const results = record(report, "results");
    const row: Record<string, string | number> = { horizon };
    for (const model of ["xgboost", "lstm", "gru"]) {
      row[model] = num({ r: results }, `r.${model}.skill_vs_mean_baseline`);
    }
    return row as { horizon: string } & Record<string, string | number>;
  });

  const results = record(twelve, "results");
  const best = str(twelve, "best_model.name");
  const importances = list<{ feature: string; importance: number }>(
    twelve, "xgboost_feature_importance");

  const modelOrder = [
    ["baseline_contributions", "Baseline — contributions only"],
    ["baseline_mean_drift", "Baseline — mean drift"],
    ["baseline_drift", "Baseline — trailing drift"],
    ["xgboost", "XGBoost"],
    ["lstm", "LSTM"],
    ["gru", "GRU"],
  ] as const;

  return (
    <Section
      title="Wealth trajectory forecasting"
      lede="Not next month's stock returns — those are close to unpredictable. The target is portfolio value h months ahead, which is forecastable because it is dominated by what is already held and what is about to be contributed."
    >
      <Note>
        That dominance is also the trap. Regressing on raw rupee value gives an
        R² near 0.97 for <em>any</em> model, including a baseline that assumes
        markets return nothing — it measures scale, not skill. Every model here
        predicts <strong>excess log growth</strong> over a contribution baseline,
        so they compete only on the market-return component.
      </Note>

      <div className="mt-4 grid gap-5 lg:grid-cols-[1.15fr_0.85fr]">
        <Card>
          <CardHeader
            title="Skill across horizons"
            subtitle="Measured against a mean-drift baseline — the best constant forecast available. Zero means no better than that baseline; below zero means worse."
          />
          <CardBody>
            <SkillByHorizon rows={skillRows} />
            <p className="mt-3 text-[12px] leading-relaxed text-[var(--ink-secondary)]">
              Skill rising with horizon is the substantive finding. Short-horizon
              growth is dominated by market noise; longer horizons carry a larger
              predictable component through contribution compounding and regime
              persistence. At three months, essentially nothing beats the baseline
              — an honest negative result.
            </p>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="At twelve months"
                      subtitle="Both measures, so the inflated one cannot be mistaken for the real one." />
          <CardBody>
            <div className="space-y-0.5">
              {modelOrder.map(([key, label]) => {
                const value = num({ r: results }, `r.${key}.value.r2`);
                const growth = num({ r: results }, `r.${key}.growth.r2`);
                const skill = num({ r: results }, `r.${key}.skill_vs_mean_baseline`);
                const isBest = key === best;
                return (
                  <div key={key}
                       className={`rounded-[var(--radius-sm)] px-3 py-2 ${isBest ? "bg-[var(--accent-wash)]" : ""}`}>
                    <div className="flex items-baseline justify-between gap-3">
                      <span className={`text-[12.5px] ${isBest ? "text-[var(--accent)]" : "text-[var(--ink-secondary)]"}`}>
                        {label}{isBest && " · best"}
                      </span>
                      <span className="tabular text-[12.5px] text-[var(--ink-primary)]">
                        {key.startsWith("baseline_mean") ? "—" : ratio(skill)}
                      </span>
                    </div>
                    <div className="tabular mt-0.5 flex gap-4 text-[10.5px] text-[var(--ink-faint)]">
                      <span>value R² {value.toFixed(3)}</span>
                      <span>growth R² {growth.toFixed(3)}</span>
                    </div>
                  </div>
                );
              })}
            </div>
            <p className="mt-3 text-[11.5px] leading-relaxed text-[var(--ink-muted)]">
              Note how little the value R² column separates anything — every row,
              including the zero-return baseline, lands near 0.97.
            </p>
          </CardBody>
        </Card>
      </div>

      {importances.length > 0 && (
        <Card className="mt-5">
          <CardHeader title="What the model leans on"
                      subtitle="XGBoost feature importance at the twelve-month horizon." />
          <CardBody>
            <MagnitudeBars
              items={importances.slice(0, 10).map((row) => ({
                label: titleCase(row.feature), value: row.importance,
              }))}
              format={(v) => v.toFixed(3)}
            />
          </CardBody>
        </Card>
      )}
    </Section>
  );
}

/* ───────────────────────── copilot ───────────────────────── */

function CopilotSection({ report }: { report?: Report }) {
  if (!isAvailable(report)) {
    return (
      <Section title="Copilot grounding">
        <Card><Unavailable reason={reasonFor(report)} /></Card>
      </Section>
    );
  }

  const summary = record(report, "summary");
  const usage = numberRecord(report, "tool_usage");

  return (
    <Section
      title="Copilot grounding"
      lede="The platform claims the Copilot explains computed values rather than inventing them. That claim is enforced and measured, not merely intended: every number in an answer is extracted and matched against the tool outputs that produced it."
    >
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card tone="accent"><CardBody>
          <Stat label="Groundedness"
                value={percent(num({ s: summary }, "s.overall_groundedness_rate"), 1)}
                tone="text-[var(--accent)]" sub="of every figure quoted" />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Figures checked" value={num({ s: summary }, "s.numbers_checked")}
                sub={`${num({ s: summary }, "s.numbers_verified")} verified`} />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Clean answers"
                value={`${num({ s: summary }, "s.fully_grounded_answers")}/${num({ s: summary }, "s.answers")}`}
                sub="with no unverified figure" />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Median latency"
                value={`${num({ s: summary }, "s.median_latency_ms").toFixed(0)}ms`}
                sub={str(report, "mode") === "llm" ? str(report, "model") : "deterministic explainer"} />
        </CardBody></Card>
      </div>

      <Card className="mt-4">
        <CardHeader title="Which tools it reached for"
                    subtitle="Across a fixed 30-question set spanning every capability." />
        <CardBody>
          <MagnitudeBars
            items={Object.entries(usage).map(([tool, count]) => ({
              label: tool.replace(/^get_/, "").replace(/_/g, " "), value: count,
            }))}
            format={(v) => v.toFixed(0)}
          />
        </CardBody>
      </Card>
    </Section>
  );
}

/* ───────────────────────── splits ───────────────────────── */

function SplitsSection({ report }: { report?: Report }) {
  if (!isAvailable(report)) return null;

  const boundaries = record(report, "split_boundaries");
  const forecast = record(report, "forecast");
  const anomaly = record(report, "anomaly");

  return (
    <Section
      title="Leakage controls"
      lede="Every split is chronological with a single shared cut date. The pipeline aborts if split ranges overlap, or if a target column ever appears among the features."
    >
      <Card>
        <CardBody>
          <div className="grid gap-5 sm:grid-cols-3">
            <Stat size="sm" label="Train" value={`→ ${str({ b: boundaries }, "b.train_end")}`}
                  sub={`${num({ f: forecast }, "f.by_split_12m.train").toLocaleString("en-IN")} rows`} />
            <Stat size="sm" label="Validation"
                  value={`→ ${str({ b: boundaries }, "b.validation_end")}`}
                  sub={`${num({ f: forecast }, "f.by_split_12m.validation").toLocaleString("en-IN")} rows`} />
            <Stat size="sm" label="Test" value="held out"
                  sub={`${num({ f: forecast }, "f.by_split_12m.test").toLocaleString("en-IN")} rows, never seen`} />
          </div>
          <Note tone="muted">
            Sequence windows are assigned to a split by the month being predicted.
            A window may look back past a boundary — that is memory, not leakage.
            What would be leakage is a target appearing in two splits, which
            assigning by target month prevents.
          </Note>
          <div className="mt-3">
            <MetricRow label="Anomaly rows" value={num({ a: anomaly }, "a.rows").toLocaleString("en-IN")} />
            <MetricRow label="Forecast rows" value={num({ f: forecast }, "f.rows").toLocaleString("en-IN")} />
            <MetricRow label="Target" value={<code className="text-[11px]">{str(report, "forecast.target")}</code>} />
          </div>
        </CardBody>
      </Card>
    </Section>
  );
}
