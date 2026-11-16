"use client";

import Link from "next/link";
import { api } from "@/lib/api";
import { useApi } from "@/lib/auth";
import { percent, rupees, rupeesCompact, shortDate, toneFor } from "@/lib/format";
import {
  Badge, Card, CardBody, CardHeader, Empty, ErrorNote, Meter, Spinner, Stat,
} from "@/components/ui";
import { PageHead } from "@/components/ui/shell";
import { AllocationDonut, CumulativeReturnChart } from "@/components/charts";

export default function OverviewPage() {
  const portfolio = useApi(() => api.portfolio(), []);
  const health = useApi(() => api.healthScore(), []);
  const analytics = useApi(() => api.analytics().catch(() => null), []);
  const goals = useApi(() => api.goals(), []);

  if (portfolio.loading) return <Spinner label="Valuing your portfolio…" />;
  if (portfolio.error) return <ErrorNote message={portfolio.error} />;

  const summary = portfolio.data;
  if (!summary || summary.n_holdings === 0) {
    return (
      <>
        <PageHead title="Overview" lede="Your wealth at a glance." />
        <Card>
          <Empty
            title="No holdings yet"
            body="Import a CSV of your holdings, or add a few by hand, and every page here fills in: allocation, risk, concentration, goals and the health score."
            action={{ label: "Import holdings", href: "/import" }}
          />
        </Card>
      </>
    );
  }

  const score = health.data;
  const activeGoals = (goals.data ?? []).filter((g) => g.status === "active");

  return (
    <>
      <PageHead
        title="Overview"
        lede="Your wealth at a glance, priced against real Indian market history."
        aside={
          summary.as_of && (
            <Badge tone="neutral">Priced to {shortDate(summary.as_of)}</Badge>
          )
        }
      />

      {/* ── headline figures ── */}
      <div className="rise grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card><CardBody>
          <Stat
            label="Total value"
            value={rupeesCompact(summary.total_value)}
            sub={rupees(summary.total_value)}
          />
        </CardBody></Card>

        <Card><CardBody>
          <Stat
            label="Unrealised gain"
            value={rupeesCompact(summary.unrealized_gain)}
            tone={toneFor(summary.unrealized_gain)}
            sub={`${percent(summary.unrealized_gain_pct, 2, true)} on ${rupeesCompact(summary.total_cost)} invested`}
          />
        </CardBody></Card>

        <Card><CardBody>
          <Stat
            label="Holdings"
            value={summary.n_holdings}
            sub={`across ${summary.n_sectors} sectors`}
          />
        </CardBody></Card>

        <Card><CardBody>
          {score ? (
            <>
              <Stat
                label="Health score"
                value={`${score.total.toFixed(0)}`}
                sub={score.grade}
              />
              <div className="mt-3"><Meter value={score.total} /></div>
            </>
          ) : (
            <Stat label="Health score" value="—" sub={health.loading ? "calculating" : "unavailable"} />
          )}
        </CardBody></Card>
      </div>

      {/* ── allocation + performance ── */}
      <div className="mt-5 grid gap-5 lg:grid-cols-[0.85fr_1.15fr]">
        <Card className="rise">
          <CardHeader
            title="Asset allocation"
            subtitle="Where your money actually sits today."
          />
          <CardBody>
            <AllocationDonut data={summary.allocation_by_class} />
          </CardBody>
        </Card>

        <Card className="rise">
          <CardHeader
            title="Cumulative return"
            subtitle="Current holdings valued back through history, against the NIFTY 50."
            action={
              <Link href="/risk" className="text-[12px] text-[var(--accent)] underline-offset-2 hover:underline">
                Risk detail
              </Link>
            }
          />
          <CardBody>
            {analytics.loading && <Spinner />}
            {!analytics.loading && !analytics.data && (
              <p className="py-10 text-center text-[13px] text-[var(--ink-secondary)]">
                Not enough overlapping price history across these holdings yet.
              </p>
            )}
            {analytics.data && (
              <CumulativeReturnChart
                dates={analytics.data.series.dates}
                portfolio={analytics.data.series.cumulative_return}
                benchmark={analytics.data.series.benchmark_cumulative_return}
              />
            )}
          </CardBody>
        </Card>
      </div>

      {/* ── holdings + goals ── */}
      <div className="mt-5 grid gap-5 lg:grid-cols-[1.15fr_0.85fr]">
        <Card className="rise">
          <CardHeader title="Largest holdings" subtitle="By current market value." />
          <div className="overflow-x-auto">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="border-b border-[var(--hairline)] text-left text-[11px] uppercase tracking-[0.07em] text-[var(--ink-muted)]">
                  <th className="px-5 py-2.5 font-medium">Symbol</th>
                  <th className="px-3 py-2.5 text-right font-medium">Value</th>
                  <th className="px-3 py-2.5 text-right font-medium">Weight</th>
                  <th className="px-5 py-2.5 text-right font-medium">Gain</th>
                </tr>
              </thead>
              <tbody>
                {summary.top_holdings.map((holding) => (
                  <tr key={holding.id} className="border-b border-[var(--hairline)] last:border-0 hover:bg-[var(--surface-3)]/40">
                    <td className="px-5 py-2.5">
                      <div className="font-medium text-[var(--ink-primary)]">{holding.symbol}</div>
                      <div className="text-[11px] text-[var(--ink-muted)]">{holding.sector ?? holding.asset_class}</div>
                    </td>
                    <td className="tabular px-3 py-2.5 text-right">{rupeesCompact(holding.market_value)}</td>
                    <td className="tabular px-3 py-2.5 text-right text-[var(--ink-secondary)]">
                      {percent(holding.weight ?? 0, 1)}
                    </td>
                    <td className={`tabular px-5 py-2.5 text-right ${toneFor(holding.unrealized_gain_pct)}`}>
                      {percent(holding.unrealized_gain_pct ?? 0, 1, true)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card className="rise">
          <CardHeader
            title="Goals"
            subtitle={activeGoals.length ? "Progress toward each target." : undefined}
            action={
              <Link href="/goals" className="text-[12px] text-[var(--accent)] underline-offset-2 hover:underline">
                All goals
              </Link>
            }
          />
          <CardBody className="space-y-4">
            {goals.loading && <Spinner />}
            {!goals.loading && activeGoals.length === 0 && (
              <p className="py-6 text-center text-[13px] text-[var(--ink-secondary)]">
                No goals set. Adding one lets the platform judge the portfolio
                against what it is actually for.
              </p>
            )}
            {activeGoals.slice(0, 4).map((goal) => (
              <div key={goal.id}>
                <div className="flex items-baseline justify-between gap-3">
                  <span className="truncate text-[13px] text-[var(--ink-primary)]">{goal.name}</span>
                  <span className="tabular shrink-0 text-[12px] text-[var(--ink-secondary)]">
                    {percent(goal.progress_fraction, 0)}
                  </span>
                </div>
                <div className="mt-1.5">
                  <Meter value={goal.progress_fraction * 100} color="var(--series-3)" />
                </div>
                <div className="tabular mt-1 text-[11px] text-[var(--ink-muted)]">
                  {rupeesCompact(goal.current_amount)} of {rupeesCompact(goal.target_amount)}
                  {" · by "}{shortDate(goal.target_date)}
                </div>
              </div>
            ))}
          </CardBody>
        </Card>
      </div>

      {score && (
        <Card className="rise mt-5">
          <CardHeader title="What the score says" subtitle={score.summary} />
          <CardBody>
            <ul className="grid gap-2.5 sm:grid-cols-2">
              {score.components
                .filter((c) => c.score !== null)
                .sort((a, b) => (a.score ?? 0) - (b.score ?? 0))
                .slice(0, 4)
                .map((component) => (
                  <li key={component.name} className="rounded-[8px] border border-[var(--hairline)] bg-[var(--surface-1)] p-3">
                    <div className="flex items-baseline justify-between gap-2">
                      <span className="text-[12.5px] font-medium capitalize text-[var(--ink-primary)]">
                        {component.name.replace(/_/g, " ")}
                      </span>
                      <span className="tabular text-[12.5px] text-[var(--ink-secondary)]">
                        {component.score?.toFixed(0)}/100
                      </span>
                    </div>
                    <p className="mt-1.5 text-[11.5px] leading-relaxed text-[var(--ink-secondary)]">
                      {component.reason}
                    </p>
                  </li>
                ))}
            </ul>
          </CardBody>
        </Card>
      )}
    </>
  );
}
