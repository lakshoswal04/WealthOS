"use client";

import { useState } from "react";
import { api, type GoalForecast } from "@/lib/api";
import { useApi } from "@/lib/auth";
import { percent, rupees, rupeesCompact, shortDate, titleCase } from "@/lib/format";
import {
  Assumptions, Badge, Button, Card, CardBody, CardHeader, Empty, ErrorNote,
  Field, inputClass, Meter, Spinner, Stat,
} from "@/components/ui";
import { PageHead } from "@/components/ui/shell";
import { GoalProjectionChart } from "@/components/charts";

const GOAL_TYPES = [
  "retirement", "home", "education", "travel",
  "emergency_fund", "wealth_building", "other",
];

export default function GoalsPage() {
  const [refreshKey, setRefreshKey] = useState(0);
  const goals = useApi(() => api.goals(), [refreshKey]);
  const [selected, setSelected] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);

  const forecast = useApi<GoalForecast | null>(
    () => (selected ? api.goalForecast(selected) : Promise.resolve(null)),
    [selected],
  );

  const [form, setForm] = useState({
    name: "", goal_type: "retirement", target_amount: "",
    target_date: "", monthly_contribution: "", priority: "3",
  });
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function createGoal(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setFormError(null);
    try {
      await api.createGoal({
        name: form.name,
        goal_type: form.goal_type,
        target_amount: Number(form.target_amount),
        target_date: form.target_date,
        monthly_contribution: Number(form.monthly_contribution || 0),
        priority: Number(form.priority),
      });
      setForm({ name: "", goal_type: "retirement", target_amount: "",
                target_date: "", monthly_contribution: "", priority: "3" });
      setCreating(false);
      setRefreshKey((k) => k + 1);
    } catch (err) {
      setFormError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function removeGoal(id: number) {
    if (!confirm("Delete this goal?")) return;
    await api.deleteGoal(id);
    if (selected === id) setSelected(null);
    setRefreshKey((k) => k + 1);
  }

  if (goals.loading) return <Spinner label="Loading goals…" />;
  if (goals.error) return <ErrorNote message={goals.error} />;

  const rows = goals.data ?? [];

  return (
    <>
      <PageHead
        title="Goals"
        lede="What the portfolio is for, and whether it is getting there."
        aside={<Button variant="ghost" onClick={() => setCreating((v) => !v)}>
          {creating ? "Cancel" : "New goal"}
        </Button>}
      />

      {creating && (
        <Card className="rise mb-5">
          <CardHeader title="New goal" />
          <CardBody>
            <form onSubmit={createGoal} className="grid gap-3 sm:grid-cols-3">
              {formError && <div className="sm:col-span-3"><ErrorNote message={formError} /></div>}
              <Field label="Name">
                <input required className={inputClass} value={form.name}
                       onChange={(e) => setForm({ ...form, name: e.target.value })}
                       placeholder="Retirement" />
              </Field>
              <Field label="Type">
                <select className={inputClass} value={form.goal_type}
                        onChange={(e) => setForm({ ...form, goal_type: e.target.value })}>
                  {GOAL_TYPES.map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}
                </select>
              </Field>
              <Field label="Priority" hint="1 is highest.">
                <input type="number" min={1} max={5} className={inputClass} value={form.priority}
                       onChange={(e) => setForm({ ...form, priority: e.target.value })} />
              </Field>
              <Field label="Target amount (₹)">
                <input required type="number" min={1} className={inputClass}
                       value={form.target_amount}
                       onChange={(e) => setForm({ ...form, target_amount: e.target.value })}
                       placeholder="10000000" />
              </Field>
              <Field label="Target date">
                <input required type="date" className={inputClass} value={form.target_date}
                       onChange={(e) => setForm({ ...form, target_date: e.target.value })} />
              </Field>
              <Field label="Monthly contribution (₹)">
                <input type="number" min={0} className={inputClass}
                       value={form.monthly_contribution}
                       onChange={(e) => setForm({ ...form, monthly_contribution: e.target.value })}
                       placeholder="30000" />
              </Field>
              <div className="sm:col-span-3">
                <Button type="submit" disabled={busy}>{busy ? "Creating…" : "Create goal"}</Button>
              </div>
            </form>
          </CardBody>
        </Card>
      )}

      {rows.length === 0 ? (
        <Card>
          <Empty
            title="No goals yet"
            body="A portfolio can look excellent in isolation and still be failing its purpose. Adding a goal lets the health score judge it against what it is for."
          />
        </Card>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[0.8fr_1.2fr]">
          <div className="space-y-3">
            {rows.map((goal) => (
              <Card
                key={goal.id}
                className={`cursor-pointer transition-colors ${
                  selected === goal.id ? "border-[var(--accent-dim)]" : "hover:border-[var(--surface-3)]"
                }`}
                onClick={() => setSelected(goal.id)}
              >
                <CardBody>
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-[14px] font-medium text-[var(--ink-primary)]">
                        {goal.name}
                      </div>
                      <div className="mt-0.5 flex items-center gap-2 text-[11px] text-[var(--ink-muted)]">
                        <Badge tone="neutral">{titleCase(goal.goal_type)}</Badge>
                        <span>by {shortDate(goal.target_date)}</span>
                      </div>
                    </div>
                    <button
                      onClick={(e) => { e.stopPropagation(); void removeGoal(goal.id); }}
                      className="shrink-0 text-[11px] text-[var(--ink-muted)] hover:text-[#ff8f8f]"
                    >
                      Delete
                    </button>
                  </div>
                  <div className="mt-3"><Meter value={goal.progress_fraction * 100} color="var(--series-3)" /></div>
                  <div className="tabular mt-1.5 flex justify-between text-[11.5px] text-[var(--ink-secondary)]">
                    <span>{rupeesCompact(goal.current_amount)} of {rupeesCompact(goal.target_amount)}</span>
                    <span>{percent(goal.progress_fraction, 0)}</span>
                  </div>
                </CardBody>
              </Card>
            ))}
            <p className="px-1 text-[11.5px] text-[var(--ink-muted)]">
              Select a goal to see its projection.
            </p>
          </div>

          <div>
            {!selected && (
              <Card><Empty title="Pick a goal"
                           body="Its projection, scenario range and required contribution will appear here." /></Card>
            )}
            {selected && forecast.loading && <Card><CardBody><Spinner /></CardBody></Card>}
            {selected && forecast.error && <ErrorNote message={forecast.error} />}
            {forecast.data && <GoalDetail forecast={forecast.data} />}
          </div>
        </div>
      )}
    </>
  );
}

function GoalDetail({ forecast }: { forecast: GoalForecast }) {
  const estimate = forecast.assumptions.return_estimate as Record<string, unknown> | undefined;

  return (
    <div className="space-y-5">
      <Card className="rise">
        <CardHeader
          title={forecast.name}
          subtitle={`${forecast.months_remaining} months to ${shortDate(forecast.target_date)}`}
          action={
            <Badge tone={forecast.on_track ? "good" : "warning"}>
              {forecast.on_track ? "On track" : "Behind"}
            </Badge>
          }
        />
        <CardBody>
          <div className="grid gap-4 sm:grid-cols-3">
            <Stat label="Projected" value={rupeesCompact(forecast.projected_value)}
                  sub={`${percent(forecast.funding_ratio, 0)} of target`} />
            <Stat label="Target" value={rupeesCompact(forecast.target_amount)}
                  sub={rupees(forecast.target_amount)} />
            <Stat
              label={forecast.on_track ? "Surplus" : "Shortfall"}
              value={rupeesCompact(
                forecast.on_track
                  ? forecast.projected_value - forecast.target_amount
                  : forecast.shortfall,
              )}
              tone={forecast.on_track ? "text-[var(--good)]" : "text-[#ff8f8f]"}
            />
          </div>

          <div className="mt-5">
            <GoalProjectionChart path={forecast.path} target={forecast.target_amount} />
          </div>
        </CardBody>
      </Card>

      <Card className="rise">
        <CardHeader
          title="Contribution"
          subtitle="What reaching the target requires, against what is set."
        />
        <CardBody>
          <div className="grid gap-4 sm:grid-cols-3">
            <Stat label="Currently" value={rupeesCompact(forecast.monthly_contribution)} sub="per month" />
            <Stat label="Required" value={rupeesCompact(forecast.required_monthly_contribution)} sub="per month" />
            <Stat
              label="Gap"
              value={forecast.contribution_gap > 0 ? rupeesCompact(forecast.contribution_gap) : "None"}
              tone={forecast.contribution_gap > 0 ? "text-[var(--warning)]" : "text-[var(--good)]"}
            />
          </div>
        </CardBody>
      </Card>

      <Card className="rise">
        <CardHeader
          title="Scenarios"
          subtitle="A range, not a number. The spread uses the standard error of the average annual return over this horizon, so it narrows as the horizon lengthens."
        />
        <CardBody>
          <div className="space-y-2.5">
            {Object.entries(forecast.scenarios).map(([label, scenario]) => (
              <div key={label}
                   className="flex items-center justify-between gap-3 rounded-[8px] border border-[var(--hairline)] bg-[var(--surface-1)] px-3.5 py-2.5">
                <div>
                  <div className="text-[12.5px] capitalize text-[var(--ink-primary)]">{label}</div>
                  <div className="tabular text-[11px] text-[var(--ink-muted)]">
                    {percent(scenario.annual_return, 2)} a year
                  </div>
                </div>
                <div className="text-right">
                  <div className="tabular text-[13.5px] text-[var(--ink-primary)]">
                    {rupeesCompact(scenario.projected_value)}
                  </div>
                  <div className="tabular text-[11px] text-[var(--ink-muted)]">
                    {scenario.funding_ratio !== null ? percent(scenario.funding_ratio, 0) : "—"} funded
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardBody>
      </Card>

      <Card className="rise">
        <CardHeader title="Assumptions" />
        <CardBody>
          <Assumptions
            items={[
              ["Expected return", percent(Number(forecast.assumptions.expected_annual_return ?? 0), 2)],
              ["Return estimated from", String(estimate?.source ?? "—")],
              ["Return standard error", percent(Number(forecast.assumptions.return_standard_error ?? 0), 2)],
              ["Contribution timing", String(forecast.assumptions.contribution_timing ?? "—")],
              ["Compounding", String(forecast.assumptions.compounding ?? "—")],
              ["Contribution source", String(forecast.assumptions.contribution_source ?? "—")],
            ]}
          />
          {typeof estimate?.note === "string" && (
            <p className="mt-3 text-[11.5px] leading-relaxed text-[var(--ink-muted)]">{estimate.note}</p>
          )}
          <p className="mt-3 text-[11.5px] leading-relaxed text-[var(--ink-muted)]">
            {String(forecast.assumptions.current_amount_source ?? "")}
          </p>
          <p className="mt-3 rounded-[7px] border border-[var(--accent-dim)] bg-[color-mix(in_oklab,var(--accent)_8%,transparent)] px-3 py-2 text-[11.5px] leading-relaxed text-[var(--accent)]">
            {String(forecast.assumptions.note ?? "")}
          </p>
        </CardBody>
      </Card>
    </div>
  );
}
