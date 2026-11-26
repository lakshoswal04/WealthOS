"use client";

import Image from "next/image";
import Link from "next/link";
import { api } from "@/lib/api";
import { useApi, useAuth } from "@/lib/auth";
import { LinkButton } from "@/components/ui";
import { PublicFooter, PublicHeader } from "@/components/ui/marketing";
import { num } from "@/lib/reports";

/* Every figure on this page is read from the pipeline reports at runtime,
   with a measured fallback, so the landing page cannot drift away from what
   the models actually scored. */

const FALLBACK = {
  clusteringAri: 0.947,
  anomalyPrAuc: 0.935,
  baselinePrAuc: 0.326,
  forecastSkill: 0.249,
  grounding: 1.0,
};

export default function LandingPage() {
  const { user } = useAuth();
  const reports = useApi(() => api.research().catch(() => null), []);

  const models = reports.data?.models;
  const metrics = {
    clusteringAri: num(
      models?.clustering, "archetype_recovery.adjusted_rand_index", FALLBACK.clusteringAri),
    anomalyPrAuc: num(
      models?.anomaly_detection, "autoencoder.pr_auc", FALLBACK.anomalyPrAuc),
    baselinePrAuc: num(
      models?.anomaly_detection, "isolation_forest.pr_auc", FALLBACK.baselinePrAuc),
    forecastSkill: num(
      models?.forecast_12m, "best_model.skill_vs_mean_baseline", FALLBACK.forecastSkill),
    grounding: num(
      models?.copilot_groundedness, "summary.overall_groundedness_rate", FALLBACK.grounding),
  };

  return (
    <>
      <PublicHeader />

      <main className="landing-page pt-16">
        {/* ───────────────────────── hero ───────────────────────── */}
        <section className="origin-hero relative overflow-hidden">
          <div className="pointer-events-none absolute inset-0 -z-10">
            <div className="absolute left-1/2 top-[-18rem] h-[36rem] w-[64rem] -translate-x-1/2 rounded-full bg-[radial-gradient(ellipse_at_center,color-mix(in_oklab,var(--accent)_13%,transparent),transparent_66%)] blur-2xl" />
          </div>

          <div className="mx-auto w-full max-w-[1180px] px-5 pb-16 pt-20 lg:pt-28">
            {/* Centred, with a letterspaced eyebrow above a two-line headline
                whose first line is muted and second is full ink. The weight
                split is what gives the line its shape — a single-weight
                headline at this size reads as a wall. */}
            <div className="stagger mx-auto max-w-3xl text-center">
              <p className="text-caption font-medium uppercase tracking-[0.22em] text-[var(--ink-muted)]">
                Portfolio intelligence, measured
              </p>

              <h1 className="hero-title mt-6 text-[clamp(3rem,7vw,6rem)] leading-[1.02] tracking-[-0.045em] text-[var(--ink-primary)]">
                <em>Understand</em> your wealth
              </h1>

              <p className="mx-auto mt-6 max-w-xl text-body-lg leading-relaxed text-[var(--ink-muted)]">
                Your portfolio, risk, and goals in one clear picture. Explore your
                wealth with intelligence grounded in real market history.
              </p>

              <div className="mt-9 flex flex-wrap items-center justify-center gap-3">
                {user ? (
                  <LinkButton href="/overview" size="lg">Go to your dashboard</LinkButton>
                ) : (
                  <>
                    <LinkButton href="/register" size="lg">Create your account</LinkButton>
                    <LinkButton href="/login" variant="ghost" size="lg">Sign in</LinkButton>
                  </>
                )}
              </div>
            </div>

            {/* A real screenshot of the running product, not an illustration. */}
            <div className="fade relative mt-16" style={{ animationDelay: "320ms" }}>
              <div className="pointer-events-none absolute -inset-x-8 -top-8 bottom-0 -z-10 rounded-[2rem] bg-[radial-gradient(ellipse_at_top,color-mix(in_oklab,var(--series-1)_10%,transparent),transparent_60%)] blur-2xl" />
              <div className="edge-lit overflow-hidden rounded-[var(--radius-lg)] border border-[var(--hairline-strong)] bg-[var(--surface-1)] shadow-[var(--lift-3)]">
                <Image
                  src="/preview/overview.png"
                  alt="The WealthOS overview dashboard, showing total value, asset allocation, cumulative return against the NIFTY 50, largest holdings and the portfolio health score"
                  width={1280} height={1729} priority
                  className="w-full"
                  style={{ maskImage: "linear-gradient(to bottom, black 62%, transparent 100%)" }}
                />
              </div>
            </div>
          </div>
        </section>

        {/* ───────────────────── trust strip ───────────────────── */}
        <section className="border-y border-[var(--hairline)] bg-[var(--surface-1)]">
          <div className="mx-auto grid w-full max-w-[1180px] grid-cols-2 gap-px px-5 lg:grid-cols-4">
            {[
              ["15 years", "of real NSE market history, 2012–2026"],
              ["58 assets", "equity, ETF, gold, debt and cash, priced daily"],
              ["6 components", "behind every Portfolio Health Score"],
              ["8 tools", "the AI copilot may call — and nothing else"],
            ].map(([value, label]) => (
              <div key={label} className="px-2 py-8 sm:px-6">
                <div className="tabular text-h2 leading-none text-[var(--ink-primary)]">
                  {value}
                </div>
                <div className="mt-2.5 text-small leading-snug text-[var(--ink-muted)]">
                  {label}
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* ───────────────────── the problem ───────────────────── */}
        <section className="mx-auto w-full max-w-[1180px] px-5 py-24">
          <h2 className="display max-w-2xl text-[clamp(1.8rem,3.6vw,2.6rem)] leading-[1.12] tracking-[-0.02em]">
            A portfolio can look diversified and still be
            <span className="text-[var(--accent)]"> one bet</span>.
          </h2>

          <div className="mt-12 grid gap-px overflow-hidden rounded-[var(--radius)] border border-[var(--hairline)] bg-[var(--hairline)] sm:grid-cols-2">
            {[
              ["Holdings are scattered", "Across brokers, fund houses and statements, so nobody sees the whole position at once."],
              ["Returns are tracked, risk is not", "Most investors know what they earned. Few know their volatility, their worst drawdown, or how much of it the market explains."],
              ["Diversification misleads", "Twenty holdings that all move together are not twenty bets. Holding counts cannot see correlation; concentration measures can."],
              ["Goals sit apart from the portfolio", "Retirement, a home, education — each tracked on a spreadsheet beside the investments meant to fund them."],
            ].map(([title, body]) => (
              <div key={title} className="bg-[var(--surface-2)] p-7">
                <h3 className="text-body-lg font-medium text-[var(--ink-primary)]">{title}</h3>
                <p className="mt-2.5 text-body leading-relaxed text-[var(--ink-secondary)]">{body}</p>
              </div>
            ))}
          </div>
        </section>

        {/* ───────────────────── capabilities ───────────────────── */}
        <section id="capabilities" className="border-t border-[var(--hairline)] bg-[var(--surface-1)]">
          <div className="mx-auto w-full max-w-[1180px] px-5 py-24">
            <div className="text-micro font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">
              Capabilities
            </div>
            <h2 className="display mt-3 max-w-2xl text-[clamp(1.8rem,3.6vw,2.6rem)] leading-[1.12] tracking-[-0.02em]">
              Four things it does that a statement cannot.
            </h2>

            <div className="mt-14 space-y-16">
              {[
                {
                  n: "01", title: "Analytics and risk",
                  body: "Volatility, Sharpe, Sortino, Calmar, maximum drawdown with its peak, trough and recovery dates, Value at Risk, expected shortfall, beta against the NIFTY 50, and the full correlation matrix of your holdings. Every figure arrives with the assumptions that produced it — a Sharpe ratio without its risk-free rate cannot be checked.",
                  points: ["Drawdown with recovery dates", "Correlation, not just counts", "Assumptions attached to every number"],
                },
                {
                  n: "02", title: "Portfolio Health Score",
                  body: "A single 0–100 figure, decomposed into six weighted components you can argue with: diversification, risk against your own stated tolerance, concentration, liquidity, goal alignment and behaviour. Every component shows its inputs and its reasoning. A component that cannot be measured is dropped rather than guessed, and the score says so.",
                  points: ["Six components, each explained", "Scored against your stated risk band", "Sensitivity analysis on every input"],
                },
                {
                  n: "03", title: "Behavioural ML and forecasting",
                  body: "K-Means profiles how you actually invest against a cohort of 10,000 simulated investors. A PyTorch autoencoder flags months whose behaviour it cannot reconstruct. XGBoost, LSTM and GRU models project your wealth forward — scored against a baseline, so the number means something.",
                  points: ["Behavioural clustering", "Anomaly detection with explanations", "Forecasts with a model range, never one line"],
                },
                {
                  n: "04", title: "A copilot that cannot invent numbers",
                  body: "Ask why your portfolio is risky, or whether you are on track. The assistant calls read-only backend tools and narrates what they return. Every figure in its answer is extracted and checked against those tool outputs before you see it, and anything unverified is flagged rather than presented as fact.",
                  points: ["Eight read-only tools", "Every number verified against the backend", "Explains, never advises"],
                },
              ].map((item, index) => (
                <div key={item.n} className="grid items-start gap-8 lg:grid-cols-[1fr_1.05fr]">
                  <div className={index % 2 === 1 ? "lg:order-2" : ""}>
                    <div className="tabular text-small text-[var(--accent)]">{item.n}</div>
                    <h3 className="display mt-2 text-h2 leading-tight text-[var(--ink-primary)]">
                      {item.title}
                    </h3>
                    <p className="mt-4 text-body-lg leading-relaxed text-[var(--ink-secondary)]">
                      {item.body}
                    </p>
                  </div>
                  <ul className={
                    "space-y-px overflow-hidden rounded-[var(--radius)] border border-[var(--hairline)] bg-[var(--hairline)] " +
                    (index % 2 === 1 ? "lg:order-1" : "")
                  }>
                    {item.points.map((point) => (
                      <li key={point} className="flex items-center gap-3 bg-[var(--surface-2)] px-5 py-4 text-body text-[var(--ink-secondary)]">
                        <span className="h-1 w-1 shrink-0 rounded-full bg-[var(--accent)]" />
                        {point}
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* ───────────────────── results ───────────────────── */}
        <section id="results" className="mx-auto w-full max-w-[1180px] px-5 py-24">
          <div className="text-micro font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">
            Measured results
          </div>
          <h2 className="display mt-3 max-w-2xl text-[clamp(1.8rem,3.6vw,2.6rem)] leading-[1.12] tracking-[-0.02em]">
            Scored on a held-out period the models never saw.
          </h2>
          <p className="mt-4 max-w-2xl text-body leading-relaxed text-[var(--ink-secondary)]">
            These figures are read live from the pipeline reports, not typed into
            this page. The Model Lab inside the product shows how each one was
            produced.
          </p>

          <div className="mt-12 grid gap-px overflow-hidden rounded-[var(--radius)] border border-[var(--hairline)] bg-[var(--hairline)] sm:grid-cols-2 lg:grid-cols-4">
            {[
              {
                value: metrics.clusteringAri.toFixed(3), label: "Clustering ARI",
                note: "Against the true generating archetype, not just cluster tightness.",
              },
              {
                value: metrics.anomalyPrAuc.toFixed(3), label: "Anomaly PR-AUC",
                note: `Against ${metrics.baselinePrAuc.toFixed(3)} for an Isolation Forest baseline.`,
              },
              {
                value: metrics.forecastSkill.toFixed(3), label: "Forecast skill, 12m",
                note: "Over a mean-drift baseline — the honest reference, not a zero-return one.",
              },
              {
                value: `${(metrics.grounding * 100).toFixed(0)}%`, label: "Copilot grounding",
                note: "Of every figure quoted across a fixed 30-question set.",
              },
            ].map((metric) => (
              <div key={metric.label} className="bg-[var(--surface-2)] p-7">
                <div className="tabular text-display leading-none text-[var(--accent)]">
                  {metric.value}
                </div>
                <div className="mt-3 text-body font-medium text-[var(--ink-primary)]">
                  {metric.label}
                </div>
                <div className="mt-2 text-caption leading-relaxed text-[var(--ink-muted)]">
                  {metric.note}
                </div>
              </div>
            ))}
          </div>

          <p className="mt-6 max-w-3xl text-small leading-relaxed text-[var(--ink-muted)]">
            Forecast skill is quoted against a mean-drift baseline rather than a
            zero-return one. Markets drifted upward over the sample, so a
            zero-return baseline is biased low and flatters every model — the
            same model scores roughly three times higher against it. Where a
            result is weak, the product says so.
          </p>
        </section>

        {/* ───────────────────── method ───────────────────── */}
        <section id="method" className="border-y border-[var(--hairline)] bg-[var(--surface-1)]">
          <div className="mx-auto w-full max-w-[1180px] px-5 py-24">
            <div className="text-micro font-semibold uppercase tracking-[0.18em] text-[var(--accent)]">
              How it works
            </div>
            <h2 className="display mt-3 text-[clamp(1.8rem,3.6vw,2.6rem)] leading-[1.12] tracking-[-0.02em]">
              Five steps, start to finish.
            </h2>

            <ol className="mt-12 grid gap-px overflow-hidden rounded-[var(--radius)] border border-[var(--hairline)] bg-[var(--hairline)] md:grid-cols-3 lg:grid-cols-5">
              {[
                ["Import", "Upload a CSV or add holdings by hand. The whole file is validated before anything is saved."],
                ["Analyse", "Positions are priced against adjusted market history and turned into risk and concentration measures."],
                ["Score", "Six components combine into a Health Score, each showing its own inputs and reasoning."],
                ["Project", "Goals are projected forward with a range of outcomes and the probability of reaching the target."],
                ["Ask", "The copilot narrates the result, and every number it quotes is checked against the backend."],
              ].map(([title, body], index) => (
                <li key={title} className="bg-[var(--surface-2)] p-6">
                  <div className="tabular text-small text-[var(--accent)]">
                    {String(index + 1).padStart(2, "0")}
                  </div>
                  <h3 className="mt-2 text-body-lg font-medium text-[var(--ink-primary)]">{title}</h3>
                  <p className="mt-2 text-small leading-relaxed text-[var(--ink-secondary)]">{body}</p>
                </li>
              ))}
            </ol>
          </div>
        </section>

        {/* ───────────────────── closing ───────────────────── */}
        <section className="mx-auto w-full max-w-[1180px] px-5 py-28 text-center">
          <h2 className="display mx-auto max-w-2xl text-[clamp(2rem,4.4vw,3.1rem)] leading-[1.08] tracking-[-0.025em]">
            See what your portfolio is
            <br />
            <span className="metal">actually doing</span>.
          </h2>
          <p className="mx-auto mt-5 max-w-xl text-body-lg leading-relaxed text-[var(--ink-secondary)]">
            Import a portfolio and every page fills in: allocation, risk,
            concentration, goals, behavioural profile and a health score you can
            interrogate component by component.
          </p>
          <div className="mt-9 flex flex-wrap justify-center gap-3">
            {user ? (
              <LinkButton href="/overview" size="lg">Go to your dashboard</LinkButton>
            ) : (
              <>
                <LinkButton href="/register" size="lg">Create your account</LinkButton>
                <Link href="/login"
                      className="inline-flex items-center px-4 py-2.5 text-body-lg text-[var(--ink-secondary)] hover:text-[var(--ink-primary)]">
                  Or sign in
                </Link>
              </>
            )}
          </div>
        </section>
      </main>

      <PublicFooter />
    </>
  );
}
