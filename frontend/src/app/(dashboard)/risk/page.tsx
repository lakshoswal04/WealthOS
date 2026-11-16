"use client";

import { api } from "@/lib/api";
import { useApi } from "@/lib/auth";
import { percent, ratio, shortDate } from "@/lib/format";
import {
  Assumptions, Badge, Card, CardBody, CardHeader, Empty, ErrorNote, Spinner, Stat,
} from "@/components/ui";
import { PageHead } from "@/components/ui/shell";
import { CorrelationHeatmap, DrawdownChart, RiskReturnScatter } from "@/components/charts";

export default function RiskPage() {
  const risk = useApi(() => api.risk(), []);
  const concentration = useApi(() => api.concentration(), []);

  if (risk.loading) return <Spinner label="Computing risk metrics…" />;
  if (risk.error) {
    return (
      <>
        <PageHead title="Risk" lede="How much this portfolio moves, and how far it has fallen." />
        <Card><Empty title="Not enough history" body={risk.error}
                     action={{ label: "Import holdings", href: "/import" }} /></Card>
      </>
    );
  }
  if (!risk.data) return null;

  const { summary, drawdown, correlation, risk_return_scatter, assumptions } = risk.data;
  const conc = concentration.data;

  return (
    <>
      <PageHead
        title="Risk"
        lede="Measured on the holdings you have today, carried back through real market history."
        aside={<Badge tone="neutral">{summary.observations.toLocaleString("en-IN")} observations</Badge>}
      />

      <div className="rise grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card><CardBody>
          <Stat label="Volatility" value={percent(summary.annualized_volatility, 2)}
                sub="annualised standard deviation" />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Sharpe ratio" value={ratio(summary.sharpe_ratio)}
                sub={`excess return per unit of risk, at ${percent(summary.risk_free_rate, 0)} risk-free`} />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Max drawdown" value={percent(summary.max_drawdown, 2)}
                tone="text-[#ff8f8f]" sub="worst peak-to-trough fall" />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Beta" value={ratio(summary.beta)}
                sub="sensitivity to the NIFTY 50" />
        </CardBody></Card>
      </div>

      <div className="mt-5 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card><CardBody>
          <Stat label="Sortino ratio" value={ratio(summary.sortino_ratio)}
                sub="return per unit of downside risk only" />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Calmar ratio" value={ratio(summary.calmar_ratio)}
                sub="return against the worst drawdown" />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Value at Risk (95%)" value={percent(summary.var_95, 2)}
                sub="on the worst 1 day in 20" />
        </CardBody></Card>
        <Card><CardBody>
          <Stat label="Expected shortfall" value={percent(summary.cvar_95, 2)}
                sub="average loss beyond that point" />
        </CardBody></Card>
      </div>

      <Card className="rise mt-5">
        <CardHeader
          title="Drawdown"
          subtitle={
            drawdown.peak_date
              ? `Worst fall of ${percent(drawdown.max_drawdown, 2)} from ${shortDate(drawdown.peak_date)} to ${shortDate(drawdown.trough_date)}${
                  drawdown.recovered
                    ? `, recovered by ${shortDate(drawdown.recovery_date)} after ${drawdown.drawdown_days} days.`
                    : ", not yet recovered."
                }`
              : undefined
          }
          action={
            drawdown.current_drawdown !== null && (
              <Badge tone={drawdown.current_drawdown < -0.1 ? "serious" : "neutral"}>
                Now {percent(drawdown.current_drawdown, 2)} below peak
              </Badge>
            )
          }
        />
        <CardBody>
          <DrawdownChart dates={drawdown.series.dates} drawdown={drawdown.series.drawdown} />
        </CardBody>
      </Card>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card className="rise">
          <CardHeader
            title="Risk against return"
            subtitle="Each holding's own annualised profile. Marker size is its weight in the portfolio."
          />
          <CardBody>
            <RiskReturnScatter points={risk_return_scatter} />
          </CardBody>
        </Card>

        <Card className="rise">
          <CardHeader
            title="Correlation"
            subtitle={
              correlation?.average_pairwise !== undefined
                ? `Average pairwise correlation ${ratio(correlation.average_pairwise, 2)}. Holdings that move together diversify less than their number suggests.`
                : undefined
            }
          />
          <CardBody>
            {correlation?.symbols?.length ? (
              <CorrelationHeatmap symbols={correlation.symbols} matrix={correlation.matrix} />
            ) : (
              <p className="py-8 text-center text-[13px] text-[var(--ink-secondary)]">
                At least two holdings with overlapping history are needed.
              </p>
            )}
          </CardBody>
        </Card>
      </div>

      {conc && (
        <Card className="rise mt-5">
          <CardHeader
            title="Concentration"
            subtitle="A portfolio is not diversified merely because it holds many things."
          />
          <CardBody>
            <div className="grid gap-4 sm:grid-cols-4">
              <Stat label="Holdings" value={conc.n_holdings} />
              <Stat label="Effective holdings" value={conc.effective_holdings.toFixed(1)}
                    hint="1 / HHI — how many equally weighted positions this behaves like" />
              <Stat label="Largest position" value={percent(conc.top_1_weight, 1)}
                    sub={conc.largest_holding ?? undefined} />
              <Stat label="Top five" value={percent(conc.top_5_weight, 1)} />
            </div>
            <ul className="mt-5 space-y-2">
              {conc.interpretation.map((note) => (
                <li key={note} className="flex gap-2.5 text-[13px] leading-relaxed text-[var(--ink-secondary)]">
                  <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-[var(--accent)]" />
                  {note}
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>
      )}

      <Card className="rise mt-5">
        <CardHeader title="How these were computed"
                    subtitle="A ratio cannot be reproduced without the assumptions behind it." />
        <CardBody>
          <Assumptions
            items={[
              ["Method", String(assumptions.method ?? "—")],
              ["Benchmark", String(assumptions.benchmark ?? "—")],
              ["Risk-free rate", percent(Number(assumptions.risk_free_rate ?? 0), 2)],
              ["Observations", String(assumptions.observations ?? "—")],
              ["Window", `${assumptions.start ?? "—"} to ${assumptions.end ?? "—"}`],
              ["Rebalancing", String(assumptions.rebalancing ?? "—")],
            ]}
          />
          {Array.isArray(assumptions.symbols_excluded) && assumptions.symbols_excluded.length > 0 && (
            <p className="mt-3 text-[11.5px] text-[var(--ink-muted)]">
              Excluded for insufficient overlapping history:{" "}
              {(assumptions.symbols_excluded as string[]).join(", ")}
            </p>
          )}
        </CardBody>
      </Card>
    </>
  );
}
