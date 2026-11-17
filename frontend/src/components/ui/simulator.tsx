"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { api, type Simulation } from "@/lib/api";
import { percent, rupeesCompact } from "@/lib/format";
import { Card, CardBody, CardHeader, ErrorNote, Note, Slider, Spinner, Stat } from "@/components/ui";
import { ProjectionFan } from "@/components/charts";

/** Interactive what-if on a goal.
 *
 *  Every projection is computed by the API, never in the browser: the
 *  formulas live in wealthos_core and are shared with the training
 *  pipelines, and a second implementation here would be free to drift.
 *  Input is debounced so dragging a slider does not flood the server.
 */
export function ScenarioSimulator({ goalId }: { goalId: number }) {
  const [simulation, setSimulation] = useState<Simulation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // null means "not yet touched", so the first load shows the user's real
  // position rather than a guessed default.
  const [contribution, setContribution] = useState<number | null>(null);
  const [annualReturn, setAnnualReturn] = useState<number | null>(null);
  const [volatility, setVolatility] = useState<number | null>(null);
  const [months, setMonths] = useState<number | null>(null);

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const touched = contribution !== null || annualReturn !== null
    || volatility !== null || months !== null;

  useEffect(() => {
    const overrides = {
      ...(contribution !== null && { monthly_contribution: contribution }),
      ...(annualReturn !== null && { annual_return: annualReturn }),
      ...(volatility !== null && { annual_volatility: volatility }),
      ...(months !== null && { months }),
    };

    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      setBusy(true);
      api.simulateGoal(goalId, overrides)
        .then((result) => { setSimulation(result); setError(null); })
        .catch((err: Error) => setError(err.message))
        .finally(() => setBusy(false));
    }, touched ? 260 : 0);

    return () => { if (timer.current) clearTimeout(timer.current); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [goalId, contribution, annualReturn, volatility, months]);

  const defaults = simulation?.defaults;

  // Slider positions follow the server's values until the user moves them.
  const current = useMemo(() => ({
    contribution: contribution ?? defaults?.monthly_contribution ?? 0,
    annualReturn: annualReturn ?? defaults?.annual_return ?? 0.1,
    volatility: volatility ?? defaults?.annual_volatility ?? 0.12,
    months: months ?? defaults?.months ?? 120,
  }), [contribution, annualReturn, volatility, months, defaults]);

  function reset() {
    setContribution(null); setAnnualReturn(null); setVolatility(null); setMonths(null);
  }

  if (!simulation && !error) {
    return <Card><CardBody><Spinner label="Running the simulation…" /></CardBody></Card>;
  }
  if (error && !simulation) return <ErrorNote message={error} />;
  if (!simulation) return null;

  const success = simulation.success_probability ?? 0;
  const finals = simulation.monte_carlo.final_values;
  const gap = Math.max(0, simulation.required_monthly_contribution - current.contribution);

  return (
    <Card>
      <CardHeader
        eyebrow="Scenario simulator"
        title="What would it take?"
        subtitle={`${simulation.monte_carlo.n_paths.toLocaleString("en-IN")} simulated paths under assumptions you choose. The band is the point — a single line would imply a precision this does not have.`}
        action={
          <div className="flex items-center gap-2">
            {busy && (
              <span className="h-3 w-3 animate-spin rounded-full border-2 border-[var(--surface-3)] border-t-[var(--accent)]" />
            )}
            {touched && (
              <button onClick={reset}
                      className="text-[11.5px] text-[var(--ink-muted)] transition-colors hover:text-[var(--accent)]">
                Reset
              </button>
            )}
          </div>
        }
      />
      <CardBody>
        <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
          {/* ── controls ── */}
          <div className="space-y-5">
            <Slider
              label="Monthly contribution" value={current.contribution}
              min={0} max={300_000} step={1_000}
              format={(v) => rupeesCompact(v)}
              onChange={setContribution}
              hint={defaults ? `Currently ${rupeesCompact(defaults.monthly_contribution)}` : undefined}
            />
            <Slider
              label="Expected annual return" value={current.annualReturn}
              min={0} max={0.25} step={0.005}
              format={(v) => percent(v, 1)}
              onChange={setAnnualReturn}
              hint={defaults ? `Estimated ${percent(defaults.annual_return, 1)} from your portfolio` : undefined}
            />
            <Slider
              label="Annual volatility" value={current.volatility}
              min={0} max={0.4} step={0.005}
              format={(v) => percent(v, 1)}
              onChange={setVolatility}
              hint="How much the range of outcomes widens"
            />
            <Slider
              label="Horizon" value={current.months}
              min={12} max={480} step={6}
              format={(v) => `${Math.round(v / 12)} years`}
              onChange={setMonths}
              hint={defaults ? `${Math.round(defaults.months / 12)} years to the target date` : undefined}
            />

            <div data-testid="success-probability"
                 className="rounded-[var(--radius-sm)] border border-[var(--hairline)] bg-[var(--surface-1)] p-4">
              <Stat
                label="Chance of reaching the target"
                value={percent(success, 0)}
                tone={success >= 0.75 ? "text-[var(--good-ink)]"
                  : success >= 0.4 ? "text-[var(--warning-ink)]" : "text-[var(--critical-ink)]"}
                sub={`of ${simulation.monte_carlo.n_paths.toLocaleString("en-IN")} simulated paths`}
              />
              {gap > 0 && (
                <p className="mt-3 text-[11.5px] leading-relaxed text-[var(--ink-secondary)]">
                  Reaching {rupeesCompact(simulation.target_amount)} on the average
                  path needs {rupeesCompact(simulation.required_monthly_contribution)} a
                  month — {rupeesCompact(gap)} more than the current setting.
                </p>
              )}
            </div>
          </div>

          {/* ── fan ── */}
          <div>
            <ProjectionFan
              months={simulation.monte_carlo.months}
              bands={simulation.monte_carlo.percentiles}
              deterministic={simulation.deterministic.projected_value}
              target={simulation.target_amount}
            />

            <div className="mt-4 grid gap-3 sm:grid-cols-4">
              {([["p10", "Worst 10%"], ["p25", "Lower 25%"],
                 ["p75", "Upper 25%"], ["p90", "Best 10%"]] as const).map(([key, label]) => (
                <div key={key}
                     className="rounded-[var(--radius-sm)] border border-[var(--hairline)] bg-[var(--surface-1)] px-3 py-2.5">
                  <div className="whitespace-nowrap text-[10px] uppercase tracking-[0.08em] text-[var(--ink-faint)]">
                    {label}
                  </div>
                  <div className="tabular mt-1 text-[14px] text-[var(--ink-primary)]">
                    {rupeesCompact(finals[key])}
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-3 flex flex-wrap items-center gap-3 text-[11.5px] text-[var(--ink-muted)]">
              <span className="flex items-center gap-1.5">
                <span className="h-0.5 w-5 rounded bg-[var(--series-1)]" /> median path
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-0.5 w-5 rounded border-t border-dashed border-[var(--ink-muted)]" />
                average-return projection
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-0.5 w-5 rounded border-t border-dashed border-[var(--accent)]" />
                target
              </span>
            </div>
          </div>
        </div>

        <Note>
          {String(simulation.monte_carlo.assumptions.note)}
        </Note>
      </CardBody>
    </Card>
  );
}
